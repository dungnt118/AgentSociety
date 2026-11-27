"""System-wide selective Backup & Restore service for AgentSociety v2.

Supports exporting and restoring SQLite platform/UrbanSim configurations, encrypted
secrets (re-encrypted across environments using a passphrase-derived PBKDF2 Fernet key),
workspace assets (2D zone maps, uploaded map images, prefill_params.json, custom/skills/),
dry-run diff preview, atomic database restore, automatic pre-restore snapshots, and
1-click rollback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import HTTPException
from sqlmodel import Session, select

from agentsociety2.agent.base.skill_registry import get_skill_registry
from agentsociety2.backend.path_security import (
    custom_skills_root,
    require_safe_segment,
    require_safe_skill_name,
    resolve_under_root,
    resolve_urban_sim_map_image,
)
from agentsociety2.backend.services.platform_resources import (
    PlatformAgentConfig,
    PlatformAgentProfile,
    PlatformAgentTemplate,
    PlatformLLMConfig,
    PlatformMapConfig,
    PlatformSurvey,
    PlatformWorkflowConfig,
    _safe_json,
    ensure_platform_seed,
)
from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    encrypt_secret,
)
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimAtlasConfig,
    UrbanSimCheckpoint,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    UrbanSimZone,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.backend.services.urban_sim.map_generator import parse_image_dimensions
from agentsociety2.backend.services.urban_sim.seed_mulberrylane import (
    ensure_mulberrylane_seed,
)
from agentsociety2.logger import get_logger

logger = get_logger()

BACKUP_FORMAT = "agentsociety-config-backup"
BACKUP_SCHEMA_VERSION = "1.0"
PBKDF2_ITERATIONS = 390_000
MIN_PASSPHRASE_LENGTH = 8

MAX_BACKUP_ZIP_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_BACKUP_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # 256 MB
MAX_BACKUP_ENTRIES = 4000
MAX_PLATFORM_MAP_FILE_BYTES = 5 * 1024 * 1024  # Skip >5MB .pb files by default

RestoreMode = Literal["MERGE_UPSERT", "REPLACE_SCOPE"]

_ACTIVE_RUN_STATUSES = {"STARTING", "RUNNING", "PAUSING", "RESUMING"}
_URBAN_SIM_SCOPES = {
    "urban_sim_projects",
    "urban_sim_zones",
    "urban_sim_personas",
    "urban_sim_atlas_configs",
}

BACKUP_SCOPE_CATALOG: list[dict[str, Any]] = [
    {
        "key": "llm_configs",
        "group": "ai_runtime",
        "group_label_vi": "AI & Hạ tầng Mô hình",
        "label_vi": "Cấu hình LLM & Nhà cung cấp AI",
        "label_en": "LLM & AI Provider Configs",
        "label_zh": "LLM 与模型配置",
        "description_vi": "Danh sách nhà cung cấp LLM, model chính/coder, base URL, thiết lập thinking và API key mã hóa.",
        "includes_secrets_possible": True,
        "depends_on": [],
    },
    {
        "key": "urban_sim_projects",
        "group": "urban_sim",
        "group_label_vi": "Mô phỏng Khu đô thị (UrbanSim)",
        "label_vi": "Dự án UrbanSim & Rubric Năng lực",
        "label_en": "UrbanSim Projects & Competency Rubrics",
        "label_zh": "城市仿真项目与能力评估量表",
        "description_vi": "Thông số dự án mô phỏng, URL portal mặc định, router, ngân sách, quiz và rubric đánh giá năng lực.",
        "includes_secrets_possible": False,
        "depends_on": ["llm_configs"],
    },
    {
        "key": "urban_sim_zones",
        "group": "urban_sim",
        "group_label_vi": "Mô phỏng Khu đô thị (UrbanSim)",
        "label_vi": "Khu vực (Zones) & Sơ đồ 2D",
        "label_en": "UrbanSim Zones & 2D Map Images",
        "label_zh": "区域拓扑与 2D 地图",
        "description_vi": "Cấu trúc các khu vực (LOBBY, OFFICE, TOWER...) và tệp ảnh sơ đồ 2D gắn với dự án.",
        "includes_secrets_possible": False,
        "depends_on": ["urban_sim_projects"],
    },
    {
        "key": "urban_sim_personas",
        "group": "urban_sim",
        "group_label_vi": "Mô phỏng Khu đô thị (UrbanSim)",
        "label_vi": "Ma trận Persona, Tri thức nền & Tài khoản",
        "label_en": "Personas, Domain Knowledge & Credentials",
        "label_zh": "角色矩阵、领域知识与登录凭据",
        "description_vi": "Danh sách BQL/Cư dân, vai trò, tri thức miền (domain_knowledge_prompt), nhiệm vụ khởi đầu và mật khẩu cổng web.",
        "includes_secrets_possible": True,
        "depends_on": ["urban_sim_projects"],
    },
    {
        "key": "urban_sim_atlas_configs",
        "group": "urban_sim",
        "group_label_vi": "Mô phỏng Khu đô thị (UrbanSim)",
        "label_vi": "Cấu hình EvidenceAtlas & Sandbox Guardrail",
        "label_en": "EvidenceAtlas Integration & Guardrails",
        "label_zh": "EvidenceAtlas 与安全护栏配置",
        "description_vi": "URL cổng EvidenceAtlas, API key, guardrail_mode, tiền tố bản ghi và danh sách từ khóa bị chặn.",
        "includes_secrets_possible": True,
        "depends_on": ["urban_sim_projects"],
    },
    {
        "key": "platform_maps",
        "group": "platform",
        "group_label_vi": "Tài nguyên Nền tảng & Kịch bản",
        "label_vi": "Cấu hình Bản đồ Nền tảng",
        "label_en": "Platform Map Configs",
        "label_zh": "平台地图配置",
        "description_vi": "Metadata bản đồ nền tảng và tệp ảnh 2D đính kèm (tự động bỏ qua file .pb kích thước lớn).",
        "includes_secrets_possible": False,
        "depends_on": [],
    },
    {
        "key": "platform_agent_templates",
        "group": "platform",
        "group_label_vi": "Tài nguyên Nền tảng & Kịch bản",
        "label_vi": "Mẫu Tác tử (Agent Templates)",
        "label_en": "Agent Templates",
        "label_zh": "智能体模板",
        "description_vi": "Khuôn mẫu tác tử, tham số ReAct, system prompt và các blocks hành vi.",
        "includes_secrets_possible": False,
        "depends_on": [],
    },
    {
        "key": "platform_agent_profiles",
        "group": "platform",
        "group_label_vi": "Tài nguyên Nền tảng & Kịch bản",
        "label_vi": "Hồ sơ Cư dân (Agent Profiles)",
        "label_en": "Agent Profiles",
        "label_zh": "智能体画像",
        "description_vi": "Tập dữ liệu hồ sơ nhân khẩu và vai trò mẫu lưu trong cơ sở dữ liệu nền tảng.",
        "includes_secrets_possible": False,
        "depends_on": [],
    },
    {
        "key": "platform_agent_configs",
        "group": "platform",
        "group_label_vi": "Tài nguyên Nền tảng & Kịch bản",
        "label_vi": "Đội hình Tác tử (Agent Configs)",
        "label_en": "Agent Configs",
        "label_zh": "智能体配置",
        "description_vi": "Cấu hình đội hình tác tử và tham chiếu tới Agent Template / Profile.",
        "includes_secrets_possible": False,
        "depends_on": ["platform_agent_templates"],
    },
    {
        "key": "platform_workflows_surveys",
        "group": "platform",
        "group_label_vi": "Tài nguyên Nền tảng & Kịch bản",
        "label_vi": "Quy trình & Khảo sát (Workflows & Surveys)",
        "label_en": "Workflows & Surveys",
        "label_zh": "工作流与问卷",
        "description_vi": "Các kịch bản bước chạy Workflow và biểu mẫu khảo sát SurveyJS.",
        "includes_secrets_possible": False,
        "depends_on": [],
    },
    {
        "key": "workspace_skills_and_params",
        "group": "workspace",
        "group_label_vi": "Kỹ năng & Tham số Workspace",
        "label_vi": "Kỹ năng tùy chỉnh (Custom Skills) & Prefill Params",
        "label_en": "Custom Skills & Prefill Params",
        "label_zh": "自定义技能与预填充参数",
        "description_vi": "Toàn bộ thư mục kỹ năng trong custom/skills/ (SKILL.md, scripts, references) và tệp .agentsociety/prefill_params.json.",
        "includes_secrets_possible": False,
        "depends_on": [],
    },
]

VALID_BACKUP_SCOPES: tuple[str, ...] = tuple(item["key"] for item in BACKUP_SCOPE_CATALOG)
_VALID_SCOPE_SET: set[str] = set(VALID_BACKUP_SCOPES)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_db_seeded(workspace_root: Path) -> Any:
    init_urban_sim_db(workspace_root)
    ensure_mulberrylane_seed(workspace_root)
    ensure_platform_seed(workspace_root)
    return get_engine(workspace_root)


def _backups_dir(workspace_root: Path) -> Path:
    d = resolve_under_root(workspace_root, ".agentsociety", "backups")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _history_file(workspace_root: Path) -> Path:
    return resolve_under_root(_backups_dir(workspace_root), "history.json")


def _load_history(workspace_root: Path) -> list[dict[str, Any]]:
    hf = _history_file(workspace_root)
    if not hf.is_file():
        return []
    try:
        parsed = json.loads(hf.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, list) else []
    except (OSError, ValueError):
        return []


def _append_history(workspace_root: Path, entry: dict[str, Any]) -> None:
    items = _load_history(workspace_root)
    items.insert(0, entry)
    items = items[:100]
    hf = _history_file(workspace_root)
    hf.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _derive_passphrase_fernet(passphrase: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def encrypt_secrets_bundle(secrets_map: dict[str, str], passphrase: str) -> dict[str, Any]:
    """Encrypt plaintext secrets dictionary using PBKDF2HMAC + Fernet."""
    clean_pass = (passphrase or "").strip()
    if len(clean_pass) < MIN_PASSPHRASE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Mật khẩu bảo vệ bí mật (Passphrase) phải có tối thiểu {MIN_PASSPHRASE_LENGTH} ký tự.",
        )
    salt = os.urandom(16)
    f = _derive_passphrase_fernet(clean_pass, salt)
    payload_bytes = json.dumps(secrets_map, ensure_ascii=False).encode("utf-8")
    token = f.encrypt(payload_bytes).decode("ascii")
    return {
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token,
    }


def decrypt_secrets_bundle(bundle: dict[str, Any], passphrase: str) -> dict[str, str]:
    """Decrypt ``secrets.enc.json`` using the admin-supplied passphrase."""
    clean_pass = (passphrase or "").strip()
    if not clean_pass:
        raise HTTPException(
            status_code=400,
            detail="Gói sao lưu chứa bí mật đã mã hóa. Vui lòng nhập Passphrase để giải mã.",
        )
    try:
        salt = base64.b64decode(str(bundle.get("salt_b64") or ""), validate=True)
        iterations = int(bundle.get("iterations") or PBKDF2_ITERATIONS)
        ciphertext = str(bundle.get("ciphertext") or "").encode("ascii")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = base64.urlsafe_b64encode(kdf.derive(clean_pass.encode("utf-8")))
        raw = Fernet(key).decrypt(ciphertext).decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Invalid secrets payload")
        return {str(k): str(v) for k, v in parsed.items()}
    except InvalidToken as exc:
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu giải mã gói sao lưu (Passphrase) không chính xác.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Không thể đọc gói bí mật đã mã hóa: {exc!s}",
        ) from exc


def validate_selected_scopes(scopes: list[str] | None) -> list[str]:
    if not scopes:
        raise HTTPException(
            status_code=400,
            detail="Vui lòng chọn ít nhất một phạm vi cấu hình để sao lưu hoặc khôi phục.",
        )
    ordered: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for raw in scopes:
        s = str(raw or "").strip()
        if not s:
            continue
        if s not in _VALID_SCOPE_SET:
            unknown.append(s)
        elif s not in seen:
            seen.add(s)
            ordered.append(s)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Phạm vi cấu hình không hợp lệ: {', '.join(unknown)}",
        )
    if not ordered:
        raise HTTPException(
            status_code=400,
            detail="Vui lòng chọn ít nhất một phạm vi cấu hình hợp lệ.",
        )
    # Keep deterministic catalog order
    return [s for s in VALID_BACKUP_SCOPES if s in seen]


def _list_custom_skill_dirs(workspace_root: Path) -> list[Path]:
    skills_dir = custom_skills_root(str(workspace_root))
    if not skills_dir.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name in {"examples", "__pycache__"} or child.name.startswith("."):
            continue
        try:
            require_safe_skill_name(child.name)
        except HTTPException:
            continue
        if (child / "SKILL.md").is_file():
            out.append(child)
    return out


def _has_active_urban_sim_runs(session: Session) -> list[str]:
    runs = session.exec(select(UrbanSimRun)).all()
    return [r.id for r in runs if str(r.status or "").upper() in _ACTIVE_RUN_STATUSES]


def get_backup_inventory(workspace_root: Path) -> dict[str, Any]:
    """Return current counts of all backupable scopes, secret counts, and active runs."""
    engine = _ensure_db_seeded(workspace_root)
    with Session(engine) as session:
        llm_rows = session.exec(select(PlatformLLMConfig)).all()
        proj_rows = session.exec(select(UrbanSimProject)).all()
        zone_rows = session.exec(select(UrbanSimZone)).all()
        checkpoint_rows = session.exec(select(UrbanSimCheckpoint)).all()
        persona_rows = session.exec(select(UrbanSimPersona)).all()
        atlas_rows = session.exec(select(UrbanSimAtlasConfig)).all()
        map_rows = session.exec(select(PlatformMapConfig)).all()
        tpl_rows = session.exec(select(PlatformAgentTemplate)).all()
        profile_rows = session.exec(select(PlatformAgentProfile)).all()
        agent_cfg_rows = session.exec(select(PlatformAgentConfig)).all()
        wf_rows = session.exec(select(PlatformWorkflowConfig)).all()
        survey_rows = session.exec(select(PlatformSurvey)).all()
        active_runs = _has_active_urban_sim_runs(session)

        llm_secrets = 0
        for row in llm_rows:
            entries = _safe_json(row.config_json, [])
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and str(entry.get("api_key_enc") or "").strip():
                        llm_secrets += 1

        persona_secrets = sum(
            1 for p in persona_rows if str(p.login_password_enc or "").strip()
        )
        atlas_secrets = sum(
            1 for a in atlas_rows if str(a.atlas_api_key_enc or "").strip()
        )

        zones_by_proj: dict[str, int] = {}
        for z in zone_rows:
            zones_by_proj[z.project_id] = zones_by_proj.get(z.project_id, 0) + 1
        checkpoints_by_proj: dict[str, int] = {}
        for cp in checkpoint_rows:
            checkpoints_by_proj[cp.project_id] = checkpoints_by_proj.get(cp.project_id, 0) + 1
        personas_by_proj: dict[str, int] = {}
        for p in persona_rows:
            personas_by_proj[p.project_id] = personas_by_proj.get(p.project_id, 0) + 1

        projects_summary = [
            {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "zones_count": zones_by_proj.get(p.id, 0),
                "checkpoints_count": checkpoints_by_proj.get(p.id, 0),
                "personas_count": personas_by_proj.get(p.id, 0),
                "has_zone_map_image": bool(p.zone_map_image_rel),
            }
            for p in proj_rows
        ]

    custom_skills = _list_custom_skill_dirs(workspace_root)
    prefill_file = resolve_under_root(workspace_root, ".agentsociety", "prefill_params.json")
    zone_map_files = sum(1 for p in projects_summary if p["has_zone_map_image"])

    counts: dict[str, int] = {
        "llm_configs": len(llm_rows),
        "urban_sim_projects": len(proj_rows),
        "urban_sim_zones": len(zone_rows),
        "urban_sim_personas": len(persona_rows),
        "urban_sim_atlas_configs": len(atlas_rows),
        "platform_maps": len(map_rows),
        "platform_agent_templates": len(tpl_rows),
        "platform_agent_profiles": len(profile_rows),
        "platform_agent_configs": len(agent_cfg_rows),
        "platform_workflows_surveys": len(wf_rows) + len(survey_rows),
        "workspace_skills_and_params": len(custom_skills) + (1 if prefill_file.is_file() else 0),
    }

    scopes_out: list[dict[str, Any]] = []
    for meta in BACKUP_SCOPE_CATALOG:
        key = meta["key"]
        item = {
            **meta,
            "count": counts[key],
            "extra": {},
        }
        if key == "llm_configs":
            item["extra"] = {"secrets_count": llm_secrets}
        elif key == "urban_sim_zones":
            item["extra"] = {
                "map_images_count": zone_map_files,
                "checkpoints_count": len(checkpoint_rows),
            }
        elif key == "urban_sim_personas":
            item["extra"] = {"secrets_count": persona_secrets}
        elif key == "urban_sim_atlas_configs":
            item["extra"] = {"secrets_count": atlas_secrets}
        elif key == "platform_workflows_surveys":
            item["extra"] = {"workflows": len(wf_rows), "surveys": len(survey_rows)}
        elif key == "workspace_skills_and_params":
            item["extra"] = {
                "skills_count": len(custom_skills),
                "skill_names": [s.name for s in custom_skills],
                "has_prefill_params": prefill_file.is_file(),
            }
        scopes_out.append(item)

    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "scopes": scopes_out,
        "projects": projects_summary,
        "secrets_summary": {
            "llm_api_keys": llm_secrets,
            "persona_passwords": persona_secrets,
            "atlas_api_keys": atlas_secrets,
            "total": llm_secrets + persona_secrets + atlas_secrets,
        },
        "active_urban_sim_runs": active_runs,
    }


def _secret_key_llm(llm_id: str, idx: int) -> str:
    return f"llm:{llm_id}:{idx}"


def _secret_key_persona(project_slug: str, agent_id: int) -> str:
    return f"persona:{project_slug}:{agent_id}"


def _secret_key_atlas(project_slug: str) -> str:
    return f"atlas:{project_slug}"


def export_backup_zip(
    workspace_root: Path,
    *,
    scopes: list[str],
    include_secrets: bool = False,
    passphrase: str = "",
    project_ids: list[str] | None = None,
    notes: str = "",
    raw_local_snapshot: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Export selected configuration scopes into a checksummed ZIP package."""
    selected_scopes = validate_selected_scopes(scopes)
    if include_secrets and not raw_local_snapshot:
        if len((passphrase or "").strip()) < MIN_PASSPHRASE_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Khi mang theo bí mật, Passphrase phải có tối thiểu {MIN_PASSPHRASE_LENGTH} ký tự.",
            )

    engine = _ensure_db_seeded(workspace_root)
    files_map: dict[str, bytes] = {}
    warnings: list[str] = []
    counts: dict[str, int] = {}
    secrets_plain: dict[str, str] = {}
    raw_secrets: dict[str, str] = {}

    selected_project_id_set = (
        {str(pid).strip() for pid in project_ids if str(pid).strip()}
        if project_ids
        else None
    )

    with Session(engine) as session:
        all_projects = session.exec(select(UrbanSimProject)).all()
        proj_by_id = {p.id: p for p in all_projects}
        target_projects = (
            [p for p in all_projects if p.id in selected_project_id_set]
            if selected_project_id_set is not None
            else list(all_projects)
        )
        target_proj_ids = {p.id for p in target_projects}
        proj_slug_by_id = {p.id: p.slug for p in all_projects}

        def _put_json(arcname: str, obj: Any) -> None:
            files_map[arcname] = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")

        # 1. llm_configs
        if "llm_configs" in selected_scopes:
            llm_rows = session.exec(select(PlatformLLMConfig)).all()
            llm_records: list[dict[str, Any]] = []
            for row in llm_rows:
                raw_entries = _safe_json(row.config_json, [])
                clean_entries: list[dict[str, Any]] = []
                if isinstance(raw_entries, list):
                    for idx, entry in enumerate(raw_entries):
                        if not isinstance(entry, dict):
                            continue
                        entry_copy = {k: v for k, v in entry.items() if k != "api_key_enc"}
                        enc = str(entry.get("api_key_enc") or "").strip()
                        skey = _secret_key_llm(row.id, idx)
                        entry_copy["has_secret"] = bool(enc)
                        entry_copy["secret_ref_key"] = skey if enc else ""
                        if enc:
                            if raw_local_snapshot:
                                raw_secrets[skey] = enc
                            elif include_secrets:
                                try:
                                    plain = decrypt_secret(enc, workspace_root)
                                    if plain:
                                        secrets_plain[skey] = plain
                                except ValueError:
                                    warnings.append(
                                        f"Không thể giải mã API key của cấu hình LLM '{row.name}' (#{idx}) bằng Fernet key hiện tại; bỏ qua secret này."
                                    )
                        clean_entries.append(entry_copy)
                llm_records.append(
                    {
                        "id": row.id,
                        "tenant_id": row.tenant_id,
                        "name": row.name,
                        "description": row.description,
                        "entries": clean_entries,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                    }
                )
            _put_json("data/llm_configs.json", llm_records)
            counts["llm_configs"] = len(llm_records)

        # 2. urban_sim_projects
        if "urban_sim_projects" in selected_scopes:
            proj_records = [
                {
                    "id": p.id,
                    "slug": p.slug,
                    "name": p.name,
                    "description": p.description,
                    "default_portal_url": p.default_portal_url,
                    "router_type": p.router_type,
                    "num_steps": int(p.num_steps),
                    "tick_seconds": int(p.tick_seconds),
                    "start_time_iso": p.start_time_iso,
                    "max_react_turns": int(p.max_react_turns),
                    "max_cost_usd_per_run": float(p.max_cost_usd_per_run),
                    "pilot_mode": bool(p.pilot_mode),
                    "zone_map_image_rel": p.zone_map_image_rel,
                    "map_prompt": getattr(p, "map_prompt", None),
                    "map_width": getattr(p, "map_width", None),
                    "map_height": getattr(p, "map_height", None),
                    "map_aspect_ratio": getattr(p, "map_aspect_ratio", None),
                    "map_image_version": int(getattr(p, "map_image_version", 0) or 0),
                    "map_image_updated_at": getattr(p, "map_image_updated_at", None),
                    "llm_config_id": p.llm_config_id,
                    "enable_sociological_debrief": bool(
                        getattr(p, "enable_sociological_debrief", True)
                    ),
                    "enable_competency_prepost_quiz": bool(
                        getattr(p, "enable_competency_prepost_quiz", False)
                    ),
                    "competency_rubric_json": getattr(p, "competency_rubric_json", None),
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                }
                for p in target_projects
            ]
            _put_json("data/urban_sim_projects.json", proj_records)
            counts["urban_sim_projects"] = len(proj_records)

        # 3. urban_sim_zones (+ polygon geometry & urban_sim_checkpoints)
        if "urban_sim_zones" in selected_scopes:
            zones = session.exec(select(UrbanSimZone)).all()
            filtered_zones = [z for z in zones if z.project_id in target_proj_ids]
            zone_records = [
                {
                    "id": z.id,
                    "project_id": z.project_id,
                    "project_slug": proj_slug_by_id.get(z.project_id, ""),
                    "zone_key": z.zone_key,
                    "name": z.name,
                    "zone_type": z.zone_type,
                    "description": z.description,
                    "ambient_signals": z.ambient_signals,
                    "sort_order": int(z.sort_order),
                    "center_x_pct": getattr(z, "center_x_pct", None),
                    "center_y_pct": getattr(z, "center_y_pct", None),
                    "polygon_points_json": getattr(z, "polygon_points_json", None),
                    "fill_color": getattr(z, "fill_color", None),
                }
                for z in filtered_zones
            ]
            cps = session.exec(select(UrbanSimCheckpoint)).all()
            filtered_cps = [cp for cp in cps if cp.project_id in target_proj_ids]
            cp_records = [
                {
                    "id": cp.id,
                    "project_id": cp.project_id,
                    "project_slug": proj_slug_by_id.get(cp.project_id, ""),
                    "checkpoint_key": cp.checkpoint_key,
                    "name": cp.name,
                    "x_pct": float(cp.x_pct),
                    "y_pct": float(cp.y_pct),
                    "icon_emoji": cp.icon_emoji,
                    "description_md": cp.description_md,
                    "zone_key": cp.zone_key,
                    "category": cp.category,
                    "sort_order": int(cp.sort_order),
                }
                for cp in filtered_cps
            ]
            # Export associated 2D zone map images
            map_image_refs: dict[str, str] = {}
            for p in target_projects:
                if not p.zone_map_image_rel:
                    continue
                fname = Path(p.zone_map_image_rel).name
                try:
                    img_path = resolve_urban_sim_map_image(workspace_root, fname)
                    if img_path.is_file():
                        arc = f"files/urban_sim_maps/{fname}"
                        files_map[arc] = img_path.read_bytes()
                        map_image_refs[p.slug] = p.zone_map_image_rel
                except HTTPException:
                    warnings.append(f"Bỏ qua ảnh bản đồ 2D không hợp lệ của dự án '{p.slug}': {fname}")
            _put_json(
                "data/urban_sim_zones.json",
                {
                    "zones": zone_records,
                    "checkpoints": cp_records,
                    "project_map_images": map_image_refs,
                },
            )
            counts["urban_sim_zones"] = len(zone_records)

        # 4. urban_sim_personas
        if "urban_sim_personas" in selected_scopes:
            personas = session.exec(select(UrbanSimPersona)).all()
            filtered_personas = [per for per in personas if per.project_id in target_proj_ids]
            persona_records: list[dict[str, Any]] = []
            for per in filtered_personas:
                pslug = proj_slug_by_id.get(per.project_id, "")
                enc = str(per.login_password_enc or "").strip()
                skey = _secret_key_persona(pslug, int(per.agent_id))
                if enc:
                    if raw_local_snapshot:
                        raw_secrets[skey] = enc
                    elif include_secrets:
                        try:
                            plain = decrypt_secret(enc, workspace_root)
                            if plain:
                                secrets_plain[skey] = plain
                        except ValueError:
                            warnings.append(
                                f"Không giải mã được mật khẩu của Persona '{per.full_name}' (agent_id={per.agent_id}); bỏ qua mật khẩu này."
                            )
                persona_records.append(
                    {
                        "id": per.id,
                        "project_id": per.project_id,
                        "project_slug": pslug,
                        "agent_id": int(per.agent_id),
                        "full_name": per.full_name,
                        "role_code": per.role_code,
                        "role_title": per.role_title,
                        "department": per.department,
                        "group_type": per.group_type,
                        "software_access_enabled": bool(per.software_access_enabled),
                        "is_pilot_member": bool(per.is_pilot_member),
                        "is_active": bool(per.is_active),
                        "home_zone": per.home_zone,
                        "avatar_icon": getattr(per, "avatar_icon", None),
                        "domain_knowledge_prompt": per.domain_knowledge_prompt,
                        "initial_tasks_json": per.initial_tasks_json,
                        "portal_url": per.portal_url,
                        "login_username": per.login_username,
                        "default_activated_skill_ids_json": getattr(
                            per, "default_activated_skill_ids_json", None
                        ),
                        "disabled_skill_ids_json": getattr(per, "disabled_skill_ids_json", None),
                        "profile_traits_json": getattr(per, "profile_traits_json", None),
                        "has_secret": bool(enc),
                        "secret_ref_key": skey if enc else "",
                        "created_at": per.created_at,
                        "updated_at": per.updated_at,
                    }
                )
            _put_json("data/urban_sim_personas.json", persona_records)
            counts["urban_sim_personas"] = len(persona_records)

        # 5. urban_sim_atlas_configs
        if "urban_sim_atlas_configs" in selected_scopes:
            atlas_rows = session.exec(select(UrbanSimAtlasConfig)).all()
            filtered_atlas = [a for a in atlas_rows if a.project_id in target_proj_ids]
            atlas_records: list[dict[str, Any]] = []
            for a in filtered_atlas:
                pslug = proj_slug_by_id.get(a.project_id, "")
                enc = str(a.atlas_api_key_enc or "").strip()
                skey = _secret_key_atlas(pslug)
                if enc:
                    if raw_local_snapshot:
                        raw_secrets[skey] = enc
                    elif include_secrets:
                        try:
                            plain = decrypt_secret(enc, workspace_root)
                            if plain:
                                secrets_plain[skey] = plain
                        except ValueError:
                            warnings.append(
                                f"Không giải mã được Atlas API Key của dự án '{pslug}'; bỏ qua key này."
                            )
                atlas_records.append(
                    {
                        "project_id": a.project_id,
                        "project_slug": pslug,
                        "enabled": bool(a.enabled),
                        "atlas_api_url": a.atlas_api_url,
                        "has_secret": bool(enc),
                        "secret_ref_key": skey if enc else "",
                        "actor_persona": a.actor_persona,
                        "source_mode": a.source_mode,
                        "attach_screenshot_on_ask": bool(a.attach_screenshot_on_ask),
                        "quota_per_min": int(a.quota_per_min),
                        "max_asks_per_tick": int(a.max_asks_per_tick),
                        "guardrail_mode": a.guardrail_mode,
                        "record_prefix": a.record_prefix,
                        "blocked_keywords_json": a.blocked_keywords_json,
                        "last_verified_at": a.last_verified_at,
                        "last_verified_project_id": a.last_verified_project_id,
                        "last_verified_project_name": a.last_verified_project_name,
                        "last_verified_scopes_json": a.last_verified_scopes_json,
                        "updated_at": a.updated_at,
                    }
                )
            _put_json("data/urban_sim_atlas_configs.json", atlas_records)
            counts["urban_sim_atlas_configs"] = len(atlas_records)

        # 6. platform_maps
        if "platform_maps" in selected_scopes:
            map_rows = session.exec(select(PlatformMapConfig)).all()
            map_records: list[dict[str, Any]] = []
            for m in map_rows:
                linked_slug = (
                    proj_by_id[m.linked_project_id].slug
                    if m.linked_project_id and m.linked_project_id in proj_by_id
                    else None
                )
                bundled_rel = ""
                if m.file_path and not m.file_path.startswith("urban_sim://"):
                    p = Path(m.file_path)
                    if not p.is_absolute():
                        try:
                            p = resolve_under_root(workspace_root, m.file_path)
                        except HTTPException:
                            p = Path("__invalid__")
                    if p.is_file():
                        size_bytes = p.stat().st_size
                        if m.map_type == "protobuf" and size_bytes > MAX_PLATFORM_MAP_FILE_BYTES:
                            warnings.append(
                                f"Bỏ qua file bản đồ .pb kích thước lớn ({size_bytes // (1024 * 1024)} MB) của '{m.name}'."
                            )
                        elif size_bytes <= MAX_PLATFORM_MAP_FILE_BYTES:
                            arc_name = f"files/platform_uploads/maps/{p.name}"
                            files_map[arc_name] = p.read_bytes()
                            bundled_rel = arc_name
                map_records.append(
                    {
                        "id": m.id,
                        "tenant_id": m.tenant_id,
                        "name": m.name,
                        "description": m.description,
                        "file_path": m.file_path,
                        "bundled_file": bundled_rel,
                        "map_type": m.map_type,
                        "linked_project_id": m.linked_project_id,
                        "linked_project_slug": linked_slug,
                        "created_at": m.created_at,
                        "updated_at": m.updated_at,
                    }
                )
            _put_json("data/platform_maps.json", map_records)
            counts["platform_maps"] = len(map_records)

        # 7. platform_agent_templates
        if "platform_agent_templates" in selected_scopes:
            tpl_rows = session.exec(select(PlatformAgentTemplate)).all()
            tpl_records = [
                {
                    "id": t.id,
                    "tenant_id": t.tenant_id,
                    "name": t.name,
                    "description": t.description,
                    "agent_type": t.agent_type,
                    "agent_class": t.agent_class,
                    "memory_distributions_json": t.memory_distributions_json,
                    "agent_params_json": t.agent_params_json,
                    "blocks_json": t.blocks_json,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                }
                for t in tpl_rows
            ]
            _put_json("data/platform_agent_templates.json", tpl_records)
            counts["platform_agent_templates"] = len(tpl_records)

        # 8. platform_agent_profiles
        if "platform_agent_profiles" in selected_scopes:
            prof_rows = session.exec(select(PlatformAgentProfile)).all()
            prof_records = [
                {
                    "id": pr.id,
                    "tenant_id": pr.tenant_id,
                    "name": pr.name,
                    "description": pr.description,
                    "agent_type": pr.agent_type,
                    "file_path": pr.file_path,
                    "record_count": int(pr.record_count),
                    "records_json": pr.records_json,
                    "created_at": pr.created_at,
                    "updated_at": pr.updated_at,
                }
                for pr in prof_rows
            ]
            _put_json("data/platform_agent_profiles.json", prof_records)
            counts["platform_agent_profiles"] = len(prof_records)

        # 9. platform_agent_configs
        if "platform_agent_configs" in selected_scopes:
            ac_rows = session.exec(select(PlatformAgentConfig)).all()
            ac_records = [
                {
                    "id": ac.id,
                    "tenant_id": ac.tenant_id,
                    "name": ac.name,
                    "description": ac.description,
                    "config_json": ac.config_json,
                    "created_at": ac.created_at,
                    "updated_at": ac.updated_at,
                }
                for ac in ac_rows
            ]
            _put_json("data/platform_agent_configs.json", ac_records)
            counts["platform_agent_configs"] = len(ac_records)

        # 10. platform_workflows_surveys
        if "platform_workflows_surveys" in selected_scopes:
            wf_rows = session.exec(select(PlatformWorkflowConfig)).all()
            sv_rows = session.exec(select(PlatformSurvey)).all()
            wf_records = [
                {
                    "id": w.id,
                    "tenant_id": w.tenant_id,
                    "name": w.name,
                    "description": w.description,
                    "config_json": w.config_json,
                    "created_at": w.created_at,
                    "updated_at": w.updated_at,
                }
                for w in wf_rows
            ]
            sv_records = [
                {
                    "id": s.id,
                    "tenant_id": s.tenant_id,
                    "name": s.name,
                    "data_json": s.data_json,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in sv_rows
            ]
            _put_json(
                "data/platform_workflows_surveys.json",
                {"workflows": wf_records, "surveys": sv_records},
            )
            counts["platform_workflows_surveys"] = len(wf_records) + len(sv_records)

    # 11. workspace_skills_and_params
    if "workspace_skills_and_params" in selected_scopes:
        prefill_file = resolve_under_root(workspace_root, ".agentsociety", "prefill_params.json")
        has_prefill = False
        if prefill_file.is_file():
            files_map["files/prefill_params.json"] = prefill_file.read_bytes()
            has_prefill = True

        skill_dirs = _list_custom_skill_dirs(workspace_root)
        skill_names: list[str] = []
        for sdir in skill_dirs:
            skill_names.append(sdir.name)
            for item in sorted(sdir.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(sdir)
                if any(part == "__pycache__" or part.startswith(".") for part in rel.parts):
                    continue
                if item.suffix == ".pyc":
                    continue
                arc = f"files/custom_skills/{sdir.name}/{rel.as_posix()}"
                files_map[arc] = item.read_bytes()

        files_map["data/workspace_skills_meta.json"] = json.dumps(
            {"skill_names": skill_names, "has_prefill_params": has_prefill},
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        counts["workspace_skills_and_params"] = len(skill_names) + (1 if has_prefill else 0)

    # Encrypt or attach secrets
    if raw_local_snapshot and raw_secrets:
        files_map["raw_secrets.json"] = json.dumps(
            raw_secrets, ensure_ascii=False, indent=2
        ).encode("utf-8")
    elif include_secrets and secrets_plain:
        encrypted_bundle = encrypt_secrets_bundle(secrets_plain, passphrase)
        files_map["secrets.enc.json"] = json.dumps(
            encrypted_bundle, ensure_ascii=False, indent=2
        ).encode("utf-8")

    file_checksums = {name: _sha256_bytes(blob) for name, blob in sorted(files_map.items())}
    manifest: dict[str, Any] = {
        "format": BACKUP_FORMAT,
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": _utcnow_iso(),
        "scopes": selected_scopes,
        "project_slugs": sorted({p.slug for p in target_projects}),
        "includes_secrets": bool(include_secrets and bool(secrets_plain)) or bool(
            raw_local_snapshot and bool(raw_secrets)
        ),
        "secrets_count": len(raw_secrets) if raw_local_snapshot else len(secrets_plain),
        "is_local_snapshot": bool(raw_local_snapshot),
        "notes": (notes or "").strip(),
        "counts": counts,
        "warnings": warnings,
        "file_checksums": file_checksums,
    }

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        for arcname, blob in sorted(files_map.items()):
            zf.writestr(arcname, blob)

    return buf.getvalue(), manifest


@dataclass
class ParsedBackupPackage:
    manifest: dict[str, Any]
    files: dict[str, bytes]
    package_sha256: str


def _validate_zip_member_name(name: str) -> str:
    if not name or "\0" in name or name.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail=f"Đường dẫn không hợp lệ trong gói ZIP: {name}")
    norm = name.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if not parts or any(p in {".", ".."} for p in parts):
        raise HTTPException(
            status_code=400,
            detail=f"Phát hiện đường dẫn nguy hiểm (Zip-Slip) trong gói ZIP: {name}",
        )
    return "/".join(parts)


def parse_and_validate_backup_zip(zip_bytes: bytes) -> ParsedBackupPackage:
    """Safely inspect, checksum-verify, and extract a backup ZIP in memory."""
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Tệp sao lưu trống.")
    if len(zip_bytes) > MAX_BACKUP_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Tệp sao lưu vượt quá giới hạn tối đa {MAX_BACKUP_ZIP_BYTES // (1024 * 1024)} MB.",
        )

    try:
        zf_ctx = zipfile.ZipFile(BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Tệp tải lên không phải định dạng ZIP hợp lệ.") from exc

    files: dict[str, bytes] = {}
    with zf_ctx as zf:
        infos = zf.infolist()
        if len(infos) > MAX_BACKUP_ENTRIES:
            raise HTTPException(
                status_code=413,
                detail=f"Gói sao lưu chứa quá nhiều tệp (>{MAX_BACKUP_ENTRIES}).",
            )
        total_uncompressed = 0
        for info in infos:
            if info.is_dir():
                continue
            safe_name = _validate_zip_member_name(info.filename)
            total_uncompressed += max(0, info.file_size)
            if total_uncompressed > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Tổng dung lượng giải nén vượt quá giới hạn an toàn 256 MB.",
                )
            with zf.open(info, "r") as handle:
                content = handle.read()
                total_uncompressed += max(0, len(content) - max(0, info.file_size))
                if total_uncompressed > MAX_BACKUP_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Tổng dung lượng giải nén vượt quá giới hạn an toàn 256 MB.",
                    )
                files[safe_name] = content

    if "manifest.json" not in files:
        raise HTTPException(status_code=400, detail="Gói sao lưu thiếu tệp manifest.json.")

    try:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="manifest.json không đúng định dạng JSON UTF-8.") from exc

    if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
        raise HTTPException(
            status_code=400,
            detail="Tệp không đúng định dạng gói sao lưu cấu hình AgentSociety.",
        )

    checksums = manifest.get("file_checksums")
    if not isinstance(checksums, dict):
        raise HTTPException(status_code=400, detail="manifest.json thiếu bảng kiểm tra SHA-256.")

    for fname, expected_hash in checksums.items():
        if fname not in files:
            raise HTTPException(
                status_code=400,
                detail=f"Gói sao lưu bị thiếu tệp đã khai báo: {fname}",
            )
        actual_hash = _sha256_bytes(files[fname])
        if actual_hash != str(expected_hash):
            raise HTTPException(
                status_code=400,
                detail=f"Sai lệch mã kiểm tra toàn vẹn SHA-256 tại tệp: {fname}",
            )

    return ParsedBackupPackage(
        manifest=manifest,
        files=files,
        package_sha256=_sha256_bytes(zip_bytes),
    )


