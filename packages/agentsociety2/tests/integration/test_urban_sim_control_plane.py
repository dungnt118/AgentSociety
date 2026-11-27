"""Integration tests (L1 Local) for Dynamic Urban Simulation Control Plane & Envs."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from agentsociety2.backend.app import app
from agentsociety2.backend.services.urban_sim.compiler import compile_run_from_db
from agentsociety2.backend.services.urban_sim.crypto import decrypt_secret
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimAtlasConfig,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.backend.services.urban_sim.lifecycle import UrbanSimLifecycleManager
from agentsociety2.backend.services.urban_sim.seed_mulberrylane import ensure_mulberrylane_seed
from agentsociety2.contrib.env.demego_web_portal import DemegoWebPortalEnv
from agentsociety2.contrib.env.evidence_atlas_support import EvidenceAtlasSupportEnv
from agentsociety2.contrib.env.urban_comm_incident import UrbanCommAndIncidentEnv
from agentsociety2.env.codegen_runtime import policy_bindings
from agentsociety2.env.router_base import RouterBase
from agentsociety2.env.router_react import ReActRouter
from agentsociety2.society.cli import ExperimentRunner
from agentsociety2.society.society import (
    LLM_STATS_JSON,
    SOCIETY_JSON,
    SOCIETY_STEP_JSON,
    STOP_REQUESTED_FILE,
    AgentSociety,
)


def _start_mock_server():
    """Spin up local HTTP server mocking EvidenceAtlas v1 + QLTN Web Portal."""
    state = {
        "ask_calls": 0,
        "ask_payloads": [],
        "feedback_payloads": [],
        "fail_first_429": True,
        "submitted_titles": [],
        "deleted_triggered": False,
    }
    lock = threading.Lock()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            return

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _send_json(self, code: int, payload: dict):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, code: int, html: str):
            raw = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path == "/api/v1/me":
                api_key = self.headers.get("X-API-KEY", "")
                if api_key != "atlas-secret-key-001":
                    self._send_json(401, {"error": "Invalid X-API-KEY"})
                    return
                self._send_json(
                    200,
                    {
                        "bound_project_id": "proj_ml_sandbox",
                        "project_name": "MulberryLane Sandbox KB",
                        "scopes": ["qa:ask", "feedback:write"],
                        "isolation_mode": "PROJECT_STRICT",
                    },
                )
                return

            if self.path.startswith("/qltn/tickets"):
                html = """<!doctype html><html><head><title>QLTN Tạo Phản Ánh</title></head><body>
                <h1>Tạo Phiếu Phản Ánh Cư Dân</h1>
                <button aria-label=""></button>
                <button>99+</button>
                <ul><li class="ant-menu-item"><a href="#requests" onclick="event.preventDefault(); document.getElementById('status').innerText='Opened: Phieu yeu cau';">Phiếu yêu cầu</a></li></ul>
                <form id="ticket-form" onsubmit="event.preventDefault(); document.getElementById('status').innerText='Saved: ' + document.getElementById('title').value;">
                  <input id="title" name="title" placeholder="Tiêu đề phản ánh" />
                  <textarea id="desc" name="description" placeholder="Nội dung sự cố"></textarea>
                  <button type="submit">Lưu phản ánh</button>
                </form>
                <button id="danger-btn" onclick="fetch('/qltn/bulk-delete', {method:'POST'})">Xóa tất cả dữ liệu</button>
                <div id="status"></div>
                </body></html>"""
                self._send_html(200, html)
                return

            if self.path.startswith("/qltn-pin"):
                html = """<!doctype html><html><head><title>QLTN MulberryLane PIN Login</title></head><body>
                <h1>Đăng nhập QLTN PIN</h1>
                <form onsubmit="event.preventDefault(); window.location.href='/qltn/tickets';">
                  <input placeholder="ten.ban@demego.vn" type="text" />
                  <div id="pin-wrap">
                    <input aria-label="OTP Input 1" type="text" />
                    <input aria-label="OTP Input 2" type="text" />
                    <input aria-label="OTP Input 3" type="text" />
                    <input aria-label="OTP Input 4" type="text" />
                    <input aria-label="OTP Input 5" type="text" />
                    <input aria-label="OTP Input 6" type="text" />
                  </div>
                  <button type="button" id="legacy-btn" onclick="document.getElementById('pin-wrap').innerHTML='<input type=password placeholder=&quot;Nhập mật khẩu&quot; />';">Mật khẩu cũ có chữ?</button>
                  <button type="submit">Đăng nhập</button>
                </form>
                </body></html>"""
                self._send_html(200, html)
                return

            # Default /qltn login page
            html = """<!doctype html><html><head><title>QLTN MulberryLane Login</title></head><body>
            <h1>Đăng nhập QLTN</h1>
            <form onsubmit="event.preventDefault(); window.location.href='/qltn/tickets';">
              <input name="username" type="text" placeholder="Tài khoản" />
              <input name="password" type="password" placeholder="Mật khẩu" />
              <button type="submit">Đăng nhập</button>
            </form>
            </body></html>"""
            self._send_html(200, html)

        def do_POST(self):  # noqa: N802
            if self.path == "/api/v1/project/qa-bot/ask":
                api_key = self.headers.get("X-API-KEY", "")
                if api_key != "atlas-secret-key-001":
                    self._send_json(401, {"error": "Unauthorized"})
                    return
                body = self._read_json()
                with lock:
                    state["ask_calls"] += 1
                    state["ask_payloads"].append(body)
                    if state["fail_first_429"]:
                        state["fail_first_429"] = False
                        self.send_response(429)
                        self.send_header("Retry-After", "0")
                        self.send_header("Content-Type", "application/json")
                        raw = b'{"error":"rate limit"}'
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                self._send_json(
                    200,
                    {
                        "bot_session_id": body.get("bot_session_id") or "sess_atlas_9001",
                        "assistant_message_id": "msg_atlas_9001",
                        "assistant_message": {
                            "question_or_answer_markdown": "Vào **Chăm sóc cư dân -> Phản ánh -> Tạo mới** và điền mã căn hộ."
                        },
                        "evaluation_target": {
                            "message_id": "msg_atlas_9001",
                            "session_id": body.get("bot_session_id") or "sess_atlas_9001",
                            "source_kind": "QA_BOT",
                        },
                        "mcp_used": True,
                    },
                )
                return

            if self.path == "/api/v1/project/agent-messages/feedback":
                body = self._read_json()
                with lock:
                    state["feedback_payloads"].append(body)
                self._send_json(200, {"ok": True})
                return

            if self.path == "/qltn/bulk-delete":
                with lock:
                    state["deleted_triggered"] = True
                self._send_json(200, {"ok": True})
                return

            self._send_json(404, {"error": "not found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state


def _client_headers(monkeypatch) -> dict[str, str]:
    monkeypatch.delenv("BACKEND_TOKEN", raising=False)
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_KEY", "sk-test-dummy-l1")
    return {"Origin": "http://127.0.0.1:5173"}


def test_l1_tc_01_seed_ssrf_atlas_and_map_upload(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)

    server, _ = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        with TestClient(app, base_url="http://127.0.0.1:8001") as client:
            r = client.get("/api/v1/urban-sim/projects", headers=headers)
            assert r.status_code == 200
            items = r.json()["items"]
            assert len(items) == 1
            proj = items[0]
            pid = proj["id"]
            assert proj["slug"] == "mulberrylane"
            assert proj["stats"]["total_personas"] == 22
            assert proj["stats"]["bql_count"] == 12
            assert proj["stats"]["resident_count"] == 10
            assert proj["stats"]["zones_count"] == 9

            # Idempotent second call
            r2 = client.get("/api/v1/urban-sim/projects", headers=headers)
            assert len(r2.json()["items"]) == 1

            # Ensure zero Beijing/MobilitySpace in generated init_config
            init_urban_sim_db(tmp_path)
            from sqlmodel import Session, select

            with Session(get_engine(tmp_path)) as sess:
                p_row = sess.get(UrbanSimProject, pid)
                personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == pid)).all())
                atlas = sess.get(UrbanSimAtlasConfig, pid)
                bundle = compile_run_from_db(
                    project=p_row,
                    personas=personas,
                    atlas=atlas,
                    zones=[],
                    run_dir=tmp_path / "compile_check",
                    workspace_root=tmp_path,
                )
            init_text = bundle.config_path.read_text(encoding="utf-8")
            assert "beijing" not in init_text.lower()
            assert "MobilitySpace" not in init_text

            # SSRF guard blocks 127.0.0.1 & link-local when flag off
            ssrf1 = client.post(
                f"/api/v1/urban-sim/projects/{pid}/atlas/test-connection",
                headers=headers,
                json={"atlas_api_url": f"{base_url}", "atlas_api_key": "atlas-secret-key-001"},
            )
            assert ssrf1.status_code == 400
            ssrf2 = client.put(
                f"/api/v1/urban-sim/projects/{pid}/atlas",
                headers=headers,
                json={"atlas_api_url": "http://169.254.169.254/latest/meta-data/"},
            )
            assert ssrf2.status_code == 400

            # Allow local test URL -> /api/v1/me reads bound_project_id & project_name
            monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
            ok_test = client.post(
                f"/api/v1/urban-sim/projects/{pid}/atlas/test-connection",
                headers=headers,
                json={"atlas_api_url": base_url, "atlas_api_key": "atlas-secret-key-001"},
            )
            assert ok_test.status_code == 200
            body = ok_test.json()
            assert body["ok"] is True
            assert body["bound_project_id"] == "proj_ml_sandbox"
            assert body["project_name"] == "MulberryLane Sandbox KB"
            assert body["scopes"] == ["qa:ask", "feedback:write"]

            # Upload SVG disguised as .png -> blocked 400
            bad_upload = client.post(
                f"/api/v1/urban-sim/projects/{pid}/zones/map-image",
                headers=headers,
                files={"file": ("evil.png", b"<svg onload=alert(1)></svg>", "image/png")},
            )
            assert bad_upload.status_code == 400

            # Upload valid PNG header bytes -> 200 & streams with nosniff
            valid_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00@\x00\x00\x00@\x08\x02\x00\x00\x00" + b"\x00" * 35
            ok_upload = client.post(
                f"/api/v1/urban-sim/projects/{pid}/zones/map-image",
                headers=headers,
                files={"file": ("floorplan.png", valid_png, "image/png")},
            )
            assert ok_upload.status_code == 200
            img_get = client.get(f"/api/v1/urban-sim/projects/{pid}/zones/map-image", headers=headers)
            assert img_get.status_code == 200
            assert img_get.headers.get("x-content-type-options") == "nosniff"
            assert img_get.content == valid_png
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_l1_tc_02_fernet_secrets_vault_isolation_and_masking(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_FERNET_KEY", raising=False)
    headers = _client_headers(monkeypatch)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        proj = client.get("/api/v1/urban-sim/projects", headers=headers).json()["items"][0]
        pid = proj["id"]
        personas = client.get(f"/api/v1/urban-sim/projects/{pid}/personas", headers=headers).json()["items"]
        bql_rep = next(p for p in personas if p["agent_id"] == 3)

        secret_pw = "SuperSecretBqlPass!2026"
        secret_atlas = "atlas-live-super-key-999"

        upd_p = client.patch(
            f"/api/v1/urban-sim/projects/{pid}/personas/{bql_rep['id']}",
            headers=headers,
            json={"login_username": "letan.mulberry@demego.vn", "login_password": secret_pw},
        )
        assert upd_p.status_code == 200
        assert upd_p.json()["persona"]["password_masked"] == "••••••"
        assert secret_pw not in upd_p.text

        upd_a = client.put(
            f"/api/v1/urban-sim/projects/{pid}/atlas",
            headers=headers,
            json={"atlas_api_url": "https://atlas.demego.vn", "atlas_api_key": secret_atlas},
        )
        assert upd_a.status_code == 200
        assert upd_a.json()["atlas"]["api_key_masked"] == "••••••"
        assert secret_atlas not in upd_a.text

        # GET never leaks secrets
        all_p = client.get(f"/api/v1/urban-sim/projects/{pid}/personas", headers=headers)
        assert secret_pw not in all_p.text
        assert "login_password_enc" not in all_p.text

        # Key persisted at .agentsociety/.fernet.key
        key_file = tmp_path / ".agentsociety" / ".fernet.key"
        assert key_file.is_file()

        from sqlmodel import Session, select

        with Session(get_engine(tmp_path)) as sess:
            p_row = sess.get(UrbanSimProject, pid)
            per_rows = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == pid)).all())
            atlas_row = sess.get(UrbanSimAtlasConfig, pid)
            assert decrypt_secret(atlas_row.atlas_api_key_enc, tmp_path) == secret_atlas

            run_dir = tmp_path / "urban_sim_runs" / "mulberrylane" / "urbrun_001_sec"
            bundle = compile_run_from_db(
                project=p_row,
                personas=per_rows,
                atlas=atlas_row,
                zones=[],
                run_dir=run_dir,
                workspace_root=tmp_path,
            )

        assert bundle.vault_path.is_file()
        for pub_file in (bundle.config_path, bundle.steps_path, bundle.prompt_overrides_path):
            txt = pub_file.read_text(encoding="utf-8")
            assert secret_pw not in txt
            assert secret_atlas not in txt

        # Verify CodeGenRouter __safe_getattr__ blocks private _vault_accessor
        web_env = DemegoWebPortalEnv(
            allowed_agent_ids=[3],
            secrets_vault_path=str(bundle.vault_path),
            screenshots_dir=str(run_dir / "artifacts" / "screenshots"),
        )
        policy = (
            ("ALLOWED_BUILTINS", frozenset({"len", "str"})),
            ("ALLOWED_MODULES", frozenset({"json"})),
            ("DANGEROUS_MODULES", frozenset({"os"})),
            ("NUMPY_NUMERIC_NAMESPACES", frozenset()),
            ("NUMPY_IO_NAMES", frozenset()),
        )
        bindings = policy_bindings(policy, None)
        guarded_getattr = bindings["__safe_getattr__"]
        with pytest.raises(AttributeError):
            guarded_getattr(web_env, "_vault_accessor")


@pytest.mark.asyncio
async def test_l1_tc_03_pause_resume_restart_budget_and_reconcile(tmp_path: Path, monkeypatch):
    """Verify FND-QA-13 fixes: Pause keeps completed_step_count=0, preserves router_type, accumulates LLM_STATS."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_KEY", "sk-test-dummy-l1")
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1")

    run_dir = tmp_path / "runs" / "pause_resume_test"
    (run_dir / "init").mkdir(parents=True, exist_ok=True)
    cfg = {
        "env_modules": [{"module_type": "UrbanCommAndIncidentEnv", "kwargs": {"personas": [], "zones": []}}],
        "agents": [{"agent_id": 1, "agent_type": "PersonAgent", "kwargs": {"id": 1, "profile": {"id": 1, "name": "GĐ"}}}],
        "codegen_router": {"final_summary_enabled": False},
        "router_type": "react",
        "max_cost_usd": 5.0,
    }
    cfg_path = run_dir / "init" / "init_config.json"
    steps_path = run_dir / "init" / "steps.yaml"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    steps_path.write_text("start_t: '2026-06-15T08:00:00+07:00'\nsteps:\n  - type: run\n    num_steps: 3\n    tick: 900\n", encoding="utf-8")

    # Fake lightweight Ray actor & society step without external LLM calls
    class _FakeActor:
        async def init(self, _dt):
            return True

        async def to_workspaces(self):
            return None

        async def from_workspaces(self):
            return True

        def set_current_time(self, _t):
            return None

        def set_replay_writer(self, _w):
            return None

        async def step(self, _tick, _t):
            return None

        def get_token_usages(self):
            return {"gpt-5.4-mini": {"calls": 1, "input": 100, "output": 20, "cached_input": 0}}

        async def close(self):
            return None

    async def _coro(val):
        return val

    fake_actor_handle = SimpleNamespace(
        init=SimpleNamespace(remote=lambda dt: _coro(True)),
        to_workspaces=SimpleNamespace(remote=lambda: _coro(None)),
        from_workspaces=SimpleNamespace(remote=lambda: _coro(True)),
        set_current_time=SimpleNamespace(remote=lambda t: None),
        set_replay_writer=SimpleNamespace(remote=lambda w: None),
        step=SimpleNamespace(remote=lambda tick, t: _coro(None)),
        get_token_usages=SimpleNamespace(remote=lambda: "ref_tok"),
        close=SimpleNamespace(remote=lambda: _coro(None)),
    )

    async def _fake_await_ref(ref):
        if ref == "ref_init":
            return True
        if ref == "ref_fw":
            return True
        if ref == "ref_tok":
            return {"gpt-5.4-mini": {"calls": 1, "input": 100, "output": 20, "cached_input": 0}}
        if ref == "ref_step":
            if state_box["calls"] == 0:
                (run_dir / STOP_REQUESTED_FILE).write_text("user_requested\n", encoding="utf-8")
            state_box["calls"] += 1
            return {
                "results": [{"id": 1, "ok": True}],
                "token_stats": {
                    "gpt-5.4-mini": {"calls": 1, "input": 500, "output": 100, "cached_input": 50}
                },
            }
        return None

    state_box = {"calls": 0}
    router_usage_obj = {
        "gpt-5.4-mini": SimpleNamespace(
            call_count=1,
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=0,
        )
    }
    import ray

    monkeypatch.setattr(ray, "is_initialized", lambda: True)
    monkeypatch.setattr(ray, "init", lambda **kw: None)
    monkeypatch.setattr(ray, "kill", lambda *a, **kw: None)
    monkeypatch.setattr(
        ray,
        "get",
        lambda ref, timeout=None: router_usage_obj if ref == "ref_tok" else (True if ref in {"ref_init", "ref_fw"} else None),
    )
    monkeypatch.setattr("agentsociety2.config.llm_dispatcher.init_dispatchers", AsyncMock(return_value=None))
    monkeypatch.setattr("agentsociety2.society.cli.get_env_router_actor_class", lambda max_concurrency=1: SimpleNamespace(remote=lambda *a, **k: fake_actor_handle))
    monkeypatch.setattr("agentsociety2.society.society.create_agents_batch", SimpleNamespace(remote=lambda *a, **k: "ref_create"))
    monkeypatch.setattr("agentsociety2.society.society.step_agent_batch", SimpleNamespace(options=lambda **kw: SimpleNamespace(remote=lambda *a, **k: "ref_step")))
    monkeypatch.setattr("agentsociety2.society.society.AgentSociety._resolve_service_proxy", AsyncMock(return_value=SimpleNamespace(replay=None)))
    monkeypatch.setattr("agentsociety2.society.society.AgentSociety._await_ref", staticmethod(_fake_await_ref))

    # 1. Fresh run stops at tick 1 because STOP_REQUESTED is written
    runner = ExperimentRunner(run_dir)
    await runner.run(config_path=cfg_path, steps_path=steps_path, replay_disable=True)

    pid_meta = json.loads((run_dir / "pid.json").read_text(encoding="utf-8"))
    step_meta = json.loads((run_dir / SOCIETY_STEP_JSON).read_text(encoding="utf-8"))
    soc_meta = json.loads((run_dir / SOCIETY_JSON).read_text(encoding="utf-8"))
    stats_1 = json.loads((run_dir / LLM_STATS_JSON).read_text(encoding="utf-8"))

    assert pid_meta["status"] == "paused"
    assert step_meta["step_count"] == 1
    assert step_meta["completed_step_count"] == 0  # FND-QA-13 trap A fixed!
    assert soc_meta["router_type"] == "react"  # FND-QA-13 trap B fixed!
    assert stats_1["scope"] == "current_process"
    assert stats_1["totals"]["input"] == 600

    # 2. Resume completes remaining 2 ticks and accumulates LLM stats
    runner2 = ExperimentRunner(run_dir)
    await runner2.run(config_path=cfg_path, steps_path=steps_path, replay_disable=True, resume=True)

    pid_meta2 = json.loads((run_dir / "pid.json").read_text(encoding="utf-8"))
    step_meta2 = json.loads((run_dir / SOCIETY_STEP_JSON).read_text(encoding="utf-8"))
    stats_2 = json.loads((run_dir / LLM_STATS_JSON).read_text(encoding="utf-8"))

    assert pid_meta2["status"] == "completed"
    assert step_meta2["step_count"] == 3
    assert step_meta2["completed_step_count"] == 1
    assert stats_2["scope"] == "cumulative"  # FND-QA-13 trap C fixed!
    assert stats_2["totals"]["input"] > stats_1["totals"]["input"]

    # 3. Budget auto-pause when max_cost_usd exceeded at _commit_tick
    soc_budget = AgentSociety(
        agent_specs=[{"id": 1, "profile": {}, "config": {}}],
        agent_class_name="PersonAgent",
        env_router=SimpleNamespace(get_token_usages=lambda: {}, to_workspaces=AsyncMock(return_value=None), close=AsyncMock(return_value=None)),
        start_t=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
        run_dir=tmp_path / "budget_run",
        env_module_types=["UrbanCommAndIncidentEnv"],
        env_kwargs={"UrbanCommAndIncidentEnv": {}},
        router_type="react",
        max_cost_usd=0.0001,
    )
    (tmp_path / "budget_run").mkdir(parents=True, exist_ok=True)
    soc_budget._token_stats = {"gpt-5.5": {"calls": 1, "input": 10000, "output": 2000, "cached_input": 0}}
    await soc_budget._commit_tick(900)
    assert soc_budget._should_terminate is True
    assert "budget_limit_reached" in (soc_budget._pause_reason or "")

    # 4. Lifecycle startup reconcile catches orphaned RUNNING DB record without NameError
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    orphan_dir = tmp_path / "urban_sim_runs" / "mulberrylane" / "urbrun_orphan"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "pid.json").write_text(json.dumps({"status": "paused", "pause_reason": "signal_pause"}), encoding="utf-8")
    from sqlmodel import Session

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id="run_orphan_01",
                project_id=proj.id,
                run_number=99,
                run_dir=str(orphan_dir),
                status="RUNNING",
                pid=99999999,
            )
        )
        sess.commit()

    mgr = UrbanSimLifecycleManager(workspace_root=tmp_path)
    await mgr.reconcile_on_startup()
    with Session(get_engine(tmp_path)) as sess:
        reconciled = sess.get(UrbanSimRun, "run_orphan_01")
        assert reconciled is not None
        assert reconciled.status == "PAUSED"
        assert reconciled.pid is None


