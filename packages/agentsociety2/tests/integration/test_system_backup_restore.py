"""Integration tests for System Backup & Restore (/api/v1/system-backup/*)."""

from __future__ import annotations

import json
import os
import zipfile
from io import BytesIO
from pathlib import Path

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from agentsociety2.backend.app import app
from agentsociety2.backend.services.platform_resources import (
    PlatformAgentTemplate,
    PlatformLLMConfig,
    PlatformSurvey,
    PlatformWorkflowConfig,
)
from agentsociety2.backend.services.system_backup import VALID_BACKUP_SCOPES
from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    encrypt_secret,
)
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimAtlasConfig,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    UrbanSimZone,
    get_engine,
)


def _setup_env(monkeypatch, ws: Path, admin_key: str = "") -> None:
    monkeypatch.setenv("WORKSPACE_PATH", str(ws))
    monkeypatch.setenv("BACKEND_TOKEN", "")
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_KEY", "sk-base-env-key")
    monkeypatch.setenv("AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1")
    monkeypatch.delenv("URBAN_SIM_FERNET_KEY", raising=False)
    monkeypatch.setenv("ADMIN_BACKUP_KEY", admin_key)


def _seed_rich_source_workspace(ws: Path) -> dict[str, str]:
    """Create custom configs + secrets + 2D map + skill + prefill_params in source workspace."""
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # 1. Create custom LLM config with real API key
        llm_resp = client.post(
            "/api/llm-configs",
            json={
                "name": "Staging GPT-6 Provider",
                "description": "Cấu hình Staging đã verify",
                "config": [
                    {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "coder_model": "gpt-6-sol",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-staging-super-secret-llm-key-001",
                        "thinking": "off",
                    }
                ],
            },
        )
        assert llm_resp.status_code == 200
        llm_id = llm_resp.json()["data"]["id"]

        # 2. Create custom UrbanSim project + bind LLM
        proj_resp = client.post(
            "/api/v1/urban-sim/projects",
            json={
                "slug": "staging-tower",
                "name": "Staging Tower Simulation",
                "description": "Dự án thử nghiệm đã chạy ổn",
                "default_portal_url": "https://staging.example.com",
                "router_type": "react",
                "num_steps": 12,
                "tick_seconds": 600,
                "llm_config_id": llm_id,
                "enable_sociological_debrief": False,
                "enable_competency_prepost_quiz": True,
                "competency_rubric_json": json.dumps({"version": "2.0", "pass_score": 80}),
                "seed_mulberrylane_template": False,
            },
        )
        assert proj_resp.status_code == 200
        proj_id = proj_resp.json()["project"]["id"]

        # 3. Create Zone & upload 2D PNG map image
        z_resp = client.post(
            f"/api/v1/urban-sim/projects/{proj_id}/zones",
            json={
                "zone_key": "LOBBY_A",
                "name": "Sảnh Lễ Tân A",
                "zone_type": "LOBBY",
                "description": "Khu vực sảnh chính",
                "sort_order": 1,
            },
        )
        assert z_resp.status_code == 200

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        img_resp = client.post(
            f"/api/v1/urban-sim/projects/{proj_id}/zones/map-image",
            files={"file": ("floorplan.png", png_bytes, "image/png")},
        )
        assert img_resp.status_code == 200

        # 4. Create Persona with domain knowledge + password
        per_resp = client.post(
            f"/api/v1/urban-sim/projects/{proj_id}/personas",
            json={
                "agent_id": 101,
                "full_name": "Nguyễn Văn An",
                "role_code": "RECEPTIONIST",
                "role_title": "Lễ tân Tòa A",
                "department": "Lễ tân",
                "group_type": "BQL",
                "home_zone": "LOBBY_A",
                "domain_knowledge_prompt": "Tri thức nghiệp vụ: luôn kiểm tra mã căn hộ trước khi cấp thẻ.",
                "initial_tasks": ["Kiểm tra ca sáng", "Tiếp nhận phản ánh"],
                "login_username": "letan.a@example.com",
                "login_password": "StagingPersonaPass!999",
            },
        )
        assert per_resp.status_code == 200

        # 5. Update Atlas config with API key
        atlas_resp = client.put(
            f"/api/v1/urban-sim/projects/{proj_id}/atlas",
            json={
                "enabled": True,
                "atlas_api_url": "https://atlas.example.com",
                "atlas_api_key": "atlas-secret-token-xyz-777",
                "actor_persona": "OPERATOR",
                "guardrail_mode": "SAFE_WRITE",
                "record_prefix": "[STG-SIM]",
                "blocked_keywords": ["xóa vĩnh viễn", "chốt sổ"],
            },
        )
        assert atlas_resp.status_code == 200

        # 6. Create Workflow, Survey, Agent Template
        assert (
            client.post(
                "/api/workflow-configs",
                json={"name": "Workflow Migrate Test", "description": "wf", "config": [{"type": "step", "steps": 4}]},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/surveys",
                json={"name": "Survey Migrate Test", "data": {"title": "Khảo sát", "pages": []}},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/agent-templates",
                json={
                    "name": "Template Migrate Test",
                    "description": "tpl",
                    "agent_type": "citizen",
                    "agent_class": "PersonAgent",
                    "agent_params": {"max_react_turns": 9, "system_prompt": "Văn phong lịch sự"},
                    "blocks": {"DailyGuidanceSkill": {"language": "vi"}},
                },
            ).status_code
            == 200
        )

        # 7. Create Custom Skill & prefill_params.json
        assert (
            client.post(
                "/api/v1/agent-skills/create",
                json={
                    "name": "resident-greeting",
                    "description": "Kỹ năng chào hỏi cư dân",
                    "body": "# Hướng dẫn\nLuôn trả lời bằng tiếng Việt trang trọng.",
                    "workspace_path": str(ws),
                },
            ).status_code
            == 200
        )
        prefill_file = ws / ".agentsociety" / "prefill_params.json"
        prefill_file.write_text(
            json.dumps({"version": "1.0", "env_modules": {"demo": {"x": 42}}, "agents": {}}),
            encoding="utf-8",
        )

        return {"llm_id": llm_id, "proj_id": proj_id}


