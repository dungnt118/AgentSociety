"""EvidenceAtlas Vendor Support Environment (https://atlas.demego.vn Public API v1)."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, ClassVar
from urllib.parse import urlparse

import httpx
from pydantic import Field

from agentsociety2.backend.services.urban_sim.crypto import validate_external_url
from agentsociety2.contrib.env._urban_events_sink import (
    append_urban_event,
    effective_caller_agent_id,
    make_vault_accessor,
)
from agentsociety2.env import EnvBase, tool
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

logger = get_logger()
_STATE_REL = "state/ENV_STATE.json"
_MAX_ATTACHMENT_BYTES = 1_500_000


_MIN_READY_SCREENSHOT_BYTES = 18_000


def _normalize_atlas_route(url_or_path: str | None) -> str:
    raw = str(url_or_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path if (parsed.scheme or parsed.netloc) else raw.split("?", 1)[0]).strip()
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def naturalize_support_question(question: str, role_title: str = "") -> str:
    """Chuẩn hóa câu hỏi gửi Đội ngũ CSKH Thần Nông về giọng văn tự nhiên người-với-người."""
    original = str(question or "").strip()
    if not original:
        return ""
    text = original

    # 1. Tước phần mệnh lệnh điều khiển rò rỉ từ ask_env ("Hỏi CSKH EvidenceAtlas về ...", "Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua ask_atlas_support: ...")
    text = re.sub(
        r"^(?:hãy\s+)?(?:hỏi|nhắn(?:\s+hỏi)?|gửi(?:\s+câu\s+hỏi)?(?:\s+(?:tới|cho))?)\s+"
        r"(?:(?:bộ\s+phận|đội(?:\s+ngũ)?)\s+hỗ\s+trợ(?:\s*/\s*cskh\s+thần\s+nông)?|cskh\s+thần\s+nông|(?:(?:bộ\s+phận\s+|đội\s+ngũ\s+)?(?:cskh\s+)?(?:evidence\s*atlas|atlas)))"
        r"(?:\s+qua\s+ask_atlas_support)?(?:\s+về)?\s*[:,-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(xin\s+chào|chào)\s+(?:bộ\s+phận\s+|đội\s+ngũ\s+)?(?:cskh\s+)?(?:evidence\s*atlas|atlas)\b\s*([,;:]?)\s*",
        lambda m: f"{m.group(1)}{m.group(2) or ','} ",
        text,
        flags=re.IGNORECASE,
    )

    # 2. Thay thế mã định danh nội bộ kiểu "chức danh agent_id 9" / "agent_id=9" bằng chức danh thật
    clean_role = str(role_title or "").strip()
    if clean_role:
        text = re.sub(
            r"\b(?:chức\s+danh|vai\s+trò)\s+agent[_\s-]*id\s*[:=]?\s*\d+\b",
            f"vai trò {clean_role}",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\bagent[_\s-]*id\s*[:=]?\s*\d+\b", clean_role, text, flags=re.IGNORECASE)
    else:
        text = re.sub(r"\bagent[_\s-]*id\s*[:=]?\s*\d+\b", "", text, flags=re.IGNORECASE)

    # 3. Thay thế tên công cụ / hệ thống nội bộ còn sót bằng cách gọi tự nhiên
    text = re.sub(r"\bcskh\s+evidence\s*atlas\b", "bộ phận hỗ trợ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bevidence\s*atlas\b", "bộ phận hỗ trợ", text, flags=re.IGNORECASE)

    # 4. Loại bỏ các câu/mệnh đề ra lệnh kiểu chatbot hoặc meta-screenshot
    meta_patterns = [
        r"(?:^|[.!?;\n]\s*)(?:vui\s+lòng|hãy|xin)\s+trả\s+lời\s+ngắn\s+gọn\s+(?:bằng\s+tiếng\s+việt)?[^.!?\n]*[.!?]?",
        r"(?:^|[.!?;\n]\s*)(?:yêu\s+cầu|vui\s+lòng|hãy|xin|nếu\s+có\s+thể\s*,?\s*xin|nếu\s+hệ\s+thống\s+hỗ\s+trợ\s*,?\s*xin|tôi\s+có\s+thể)?\s*(?:đính\s+kèm|gửi\s+kèm|xem\s+kèm|kèm)\s+ảnh\s+(?:chụp\s+)?màn\s+hình[^.!?\n]*[.!?]?",
        r"(?:^|[.!?;\n]\s*)đính\s+kèm\s+ảnh\s+(?:chụp\s+)?màn\s+hình[^.!?\n]*[.!?]?",
        r"\s*[,;]\s*(?:kèm|đính\s+kèm)\s+ảnh\s+(?:chụp\s+)?màn\s+hình[^.!?\n]*(?=[.!?]|$)",
    ]
    for pat in meta_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # 5. Dọn khoảng trắng, dấu câu thừa
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    text = text.strip(" \t\r\n,;:-")
    if not text:
        return original
    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


class EvidenceAtlasSupportEnv(EnvBase):
    """Kênh trao đổi với Đội ngũ hỗ trợ / CSKH Thần Nông dành cho nhân sự BQL dùng phần mềm từ con số 0."""

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("bot_session_id", "TEXT"),
        ColumnDef("total_asks", "INTEGER"),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_atlas_asks", "INTEGER"),
        ColumnDef("rate_limited_retries", "INTEGER"),
    ]

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        return True

    @classmethod
    def description(cls) -> str:
        return (
            "Kênh trao đổi với Đội ngũ hỗ trợ / CSKH Thần Nông (giao tiếp người với người): "
            "giải đáp quy trình nghiệp vụ và cách thao tác phần mềm QLTN khi nhân sự BQL gặp vướng mắc."
        )

    @classmethod
    def skill_dirs(cls) -> list:
        return []

    def __init__(
        self,
        allowed_agent_ids: list[int] | None = None,
        secrets_vault_path: str | None = None,
        screenshots_dir: str | None = None,
        events_log_path: str | None = None,
        atlas_api_url: str = "https://atlas.demego.vn",
        actor_persona: str = "END_USER",
        source_mode: str = "FEDERATED_AUTO",
        attach_screenshot_on_ask: bool = False,
        quota_per_min: int = 25,
        max_asks_per_tick: int = 2,
        async_dispatch_after_sec: float = 6.0,
        personas_meta: dict[str, dict[str, str]] | None = None,
    ):
        super().__init__()
        self._allowed_ids: set[int] = {int(x) for x in (allowed_agent_ids or [])}
        self._screenshots_dir = Path(screenshots_dir).resolve() if screenshots_dir else None
        self._events_log_path = events_log_path
        self._atlas_api_url = str(atlas_api_url or "https://atlas.demego.vn").strip().rstrip("/")
        self._actor_persona = str(actor_persona or "END_USER").upper()
        self._source_mode = str(source_mode or "FEDERATED_AUTO").upper()
        self._attach_screenshot_on_ask = bool(attach_screenshot_on_ask)
        self._quota_per_min = max(1, min(int(quota_per_min or 25), 30))
        self._max_asks_per_tick = max(1, int(max_asks_per_tick or 2))
        self._async_dispatch_after_sec = max(0.05, float(async_dispatch_after_sec))
        self._personas_meta = {int(k): dict(v) for k, v in (personas_meta or {}).items()}

        # Private secret accessor closure (FND-QA-03)
        self._vault_accessor = make_vault_accessor(secrets_vault_path)

        self._rate_lock = asyncio.Lock()
        self._inflight_sem = asyncio.Semaphore(3)
        self._request_timestamps: deque[float] = deque()
        self._agent_locks: dict[int, asyncio.Lock] = {}

        self._bot_sessions: dict[int, str] = {}
        self._qa_history: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._unread_replies: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._pending_tickets: dict[str, dict[str, Any]] = {}
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._next_ticket_id = 1
        self._asks_in_current_tick: dict[int, int] = defaultdict(int)
        self._total_asks_by_agent: dict[int, int] = defaultdict(int)
        self._rate_limit_retries = 0
        self._step_counter = 0

    def _agent_lock(self, agent_id: int) -> asyncio.Lock:
        aid = int(agent_id)
        if aid not in self._agent_locks:
            self._agent_locks[aid] = asyncio.Lock()
        return self._agent_locks[aid]

    def _agent_meta(self, agent_id: int) -> tuple[str, str]:
        m = self._personas_meta.get(int(agent_id), {})
        return str(m.get("full_name") or f"BQL-{agent_id}"), str(m.get("role_title") or "")

    async def _acquire_rate_slot(self) -> None:
        while True:
            async with self._rate_lock:
                now = time.monotonic()
                while self._request_timestamps and (now - self._request_timestamps[0]) >= 60.0:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < self._quota_per_min:
                    self._request_timestamps.append(now)
                    return
                wait_sec = max(0.2, 60.1 - (now - self._request_timestamps[0]))
            await asyncio.sleep(min(wait_sec, 10.0))

    async def to_workspace(self, workspace_path=None) -> None:
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            return
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "bot_sessions": {str(k): v for k, v in self._bot_sessions.items()},
                    "qa_history": {str(k): v[-10:] for k, v in self._qa_history.items()},
                    "unread_replies": {str(k): v[-10:] for k, v in self._unread_replies.items()},
                    "next_ticket_id": self._next_ticket_id,
                    "total_asks_by_agent": {str(k): v for k, v in self._total_asks_by_agent.items()},
                    "rate_limit_retries": self._rate_limit_retries,
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._bot_sessions = {int(k): str(v) for k, v in (state.get("bot_sessions") or {}).items()}
        self._qa_history = defaultdict(
            list, {int(k): list(v) for k, v in (state.get("qa_history") or {}).items()}
        )
        self._unread_replies = defaultdict(
            list, {int(k): list(v) for k, v in (state.get("unread_replies") or {}).items()}
        )
        self._next_ticket_id = max(1, int(state.get("next_ticket_id") or 1))
        self._total_asks_by_agent = defaultdict(
            int, {int(k): int(v) for k, v in (state.get("total_asks_by_agent") or {}).items()}
        )
        self._rate_limit_retries = int(state.get("rate_limit_retries") or 0)
        self._step_counter = int(state.get("step_counter") or 0)
        return True

    async def close(self) -> None:
        """Gracefully settle or cancel in-flight Atlas background ticket tasks on shutdown."""
        pending = [t for t in list(self._bg_tasks) if not t.done()]
        if not pending:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=3.0)
        except TimeoutError:
            for t in pending:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    def _build_latest_screenshot_attachment(self, agent_id: int, route_hint: str | None) -> list[dict[str, Any]]:
        if self._screenshots_dir is None:
            return []
        aid = int(agent_id)
        latest = self._screenshots_dir / f"agent_{aid}_latest.jpg"
        if not latest.is_file():
            return []

        meta_path = self._screenshots_dir / f"agent_{aid}_latest.meta.json"
        meta_verified_ready = False
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = None
            if not isinstance(meta, dict):
                return []
            if str(meta.get("capture_status") or "").upper() != "READY":
                logger.info(
                    "Skipping Atlas screenshot attachment for agent %d: capture_status=%s",
                    aid,
                    meta.get("capture_status"),
                )
                return []
            if route_hint:
                norm_hint = _normalize_atlas_route(route_hint)
                norm_img = _normalize_atlas_route(
                    meta.get("latest_image_route_path") or meta.get("latest_image_url")
                )
                if norm_img and norm_hint and norm_hint != norm_img:
                    logger.info(
                        "Skipping Atlas screenshot attachment for agent %d: route mismatch (%s != %s)",
                        aid,
                        norm_hint,
                        norm_img,
                    )
                    return []
            meta_verified_ready = True

        raw = latest.read_bytes()
        if len(raw) == 0 or len(raw) > _MAX_ATTACHMENT_BYTES:
            return []
        if not meta_verified_ready and len(raw) < _MIN_READY_SCREENSHOT_BYTES:
            logger.info(
                "Skipping Atlas screenshot attachment for agent %d: unverified small image (%dB < %dB)",
                aid,
                len(raw),
                _MIN_READY_SCREENSHOT_BYTES,
            )
            return []
        b64 = base64.b64encode(raw).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"
        if len(data_url) > 2_500_000:
            return []
        return [
            {
                "attachment_id": f"att_agent_{aid}",
                "file_name": latest.name,
                "mime_type": "image/jpeg",
                "size_bytes": len(raw),
                "data_url_preview": data_url,
                "step_order": 1,
                "observed_route_hint": route_hint,
            }
        ]

    @tool(readonly=True, kind="observe")
    async def observe_atlas_support(self, agent_id: int) -> dict[str, Any]:
        """Quan sát lịch sử hỏi đáp CSKH EvidenceAtlas, thư trả lời mới và các ticket đang chờ phản hồi."""
        aid = effective_caller_agent_id(agent_id)
        if aid not in self._allowed_ids:
            return {"agent_id": aid, "support_available": False}
        unread = list(self._unread_replies.pop(aid, []))
        pending = [
            {
                "ticket_id": t["ticket_id"],
                "question": t["question"],
                "created_at": t["created_at"],
            }
            for t in self._pending_tickets.values()
            if int(t.get("agent_id", -1)) == aid
        ]
        return {
            "agent_id": aid,
            "support_available": True,
            "bot_session_id": self._bot_sessions.get(aid),
            "unread_replies": unread,
            "pending_tickets": pending,
            "recent_qa": self._qa_history.get(aid, [])[-3:],
            "asks_remaining_this_tick": max(0, self._max_asks_per_tick - self._asks_in_current_tick.get(aid, 0)),
        }

    @tool(readonly=True)
    async def get_recent_support_qa(self, agent_id: int, limit: int = 5) -> dict[str, Any]:
        """Đọc lại các câu hỏi & giải đáp CSKH trước đó của mình để không hỏi lặp."""
        aid = effective_caller_agent_id(agent_id)
        if aid not in self._allowed_ids:
            return {"ok": False, "error": "ACCESS_DENIED: Cư dân không sử dụng cổng CSKH nội bộ."}
        return {
            "ok": True,
            "bot_session_id": self._bot_sessions.get(aid),
            "items": self._qa_history.get(aid, [])[-max(1, min(int(limit), 10)):],
        }

    @tool(readonly=False)
    async def ask_atlas_support(
        self,
        agent_id: int,
        question: Annotated[
            str,
            Field(
                description=(
                    "Nội dung nhắn hỏi gửi tới Đội ngũ hỗ trợ / CSKH Thần Nông (giao tiếp người với người, "
                    "phía tiếp nhận có thể gồm cả chuyên viên và trợ lý). "
                    "BẮT BUỘC viết bằng tiếng Việt tự nhiên như một nhân sự BQL thật đang hỏi đồng nghiệp/CSKH về vướng mắc công việc "
                    "(đi thẳng vào vấn đề, ví dụ: 'Cho mình hỏi quy trình trên QLTN cho Trưởng ca An ninh: cách vào mục xử lý sự vụ an ninh/bãi xe...'). "
                    "TUYỆT ĐỐI KHÔNG chép tiền tố mệnh lệnh như 'Hỏi CSKH EvidenceAtlas về...', KHÔNG nhắc tên 'EvidenceAtlas', 'bot' hay 'agent_id', "
                    "KHÔNG thêm câu ra lệnh định dạng kiểu bot như 'Vui lòng trả lời ngắn gọn bằng tiếng Việt', "
                    "và KHÔNG viết 'đính kèm ảnh chụp màn hình' vào câu hỏi (hãy dùng tham số attach_screenshot=True nếu muốn gửi kèm ảnh)."
                )
            ),
        ],
        current_url: str = "",
        screen_summary: str = "",
        attach_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông về cách thao tác phần mềm QLTN (giao tiếp tự nhiên giữa người với người)."""
        aid = effective_caller_agent_id(agent_id)
        if aid not in self._allowed_ids:
            return {
                "ok": False,
                "error": f"ACCESS_DENIED: Agent {aid} thuộc nhóm Cư dân, không được gọi cổng CSKH BQL.",
            }
        q_raw = str(question or "").strip()
        if not q_raw:
            return {"ok": False, "error": "Câu hỏi gửi CSKH không được để trống."}
        name, role = self._agent_meta(aid)
        q_clean = naturalize_support_question(q_raw, role_title=role)

        if self._asks_in_current_tick.get(aid, 0) >= self._max_asks_per_tick:
            return {
                "ok": False,
                "error": f"TICK_QUOTA_EXCEEDED: Đã đạt tối đa {self._max_asks_per_tick} lượt hỏi CSKH trong bước này. Hãy dùng hướng dẫn đã nhận hoặc tiếp tục ở bước sau.",
            }

        vault = self._vault_accessor()
        atlas_sec = vault.get("atlas") or {}
        base_url = validate_external_url(str(atlas_sec.get("atlas_api_url") or self._atlas_api_url)).rstrip("/")
        api_key = str(atlas_sec.get("atlas_api_key") or "").strip()
        if not api_key:
            return {
                "ok": False,
                "error": "MISSING_ATLAS_API_KEY: Chưa cấu hình API Key EvidenceAtlas trong DB.",
            }

        route_hint: str | None = None
        if current_url.strip():
            route_hint = _normalize_atlas_route(current_url.strip()) or None

        full_question = q_clean
        if screen_summary.strip():
            full_question = f"{q_clean}\n\nHiện tôi đang ở màn hình: {screen_summary.strip()[:500]}"

        existing_pending = [
            {
                "ticket_id": t["ticket_id"],
                "question": t["question"],
                "created_at": t["created_at"],
            }
            for t in self._pending_tickets.values()
            if int(t.get("agent_id", -1)) == aid
        ]
        if existing_pending:
            return {
                "ok": True,
                "status": "ALREADY_PENDING",
                "pending_tickets": existing_pending,
                "message": (
                    "Câu hỏi trước đó của bạn đang được Đội ngũ CSKH Thần Nông xử lý. "
                    "Hãy kiểm tra observe_atlas_support ở lượt sau và ngay bây giờ tiếp tục di chuyển thực địa "
                    "(move_to_checkpoint / move_to_zone với readonly=False) hoặc xử lý công việc trên QLTN."
                ),
            }

        ticket_id = f"ATL-{self._next_ticket_id:04d}"
        self._next_ticket_id += 1
        self._asks_in_current_tick[aid] = self._asks_in_current_tick.get(aid, 0) + 1
        ticket_meta: dict[str, Any] = {
            "ticket_id": ticket_id,
            "agent_id": aid,
            "question": q_clean[:200],
            "created_at": datetime.now(UTC).isoformat(),
            "dispatched_async": False,
        }
        self._pending_tickets[ticket_id] = ticket_meta

        existing_session = self._bot_sessions.get(aid)
        payload: dict[str, Any] = {
            "question": full_question,
            "actor_persona": str(atlas_sec.get("actor_persona") or self._actor_persona),
            "source_mode": str(atlas_sec.get("source_mode") or self._source_mode),
        }
        if existing_session:
            payload["bot_session_id"] = existing_session
        else:
            payload["create_new_session"] = True
        if route_hint:
            payload["explicit_route_hint"] = route_hint
        if attach_screenshot or self._attach_screenshot_on_ask:
            atts = self._build_latest_screenshot_attachment(aid, route_hint)
            if atts:
                payload["attachments"] = atts

        endpoint = f"{base_url}/api/v1/project/qa-bot/ask"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

        async def _execute_ticket() -> dict[str, Any]:
            try:
                async with self._agent_lock(aid):
                    cur_session = self._bot_sessions.get(aid) or existing_session
                    if cur_session:
                        payload["bot_session_id"] = cur_session
                        payload.pop("create_new_session", None)

                    resp_data: dict[str, Any] | None = None
                    last_error: str = ""
                    drop_attachments_next = False
                    async with self._inflight_sem:
                        async with httpx.AsyncClient(timeout=95.0) as client:
                            for attempt in range(2):
                                if drop_attachments_next and "attachments" in payload:
                                    # Fallback text-only chỉ khi Atlas gặp 502/504/timeout xử lý ảnh đính kèm
                                    payload.pop("attachments", None)
                                await self._acquire_rate_slot()
                                try:
                                    resp = await client.post(endpoint, headers=headers, json=payload)
                                except httpx.TimeoutException:
                                    last_error = "EvidenceAtlas timeout sau 95s"
                                    drop_attachments_next = True
                                    if attempt < 1:
                                        await asyncio.sleep(2)
                                        continue
                                    break
                                except httpx.RequestError as exc:
                                    last_error = f"Lỗi mạng kết nối EvidenceAtlas: {exc}"
                                    break

                                if resp.status_code == 429 or resp.status_code >= 500:
                                    self._rate_limit_retries += 1
                                    if resp.status_code in (502, 504):
                                        drop_attachments_next = True
                                    retry_after = resp.headers.get("Retry-After")
                                    delay = float(retry_after) if (retry_after and retry_after.isdigit()) else 3.0
                                    last_error = f"HTTP {resp.status_code}: {resp.text[:250]}"
                                    if attempt < 1:
                                        await asyncio.sleep(min(delay, 10.0))
                                        continue
                                    break

                                if resp.status_code in (401, 403):
                                    err_out = {
                                        "ok": False,
                                        "error": f"ATLAS_AUTH_ERROR HTTP {resp.status_code}: {resp.text[:300]}",
                                    }
                                    if ticket_meta.get("dispatched_async"):
                                        self._unread_replies[aid].append({"ticket_id": ticket_id, **err_out})
                                    return err_out
                                if resp.status_code >= 400:
                                    err_out = {
                                        "ok": False,
                                        "error": f"ATLAS_HTTP_{resp.status_code}: {resp.text[:300]}",
                                    }
                                    if ticket_meta.get("dispatched_async"):
                                        self._unread_replies[aid].append({"ticket_id": ticket_id, **err_out})
                                    return err_out

                                resp_data = resp.json()
                                break

                    if resp_data is None:
                        append_urban_event(
                            self._events_log_path,
                            stream="ATLAS",
                            agent_id=aid,
                            agent_name=name,
                            role_title=role,
                            action="ask_atlas_support",
                            summary=f"Lỗi hỏi Atlas [{ticket_id}]: {last_error[:120]}",
                            sim_time=self.t,
                            ok=False,
                            details={"ticket_id": ticket_id, "question": q_clean, "error": last_error},
                        )
                        err_out = {"ok": False, "error": last_error}
                        if ticket_meta.get("dispatched_async"):
                            self._unread_replies[aid].append(
                                {"ticket_id": ticket_id, "question": q_clean, **err_out}
                            )
                        return err_out

                    bot_sess_id = str(resp_data.get("bot_session_id") or cur_session or "")
                    if bot_sess_id:
                        self._bot_sessions[aid] = bot_sess_id

                    msg_obj = resp_data.get("assistant_message") or {}
                    answer_md = str(
                        msg_obj.get("question_or_answer_markdown")
                        or msg_obj.get("content")
                        or msg_obj.get("answer_markdown")
                        or resp_data.get("answer")
                        or json.dumps(resp_data, ensure_ascii=False)[:1500]
                    )
                    eval_target = resp_data.get("evaluation_target") or {
                        "message_id": resp_data.get("assistant_message_id"),
                        "session_id": bot_sess_id,
                        "source_kind": "QA_BOT",
                    }
                    self._total_asks_by_agent[aid] = self._total_asks_by_agent.get(aid, 0) + 1

                    record = {
                        "ok": True,
                        "ticket_id": ticket_id,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "bot_session_id": bot_sess_id,
                        "assistant_message_id": resp_data.get("assistant_message_id"),
                        "route_hint": route_hint,
                        "question": q_clean,
                        "answer": answer_md,
                        "evaluation_target": eval_target,
                        "mcp_used": bool(resp_data.get("mcp_used")),
                    }
                    self._qa_history[aid].append(record)
                    self._qa_history[aid] = self._qa_history[aid][-15:]
                    if ticket_meta.get("dispatched_async"):
                        self._unread_replies[aid].append(record)
                        self._unread_replies[aid] = self._unread_replies[aid][-15:]

                    append_urban_event(
                        self._events_log_path,
                        stream="ATLAS",
                        agent_id=aid,
                        agent_name=name,
                        role_title=role,
                        action="ask_atlas_support",
                        summary=f"{name} hỏi CSKH -> {answer_md[:140]}",
                        sim_time=self.t,
                        ok=True,
                        details=record,
                    )
                    return {
                        "ok": True,
                        "ticket_id": ticket_id,
                        "bot_session_id": bot_sess_id,
                        "assistant_message_id": resp_data.get("assistant_message_id"),
                        "answer": answer_md,
                        "evaluation_target": eval_target,
                        "hint": "Hãy ghi nhớ hướng dẫn từ đội ngũ hỗ trợ qua finish(memories=[...]) hoặc notes/atlas_guides.md rồi quay lại thao tác QLTN.",
                    }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err_out = {"ok": False, "error": f"ATLAS_INTERNAL_ERROR: {exc}"}
                if ticket_meta.get("dispatched_async"):
                    self._unread_replies[aid].append({"ticket_id": ticket_id, **err_out})
                return err_out
            finally:
                self._pending_tickets.pop(ticket_id, None)

        task = asyncio.create_task(_execute_ticket())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self._async_dispatch_after_sec)
        except TimeoutError:
            ticket_meta["dispatched_async"] = True
            return {
                "ok": True,
                "status": "QUEUED_AWAITING_REPLY",
                "ticket_id": ticket_id,
                "bot_session_id": existing_session or "",
                "message": (
                    f"Đã gửi câu hỏi [{ticket_id}] tới Đội ngũ hỗ trợ / CSKH Thần Nông và đang chờ phản hồi chuyên sâu "
                    "(giữ nguyên đầy đủ timeout 95s ở nền). Kết quả sẽ tự động gửi vào observe_atlas_support (unread_replies). "
                    "Trong lúc chờ, KHÔNG đứng yên — HÃY chuyển ngay sang di chuyển tuần tra/kiểm tra thực địa "
                    "(move_to_checkpoint / move_to_zone với readonly=False) hoặc tiếp tục tác nghiệp công việc khác."
                ),
            }

    @tool(readonly=False)
    async def rate_support_answer(
        self,
        agent_id: int,
        message_id: str,
        vote: str = "LIKE",
        reason: str = "",
        category: str = "OTHER",
    ) -> dict[str, Any]:
        """Gửi đánh giá LIKE/DISLIKE câu trả lời CSKH đồng bộ về EvidenceAtlas."""
        aid = effective_caller_agent_id(agent_id)
        if aid not in self._allowed_ids:
            return {"ok": False, "error": "ACCESS_DENIED"}
        v_norm = vote.strip().upper()
        if v_norm not in {"LIKE", "DISLIKE", "NEUTRAL"}:
            return {"ok": False, "error": "vote phải là LIKE, DISLIKE hoặc NEUTRAL"}
        vault = self._vault_accessor()
        atlas_sec = vault.get("atlas") or {}
        base_url = validate_external_url(str(atlas_sec.get("atlas_api_url") or self._atlas_api_url)).rstrip("/")
        api_key = str(atlas_sec.get("atlas_api_key") or "").strip()
        if not api_key:
            return {"ok": False, "error": "MISSING_ATLAS_API_KEY"}
        payload = {
            "message_id": message_id.strip(),
            "session_id": self._bot_sessions.get(aid, ""),
            "source_kind": "QA_BOT",
            "vote": v_norm,
            "reason": reason.strip(),
            **({"category": category} if v_norm == "DISLIKE" else {}),
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            await self._acquire_rate_slot()
            resp = await client.post(
                f"{base_url}/api/v1/project/agent-messages/feedback",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json=payload,
            )
        return {"ok": resp.status_code < 400, "status_code": resp.status_code, "body": resp.text[:300]}

    async def step(self, tick: int, t: datetime):
        self.t = t
        self._step_counter += 1
        self._asks_in_current_tick.clear()
        records = [
            {
                "agent_id": aid,
                "bot_session_id": self._bot_sessions.get(aid, ""),
                "total_asks": self._total_asks_by_agent.get(aid, 0),
            }
            for aid in sorted(self._allowed_ids)
        ]
        await self._write_agent_state_batch(self._step_counter, t, records)
        await self._write_env_state(
            self._step_counter,
            t,
            total_atlas_asks=sum(self._total_asks_by_agent.values()),
            rate_limited_retries=self._rate_limit_retries,
        )