@pytest.mark.asyncio
async def test_l1_tc_04_react_router_multistep_and_dual_acl_override():
    comm_env = UrbanCommAndIncidentEnv(
        project_name="MulberryLane",
        personas=[
            {"agent_id": 3, "full_name": "Lê Thu Hà", "role_code": "BQL_RECEPTIONIST", "role_title": "Lễ tân", "group_type": "BQL", "home_zone": "LOBBY_MAIN"},
            {"agent_id": 12, "full_name": "Bà Lan", "role_code": "RESIDENT", "role_title": "Cư dân A-1205", "group_type": "RESIDENT", "home_zone": "TOWER_A"},
        ],
        zones=[{"zone_key": "LOBBY_MAIN", "name": "Sảnh", "zone_type": "LOBBY", "description": ""}],
        bql_agent_ids=[3],
        resident_agent_ids=[12],
    )
    await comm_env.report_resident_incident(agent_id=12, title="Rò nước", description="Bồn rửa bếp", zone_key="TOWER_A")

    router = ReActRouter(
        env_modules=[comm_env],
        max_steps=4,
        final_summary_enabled=False,
        model_role="summary",
        llm_clients_spec={"coder": object(), "default": object()},
    )
    await router.init(datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc))

    seen_tools_per_step = []

    def _mk_tc(cid: str, name: str, arguments: dict):
        return SimpleNamespace(
            id=cid,
            type="function",
            function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        )

    responses = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Bước 1: thử gọi observe_urban_inbox giả danh agent 3",
                        tool_calls=[_mk_tc("tc1", "observe_urban_inbox", {"agent_id": 3})],
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Bước 2: thử gọi manage_incident giả danh BQL agent 3",
                        tool_calls=[_mk_tc("tc2", "manage_incident", {"agent_id": 3, "incident_id": "INC-0001", "new_status": "RESOLVED"})],
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Hoàn tất kiểm tra", tool_calls=None)
                )
            ]
        ),
    ]

    async def _fake_acompletion(**kwargs):
        seen_tools_per_step.append(kwargs.get("tools"))
        assert kwargs.get("model") == "summary"
        return responses.pop(0)

    gen_final_spy = AsyncMock(side_effect=AssertionError("final_summary_enabled=False must not call LLM summary"))
    router.acompletion_with_system_prompt = _fake_acompletion
    router.generate_final_answer = gen_final_spy

    results, answer = await router.ask(ctx={"agent_id": 12}, instruction="Kiểm tra sự vụ")
    assert len(seen_tools_per_step) == 3
    assert seen_tools_per_step[1] is not None  # step_count > 1 still has tools!
    assert "INC-0001" in answer or "status" in results

    # Verify CodeGenRouter context enforcement (ACTIVE_CALLER_AGENT_ID)
    tok = router._set_trace_context("tr1", "sp1", 12)
    try:
        denied = await comm_env.manage_incident(agent_id=3, incident_id="INC-0001", new_status="RESOLVED")
        assert denied["ok"] is False
        assert "ACCESS_DENIED" in denied["error"]
    finally:
        router._reset_trace_context(tok)


@pytest.mark.asyncio
async def test_l1_tc_05_evidence_atlas_retry_session_and_attachment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    server, state = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        run_dir = tmp_path / "atlas_test"
        shots_dir = run_dir / "artifacts" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / "agent_3_latest.jpg").write_bytes(b"\xff\xd8\xff\xe0MOCKJPEGDATA" * 1200)

        from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob

        vault_path = run_dir / ".run_secrets.enc"
        vault_path.write_text(
            encrypt_vault_blob({"atlas": {"atlas_api_url": base_url, "atlas_api_key": "atlas-secret-key-001"}}, tmp_path),
            encoding="utf-8",
        )

        env = EvidenceAtlasSupportEnv(
            allowed_agent_ids=[3],
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            events_log_path=str(run_dir / "urban_events.jsonl"),
            atlas_api_url=base_url,
            attach_screenshot_on_ask=True,
        )
        env._bind_workspace(run_dir / "env" / "EvidenceAtlasSupportEnv")

        # Resident ACL blocked
        denied = await env.ask_atlas_support(agent_id=12, question="Tôi có vào được không?")
        assert denied["ok"] is False
        assert "ACCESS_DENIED" in denied["error"]

        # First ask triggers 429 retry + creates new session + includes data_url_preview
        res1 = await env.ask_atlas_support(
            agent_id=3,
            question="Tạo phiếu phản ánh cư dân ở đâu?",
            current_url=f"{base_url}/qltn/tickets",
            screen_summary="Đang ở trang danh sách phản ánh",
        )
        assert res1["ok"] is True
        assert res1["bot_session_id"] == "sess_atlas_9001"
        assert state["ask_calls"] == 2  # 429 retry once -> 200
        p1 = state["ask_payloads"][-1]
        assert p1["actor_persona"] == "END_USER"
        assert p1["source_mode"] == "FEDERATED_AUTO"
        assert p1["create_new_session"] is True
        assert p1["explicit_route_hint"] == "/qltn/tickets"
        assert p1["attachments"][0]["data_url_preview"].startswith("data:image/jpeg;base64,")

        await env.to_workspace()

        # Restore into fresh instance and send 2nd ask reusing bot_session_id
        env2 = EvidenceAtlasSupportEnv(
            allowed_agent_ids=[3],
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            atlas_api_url=base_url,
        )
        restored = await env2.restore(run_dir / "env" / "EvidenceAtlasSupportEnv")
        assert restored is True
        res2 = await env2.ask_atlas_support(agent_id=3, question="Bước tiếp theo là gì?")
        assert res2["ok"] is True
        p2 = state["ask_payloads"][-1]
        assert p2["bot_session_id"] == "sess_atlas_9001"
        assert "create_new_session" not in p2
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_l1_tc_06_playwright_real_portal_safe_write_and_screenshots(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    headers = _client_headers(monkeypatch)
    server, state = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        init_urban_sim_db(tmp_path)
        proj = ensure_mulberrylane_seed(tmp_path)

        from sqlmodel import Session

        run_id = "urbrun_pw_001"
        run_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / run_id).resolve()
        shots_dir = run_dir / "artifacts" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        with Session(get_engine(tmp_path)) as sess:
            sess.add(UrbanSimRun(id=run_id, project_id=proj.id, run_number=1, run_dir=str(run_dir), status="COMPLETED"))
            sess.commit()

        from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob

        vault_path = run_dir / ".run_secrets.enc"
        vault_path.write_text(
            encrypt_vault_blob(
                {"portal_credentials": {"3": {"portal_url": f"{base_url}/qltn", "username": "letan", "password": "pw123"}}},
                tmp_path,
            ),
            encoding="utf-8",
        )

        env = DemegoWebPortalEnv(
            allowed_agent_ids=[3],
            default_portal_url=f"{base_url}/qltn",
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            events_log_path=str(run_dir / "urban_events.jsonl"),
            guardrail_mode="SAFE_WRITE",
            record_prefix="[SIM-BQL]",
            blocked_keywords=["xóa tất cả", "chốt sổ"],
        )
        env._bind_workspace(run_dir / "env" / "DemegoWebPortalEnv")

        try:
            obs0 = await env.observe_web_portal(agent_id=3)
            assert obs0["status"] == "NOT_LOGGED_IN"
            assert "readonly=False" in obs0["hint"]

            login_res = await env.login_qltn_portal(agent_id=3)
            assert login_res["ok"] is True
            assert "/qltn/tickets" in (login_res.get("url") or "")
            assert login_res["screenshot"] is not None
            shot_name = login_res["screenshot"]

            # Locate title input ref and danger button ref from extracted DOM
            elems = login_res["snapshot"]["elements"]
            title_ref = next(e["ref_id"] for e in elems if e.get("name") == "title")
            danger_ref = next(e["ref_id"] for e in elems if "xóa tất cả" in e.get("label", "").lower())

            fill_res = await env.fill_web_input(agent_id=3, ref_id=title_ref, value="Rò nước A-1205")
            assert fill_res["ok"] is True
            assert fill_res["value_used"].startswith("[SIM-BQL] ")

            # SAFE_WRITE must block destructive button via both click_web_element & click_web_text
            blk_res = await env.click_web_element(agent_id=3, ref_id=danger_ref)
            assert blk_res["ok"] is False
            assert "GUARDRAIL_BLOCKED" in blk_res["error"]

            blk_text_res = await env.click_web_text(agent_id=3, text="Xóa tất cả")
            assert blk_text_res["ok"] is False
            assert "GUARDRAIL_BLOCKED" in blk_text_res["error"]
            assert state["deleted_triggered"] is False

            await env.to_workspace()
        finally:
            await env.close()

        # Verify FastAPI screenshot streaming + traversal protection
        with TestClient(app, base_url="http://127.0.0.1:8001") as client:
            r_ok = client.get(
                f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/screenshots/{shot_name}",
                headers=headers,
            )
            assert r_ok.status_code == 200
            assert r_ok.content.startswith(b"\xff\xd8\xff")
            assert r_ok.headers.get("x-content-type-options") == "nosniff"

            r_bad_slash = client.get(
                f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/screenshots/..%2F.run_secrets.enc",
                headers=headers,
            )
            assert r_bad_slash.status_code in (400, 404)

            r_bad_file = client.get(
                f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/screenshots/.run_secrets.enc",
                headers=headers,
            )
            assert r_bad_file.status_code == 400
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_l1_tc_07_concurrency_21_personas_and_delete_cleanup(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    server, _ = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        init_urban_sim_db(tmp_path)
        proj = ensure_mulberrylane_seed(tmp_path)
        from sqlmodel import Session, select

        with Session(get_engine(tmp_path)) as sess:
            per_rows = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())

        run_id = "urbrun_soak_021"
        run_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / run_id).resolve()
        shots_dir = run_dir / "artifacts" / "screenshots"
        events_path = run_dir / "urban_events.jsonl"

        from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob

        vault_path = run_dir / ".run_secrets.enc"
        run_dir.mkdir(parents=True, exist_ok=True)
        vault_path.write_text(
            encrypt_vault_blob(
                {
                    "portal_credentials": {
                        str(p.agent_id): {"portal_url": f"{base_url}/qltn", "username": f"u{p.agent_id}", "password": "pw"}
                        for p in per_rows
                        if p.software_access_enabled
                    },
                    "atlas": {"atlas_api_url": base_url, "atlas_api_key": "atlas-secret-key-001"},
                },
                tmp_path,
            ),
            encoding="utf-8",
        )

        comm_env = UrbanCommAndIncidentEnv(
            personas=[{"agent_id": p.agent_id, "full_name": p.full_name, "role_code": p.role_code, "role_title": p.role_title, "group_type": p.group_type, "home_zone": p.home_zone} for p in per_rows],
            bql_agent_ids=[p.agent_id for p in per_rows if p.group_type == "BQL"],
            resident_agent_ids=[p.agent_id for p in per_rows if p.group_type == "RESIDENT"],
            events_log_path=str(events_path),
        )
        web_env = DemegoWebPortalEnv(
            allowed_agent_ids=[p.agent_id for p in per_rows if p.software_access_enabled],
            default_portal_url=f"{base_url}/qltn",
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            events_log_path=str(events_path),
        )
        atlas_env = EvidenceAtlasSupportEnv(
            allowed_agent_ids=[p.agent_id for p in per_rows if p.software_access_enabled],
            secrets_vault_path=str(vault_path),
            events_log_path=str(events_path),
            atlas_api_url=base_url,
            quota_per_min=30,
        )

        async def _worker(p: UrbanSimPersona):
            if p.group_type == "RESIDENT":
                res = await comm_env.report_resident_incident(
                    agent_id=p.agent_id,
                    title=f"Yêu cầu từ #{p.agent_id}",
                    description="Kiểm tra vận hành đồng thời",
                    zone_key=p.home_zone,
                )
                assert res["ok"] is True
            else:
                r1 = await web_env.login_qltn_portal(agent_id=p.agent_id)
                assert r1["ok"] is True
                r2 = await atlas_env.ask_atlas_support(agent_id=p.agent_id, question=f"Hỏi cho #{p.agent_id}")
                assert r2["ok"] is True

        try:
            await asyncio.gather(*[_worker(p) for p in per_rows])
        finally:
            await web_env.close()

        lines = [json.loads(ln) for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        seqs = [int(item["seq"]) for item in lines]
        assert seqs == list(range(1, len(seqs) + 1))  # strictly monotonic unique seq across 21 concurrent workers

        # Verify delete_run removes directory & screenshots completely
        with Session(get_engine(tmp_path)) as sess:
            sess.add(UrbanSimRun(id=run_id, project_id=proj.id, run_number=2, run_dir=str(run_dir), status="COMPLETED"))
            sess.commit()
        mgr = UrbanSimLifecycleManager(workspace_root=tmp_path)
        await mgr.delete_run(proj.id, run_id)
        assert not run_dir.exists()
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_l1_tc_08_autonomous_resident_profile_and_building_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    from sqlmodel import Session, select

    with Session(get_engine(tmp_path)) as sess:
        p_row = sess.get(UrbanSimProject, proj.id)
        personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
        atlas = sess.get(UrbanSimAtlasConfig, proj.id)

        residents = [p for p in personas if p.group_type == "RESIDENT"]
        assert len(residents) == 10
        for r in residents:
            assert json.loads(r.initial_tasks_json or "[]") == []
            assert "bồn rửa" not in r.domain_knowledge_prompt.lower()
            assert "30k-456.78" not in r.domain_knowledge_prompt.lower()

        from agentsociety2.backend.services.urban_sim.db import UrbanSimZone

        zones_db = list(
            sess.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == proj.id)).all()
        )
        bundle = compile_run_from_db(
            project=p_row,
            personas=personas,
            atlas=atlas,
            zones=zones_db,
            run_dir=tmp_path / "autonomous_compile",
            workspace_root=tmp_path,
        )

    init_cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
    resident_cfgs = [a for a in init_cfg["agents"] if a["kwargs"]["profile"]["group_type"] == "RESIDENT"]
    bql_cfgs = [a for a in init_cfg["agents"] if a["kwargs"]["profile"]["group_type"] == "BQL"]
    assert len(resident_cfgs) >= 3
    assert len(bql_cfgs) >= 3
    for a in init_cfg["agents"]:
        assert "built-in@daily-guidance" in a["kwargs"]["disabled_skill_ids"]
        assert "built-in@daily-guidance" not in a["kwargs"]["default_activated_skill_ids"]
    for a in resident_cfgs:
        desc = a["kwargs"]["profile"]["description"]
        assert "Behavior Mode: AUTONOMOUS" in desc
        assert "Initial Tasks / Incidents:" not in desc
        assert a["kwargs"]["default_activated_skill_ids"] == ["env:UrbanCommAndIncidentEnv@urban-resident-vn"]
    for a in bql_cfgs:
        assert a["kwargs"]["default_activated_skill_ids"] == ["env:DemegoWebPortalEnv@bql-qltn-ops-vn"]

    # Verify Vietnamese SKILL.md files exist inside env skill_dirs()
    res_dirs = UrbanCommAndIncidentEnv.skill_dirs()
    bql_dirs = DemegoWebPortalEnv.skill_dirs()
    assert res_dirs and (res_dirs[0] / "urban-resident-vn" / "SKILL.md").is_file()
    assert bql_dirs and (bql_dirs[0] / "bql-qltn-ops-vn" / "SKILL.md").is_file()
    assert "Tiếng Việt" in (res_dirs[0] / "urban-resident-vn" / "SKILL.md").read_text(encoding="utf-8")
    assert "Tiếng Việt" in (bql_dirs[0] / "bql-qltn-ops-vn" / "SKILL.md").read_text(encoding="utf-8")

    comm_env = UrbanCommAndIncidentEnv(
        project_name="MulberryLane",
        personas=[
            {
                "agent_id": p.agent_id,
                "full_name": p.full_name,
                "role_code": p.role_code,
                "role_title": p.role_title,
                "group_type": p.group_type,
                "home_zone": p.home_zone,
            }
            for p in personas
        ],
        zones=[
            {
                "zone_key": z.zone_key,
                "name": z.name,
                "zone_type": z.zone_type,
                "description": z.description,
                "ambient_signals": z.ambient_signals,
            }
            for z in zones_db
        ],
        bql_agent_ids=[p.agent_id for p in personas if p.group_type == "BQL"],
        resident_agent_ids=[p.agent_id for p in personas if p.group_type == "RESIDENT"],
    )
    comm_env.t = datetime(2026, 6, 15, 8, 15, tzinfo=timezone.utc)
    obs = await comm_env.observe_urban_inbox(agent_id=12)
    assert obs["agent_id"] == 12
    assert obs["sim_time"] == "2026-06-15T08:15:00+00:00"
    assert "building_context" in obs
    bc = obs["building_context"]
    assert bc["time_band"] == "MORNING_RUSH"
    assert isinstance(bc["building_signals"], list) and len(bc["building_signals"]) >= 1
    assert any("Zen Tower ZA" in sig for sig in bc["building_signals"])
    assert bc["has_own_open_incident"] is False
    assert "readonly=False" in bc["autonomy_guidance"]
    assert "visible_incidents" in obs and "recent_messages" in obs and "bql_contacts" in obs

    obs_c = await comm_env.observe_urban_inbox(agent_id=14)
    assert any("Fantasy Tower" in sig for sig in obs_c["building_context"]["building_signals"])


