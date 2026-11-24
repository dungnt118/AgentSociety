#!/usr/bin/env python3
"""Serve the Daily Mobility interactive live dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from daily_mobility.tools.live_data import build_dashboard_payload

STATIC_DIR = TOOLS_DIR / "live_dashboard"
STATIC_ROUTES = {
    "/" + name: STATIC_DIR / name
    for name in ("index.html", "styles.css", "i18n.js", "app.js", "geo_map.js")
}
STATIC_ROUTES["/"] = STATIC_ROUTES["/index.html"]

_MAX_TRANSLATE_BODY_BYTES = 16 * 1024
_MAX_TRANSLATE_TEXT_LEN = 4000
_TRANSLATE_LOCK = threading.Lock()
_TRANSLATE_SYSTEM_PROMPT = (
    "Bạn là biên dịch viên chuyên về mô phỏng khoa học xã hội. "
    "Hãy dịch đoạn giải thích hành vi sau sang tiếng Việt tự nhiên, súc tích, chính xác. "
    "Giữ nguyên các mã định danh (như AOI 500026935, POI, giờ 09:30, tên đoạn kế hoạch như work_morning). "
    "Chỉ trả về bản dịch, không thêm chú thích."
)


def _translation_cache_path(run_dir: Path) -> Path:
    return run_dir / "translations_vi.json"


def _read_translation_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_translation_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _post_chat_completion(
    *,
    api_base: str,
    api_key: str,
    model: str,
    text: str,
) -> tuple[int, str, str]:
    resp = requests.post(
        f"{api_base}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        },
        timeout=25,
    )
    if resp.status_code != 200:
        return resp.status_code, "", resp.text[:300]
    payload = resp.json()
    choices = payload.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "").strip()
    if not content:
        return 502, "", "Empty translation response from model"
    return 200, content, ""


def _translate_to_vi(run_dir: Path, text: str, target_lang: str) -> tuple[int, dict[str, Any]]:
    cache_key = hashlib.sha256(f"{target_lang}:{text}".encode("utf-8")).hexdigest()
    cache_path = _translation_cache_path(run_dir)

    with _TRANSLATE_LOCK:
        cache = _read_translation_cache(cache_path)
        hit = cache.get(cache_key)
        if isinstance(hit, dict) and hit.get("translated"):
            return 200, {
                "translated": str(hit["translated"]),
                "cached": True,
                "model": hit.get("model"),
            }

    api_key = os.getenv("AGENTSOCIETY_LLM_API_KEY", "").strip()
    if not api_key:
        return 503, {"error": "AGENTSOCIETY_LLM_API_KEY is not configured for translation"}

    api_base = os.getenv("AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
    primary_model = os.getenv("DASHBOARD_TRANSLATE_MODEL", "gpt-5.4-nano").strip()
    fallback_model = os.getenv("AGENTSOCIETY_LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    if not primary_model:
        primary_model = fallback_model

    used_model = primary_model
    status, translated, err_detail = _post_chat_completion(
        api_base=api_base, api_key=api_key, model=primary_model, text=text
    )
    if status != 200 and 400 <= status < 500 and fallback_model != primary_model:
        used_model = fallback_model
        status, translated, err_detail = _post_chat_completion(
            api_base=api_base, api_key=api_key, model=fallback_model, text=text
        )

    if status != 200:
        return 503, {"error": f"Translation upstream failed ({status}): {err_detail}"}

    with _TRANSLATE_LOCK:
        cache = _read_translation_cache(cache_path)
        cache[cache_key] = {
            "source": text,
            "translated": translated,
            "target_lang": target_lang,
            "model": used_model,
        }
        _write_translation_cache(cache_path, cache)

    return 200, {
        "translated": translated,
        "cached": False,
        "model": used_model,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    run_dir: Path
    log_file: Path | None
    agent_id: int

    def log_message(self, format: str, *args) -> None:
        if self.path.startswith("/api/"):
            return

    def _send_json(self, payload: dict, status: HTTPStatus | int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        suffix = path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(suffix, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/api/live-state":
            try:
                qs = parse_qs(parsed.query)
                agent_id = self.agent_id
                if qs.get("agent_id"):
                    try:
                        agent_id = int(qs["agent_id"][0])
                    except ValueError:
                        logging.getLogger(__name__).debug("Malformed agent_id query param; using default")
                payload = build_dashboard_payload(
                    self.run_dir, self.log_file, agent_id=agent_id
                )
            except Exception as exc:
                logging.getLogger(__name__).exception("Could not build live dashboard state")
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(payload)
            return

        candidate = STATIC_ROUTES.get(route)
        if candidate is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_file(candidate)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route != "/api/translate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, HTTPStatus.BAD_REQUEST)
            return

        if length <= 0 or length > _MAX_TRANSLATE_BODY_BYTES:
            self._send_json({"error": "Request body empty or too large"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            raw_body = self.rfile.read(length)
            req = json.loads(raw_body.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            self._send_json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return

        if not isinstance(req, dict):
            self._send_json({"error": "Expected JSON object"}, HTTPStatus.BAD_REQUEST)
            return

        text = req.get("text")
        target_lang = str(req.get("target_lang") or "vi").strip().lower()
        if target_lang != "vi":
            self._send_json({"error": "Only target_lang='vi' is supported"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(text, str) or not text.strip():
            self._send_json({"error": "Field 'text' must be a non-empty string"}, HTTPStatus.BAD_REQUEST)
            return
        text = text.strip()
        if len(text) > _MAX_TRANSLATE_TEXT_LEN:
            self._send_json({"error": "Field 'text' exceeds max length"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            status_code, payload = _translate_to_vi(self.run_dir, text, target_lang)
        except Exception as exc:
            logging.getLogger(__name__).exception("Translation endpoint failed")
            self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self._send_json(payload, status_code)


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Mobility live web dashboard")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--agent-id", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    handler = type(
        "BoundDashboardHandler",
        (DashboardHandler,),
        {
            "run_dir": args.run_dir.resolve(),
            "log_file": args.log_file,
            "agent_id": args.agent_id,
        },
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Daily Mobility dashboard: {url}", flush=True)
    print(f"run-dir: {args.run_dir.resolve()}", flush=True)
    print(f"agent-id: {args.agent_id}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
