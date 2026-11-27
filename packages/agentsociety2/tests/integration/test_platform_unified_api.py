"""Integration tests for Unified AgentSociety v2 Platform Control Plane API (/api/*)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from fastapi.testclient import TestClient
from sqlmodel import Session

from agentsociety2.backend.app import app
from agentsociety2.backend.services.platform_resources import (
    PlatformLLMConfig,
    resolve_llm_env_override,
)
from agentsociety2.backend.services.urban_sim.db import UrbanSimRun, get_engine


def test_unified_platform_seed_and_crud_llm_fernet(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_KEY", "sk-env-secret-999")
    monkeypatch.setenv("AGENTSOCIETY_LLM_MODEL", "gpt-5.5")

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 1. All 11 endpoints return HTTP 200 and JSON {data: [...]}
        for path in [
            "/api/llm-configs",
            "/api/map-configs",
            "/api/agent-configs",
            "/api/agent-templates",
            "/api/agent-profiles",
            "/api/agent-classes?agent_type=citizen",
            "/api/agent-blocks",
            "/api/community/workflow/functions",
            "/api/workflow-configs",
            "/api/experiments",
            "/api/surveys",
        ]:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} failed: {resp.text}"
            body = resp.json()
            assert isinstance(body.get("data"), list), f"{path} missing data list"

        # 2. Seeded LLM masks key
        llm_list = client.get("/api/llm-configs").json()["data"]
        assert len(llm_list) >= 1
        assert llm_list[0]["config"][0]["api_key"] != "sk-env-secret-999"
        assert "••••" in llm_list[0]["config"][0]["api_key"]

        # 3. Create LLM config -> stored Fernet encrypted -> link to MulberryLane project
        created = client.post(
            "/api/llm-configs",
            json={
                "name": "Mulberry Custom OpenAI",
                "description": "Key test tích hợp",
                "config": [
                    {
                        "provider": "openai",
                        "model": "gpt-5.4-mini",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-plaintext-must-be-encrypted",
                    }
                ],
            },
        )
        assert created.status_code == 200
        created_data = created.json()["data"]
        llm_id = created_data["id"]
        assert created_data["config"][0]["api_key"] != "sk-plaintext-must-be-encrypted"
        assert created_data["config"][0]["has_api_key"] is True

        # Update description keeping masked password
        updated = client.put(
            f"/api/llm-configs/{llm_id}",
            json={
                "name": "Mulberry Custom OpenAI v2",
                "description": "Updated",
                "config": [
                    {
                        "provider": "openai",
                        "model": "gpt-5.4-mini",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": created_data["config"][0]["api_key"],
                    }
                ],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "Mulberry Custom OpenAI v2"

        # Verify raw DB row stores Fernet ciphertext & resolves properly for subprocess
        engine = get_engine(tmp_path)
        with Session(engine) as session:
            row = session.get(PlatformLLMConfig, llm_id)
            assert row is not None
            assert "sk-plaintext-must-be-encrypted" not in row.config_json
            overrides = resolve_llm_env_override(session, llm_id, tmp_path)
            assert overrides["AGENTSOCIETY_LLM_API_KEY"] == "sk-plaintext-must-be-encrypted"
            assert overrides["AGENTSOCIETY_LLM_MODEL"] == "gpt-5.4-mini"

        # Link to MulberryLane project
        projects = client.get("/api/v1/urban-sim/projects").json()["items"]
        proj_id = projects[0]["id"]
        patched = client.patch(
            f"/api/v1/urban-sim/projects/{proj_id}",
            json={"llm_config_id": llm_id},
        )
        assert patched.status_code == 200
        assert patched.json()["project"]["llm_config_id"] == llm_id

        # Delete LLM unlinks cleanly
        deleted = client.delete(f"/api/llm-configs/{llm_id}")
        assert deleted.status_code == 200
        proj_after = client.get(f"/api/v1/urban-sim/projects/{proj_id}").json()["project"]
        assert proj_after["llm_config_id"] is None


def test_unified_map_upload_survey_and_experiments(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # Block image uploads on legacy /maps endpoint (415) & disallow image_2d map creation (400)
        bad_upload = client.post(
            "/api/map-configs/-/upload",
            files={"file": ("evil.png", b"<svg onload='alert(1)'></svg>", "image/png")},
        )
        assert bad_upload.status_code == 415

        bad_img_create = client.post(
            "/api/map-configs",
            json={
                "name": "Ảnh 2D không hợp lệ ở /maps",
                "description": "Should reject",
                "config": {"file_path": "floor.png", "map_type": "image_2d"},
            },
        )
        assert bad_img_create.status_code == 400

        # Allow valid .pb traffic map upload
        pb_bytes = b"\x08\x01\x12\x0cMulberryMapPb"
        good_upload = client.post(
            "/api/map-configs/-/upload",
            files={"file": ("traffic_test.pb", pb_bytes, "application/octet-stream")},
        )
        assert good_upload.status_code == 200
        rel_path = good_upload.json()["data"]["file_path"]
        assert rel_path.endswith("_traffic_test.pb")

        created_map = client.post(
            "/api/map-configs",
            json={
                "name": "Bản đồ Giao thông Test (.pb)",
                "description": "Test pb map",
                "config": {"file_path": rel_path},
            },
        )
        assert created_map.status_code == 200
        map_id = created_map.json()["data"]["id"]
        assert created_map.json()["data"]["config"]["map_type"] == "protobuf"

        temp_link = client.post(
            f"/api/map-configs/{map_id}/temp-link",
            json={"expire_seconds": 120},
        )
        assert temp_link.status_code == 200
        token = temp_link.json()["data"]["token"]
        resolved = client.get(f"/api/map-configs/{map_id}/temp-link?token={token}")
        assert resolved.status_code == 200

        # Upload agent profile JSON
        profile_upload = client.post(
            "/api/agent-profiles/upload",
            files={
                "file": (
                    "residents.json",
                    io.BytesIO(json.dumps([{"name": "Cư dân A"}, {"name": "Cư dân B"}]).encode("utf-8")),
                    "application/json",
                )
            },
            data={"name": "residents.json", "description": "2 cư dân thử"},
        )
        assert profile_upload.status_code == 200
        prof_id = profile_upload.json()["data"]["id"]
        assert profile_upload.json()["data"]["record_count"] == 2
        prof_dl = client.get(f"/api/agent-profiles/{prof_id}")
        assert prof_dl.status_code == 200
        assert len(prof_dl.json()["data"]) == 2

        # Survey CRUD
        sv_create = client.post(
            "/api/surveys",
            json={"name": "Survey Test", "data": {"pages": [{"name": "p1", "elements": []}]}},
        )
        assert sv_create.status_code == 200
        sv_id = sv_create.json()["data"]["id"]
        assert client.put(
            f"/api/surveys/{sv_id}",
            json={"name": "Survey Updated", "data": {"pages": [{"name": "p1", "elements": []}]}},
        ).status_code == 200
        assert client.delete(f"/api/surveys/{sv_id}").status_code == 200

        # Seeded UrbanSimRun appears in /api/experiments
        projects = client.get("/api/v1/urban-sim/projects").json()["items"]
        proj_id = projects[0]["id"]
        run_dir = tmp_path / "urban_sim_runs" / "mulberrylane" / "urbrun_verify_sync"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "output.log").write_text("hello urban sim log\n", encoding="utf-8")
        engine = get_engine(tmp_path)
        with Session(engine) as session:
            session.add(
                UrbanSimRun(
                    id="urbrun_verify_sync",
                    project_id=proj_id,
                    run_number=99,
                    run_dir=str(run_dir),
                    status="COMPLETED",
                    step_count=4,
                    total_steps=4,
                    active_agent_count=9,
                    total_tokens=1234,
                    total_cost_usd=0.02,
                )
            )
            session.commit()

        exps = client.get("/api/experiments").json()["data"]
        matched = [e for e in exps if e["id"] == "urbrun_verify_sync"]
        assert len(matched) == 1
        assert matched[0]["urban_sim_project_id"] == proj_id
        assert matched[0]["urban_sim_run_id"] == "urbrun_verify_sync"
        assert matched[0]["status"] == 2
        log_resp = client.get("/api/run-experiments/urbrun_verify_sync/log")
        assert log_resp.status_code == 200
        assert "hello urban sim log" in log_resp.text


def test_llm_catalog_rate_card_and_multiprovider_overrides(tmp_path: Path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import pytest

    from agentsociety2.config.llm_catalog import resolve_model_rates_usd

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_KEY", "sk-env-fallback")

    # 1. Longest-key rate resolution prevents substring mis-matching
    assert resolve_model_rates_usd("gpt-6-luna") == pytest.approx((0.10e-6, 0.01e-6, 0.50e-6))
    assert resolve_model_rates_usd("openai/gpt-6-luna") == pytest.approx((0.10e-6, 0.01e-6, 0.50e-6))
    assert resolve_model_rates_usd("gpt-5.4-mini") == pytest.approx((0.75e-6, 0.075e-6, 4.50e-6))
    assert resolve_model_rates_usd("gpt-4o-mini") == pytest.approx((0.15e-6, 0.075e-6, 0.60e-6))
    assert resolve_model_rates_usd("gemini-3.8-flash") == pytest.approx((0.75e-6, 0.075e-6, 3.75e-6))
    assert resolve_model_rates_usd("claude-sonnet-5-5") == pytest.approx((2.00e-6, 0.20e-6, 10.00e-6))

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 2. Catalog endpoint exposes 11 providers & gpt-6-luna + thinking=off defaults
        cat_resp = client.get("/api/llm-catalog")
        assert cat_resp.status_code == 200
        cat_data = cat_resp.json()["data"]
        assert cat_data["defaults"]["model"] == "gpt-6-luna"
        assert cat_data["defaults"]["thinking"] == "off"
        provider_ids = {p["provider"] for p in cat_data["providers"]}
        assert {
            "openai",
            "gemini",
            "claude",
            "deepseek",
            "xai",
            "qwen",
            "mistral",
            "openai_compatible",
            "zhipuai",
            "siliconflow",
            "vllm",
        } <= provider_ids

        # 3. Creating default OpenAI gpt-6-luna config syncs BOTH LLM and CODER_LLM + thinking=off
        created = client.post(
            "/api/llm-configs",
            json={
                "name": "GPT-6 Luna Fast",
                "description": "Default off reasoning",
                "config": [
                    {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "api_key": "sk-luna-test-key",
                    }
                ],
            },
        )
        assert created.status_code == 200
        entry = created.json()["data"]["config"][0]
        llm_id = created.json()["data"]["id"]
        assert entry["thinking"] == "off"
        assert entry["reasoning_effort"] == "none"
        assert entry["pricing"]["input_usd_per_1m"] == pytest.approx(0.10)

        engine = get_engine(tmp_path)
        with Session(engine) as session:
            ov = resolve_llm_env_override(session, llm_id, tmp_path)
            assert ov["AGENTSOCIETY_LLM_MODEL"] == "gpt-6-luna"
            assert ov["AGENTSOCIETY_CODER_LLM_MODEL"] == "gpt-6-luna"
            assert ov["AGENTSOCIETY_LLM_THINKING"] == "off"
            assert ov["AGENTSOCIETY_CODER_LLM_THINKING"] == "off"
            assert ov["AGENTSOCIETY_LLM_REASONING_EFFORT"] == ""
            assert ov["AGENTSOCIETY_CODER_LLM_REASONING_EFFORT"] == ""
            assert ov["AGENTSOCIETY_LLM_API_TYPE"] == "openai"
            assert ov["AGENTSOCIETY_CODER_LLM_API_TYPE"] == "openai"
            assert ov["AGENTSOCIETY_CODER_LLM_API_KEY"] == "sk-luna-test-key"

        # 4. Updating thinking=on + custom coder_model propagates cleanly
        updated = client.put(
            f"/api/llm-configs/{llm_id}",
            json={
                "name": "GPT-6 Luna Reasoning On",
                "config": [
                    {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "coder_model": "gpt-5.4-nano",
                        "thinking": "on",
                        "reasoning_effort": "low",
                        "api_key": "••••••",
                    }
                ],
            },
        )
        assert updated.status_code == 200
        with Session(engine) as session:
            ov2 = resolve_llm_env_override(session, llm_id, tmp_path)
            assert ov2["AGENTSOCIETY_LLM_MODEL"] == "gpt-6-luna"
            assert ov2["AGENTSOCIETY_CODER_LLM_MODEL"] == "gpt-5.4-nano"
            assert ov2["AGENTSOCIETY_LLM_THINKING"] == "on"
            assert ov2["AGENTSOCIETY_CODER_LLM_THINKING"] == "on"
            assert ov2["AGENTSOCIETY_LLM_REASONING_EFFORT"] == "low"
            assert ov2["AGENTSOCIETY_CODER_LLM_REASONING_EFFORT"] == "low"
            assert ov2["AGENTSOCIETY_LLM_API_KEY"] == "sk-luna-test-key"

        # 5. Claude -> anthropic api_type; Gemini /v1beta -> /v1beta/openai normalization
        claude_res = client.post(
            "/api/llm-configs",
            json={
                "name": "Claude Haiku 5.5",
                "config": [{"provider": "claude", "model": "claude-haiku-5-5", "api_key": "sk-ant-1"}],
            },
        )
        gemini_res = client.post(
            "/api/llm-configs",
            json={
                "name": "Gemini 3.8 Flash",
                "config": [
                    {
                        "provider": "gemini",
                        "model": "gemini-3.8-flash",
                        "base_url": "https://generativelanguage.googleapis.com/v1beta",
                        "api_key": "AIza-test",
                    }
                ],
            },
        )
        assert claude_res.status_code == 200
        assert gemini_res.status_code == 200
        with Session(engine) as session:
            ov_claude = resolve_llm_env_override(session, claude_res.json()["data"]["id"], tmp_path)
            assert ov_claude["AGENTSOCIETY_LLM_API_TYPE"] == "anthropic"
            assert ov_claude["AGENTSOCIETY_CODER_LLM_API_TYPE"] == "anthropic"
            ov_gem = resolve_llm_env_override(session, gemini_res.json()["data"]["id"], tmp_path)
            assert ov_gem["AGENTSOCIETY_LLM_API_BASE"] == "https://generativelanguage.googleapis.com/v1beta/openai"

        # 6. Preflight reflects linked LLM config
        projects = client.get("/api/v1/urban-sim/projects").json()["items"]
        proj_id = projects[0]["id"]
        client.patch(f"/api/v1/urban-sim/projects/{proj_id}", json={"llm_config_id": llm_id})
        pf = client.get(f"/api/v1/urban-sim/projects/{proj_id}/preflight").json()["preflight"]
        assert pf["effective_llm_model"] == "gpt-6-luna"
        assert pf["effective_coder_model"] == "gpt-5.4-nano"
        assert pf["effective_llm_thinking"] == "on"

        # 7. SSRF blocks private loopback on fetch-models when URBAN_SIM_ALLOW_LOCAL_URLS != 1
        monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
        ssrf_resp = client.post(
            "/api/llm-configs/fetch-models",
            json={
                "provider": "openai",
                "base_url": "http://127.0.0.1:9999/v1",
                "api_key": "sk-test",
            },
        )
        assert ssrf_resp.status_code == 400

        # 8. Mock remote /models verifies fetch-models filtering + test-connection
        class _ModelsHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):  # noqa: N802
                if self.path == "/v1/models":
                    payload = json.dumps(
                        {
                            "data": [
                                {"id": "gpt-6-luna"},
                                {"id": "gpt-5.4-mini"},
                                {"id": "gpt-3.5-turbo"},
                                {"id": "whisper-1"},
                            ]
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
            port = srv.server_address[1]
            fetch_resp = client.post(
                "/api/llm-configs/fetch-models",
                json={
                    "provider": "openai",
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "api_key": "sk-mock",
                },
            )
            assert fetch_resp.status_code == 200
            model_ids = [m["model_id"] for m in fetch_resp.json()["data"]["models"]]
            assert "gpt-6-luna" in model_ids
            assert "gpt-5.4-mini" in model_ids
            assert "gpt-3.5-turbo" not in model_ids
            assert "whisper-1" not in model_ids

            probe_resp = client.post(
                "/api/llm-configs/test-connection",
                json={
                    "provider": "openai",
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "api_key": "sk-mock",
                    "model": "gpt-6-luna",
                },
            )
            assert probe_resp.status_code == 200
            probe_data = probe_resp.json()["data"]
            assert probe_data["ok"] is True
            assert probe_data["model_found"] is True
            assert probe_data["models_count"] == 4
        finally:
            srv.shutdown()
            srv.server_close()