@pytest.mark.asyncio
async def test_l1_tc_09_playwright_otp_pin_toggle_login(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    server, _ = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        run_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / "urbrun_pin_001").resolve()
        shots_dir = run_dir / "artifacts" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)

        from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob

        vault_path = run_dir / ".run_secrets.enc"
        vault_path.write_text(
            encrypt_vault_blob(
                {"portal_credentials": {"3": {"portal_url": f"{base_url}/qltn-pin/login", "username": "sim_letan", "password": "739158"}}},
                tmp_path,
            ),
            encoding="utf-8",
        )

        web_env = DemegoWebPortalEnv(
            allowed_agent_ids=[3],
            default_portal_url=f"{base_url}/qltn-pin/login",
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            events_log_path=str(run_dir / "urban_events.jsonl"),
        )
        web_env._bind_workspace(run_dir / "env" / "DemegoWebPortalEnv")
        try:
            res = await web_env.login_qltn_portal(agent_id=3)
            assert res["ok"] is True
            assert "/qltn/tickets" in (res.get("url") or "")
        finally:
            await web_env.close()
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_l1_tc_10_click_web_text_and_dom_filter_and_zone_signals(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    server, _ = _start_mock_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        run_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / "urbrun_tc10").resolve()
        shots_dir = run_dir / "artifacts" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)

        from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob

        vault_path = run_dir / ".run_secrets.enc"
        vault_path.write_text(
            encrypt_vault_blob(
                {"portal_credentials": {"3": {"portal_url": f"{base_url}/qltn/login", "username": "sim_letan", "password": "739158"}}},
                tmp_path,
            ),
            encoding="utf-8",
        )

        web_env = DemegoWebPortalEnv(
            allowed_agent_ids=[3],
            default_portal_url=f"{base_url}/qltn/login",
            secrets_vault_path=str(vault_path),
            screenshots_dir=str(shots_dir),
            events_log_path=str(run_dir / "urban_events.jsonl"),
            guardrail_mode="SAFE_WRITE",
            blocked_keywords=["xóa tất cả"],
        )
        web_env._bind_workspace(run_dir / "env" / "DemegoWebPortalEnv")
        try:
            pre_obs = await web_env.observe_web_portal(agent_id=3)
            assert pre_obs["status"] == "NOT_LOGGED_IN"
            assert "readonly=False" in pre_obs["hint"]

            login_res = await web_env.login_qltn_portal(agent_id=3)
            assert login_res["ok"] is True
            elems = login_res["snapshot"]["elements"]
            labels = [e["label"] for e in elems]
            assert "Phiếu yêu cầu" in labels
            assert "button" not in labels
            assert "99+" not in labels

            click_res = await web_env.click_web_text(agent_id=3, text="Phiếu yêu cầu")
            assert click_res["ok"] is True
            assert "Opened: Phieu yeu cau" in (click_res["snapshot"].get("body_excerpt") or "")

            blocked_res = await web_env.click_web_text(agent_id=3, text="Xóa tất cả")
            assert blocked_res["ok"] is False
            assert "GUARDRAIL_BLOCKED" in blocked_res["error"]
        finally:
            await web_env.close()

        comm_env = UrbanCommAndIncidentEnv(
            project_name="MulberryLane",
            personas=[
                {"agent_id": 12, "full_name": "Cư dân A", "role_code": "RESIDENT", "role_title": "Chủ hộ", "group_type": "RESIDENT", "home_zone": "TOWER_A"},
                {"agent_id": 14, "full_name": "Cư dân C", "role_code": "RESIDENT", "role_title": "Chủ hộ", "group_type": "RESIDENT", "home_zone": "TOWER_C"},
            ],
            zones=[
                {
                    "zone_key": "TOWER_A",
                    "name": "Zen ZA",
                    "zone_type": "TOWER",
                    "description": "Khối căn hộ ZA",
                    "ambient_signals": "Tín hiệu động ZA: kiểm tra áp lực nước và thẻ xe hầm.",
                },
                {
                    "zone_key": "TOWER_C",
                    "name": "Fantasy",
                    "zone_type": "TOWER",
                    "description": "Khối căn hộ Fantasy",
                    "ambient_signals": "Tín hiệu động Fantasy: thang máy tầng cao rung nhẹ.",
                },
            ],
            bql_agent_ids=[],
            resident_agent_ids=[12, 14],
        )
        comm_env.t = datetime(2026, 6, 15, 8, 15, tzinfo=timezone.utc)
        obs_a = await comm_env.observe_urban_inbox(agent_id=12)
        obs_c = await comm_env.observe_urban_inbox(agent_id=14)
        assert any("ZA" in s for s in obs_a["building_context"]["building_signals"])
        assert any("Fantasy" in s for s in obs_c["building_context"]["building_signals"])
        assert "readonly=False" in obs_a["building_context"]["autonomy_guidance"]
    finally:
        server.shutdown()


def test_l1_tc_11_export_atlas_qa_markdown_and_json(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    from sqlmodel import Session

    run_id = "urbrun_export_011"
    run_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id=run_id,
                project_id=proj.id,
                run_number=7,
                run_dir=str(run_dir),
                status="COMPLETED",
                step_count=4,
                total_steps=4,
            )
        )
        sess.commit()

    # Tạo >350 sự kiện hỗn hợp để bảo đảm Export lấy toàn bộ, không bị cắt theo limit 300
    events_lines: list[str] = []
    mermaid_ans = (
        "## 1. Quy trình\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        " A[Danh sách công việc] --> B{Có nút Nhận việc?}\n"
        " B -->|Có| C[Chọn Nhận việc]\n"
        "```\n\n"
        "| Cột | Giá trị |\n| --- | --- |\n| Màn hình | Công việc |"
    )
    for seq in range(1, 361):
        if seq in (12, 355):
            ev = {
                "seq": seq,
                "stream": "ATLAS",
                "agent_id": 4 if seq == 12 else 9,
                "agent_name": "Trưởng ca An ninh" if seq == 12 else "Kỹ sư trưởng",
                "role_title": "Trưởng ca An ninh" if seq == 12 else "Kỹ sư trưởng",
                "action": "ask_atlas_support",
                "summary": "Hỏi CSKH",
                "ok": True,
                "sim_time": "2026-06-15T08:30:00+07:00",
                "wall_time": "2026-11-25T08:30:00+00:00",
                "details": {
                    "bot_session_id": f"sess_{seq}",
                    "assistant_message_id": f"msg_{seq}",
                    "route_hint": "/ext/internal-tasks",
                    "question": f"Câu hỏi #{seq}",
                    "answer": mermaid_ans if seq == 12 else "Vào **Bảo trì tài sản**.",
                    "mcp_used": True,
                },
            }
        elif seq == 358:
            ev = {
                "seq": seq,
                "stream": "ATLAS",
                "agent_id": 4,
                "agent_name": "Trưởng ca An ninh",
                "role_title": "Trưởng ca An ninh",
                "action": "ask_atlas_support",
                "summary": "Lỗi hỏi CSKH",
                "ok": False,
                "sim_time": "2026-06-15T09:00:00+07:00",
                "wall_time": "2026-11-25T09:00:00+00:00",
                "details": {
                    "question": "Câu hỏi bị timeout",
                    "error": "HTTP 504 Gateway Time-out",
                },
            }
        else:
            ev = {
                "seq": seq,
                "stream": "WEB",
                "agent_id": 3,
                "agent_name": "Lễ tân",
                "role_title": "Lễ tân",
                "action": "click_web_text",
                "summary": "Thao tác web",
                "ok": True,
                "sim_time": "2026-06-15T08:15:00+07:00",
                "wall_time": "2026-11-25T08:15:00+00:00",
                "details": {},
            }
        events_lines.append(json.dumps(ev, ensure_ascii=False))
    (run_dir / "urban_events.jsonl").write_text("\n".join(events_lines) + "\n", encoding="utf-8")

    # Thêm một Run trống để kiểm tra edge-case
    empty_run_id = "urbrun_empty_011"
    empty_dir = (tmp_path / "urban_sim_runs" / "mulberrylane" / empty_run_id).resolve()
    empty_dir.mkdir(parents=True, exist_ok=True)
    with Session(get_engine(tmp_path)) as sess:
        sess.add(UrbanSimRun(id=empty_run_id, project_id=proj.id, run_number=8, run_dir=str(empty_dir), status="COMPLETED"))
        sess.commit()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        r_md = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/atlas-qa/export?format=markdown",
            headers=headers,
        )
        assert r_md.status_code == 200
        assert r_md.headers.get("x-content-type-options") == "nosniff"
        assert ".md" in (r_md.headers.get("content-disposition") or "")
        assert "```mermaid" in r_md.text
        assert "flowchart TD" in r_md.text
        assert "Câu hỏi #12" in r_md.text
        assert "Câu hỏi #355" in r_md.text
        assert "HTTP 504 Gateway Time-out" in r_md.text

        r_json = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/atlas-qa/export?format=json",
            headers=headers,
        )
        assert r_json.status_code == 200
        assert ".json" in (r_json.headers.get("content-disposition") or "")
        data = r_json.json()
        assert data["summary"] == {"total": 3, "succeeded": 2, "failed": 1, "unique_agents": 2}
        assert [item["seq"] for item in data["items"]] == [12, 355, 358]
        assert "```mermaid" in data["items"][0]["answer_markdown"]

        r_filtered = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/atlas-qa/export?format=json&agent_id=4",
            headers=headers,
        )
        assert r_filtered.status_code == 200
        filtered_data = r_filtered.json()
        assert filtered_data["summary"]["total"] == 2
        assert [item["seq"] for item in filtered_data["items"]] == [12, 358]

        r_empty = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{empty_run_id}/atlas-qa/export?format=markdown",
            headers=headers,
        )
        assert r_empty.status_code == 200
        assert "Chưa ghi nhận lượt hỏi đáp CSKH nào" in r_empty.text


def test_l1_tc_12_naturalize_support_question_and_prompt_rules(tmp_path: Path, monkeypatch):
    from agentsociety2.contrib.env.evidence_atlas_support import naturalize_support_question

    q134 = (
        "Hỏi CSKH EvidenceAtlas về quy trình trên QLTN cho Trưởng ca An ninh: "
        "cách vào mục xử lý sự vụ an ninh/bãi xe, nhận việc, cập nhật phân công cho nhân viên, "
        "và ghi nhận/đổi trạng thái ticket từ màn hình Công việc / Công việc thực thi hiện tại. "
        "Vui lòng trả lời ngắn gọn bằng tiếng Việt."
    )
    out134 = naturalize_support_question(q134, role_title="Trưởng ca An ninh")
    assert out134 == (
        "Quy trình trên QLTN cho Trưởng ca An ninh: cách vào mục xử lý sự vụ an ninh/bãi xe, "
        "nhận việc, cập nhật phân công cho nhân viên, và ghi nhận/đổi trạng thái ticket từ màn hình "
        "Công việc / Công việc thực thi hiện tại"
    )
    assert "EvidenceAtlas" not in out134
    assert "trả lời ngắn gọn" not in out134.lower()

    q25 = (
        "Vui lòng cho biết đường dẫn và cách thao tác trên QLTN cho chức danh agent_id 9 "
        "để xem/nhận ticket bảo trì và phân công nhân viên kỹ thuật."
    )
    out25 = naturalize_support_question(q25, role_title="Kỹ sư trưởng")
    assert "agent_id" not in out25
    assert "Kỹ sư trưởng" in out25

    q22 = (
        "Xin chào CSKH EvidenceAtlas, vui lòng cho biết đường dẫn trên QLTN cho vai trò Trợ lý Dự án. "
        "Tôi có thể đính kèm ảnh màn hình hiện tại nếu cần."
    )
    out22 = naturalize_support_question(q22, role_title="Trợ lý Dự án")
    assert "EvidenceAtlas" not in out22
    assert "ảnh màn hình" not in out22.lower()
    assert out22.startswith("Xin chào,")

    q50 = (
        "Hỏi EvidenceAtlas cách thao tác cho Lễ tân trên QLTN: vị trí tạo phiếu phản ánh/yêu cầu; "
        "kèm ảnh chụp màn hình hiện tại."
    )
    out50 = naturalize_support_question(q50, role_title="Lễ tân Sảnh chính")
    assert out50 == "Cách thao tác cho Lễ tân trên QLTN: vị trí tạo phiếu phản ánh/yêu cầu"

    q89 = (
        "Hỏi CSKH EvidenceAtlas hướng dẫn thao tác trên QLTN cho nhân viên an ninh. "
        "Đính kèm ảnh màn hình hiện tại."
    )
    out89 = naturalize_support_question(q89, role_title="NV An ninh 1")
    assert out89 == "Hướng dẫn thao tác trên QLTN cho nhân viên an ninh"

    # Câu tự nhiên sẵn không bị biến dạng
    q_nat = "Tạo phiếu phản ánh cư dân ở đâu?"
    assert naturalize_support_question(q_nat, role_title="Lễ tân") == q_nat

    # Kiểm tra tool schema Annotated Field description được truyền cho LLM Router
    env = EvidenceAtlasSupportEnv(allowed_agent_ids=[3])
    ask_tool = next(t for t in env._llm_tools if t["function"]["name"] == "ask_atlas_support")
    q_desc = ask_tool["function"]["parameters"]["properties"]["question"]["description"]
    assert "người với người" in q_desc
    assert "EvidenceAtlas" in q_desc  # cấm nhắc EvidenceAtlas

    # Kiểm tra compile_run_from_db làm sạch cụm seed cũ từ DB và sinh prompt_overrides mới
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    from sqlmodel import Session, select

    with Session(get_engine(tmp_path)) as sess:
        p_row = sess.get(UrbanSimProject, proj.id)
        personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
        atlas = sess.get(UrbanSimAtlasConfig, proj.id)
        # Giả lập bản ghi cũ trong DB vẫn còn cụm seed cũ
        for p in personas:
            if p.agent_id == 4:
                p.domain_knowledge_prompt = "Nếu chưa biết thì hỏi CSKH EvidenceAtlas."
                p.initial_tasks_json = json.dumps(["Hỏi EvidenceAtlas khi cần."], ensure_ascii=False)
        bundle = compile_run_from_db(
            project=p_row,
            personas=personas,
            atlas=atlas,
            zones=[],
            run_dir=tmp_path / "compile_natural_cskh",
            workspace_root=tmp_path,
        )

    po_txt = bundle.prompt_overrides_path.read_text(encoding="utf-8")
    assert "Thần Nông" in po_txt
    assert "người với người" in po_txt
    init_cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
    ag4_desc = next(a for a in init_cfg["agents"] if a["agent_id"] == 4)["kwargs"]["profile"]["description"]
    assert "EvidenceAtlas" not in ag4_desc
    assert "Thần Nông" in ag4_desc


