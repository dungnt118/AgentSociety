"""Integration & performance tests for Digital Urban Map, Checkpoints, Movement Engine, and Backup (L1 DoD)."""

from __future__ import annotations

import asyncio
import json
import statistics
import struct
import time
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from agentsociety2.backend.app import app
from agentsociety2.backend.services.platform_resources import PlatformLLMConfig, PlatformMapConfig
from agentsociety2.backend.services.system_backup import execute_restore, export_backup_zip
from agentsociety2.backend.services.urban_sim.compiler import compile_run_from_db
from agentsociety2.backend.services.urban_sim.crypto import encrypt_secret
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimCheckpoint,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    UrbanSimZone,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.backend.services.urban_sim.seed_mulberrylane import ensure_mulberrylane_seed
from agentsociety2.contrib.env.urban_comm_incident import UrbanCommAndIncidentEnv


def _make_png(width: int, height: int) -> bytes:
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_row = b"\x00" + b"\x00\x00\x00" * min(width, 16)
    compressed = zlib.compress(raw_row if width <= 16 else b"\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


def _seed_project_llm(ws: Path, *, base_url: str = "https://api.openai.com/v1", provider: str = "openai") -> str:
    engine = get_engine(ws)
    with Session(engine) as session:
        cfg = PlatformLLMConfig(
            name="Test Map LLM",
            description="LLM for digital map tests",
            config_json=json.dumps(
                [
                    {
                        "provider": provider,
                        "model": "gpt-4o-mini",
                        "base_url": base_url,
                        "api_type": "openai",
                        "api_key_enc": encrypt_secret("sk-test-1234567890", ws),
                    }
                ]
            ),
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg.id


def test_l1_tc_01_legacy_maps_guard_and_pb_compat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # Ensure linked urban_zones record blocks edit of file_path/map_type and delete
        maps_res = client.get("/api/map-configs")
        assert maps_res.status_code == 200
        urban_row = next(
            (m for m in maps_res.json()["data"] if m.get("map_type") == "urban_zones"),
            None,
        )
        if urban_row is None:
            created_u = client.post(
                "/api/map-configs",
                json={
                    "name": "MulberryLane Linked",
                    "description": "Linked",
                    "config": {
                        "file_path": "urban_sim://mulberrylane/zones",
                        "map_type": "urban_zones",
                        "linked_project_id": proj.id,
                    },
                },
            )
            assert created_u.status_code == 200
            urban_row = created_u.json()["data"]

        assert urban_row.get("managed_by") == "urban_sim"

        put_409 = client.put(
            f"/api/map-configs/{urban_row['id']}",
            json={
                "name": "MulberryLane Tamper",
                "description": "Tamper",
                "config": {"file_path": "maps/other.pb", "map_type": "protobuf"},
            },
        )
        assert put_409.status_code == 409

        del_409 = client.delete(f"/api/map-configs/{urban_row['id']}")
        assert del_409.status_code == 409

        # Reject non-.pb upload (415) and image_2d creation (400)
        up_415 = client.post(
            "/api/map-configs/-/upload",
            files={"file": ("floor.png", _make_png(16, 16), "image/png")},
        )
        assert up_415.status_code == 415

        post_400 = client.post(
            "/api/map-configs",
            json={
                "name": "Image 2D Disallowed",
                "config": {"file_path": "x/floor.png", "map_type": "image_2d"},
            },
        )
        assert post_400.status_code == 400

        # Allow .pb upload (200)
        up_200 = client.post(
            "/api/map-configs/-/upload",
            files={"file": ("city.pb", b"\x08\x01\x12\x04city", "application/octet-stream")},
        )
        assert up_200.status_code == 200
        assert up_200.json()["data"]["map_type"] == "protobuf"


def test_l1_tc_02_migrations_bomb_guard_and_dynamic_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    # Idempotent init twice
    init_urban_sim_db(tmp_path)
    init_urban_sim_db(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        c_proj = client.post(
            "/api/v1/urban-sim/projects",
            json={
                "slug": "empty-map-proj",
                "name": "Dự án trống bản đồ",
                "seed_mulberrylane_template": False,
            },
        )
        assert c_proj.status_code == 200
        pid = c_proj.json()["project"]["id"]
        assert c_proj.json()["project"]["has_digital_map"] is False

        # Dynamic gating 409 when creating checkpoint without Digital Map
        cp_409 = client.post(
            f"/api/v1/urban-sim/projects/{pid}/checkpoints",
            json={"name": "Cổng Chính", "x_pct": 10, "y_pct": 80, "icon_emoji": "🛡️"},
        )
        assert cp_409.status_code == 409
        assert cp_409.json()["detail"]["code"] == "DIGITAL_MAP_REQUIRED"

        gen_409 = client.post(
            f"/api/v1/urban-sim/projects/{pid}/checkpoints/generate",
            json={"prompt": "Tạo các chốt an ninh cho dự án mới"},
        )
        assert gen_409.status_code == 409

        # Upload valid PNG first -> has_digital_map turns True
        ok_png = _make_png(800, 500)
        up_ok = client.post(
            f"/api/v1/urban-sim/projects/{pid}/zones/map-image",
            files={"file": ("plan.png", ok_png, "image/png")},
        )
        assert up_ok.status_code == 200
        assert up_ok.json()["map_width"] == 800
        assert up_ok.json()["map_height"] == 500
        assert up_ok.json()["map_image_version"] == 1

        # Now decompression bomb (20000x20000) must return 400 and NOT erase old image!
        bomb_png = _make_png(20000, 20000)
        up_bomb = client.post(
            f"/api/v1/urban-sim/projects/{pid}/zones/map-image",
            files={"file": ("bomb.png", bomb_png, "image/png")},
        )
        assert up_bomb.status_code == 400
        img_get = client.get(f"/api/v1/urban-sim/projects/{pid}/zones/map-image")
        assert img_get.status_code == 200
        assert img_get.headers.get("x-content-type-options") == "nosniff"

        # Add checkpoint now -> succeeds, then deleting map image without polygons returns 409
        cp_ok = client.post(
            f"/api/v1/urban-sim/projects/{pid}/checkpoints",
            json={"name": "Cổng Bắc", "x_pct": 25, "y_pct": 25, "icon_emoji": "🛡️"},
        )
        assert cp_ok.status_code == 200
        del_img_409 = client.delete(f"/api/v1/urban-sim/projects/{pid}/zones/map-image")
        assert del_img_409.status_code == 409


def test_l1_tc_03_ai_generation_ssrf_vision_fallback_lock_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    # 1. SSRF check on local base_url when provider != vllm
    bad_llm_id = _seed_project_llm(tmp_path, base_url="http://127.0.0.1:9999/v1", provider="openai")
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        client.patch(
            f"/api/v1/urban-sim/projects/{proj.id}",
            json={"llm_config_id": bad_llm_id},
        )
        ssrf_res = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/digital-map/generate",
            json={"map_prompt": "Tạo bản đồ khuôn viên gồm 2 khu vực"},
        )
        assert ssrf_res.status_code == 400
        assert "SSRF" in ssrf_res.json()["detail"]

        # 2. Switch to valid external URL + upload image -> test Vision 400 fail-fast (0 retries -> Text-only fallback)
        good_llm_id = _seed_project_llm(tmp_path, base_url="https://api.openai.com/v1", provider="openai")
        client.patch(
            f"/api/v1/urban-sim/projects/{proj.id}",
            json={"llm_config_id": good_llm_id},
        )
        client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/map-image",
            files={"file": ("site.png", _make_png(640, 400), "image/png")},
        )

        call_log: list[bool] = []

        async def _fake_acompletion(*_args, **kwargs):
            msgs = kwargs.get("messages") or []
            is_vision = any(isinstance(m.get("content"), list) for m in msgs if isinstance(m, dict))
            call_log.append(is_vision)
            if is_vision:
                exc = RuntimeError("BadRequestError: This model does not support image_url inputs")
                setattr(exc, "status_code", 400)
                raise exc
            payload = {
                "aspect_ratio": 1.6,
                "zones": [
                    {
                        "zone_key": "LOBBY_MAIN",
                        "name": "Sảnh Lễ tân Trung tâm",
                        "zone_type": "LOBBY",
                        "description": "Khu sảnh mới",
                        "ambient_signals": "Đông đúc buổi sáng",
                        "fill_color": "#0ea5e9",
                        "polygon_points": [[10, 10], [45, 10], [45, 45], [10, 45]],
                    },
                    {
                        "zone_key": "PARK_SOUTH",
                        "name": "Công viên Phía Nam",
                        "zone_type": "UTILITY",
                        "description": "Khu cây xanh mới",
                        "ambient_signals": "Dạo bộ chiều",
                        "fill_color": "#10b981",
                        "polygon_points": [[55, 55], [90, 55], [90, 90], [55, 90]],
                    },
                ],
            }
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, prompt_tokens_details=None),
            )

        from agentsociety2.config import llm_dispatcher

        monkeypatch.setattr(
            llm_dispatcher,
            "_build_router",
            lambda *_a, **_kw: SimpleNamespace(acompletion=_fake_acompletion),
        )

        gen_res = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/digital-map/generate",
            json={"map_prompt": "Sinh sơ đồ sảnh lễ tân và công viên phía nam"},
        )
        assert gen_res.status_code == 200
        body = gen_res.json()
        # Vision called exactly ONCE (0 retries!) then 1 text-only call
        assert call_log == [True, False]
        assert body["used_vision"] is False
        assert body["fallback_reason"]
        assert len(body["zones"]) == 2

        # 3. Apply MERGE preserves existing 22 personas' home_zone
        merge_res = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/digital-map/apply",
            json={
                "mode": "MERGE",
                "map_prompt": "Updated prompt",
                "zones": body["zones"],
            },
        )
        assert merge_res.status_code == 200
        pers = client.get(f"/api/v1/urban-sim/projects/{proj.id}/personas").json()["items"]
        assert len(pers) == 22
        assert all(bool(p["home_zone"]) for p in pers)