def _read_pkg_json(pkg: ParsedBackupPackage, arcname: str, fallback: Any) -> Any:
    raw = pkg.files.get(arcname)
    if raw is None:
        return fallback
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return fallback


def _resolve_restore_scopes(pkg: ParsedBackupPackage, requested_scopes: list[str] | None) -> list[str]:
    pkg_scopes = validate_selected_scopes(list(pkg.manifest.get("scopes") or []))
    if not requested_scopes:
        return pkg_scopes
    req = validate_selected_scopes(requested_scopes)
    effective = [s for s in req if s in set(pkg_scopes)]
    if not effective:
        raise HTTPException(
            status_code=400,
            detail="Không có phạm vi nào được chọn khớp với dữ liệu có trong gói sao lưu.",
        )
    return effective


def _resolve_secrets_for_restore(
    pkg: ParsedBackupPackage,
    *,
    restore_secrets: bool,
    passphrase: str,
    use_raw_local_secrets: bool = False,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return (plaintext_secrets_map, raw_encrypted_secrets_map, warnings)."""
    warnings: list[str] = []
    if use_raw_local_secrets and "raw_secrets.json" in pkg.files:
        raw_map = _read_pkg_json(pkg, "raw_secrets.json", {})
        if isinstance(raw_map, dict):
            return {}, {str(k): str(v) for k, v in raw_map.items()}, warnings

    if not restore_secrets:
        if "secrets.enc.json" in pkg.files:
            warnings.append(
                "Gói sao lưu có chứa bí mật mã hóa nhưng tùy chọn khôi phục bí mật đang tắt; giữ nguyên khóa/mật khẩu hiện có trên môi trường đích."
            )
        return {}, {}, warnings

    if "secrets.enc.json" not in pkg.files:
        warnings.append(
            "Gói sao lưu không mang theo bí mật; hệ thống sẽ giữ nguyên khóa/mật khẩu hiện có trên môi trường đích."
        )
        return {}, {}, warnings

    bundle = _read_pkg_json(pkg, "secrets.enc.json", {})
    plain_map = decrypt_secrets_bundle(bundle, passphrase)
    return plain_map, {}, warnings


def preview_restore(
    workspace_root: Path,
    *,
    zip_bytes: bytes,
    selected_scopes: list[str] | None = None,
    mode: RestoreMode = "MERGE_UPSERT",
    restore_secrets: bool = True,
    passphrase: str = "",
    project_slugs: list[str] | None = None,
) -> dict[str, Any]:
    """Compute a non-mutating Dry-Run diff preview before executing Restore."""
    pkg = parse_and_validate_backup_zip(zip_bytes)
    effective_scopes = _resolve_restore_scopes(pkg, selected_scopes)
    plain_secrets, _, sec_warnings = _resolve_secrets_for_restore(
        pkg,
        restore_secrets=restore_secrets,
        passphrase=passphrase,
        use_raw_local_secrets=False,
    )

    engine = _ensure_db_seeded(workspace_root)
    warnings = list(pkg.manifest.get("warnings") or []) + sec_warnings
    blocking_errors: list[str] = []
    slug_filter = {s.strip() for s in project_slugs if s.strip()} if project_slugs else None

    scope_diffs: list[dict[str, Any]] = []

    with Session(engine) as session:
        if set(effective_scopes) & _URBAN_SIM_SCOPES:
            active_runs = _has_active_urban_sim_runs(session)
            if active_runs:
                blocking_errors.append(
                    f"Đang có phiên mô phỏng UrbanSim chạy ({', '.join(active_runs)}). Hãy tạm dừng trước khi khôi phục."
                )

        existing_llms = session.exec(select(PlatformLLMConfig)).all()
        existing_projs = session.exec(select(UrbanSimProject)).all()
        existing_zones = session.exec(select(UrbanSimZone)).all()
        existing_personas = session.exec(select(UrbanSimPersona)).all()
        existing_atlas = session.exec(select(UrbanSimAtlasConfig)).all()
        existing_maps = session.exec(select(PlatformMapConfig)).all()
        existing_tpls = session.exec(select(PlatformAgentTemplate)).all()
        existing_profiles = session.exec(select(PlatformAgentProfile)).all()
        existing_agent_cfgs = session.exec(select(PlatformAgentConfig)).all()
        existing_wfs = session.exec(select(PlatformWorkflowConfig)).all()
        existing_surveys = session.exec(select(PlatformSurvey)).all()

        llm_by_id = {x.id: x for x in existing_llms}
        llm_by_name = {(x.tenant_id, x.name): x for x in existing_llms}
        proj_by_slug = {p.slug: p for p in existing_projs}
        proj_by_id = {p.id: p for p in existing_projs}

        # Build simulated target project slug -> target id mapping
        incoming_projects: list[dict[str, Any]] = _read_pkg_json(
            pkg, "data/urban_sim_projects.json", []
        )
        if slug_filter is not None:
            incoming_projects = [p for p in incoming_projects if p.get("slug") in slug_filter]

        target_proj_id_by_slug: dict[str, str] = {p.slug: p.id for p in existing_projs}
        for ip in incoming_projects:
            slug = str(ip.get("slug") or "")
            if slug and slug not in target_proj_id_by_slug:
                target_proj_id_by_slug[slug] = str(ip.get("id") or "")

        def _make_diff(scope_key: str, create_items: list[str], update_items: list[str], delete_items: list[str], unchanged_count: int = 0) -> dict[str, Any]:
            meta = next(m for m in BACKUP_SCOPE_CATALOG if m["key"] == scope_key)
            return {
                "scope": scope_key,
                "label_vi": meta["label_vi"],
                "create_count": len(create_items),
                "update_count": len(update_items),
                "delete_count": len(delete_items),
                "unchanged_count": unchanged_count,
                "samples": {
                    "create": create_items[:20],
                    "update": update_items[:20],
                    "delete": delete_items[:20],
                },
            }

        if "llm_configs" in effective_scopes:
            inc = _read_pkg_json(pkg, "data/llm_configs.json", [])
            creates, updates, deletes = [], [], []
            matched_ids: set[str] = set()
            for r in inc:
                rid = str(r.get("id") or "")
                key_tn = (str(r.get("tenant_id") or "default"), str(r.get("name") or ""))
                match = llm_by_id.get(rid) or llm_by_name.get(key_tn)
                if match and mode == "MERGE_UPSERT":
                    matched_ids.add(match.id)
                    updates.append(str(r.get("name") or rid))
                else:
                    creates.append(str(r.get("name") or rid))
            if mode == "REPLACE_SCOPE":
                deletes = [x.name for x in existing_llms]
            scope_diffs.append(_make_diff("llm_configs", creates, updates, deletes))

        if "urban_sim_projects" in effective_scopes:
            creates, updates, deletes = [], [], []
            runs_proj_ids = {r.project_id for r in session.exec(select(UrbanSimRun)).all()}
            for p in incoming_projects:
                slug = str(p.get("slug") or "")
                if slug in proj_by_slug and mode == "MERGE_UPSERT":
                    updates.append(f"{p.get('name')} ({slug})")
                elif slug in proj_by_slug and mode == "REPLACE_SCOPE" and proj_by_slug[slug].id in runs_proj_ids:
                    updates.append(f"{p.get('name')} ({slug}) [giữ lịch sử run]")
                else:
                    creates.append(f"{p.get('name')} ({slug})")
            if mode == "REPLACE_SCOPE":
                for ep in existing_projs:
                    if ep.id in runs_proj_ids:
                        warnings.append(
                            f"Dự án '{ep.name}' ({ep.slug}) đã có lịch sử Run nên ở chế độ REPLACE_SCOPE sẽ được cập nhật tại chỗ thay vì xóa bản ghi dự án."
                        )
                    else:
                        deletes.append(f"{ep.name} ({ep.slug})")
            scope_diffs.append(_make_diff("urban_sim_projects", creates, updates, deletes))

        if "urban_sim_zones" in effective_scopes:
            z_payload = _read_pkg_json(pkg, "data/urban_sim_zones.json", {})
            inc_zones = z_payload.get("zones", []) if isinstance(z_payload, dict) else []
            inc_cps = z_payload.get("checkpoints", []) if isinstance(z_payload, dict) else []
            if slug_filter is not None:
                inc_zones = [z for z in inc_zones if z.get("project_slug") in slug_filter]
                inc_cps = [c for c in inc_cps if c.get("project_slug") in slug_filter]
            existing_zone_keys = {
                (z.project_id, z.zone_key): z for z in existing_zones
            }
            existing_cp_rows = session.exec(select(UrbanSimCheckpoint)).all()
            existing_cp_keys = {
                (c.project_id, c.checkpoint_key): c for c in existing_cp_rows
            }
            creates, updates, deletes = [], [], []
            for z in inc_zones:
                pslug = str(z.get("project_slug") or "")
                tpid = target_proj_id_by_slug.get(pslug) or str(z.get("project_id") or "")
                if tpid not in target_proj_id_by_slug.values() and tpid not in proj_by_id:
                    warnings.append(
                        f"Zone '{z.get('zone_key')}' thuộc dự án '{pslug}' chưa tồn tại trên môi trường đích (hãy chọn thêm phạm vi Dự án UrbanSim)."
                    )
                    continue
                if mode == "MERGE_UPSERT" and (tpid, str(z.get("zone_key") or "")) in existing_zone_keys:
                    updates.append(f"{pslug}:{z.get('zone_key')}")
                else:
                    creates.append(f"{pslug}:{z.get('zone_key')}")
            for cp in inc_cps:
                pslug = str(cp.get("project_slug") or "")
                tpid = target_proj_id_by_slug.get(pslug) or str(cp.get("project_id") or "")
                if tpid not in target_proj_id_by_slug.values() and tpid not in proj_by_id:
                    continue
                ckey = str(cp.get("checkpoint_key") or "")
                if mode == "MERGE_UPSERT" and (tpid, ckey) in existing_cp_keys:
                    updates.append(f"[Chốt] {pslug}:{ckey}")
                else:
                    creates.append(f"[Chốt] {pslug}:{ckey}")
            if mode == "REPLACE_SCOPE":
                deletes = [f"{z.project_id}:{z.zone_key}" for z in existing_zones] + [
                    f"[Chốt] {c.project_id}:{c.checkpoint_key}" for c in existing_cp_rows
                ]
            scope_diffs.append(_make_diff("urban_sim_zones", creates, updates, deletes))

        if "urban_sim_personas" in effective_scopes:
            inc_pers = _read_pkg_json(pkg, "data/urban_sim_personas.json", [])
            if slug_filter is not None:
                inc_pers = [p for p in inc_pers if p.get("project_slug") in slug_filter]
            existing_per_keys = {
                (p.project_id, int(p.agent_id)): p for p in existing_personas
            }
            creates, updates, deletes = [], [], []
            for per in inc_pers:
                pslug = str(per.get("project_slug") or "")
                tpid = target_proj_id_by_slug.get(pslug) or str(per.get("project_id") or "")
                if tpid not in target_proj_id_by_slug.values() and tpid not in proj_by_id:
                    warnings.append(
                        f"Persona '{per.get('full_name')}' thuộc dự án '{pslug}' chưa tồn tại trên môi trường đích."
                    )
                    continue
                aid = int(per.get("agent_id") or 0)
                if mode == "MERGE_UPSERT" and (tpid, aid) in existing_per_keys:
                    updates.append(f"{pslug}#{aid} {per.get('full_name')}")
                else:
                    creates.append(f"{pslug}#{aid} {per.get('full_name')}")
            if mode == "REPLACE_SCOPE":
                deletes = [f"{p.project_id}#{p.agent_id} {p.full_name}" for p in existing_personas]
            scope_diffs.append(_make_diff("urban_sim_personas", creates, updates, deletes))

        if "urban_sim_atlas_configs" in effective_scopes:
            inc_atlas = _read_pkg_json(pkg, "data/urban_sim_atlas_configs.json", [])
            if slug_filter is not None:
                inc_atlas = [a for a in inc_atlas if a.get("project_slug") in slug_filter]
            existing_atlas_pids = {a.project_id for a in existing_atlas}
            creates, updates, deletes = [], [], []
            for a in inc_atlas:
                pslug = str(a.get("project_slug") or "")
                tpid = target_proj_id_by_slug.get(pslug) or str(a.get("project_id") or "")
                if tpid not in target_proj_id_by_slug.values() and tpid not in proj_by_id:
                    warnings.append(
                        f"Cấu hình Atlas của dự án '{pslug}' không tìm thấy dự án đích."
                    )
                    continue
                if mode == "MERGE_UPSERT" and tpid in existing_atlas_pids:
                    updates.append(f"Atlas ({pslug})")
                else:
                    creates.append(f"Atlas ({pslug})")
            if mode == "REPLACE_SCOPE":
                deletes = [f"Atlas ({a.project_id})" for a in existing_atlas]
            scope_diffs.append(_make_diff("urban_sim_atlas_configs", creates, updates, deletes))

        if "platform_maps" in effective_scopes:
            inc_maps = _read_pkg_json(pkg, "data/platform_maps.json", [])
            map_by_id = {m.id: m for m in existing_maps}
            map_by_name = {(m.tenant_id, m.name): m for m in existing_maps}
            creates, updates, deletes = [], [], []
            for m in inc_maps:
                mid = str(m.get("id") or "")
                mkey = (str(m.get("tenant_id") or "default"), str(m.get("name") or ""))
                if mode == "MERGE_UPSERT" and (mid in map_by_id or mkey in map_by_name):
                    updates.append(str(m.get("name") or mid))
                else:
                    creates.append(str(m.get("name") or mid))
            if mode == "REPLACE_SCOPE":
                deletes = [m.name for m in existing_maps]
            scope_diffs.append(_make_diff("platform_maps", creates, updates, deletes))

        if "platform_agent_templates" in effective_scopes:
            inc_tpls = _read_pkg_json(pkg, "data/platform_agent_templates.json", [])
            tpl_by_id = {t.id: t for t in existing_tpls}
            tpl_by_name = {(t.tenant_id, t.name): t for t in existing_tpls}
            creates, updates, deletes = [], [], []
            for t in inc_tpls:
                tid = str(t.get("id") or "")
                tkey = (str(t.get("tenant_id") or "default"), str(t.get("name") or ""))
                if mode == "MERGE_UPSERT" and (tid in tpl_by_id or tkey in tpl_by_name):
                    updates.append(str(t.get("name") or tid))
                else:
                    creates.append(str(t.get("name") or tid))
            if mode == "REPLACE_SCOPE":
                deletes = [t.name for t in existing_tpls]
            scope_diffs.append(_make_diff("platform_agent_templates", creates, updates, deletes))

        if "platform_agent_profiles" in effective_scopes:
            inc_profs = _read_pkg_json(pkg, "data/platform_agent_profiles.json", [])
            p_by_id = {p.id: p for p in existing_profiles}
            p_by_name = {(p.tenant_id, p.name): p for p in existing_profiles}
            creates, updates, deletes = [], [], []
            for pr in inc_profs:
                pid = str(pr.get("id") or "")
                pkey = (str(pr.get("tenant_id") or "default"), str(pr.get("name") or ""))
                if mode == "MERGE_UPSERT" and (pid in p_by_id or pkey in p_by_name):
                    updates.append(str(pr.get("name") or pid))
                else:
                    creates.append(str(pr.get("name") or pid))
            if mode == "REPLACE_SCOPE":
                deletes = [p.name for p in existing_profiles]
            scope_diffs.append(_make_diff("platform_agent_profiles", creates, updates, deletes))

        if "platform_agent_configs" in effective_scopes:
            inc_ac = _read_pkg_json(pkg, "data/platform_agent_configs.json", [])
            ac_by_id = {a.id: a for a in existing_agent_cfgs}
            ac_by_name = {(a.tenant_id, a.name): a for a in existing_agent_cfgs}
            creates, updates, deletes = [], [], []
            for ac in inc_ac:
                acid = str(ac.get("id") or "")
                ackey = (str(ac.get("tenant_id") or "default"), str(ac.get("name") or ""))
                if mode == "MERGE_UPSERT" and (acid in ac_by_id or ackey in ac_by_name):
                    updates.append(str(ac.get("name") or acid))
                else:
                    creates.append(str(ac.get("name") or acid))
            if mode == "REPLACE_SCOPE":
                deletes = [a.name for a in existing_agent_cfgs]
            scope_diffs.append(_make_diff("platform_agent_configs", creates, updates, deletes))

        if "platform_workflows_surveys" in effective_scopes:
            ws_payload = _read_pkg_json(pkg, "data/platform_workflows_surveys.json", {})
            inc_wfs = ws_payload.get("workflows", []) if isinstance(ws_payload, dict) else []
            inc_svs = ws_payload.get("surveys", []) if isinstance(ws_payload, dict) else []
            wf_by_id = {w.id: w for w in existing_wfs}
            wf_by_name = {(w.tenant_id, w.name): w for w in existing_wfs}
            sv_by_id = {s.id: s for s in existing_surveys}
            sv_by_name = {(s.tenant_id, s.name): s for s in existing_surveys}
            creates, updates, deletes = [], [], []
            for w in inc_wfs:
                wid = str(w.get("id") or "")
                wkey = (str(w.get("tenant_id") or "default"), str(w.get("name") or ""))
                if mode == "MERGE_UPSERT" and (wid in wf_by_id or wkey in wf_by_name):
                    updates.append(f"[Workflow] {w.get('name')}")
                else:
                    creates.append(f"[Workflow] {w.get('name')}")
            for s in inc_svs:
                sid = str(s.get("id") or "")
                skey = (str(s.get("tenant_id") or "default"), str(s.get("name") or ""))
                if mode == "MERGE_UPSERT" and (sid in sv_by_id or skey in sv_by_name):
                    updates.append(f"[Survey] {s.get('name')}")
                else:
                    creates.append(f"[Survey] {s.get('name')}")
            if mode == "REPLACE_SCOPE":
                deletes = [f"[Workflow] {w.name}" for w in existing_wfs] + [
                    f"[Survey] {s.name}" for s in existing_surveys
                ]
            scope_diffs.append(
                _make_diff("platform_workflows_surveys", creates, updates, deletes)
            )

        if "workspace_skills_and_params" in effective_scopes:
            meta = _read_pkg_json(pkg, "data/workspace_skills_meta.json", {})
            inc_skills = list(meta.get("skill_names") or []) if isinstance(meta, dict) else []
            has_prefill = "files/prefill_params.json" in pkg.files
            existing_skill_names = {d.name for d in _list_custom_skill_dirs(workspace_root)}
            prefill_exists = resolve_under_root(
                workspace_root, ".agentsociety", "prefill_params.json"
            ).is_file()
            creates, updates, deletes = [], [], []
            for sname in inc_skills:
                if mode == "MERGE_UPSERT" and sname in existing_skill_names:
                    updates.append(f"[Skill] {sname}")
                else:
                    creates.append(f"[Skill] {sname}")
            if has_prefill:
                if mode == "MERGE_UPSERT" and prefill_exists:
                    updates.append("prefill_params.json")
                else:
                    creates.append("prefill_params.json")
            if mode == "REPLACE_SCOPE":
                deletes = [f"[Skill] {n}" for n in sorted(existing_skill_names)]
                if prefill_exists:
                    deletes.append("prefill_params.json")
            scope_diffs.append(
                _make_diff("workspace_skills_and_params", creates, updates, deletes)
            )

    totals = {
        "create": sum(d["create_count"] for d in scope_diffs),
        "update": sum(d["update_count"] for d in scope_diffs),
        "delete": sum(d["delete_count"] for d in scope_diffs),
        "unchanged": sum(d["unchanged_count"] for d in scope_diffs),
        "secrets_to_restore": len(plain_secrets),
    }

    return {
        "can_apply": len(blocking_errors) == 0,
        "blocking_errors": blocking_errors,
        "mode": mode,
        "effective_scopes": effective_scopes,
        "manifest": {
            "format": pkg.manifest.get("format"),
            "schema_version": pkg.manifest.get("schema_version"),
            "created_at": pkg.manifest.get("created_at"),
            "scopes": pkg.manifest.get("scopes"),
            "project_slugs": pkg.manifest.get("project_slugs"),
            "includes_secrets": bool(pkg.manifest.get("includes_secrets")),
            "secrets_count": int(pkg.manifest.get("secrets_count") or 0),
            "notes": pkg.manifest.get("notes") or "",
            "package_sha256": pkg.package_sha256,
        },
        "scope_diffs": scope_diffs,
        "totals": totals,
        "warnings": list(dict.fromkeys(warnings)),
    }


def create_local_snapshot(
    workspace_root: Path,
    *,
    trigger: str = "PRE_RESTORE",
    note: str = "",
) -> dict[str, Any]:
    """Capture full local state (including local raw encrypted secrets) into .agentsociety/backups/."""
    zip_bytes, manifest = export_backup_zip(
        workspace_root,
        scopes=list(VALID_BACKUP_SCOPES),
        include_secrets=False,
        raw_local_snapshot=True,
        notes=note or f"Auto snapshot ({trigger})",
    )
    snap_id = f"snap_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    bdir = _backups_dir(workspace_root)
    snap_path = resolve_under_root(bdir, f"{snap_id}.zip")
    snap_path.write_bytes(zip_bytes)

    record = {
        "snapshot_id": snap_id,
        "file_name": snap_path.name,
        "trigger": trigger,
        "note": note or manifest.get("notes") or "",
        "created_at": manifest["created_at"],
        "size_bytes": len(zip_bytes),
        "sha256": _sha256_bytes(zip_bytes),
        "scopes": manifest["scopes"],
        "counts": manifest["counts"],
    }
    _append_history(workspace_root, record)
    return record


def list_backup_snapshots(workspace_root: Path) -> list[dict[str, Any]]:
    bdir = _backups_dir(workspace_root)
    history = _load_history(workspace_root)
    out: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for item in history:
        sid = str(item.get("snapshot_id") or "")
        fname = str(item.get("file_name") or f"{sid}.zip")
        try:
            fpath = resolve_under_root(bdir, fname)
            exists = fpath.is_file()
        except HTTPException:
            exists = False
        seen_files.add(fname)
        out.append({**item, "file_exists": exists})

    for zpath in sorted(bdir.glob("snap_*.zip"), reverse=True):
        if zpath.name in seen_files:
            continue
        out.append(
            {
                "snapshot_id": zpath.stem,
                "file_name": zpath.name,
                "trigger": "SNAPSHOT",
                "note": "",
                "created_at": datetime.fromtimestamp(zpath.stat().st_mtime, UTC).isoformat(),
                "size_bytes": zpath.stat().st_size,
                "sha256": _sha256_bytes(zpath.read_bytes()),
                "scopes": list(VALID_BACKUP_SCOPES),
                "counts": {},
                "file_exists": True,
            }
        )
    return out


def get_snapshot_file_path(workspace_root: Path, snapshot_id: str) -> Path:
    safe_id = require_safe_segment(snapshot_id.strip(), field="snapshot_id")
    bdir = _backups_dir(workspace_root)
    fpath = resolve_under_root(bdir, f"{safe_id}.zip")
    if not fpath.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bản chụp '{snapshot_id}'.")
    return fpath


def delete_backup_snapshot(workspace_root: Path, snapshot_id: str) -> dict[str, Any]:
    fpath = get_snapshot_file_path(workspace_root, snapshot_id)
    fpath.unlink(missing_ok=True)
    items = [i for i in _load_history(workspace_root) if i.get("snapshot_id") != snapshot_id]
    _history_file(workspace_root).write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"deleted": snapshot_id}


def execute_restore(
    workspace_root: Path,
    *,
    zip_bytes: bytes,
    selected_scopes: list[str] | None = None,
    mode: RestoreMode = "MERGE_UPSERT",
    restore_secrets: bool = True,
    passphrase: str = "",
    project_slugs: list[str] | None = None,
    create_pre_restore_snapshot: bool = True,
    use_raw_local_secrets: bool = False,
    trigger_label: str = "RESTORE",
) -> dict[str, Any]:
    """Atomically apply selected scopes from a backup package onto the target environment."""
    pkg = parse_and_validate_backup_zip(zip_bytes)
    effective_scopes = _resolve_restore_scopes(pkg, selected_scopes)
    plain_secrets, raw_secrets, sec_warnings = _resolve_secrets_for_restore(
        pkg,
        restore_secrets=restore_secrets,
        passphrase=passphrase,
        use_raw_local_secrets=use_raw_local_secrets,
    )

    engine = _ensure_db_seeded(workspace_root)
    with Session(engine) as session:
        if set(effective_scopes) & _URBAN_SIM_SCOPES:
            active_runs = _has_active_urban_sim_runs(session)
            if active_runs:
                raise HTTPException(
                    status_code=409,
                    detail=f"Không thể khôi phục khi đang có phiên chạy UrbanSim hoạt động ({', '.join(active_runs)}).",
                )

    snapshot_record: dict[str, Any] | None = None
    if create_pre_restore_snapshot:
        snapshot_record = create_local_snapshot(
            workspace_root,
            trigger=f"PRE_{trigger_label}",
            note=f"Tự động chụp trước {trigger_label} ({mode}, {len(effective_scopes)} phạm vi)",
        )

    slug_filter = {s.strip() for s in project_slugs if s.strip()} if project_slugs else None
    warnings = list(pkg.manifest.get("warnings") or []) + sec_warnings
    applied_counts: dict[str, dict[str, int]] = {
        s: {"created": 0, "updated": 0, "deleted": 0} for s in effective_scopes
    }

    def _resolve_secret_enc(skey: str, fallback_existing_enc: str | None) -> str | None:
        if use_raw_local_secrets and skey and skey in raw_secrets:
            return raw_secrets[skey]
        if restore_secrets and skey and skey in plain_secrets:
            return encrypt_secret(plain_secrets[skey], workspace_root)
        if mode == "MERGE_UPSERT" and fallback_existing_enc:
            return fallback_existing_enc
        return None

    with Session(engine) as session:
        try:
            # --- REPLACE_SCOPE deletions in reverse FK order ---
            if mode == "REPLACE_SCOPE":
                if "urban_sim_atlas_configs" in effective_scopes:
                    for row in session.exec(select(UrbanSimAtlasConfig)).all():
                        session.delete(row)
                        applied_counts["urban_sim_atlas_configs"]["deleted"] += 1
                if "urban_sim_personas" in effective_scopes:
                    for row in session.exec(select(UrbanSimPersona)).all():
                        session.delete(row)
                        applied_counts["urban_sim_personas"]["deleted"] += 1
                if "urban_sim_zones" in effective_scopes:
                    # Clear UrbanSimCheckpoint before UrbanSimZone to preserve FK integrity
                    for row in session.exec(select(UrbanSimCheckpoint)).all():
                        session.delete(row)
                    for row in session.exec(select(UrbanSimZone)).all():
                        session.delete(row)
                        applied_counts["urban_sim_zones"]["deleted"] += 1
                if "urban_sim_projects" in effective_scopes:
                    runs_proj_ids = {r.project_id for r in session.exec(select(UrbanSimRun)).all()}
                    for row in session.exec(select(UrbanSimProject)).all():
                        if row.id in runs_proj_ids:
                            warnings.append(
                                f"Giữ lại bản ghi dự án '{row.name}' ({row.slug}) do đang có lịch sử Run; sẽ cập nhật cấu hình tại chỗ."
                            )
                        else:
                            # Remove child rows in reverse FK order BEFORE deleting UrbanSimProject
                            for c_cp in session.exec(
                                select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == row.id)
                            ).all():
                                session.delete(c_cp)
                            for c_atlas in session.exec(
                                select(UrbanSimAtlasConfig).where(UrbanSimAtlasConfig.project_id == row.id)
                            ).all():
                                session.delete(c_atlas)
                            for c_per in session.exec(
                                select(UrbanSimPersona).where(UrbanSimPersona.project_id == row.id)
                            ).all():
                                session.delete(c_per)
                            for c_zone in session.exec(
                                select(UrbanSimZone).where(UrbanSimZone.project_id == row.id)
                            ).all():
                                session.delete(c_zone)
                            session.flush()
                            session.delete(row)
                            applied_counts["urban_sim_projects"]["deleted"] += 1
                if "llm_configs" in effective_scopes:
                    for proj in session.exec(select(UrbanSimProject)).all():
                        if proj.llm_config_id is not None:
                            proj.llm_config_id = None
                            session.add(proj)
                    for row in session.exec(select(PlatformLLMConfig)).all():
                        session.delete(row)
                        applied_counts["llm_configs"]["deleted"] += 1
                if "platform_maps" in effective_scopes:
                    for row in session.exec(select(PlatformMapConfig)).all():
                        session.delete(row)
                        applied_counts["platform_maps"]["deleted"] += 1
                if "platform_agent_configs" in effective_scopes:
                    for row in session.exec(select(PlatformAgentConfig)).all():
                        session.delete(row)
                        applied_counts["platform_agent_configs"]["deleted"] += 1
                if "platform_agent_profiles" in effective_scopes:
                    for row in session.exec(select(PlatformAgentProfile)).all():
                        session.delete(row)
                        applied_counts["platform_agent_profiles"]["deleted"] += 1
                if "platform_agent_templates" in effective_scopes:
                    for row in session.exec(select(PlatformAgentTemplate)).all():
                        session.delete(row)
                        applied_counts["platform_agent_templates"]["deleted"] += 1
                if "platform_workflows_surveys" in effective_scopes:
                    for row in session.exec(select(PlatformWorkflowConfig)).all():
                        session.delete(row)
                        applied_counts["platform_workflows_surveys"]["deleted"] += 1
                    for row in session.exec(select(PlatformSurvey)).all():
                        session.delete(row)
                        applied_counts["platform_workflows_surveys"]["deleted"] += 1
                session.flush()

            # Build ID/slug maps from current DB state after any REPLACE deletions
            llm_id_map: dict[str, str] = {}
            for existing_llm in session.exec(select(PlatformLLMConfig)).all():
                llm_id_map[existing_llm.id] = existing_llm.id

            # 1. llm_configs
            if "llm_configs" in effective_scopes:
                inc_llms: list[dict[str, Any]] = _read_pkg_json(pkg, "data/llm_configs.json", [])
                for item in inc_llms:
                    src_id = str(item.get("id") or "").strip()
                    tenant_id = str(item.get("tenant_id") or "default").strip()
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    existing = session.get(PlatformLLMConfig, src_id) if src_id else None
                    if existing is None:
                        existing = session.exec(
                            select(PlatformLLMConfig).where(
                                PlatformLLMConfig.tenant_id == tenant_id,
                                PlatformLLMConfig.name == name,
                            )
                        ).first()

                    prev_entries = (
                        _safe_json(existing.config_json, []) if existing is not None else []
                    )
                    new_entries: list[dict[str, Any]] = []
                    for idx, entry in enumerate(item.get("entries") or []):
                        if not isinstance(entry, dict):
                            continue
                        skey = str(entry.get("secret_ref_key") or _secret_key_llm(src_id, idx))
                        prev_enc = ""
                        if isinstance(prev_entries, list) and idx < len(prev_entries):
                            pe = prev_entries[idx]
                            if isinstance(pe, dict):
                                prev_enc = str(pe.get("api_key_enc") or "")
                        resolved_enc = _resolve_secret_enc(skey, prev_enc) or ""
                        clean = {
                            k: v
                            for k, v in entry.items()
                            if k not in {"has_secret", "secret_ref_key", "api_key_enc"}
                        }
                        clean["api_key_enc"] = resolved_enc
                        new_entries.append(clean)

                    serialized_entries = json.dumps(new_entries, ensure_ascii=False)
                    if existing is not None:
                        existing.name = name
                        existing.description = str(item.get("description") or "")
                        existing.config_json = serialized_entries
                        existing.updated_at = _utcnow_iso()
                        session.add(existing)
                        if src_id:
                            llm_id_map[src_id] = existing.id
                        applied_counts["llm_configs"]["updated"] += 1
                    else:
                        new_row = PlatformLLMConfig(
                            id=src_id or str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            name=name,
                            description=str(item.get("description") or ""),
                            config_json=serialized_entries,
                            created_at=str(item.get("created_at") or _utcnow_iso()),
                            updated_at=_utcnow_iso(),
                        )
                        session.add(new_row)
                        session.flush()
                        if src_id:
                            llm_id_map[src_id] = new_row.id
                        applied_counts["llm_configs"]["created"] += 1

            # 2. urban_sim_projects
            proj_slug_to_id: dict[str, str] = {
                p.slug: p.id for p in session.exec(select(UrbanSimProject)).all()
            }
            proj_id_map: dict[str, str] = {pid: pid for pid in proj_slug_to_id.values()}

            if "urban_sim_projects" in effective_scopes:
                inc_projs: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/urban_sim_projects.json", []
                )
                if slug_filter is not None:
                    inc_projs = [p for p in inc_projs if p.get("slug") in slug_filter]

                for ip in inc_projs:
                    slug = str(ip.get("slug") or "").strip()
                    src_id = str(ip.get("id") or "").strip()
                    if not slug:
                        continue
                    existing = session.exec(
                        select(UrbanSimProject).where(UrbanSimProject.slug == slug)
                    ).first()
                    if existing is None and src_id:
                        existing = session.get(UrbanSimProject, src_id)

                    src_llm_id = ip.get("llm_config_id")
                    mapped_llm_id = llm_id_map.get(str(src_llm_id)) if src_llm_id else None
                    if mapped_llm_id is None and existing is not None:
                        mapped_llm_id = existing.llm_config_id

                    if existing is not None:
                        existing.name = str(ip.get("name") or existing.name)
                        existing.description = str(ip.get("description") or "")
                        existing.default_portal_url = str(
                            ip.get("default_portal_url") or existing.default_portal_url
                        )
                        existing.router_type = str(ip.get("router_type") or existing.router_type)
                        existing.num_steps = int(ip.get("num_steps") or existing.num_steps)
                        existing.tick_seconds = int(ip.get("tick_seconds") or existing.tick_seconds)
                        existing.start_time_iso = str(
                            ip.get("start_time_iso") or existing.start_time_iso
                        )
                        existing.max_react_turns = int(
                            ip.get("max_react_turns") or existing.max_react_turns
                        )
                        existing.max_cost_usd_per_run = float(
                            ip.get("max_cost_usd_per_run") or existing.max_cost_usd_per_run
                        )
                        existing.pilot_mode = bool(ip.get("pilot_mode", existing.pilot_mode))
                        if "zone_map_image_rel" in ip and ip.get("zone_map_image_rel"):
                            existing.zone_map_image_rel = Path(str(ip["zone_map_image_rel"])).name
                        if "map_prompt" in ip:
                            existing.map_prompt = ip.get("map_prompt")
                        if ip.get("map_width") is not None:
                            existing.map_width = int(ip["map_width"])
                        if ip.get("map_height") is not None:
                            existing.map_height = int(ip["map_height"])
                        if ip.get("map_aspect_ratio") is not None:
                            existing.map_aspect_ratio = float(ip["map_aspect_ratio"])
                        if ip.get("map_image_version") is not None:
                            existing.map_image_version = int(ip["map_image_version"])
                        if "map_image_updated_at" in ip:
                            existing.map_image_updated_at = ip.get("map_image_updated_at")
                        existing.llm_config_id = mapped_llm_id
                        existing.enable_sociological_debrief = bool(
                            ip.get("enable_sociological_debrief", True)
                        )
                        existing.enable_competency_prepost_quiz = bool(
                            ip.get("enable_competency_prepost_quiz", False)
                        )
                        existing.competency_rubric_json = ip.get("competency_rubric_json")
                        existing.updated_at = _utcnow_iso()
                        session.add(existing)
                        proj_slug_to_id[slug] = existing.id
                        if src_id:
                            proj_id_map[src_id] = existing.id
                        applied_counts["urban_sim_projects"]["updated"] += 1
                    else:
                        new_proj = UrbanSimProject(
                            id=src_id or f"proj_{uuid.uuid4().hex[:12]}",
                            slug=slug,
                            name=str(ip.get("name") or slug),
                            description=str(ip.get("description") or ""),
                            default_portal_url=str(
                                ip.get("default_portal_url") or "https://mulberrylane.sandbox.demego.vn"
                            ),
                            router_type=str(ip.get("router_type") or "react"),
                            num_steps=int(ip.get("num_steps") or 8),
                            tick_seconds=int(ip.get("tick_seconds") or 900),
                            start_time_iso=str(
                                ip.get("start_time_iso") or "2026-06-15T08:00:00+07:00"
                            ),
                            max_react_turns=int(ip.get("max_react_turns") or 6),
                            max_cost_usd_per_run=float(ip.get("max_cost_usd_per_run") or 5.0),
                            pilot_mode=bool(ip.get("pilot_mode", True)),
                            zone_map_image_rel=(
                                Path(str(ip["zone_map_image_rel"])).name
                                if ip.get("zone_map_image_rel")
                                else None
                            ),
                            map_prompt=ip.get("map_prompt"),
                            map_width=int(ip["map_width"]) if ip.get("map_width") is not None else None,
                            map_height=int(ip["map_height"]) if ip.get("map_height") is not None else None,
                            map_aspect_ratio=(
                                float(ip["map_aspect_ratio"])
                                if ip.get("map_aspect_ratio") is not None
                                else None
                            ),
                            map_image_version=int(ip.get("map_image_version") or 0),
                            map_image_updated_at=ip.get("map_image_updated_at"),
                            llm_config_id=mapped_llm_id,
                            enable_sociological_debrief=bool(
                                ip.get("enable_sociological_debrief", True)
                            ),
                            enable_competency_prepost_quiz=bool(
                                ip.get("enable_competency_prepost_quiz", False)
                            ),
                            competency_rubric_json=ip.get("competency_rubric_json"),
                            created_at=str(ip.get("created_at") or _utcnow_iso()),
                            updated_at=_utcnow_iso(),
                        )
                        session.add(new_proj)
                        session.flush()
                        proj_slug_to_id[slug] = new_proj.id
                        if src_id:
                            proj_id_map[src_id] = new_proj.id
                        applied_counts["urban_sim_projects"]["created"] += 1

            def _resolve_target_project_id(pslug: str, raw_pid: str) -> str | None:
                if pslug and pslug in proj_slug_to_id:
                    return proj_slug_to_id[pslug]
                if raw_pid and raw_pid in proj_id_map:
                    return proj_id_map[raw_pid]
                if raw_pid and session.get(UrbanSimProject, raw_pid) is not None:
                    return raw_pid
                return None

            # 3. urban_sim_zones (+ polygon geometry & checkpoints)
            if "urban_sim_zones" in effective_scopes:
                z_payload = _read_pkg_json(pkg, "data/urban_sim_zones.json", {})
                inc_zones = z_payload.get("zones", []) if isinstance(z_payload, dict) else []
                inc_cps = z_payload.get("checkpoints", []) if isinstance(z_payload, dict) else []
                map_img_refs = (
                    z_payload.get("project_map_images", {})
                    if isinstance(z_payload, dict)
                    else {}
                )
                if slug_filter is not None:
                    inc_zones = [z for z in inc_zones if z.get("project_slug") in slug_filter]
                    inc_cps = [c for c in inc_cps if c.get("project_slug") in slug_filter]

                for iz in inc_zones:
                    pslug = str(iz.get("project_slug") or "")
                    tpid = _resolve_target_project_id(pslug, str(iz.get("project_id") or ""))
                    if not tpid:
                        warnings.append(
                            f"Bỏ qua Zone '{iz.get('zone_key')}' do không tìm thấy dự án '{pslug}' trên đích."
                        )
                        continue
                    zkey = str(iz.get("zone_key") or "").strip()
                    existing_z = session.exec(
                        select(UrbanSimZone).where(
                            UrbanSimZone.project_id == tpid,
                            UrbanSimZone.zone_key == zkey,
                        )
                    ).first()
                    cx = float(iz["center_x_pct"]) if iz.get("center_x_pct") is not None else None
                    cy = float(iz["center_y_pct"]) if iz.get("center_y_pct") is not None else None
                    poly_json = iz.get("polygon_points_json")
                    fcolor = iz.get("fill_color")
                    if existing_z is not None:
                        existing_z.name = str(iz.get("name") or existing_z.name)
                        existing_z.zone_type = str(iz.get("zone_type") or existing_z.zone_type)
                        existing_z.description = str(iz.get("description") or "")
                        existing_z.ambient_signals = str(iz.get("ambient_signals") or "")
                        existing_z.sort_order = int(iz.get("sort_order") or 0)
                        if "center_x_pct" in iz:
                            existing_z.center_x_pct = cx
                        if "center_y_pct" in iz:
                            existing_z.center_y_pct = cy
                        if "polygon_points_json" in iz:
                            existing_z.polygon_points_json = poly_json
                        if "fill_color" in iz:
                            existing_z.fill_color = fcolor
                        session.add(existing_z)
                        applied_counts["urban_sim_zones"]["updated"] += 1
                    else:
                        session.add(
                            UrbanSimZone(
                                id=f"zone_{uuid.uuid4().hex[:12]}",
                                project_id=tpid,
                                zone_key=zkey,
                                name=str(iz.get("name") or zkey),
                                zone_type=str(iz.get("zone_type") or "OFFICE"),
                                description=str(iz.get("description") or ""),
                                ambient_signals=str(iz.get("ambient_signals") or ""),
                                sort_order=int(iz.get("sort_order") or 0),
                                center_x_pct=cx,
                                center_y_pct=cy,
                                polygon_points_json=poly_json,
                                fill_color=fcolor,
                            )
                        )
                        applied_counts["urban_sim_zones"]["created"] += 1

                # Restore urban_sim_checkpoints (if present; legacy v1.0 zips cleanly skip)
                for icp in inc_cps:
                    pslug = str(icp.get("project_slug") or "")
                    tpid = _resolve_target_project_id(pslug, str(icp.get("project_id") or ""))
                    if not tpid:
                        continue
                    cpkey = str(icp.get("checkpoint_key") or "").strip()
                    if not cpkey:
                        continue
                    existing_cp = session.exec(
                        select(UrbanSimCheckpoint).where(
                            UrbanSimCheckpoint.project_id == tpid,
                            UrbanSimCheckpoint.checkpoint_key == cpkey,
                        )
                    ).first()
                    if existing_cp is not None:
                        existing_cp.name = str(icp.get("name") or cpkey)
                        existing_cp.x_pct = float(icp.get("x_pct") or 50.0)
                        existing_cp.y_pct = float(icp.get("y_pct") or 50.0)
                        existing_cp.icon_emoji = str(icp.get("icon_emoji") or "📍")
                        existing_cp.description_md = str(icp.get("description_md") or "")
                        existing_cp.zone_key = icp.get("zone_key")
                        existing_cp.category = str(icp.get("category") or "general")
                        existing_cp.sort_order = int(icp.get("sort_order") or 0)
                        existing_cp.updated_at = _utcnow_iso()
                        session.add(existing_cp)
                    else:
                        session.add(
                            UrbanSimCheckpoint(
                                id=f"cp_{uuid.uuid4().hex[:12]}",
                                project_id=tpid,
                                checkpoint_key=cpkey,
                                name=str(icp.get("name") or cpkey),
                                x_pct=float(icp.get("x_pct") or 50.0),
                                y_pct=float(icp.get("y_pct") or 50.0),
                                icon_emoji=str(icp.get("icon_emoji") or "📍"),
                                description_md=str(icp.get("description_md") or ""),
                                zone_key=icp.get("zone_key"),
                                category=str(icp.get("category") or "general"),
                                sort_order=int(icp.get("sort_order") or 0),
                            )
                        )

                # Restore 2D zone map image files atomically & recompute dimensions (also handles legacy v1.0 zips)
                for pslug, rel_path in (map_img_refs or {}).items():
                    if slug_filter is not None and pslug not in slug_filter:
                        continue
                    fname = Path(str(rel_path)).name
                    arc = f"files/urban_sim_maps/{fname}"
                    if arc in pkg.files:
                        img_bytes = pkg.files[arc]
                        tpid = proj_slug_to_id.get(pslug)
                        suffix = Path(fname).suffix.lower() or ".png"
                        hash8 = _sha256_bytes(img_bytes)[:8]
                        dest_fname = f"{tpid}_{hash8}{suffix}" if tpid else fname
                        dest = resolve_urban_sim_map_image(workspace_root, dest_fname)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        tmp_dest = dest.with_name(f".tmp_{uuid.uuid4().hex[:8]}_{dest_fname}")
                        tmp_dest.write_bytes(img_bytes)
                        os.replace(tmp_dest, dest)
                        if tpid:
                            proj_obj = session.get(UrbanSimProject, tpid)
                            if proj_obj is not None:
                                proj_obj.zone_map_image_rel = dest_fname
                                proj_obj.map_image_version = int(getattr(proj_obj, "map_image_version", 0) or 0) + 1
                                proj_obj.map_image_updated_at = _utcnow_iso()
                                try:
                                    w, h = parse_image_dimensions(img_bytes, suffix)
                                    proj_obj.map_width = w
                                    proj_obj.map_height = h
                                    proj_obj.map_aspect_ratio = round(w / max(1, h), 4)
                                except ValueError:
                                    pass
                                session.add(proj_obj)

            # 4. urban_sim_personas
            if "urban_sim_personas" in effective_scopes:
                inc_pers: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/urban_sim_personas.json", []
                )
                if slug_filter is not None:
                    inc_pers = [p for p in inc_pers if p.get("project_slug") in slug_filter]

                for ip in inc_pers:
                    pslug = str(ip.get("project_slug") or "")
                    tpid = _resolve_target_project_id(pslug, str(ip.get("project_id") or ""))
                    if not tpid:
                        warnings.append(
                            f"Bỏ qua Persona '{ip.get('full_name')}' do không tìm thấy dự án '{pslug}' trên đích."
                        )
                        continue
                    aid = int(ip.get("agent_id") or 0)
                    existing_per = session.exec(
                        select(UrbanSimPersona).where(
                            UrbanSimPersona.project_id == tpid,
                            UrbanSimPersona.agent_id == aid,
                        )
                    ).first()

                    skey = str(ip.get("secret_ref_key") or _secret_key_persona(pslug, aid))
                    resolved_pw_enc = _resolve_secret_enc(
                        skey,
                        existing_per.login_password_enc if existing_per else None,
                    )

                    if existing_per is not None:
                        existing_per.full_name = str(ip.get("full_name") or existing_per.full_name)
                        existing_per.role_code = str(ip.get("role_code") or existing_per.role_code)
                        existing_per.role_title = str(
                            ip.get("role_title") or existing_per.role_title
                        )
                        existing_per.department = str(ip.get("department") or "")
                        existing_per.group_type = str(
                            ip.get("group_type") or existing_per.group_type
                        )
                        existing_per.software_access_enabled = bool(
                            ip.get("software_access_enabled", True)
                        )
                        existing_per.is_pilot_member = bool(ip.get("is_pilot_member", False))
                        existing_per.is_active = bool(ip.get("is_active", True))
                        existing_per.home_zone = str(ip.get("home_zone") or "LOBBY_MAIN")
                        existing_per.avatar_icon = ip.get("avatar_icon")
                        existing_per.domain_knowledge_prompt = str(
                            ip.get("domain_knowledge_prompt") or ""
                        )
                        existing_per.initial_tasks_json = str(
                            ip.get("initial_tasks_json") or "[]"
                        )
                        existing_per.portal_url = ip.get("portal_url")
                        existing_per.login_username = ip.get("login_username")
                        existing_per.default_activated_skill_ids_json = ip.get(
                            "default_activated_skill_ids_json"
                        )
                        existing_per.disabled_skill_ids_json = ip.get(
                            "disabled_skill_ids_json"
                        )
                        existing_per.profile_traits_json = ip.get("profile_traits_json")
                        existing_per.login_password_enc = resolved_pw_enc
                        existing_per.updated_at = _utcnow_iso()
                        session.add(existing_per)
                        applied_counts["urban_sim_personas"]["updated"] += 1
                    else:
                        session.add(
                            UrbanSimPersona(
                                id=f"per_{uuid.uuid4().hex[:12]}",
                                project_id=tpid,
                                agent_id=aid,
                                full_name=str(ip.get("full_name") or f"Agent {aid}"),
                                role_code=str(ip.get("role_code") or "BQL_STAFF"),
                                role_title=str(ip.get("role_title") or "Staff"),
                                department=str(ip.get("department") or ""),
                                group_type=str(ip.get("group_type") or "BQL"),
                                software_access_enabled=bool(
                                    ip.get("software_access_enabled", True)
                                ),
                                is_pilot_member=bool(ip.get("is_pilot_member", False)),
                                is_active=bool(ip.get("is_active", True)),
                                home_zone=str(ip.get("home_zone") or "LOBBY_MAIN"),
                                avatar_icon=ip.get("avatar_icon"),
                                domain_knowledge_prompt=str(
                                    ip.get("domain_knowledge_prompt") or ""
                                ),
                                initial_tasks_json=str(ip.get("initial_tasks_json") or "[]"),
                                portal_url=ip.get("portal_url"),
                                login_username=ip.get("login_username"),
                                default_activated_skill_ids_json=ip.get(
                                    "default_activated_skill_ids_json"
                                ),
                                disabled_skill_ids_json=ip.get(
                                    "disabled_skill_ids_json"
                                ),
                                profile_traits_json=ip.get("profile_traits_json"),
                                login_password_enc=resolved_pw_enc,
                                created_at=str(ip.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["urban_sim_personas"]["created"] += 1

            # 5. urban_sim_atlas_configs
            if "urban_sim_atlas_configs" in effective_scopes:
                inc_atlas: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/urban_sim_atlas_configs.json", []
                )
                if slug_filter is not None:
                    inc_atlas = [a for a in inc_atlas if a.get("project_slug") in slug_filter]

                for ia in inc_atlas:
                    pslug = str(ia.get("project_slug") or "")
                    tpid = _resolve_target_project_id(pslug, str(ia.get("project_id") or ""))
                    if not tpid:
                        warnings.append(
                            f"Bỏ qua cấu hình Atlas do không tìm thấy dự án '{pslug}' trên đích."
                        )
                        continue
                    existing_a = session.get(UrbanSimAtlasConfig, tpid)
                    skey = str(ia.get("secret_ref_key") or _secret_key_atlas(pslug))
                    resolved_key_enc = _resolve_secret_enc(
                        skey,
                        existing_a.atlas_api_key_enc if existing_a else None,
                    )
                    if existing_a is not None:
                        existing_a.enabled = bool(ia.get("enabled", True))
                        existing_a.atlas_api_url = str(
                            ia.get("atlas_api_url") or existing_a.atlas_api_url
                        )
                        existing_a.atlas_api_key_enc = resolved_key_enc
                        existing_a.actor_persona = str(ia.get("actor_persona") or "END_USER")
                        existing_a.source_mode = str(ia.get("source_mode") or "FEDERATED_AUTO")
                        existing_a.attach_screenshot_on_ask = bool(
                            ia.get("attach_screenshot_on_ask", False)
                        )
                        existing_a.quota_per_min = int(ia.get("quota_per_min") or 25)
                        existing_a.max_asks_per_tick = int(ia.get("max_asks_per_tick") or 2)
                        existing_a.guardrail_mode = str(ia.get("guardrail_mode") or "SAFE_WRITE")
                        existing_a.record_prefix = str(ia.get("record_prefix") or "[SIM-BQL]")
                        existing_a.blocked_keywords_json = str(
                            ia.get("blocked_keywords_json") or "[]"
                        )
                        existing_a.last_verified_at = ia.get("last_verified_at")
                        existing_a.last_verified_project_id = ia.get("last_verified_project_id")
                        existing_a.last_verified_project_name = ia.get(
                            "last_verified_project_name"
                        )
                        existing_a.last_verified_scopes_json = str(
                            ia.get("last_verified_scopes_json") or "[]"
                        )
                        existing_a.updated_at = _utcnow_iso()
                        session.add(existing_a)
                        applied_counts["urban_sim_atlas_configs"]["updated"] += 1
                    else:
                        session.add(
                            UrbanSimAtlasConfig(
                                project_id=tpid,
                                enabled=bool(ia.get("enabled", True)),
                                atlas_api_url=str(
                                    ia.get("atlas_api_url") or "https://atlas.demego.vn"
                                ),
                                atlas_api_key_enc=resolved_key_enc,
                                actor_persona=str(ia.get("actor_persona") or "END_USER"),
                                source_mode=str(ia.get("source_mode") or "FEDERATED_AUTO"),
                                attach_screenshot_on_ask=bool(
                                    ia.get("attach_screenshot_on_ask", False)
                                ),
                                quota_per_min=int(ia.get("quota_per_min") or 25),
                                max_asks_per_tick=int(ia.get("max_asks_per_tick") or 2),
                                guardrail_mode=str(ia.get("guardrail_mode") or "SAFE_WRITE"),
                                record_prefix=str(ia.get("record_prefix") or "[SIM-BQL]"),
                                blocked_keywords_json=str(
                                    ia.get("blocked_keywords_json") or "[]"
                                ),
                                last_verified_at=ia.get("last_verified_at"),
                                last_verified_project_id=ia.get("last_verified_project_id"),
                                last_verified_project_name=ia.get("last_verified_project_name"),
                                last_verified_scopes_json=str(
                                    ia.get("last_verified_scopes_json") or "[]"
                                ),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["urban_sim_atlas_configs"]["created"] += 1

            # 6. platform_maps
            if "platform_maps" in effective_scopes:
                inc_maps: list[dict[str, Any]] = _read_pkg_json(pkg, "data/platform_maps.json", [])
                for m in inc_maps:
                    src_id = str(m.get("id") or "").strip()
                    tenant_id = str(m.get("tenant_id") or "default").strip()
                    name = str(m.get("name") or "").strip()
                    if not name:
                        continue
                    file_path = str(m.get("file_path") or "")
                    bundled_arc = str(m.get("bundled_file") or "")
                    if bundled_arc and bundled_arc in pkg.files:
                        fname = Path(bundled_arc).name
                        dest_map = resolve_under_root(
                            workspace_root, ".agentsociety", "platform_uploads", "maps", fname
                        )
                        dest_map.parent.mkdir(parents=True, exist_ok=True)
                        dest_map.write_bytes(pkg.files[bundled_arc])
                        file_path = f".agentsociety/platform_uploads/maps/{fname}"

                    linked_pid = _resolve_target_project_id(
                        str(m.get("linked_project_slug") or ""),
                        str(m.get("linked_project_id") or ""),
                    )

                    existing_m = session.get(PlatformMapConfig, src_id) if src_id else None
                    if existing_m is None:
                        existing_m = session.exec(
                            select(PlatformMapConfig).where(
                                PlatformMapConfig.tenant_id == tenant_id,
                                PlatformMapConfig.name == name,
                            )
                        ).first()
                    if existing_m is not None:
                        existing_m.name = name
                        existing_m.description = str(m.get("description") or "")
                        existing_m.file_path = file_path
                        existing_m.map_type = str(m.get("map_type") or existing_m.map_type)
                        existing_m.linked_project_id = linked_pid
                        existing_m.updated_at = _utcnow_iso()
                        session.add(existing_m)
                        applied_counts["platform_maps"]["updated"] += 1
                    else:
                        session.add(
                            PlatformMapConfig(
                                id=src_id or str(uuid.uuid4()),
                                tenant_id=tenant_id,
                                name=name,
                                description=str(m.get("description") or ""),
                                file_path=file_path,
                                map_type=str(m.get("map_type") or "urban_zones"),
                                linked_project_id=linked_pid,
                                created_at=str(m.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["platform_maps"]["created"] += 1

            # 7. platform_agent_templates
            template_id_map: dict[str, str] = {
                t.id: t.id for t in session.exec(select(PlatformAgentTemplate)).all()
            }
            if "platform_agent_templates" in effective_scopes:
                inc_tpls: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/platform_agent_templates.json", []
                )
                for t in inc_tpls:
                    src_id = str(t.get("id") or "").strip()
                    tenant_id = str(t.get("tenant_id") or "default").strip()
                    name = str(t.get("name") or "").strip()
                    if not name:
                        continue
                    existing_t = session.get(PlatformAgentTemplate, src_id) if src_id else None
                    if existing_t is None:
                        existing_t = session.exec(
                            select(PlatformAgentTemplate).where(
                                PlatformAgentTemplate.tenant_id == tenant_id,
                                PlatformAgentTemplate.name == name,
                            )
                        ).first()
                    if existing_t is not None:
                        existing_t.name = name
                        existing_t.description = str(t.get("description") or "")
                        existing_t.agent_type = str(t.get("agent_type") or "citizen")
                        existing_t.agent_class = str(t.get("agent_class") or "PersonAgent")
                        existing_t.memory_distributions_json = str(
                            t.get("memory_distributions_json") or "{}"
                        )
                        existing_t.agent_params_json = str(t.get("agent_params_json") or "{}")
                        existing_t.blocks_json = str(t.get("blocks_json") or "{}")
                        existing_t.updated_at = _utcnow_iso()
                        session.add(existing_t)
                        if src_id:
                            template_id_map[src_id] = existing_t.id
                        applied_counts["platform_agent_templates"]["updated"] += 1
                    else:
                        new_t = PlatformAgentTemplate(
                            id=src_id or str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            name=name,
                            description=str(t.get("description") or ""),
                            agent_type=str(t.get("agent_type") or "citizen"),
                            agent_class=str(t.get("agent_class") or "PersonAgent"),
                            memory_distributions_json=str(
                                t.get("memory_distributions_json") or "{}"
                            ),
                            agent_params_json=str(t.get("agent_params_json") or "{}"),
                            blocks_json=str(t.get("blocks_json") or "{}"),
                            created_at=str(t.get("created_at") or _utcnow_iso()),
                            updated_at=_utcnow_iso(),
                        )
                        session.add(new_t)
                        session.flush()
                        if src_id:
                            template_id_map[src_id] = new_t.id
                        applied_counts["platform_agent_templates"]["created"] += 1

            # 8. platform_agent_profiles
            if "platform_agent_profiles" in effective_scopes:
                inc_profs: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/platform_agent_profiles.json", []
                )
                for pr in inc_profs:
                    src_id = str(pr.get("id") or "").strip()
                    tenant_id = str(pr.get("tenant_id") or "default").strip()
                    name = str(pr.get("name") or "").strip()
                    if not name:
                        continue
                    existing_pr = session.get(PlatformAgentProfile, src_id) if src_id else None
                    if existing_pr is None:
                        existing_pr = session.exec(
                            select(PlatformAgentProfile).where(
                                PlatformAgentProfile.tenant_id == tenant_id,
                                PlatformAgentProfile.name == name,
                            )
                        ).first()
                    if existing_pr is not None:
                        existing_pr.name = name
                        existing_pr.description = str(pr.get("description") or "")
                        existing_pr.agent_type = str(pr.get("agent_type") or "citizen")
                        existing_pr.file_path = str(pr.get("file_path") or "")
                        existing_pr.record_count = int(pr.get("record_count") or 0)
                        existing_pr.records_json = str(pr.get("records_json") or "[]")
                        existing_pr.updated_at = _utcnow_iso()
                        session.add(existing_pr)
                        applied_counts["platform_agent_profiles"]["updated"] += 1
                    else:
                        session.add(
                            PlatformAgentProfile(
                                id=src_id or str(uuid.uuid4()),
                                tenant_id=tenant_id,
                                name=name,
                                description=str(pr.get("description") or ""),
                                agent_type=str(pr.get("agent_type") or "citizen"),
                                file_path=str(pr.get("file_path") or ""),
                                record_count=int(pr.get("record_count") or 0),
                                records_json=str(pr.get("records_json") or "[]"),
                                created_at=str(pr.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["platform_agent_profiles"]["created"] += 1

            # 9. platform_agent_configs
            if "platform_agent_configs" in effective_scopes:
                inc_ac: list[dict[str, Any]] = _read_pkg_json(
                    pkg, "data/platform_agent_configs.json", []
                )
                for ac in inc_ac:
                    src_id = str(ac.get("id") or "").strip()
                    tenant_id = str(ac.get("tenant_id") or "default").strip()
                    name = str(ac.get("name") or "").strip()
                    if not name:
                        continue
                    cfg_obj = _safe_json(ac.get("config_json"), {})
                    if isinstance(cfg_obj, dict):
                        citizens = cfg_obj.get("citizens")
                        if isinstance(citizens, list):
                            for cit in citizens:
                                if isinstance(cit, dict) and cit.get("template_id"):
                                    tid = str(cit["template_id"])
                                    if tid in template_id_map:
                                        cit["template_id"] = template_id_map[tid]
                        sup = cfg_obj.get("supervisor")
                        if isinstance(sup, dict) and sup.get("template_id"):
                            tid = str(sup["template_id"])
                            if tid in template_id_map:
                                sup["template_id"] = template_id_map[tid]
                    remapped_json = json.dumps(cfg_obj, ensure_ascii=False)

                    existing_ac = session.get(PlatformAgentConfig, src_id) if src_id else None
                    if existing_ac is None:
                        existing_ac = session.exec(
                            select(PlatformAgentConfig).where(
                                PlatformAgentConfig.tenant_id == tenant_id,
                                PlatformAgentConfig.name == name,
                            )
                        ).first()
                    if existing_ac is not None:
                        existing_ac.name = name
                        existing_ac.description = str(ac.get("description") or "")
                        existing_ac.config_json = remapped_json
                        existing_ac.updated_at = _utcnow_iso()
                        session.add(existing_ac)
                        applied_counts["platform_agent_configs"]["updated"] += 1
                    else:
                        session.add(
                            PlatformAgentConfig(
                                id=src_id or str(uuid.uuid4()),
                                tenant_id=tenant_id,
                                name=name,
                                description=str(ac.get("description") or ""),
                                config_json=remapped_json,
                                created_at=str(ac.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["platform_agent_configs"]["created"] += 1

            # 10. platform_workflows_surveys
            if "platform_workflows_surveys" in effective_scopes:
                ws_payload = _read_pkg_json(pkg, "data/platform_workflows_surveys.json", {})
                inc_wfs = ws_payload.get("workflows", []) if isinstance(ws_payload, dict) else []
                inc_svs = ws_payload.get("surveys", []) if isinstance(ws_payload, dict) else []

                for w in inc_wfs:
                    src_id = str(w.get("id") or "").strip()
                    tenant_id = str(w.get("tenant_id") or "default").strip()
                    name = str(w.get("name") or "").strip()
                    if not name:
                        continue
                    existing_w = session.get(PlatformWorkflowConfig, src_id) if src_id else None
                    if existing_w is None:
                        existing_w = session.exec(
                            select(PlatformWorkflowConfig).where(
                                PlatformWorkflowConfig.tenant_id == tenant_id,
                                PlatformWorkflowConfig.name == name,
                            )
                        ).first()
                    if existing_w is not None:
                        existing_w.name = name
                        existing_w.description = str(w.get("description") or "")
                        existing_w.config_json = str(w.get("config_json") or "[]")
                        existing_w.updated_at = _utcnow_iso()
                        session.add(existing_w)
                        applied_counts["platform_workflows_surveys"]["updated"] += 1
                    else:
                        session.add(
                            PlatformWorkflowConfig(
                                id=src_id or str(uuid.uuid4()),
                                tenant_id=tenant_id,
                                name=name,
                                description=str(w.get("description") or ""),
                                config_json=str(w.get("config_json") or "[]"),
                                created_at=str(w.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["platform_workflows_surveys"]["created"] += 1

                for s in inc_svs:
                    src_id = str(s.get("id") or "").strip()
                    tenant_id = str(s.get("tenant_id") or "default").strip()
                    name = str(s.get("name") or "").strip()
                    if not name:
                        continue
                    existing_s = session.get(PlatformSurvey, src_id) if src_id else None
                    if existing_s is None:
                        existing_s = session.exec(
                            select(PlatformSurvey).where(
                                PlatformSurvey.tenant_id == tenant_id,
                                PlatformSurvey.name == name,
                            )
                        ).first()
                    if existing_s is not None:
                        existing_s.name = name
                        existing_s.data_json = str(s.get("data_json") or "{}")
                        existing_s.updated_at = _utcnow_iso()
                        session.add(existing_s)
                        applied_counts["platform_workflows_surveys"]["updated"] += 1
                    else:
                        session.add(
                            PlatformSurvey(
                                id=src_id or str(uuid.uuid4()),
                                tenant_id=tenant_id,
                                name=name,
                                data_json=str(s.get("data_json") or "{}"),
                                created_at=str(s.get("created_at") or _utcnow_iso()),
                                updated_at=_utcnow_iso(),
                            )
                        )
                        applied_counts["platform_workflows_surveys"]["created"] += 1

            session.commit()
        except Exception:
            session.rollback()
            raise

    # 11. workspace_skills_and_params (filesystem atomic staging after DB commit)
    if "workspace_skills_and_params" in effective_scopes:
        skills_root = custom_skills_root(str(workspace_root))
        skills_root.mkdir(parents=True, exist_ok=True)
        prefill_dest = resolve_under_root(workspace_root, ".agentsociety", "prefill_params.json")

        if mode == "REPLACE_SCOPE":
            for old_dir in _list_custom_skill_dirs(workspace_root):
                shutil.rmtree(old_dir, ignore_errors=True)
                applied_counts["workspace_skills_and_params"]["deleted"] += 1
            if prefill_dest.is_file():
                prefill_dest.unlink(missing_ok=True)
                applied_counts["workspace_skills_and_params"]["deleted"] += 1

        if "files/prefill_params.json" in pkg.files:
            existed = prefill_dest.is_file()
            prefill_dest.parent.mkdir(parents=True, exist_ok=True)
            prefill_dest.write_bytes(pkg.files["files/prefill_params.json"])
            if existed:
                applied_counts["workspace_skills_and_params"]["updated"] += 1
            else:
                applied_counts["workspace_skills_and_params"]["created"] += 1

        skill_files_by_name: dict[str, dict[str, bytes]] = {}
        prefix = "files/custom_skills/"
        for arcname, blob in pkg.files.items():
            if not arcname.startswith(prefix):
                continue
            rest = arcname[len(prefix) :]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                continue
            sname, rel_part = parts[0], parts[1]
            require_safe_skill_name(sname)
            skill_files_by_name.setdefault(sname, {})[rel_part] = blob

        for sname, rel_map in skill_files_by_name.items():
            dest_skill = resolve_under_root(skills_root, sname)
            existed = dest_skill.is_dir()
            with tempfile.TemporaryDirectory(prefix="as2_skill_restore_") as tmp_dir:
                staged = Path(tmp_dir) / sname
                staged.mkdir(parents=True, exist_ok=True)
                for rel_part, blob in rel_map.items():
                    target = resolve_under_root(staged, *rel_part.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
                if dest_skill.exists():
                    shutil.rmtree(dest_skill)
                shutil.copytree(staged, dest_skill)
            if existed:
                applied_counts["workspace_skills_and_params"]["updated"] += 1
            else:
                applied_counts["workspace_skills_and_params"]["created"] += 1

        # Hot-reload custom skill registry
        try:
            get_skill_registry().scan_custom(skills_root)
        except Exception as exc:
            logger.warning("[SystemBackup] Không thể scan lại custom skills sau restore: %s", exc)

    return {
        "success": True,
        "mode": mode,
        "trigger": trigger_label,
        "restored_at": _utcnow_iso(),
        "effective_scopes": effective_scopes,
        "applied_counts": applied_counts,
        "secrets_restored_count": len(plain_secrets) if not use_raw_local_secrets else len(raw_secrets),
        "pre_restore_snapshot": snapshot_record,
        "warnings": list(dict.fromkeys(warnings)),
    }


def rollback_from_snapshot(workspace_root: Path, snapshot_id: str) -> dict[str, Any]:
    """Rollback target environment using a local Pre-Restore Snapshot (with raw Fernet secrets)."""
    snap_path = get_snapshot_file_path(workspace_root, snapshot_id)
    snap_bytes = snap_path.read_bytes()
    return execute_restore(
        workspace_root,
        zip_bytes=snap_bytes,
        selected_scopes=None,
        mode="REPLACE_SCOPE",
        restore_secrets=True,
        passphrase="",
        project_slugs=None,
        create_pre_restore_snapshot=True,
        use_raw_local_secrets=True,
        trigger_label=f"ROLLBACK_{snapshot_id}",
    )