@pytest.mark.asyncio
async def test_l1_tc_13_persona_timeline_and_layer2_thought_redaction(tmp_path: Path, monkeypatch):
    """Verify Layer-2 react.thought + redacted input.args in trace AND Layer-1 timeline API aggregation."""
    import glob
    from datetime import timedelta
    from sqlmodel import Session
    from agentsociety2.agent.base.agent import _extract_react_thought, _sanitize_trace_args
    from agentsociety2.agent.person import PersonAgent
    from agentsociety2.trace.sharded_writer import TraceProxy

    # 1. Helper unit assertions
    assert (
        _extract_react_thought(
            {"role": "assistant", "content": "Tôi cần xem lại sổ tay trước khi mở Phiếu yêu cầu."}
        )
        == "Tôi cần xem lại sổ tay trước khi mở Phiếu yêu cầu."
    )
    assert _extract_react_thought({"role": "assistant", "content": '{"action":"read"}'}) == ""
    assert (
        _extract_react_thought(
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "Suy luận nội bộ từ reasoning_content.",
            }
        )
        == "Suy luận nội bộ từ reasoning_content."
    )
    redacted = _sanitize_trace_args(
        {"password": "my-secret-password", "nested": {"api_key": "sk-live-123", "portal_url": "https://ok"}}
    )
    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["api_key"] == "***REDACTED***"
    assert redacted["nested"]["portal_url"] == "https://ok"

    # 2. PersonAgent.step trace emission with mock dispatcher
    run_dir = tmp_path / "layer2_trace_run"
    ws_agent = run_dir / "agents" / "agent_0003"
    PersonAgent.create(
        ws_agent,
        {"id": 3, "name": "Lễ tân Test", "role": "Lễ tân", "description": "Lễ tân sảnh chính"},
        {"enable_memory": True, "enable_todo_list": True, "max_react_turns": 4},
    )
    (ws_agent / "notes").mkdir(parents=True, exist_ok=True)
    (ws_agent / "notes" / "atlas_guides.md").write_text("# Sổ tay\n- Mở `/ext/ticket`", encoding="utf-8")

    class _FakeLLM:
        model_name = "mock-gpt"

    proxy = SimpleNamespace(
        env=None,
        llm=SimpleNamespace(coder=_FakeLLM(), default=_FakeLLM(), embedding=None),
        trace=TraceProxy(trace_dir=str(run_dir / "trace")),
        replay=None,
        run_dir=run_dir,
    )
    ag = await PersonAgent.from_workspace(ws_agent, proxy)

    responses = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Tôi cần kiểm tra xem mình có ghi chú hướng dẫn mở phiếu hay chưa.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="todo_list",
                                    arguments=json.dumps({"password": "hidden-pw", "status": "pending"}),
                                ),
                            )
                        ],
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Tôi đã xem xong danh sách việc cần làm và sẵn sàng kết thúc lượt.",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_2",
                                function=SimpleNamespace(
                                    name="finish",
                                    arguments=json.dumps(
                                        {
                                            "final": "Đã kiểm tra danh sách việc lúc 08:00.",
                                            "memories": [
                                                {
                                                    "type": "observation",
                                                    "importance": 0.85,
                                                    "keywords": ["sổ tay", "INC-0001"],
                                                    "text": "Đã rà soát việc cần làm liên quan INC-0001.",
                                                }
                                            ],
                                        },
                                        ensure_ascii=False,
                                    ),
                                ),
                            )
                        ],
                    )
                )
            ]
        ),
    ]

    async def _fake_call(**kwargs):
        return responses.pop(0)

    ag._dispatcher = SimpleNamespace(call=_fake_call, model_name="mock-gpt")
    await ag.step(900, datetime(2026, 6, 15, 8, 0, tzinfo=timezone(timedelta(hours=7))))

    trace_recs = []
    for tf in sorted(glob.glob(str(run_dir / "trace" / "trace_*.jsonl"))):
        for ln in Path(tf).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                trace_recs.append(json.loads(ln))

    turn_thoughts = [
        (r.get("attributes") or {}).get("react.thought")
        for r in trace_recs
        if r.get("name") == "react.turn" and (r.get("attributes") or {}).get("react.thought")
    ]
    assert any("kiểm tra xem mình có ghi chú" in t for t in turn_thoughts)
    tool_spans = [r for r in trace_recs if r.get("name") == "react.tool"]
    assert tool_spans
    assert (tool_spans[0].get("attributes") or {}).get("input.args", {}).get("password") == "***REDACTED***"

    # 3. Control-plane REST API timeline endpoint aggregation check
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    run_id = "urbrun_timeline_test"
    # Copy layer2 trace/agent workspace into seeded run_dir under tmp_path
    import shutil

    api_run_dir = (tmp_path / "urban_sim_runs" / proj.slug / run_id).resolve()
    shutil.copytree(run_dir, api_run_dir, dirs_exist_ok=True)
    (api_run_dir / "urban_events.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "stream": "WEB",
                "agent_id": 3,
                "agent_name": "Lễ tân Sảnh chính (sim_letan)",
                "role_title": "Lễ tân Sảnh chính",
                "action": "login_qltn_portal",
                "summary": "Đăng nhập QLTN -> https://mulberrylane.sandbox.demego.vn/home",
                "ok": True,
                "sim_time": "2026-06-15T08:00:00+07:00",
                "wall_time": "2026-11-25T08:00:00+00:00",
                "screenshot_file": None,
                "details": {"url": "https://mulberrylane.sandbox.demego.vn/home"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    comm_env_dir = api_run_dir / "env" / "UrbanCommAndIncidentEnv" / "state"
    comm_env_dir.mkdir(parents=True, exist_ok=True)
    (comm_env_dir / "ENV_STATE.json").write_text(
        json.dumps(
            {
                "incidents": {
                    "INC-0001": {
                        "incident_id": "INC-0001",
                        "reporter_id": 16,
                        "reporter_name": "Cư dân ZB2001",
                        "zone_key": "TOWER_B",
                        "title": "Đầu đọc thẻ xe máy lỗi",
                        "status": "OPEN",
                        "resolution_note": "",
                    }
                },
                "mailboxes": {"3": [{"incident_id": "INC-0001"}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id=run_id,
                project_id=proj.id,
                run_number=1,
                run_dir=str(api_run_dir),
                status="COMPLETED",
                step_count=1,
                total_steps=1,
                active_agent_count=1,
            )
        )
        sess.commit()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        resp = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/agents/3/timeline",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["summary"]["total_steps"] >= 1
        assert body["summary"]["web_events_count"] == 1
        assert body["summary"]["notes_count"] == 1
        step1 = body["steps"][0]
        assert any("kiểm tra xem mình có ghi chú" in th for th in step1["thoughts"])
        assert step1["web_events"][0]["action"] == "login_qltn_portal"
        assert any(inc["incident_id"] == "INC-0001" for inc in step1["related_incidents"])
        assert body["notes"][0]["path"] == "notes/atlas_guides.md"
        # Tool args remain redacted in API payload too
        tool_acts = [a for t in step1["technical_turns"] for a in t["actions"]]
        todo_act = next(a for a in tool_acts if a["action"] == "todo_list")
        assert todo_act["args"]["password"] == "***REDACTED***"

        # Unknown agent_id must return 404
        resp404 = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/agents/999/timeline",
            headers=headers,
        )
        assert resp404.status_code == 404


# ==================== BQL COMPETENCY & AI AUDITOR TESTS (TC-EVAL-01..07) ====================


def test_eval_01_math_and_miller_edge_cases(tmp_path: Path):
    """TC-EVAL-01: Marx-Cummings c, Smith L_first, failed trace attempts, READ_ONLY vs SAFE_WRITE, oversight M3."""
    from agentsociety2.backend.services.urban_sim.competency import (
        DEFAULT_MULBERRYLANE_RUBRIC,
        compute_marx_cummings_c,
        compute_smith_lostness,
        evaluate_run_competency,
        normalize_url_for_lostness,
    )

    # 1) Marx & Cummings (2007) Normalized Change c (0 NaN/Inf/ZeroDiv)
    assert compute_marx_cummings_c(20.0, 60.0) == {"value": 0.5, "status": "OK"}
    assert compute_marx_cummings_c(80.0, 40.0) == {"value": -0.5, "status": "OK"}
    assert compute_marx_cummings_c(100.0, 100.0) == {"value": None, "status": "CEILING_UNCHANGED"}
    assert compute_marx_cummings_c(0.0, 0.0) == {"value": None, "status": "FLOOR_UNCHANGED"}
    assert compute_marx_cummings_c(50.0, 50.0) == {"value": 0.0, "status": "UNCHANGED"}
    assert compute_marx_cummings_c(None, 70.0) == {"value": None, "status": "NO_QUIZ_DATA"}

    # 2) Smith L_first + URL normalization
    norm_u = normalize_url_for_lostness(
        "https://MulberryLane.Sandbox.Demego.vn/ext/ticket/123456?page=2&sort=desc&type=req#top"
    )
    assert norm_u == "/ext/ticket/:id"

    rule_rec = DEFAULT_MULBERRYLANE_RUBRIC.roles["BQL_RECEPTIONIST"]
    m_nr, reached_nr, _ = compute_smith_lostness(
        visited_urls=["https://mulberrylane.sandbox.demego.vn/home"],
        target_patterns=rule_rec.target_url_patterns,
        expected_min_steps=rule_rec.expected_min_steps,
        total_non_login_web_actions=3,
        min_actions_for_lostness=rule_rec.min_actions_for_lostness,
    )
    assert reached_nr is False and m_nr["status"] == "TARGET_NOT_REACHED"

    m_low, reached_low, _ = compute_smith_lostness(
        visited_urls=[
            "https://mulberrylane.sandbox.demego.vn/home",
            "https://mulberrylane.sandbox.demego.vn/ext/ticket",
        ],
        target_patterns=rule_rec.target_url_patterns,
        expected_min_steps=rule_rec.expected_min_steps,
        total_non_login_web_actions=1,
        min_actions_for_lostness=rule_rec.min_actions_for_lostness,
    )
    assert reached_low is True and m_low["status"] == "INCONCLUSIVE_LOW_ACTIVITY"

    m_direct, _, _ = compute_smith_lostness(
        visited_urls=[
            "https://mulberrylane.sandbox.demego.vn/home",
            "https://mulberrylane.sandbox.demego.vn/ext/ticket",
        ],
        target_patterns=rule_rec.target_url_patterns,
        expected_min_steps=rule_rec.expected_min_steps,
        total_non_login_web_actions=3,
        min_actions_for_lostness=rule_rec.min_actions_for_lostness,
    )
    assert m_direct == {"value": 0.0, "status": "DIRECT_SHORTCUT"}

    # 3) Full evaluate_run_competency: oversight M4 (BQL_DIRECTOR), READ_ONLY M3, failed trace attempts, same-tick CSKH conversion
    run_dir = tmp_path / "run_eval_01"
    (run_dir / "trace").mkdir(parents=True, exist_ok=True)
    (run_dir / "env" / "DemegoWebPortalEnv" / "state").mkdir(parents=True, exist_ok=True)
    (run_dir / "env" / "DemegoWebPortalEnv" / "state" / "ENV_STATE.json").write_text(
        json.dumps({"guardrail_mode": "READ_ONLY"}), encoding="utf-8"
    )
    (run_dir / "agents" / "agent_0001" / "notes").mkdir(parents=True, exist_ok=True)
    (run_dir / "agents" / "agent_0001" / "notes" / "atlas_guides.md").write_text(
        "- Mở /ext/ticket và /ext/incidents", encoding="utf-8"
    )

    society_doc = {
        "agent_specs": [
            {
                "id": 1,
                "profile": {
                    "name": "Giám đốc Dự án",
                    "role": "Giám đốc",
                    "role_code": "BQL_DIRECTOR",
                    "group_type": "BQL",
                    "software_access_enabled": True,
                },
                "config": {},
            },
            {
                "id": 3,
                "profile": {
                    "name": "Lễ tân Sảnh chính",
                    "role": "Lễ tân",
                    "role_code": "BQL_RECEPTIONIST",
                    "group_type": "BQL",
                    "software_access_enabled": True,
                },
                "config": {},
            },
        ]
    }
    (run_dir / "SOCIETY.json").write_text(json.dumps(society_doc, ensure_ascii=False), encoding="utf-8")

    # Trace: 1 failed web attempt for agent 3 + step timestamps
    trace_lines = [
        {
            "trace_id": "t_a3_s1",
            "name": "agent.step",
            "resource": {"agent.id": 3},
            "attributes": {"step.count": 1, "input.summary": {"time": "2026-06-15T08:00:00+07:00"}},
        },
        {
            "trace_id": "t_a3_s1",
            "name": "react.tool",
            "resource": {"agent.id": 3},
            "attributes": {
                "react.action": "ask_env",
                "result.ok": True,
                "input.args": {"tool": "click_web_text"},
                "output.summary": '{"ok": false, "error": "Không tìm thấy mục"}',
            },
        },
        {
            "trace_id": "t_a3_s1",
            "name": "react.tool",
            "resource": {"agent.id": 3},
            "attributes": {
                "react.action": "ask_env",
                "result.ok": True,
                "output.summary": 'GUARDRAIL_BLOCKED (READ_ONLY): Bị chặn thao tác ghi "lưu"',
            },
        },
    ]
    (run_dir / "trace" / "trace_001.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in trace_lines) + "\n", encoding="utf-8"
    )

    events = [
        # Agent 1 (oversight): login + 2 distinct target modules -> M3 + manage_incident -> M4
        {"seq": 1, "stream": "WEB", "agent_id": 1, "action": "login_qltn_portal", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/home"}},
        {"seq": 2, "stream": "WEB", "agent_id": 1, "action": "click_web_text", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/ticket"}},
        {"seq": 3, "stream": "WEB", "agent_id": 1, "action": "click_web_text", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/incidents"}},
        {"seq": 4, "stream": "WEB", "agent_id": 1, "action": "click_web_text", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/incidents"}},
        {"seq": 5, "stream": "INCIDENT", "agent_id": 1, "action": "manage_incident", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"incident_id": "INC-0001"}},
        # Agent 3: ask ATLAS same tick -> later clicks ticket -> READ_ONLY block -> achieves M3 READ_ONLY_VERIFIED!
        {"seq": 6, "stream": "WEB", "agent_id": 3, "action": "login_qltn_portal", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/home"}},
        {"seq": 7, "stream": "ATLAS", "agent_id": 3, "action": "ask_atlas_support", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"question": "Tạo phiếu ở đâu?"}},
        {"seq": 8, "stream": "WEB", "agent_id": 3, "action": "click_web_text", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/ticket"}},
        {"seq": 9, "stream": "WEB", "agent_id": 3, "action": "click_web_text", "ok": True, "sim_time": "2026-06-15T08:00:00+07:00", "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/ticket"}},
        {"seq": 10, "stream": "WEB", "agent_id": 3, "action": "guardrail_block", "ok": False, "summary": "READ_ONLY chặn bấm 'luu phan anh'", "sim_time": "2026-06-15T08:00:00+07:00", "details": {}},
    ]
    (run_dir / "urban_events.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in events) + "\n", encoding="utf-8"
    )

    rep = evaluate_run_competency(run_dir=run_dir, bypass_cache=True)
    by_id = {r["agent_id"]: r for r in rep["agents"]}
    assert by_id[1]["miller_level"] == "M4"
    assert by_id[1]["retention"]["has_retention"] is True
    assert by_id[3]["miller_level"] == "M3"
    assert "READ_ONLY_VERIFIED" in by_id[3]["flags"]
    assert by_id[3]["safety_violation"] is False
    # 3 ok web ops + 1 failed web attempt from trace = 0.75
    assert by_id[3]["activity"]["failed_web_attempts"] == 1
    assert by_id[3]["metrics"]["effectiveness"]["value"] == 0.75
    # Same-tick conversion after seq 7 -> seq 8
    assert by_id[3]["metrics"]["cskh_conversion"]["value"] == 1.0


def test_eval_02_sqlite_migration_and_rubric_validation(tmp_path: Path, monkeypatch):
    """TC-EVAL-02: Idempotent ALTER TABLE on legacy SQLite DB missing new columns + 64KB rubric limit."""
    import sqlite3
    from agentsociety2.backend.services.urban_sim.db import _ENGINE_CACHE, UrbanSimProject, get_engine

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    _ENGINE_CACHE.clear()

    db_file = tmp_path / ".agentsociety" / "urban_sim.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    # Create legacy table missing enable_competency_prepost_quiz & competency_rubric_json
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE urban_sim_projects (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            default_portal_url TEXT NOT NULL DEFAULT 'https://mulberrylane.sandbox.demego.vn',
            router_type TEXT NOT NULL DEFAULT 'react',
            num_steps INTEGER NOT NULL DEFAULT 8,
            tick_seconds INTEGER NOT NULL DEFAULT 900,
            start_time_iso TEXT NOT NULL DEFAULT '2026-06-15T08:00:00+07:00',
            max_react_turns INTEGER NOT NULL DEFAULT 6,
            max_cost_usd_per_run REAL NOT NULL DEFAULT 5.0,
            pilot_mode INTEGER NOT NULL DEFAULT 1,
            zone_map_image_rel TEXT,
            llm_config_id TEXT,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "INSERT INTO urban_sim_projects (id, slug, name) VALUES ('proj_legacy', 'legacy-ml', 'Legacy ML')"
    )
    conn.commit()
    conn.close()

    # Calling get_engine() directly MUST migrate columns cleanly
    eng = get_engine(tmp_path)
    with Session(eng) as sess:
        row = sess.get(UrbanSimProject, "proj_legacy")
        assert row is not None
        assert bool(row.enable_competency_prepost_quiz) is False
        assert row.competency_rubric_json is None

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # > 64KB rubric rejected with 400
        oversized = json.dumps({"version": "x", "fallback_role": {"role_code": "BQL_STAFF", "label": "X"}, "roles": [], "quiz_questions": [], "pad": "a" * 70000})
        resp_big = client.patch(
            "/api/v1/urban-sim/projects/proj_legacy",
            headers=headers,
            json={"competency_rubric_json": oversized},
        )
        assert resp_big.status_code == 400
        resp_bad = client.patch(
            "/api/v1/urban-sim/projects/proj_legacy",
            headers=headers,
            json={"competency_rubric_json": "{not valid json"},
        )
        assert resp_bad.status_code == 400


def test_eval_03_ssot_society_json_and_pilot_filtering(tmp_path: Path):
    """TC-EVAL-03: 3-tier SSOT parses SOCIETY.json['agent_specs'][].profile (no kwargs) and filters Pilot BQL."""
    from agentsociety2.backend.services.urban_sim.competency import (
        evaluate_run_competency,
        extract_run_models,
        load_run_participants,
    )

    run_dir = tmp_path / "pilot_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Exact schema from cli.py / society.py: {"id": ..., "profile": {"name": ..., "role": ...}, "config": {}}
    (run_dir / "SOCIETY.json").write_text(
        json.dumps(
            {
                "agent_specs": [
                    {
                        "id": 1,
                        "profile": {
                            "name": "Giám đốc Pilot",
                            "role": "Giám đốc Dự án",
                            "role_code": "BQL_DIRECTOR",
                            "group_type": "BQL",
                            "software_access_enabled": True,
                        },
                        "config": {},
                    },
                    {
                        "id": 12,
                        "profile": {
                            "name": "Cư dân ZB",
                            "role": "Cư dân",
                            "role_code": "RESIDENT",
                            "group_type": "RESIDENT",
                            "software_access_enabled": False,
                        },
                        "config": {},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "LLM_STATS.json").write_text(
        json.dumps({"agent_side": {"models": {"openai/gpt-5.4-mini": {"calls": 10}}}}),
        encoding="utf-8",
    )

    # Even if DB fallback has 20 other personas, SOCIETY.json wins!
    db_fallback = [
        {"agent_id": 99, "full_name": "DB Ghost", "role_code": "BQL_STAFF", "role_title": "Ghost", "group_type": "BQL", "software_access_enabled": True}
    ]
    eligible, excluded, src = load_run_participants(run_dir, db_fallback)
    assert src == "SOCIETY_JSON"
    assert [p["agent_id"] for p in eligible] == [1]
    assert [p["agent_id"] for p in excluded] == [12]
    assert eligible[0]["full_name"] == "Giám đốc Pilot"
    assert eligible[0]["role_title"] == "Giám đốc Dự án"

    rep = evaluate_run_competency(run_dir=run_dir, fallback_personas=db_fallback, bypass_cache=True)
    assert rep["cohort_summary"]["eligible_bql_n"] == 1
    assert rep["cohort_summary"]["excluded_count"] == 1
    models, fams = extract_run_models(run_dir)
    assert models == ["openai/gpt-5.4-mini"]
    assert fams == ["openai"]


def test_eval_04_prepost_quiz_compiler_and_parser_safety(tmp_path: Path):
    """TC-EVAL-04: Pre/Post QuestionnaireStep uses OPT_A..OPT_D/CHUA_BIET, Pilot software_ids, and lifecycle completed_step_count guard."""
    import yaml
    from agentsociety2.backend.services.urban_sim.competency import QUIZ_CHOICE_CODES
    from agentsociety2.backend.services.urban_sim.lifecycle import _count_expected_top_level_steps, derive_execution_phase
    from agentsociety2.society.models import QuestionItem
    from agentsociety2.society.questionnaire import _parse_question_answer

    # Verify questionnaire.py parser safety (FND-EVAL-13)
    q_item = QuestionItem(
        id="q1",
        prompt="Chọn câu đúng",
        response_type="choice",
        choices=list(QUIZ_CHOICE_CODES),
    )
    ans_idk = _parse_question_answer(q_item, '{"reason": "chưa làm bao giờ", "answer": "Tôi không biết"}')
    assert ans_idk.parse_success is False  # NEVER silently flipped to OPT_B!
    ans_chua = _parse_question_answer(q_item, '{"reason": "chưa làm", "answer": "CHUA_BIET"}')
    assert ans_chua.parse_success is True and ans_chua.parsed_value == "CHUA_BIET"
    ans_b = _parse_question_answer(q_item, '{"reason": "biết rồi", "answer": "Chọn OPT_B"}')
    assert ans_b.parse_success is True and ans_b.parsed_value == "OPT_B"

    # Compiler emits 3 steps + separate competency_quiz_key.json when only prepost quiz enabled
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    proj.enable_sociological_debrief = False
    proj.enable_competency_prepost_quiz = True
    proj.pilot_mode = True
    with Session(get_engine(tmp_path)) as sess:
        personas = sess.exec(
            __import__("sqlmodel").select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)
        ).all()
        atlas = sess.get(UrbanSimAtlasConfig, proj.id)
        run_dir = tmp_path / "run_quiz_compile"
        bundle = compile_run_from_db(
            project=proj,
            personas=personas,
            atlas=atlas,
            zones=[],
            run_dir=run_dir,
            workspace_root=tmp_path,
        )

    steps_doc = yaml.safe_load(bundle.steps_path.read_text(encoding="utf-8"))
    steps = steps_doc["steps"]
    assert len(steps) == 3
    assert steps[0]["type"] == "questionnaire" and steps[0]["questionnaire_id"] == "bql_competency_pre"
    assert steps[1]["type"] == "run"
    assert steps[2]["type"] == "questionnaire" and steps[2]["questionnaire_id"] == "bql_competency_post"
    # Answer keys MUST NOT appear in steps.yaml
    assert "correct_choice" not in bundle.steps_path.read_text(encoding="utf-8")
    assert (run_dir / "init" / "competency_quiz_key.json").is_file()
    assert _count_expected_top_level_steps(run_dir) == 3

    # Lifecycle execution_phase check (3-step legacy Quiz)
    assert derive_execution_phase(run_dir, "RUNNING", 0, 8) == "PRE_QUIZ"
    (run_dir / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 2}), encoding="utf-8")
    assert derive_execution_phase(run_dir, "RUNNING", 8, 8) == "POST_QUIZ"
    (run_dir / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 3}), encoding="utf-8")
    assert derive_execution_phase(run_dir, "RUNNING", 8, 8) == "DONE"

    # When both debrief + prepost quiz enabled -> 4 steps: pre, run, debrief, post
    proj.enable_sociological_debrief = True
    run_dir_4 = tmp_path / "run_debrief_and_quiz_compile"
    bundle_4 = compile_run_from_db(
        project=proj,
        personas=personas,
        atlas=atlas,
        zones=[],
        run_dir=run_dir_4,
        workspace_root=tmp_path,
    )
    steps_4 = yaml.safe_load(bundle_4.steps_path.read_text(encoding="utf-8"))["steps"]
    assert [s.get("questionnaire_id") or s["type"] for s in steps_4] == [
        "bql_competency_pre",
        "run",
        "bql_sociological_debrief",
        "bql_competency_post",
    ]
    assert derive_execution_phase(run_dir_4, "RUNNING", 0, 8) == "PRE_QUIZ"
    (run_dir_4 / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 2}), encoding="utf-8")
    assert derive_execution_phase(run_dir_4, "RUNNING", 8, 8) == "POST_DEBRIEF"
    (run_dir_4 / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 3}), encoding="utf-8")
    assert derive_execution_phase(run_dir_4, "RUNNING", 8, 8) == "POST_QUIZ"


def test_eval_05_ai_audit_security_ssrf_and_pii_redaction(tmp_path: Path, monkeypatch):
    """TC-EVAL-05: SSRF blocked (400), deleted judge ID (400), PII masked, citation verifier flags hallucinated seq, Same-Family Bias."""
    from agentsociety2.backend.services.platform_resources import PlatformLLMConfig, merge_llm_entries
    from agentsociety2.backend.services.urban_sim.competency import (
        normalize_model_family,
        redact_sensitive_text,
        verify_audit_citations,
    )

    # Family normalization across gateway prefixes
    assert normalize_model_family("openai/gpt-5.4-mini") == "openai"
    assert normalize_model_family("openrouter/anthropic/claude-sonnet-4") == "anthropic"
    assert normalize_model_family("gpt-5.5") == "openai"

    # PII + secret redaction
    raw_txt = "Gọi cư dân 0912345678, email lan.nguyen@example.com, CCCD 001092001234, Bearer sk-proj-abcdefghijklmno"
    red = redact_sensitive_text(raw_txt)
    assert "0912345678" not in red
    assert "lan.nguyen@example.com" not in red
    assert "001092001234" not in red
    assert "sk-proj-abcdefghijklmno" not in red

    # Citation verifier flags hallucinated seq & wrong step
    cites, unverified = verify_audit_citations(
        [
            {"seq": 5, "step_index": 1, "quote": "real"},
            {"seq": 9999, "step_index": 1, "quote": "fake seq"},
        ],
        valid_seqs={5},
        valid_steps={1, 2},
    )
    assert unverified == 1
    assert cites[0]["verified"] is True
    assert cites[1]["verified"] is False and "UNVERIFIED_CITATION" in (cites[1]["flag"] or "")

    # REST API rejects SSRF & unknown judge_llm_config_id with 400
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    run_dir = tmp_path / "urban_sim_runs" / proj.slug / "urbrun_sec"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "SOCIETY.json").write_text(json.dumps({"agent_specs": []}), encoding="utf-8")

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id="urbrun_sec",
                project_id=proj.id,
                run_number=1,
                run_dir=str(run_dir),
                status="COMPLETED",
                step_count=1,
                total_steps=1,
            )
        )
        ssrf_cfg = PlatformLLMConfig(
            id="cfg_ssrf",
            name="Bad SSRF",
            config_json=merge_llm_entries(
                [{"provider": "openai", "model": "gpt-4o", "base_url": "http://127.0.0.1:9999/v1", "api_key": "sk-test-1234567890"}],
                None,
                tmp_path,
            ),
        )
        sess.add(ssrf_cfg)
        sess.commit()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        r_missing = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/urbrun_sec/competency/ai-audit",
            headers=headers,
            json={"judge_llm_config_id": "nonexistent_id"},
        )
        assert r_missing.status_code == 400
        r_ssrf = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/urbrun_sec/competency/ai-audit",
            headers=headers,
            json={"judge_llm_config_id": "cfg_ssrf"},
        )
        assert r_ssrf.status_code == 400