@pytest.mark.asyncio
async def test_l1_tc_03b_concurrent_lock_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)
    good_llm_id = _seed_project_llm(tmp_path, base_url="https://api.openai.com/v1", provider="openai")

    engine = get_engine(tmp_path)
    with Session(engine) as s:
        p = s.get(UrbanSimProject, proj.id)
        assert p is not None
        p.llm_config_id = good_llm_id
        s.add(p)
        s.commit()

    from agentsociety2.config import llm_dispatcher

    async def _slow_acompletion(*_args, **_kwargs):
        await asyncio.sleep(0.25)
        payload = {
            "aspect_ratio": 1.6,
            "zones": [
                {
                    "zone_key": "ZONE_ONE",
                    "name": "Zone One",
                    "zone_type": "LOBBY",
                    "polygon_points": [[10, 10], [40, 10], [40, 40], [10, 40]],
                }
            ],
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, prompt_tokens_details=None),
        )

    monkeypatch.setattr(
        llm_dispatcher,
        "_build_router",
        lambda *_a, **_kw: SimpleNamespace(acompletion=_slow_acompletion),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as ac:
        r1_task = asyncio.create_task(
            ac.post(
                f"/api/v1/urban-sim/projects/{proj.id}/digital-map/generate",
                json={"map_prompt": "Tạo khu vực 1"},
            )
        )
        await asyncio.sleep(0.05)
        r2 = await ac.post(
            f"/api/v1/urban-sim/projects/{proj.id}/digital-map/generate",
            json={"map_prompt": "Tạo khu vực đồng thời"},
        )
        r1 = await r1_task
        assert r1.status_code == 200
        assert r2.status_code == 409


def test_l1_tc_04_tc_05_zones_layout_point_and_checkpoints_cascade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        zones = client.get(f"/api/v1/urban-sim/projects/{proj.id}/zones").json()["items"]
        z0 = zones[0]

        # Atomic rollback on bad layout batch
        bad_layout = client.put(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/layout",
            json={
                "zones": [
                    {"id": z0["id"], "polygon_points": [[5, 5], [25, 5], [25, 25], [5, 25]]},
                    {"id": "non_existent_zone", "polygon_points": [[10, 10], [20, 10], [20, 20]]},
                ]
            },
        )
        assert bad_layout.status_code == 404
        z0_after = next(
            z for z in client.get(f"/api/v1/urban-sim/projects/{proj.id}/zones").json()["items"] if z["id"] == z0["id"]
        )
        assert z0_after["polygon_points"] == z0["polygon_points"]

        # Valid layout persists
        ok_layout = client.put(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/layout",
            json={
                "zones": [
                    {"id": z0["id"], "polygon_points": [[6, 66], [28, 66], [28, 92], [6, 92]]}
                ]
            },
        )
        assert ok_layout.status_code == 200

        # Checkpoint inside TOWER_A -> rename TOWER_A -> TOWER_X -> cascade update
        cp_res = client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/checkpoints",
            json={
                "checkpoint_key": "CP_CUSTOM_ZEN",
                "name": "Điểm kiểm tra Zen A",
                "x_pct": 44.0,
                "y_pct": 52.0,
                "icon_emoji": "🔧",
                "description_md": "### Kiểm tra\n- Đèn hành lang",
            },
        )
        assert cp_res.status_code == 200
        assert cp_res.json()["checkpoint"]["zone_key"] == "TOWER_A"

        tower_a = next(z for z in zones if z["zone_key"] == "TOWER_A")
        ren_res = client.patch(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/{tower_a['id']}",
            json={"zone_key": "TOWER_X"},
        )
        assert ren_res.status_code == 200
        cps = client.get(f"/api/v1/urban-sim/projects/{proj.id}/checkpoints").json()["items"]
        custom_cp = next(c for c in cps if c["checkpoint_key"] == "CP_CUSTOM_ZEN")
        assert custom_cp["zone_key"] == "TOWER_X"

        # Idempotent apply-batch called twice
        batch_payload = {
            "checkpoints": [
                {
                    "checkpoint_key": "CP_BATCH_TEST",
                    "name": "Chốt Lô Test",
                    "x_pct": 49.0,
                    "y_pct": 80.0,
                    "icon_emoji": "🛎️",
                    "category": "service",
                    "description_md": "Kiểm thử batch idempotent",
                }
            ]
        }
        b1 = client.post(f"/api/v1/urban-sim/projects/{proj.id}/checkpoints/apply-batch", json=batch_payload)
        b2 = client.post(f"/api/v1/urban-sim/projects/{proj.id}/checkpoints/apply-batch", json=batch_payload)
        assert b1.status_code == 200 and b2.status_code == 200
        cps_final = client.get(f"/api/v1/urban-sim/projects/{proj.id}/checkpoints").json()["items"]
        assert sum(1 for c in cps_final if c["checkpoint_key"] == "CP_BATCH_TEST") == 1