def test_admin_backup_key_guard_and_inventory(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "ws_guard"
    ws.mkdir()
    _setup_env(monkeypatch, ws, admin_key="super-secret-prod-key")

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        st_no_key = client.get("/api/v1/system-backup/status")
        assert st_no_key.status_code == 200
        assert st_no_key.json()["data"]["admin_key_required"] is True
        assert st_no_key.json()["data"]["admin_key_valid"] is False

        assert client.get("/api/v1/system-backup/inventory").status_code == 403
        assert (
            client.get(
                "/api/v1/system-backup/inventory",
                headers={"X-Admin-Backup-Key": "wrong-key"},
            ).status_code
            == 403
        )

        inv_ok = client.get(
            "/api/v1/system-backup/inventory",
            headers={"X-Admin-Backup-Key": "super-secret-prod-key"},
        )
        assert inv_ok.status_code == 200
        data = inv_ok.json()["data"]
        assert len(data["scopes"]) == len(VALID_BACKUP_SCOPES)
        assert data["secrets_summary"]["total"] >= 0


def test_full_export_and_cross_env_fernet_reencryption_restore(
    tmp_path: Path, monkeypatch
) -> None:
    src_ws = tmp_path / "staging_ws"
    dst_ws = tmp_path / "prod_ws"
    src_ws.mkdir()
    dst_ws.mkdir()

    # 1. Seed & export from Staging workspace
    _setup_env(monkeypatch, src_ws, admin_key="stg-key")
    _seed_rich_source_workspace(src_ws)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        exp_resp = client.post(
            "/api/v1/system-backup/export",
            headers={"X-Admin-Backup-Key": "stg-key"},
            json={
                "scopes": list(VALID_BACKUP_SCOPES),
                "include_secrets": True,
                "passphrase": "MigratePass!2026",
                "notes": "Staging ready for Prod",
            },
        )
        assert exp_resp.status_code == 200
        backup_zip = exp_resp.content
        assert exp_resp.headers.get("X-Backup-Sha256")

    # Verify secrets are NOT plaintext inside data/*.json
    with zipfile.ZipFile(BytesIO(backup_zip), "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "secrets.enc.json" in names
        assert "raw_secrets.json" not in names
        assert "sk-staging-super-secret-llm-key-001" not in zf.read("data/llm_configs.json").decode("utf-8")
        assert "StagingPersonaPass!999" not in zf.read("data/urban_sim_personas.json").decode("utf-8")
        assert "atlas-secret-token-xyz-777" not in zf.read("data/urban_sim_atlas_configs.json").decode("utf-8")

    # 2. Switch to fresh Production workspace (different .fernet.key)
    _setup_env(monkeypatch, dst_ws, admin_key="prod-key")

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # Wrong passphrase -> 400
        bad_prev = client.post(
            "/api/v1/system-backup/preview",
            headers={"X-Admin-Backup-Key": "prod-key"},
            files={"file": ("backup.zip", backup_zip, "application/zip")},
            data={"mode": "MERGE_UPSERT", "restore_secrets": "true", "passphrase": "wrong-passphrase"},
        )
        assert bad_prev.status_code == 400

        # Valid preview
        prev_resp = client.post(
            "/api/v1/system-backup/preview",
            headers={"X-Admin-Backup-Key": "prod-key"},
            files={"file": ("backup.zip", backup_zip, "application/zip")},
            data={"mode": "MERGE_UPSERT", "restore_secrets": "true", "passphrase": "MigratePass!2026"},
        )
        assert prev_resp.status_code == 200
        prev_data = prev_resp.json()["data"]
        assert prev_data["can_apply"] is True
        assert prev_data["totals"]["secrets_to_restore"] >= 3
        assert prev_data["totals"]["create"] > 0

        # Execute restore
        rest_resp = client.post(
            "/api/v1/system-backup/restore",
            headers={"X-Admin-Backup-Key": "prod-key"},
            files={"file": ("backup.zip", backup_zip, "application/zip")},
            data={
                "mode": "MERGE_UPSERT",
                "restore_secrets": "true",
                "passphrase": "MigratePass!2026",
                "create_snapshot": "true",
            },
        )
        assert rest_resp.status_code == 200
        rest_data = rest_resp.json()["data"]
        assert rest_data["success"] is True
        assert rest_data["pre_restore_snapshot"] is not None

    # Verify Production .fernet.key differs from Staging .fernet.key AND all 3 secrets decrypt cleanly on Production
    assert (src_ws / ".agentsociety" / ".fernet.key").read_bytes() != (
        dst_ws / ".agentsociety" / ".fernet.key"
    ).read_bytes()

    dst_engine = get_engine(dst_ws)
    with Session(dst_engine) as session:
        llm_row = session.exec(
            select(PlatformLLMConfig).where(PlatformLLMConfig.name == "Staging GPT-6 Provider")
        ).first()
        assert llm_row is not None
        entries = json.loads(llm_row.config_json)
        assert decrypt_secret(entries[0]["api_key_enc"], dst_ws) == "sk-staging-super-secret-llm-key-001"

        proj_row = session.exec(
            select(UrbanSimProject).where(UrbanSimProject.slug == "staging-tower")
        ).first()
        assert proj_row is not None
        assert proj_row.llm_config_id == llm_row.id
        assert proj_row.enable_sociological_debrief is False
        assert proj_row.enable_competency_prepost_quiz is True

        zone_row = session.exec(
            select(UrbanSimZone).where(
                UrbanSimZone.project_id == proj_row.id,
                UrbanSimZone.zone_key == "LOBBY_A",
            )
        ).first()
        assert zone_row is not None

        per_row = session.exec(
            select(UrbanSimPersona).where(
                UrbanSimPersona.project_id == proj_row.id,
                UrbanSimPersona.agent_id == 101,
            )
        ).first()
        assert per_row is not None
        assert "kiểm tra mã căn hộ" in per_row.domain_knowledge_prompt
        assert decrypt_secret(per_row.login_password_enc, dst_ws) == "StagingPersonaPass!999"

        atlas_row = session.get(UrbanSimAtlasConfig, proj_row.id)
        assert atlas_row is not None
        assert decrypt_secret(atlas_row.atlas_api_key_enc, dst_ws) == "atlas-secret-token-xyz-777"

        assert session.exec(select(PlatformWorkflowConfig).where(PlatformWorkflowConfig.name == "Workflow Migrate Test")).first() is not None
        assert session.exec(select(PlatformSurvey).where(PlatformSurvey.name == "Survey Migrate Test")).first() is not None
        assert session.exec(select(PlatformAgentTemplate).where(PlatformAgentTemplate.name == "Template Migrate Test")).first() is not None

    # Verify workspace files restored (including bare-filename 2D map image served via API)
    assert (dst_ws / "custom" / "skills" / "resident-greeting" / "SKILL.md").is_file()
    assert json.loads((dst_ws / ".agentsociety" / "prefill_params.json").read_text(encoding="utf-8"))["env_modules"]["demo"]["x"] == 42
    assert proj_row.zone_map_image_rel
    assert "/" not in proj_row.zone_map_image_rel
    assert (dst_ws / ".agentsociety" / "urban_sim_maps" / proj_row.zone_map_image_rel).is_file()

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        map_img_resp = client.get(f"/api/v1/urban-sim/projects/{proj_row.id}/zones/map-image")
        assert map_img_resp.status_code == 200
        assert map_img_resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_export_without_secrets_preserves_production_secrets_and_selective_scope(
    tmp_path: Path, monkeypatch
) -> None:
    src_ws = tmp_path / "src_no_sec"
    dst_ws = tmp_path / "dst_has_sec"
    src_ws.mkdir()
    dst_ws.mkdir()

    # 1. Seed source & export WITHOUT secrets, only llm_configs + platform_workflows_surveys
    _setup_env(monkeypatch, src_ws)
    _seed_rich_source_workspace(src_ws)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        exp_resp = client.post(
            "/api/v1/system-backup/export",
            json={
                "scopes": ["llm_configs", "platform_workflows_surveys"],
                "include_secrets": False,
            },
        )
        assert exp_resp.status_code == 200
        backup_zip = exp_resp.content

    # 2. Seed Production with an existing LLM config of same name + Prod API key + Prod survey
    _setup_env(monkeypatch, dst_ws)
    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        assert (
            client.post(
                "/api/llm-configs",
                json={
                    "name": "Staging GPT-6 Provider",
                    "description": "Prod old description",
                    "config": [
                        {
                            "provider": "openai",
                            "model": "gpt-5.5",
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "sk-production-key-must-be-preserved",
                        }
                    ],
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/surveys",
                json={"name": "Prod Existing Survey", "data": {"title": "Prod", "pages": []}},
            ).status_code
            == 200
        )

        # Restore only llm_configs (selective scope -> workflow/survey in zip skipped!)
        rest_resp = client.post(
            "/api/v1/system-backup/restore",
            files={"file": ("b.zip", backup_zip, "application/zip")},
            data={
                "scopes_json": json.dumps(["llm_configs"]),
                "mode": "MERGE_UPSERT",
                "restore_secrets": "false",
            },
        )
        assert rest_resp.status_code == 200
        assert rest_resp.json()["data"]["effective_scopes"] == ["llm_configs"]

    dst_engine = get_engine(dst_ws)
    with Session(dst_engine) as session:
        llm_row = session.exec(
            select(PlatformLLMConfig).where(PlatformLLMConfig.name == "Staging GPT-6 Provider")
        ).first()
        assert llm_row is not None
        assert llm_row.description == "Cấu hình Staging đã verify"
        entries = json.loads(llm_row.config_json)
        assert entries[0]["model"] == "gpt-6-luna"
        # Existing Production secret preserved!
        assert decrypt_secret(entries[0]["api_key_enc"], dst_ws) == "sk-production-key-must-be-preserved"

        # Selective restore did NOT import Workflow Migrate Test
        assert session.exec(select(PlatformWorkflowConfig).where(PlatformWorkflowConfig.name == "Workflow Migrate Test")).first() is None
        assert session.exec(select(PlatformSurvey).where(PlatformSurvey.name == "Prod Existing Survey")).first() is not None


def test_replace_scope_and_one_click_rollback(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "ws_rollback"
    ws.mkdir()
    _setup_env(monkeypatch, ws)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        # Initial Prod state: Workflow A + Survey A
        assert (
            client.post(
                "/api/workflow-configs",
                json={"name": "Prod Original Workflow", "description": "orig", "config": [{"steps": 2}]},
            ).status_code
            == 200
        )
        # Export a package containing ONLY Workflow B
        exp_a = client.post(
            "/api/v1/system-backup/export",
            json={"scopes": ["platform_workflows_surveys"], "include_secrets": False},
        ).content

        # Mutate state: replace workflows via another backup
        assert (
            client.post(
                "/api/workflow-configs",
                json={"name": "New Workflow To Replace", "description": "new", "config": [{"steps": 5}]},
            ).status_code
            == 200
        )
        # Restore with REPLACE_SCOPE using exp_a (which only had Prod Original Workflow)
        rest_resp = client.post(
            "/api/v1/system-backup/restore",
            files={"file": ("b.zip", exp_a, "application/zip")},
            data={"mode": "REPLACE_SCOPE", "restore_secrets": "false", "create_snapshot": "true"},
        )
        assert rest_resp.status_code == 200
        snap_id = rest_resp.json()["data"]["pre_restore_snapshot"]["snapshot_id"]

        # Verify New Workflow To Replace was removed by REPLACE_SCOPE
        wf_list = [w["name"] for w in client.get("/api/workflow-configs").json()["data"]]
        assert "New Workflow To Replace" not in wf_list
        assert "Prod Original Workflow" in wf_list

        # Rollback 1-Click to pre_restore snapshot -> New Workflow To Replace is back!
        rb_resp = client.post(f"/api/v1/system-backup/snapshots/{snap_id}/rollback")
        assert rb_resp.status_code == 200
        wf_list_after = [w["name"] for w in client.get("/api/workflow-configs").json()["data"]]
        assert "New Workflow To Replace" in wf_list_after
        assert "Prod Original Workflow" in wf_list_after


def test_active_run_blocks_urban_sim_restore_and_security_zip_checks(
    tmp_path: Path, monkeypatch
) -> None:
    ws = tmp_path / "ws_sec"
    ws.mkdir()
    _setup_env(monkeypatch, ws)

    with TestClient(app, base_url="http://127.0.0.1:8001") as client:
        exp_resp = client.post(
            "/api/v1/system-backup/export",
            json={"scopes": ["urban_sim_projects"], "include_secrets": False},
        )
        assert exp_resp.status_code == 200
        good_zip = exp_resp.content

        # 1. Zip-Slip protection
        bad_buf = BytesIO()
        with zipfile.ZipFile(bad_buf, "w") as zf:
            zf.writestr("../escape.txt", b"evil")
            zf.writestr("manifest.json", b"{}")
        slip_resp = client.post(
            "/api/v1/system-backup/preview",
            files={"file": ("slip.zip", bad_buf.getvalue(), "application/zip")},
            data={"mode": "MERGE_UPSERT"},
        )
        assert slip_resp.status_code == 400

        # 2. Tampered checksum protection
        tamper_buf = BytesIO()
        with zipfile.ZipFile(BytesIO(good_zip), "r") as src_zf, zipfile.ZipFile(tamper_buf, "w") as dst_zf:
            for item in src_zf.infolist():
                content = src_zf.read(item.filename)
                if item.filename == "data/urban_sim_projects.json":
                    content = b"[]"
                dst_zf.writestr(item.filename, content)
        tamper_resp = client.post(
            "/api/v1/system-backup/preview",
            files={"file": ("tamper.zip", tamper_buf.getvalue(), "application/zip")},
            data={"mode": "MERGE_UPSERT"},
        )
        assert tamper_resp.status_code == 400

        # 3. Active UrbanSimRun blocks restore with 409
        engine = get_engine(ws)
        with Session(engine) as session:
            proj = session.exec(select(UrbanSimProject)).first()
            assert proj is not None
            session.add(
                UrbanSimRun(
                    id="run_active_block_test",
                    project_id=proj.id,
                    run_number=99,
                    run_dir=str(ws / "run_99"),
                    status="RUNNING",
                )
            )
            session.commit()

        prev_blocked = client.post(
            "/api/v1/system-backup/preview",
            files={"file": ("good.zip", good_zip, "application/zip")},
            data={"mode": "MERGE_UPSERT"},
        )
        assert prev_blocked.status_code == 200
        assert prev_blocked.json()["data"]["can_apply"] is False

        rest_blocked = client.post(
            "/api/v1/system-backup/restore",
            files={"file": ("good.zip", good_zip, "application/zip")},
            data={"mode": "MERGE_UPSERT"},
        )
        assert rest_blocked.status_code == 409

        # Ensure encrypt_secret sanity in target ws still works
        token = encrypt_secret("check", ws)
        assert decrypt_secret(token, ws) == "check"