@pytest.mark.asyncio
async def test_eval_06_ai_audit_concurrency_atomic_and_delete_run(tmp_path: Path, monkeypatch):
    """TC-EVAL-06: Double-submit returns 409, immutable v{N}, LLM_STATS untouched, delete_run cancels cleanly, startup reconcile."""
    from agentsociety2.backend.services.platform_resources import PlatformLLMConfig, merge_llm_entries
    from agentsociety2.backend.services.urban_sim.competency import get_competency_audit_manager
    from agentsociety2.config.llm_dispatcher import LLMClient

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    run_id = "urbrun_audit_race"
    run_dir = tmp_path / "urban_sim_runs" / proj.slug / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    llm_stats_orig = json.dumps({"models": {"gpt-5.4-mini": {"calls": 3, "input": 100, "output": 20, "cached_input": 0}}})
    (run_dir / "LLM_STATS.json").write_text(llm_stats_orig, encoding="utf-8")
    (run_dir / "SOCIETY.json").write_text(
        json.dumps(
            {
                "agent_specs": [
                    {"id": 3, "profile": {"name": "Lễ tân", "role": "Lễ tân", "role_code": "BQL_RECEPTIONIST", "group_type": "BQL", "software_access_enabled": True}}
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "urban_events.jsonl").write_text(
        json.dumps({"seq": 10, "stream": "WEB", "agent_id": 3, "action": "login_qltn_portal", "ok": True, "details": {"url": "https://example.com/home"}}) + "\n",
        encoding="utf-8",
    )

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id=run_id,
                project_id=proj.id,
                run_number=1,
                run_dir=str(run_dir),
                status="COMPLETED",
                step_count=1,
                total_steps=1,
            )
        )
        sess.add(
            PlatformLLMConfig(
                id="cfg_judge_ok",
                name="Anthropic Judge",
                config_json=merge_llm_entries(
                    [{"provider": "anthropic", "model": "claude-3-7-sonnet-latest", "base_url": "https://api.anthropic.com", "api_key": "sk-ant-test-123456"}],
                    None,
                    tmp_path,
                ),
            )
        )
        sess.commit()

    async def _mock_call(self, messages=None, **kwargs):
        await asyncio.sleep(0.15)
        self._record_tokens(
            self.model_name,
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40)),
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "scores": {"navigation": 2, "form_execution": 1, "help_seeking": 2, "closed_loop": 1},
                                "primary_root_cause": "UI_UX_FRICTION",
                                "diagnosis_summary": "Cần thêm nút rõ ràng hơn.",
                                "citations": [{"seq": 10, "step_index": None, "quote": "login"}],
                                "recommendations": ["Thêm menu nổi bật"],
                            },
                            ensure_ascii=False,
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(LLMClient, "call", _mock_call)

    mgr = get_competency_audit_manager()
    with Session(get_engine(tmp_path)) as sess:
        st1 = await mgr.start_audit(
            run_id=run_id,
            run_dir=run_dir,
            run_meta={"status": "COMPLETED", "step_count": 1},
            judge_llm_config_id="cfg_judge_ok",
            session=sess,
            workspace_root=tmp_path,
            project_rubric_json=None,
            fallback_personas=[],
        )
        assert st1["status"] == "QUEUED"
        assert st1["same_family_bias_warning"] is False  # anthropic judge vs openai run

        # Concurrent double submit -> 409
        with pytest.raises(HTTPException) as exc_info:
            await mgr.start_audit(
                run_id=run_id,
                run_dir=run_dir,
                run_meta={"status": "COMPLETED", "step_count": 1},
                judge_llm_config_id="cfg_judge_ok",
                session=sess,
                workspace_root=tmp_path,
                project_rubric_json=None,
                fallback_personas=[],
            )
        assert exc_info.value.status_code == 409

    # Wait for background completion
    task = mgr._tasks.get(run_id)
    if task is not None:
        await task
    state_v1 = mgr.get_audit_state(run_dir)
    assert state_v1["status"]["status"] == "COMPLETED"
    assert state_v1["versions"] == [1]
    assert (run_dir / "artifacts" / "competency_audit" / "competency_audit_v1.json").is_file()
    # Original LLM_STATS.json untouched!
    assert (run_dir / "LLM_STATS.json").read_text(encoding="utf-8") == llm_stats_orig

    # Test startup reconcile on stuck RUNNING file
    status_fp = run_dir / "artifacts" / "competency_audit" / "competency_audit_status.json"
    status_fp.write_text(json.dumps({"status": "RUNNING", "run_id": run_id}), encoding="utf-8")
    mgr.reconcile_on_startup(tmp_path)
    assert json.loads(status_fp.read_text(encoding="utf-8"))["status"] == "INTERRUPTED_ON_RESTART"

    # Test delete_run cancels active task cleanly & removes directory without orphan recreation
    with Session(get_engine(tmp_path)) as sess:
        await mgr.start_audit(
            run_id=run_id,
            run_dir=run_dir,
            run_meta={"status": "COMPLETED", "step_count": 1},
            judge_llm_config_id="cfg_judge_ok",
            session=sess,
            workspace_root=tmp_path,
            project_rubric_json=None,
            fallback_personas=[],
        )
    lc = UrbanSimLifecycleManager()
    await lc.delete_run(proj.id, run_id)
    assert not run_dir.exists()