@pytest.mark.asyncio
async def test_l1_tc_06_env_snapshot_live_overlay_legacy_resume_and_perf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # Upload image to verify run snapshot isolation
        client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/map-image",
            files={"file": ("snap.png", _make_png(800, 500), "image/png")},
        )

        engine = get_engine(tmp_path)
        with Session(engine) as session:
            db_proj = session.get(UrbanSimProject, proj.id)
            assert db_proj is not None
            personas = list(session.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
            zones = list(session.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == proj.id)).all())
            cps = list(session.exec(select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == proj.id)).all())
            run_id = "urbrun_001_testlive"
            run_dir = (tmp_path / "urban_sim_runs" / db_proj.slug / run_id).resolve()
            bundle = compile_run_from_db(
                project=db_proj,
                personas=personas,
                atlas=None,
                zones=zones,
                checkpoints=cps,
                run_dir=run_dir,
                workspace_root=tmp_path,
            )
            session.add(
                UrbanSimRun(
                    id=run_id,
                    project_id=db_proj.id,
                    run_number=1,
                    run_dir=str(run_dir),
                    status="RUNNING",
                    total_steps=db_proj.num_steps,
                    active_agent_count=bundle.active_agent_count,
                )
            )
            session.commit()

        assert (run_dir / "init" / "digital_map_snapshot.json").is_file()
        assert (run_dir / "init" / "map_image.png").is_file()

        # Instantiate env directly & write initial ENV_STATE.json, then move_to_checkpoint WITHOUT calling to_workspace()!
        cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
        env_kwargs = next(m["kwargs"] for m in cfg["env_modules"] if m["module_type"] == "UrbanCommAndIncidentEnv")
        env = UrbanCommAndIncidentEnv(**env_kwargs)
        env_ws = run_dir / "env" / "UrbanCommAndIncidentEnv"
        await env.to_workspace(env_ws)

        # Verify observe_urban_inbox compact map_context cap (<=12 checkpoints, no polygon_points/full markdown)
        inbox = await env.observe_urban_inbox(agent_id=1)
        assert len(inbox["map_context"]["nearby_checkpoints"]) <= 12
        for item in inbox["map_context"]["nearby_checkpoints"]:
            assert len(item["summary"]) <= 120
            assert "description_md" not in item
            assert "polygon_points" not in item

        # Mid-tick move BEFORE ENV_STATE.json flush
        mv = await env.move_to_checkpoint(agent_id=1, checkpoint_key="CP_POOL", activity="Kiểm tra bể bơi")
        assert mv["ok"] is True
        assert mv["checkpoint_key"] == "CP_POOL"

        st = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/state")
        assert st.status_code == 200
        st_data = st.json()
        ag1 = next(a for a in st_data["agent_statuses"] if a["agent_id"] == 1)
        assert ag1["current_checkpoint_key"] == "CP_POOL"
        assert ag1["current_x_pct"] == pytest.approx(44.0)
        assert ag1["current_y_pct"] == pytest.approx(52.0)
        assert len(ag1["recent_trail"]) >= 1
        assert len(st_data["recent_movements"]) >= 1

        # Snapshot isolation: delete project image from DB & disk, old Run map-image & state still work!
        client.delete(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/map-image?clear_orphaned_checkpoints=false"
        )
        run_img = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/map-image")
        assert run_img.status_code == 200

        # Legacy Resume defense: old ENV_STATE.json missing agent_positions/last_move_event_seq & env missing checkpoints
        legacy_ws = tmp_path / "legacy_env_ws"
        legacy_state_file = legacy_ws / "state" / "ENV_STATE.json"
        legacy_state_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_state_file.write_text(
            json.dumps({"mailboxes": {}, "incidents": {}, "agent_zones": {"1": "LOBBY_MAIN"}}),
            encoding="utf-8",
        )
        legacy_env = UrbanCommAndIncidentEnv(
            project_name="Legacy",
            personas=[{"agent_id": 1, "full_name": "Agent 1", "role_title": "BQL", "group_type": "BQL", "home_zone": "LOBBY_MAIN"}],
            zones=[{"zone_key": "LOBBY_MAIN", "name": "Lobby", "zone_type": "LOBBY"}],
            checkpoints=None,
        )
        assert await legacy_env.restore(legacy_ws) is True

        # PERF-01: 2000 urban_events.jsonl lines -> P95 <= 150ms
        events_file = run_dir / "urban_events.jsonl"
        existing_lines = events_file.read_text(encoding="utf-8").splitlines()
        base_seq = len(existing_lines) + 1
        with open(events_file, "a", encoding="utf-8") as fh:
            for i in range(2000):
                aid = (i % 22) + 1
                rec = {
                    "seq": base_seq + i,
                    "stream": "COMM",
                    "agent_id": aid,
                    "agent_name": f"Agent {aid}",
                    "role_title": "Tester",
                    "action": "move_to_checkpoint" if i % 2 == 0 else "send_urban_message",
                    "summary": f"Event {i}",
                    "ok": True,
                    "sim_time": "2026-06-15T08:15:00+07:00",
                    "wall_time": "2026-06-15T08:15:00+00:00",
                    "details": {
                        "to_zone": "TOWER_A",
                        "checkpoint_key": "CP_POOL",
                        "to_x_pct": 44.0,
                        "to_y_pct": 52.0,
                        "activity": "Tuần tra",
                        "movement_status": "patrolling",
                    },
                }
                fh.write(json.dumps(rec) + "\n")

        latencies_ms: list[float] = []
        for _ in range(25):
            t0 = time.perf_counter()
            r = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/state")
            assert r.status_code == 200
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        p95 = statistics.quantiles(latencies_ms, n=20)[-1]
        assert p95 <= 150.0, f"P95 get_run_state too slow: {p95:.1f}ms"


def test_l1_tc_07_backup_restore_replace_fk_and_legacy_v1_compat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ws_src = tmp_path / "src_ws"
    ws_dst = tmp_path / "dst_ws"
    ws_legacy = tmp_path / "legacy_dst_ws"
    ws_src.mkdir()
    ws_dst.mkdir()
    ws_legacy.mkdir()

    monkeypatch.setenv("WORKSPACE_PATH", str(ws_src))
    init_urban_sim_db(ws_src)
    proj = ensure_mulberrylane_seed(ws_src)
    monkeypatch.setenv("BACKEND_TOKEN", "")
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        client.post(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/map-image",
            files={"file": ("src_plan.png", _make_png(800, 500), "image/png")},
        )

    zip_bytes, _manifest = export_backup_zip(
        ws_src,
        scopes=["urban_sim_projects", "urban_sim_zones", "urban_sim_personas"],
        include_secrets=False,
    )

    # Restore in REPLACE_SCOPE on destination workspace (PRAGMA foreign_keys=ON enabled!)
    monkeypatch.setenv("WORKSPACE_PATH", str(ws_dst))
    res = execute_restore(
        ws_dst,
        zip_bytes=zip_bytes,
        selected_scopes=["urban_sim_projects", "urban_sim_zones"],
        mode="REPLACE_SCOPE",
        restore_secrets=False,
    )
    assert res["success"] is True
    # Also test REPLACE_SCOPE on urban_sim_zones alone
    res2 = execute_restore(
        ws_dst,
        zip_bytes=zip_bytes,
        selected_scopes=["urban_sim_zones"],
        mode="REPLACE_SCOPE",
        restore_secrets=False,
    )
    assert res2["success"] is True

    eng_dst = get_engine(ws_dst)
    with Session(eng_dst) as s:
        restored_cps = s.exec(select(UrbanSimCheckpoint)).all()
        restored_zones = s.exec(select(UrbanSimZone)).all()
        assert len(restored_cps) == 8
        assert any(bool(z.polygon_points_json) for z in restored_zones)

    # Legacy v1.0 backup package (missing checkpoints, polygon_points_json, map_width/map_height)
    import hashlib

    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zin:
        entries: dict[str, bytes] = {}
        for item in zin.infolist():
            raw = zin.read(item.filename)
            if item.filename == "data/urban_sim_zones.json":
                zdata = json.loads(raw.decode("utf-8"))
                zdata.pop("checkpoints", None)
                for z in zdata.get("zones", []):
                    z.pop("polygon_points_json", None)
                    z.pop("center_x_pct", None)
                    z.pop("center_y_pct", None)
                raw = json.dumps(zdata).encode("utf-8")
            elif item.filename == "data/urban_sim_projects.json":
                pdata = json.loads(raw.decode("utf-8"))
                for p in pdata:
                    p.pop("map_width", None)
                    p.pop("map_height", None)
                    p.pop("map_aspect_ratio", None)
                raw = json.dumps(pdata).encode("utf-8")
            entries[item.filename] = raw

        manifest_obj = json.loads(entries["manifest.json"].decode("utf-8"))
        manifest_obj["schema_version"] = "1.0"
        manifest_obj["file_checksums"] = {
            k: hashlib.sha256(v).hexdigest()
            for k, v in sorted(entries.items())
            if k != "manifest.json"
        }
        entries["manifest.json"] = json.dumps(manifest_obj, ensure_ascii=False, indent=2).encode("utf-8")
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for k, v in sorted(entries.items()):
                zout.writestr(k, v)
        legacy_zip = buf.getvalue()

    monkeypatch.setenv("WORKSPACE_PATH", str(ws_legacy))
    res_leg = execute_restore(
        ws_legacy,
        zip_bytes=legacy_zip,
        selected_scopes=["urban_sim_projects", "urban_sim_zones"],
        mode="REPLACE_SCOPE",
        restore_secrets=False,
    )
    assert res_leg["success"] is True
    with Session(get_engine(ws_legacy)) as s:
        p_leg = s.exec(select(UrbanSimProject).where(UrbanSimProject.slug == "mulberrylane")).first()
        assert p_leg is not None
        assert p_leg.map_width == 800
        assert p_leg.map_height == 500