def test_eval_07_competency_endpoints_and_export(tmp_path: Path, monkeypatch):
    """TC-EVAL-07: GET /competency and GET /competency/export?format=markdown|json with nosniff."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    run_id = "urbrun_export_check"
    run_dir = tmp_path / "urban_sim_runs" / proj.slug / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "SOCIETY.json").write_text(
        json.dumps(
            {
                "agent_specs": [
                    {"id": 3, "profile": {"name": "Lễ tân", "role": "Lễ tân", "role_code": "BQL_RECEPTIONIST", "group_type": "BQL", "software_access_enabled": True}}
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "urban_events.jsonl").write_text(
        json.dumps({"seq": 1, "stream": "WEB", "agent_id": 3, "action": "login_qltn_portal", "ok": True, "details": {"url": "https://mulberrylane.sandbox.demego.vn/home"}}) + "\n",
        encoding="utf-8",
    )

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id=run_id,
                project_id=proj.id,
                run_number=2,
                run_dir=str(run_dir),
                status="COMPLETED",
                step_count=1,
                total_steps=1,
            )
        )
        sess.commit()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        r_comp = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/competency", headers=headers)
        assert r_comp.status_code == 200
        cdata = r_comp.json()["data"]
        assert cdata["cohort_summary"]["eligible_bql_n"] == 1
        assert cdata["agents"][0]["miller_level"] == "M1"

        r_md = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/competency/export?format=markdown",
            headers=headers,
        )
        assert r_md.status_code == 200
        assert r_md.headers.get("x-content-type-options") == "nosniff"
        assert "attachment;" in (r_md.headers.get("content-disposition") or "")
        assert "Miller" in r_md.text

        r_json = client.get(
            f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/competency/export?format=json",
            headers=headers,
        )
        assert r_json.status_code == 200
        assert r_json.headers.get("x-content-type-options") == "nosniff"
        assert r_json.json()["competency"]["cohort_summary"]["eligible_bql_n"] == 1


@pytest.mark.asyncio
async def test_aud_01_pre_action_thought_prefix_cache_and_episode_labels(tmp_path: Path):
    """TC-AUD-01: Pre-action thought opt-in uniform across 21 PersonAgents (Prompt Prefix Cache) & 9/9 episode labels."""
    from agentsociety2.agent.base.tool_schema import react_tool_schemas
    from agentsociety2.agent.person import PersonAgent
    from agentsociety2.backend.services.urban_sim.compiler import compile_run_from_db
    from agentsociety2.backend.services.urban_sim.db import (
        UrbanSimAtlasConfig,
        UrbanSimPersona,
        UrbanSimProject,
        UrbanSimZone,
    )
    from agentsociety2.backend.services.urban_sim.timeline import build_agent_timeline
    from agentsociety2.skills.experiment.models import AGENT_CONFIG_KEYS, split_agent_kwargs

    assert "require_pre_action_thought" in AGENT_CONFIG_KEYS

    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    run_dir = tmp_path / "run_aud_01"
    with Session(get_engine(tmp_path)) as sess:
        db_proj = sess.get(UrbanSimProject, proj.id)
        personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)))
        atlas = sess.exec(select(UrbanSimAtlasConfig).where(UrbanSimAtlasConfig.project_id == proj.id)).first()
        zones = list(sess.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == proj.id)))
        bundle = compile_run_from_db(
            project=db_proj,
            personas=personas,
            atlas=atlas,
            zones=zones,
            run_dir=run_dir,
            workspace_root=tmp_path,
        )

    init_cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
    assert len(init_cfg["agents"]) >= 2
    for agent_entry in init_cfg["agents"]:
        aid = int(agent_entry["agent_id"])
        profile, config = split_agent_kwargs(aid, agent_entry["kwargs"])
        assert config.get("require_pre_action_thought") is True
        assert "require_pre_action_thought" not in profile

    # Verify cross-agent tool schema equality (tools prefix identical for BQL & Resident)
    class _DummyProxy:
        env = None
        llm = SimpleNamespace(default=SimpleNamespace(model_name="gpt-5.4-mini"))

    bql_ws = tmp_path / "ws_bql"
    res_ws = tmp_path / "ws_res"
    PersonAgent.create(bql_ws, {"id": 3, "name": "Lễ tân"}, {"require_pre_action_thought": True})
    PersonAgent.create(res_ws, {"id": 12, "name": "Cư dân"}, {"require_pre_action_thought": True})
    a_bql = await PersonAgent.from_workspace(bql_ws, _DummyProxy())
    a_res = await PersonAgent.from_workspace(res_ws, _DummyProxy())

    tools_bql = react_tool_schemas(readonly=False, overrides=a_bql._react_tool_overrides(readonly=False))
    tools_res = react_tool_schemas(readonly=False, overrides=a_res._react_tool_overrides(readonly=False))
    assert tools_bql == tools_res
    ask_env_bql = next(t for t in tools_bql if t["function"]["name"] == "ask_env")
    assert "thought" in ask_env_bql["function"]["parameters"]["properties"]
    assert ask_env_bql["function"]["parameters"]["required"][0] == "thought"

    # ask / readonly mode must stay untouched
    tools_ro = react_tool_schemas(readonly=True, overrides=a_bql._react_tool_overrides(readonly=True))
    ask_env_ro = next(t for t in tools_ro if t["function"]["name"] == "ask_env")
    assert "thought" not in ask_env_ro["function"]["parameters"]["properties"]

    # _parse_react_turn extracts thought when content=None and preserves _decisions_assistant_message
    msg1 = SimpleNamespace(
        content=None,
        reasoning_content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="ask_env",
                    arguments=json.dumps(
                        {
                            "thought": "Tôi sẽ mở mục Phiếu yêu cầu trên QLTN để kiểm tra phản ánh mới.",
                            "instruction": "click Phiếu yêu cầu",
                            "readonly": False,
                            "variables": {"text": "Phiếu yêu cầu"},
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        ],
    )
    resp1 = SimpleNamespace(choices=[SimpleNamespace(message=msg1)])
    turn1 = a_bql._parse_react_turn(resp1, readonly=False)
    assert turn1.error == ""
    assert turn1.thought == "Tôi sẽ mở mục Phiếu yêu cầu trên QLTN để kiểm tra phản ánh mới."
    echo_args = json.loads(turn1.assistant_message["tool_calls"][0]["function"]["arguments"])
    assert echo_args["thought"] == turn1.thought
    assert "thought" not in a_bql._build_env_tool_context(turn1.decisions[0].args)

    # Fallback reading reasoning_content on raw_message without mutating assistant_message
    msg2 = SimpleNamespace(
        content=None,
        reasoning_content="Suy nghĩ từ reasoning_content nguyên bản.",
        tool_calls=[
            SimpleNamespace(
                id="call_2",
                function=SimpleNamespace(
                    name="todo_list",
                    arguments="{}",
                ),
            )
        ],
    )
    resp2 = SimpleNamespace(choices=[SimpleNamespace(message=msg2)])
    turn2 = a_bql._parse_react_turn(resp2, readonly=False)
    assert turn2.thought == "Suy nghĩ từ reasoning_content nguyên bản."
    assert "reasoning_content" not in (turn2.assistant_message or {})

    # Check 9/9 MemoryEpisodeType Vietnamese labels in timeline.py
    ep_dir = run_dir / "agents" / "agent_0003" / "memory"
    ep_dir.mkdir(parents=True, exist_ok=True)
    all_types = [
        "observation",
        "routine",
        "goal",
        "commitment",
        "resolution",
        "preference",
        "identity",
        "conflict",
        "relationship",
    ]
    (ep_dir / "episodes.jsonl").write_text(
        "\n".join(
            json.dumps(
                {"id": f"e{i}", "step_index": 1, "time": "2026-06-15T08:00:00+07:00", "type": tp, "text": f"text {tp}"},
                ensure_ascii=False,
            )
            for i, tp in enumerate(all_types, start=1)
        )
        + "\n",
        encoding="utf-8",
    )
    tl = build_agent_timeline(
        run_dir=run_dir,
        persona={"agent_id": 3, "full_name": "Lễ tân", "group_type": "BQL"},
    )
    lbl_map = {e["type"]: e["type_label"] for e in tl["steps"][0]["episodes"]}
    assert lbl_map["goal"] == "Mục tiêu tiếp theo"
    assert lbl_map["commitment"] == "Cam kết"
    assert lbl_map["resolution"] == "Hướng giải quyết"
    assert lbl_map["preference"] == "Thói quen / Sở thích"
    assert lbl_map["identity"] == "Bản sắc / Vai trò"
    assert lbl_map["conflict"] == "Vướng mắc / Xung đột"
    assert lbl_map["relationship"] == "Quan hệ phối hợp"


@pytest.mark.asyncio
async def test_aud_02_playwright_readiness_gate_and_popover_dismiss(tmp_path: Path):
    """TC-AUD-02: Playwright readiness gate waits out splash, times out safely, dismisses hover, and writes atomic meta."""
    from agentsociety2.contrib.env.demego_web_portal import DemegoWebPortalEnv

    shots_dir = tmp_path / "shots"
    env = DemegoWebPortalEnv(
        allowed_agent_ids=[3],
        default_portal_url="https://mulberrylane.sandbox.demego.vn",
        screenshots_dir=str(shots_dir),
    )
    try:
        page = await env._get_page(3)
        await page.set_content(
            """
            <html><body>
              <div id="splash">Demepro - Đang tải ứng dụng...</div>
              <main id="app" style="display:none">
                <h1>Phiếu yêu cầu</h1>
                <button id="b1">Tạo mới</button>
                <a href="/ext/ticket">Danh sách</a>
              </main>
              <script>
                setTimeout(() => {
                  document.getElementById('splash').style.display = 'none';
                  document.getElementById('app').style.display = 'block';
                }, 400);
              </script>
            </body></html>
            """
        )
        res_ready = await env._wait_until_page_ready(page, timeout_ms=4000, initial_settle_ms=100)
        assert res_ready["capture_status"] == "READY"
        assert res_ready["ready"] is True

        await env._dismiss_hover_overlays(page)
        shot_ok, bytes_ok = await env._capture_screenshot(
            3,
            page,
            "ticket_ready",
            capture_status=res_ready["capture_status"],
            current_url="https://mulberrylane.sandbox.demego.vn/ext/ticket",
        )
        assert shot_ok is not None and (bytes_ok or 0) > 0
        latest_bytes_before = (shots_dir / "agent_3_latest.jpg").read_bytes()

        # Now simulate stuck splash -> LOADING_TIMEOUT must NOT overwrite latest.jpg but MUST update latest.meta.json
        await page.set_content("<html><body><div>Demepro — Đang tải ứng dụng...</div></body></html>")
        res_to = await env._wait_until_page_ready(page, timeout_ms=500, initial_settle_ms=50)
        assert res_to["capture_status"] == "LOADING_TIMEOUT"
        assert res_to["ready"] is False
        shot_to, _ = await env._capture_screenshot(
            3,
            page,
            "nav_timeout",
            capture_status="LOADING_TIMEOUT",
            current_url="https://mulberrylane.sandbox.demego.vn/ext/car-parkings",
        )
        assert shot_to is not None
        assert (shots_dir / "agent_3_latest.jpg").read_bytes() == latest_bytes_before
        meta = json.loads((shots_dir / "agent_3_latest.meta.json").read_text(encoding="utf-8"))
        assert meta["capture_status"] == "LOADING_TIMEOUT"
        assert meta["current_route_path"] == "/ext/car-parkings"
        assert meta["latest_image_route_path"] == "/ext/ticket"
    finally:
        await env.close()


def test_aud_03_atlas_rejects_loading_and_stale_route_screenshot(tmp_path: Path):
    """TC-AUD-03: EvidenceAtlasSupportEnv rejects LOADING_TIMEOUT, route mismatch (/home vs /car-parkings), and <18KB unverified files."""
    from agentsociety2.contrib.env.evidence_atlas_support import EvidenceAtlasSupportEnv

    shots_dir = tmp_path / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    atlas_env = EvidenceAtlasSupportEnv(
        allowed_agent_ids=[3],
        screenshots_dir=str(shots_dir),
    )

    latest_jpg = shots_dir / "agent_3_latest.jpg"
    meta_json = shots_dir / "agent_3_latest.meta.json"

    # Case 1: unverified small file (<18KB) without meta -> rejected
    latest_jpg.write_bytes(b"\xff\xd8\xff" + b"0" * 13000)
    assert atlas_env._build_latest_screenshot_attachment(3, "/ext/ticket") == []

    # Case 2: meta says LOADING_TIMEOUT -> rejected even if file >= 18KB
    latest_jpg.write_bytes(b"\xff\xd8\xff" + b"1" * 25000)
    meta_json.write_text(
        json.dumps({"capture_status": "LOADING_TIMEOUT", "latest_image_route_path": "/ext/ticket"}),
        encoding="utf-8",
    )
    assert atlas_env._build_latest_screenshot_attachment(3, "/ext/ticket") == []

    # Case 3: meta says READY for /home, but agent asks on /ext/car-parkings/ -> stale wrong-route rejected
    meta_json.write_text(
        json.dumps({"capture_status": "READY", "latest_image_route_path": "/home", "latest_image_url": "https://example.com/home"}),
        encoding="utf-8",
    )
    assert atlas_env._build_latest_screenshot_attachment(3, "/ext/car-parkings/") == []

    # Case 4: meta says READY for /ext/ticket/ matching /ext/ticket -> attached!
    meta_json.write_text(
        json.dumps({"capture_status": "READY", "latest_image_route_path": "/ext/ticket/"}),
        encoding="utf-8",
    )
    atts = atlas_env._build_latest_screenshot_attachment(3, "/ext/ticket")
    assert len(atts) == 1
    assert atts[0]["file_name"] == "agent_3_latest.jpg"


def test_aud_04_legacy_run_screenshot_status_across_all_three_apis(tmp_path: Path, monkeypatch):
    """TC-AUD-04: Read-only LOADING_SPLASH_SUSPECTED (<18KB) vs READY returned across /state, /events, and /timeline for legacy runs."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    headers = _client_headers(monkeypatch)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    run_id = "urbrun_legacy_aud"
    run_dir = tmp_path / "urban_sim_runs" / proj.slug / run_id
    shots_dir = run_dir / "artifacts" / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    small_shot = shots_dir / "agent_3_s1_nav_20261125.jpg"
    normal_shot = shots_dir / "agent_3_s2_click_20261125.jpg"
    latest_shot = shots_dir / "agent_3_latest.jpg"
    small_shot.write_bytes(b"a" * 12900)
    normal_shot.write_bytes(b"b" * 24000)
    latest_shot.write_bytes(b"c" * 12800)

    (run_dir / "urban_events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "stream": "WEB",
                        "agent_id": 3,
                        "agent_name": "Lễ tân",
                        "role_title": "Lễ tân",
                        "action": "navigate_web_path",
                        "summary": "Chuyển trang",
                        "ok": True,
                        "sim_time": "2026-06-15T08:00:00+07:00",
                        "wall_time": "2026-11-25T01:00:00Z",
                        "screenshot_file": small_shot.name,
                        "details": {"url": "https://mulberrylane.sandbox.demego.vn/home"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "stream": "WEB",
                        "agent_id": 3,
                        "agent_name": "Lễ tân",
                        "role_title": "Lễ tân",
                        "action": "click_web_text",
                        "summary": "Mở Phiếu yêu cầu",
                        "ok": True,
                        "sim_time": "2026-06-15T08:15:00+07:00",
                        "wall_time": "2026-11-25T01:01:00Z",
                        "screenshot_file": normal_shot.name,
                        "details": {"url": "https://mulberrylane.sandbox.demego.vn/ext/ticket"},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with Session(get_engine(tmp_path)) as sess:
        sess.add(
            UrbanSimRun(
                id=run_id,
                project_id=proj.id,
                run_number=2,
                run_dir=str(run_dir),
                status="COMPLETED",
                step_count=2,
                total_steps=2,
            )
        )
        sess.commit()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        st_res = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/state", headers=headers)
        assert st_res.status_code == 200
        a3 = next(a for a in st_res.json()["agent_statuses"] if a["agent_id"] == 3)
        assert a3["latest_screenshot_status"] == "LOADING_SPLASH_SUSPECTED"
        assert a3["latest_screenshot_bytes"] == 12800

        ev_res = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/events", headers=headers)
        assert ev_res.status_code == 200
        items = ev_res.json()["items"]
        assert items[0]["screenshot_status"] == "LOADING_SPLASH_SUSPECTED"
        assert items[0]["screenshot_bytes"] == 12900
        assert items[1]["screenshot_status"] == "READY"
        assert items[1]["screenshot_bytes"] == 24000

        tl_res = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/agents/3/timeline", headers=headers)
        assert tl_res.status_code == 200
        tl_data = tl_res.json()
        assert tl_data["summary"]["loading_screenshots_count"] == 1
        assert tl_data["steps"][0]["web_events"][0]["screenshot_status"] == "LOADING_SPLASH_SUSPECTED"
        assert tl_data["steps"][0]["web_events"][1]["screenshot_status"] == "READY"


@pytest.mark.asyncio
async def test_fw_01_framework_agnostic_readiness_xhr_aria_dom_quiescence_and_main_excerpt(
    tmp_path: Path, monkeypatch
):
    """Verify framework-agnostic XHR/Fetch + ARIA + DOM quiescence readiness, main_excerpt/table_rows, and ok=False logging."""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from agentsociety2.contrib.env.demego_web_portal import DemegoWebPortalEnv

    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")

    html_page = (
        "<!DOCTYPE html><html><body>"
        "<aside style='width:200px'>" + ("Menu mục " * 140) + "</aside>"
        "<main id='app'>"
        "  <h1>Danh sách công việc</h1>"
        "  <button id='loadBtn' onclick='loadRows()'>Tải việc chờ</button>"
        "  <div id='status' role='progressbar' style='display:none'>Loading</div>"
        "  <table aria-busy='false'><thead><tr><th>Mã</th><th>Tiêu đề</th></tr></thead>"
        "    <tbody id='rows'></tbody>"
        "  </table>"
        "</main>"
        "<script>"
        "async function loadRows() {"
        "  const tbl = document.querySelector('table');"
        "  const st = document.getElementById('status');"
        "  tbl.setAttribute('aria-busy', 'true');"
        "  st.style.display = 'block';"
        "  try {"
        "    const r = await fetch('/api/items');"
        "    const data = await r.json();"
        "    document.getElementById('rows').innerHTML = data.map(x => `<tr><td>${x.id}</td><td>${x.title}</td></tr>`).join('');"
        "  } finally {"
        "    st.style.display = 'none';"
        "    tbl.setAttribute('aria-busy', 'false');"
        "  }"
        "}"
        "</script></body></html>"
    )

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path.startswith("/api/items"):
                time.sleep(0.45)
                payload = json.dumps(
                    [
                        {"id": "CV-01", "title": "Kiểm tra rung thang máy ZA"},
                        {"id": "CV-02", "title": "Sửa barie hầm B1"},
                        {"id": "CV-03", "title": "Kiểm tra áp lực nước ZA12"},
                    ],
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(payload)
                return
            body = html_page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    events_log = tmp_path / "urban_events.jsonl"
    shots_dir = tmp_path / "shots"
    env = DemegoWebPortalEnv(
        allowed_agent_ids=[1],
        default_portal_url=f"http://127.0.0.1:{server.server_port}/tasks",
        screenshots_dir=str(shots_dir),
        events_log_path=str(events_log),
    )
    try:
        nav = await env.navigate_web_path(agent_id=1, path="/tasks")
        assert nav["ok"] is True
        clicked = await env.click_web_text(agent_id=1, text="Tải việc chờ")
        assert clicked["ok"] is True
        assert clicked["capture_status"] == "READY"
        snap = clicked["snapshot"]
        assert "Kiểm tra rung thang máy ZA" in snap["main_excerpt"]
        assert len(snap["table_rows"]) == 3
        assert any("CV-02" in row for row in snap["table_rows"])

        # Missing button must emit ok=False WEB event to urban_events.jsonl
        miss = await env.click_web_text(agent_id=1, text="Nút không hề tồn tại")
        assert miss["ok"] is False
        ev_lines = [json.loads(ln) for ln in events_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert any(e.get("action") == "click_web_text" and e.get("ok") is False for e in ev_lines)
    finally:
        await env.close()
        server.shutdown()


@pytest.mark.asyncio
async def test_fw_02_react_router_cskh_routing_hint_naturalize_and_timeline_label():
    """Verify ReActRouter CSKH routing guard, expanded naturalizer, Failure-Escalation rules, and timeline label priority."""
    from agentsociety2.backend.services.urban_sim.compiler import URBAN_SIM_BASE_RULES
    from agentsociety2.backend.services.urban_sim.timeline import _friendly_env_tool_label
    from agentsociety2.contrib.env.evidence_atlas_support import EvidenceAtlasSupportEnv, naturalize_support_question
    from agentsociety2.env.router_react import ReActRouter

    atlas_env = EvidenceAtlasSupportEnv(allowed_agent_ids=[1])
    router = ReActRouter(env_modules=[atlas_env], max_steps=2, final_summary_enabled=False)

    prompt = router._build_initial_prompt(
        "Tôi đang ở trang /ext/internal-tasks, số liệu bằng 0 dù badge 99+.",
        {"agent_id": 1, "attach_screenshot": True},
        readonly=False,
    )
    assert "CRITICAL SUPPORT ROUTING" in prompt
    assert "ask_atlas_support" in prompt

    captured = {}

    async def _fake_ask(self_mod, agent_id: int = 0, **kwargs):
        captured["agent_id"] = agent_id
        captured.update(kwargs)
        return {"ok": True}

    atlas_tool = router._tool_name_to_tool_obj["ask_atlas_support"]
    orig_fn = atlas_tool.fn
    atlas_tool.fn = _fake_ask
    try:
        await router._execute_tool(
            "ask_atlas_support",
            {"agent_id": 9, "question": "Màn hình báo không có quyền thì làm sao?"},
            readonly=False,
            ctx={"agent_id": 1, "attach_screenshot": True},
        )
        assert captured["agent_id"] == 1
        assert captured["attach_screenshot"] is True
    finally:
        atlas_tool.fn = orig_fn

    assert (
        naturalize_support_question(
            "Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua ask_atlas_support: biểu mẫu báo Không có loại phiếu."
        )
        == "Biểu mẫu báo Không có loại phiếu."
    )
    assert (
        naturalize_support_question("Hỏi bộ phận hỗ trợ: tôi cần tìm danh sách công việc thực thi")
        == "Tôi cần tìm danh sách công việc thực thi"
    )

    assert "Failure-Escalation" in URBAN_SIM_BASE_RULES
    assert 'ctx={"attach_screenshot": true}' in URBAN_SIM_BASE_RULES

    from agentsociety2.contrib.env.demego_web_portal import DemegoWebPortalEnv

    skill_path = DemegoWebPortalEnv.skill_dirs()[0] / "bql-qltn-ops-vn" / "SKILL.md"
    skill_txt = skill_path.read_text(encoding="utf-8")
    assert "Failure-Escalation" in skill_txt

    # Shadowed login_qltn_portal (already_logged_in: true) must NOT hide click_web_text or ask_atlas_support
    shadow_click = '{"status": "success", "login_qltn_portal": {"ok": true, "already_logged_in": true}, "click_web_text": {"ok": true}}'
    assert _friendly_env_tool_label("ask_env", shadow_click) == "Bấm thao tác trên QLTN"

    truncated_obs = '{"status": "success", "login_qltn_portal": {"ok": true, "already_logged_in": true}}'
    assert (
        _friendly_env_tool_label(
            "ask_env",
            truncated_obs,
            {"instruction": "Tôi bấm không mở được", "ctx": {"attach_screenshot": True}},
        )
        == "Nhắn hỏi CSKH Thần Nông"
    )


def test_monitor_state_sim_clock_day_night_and_agent_activity_summary(tmp_path: Path, monkeypatch):
    """Verify /state returns sim_clock (day/night + period) and rich per-agent activity summary."""
    import yaml

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    headers = _client_headers(monkeypatch)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        proj = client.get("/api/v1/urban-sim/projects", headers=headers).json()["items"][0]
        pid = proj["id"]

        run_id = "urbrun_099_clock"
        run_dir = tmp_path / "urban_sim_runs" / "mulberrylane" / run_id
        (run_dir / "init").mkdir(parents=True, exist_ok=True)
        (run_dir / "init" / "steps.yaml").write_text(
            yaml.safe_dump(
                {
                    "start_t": "2026-06-15T08:00:00+07:00",
                    "steps": [{"type": "run", "num_steps": 20, "tick": 900}],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with Session(get_engine(tmp_path)) as sess:
            sess.add(
                UrbanSimRun(
                    id=run_id,
                    project_id=pid,
                    run_number=99,
                    run_dir=str(run_dir),
                    status="RUNNING",
                    step_count=0,
                    total_steps=20,
                    active_agent_count=21,
                    pilot_mode=False,
                    router_type="react",
                )
            )
            sess.commit()

        # Case 1: Before SOCIETY_STEP.json exists -> fallback cleanly to init/steps.yaml
        r0 = client.get(f"/api/v1/urban-sim/projects/{pid}/runs/{run_id}/state", headers=headers)
        assert r0.status_code == 200
        d0 = r0.json()
        assert d0["sim_clock"]["current_sim_time"] == "2026-06-15T08:00:00+07:00"
        assert d0["sim_clock"]["end_sim_time"] == "2026-06-15T13:00:00+07:00"
        assert d0["sim_clock"]["tick_seconds"] == 900
        assert d0["sim_clock"]["is_daytime"] is True
        assert d0["sim_clock"]["time_band"] == "MORNING_RUSH"
        assert d0["sim_clock"]["day_night_label_vi"] == "Ban ngày"

        # Case 2: Daytime tick + rich events + mailbox/incidents + workspace notes/todos/episodes
        (run_dir / SOCIETY_STEP_JSON).write_text(
            json.dumps(
                {
                    "current_time": "2026-06-15T08:15:00+07:00",
                    "step_count": 1,
                    "completed_step_count": 0,
                    "terminated": False,
                    "pending_update": None,
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "env" / "UrbanCommAndIncidentEnv" / "state").mkdir(parents=True, exist_ok=True)
        (run_dir / "env" / "UrbanCommAndIncidentEnv" / "state" / "ENV_STATE.json").write_text(
            json.dumps(
                {
                    "agent_zones": {"3": "LOBBY_MAIN", "12": "TOWER_A"},
                    "mailboxes": {
                        "3": [{"message_id": 1, "read": False}, {"message_id": 2, "read": True}],
                        "12": [{"message_id": 3, "read": False}],
                    },
                    "incidents": {
                        "INC-0001": {
                            "incident_id": "INC-0001",
                            "reporter_id": 12,
                            "reporter_name": "Bà Trần Thị Thúy",
                            "assigned_to_id": 3,
                            "zone_key": "TOWER_A",
                            "title": "Áp lực nước yếu",
                            "status": "OPEN",
                        },
                        "INC-0002": {
                            "incident_id": "INC-0002",
                            "reporter_id": 12,
                            "reporter_name": "Bà Trần Thị Thúy",
                            "assigned_to_id": 3,
                            "zone_key": "TOWER_A",
                            "title": "Đèn hành lang nhấp nháy",
                            "status": "RESOLVED",
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "env" / "DemegoWebPortalEnv" / "state").mkdir(parents=True, exist_ok=True)
        (run_dir / "env" / "DemegoWebPortalEnv" / "state" / "ENV_STATE.json").write_text(
            json.dumps(
                {
                    "last_urls": {"3": "https://mulberrylane.sandbox.demego.vn/tickets"},
                    "actions_count": {"3": 2},
                    "blocked_count": {"3": 1},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "env" / "EvidenceAtlasSupportEnv" / "state").mkdir(parents=True, exist_ok=True)
        (run_dir / "env" / "EvidenceAtlasSupportEnv" / "state" / "ENV_STATE.json").write_text(
            json.dumps({"total_asks_by_agent": {"3": 1}, "bot_sessions": {"3": "sess_3"}}),
            encoding="utf-8",
        )

        events = [
            {
                "seq": 1,
                "stream": "WEB",
                "agent_id": 3,
                "action": "login_qltn_portal",
                "summary": "Đăng nhập QLTN thành công",
                "ok": True,
                "sim_time": "2026-06-15T08:05:00+07:00",
            },
            {
                "seq": 2,
                "stream": "WEB",
                "agent_id": 3,
                "action": "click_web_text",
                "summary": "Không tìm thấy nút X",
                "ok": False,
                "sim_time": "2026-06-15T08:07:00+07:00",
            },
            {
                "seq": 3,
                "stream": "ATLAS",
                "agent_id": 3,
                "action": "ask_atlas_support",
                "summary": "Hỏi cách tạo phản ánh",
                "ok": True,
                "sim_time": "2026-06-15T08:08:00+07:00",
            },
            {
                "seq": 4,
                "stream": "COMM",
                "agent_id": 12,
                "action": "report_resident_incident",
                "summary": "Báo áp lực nước yếu tại ZA1201",
                "ok": True,
                "sim_time": "2026-06-15T08:10:00+07:00",
            },
            {
                "seq": 5,
                "stream": "INCIDENT",
                "agent_id": 3,
                "action": "manage_incident",
                "summary": "[INC-0001] -> IN_PROGRESS",
                "ok": True,
                "sim_time": "2026-06-15T08:12:00+07:00",
            },
            {
                "seq": 6,
                "stream": "COMM",
                "agent_id": 3,
                "action": "send_urban_message",
                "summary": "Lễ tân -> Bà Thúy: Đã tiếp nhận sự cố",
                "ok": True,
                "sim_time": "2026-06-15T08:14:00+07:00",
            },
        ]
        (run_dir / "urban_events.jsonl").write_text(
            "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events) + "\n",
            encoding="utf-8",
        )

        ag3_root = run_dir / "agents" / "agent_0003"
        (ag3_root / "memory").mkdir(parents=True, exist_ok=True)
        (ag3_root / "notes").mkdir(parents=True, exist_ok=True)
        (ag3_root / "memory" / "episodes.jsonl").write_text(
            '{"id":"e1"}\n{"id":"e2"}\n{"id":"e3"}\n',
            encoding="utf-8",
        )
        (ag3_root / "TODO.json").write_text(
            json.dumps(
                {
                    "todos": [
                        {"id": "t1", "title": "Tiếp nhận phản ánh", "status": "completed"},
                        {"id": "t2", "title": "Theo dõi xử lý", "status": "in_progress"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (ag3_root / "notes" / "atlas_guides.md").write_text("# Hướng dẫn QLTN\n", encoding="utf-8")

        r1 = client.get(f"/api/v1/urban-sim/projects/{pid}/runs/{run_id}/state", headers=headers)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["run"]["current_sim_time"] == "2026-06-15T08:15:00+07:00"
        assert d1["sim_clock"]["is_daytime"] is True
        assert d1["sim_clock"]["time_band"] == "MORNING_RUSH"
        assert d1["sim_clock"]["day_index"] == 1

        by_id = {a["agent_id"]: a for a in d1["agent_statuses"]}
        ag3 = by_id[3]
        assert ag3["web_actions_count"] == 2
        assert ag3["blocked_actions_count"] == 1
        assert ag3["atlas_asks_count"] == 1
        assert ag3["comm_actions_count"] == 1
        assert ag3["incident_actions_count"] == 1
        assert ag3["total_actions_count"] == 5
        assert ag3["web_failed_count"] == 1
        assert ag3["unread_messages_count"] == 1
        assert ag3["received_messages_count"] == 2
        assert ag3["incidents_related_count"] == 2
        assert ag3["incidents_open_count"] == 1
        assert ag3["episodes_count"] == 3
        assert ag3["todos_total"] == 2
        assert ag3["todos_completed"] == 1
        assert ag3["notes_count"] == 1
        assert ag3["last_action"] == "send_urban_message"
        assert ag3["last_action_stream"] == "COMM"
        assert ag3["last_action_sim_time"] == "2026-06-15T08:14:00+07:00"

        ag12 = by_id[12]
        assert ag12["comm_actions_count"] == 1
        assert ag12["total_actions_count"] == 1
        assert ag12["unread_messages_count"] == 1
        assert ag12["incidents_related_count"] == 2
        assert ag12["incidents_open_count"] == 1
        assert ag12["last_action"] == "report_resident_incident"

        # Case 3: Nighttime simulation clock + multi-day elapsed ticks (day_index == 2)
        (run_dir / SOCIETY_STEP_JSON).write_text(
            json.dumps(
                {
                    "current_time": "2026-06-16T21:30:00+07:00",
                    "step_count": 150,
                    "completed_step_count": 0,
                    "terminated": False,
                    "pending_update": None,
                }
            ),
            encoding="utf-8",
        )
        r2 = client.get(f"/api/v1/urban-sim/projects/{pid}/runs/{run_id}/state", headers=headers)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["sim_clock"]["is_daytime"] is False
        assert d2["sim_clock"]["time_band"] == "QUIET_NIGHT"
        assert d2["sim_clock"]["day_night_label_vi"] == "Ban đêm"
        assert d2["sim_clock"]["period_vi"] == "Đêm"
        assert d2["sim_clock"]["day_index"] == 2
        assert d2["sim_clock"]["elapsed_seconds"] >= 86400


def test_rubric_default_endpoint_and_roundtrip(tmp_path: Path, monkeypatch):
    """Verify GET /rubric-default exposes valid schema and PATCH project accepts custom rubric round-trip."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    headers = _client_headers(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 1. Fetch default rubric from Single Source of Truth endpoint
        r_def = client.get("/api/v1/urban-sim/rubric-default", headers=headers)
        assert r_def.status_code == 200
        body = r_def.json()
        assert body["success"] is True
        rubric = body["rubric"]
        assert rubric["version"] == "1.0"
        assert "BQL_DIRECTOR" in rubric["roles"]
        assert "BQL_STAFF" in rubric["roles"]
        assert len(rubric["roles"]) >= 8
        assert len(rubric["quiz_questions"]) >= 6
        first_q = rubric["quiz_questions"][0]
        assert set(first_q["options"].keys()) == {"OPT_A", "OPT_B", "OPT_C", "OPT_D"}

        # 2. Create project and verify default empty rubric -> PATCH custom rubric round-trip
        create_res = client.post(
            "/api/v1/urban-sim/projects",
            json={
                "slug": "rubric-roundtrip-proj",
                "name": "Rubric Roundtrip Project",
                "default_portal_url": "https://example.demego.vn",
                "seed_mulberrylane_template": False,
            },
            headers=headers,
        )
        assert create_res.status_code == 200
        pid = create_res.json()["project"]["id"]

        custom_rubric = {
            "version": "2026-06-v1",
            "roles": {
                "OPS_CUSTOM": {
                    "role_code": "OPS_CUSTOM",
                    "label": "Chuyên viên Vận hành Tòa nhà",
                    "interaction_mode": "write_ops",
                    "target_url_patterns": ["/ext/incidents", "/ext/tasks"],
                    "expected_min_steps": 4,
                    "min_actions_for_lostness": 3,
                    "expected_target_modules_for_m3": 2,
                }
            },
            "quiz_questions": [
                {
                    "id": "q_custom_01",
                    "topic": "Quy trình tiếp nhận sự cố cư dân",
                    "skill_domain": "INCIDENT_OPS",
                    "prompt_stem": "Khi cư dân báo sự cố khẩn cấp, nhân sự cần truy cập phân hệ nào đầu tiên?",
                    "options": {
                        "OPT_A": "/ext/incidents",
                        "OPT_B": "/ext/billing",
                        "OPT_C": "/ext/parking",
                        "OPT_D": "/home",
                    },
                    "correct_choice": "OPT_A",
                }
            ],
        }
        patch_res = client.patch(
            f"/api/v1/urban-sim/projects/{pid}",
            json={"competency_rubric_json": json.dumps(custom_rubric, ensure_ascii=False)},
            headers=headers,
        )
        assert patch_res.status_code == 200
        saved_json = patch_res.json()["project"]["competency_rubric_json"]
        assert json.loads(saved_json)["roles"]["OPS_CUSTOM"]["label"] == "Chuyên viên Vận hành Tòa nhà"

        # 3. Reset back to empty (revert to MulberryLane default)
        reset_res = client.patch(
            f"/api/v1/urban-sim/projects/{pid}",
            json={"competency_rubric_json": ""},
            headers=headers,
        )
        assert reset_res.status_code == 200
        assert (reset_res.json()["project"]["competency_rubric_json"] or "") == ""


def test_soc_01_debrief_default_compile_and_lifecycle(tmp_path: Path):
    """TC-SOC-01: Default project enables Sociological Debrief (2 steps: run + bql_sociological_debrief) -> POST_DEBRIEF."""
    import yaml
    from agentsociety2.backend.services.urban_sim.lifecycle import (
        _count_expected_top_level_steps,
        derive_execution_phase,
    )

    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    assert proj.enable_sociological_debrief is True
    assert proj.enable_competency_prepost_quiz is False

    with Session(get_engine(tmp_path)) as sess:
        personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
        atlas = sess.get(UrbanSimAtlasConfig, proj.id)
        run_dir = tmp_path / "run_default_debrief"
        bundle = compile_run_from_db(
            project=proj,
            personas=personas,
            atlas=atlas,
            zones=[],
            run_dir=run_dir,
            workspace_root=tmp_path,
        )

    steps = yaml.safe_load(bundle.steps_path.read_text(encoding="utf-8"))["steps"]
    assert len(steps) == 2
    assert steps[0]["type"] == "run"
    assert steps[1]["type"] == "questionnaire"
    assert steps[1]["questionnaire_id"] == "bql_sociological_debrief"
    assert steps[1]["allow_env_tools"] is False
    assert steps[1]["retry_on_parse_error"] is True
    assert _count_expected_top_level_steps(run_dir) == 2

    assert derive_execution_phase(run_dir, "RUNNING", 2, 8) == "SIMULATING"
    (run_dir / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 1}), encoding="utf-8")
    assert derive_execution_phase(run_dir, "RUNNING", 8, 8) == "POST_DEBRIEF"
    (run_dir / "SOCIETY_STEP.json").write_text(json.dumps({"completed_step_count": 2}), encoding="utf-8")
    assert derive_execution_phase(run_dir, "RUNNING", 8, 8) == "DONE"

    # Explicit disable returns single-step run
    proj.enable_sociological_debrief = False
    with Session(get_engine(tmp_path)) as sess:
        personas = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
        atlas = sess.get(UrbanSimAtlasConfig, proj.id)
        run_dir_off = tmp_path / "run_debrief_off"
        bundle_off = compile_run_from_db(
            project=proj,
            personas=personas,
            atlas=atlas,
            zones=[],
            run_dir=run_dir_off,
            workspace_root=tmp_path,
        )
    steps_off = yaml.safe_load(bundle_off.steps_path.read_text(encoding="utf-8"))["steps"]
    assert [s["type"] for s in steps_off] == ["run"]


def test_soc_02_allow_env_tools_false_and_json_retry(tmp_path: Path):
    """TC-SOC-02: allow_env_tools=False blocks ask_env & env:* scripts, legacy agent signature works, JSON retries 1x."""
    from agentsociety2.agent.base.tool_schema import react_tool_schemas
    from agentsociety2.agent.person import PersonAgent
    from agentsociety2.society.questionnaire import QuestionItem, Questionnaire, QuestionnaireRunner

    schemas_default = react_tool_schemas(allow_env_tools=True)
    schemas_locked = react_tool_schemas(allow_env_tools=False)
    assert any(s["function"]["name"] == "ask_env" for s in schemas_default)
    assert not any(s["function"]["name"] == "ask_env" for s in schemas_locked)
    assert any(s["function"]["name"] == "execute_skill_script" for s in schemas_locked)

    ws99 = tmp_path / "ws_99"
    PersonAgent.create(ws99, {"id": 99, "name": "Tester"}, {})

    class _DummyLLM:
        model_name = "mock-gpt"

    proxy99 = SimpleNamespace(
        env=None,
        llm=SimpleNamespace(coder=_DummyLLM(), default=_DummyLLM(), embedding=None),
        trace=None,
        replay=None,
        run_dir=tmp_path,
    )

    async def _exercise_tool_lock():
        agent = await PersonAgent.from_workspace(ws99, proxy99)
        res_ask = await agent.dispatch_react_tool(
            "ask_env", {"instruction": "open browser"}, allow_env_tools=False
        )
        res_script_colon = await agent.dispatch_react_tool(
            "execute_skill_script", {"script": "env:browser_click"}, allow_env_tools=False
        )
        res_script_slash = await agent.dispatch_react_tool(
            "execute_skill_script", {"script": "env/portal.py"}, allow_env_tools=False
        )
        return res_ask, res_script_colon, res_script_slash

    r1, r2, r3 = asyncio.run(_exercise_tool_lock())
    for res in (r1, r2, r3):
        assert res.ok is False or "ALLOW_ENV_TOOLS_FALSE" in str(res.observation).upper() or "allow_env_tools" in str(res.observation)

    # Legacy subclass without allow_env_tools param + retry_on_parse_error=True for JSON
    class _LegacyAgent:
        def __init__(self, responses):
            self.id = 1
            self.name = "Legacy Tester"
            self._responses = list(responses)
            self.calls = 0

        async def ask(self, message: str, readonly: bool = True, t: datetime | None = None) -> str:
            idx = min(self.calls, len(self._responses) - 1)
            self.calls += 1
            return self._responses[idx]

    q = Questionnaire(
        questionnaire_id="test_debrief",
        questions=[
            QuestionItem(
                id="debrief_json",
                prompt="Trả về JSON",
                response_type="json",
            )
        ],
        allow_env_tools=False,
        retry_on_parse_error=True,
    )
    runner = QuestionnaireRunner()
    # 1st attempt: invalid JSON -> 2nd valid dict -> succeeds!
    legacy_ok = _LegacyAgent(["not-json-at-all", json.dumps({"umux_capabilities": 6, "umux_ease": 6})])
    resp_ok = asyncio.run(
        runner.run(q, [legacy_ok], t=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc), step_count=1)
    )
    assert legacy_ok.calls == 2
    assert resp_ok.responses[0].answers[0].parse_success is True
    assert resp_ok.responses[0].answers[0].parsed_value["umux_capabilities"] == 6

    # test 2: 1st JSON scalar "42" (not dict/list) -> fails schema check & triggers retry -> 2nd valid dict succeeds
    legacy_scalar = _LegacyAgent(["42", json.dumps({"seq_ease": 5})])
    resp_scalar = asyncio.run(
        runner.run(q, [legacy_scalar], t=datetime(2026, 6, 15, 11, 0, tzinfo=timezone.utc), step_count=1)
    )
    assert legacy_scalar.calls == 2
    assert resp_scalar.responses[0].answers[0].parse_success is True
    assert resp_scalar.responses[0].answers[0].parsed_value["seq_ease"] == 5


def test_soc_03_sociological_metrics_triangulation_bias_and_kane(tmp_path: Path):
    """TC-SOC-03: UMUX-Lite (Lah 2020), Workload ((x-1)/6)*100, CSKH_ALL_FAILED vs NO_CSKH_ASK, PII redact, CIT grounding, Bias Warning, Kane."""
    from agentsociety2.backend.services.urban_sim.competency import evaluate_run_competency

    init_urban_sim_db(tmp_path)
    run_dir = tmp_path / "run_soc_eval"
    art = run_dir / "artifacts"
    (art / "agent_1").mkdir(parents=True, exist_ok=True)
    (art / "agent_2").mkdir(parents=True, exist_ok=True)
    (art / "agent_3").mkdir(parents=True, exist_ok=True)
    init_dir = run_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    init_cfg = {
        "agents": [
            {"agent_id": 1, "kwargs": {"profile": {"name": "Giám đốc Test", "group_type": "BQL", "role_code": "BQL_DIRECTOR", "role_title": "Giám đốc Dự án", "software_access_enabled": True}}},
            {"agent_id": 2, "kwargs": {"profile": {"name": "Kỹ thuật Test", "group_type": "BQL", "role_code": "ENG_STAFF", "role_title": "Nhân viên Kỹ thuật", "software_access_enabled": True}}},
            {"agent_id": 3, "kwargs": {"profile": {"name": "An ninh Test", "group_type": "BQL", "role_code": "SEC_STAFF", "role_title": "Nhân viên Bảo vệ", "software_access_enabled": True}}},
        ]
    }
    (init_dir / "init_config.json").write_text(json.dumps(init_cfg, ensure_ascii=False), encoding="utf-8")

    # Structured urban_events.jsonl for Behavioral Triangulation
    # Agent 1: login ok, opened /ext/incidents ok, atlas asked & ok (VALID) -> CIT /ext/incidents matches seq 11!
    # Agent 2: login ok, clicked fail, atlas asked 2x all failed (CSKH_ALL_FAILED), yet CIT claims unreachable /unknown/nowhere-route -> UNGROUNDED if failed event isn't token/route matched? Note failed ev matches unless ok=True, wait: _ground_cit_incident marks ANY failed WEB/ATLAS event as fallback anchor (`elif not bool(ev.get("ok", True)): matched = True`)! So Agent 3 (no failed events, no matching URL/token) -> UNGROUNDED_SELF_REPORT!
    (run_dir / "urban_events.jsonl").write_text(
        "\n".join([
            json.dumps({"seq": 10, "agent_id": 1, "stream": "WEB", "action": "login_portal", "ok": True, "summary": "Đăng nhập cổng QLTN", "details": {"url": "https://portal/home", "screenshot_path": "artifacts/agent_1/s1.png"}}),
            json.dumps({"seq": 11, "agent_id": 1, "stream": "WEB", "action": "navigate", "ok": True, "summary": "Mở danh sách phản ánh cư dân", "details": {"url": "https://portal/ext/incidents", "screenshot_path": "artifacts/agent_1/s2.png"}}),
            json.dumps({"seq": 12, "agent_id": 1, "stream": "ATLAS", "action": "ask_support", "ok": True, "summary": "Hỏi quy trình /ext/incidents", "details": {"question": "Quy trình /ext/incidents"}}),
            json.dumps({"seq": 13, "agent_id": 1, "stream": "COMM", "action": "manage_incident", "ok": True, "summary": "Xử lý phản ánh"}),
            json.dumps({"seq": 20, "agent_id": 2, "stream": "WEB", "action": "login_portal", "ok": True, "summary": "Đăng nhập QLTN", "details": {"url": "https://portal/home"}}),
            json.dumps({"seq": 21, "agent_id": 2, "stream": "WEB", "action": "click", "ok": False, "summary": "Lỗi nút trên /ext/internal-tasks", "details": {"url": "https://portal/ext/internal-tasks"}}),
            json.dumps({"seq": 22, "agent_id": 2, "stream": "ATLAS", "action": "ask_support", "ok": False, "summary": "Lỗi kết nối CSKH lần 1", "details": {"question": "Mở phiếu lỗi"}}),
            json.dumps({"seq": 23, "agent_id": 2, "stream": "ATLAS", "action": "ask_support", "ok": False, "summary": "Lỗi kết nối CSKH lần 2", "details": {"question": "Mở phiếu lần 2"}}),
            json.dumps({"seq": 30, "agent_id": 3, "stream": "WEB", "action": "login_portal", "ok": True, "summary": "Đăng nhập QLTN", "details": {"url": "https://portal/home"}}),
        ]),
        encoding="utf-8",
    )

    debrief_payload = {
        "questionnaire_id": "bql_sociological_debrief",
        "responses": [
            {
                "agent_id": 1,
                "answers": [
                    {
                        "question_id": "q_debrief_metrics",
                        "parse_success": True,
                        "parsed_value": {
                            "umux_capabilities": 7,
                            "umux_ease": 5,
                            "seq_ease": 6,
                            "workload_effort": 5,
                            "workload_frustration": 3,
                            "cskh_accuracy": 6,
                            "cskh_helpfulness": 6,
                        },
                    },
                    {
                        "question_id": "q_debrief_incidents",
                        "parse_success": True,
                        "parsed_value": {
                            "incidents": [
                                {
                                    "context_task": "Kiểm tra danh sách phản ánh cư dân",
                                    "screen_or_url": "/ext/incidents",
                                    "what_happened": "Cư dân SĐT 0912345678 phản ánh chậm hiển thị",
                                    "cskh_outcome": "HELPFUL",
                                    "root_cause_category": "SOFTWARE_UX_BUG",
                                    "severity": "MAJOR",
                                    "suggestion": "Tối ưu phân trang /ext/incidents",
                                }
                            ]
                        },
                    },
                    {
                        "question_id": "q_debrief_reflection",
                        "parse_success": True,
                        "parsed_value": "Dễ theo dõi phản ánh.",
                    },
                ],
            },
            {
                "agent_id": 2,
                "answers": [
                    {
                        "question_id": "q_debrief_metrics",
                        "parse_success": True,
                        "parsed_value": {
                            "umux_capabilities": 7,
                            "umux_ease": 7,
                            "seq_ease": 7,
                            "workload_effort": 2,
                            "workload_frustration": 1,
                            "cskh_accuracy": 7,
                            "cskh_helpfulness": 7,
                        },
                    },
                    {
                        "question_id": "q_debrief_incidents",
                        "parse_success": True,
                        "parsed_value": {"incidents": []},
                    },
                    {
                        "question_id": "q_debrief_reflection",
                        "parse_success": True,
                        "parsed_value": "Mọi thứ hoàn hảo!",
                    },
                ],
            },
            {
                "agent_id": 3,
                "answers": [
                    {
                        "question_id": "q_debrief_metrics",
                        "parse_success": True,
                        "parsed_value": {
                            "umux_capabilities": 5,
                            "umux_ease": 5,
                            "seq_ease": 5,
                            "workload_effort": 4,
                            "workload_frustration": 2,
                            "cskh_accuracy": 6,
                            "cskh_helpfulness": 6,
                        },
                    },
                    {
                        "question_id": "q_debrief_incidents",
                        "parse_success": True,
                        "parsed_value": {
                            "incidents": [
                                {
                                    "context_task": "Tìm báo cáo thuế năm 2099",
                                    "screen_or_url": "/unknown/nowhere-route",
                                    "what_happened": "Không tìm thấy menu giả định",
                                    "cskh_outcome": "NOT_ASKED",
                                    "root_cause_category": "KNOWLEDGE_GAP",
                                    "severity": "MINOR",
                                    "suggestion": "Bổ sung tài liệu",
                                }
                            ]
                        },
                    },
                    {
                        "question_id": "q_debrief_reflection",
                        "parse_success": True,
                        "parsed_value": "Chưa hỏi CSKH lần nào.",
                    },
                ],
            },
        ],
    }
    (art / "questionnaire_step_2.json").write_text(
        json.dumps(debrief_payload, ensure_ascii=False), encoding="utf-8"
    )

    report = evaluate_run_competency(run_dir=run_dir, bypass_cache=True)
    soc = report["sociological_debrief"]
    assert soc["available"] is True
    assert soc["status"] == "COMPLETE"
    assert soc["respondents_n"] == 3
    assert soc["cskh_valid_n"] == 1
    assert soc["cskh_all_failed_n"] == 1

    ag1 = next(a for a in report["agents"] if a["agent_id"] == 1)
    ag2 = next(a for a in report["agents"] if a["agent_id"] == 2)
    ag3 = next(a for a in report["agents"] if a["agent_id"] == 3)

    assert ag1["debrief"]["umux_lite_score"] == 83.3
    assert ag1["debrief"]["workload_effort_100"] == 66.7
    assert ag1["debrief"]["workload_frustration_100"] == 33.3
    assert ag1["debrief"]["workload_subset_100"] == 50.0
    assert ag1["debrief"]["cskh_status"] == "OK"
    assert ag1["debrief"]["incidents"][0]["grounding_status"] == "VERIFIED_BY_LOG"
    assert "0912345678" not in ag1["debrief"]["incidents"][0]["what_happened"]

    assert ag2["debrief"]["cskh_status"] == "CSKH_ALL_FAILED"
    assert "ACQUIESCENCE_BIAS_WARNING" in ag2["debrief"]["bias_flags"]
    # Non-compensatory Kane gate: Agent 2 never reached ENG_STAFF target -> stays M1 even with UMUX=100
    assert ag2["miller_level"] in ("M0", "M1")

    assert ag3["debrief"]["cskh_status"] == "NO_CSKH_ASK"
    assert ag3["debrief"]["incidents"][0]["grounding_status"] == "UNGROUNDED_SELF_REPORT"
    assert soc["cskh_quality_mean"] == 6.0


def test_soc_04_accounting_role_and_sync_endpoint(tmp_path: Path, monkeypatch):
    """TC-SOC-04: MulberryLane has #22 BQL_ACCOUNTANT; sync-accounting-persona is idempotent & safe when #22 taken."""
    from agentsociety2.backend.services.urban_sim.competency import DEFAULT_MULBERRYLANE_RUBRIC

    assert "BQL_ACCOUNTANT" in DEFAULT_MULBERRYLANE_RUBRIC.roles

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    headers = _client_headers(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 1. MulberryLane already seeded with #22 BQL_ACCOUNTANT -> idempotent created=False
        projs = client.get("/api/v1/urban-sim/projects", headers=headers).json()["items"]
        ml_id = projs[0]["id"]
        ml_personas = client.get(f"/api/v1/urban-sim/projects/{ml_id}/personas", headers=headers).json()["items"]
        acc = next((p for p in ml_personas if p["role_code"] == "BQL_ACCOUNTANT"), None)
        assert acc is not None and acc["agent_id"] == 22 and acc["is_pilot_member"] is True

        sync_ml = client.post(f"/api/v1/urban-sim/projects/{ml_id}/sync-accounting-persona", headers=headers)
        assert sync_ml.status_code == 200 and sync_ml.json()["created"] is False

        # 2. Custom project where agent_id=22 is already occupied -> allocates next max+1 (=23) cleanly
        c_res = client.post(
            "/api/v1/urban-sim/projects",
            json={
                "slug": "test-occ-22",
                "name": "Occupied 22 Test",
                "default_portal_url": "https://portal.example.com",
                "seed_mulberrylane_template": False,
            },
            headers=headers,
        )
        assert c_res.status_code == 200
        cpid = c_res.json()["project"]["id"]
        p_occ = client.post(
            f"/api/v1/urban-sim/projects/{cpid}/personas",
            json={
                "agent_id": 22,
                "full_name": "Cư dân Đang Giữ #22",
                "role_code": "RESIDENT",
                "role_title": "Cư dân",
                "department": "Cư dân",
                "group_type": "RESIDENT",
                "software_access_enabled": False,
                "home_zone": "LOBBY_MAIN",
            },
            headers=headers,
        )
        assert p_occ.status_code == 200

        sync_new = client.post(f"/api/v1/urban-sim/projects/{cpid}/sync-accounting-persona", headers=headers)
        assert sync_new.status_code == 200
        assert sync_new.json()["created"] is True
        assert sync_new.json()["persona"]["agent_id"] == 23
        assert sync_new.json()["persona"]["role_code"] == "BQL_ACCOUNTANT"

        sync_again = client.post(f"/api/v1/urban-sim/projects/{cpid}/sync-accounting-persona", headers=headers)
        assert sync_again.status_code == 200
        assert sync_again.json()["created"] is False


def test_soc_05_scenario_brief_and_zone_details_caps(tmp_path: Path, monkeypatch):
    """TC-SOC-05: /scenario-brief-template works & observe_urban_inbox injects bounded scenario_brief + zone_details."""
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    headers = _client_headers(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        tpl_res = client.get("/api/v1/urban-sim/scenario-brief-template", headers=headers)
        assert tpl_res.status_code == 200
        assert len(tpl_res.json()["template"]) > 100

    env = UrbanCommAndIncidentEnv(
        scenario_brief="Thực trạng tồn đọng công nợ & PCCC. " + ("X" * 4500),
        zones=[
            {"zone_key": "LOBBY_MAIN", "name": "Sảnh chính", "description": "Mô tả khu vực sảnh " + ("Z" * 400)},
            {"zone_key": "BASEMENT_B1B2", "name": "Hầm B1-B2", "description": "Mô tả hầm " + ("Y" * 350)},
        ],
    )
    obs = asyncio.run(env.observe_urban_inbox(agent_id=1))
    bctx = obs["building_context"]
    assert 100 < len(bctx["scenario_brief"]) <= 4000
    assert isinstance(bctx["current_zone_detail"], dict)
    assert len(bctx["current_zone_detail"].get("description", "")) <= 240
    assert "zone_details" in obs and len(obs["zone_details"]) == 2
    assert all(len(z.get("description", "")) <= 240 for z in obs["zone_details"])


def test_zone_crud_and_zero_hardcode_context(tmp_path: Path, monkeypatch):
    """Zone CRUD (POST/PATCH rename cascade/DELETE 409 + reassign_to) & 100% zero-hardcode dynamic context for non-MulberryLane project."""
    from agentsociety2.backend.services.urban_sim.db import UrbanSimZone

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    headers = _client_headers(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 1. Create clean non-MulberryLane project (zero template seeding)
        p_res = client.post(
            "/api/v1/urban-sim/projects",
            json={
                "slug": "royal-city-clean",
                "name": "Khu đô thị Royal City",
                "default_portal_url": "https://qltn.royal.example.com",
                "seed_mulberrylane_template": False,
            },
            headers=headers,
        )
        assert p_res.status_code == 200
        pid = p_res.json()["project"]["id"]

        # 2. Add 2 custom zones with dynamic ambient_signals
        z1_res = client.post(
            f"/api/v1/urban-sim/projects/{pid}/zones",
            json={
                "zone_key": "tower r1",
                "name": "Tòa R1 — Khu Căn hộ",
                "zone_type": "TOWER",
                "description": "Khối căn hộ R1 phía Bắc",
                "ambient_signals": "Tín hiệu động Royal R1: bảo trì bơm tăng áp tầng mái.\nKiểm tra hóa đơn nước kỳ mới.",
                "sort_order": 1,
            },
            headers=headers,
        )
        assert z1_res.status_code == 200
        z1 = z1_res.json()["zone"]
        assert z1["zone_key"] == "TOWER_R1"
        assert "Royal R1" in z1["ambient_signals"]

        z2_res = client.post(
            f"/api/v1/urban-sim/projects/{pid}/zones",
            json={
                "zone_key": "LOBBY_R1",
                "name": "Sảnh Chính Royal",
                "zone_type": "LOBBY",
                "description": "Sảnh đón tiếp cư dân",
                "ambient_signals": "",
                "sort_order": 2,
            },
            headers=headers,
        )
        assert z2_res.status_code == 200
        z2 = z2_res.json()["zone"]

        # 3. Create receptionist at agent_id=105 & resident in TOWER_R1
        rec_res = client.post(
            f"/api/v1/urban-sim/projects/{pid}/personas",
            json={
                "agent_id": 105,
                "full_name": "Lễ tân Royal",
                "role_code": "BQL_RECEPTIONIST",
                "role_title": "Lễ tân",
                "group_type": "BQL",
                "software_access_enabled": True,
                "home_zone": "LOBBY_R1",
            },
            headers=headers,
        )
        assert rec_res.status_code == 200
        res_p = client.post(
            f"/api/v1/urban-sim/projects/{pid}/personas",
            json={
                "agent_id": 201,
                "full_name": "Cư dân R1",
                "role_code": "RESIDENT",
                "role_title": "Chủ hộ",
                "group_type": "RESIDENT",
                "software_access_enabled": False,
                "home_zone": "TOWER_R1",
            },
            headers=headers,
        )
        assert res_p.status_code == 200

        # 4. PATCH rename zone_key TOWER_R1 -> TOWER_R1_VIP cascades to resident home_zone
        patch_res = client.patch(
            f"/api/v1/urban-sim/projects/{pid}/zones/{z1['id']}",
            json={"zone_key": "TOWER_R1_VIP", "name": "Tòa R1 VIP"},
            headers=headers,
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["zone"]["zone_key"] == "TOWER_R1_VIP"
        assert patch_res.json()["zone"]["persona_count"] == 1

        personas_after = client.get(f"/api/v1/urban-sim/projects/{pid}/personas", headers=headers).json()["items"]
        res_item = next(p for p in personas_after if p["agent_id"] == 201)
        assert res_item["home_zone"] == "TOWER_R1_VIP"

        # 5. DELETE protected (409 without reassign_to, 200 with reassign_to=LOBBY_R1)
        del_409 = client.delete(f"/api/v1/urban-sim/projects/{pid}/zones/{z1['id']}", headers=headers)
        assert del_409.status_code == 409

        del_ok = client.delete(
            f"/api/v1/urban-sim/projects/{pid}/zones/{z1['id']}?reassign_to=LOBBY_R1",
            headers=headers,
        )
        assert del_ok.status_code == 200 and del_ok.json()["reassigned_personas"] == 1

        # Re-add TOWER_R1_VIP for runtime zero-hardcode compile check
        z3_res = client.post(
            f"/api/v1/urban-sim/projects/{pid}/zones",
            json={
                "zone_key": "TOWER_R1_VIP",
                "name": "Tòa R1 VIP",
                "zone_type": "TOWER",
                "description": "Khu VIP R1",
                "ambient_signals": "Tín hiệu động Royal R1: kiểm tra hệ thống PCCC tầng 15.",
                "sort_order": 3,
            },
            headers=headers,
        )
        assert z3_res.status_code == 200

    # 6. Verify compile_run_from_db & UrbanCommAndIncidentEnv have ZERO MulberryLane / agent_id=3 hardcodes
    with Session(get_engine(tmp_path)) as sess:
        p_row = sess.get(UrbanSimProject, pid)
        pers_db = list(sess.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == pid)).all())
        zones_db = list(sess.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == pid)).all())
        atlas = sess.get(UrbanSimAtlasConfig, pid)
        bundle = compile_run_from_db(
            project=p_row,
            personas=pers_db,
            atlas=atlas,
            zones=zones_db,
            run_dir=tmp_path / "royal_compile",
            workspace_root=tmp_path,
        )

    prompt_txt = bundle.prompt_overrides_path.read_text(encoding="utf-8")
    assert "Khu đô thị Royal City" in prompt_txt
    assert "agent_id=105" in prompt_txt
    assert "MulberryLane" not in prompt_txt
    assert "agent_id=3" not in prompt_txt

    env = UrbanCommAndIncidentEnv(
        project_name="Khu đô thị Royal City",
        scenario_brief="Thực trạng Royal City: tập trung kiểm tra PCCC và thu phí dịch vụ.",
        personas=[
            {"agent_id": 105, "full_name": "Lễ tân Royal", "role_code": "BQL_RECEPTIONIST", "role_title": "Lễ tân", "group_type": "BQL", "home_zone": "LOBBY_R1"},
            {"agent_id": 201, "full_name": "Cư dân R1", "role_code": "RESIDENT", "role_title": "Chủ hộ", "group_type": "RESIDENT", "home_zone": "TOWER_R1_VIP"},
        ],
        zones=[
            {"zone_key": "LOBBY_R1", "name": "Sảnh Chính Royal", "zone_type": "LOBBY", "description": "Sảnh chính", "ambient_signals": ""},
            {"zone_key": "TOWER_R1_VIP", "name": "Tòa R1 VIP", "zone_type": "TOWER", "description": "Khu VIP R1", "ambient_signals": "Tín hiệu động Royal R1: kiểm tra hệ thống PCCC tầng 15."},
        ],
        bql_agent_ids=[105],
        resident_agent_ids=[201],
    )
    env.t = datetime(2026, 6, 15, 8, 15, tzinfo=timezone.utc)
    obs_vip = asyncio.run(env.observe_urban_inbox(agent_id=201))
    bctx_vip = obs_vip["building_context"]
    joined = json.dumps(obs_vip, ensure_ascii=False)
    for forbidden in ("MulberryLane", "Zen Tower", "Fantasy Tower", "tháng 6", "agent_id=3"):
        assert forbidden not in joined
    assert "Tín hiệu động Royal R1: kiểm tra hệ thống PCCC tầng 15." in bctx_vip["building_signals"]
    assert "agent_id=105" in bctx_vip["autonomy_guidance"]

    obs_lobby = asyncio.run(env.observe_urban_inbox(agent_id=105))
    assert any("Sảnh chính" in sig for sig in obs_lobby["building_context"]["building_signals"])