def test_l1_tc_08_persona_skills_traits_zone_assign_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy import text

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    # Verify idempotent column migrations on urban_sim_personas
    init_urban_sim_db(tmp_path)
    engine = get_engine(tmp_path)
    with Session(engine) as s:
        cols = {
            row[1]
            for row in s.exec(text("PRAGMA table_info(urban_sim_personas)")).all()
        }
        assert {
            "default_activated_skill_ids_json",
            "disabled_skill_ids_json",
            "profile_traits_json",
        }.issubset(cols)

    # Seed a custom /skills module inside workspace_root/custom/skills/
    custom_skill_dir = tmp_path / "custom" / "skills" / "test-urban-skill"
    custom_skill_dir.mkdir(parents=True, exist_ok=True)
    (custom_skill_dir / "SKILL.md").write_text(
        "---\nname: test-urban-skill\ndescription: Ky nang kiem thu khu do thi\n---\n# Test Skill\n",
        encoding="utf-8",
    )

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        sk_res = client.get("/api/v1/urban-sim/available-skills")
        assert sk_res.status_code == 200
        sk_items = sk_res.json()["items"]
        sk_ids = {it["skill_id"] for it in sk_items}
        assert "custom@test-urban-skill" in sk_ids
        assert "built-in@daily-guidance" in sk_ids

        personas = client.get(f"/api/v1/urban-sim/projects/{proj.id}/personas").json()["items"]
        zones = client.get(f"/api/v1/urban-sim/projects/{proj.id}/zones").json()["items"]
        res_persona = next(p for p in personas if p["group_type"] == "RESIDENT")

        # Assign custom skill + deliberately try assigning QLTN skill to RESIDENT (must be blocked in compiler!)
        patch_res = client.patch(
            f"/api/v1/urban-sim/projects/{proj.id}/personas/{res_persona['id']}",
            json={
                "default_activated_skill_ids": [
                    "custom@test-urban-skill",
                    "env:DemegoWebPortalEnv@bql-qltn-ops-vn",
                ],
                "disabled_skill_ids": ["built-in@daily-guidance"],
                "profile_traits": {
                    "age": 34,
                    "gender": "Nữ",
                    "occupation": "Kiến trúc sư",
                    "personality_tags": ["Cẩn thận", "Yêu thể thao"],
                    "communication_style": "Lịch sự, rõ ràng",
                    "daily_routine": "Chạy bộ lúc 18:00 quanh bể bơi",
                    "background_story": "Cư dân tòa Fantasy từ 2023",
                },
            },
        )
        assert patch_res.status_code == 200
        updated_p = patch_res.json()["persona"]
        assert "custom@test-urban-skill" in updated_p["default_activated_skill_ids"]
        assert updated_p["profile_traits"]["occupation"] == "Kiến trúc sư"

        # Compile run and check custom/skills snapshot, traits formatting, "Khu vực=" label, and QLTN security invariant
        with Session(engine) as s:
            db_proj = s.get(UrbanSimProject, proj.id)
            assert db_proj is not None
            db_personas = list(s.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
            db_zones = list(s.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == proj.id)).all())
            db_cps = list(s.exec(select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == proj.id)).all())
            run_dir = (tmp_path / "urban_sim_runs" / db_proj.slug / "run_tc08_skills").resolve()
            bundle = compile_run_from_db(
                project=db_proj,
                personas=db_personas,
                atlas=None,
                zones=db_zones,
                checkpoints=db_cps,
                run_dir=run_dir,
                workspace_root=tmp_path,
            )

        assert (run_dir / "custom" / "skills" / "test-urban-skill" / "SKILL.md").is_file()
        cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
        compiled_res = next(a for a in cfg["agents"] if a["agent_id"] == res_persona["agent_id"])
        act_skills = compiled_res["kwargs"]["default_activated_skill_ids"]
        dis_skills = compiled_res["kwargs"]["disabled_skill_ids"]
        assert "custom@test-urban-skill" in act_skills
        assert "env:DemegoWebPortalEnv@bql-qltn-ops-vn" not in act_skills
        assert "built-in@daily-guidance" in dis_skills
        prof_desc = compiled_res["kwargs"]["profile"]["description"]
        assert "Kiến trúc sư" in prof_desc
        assert "Khu vực=" in prof_desc
        assert "Zone=" not in prof_desc

        # Test direct zone <-> persona assignment endpoint (assign in + reassign out to fallback)
        target_zone = zones[0]
        fallback_zone = zones[1]
        assign_res = client.put(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/{target_zone['id']}/personas",
            json={
                "persona_ids": [res_persona["id"]],
                "fallback_zone_key": fallback_zone["zone_key"],
            },
        )
        assert assign_res.status_code == 200
        assert res_persona["id"] in assign_res.json()["assigned_persona_ids"]

        personas_after = client.get(f"/api/v1/urban-sim/projects/{proj.id}/personas").json()["items"]
        p_check = next(p for p in personas_after if p["id"] == res_persona["id"])
        assert p_check["home_zone"] == target_zone["zone_key"]

        # Reassign empty list -> moves res_persona out to fallback_zone
        assign_out = client.put(
            f"/api/v1/urban-sim/projects/{proj.id}/zones/{target_zone['id']}/personas",
            json={
                "persona_ids": [],
                "fallback_zone_key": fallback_zone["zone_key"],
            },
        )
        assert assign_out.status_code == 200
        assert assign_out.json()["reassigned_out_count"] >= 1
        personas_after2 = client.get(f"/api/v1/urban-sim/projects/{proj.id}/personas").json()["items"]
        p_check2 = next(p for p in personas_after2 if p["id"] == res_persona["id"])
        assert p_check2["home_zone"] == fallback_zone["zone_key"]

    # System backup export/restore roundtrip preserving skills & profile_traits
    zip_bytes, _ = export_backup_zip(
        tmp_path,
        scopes=["urban_sim_projects", "urban_sim_zones", "urban_sim_personas"],
        include_secrets=False,
    )
    ws_dst = tmp_path / "dst_skills_ws"
    ws_dst.mkdir()
    monkeypatch.setenv("WORKSPACE_PATH", str(ws_dst))
    res_restore = execute_restore(
        ws_dst,
        zip_bytes=zip_bytes,
        selected_scopes=["urban_sim_projects", "urban_sim_zones", "urban_sim_personas"],
        mode="REPLACE_SCOPE",
        restore_secrets=False,
    )
    assert res_restore["success"] is True
    with Session(get_engine(ws_dst)) as s_dst:
        restored_res = s_dst.exec(
            select(UrbanSimPersona).where(
                UrbanSimPersona.project_id == proj.id,
                UrbanSimPersona.agent_id == res_persona["agent_id"],
            )
        ).first()
        assert restored_res is not None
        assert "custom@test-urban-skill" in json.loads(restored_res.default_activated_skill_ids_json)
        assert "built-in@daily-guidance" in json.loads(restored_res.disabled_skill_ids_json)
        assert json.loads(restored_res.profile_traits_json)["occupation"] == "Kiến trúc sư"


@pytest.mark.asyncio
async def test_l1_tc_09_persona_avatar_icon_continuous_clock_and_spatial_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy import text

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.delenv("URBAN_SIM_ALLOW_LOCAL_URLS", raising=False)
    init_urban_sim_db(tmp_path)
    proj = ensure_mulberrylane_seed(tmp_path)

    engine = get_engine(tmp_path)
    with Session(engine) as s:
        cols = {row[1] for row in s.exec(text("PRAGMA table_info(urban_sim_personas)")).all()}
        assert "avatar_icon" in cols

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        personas = client.get(f"/api/v1/urban-sim/projects/{proj.id}/personas").json()["items"]
        sec_p = next(p for p in personas if p["role_code"] == "SEC_STAFF")
        assert sec_p["avatar_icon"] == "👮"

        # Update custom avatar_icon via PATCH and verify persistence
        patch_res = client.patch(
            f"/api/v1/urban-sim/projects/{proj.id}/personas/{sec_p['id']}",
            json={"avatar_icon": "🕵️"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["persona"]["avatar_icon"] == "🕵️"

        # Compile run & verify sim_clock continuous fields + avatar_icon in /state + spatial guidance in inbox
        with Session(engine) as s:
            db_proj = s.get(UrbanSimProject, proj.id)
            assert db_proj is not None
            db_personas = list(s.exec(select(UrbanSimPersona).where(UrbanSimPersona.project_id == proj.id)).all())
            db_zones = list(s.exec(select(UrbanSimZone).where(UrbanSimZone.project_id == proj.id)).all())
            db_cps = list(s.exec(select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == proj.id)).all())
            run_id = "urbrun_tc09_icon_clock"
            run_dir = (tmp_path / "urban_sim_runs" / db_proj.slug / run_id).resolve()
            bundle = compile_run_from_db(
                project=db_proj,
                personas=db_personas,
                atlas=None,
                zones=db_zones,
                checkpoints=db_cps,
                run_dir=run_dir,
                workspace_root=tmp_path,
            )
            s.add(
                UrbanSimRun(
                    id=run_id,
                    project_id=db_proj.id,
                    run_number=9,
                    run_dir=str(run_dir),
                    status="RUNNING",
                    total_steps=db_proj.num_steps,
                    active_agent_count=bundle.active_agent_count,
                )
            )
            s.commit()

        cfg = json.loads(bundle.config_path.read_text(encoding="utf-8"))
        env_kwargs = next(m["kwargs"] for m in cfg["env_modules"] if m["module_type"] == "UrbanCommAndIncidentEnv")
        env = UrbanCommAndIncidentEnv(**env_kwargs)
        inbox = await env.observe_urban_inbox(agent_id=12)
        guidance_txt = inbox["building_context"]["autonomy_guidance"]
        assert "move_to_checkpoint" in guidance_txt
        assert len(inbox["map_context"]["nearby_checkpoints"]) >= 1

        st = client.get(f"/api/v1/urban-sim/projects/{proj.id}/runs/{run_id}/state")
        assert st.status_code == 200
        st_json = st.json()
        sc = st_json["sim_clock"]
        assert sc.get("tick_started_at")
        assert float(sc.get("estimated_tick_wall_seconds") or 0) > 0
        assert "agents_completed_in_tick" in sc
        sec_state = next(a for a in st_json["agent_statuses"] if a["agent_id"] == sec_p["agent_id"])
        assert sec_state["avatar_icon"] == "🕵️"

    # Backup & restore roundtrip preserves custom avatar_icon
    zip_bytes, _ = export_backup_zip(
        tmp_path,
        scopes=["urban_sim_projects", "urban_sim_zones", "urban_sim_personas"],
        include_secrets=False,
    )
    ws_dst = tmp_path / "dst_icon_ws"
    ws_dst.mkdir()
    monkeypatch.setenv("WORKSPACE_PATH", str(ws_dst))
    res_restore = execute_restore(
        ws_dst,
        zip_bytes=zip_bytes,
        selected_scopes=["urban_sim_projects", "urban_sim_zones", "urban_sim_personas"],
        mode="REPLACE_SCOPE",
        restore_secrets=False,
    )
    assert res_restore["success"] is True
    with Session(get_engine(ws_dst)) as s_dst:
        restored_sec = s_dst.exec(
            select(UrbanSimPersona).where(
                UrbanSimPersona.project_id == proj.id,
                UrbanSimPersona.agent_id == sec_p["agent_id"],
            )
        ).first()
        assert restored_sec is not None
        assert restored_sec.avatar_icon == "🕵️"


@pytest.mark.asyncio
async def test_l1_tc_10_evidence_atlas_async_queue_keeps_95s_timeout(tmp_path: Path, monkeypatch):
    """L1-TC-10: Verify EvidenceAtlas non-blocking ticket queue returns <1s without cutting 95s HTTP timeout."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from agentsociety2.backend.services.urban_sim.crypto import encrypt_vault_blob
    from agentsociety2.contrib.env.evidence_atlas_support import EvidenceAtlasSupportEnv

    monkeypatch.setenv("URBAN_SIM_ALLOW_LOCAL_URLS", "1")
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))

    seen_calls: list[dict] = []

    class _SlowAtlasHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            seen_calls.append(body)
            # Simulate slow EvidenceAtlas answer (> async_dispatch_after_sec) while keeping full 95s HTTP timeout
            time.sleep(0.9)
            resp = json.dumps(
                {
                    "ok": True,
                    "answer": "Đã đối chiếu QLTN: vào Menu Vận hành -> Tuần tra An ninh để lập biên bản.",
                    "bot_session_id": "sess_async_95s_001",
                    "message_id": "msg_async_001",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowAtlasHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        run_dir = tmp_path / "atlas_async_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        vault_path = run_dir / ".run_secrets.enc"
        vault_path.write_text(
            encrypt_vault_blob({"atlas": {"atlas_api_url": base_url, "atlas_api_key": "atlas-async-key"}}, tmp_path),
            encoding="utf-8",
        )
        events_path = run_dir / "urban_events.jsonl"
        env = EvidenceAtlasSupportEnv(
            allowed_agent_ids=[3],
            secrets_vault_path=str(vault_path),
            events_log_path=str(events_path),
            atlas_api_url=base_url,
            async_dispatch_after_sec=0.2,
            personas_meta={"3": {"full_name": "NV An ninh 1", "role_title": "Trưởng ca An ninh"}},
        )
        env._bind_workspace(run_dir / "env" / "EvidenceAtlasSupportEnv")

        # 1) First ask dispatches to background well under 0.6s instead of blocking step
        t0 = time.monotonic()
        res1 = await env.ask_atlas_support(agent_id=3, question="Quy trình xử lý sự cố cổng chính trên QLTN?")
        elapsed = time.monotonic() - t0
        assert elapsed < 0.6, f"Expected non-blocking return <0.6s, got {elapsed:.2f}s"
        assert res1["ok"] is True
        assert res1["status"] == "QUEUED_AWAITING_REPLY"
        assert str(res1["ticket_id"]).startswith("ATL-")

        # 2) Duplicate ask while ticket is pending returns ALREADY_PENDING immediately
        res_dup = await env.ask_atlas_support(agent_id=3, question="Nhắc lại câu hỏi khi chưa xong")
        assert res_dup["ok"] is True
        assert res_dup["status"] == "ALREADY_PENDING"
        assert len(res_dup["pending_tickets"]) == 1

        obs_pending = await env.observe_atlas_support(agent_id=3)
        assert len(obs_pending["pending_tickets"]) == 1
        assert obs_pending["unread_replies"] == []

        # 3) Wait for background task (still running with full 95s HTTP timeout) to complete
        for _ in range(25):
            await asyncio.sleep(0.1)
            if events_path.is_file() and events_path.read_text(encoding="utf-8").strip():
                obs_done = await env.observe_atlas_support(agent_id=3)
                if obs_done["unread_replies"]:
                    break
        else:
            pytest.fail("Background Atlas ticket did not deliver reply to observe_atlas_support within 2.5s")

        reply = obs_done["unread_replies"][0]
        assert reply["ticket_id"] == res1["ticket_id"]
        assert reply["ok"] is True
        assert "Tuần tra An ninh" in reply["answer"]
        assert obs_done["bot_session_id"] == "sess_async_95s_001"
        assert obs_done["pending_tickets"] == []

        # Event persisted to urban_events.jsonl & to_workspace()/close() settle cleanly
        ev_lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(ev.get("action") == "ask_atlas_support" and ev.get("ok") is True for ev in ev_lines)
        await env.close()
    finally:
        server.shutdown()
        server.server_close()
