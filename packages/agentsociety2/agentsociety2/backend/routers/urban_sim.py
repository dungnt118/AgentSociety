"""Dynamic Urban Simulation REST API Control Plane (/api/v1/urban-sim/*)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agentsociety2.backend.path_security import (
    _configured_workspace_root,
    resolve_under_root,
    resolve_urban_sim_map_image,
    resolve_urban_sim_run_dir,
    resolve_urban_sim_screenshot,
)
from agentsociety2.backend.services.urban_sim.competency import (
    DEFAULT_MULBERRYLANE_RUBRIC,
    evaluate_run_competency,
    get_competency_audit_manager,
    render_competency_markdown,
    validate_competency_rubric_json,
)
from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    validate_external_url,
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
    resolve_default_persona_icon,
)
from agentsociety2.backend.services.urban_sim.lifecycle import (
    UrbanSimLifecycleManager,
    compute_run_cost,
    derive_execution_phase,
)
from agentsociety2.backend.services.urban_sim.map_generator import (
    MAX_CHECKPOINT_MD_CHARS,
    MAX_PROMPT_CHARS,
    build_digital_map_geojson,
    find_containing_zone_key,
    generate_checkpoints_draft,
    generate_digital_map_draft,
    generate_zone_from_point_draft,
    normalize_map_key,
    parse_image_dimensions,
    parse_polygon_json,
    project_has_digital_map,
    recompute_checkpoint_zones,
    validate_and_normalize_polygon,
)
from agentsociety2.backend.services.urban_sim.seed_mulberrylane import (
    ACCOUNTING_PERSONA_TEMPLATE,
    MULBERRYLANE_CHECKPOINTS,
    MULBERRYLANE_MAP_PROMPT,
    MULBERRYLANE_PERSONAS,
    MULBERRYLANE_SCENARIO_BRIEF,
    MULBERRYLANE_ZONE_GEOMETRIES,
    MULBERRYLANE_ZONES,
    ensure_mulberrylane_seed,
)
from agentsociety2.backend.services.urban_sim.timeline import (
    build_agent_timeline,
    classify_screenshot_file,
)
from agentsociety2.logger import get_logger
from agentsociety2.society.society import LLM_STATS_JSON, SOCIETY_STEP_JSON

logger = get_logger()

router = APIRouter(prefix="/api/v1/urban-sim", tags=["Urban Simulation"])

_lifecycle_manager = UrbanSimLifecycleManager()
_MAX_MAP_UPLOAD_BYTES = 5 * 1024 * 1024


def get_lifecycle_manager() -> UrbanSimLifecycleManager:
    """Return shared UrbanSimLifecycleManager instance for app lifespan & API handlers."""
    return _lifecycle_manager


def _ws_root() -> Path:
    return Path(_configured_workspace_root()).resolve()


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_mask_placeholder(value: str | None) -> bool:
    clean = (value or "").strip()
    return not clean or set(clean) <= {"•", "*"}


def _parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _detect_raster_magic(data: bytes) -> tuple[str, str]:
    """Verify magic bytes strictly (allow PNG/JPEG/WEBP only; reject SVG/HTML/arbitrary)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise HTTPException(
        status_code=400,
        detail="Định dạng ảnh không hợp lệ. Chỉ chấp nhận PNG, JPEG hoặc WEBP thực tế (từ chối SVG/HTML).",
    )


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _serialize_persona(p: UrbanSimPersona) -> dict[str, Any]:
    has_pw = bool(p.login_password_enc and p.login_password_enc.strip())
    raw_activated = getattr(p, "default_activated_skill_ids_json", None)
    raw_disabled = getattr(p, "disabled_skill_ids_json", None)
    return {
        "id": p.id,
        "project_id": p.project_id,
        "agent_id": p.agent_id,
        "full_name": p.full_name,
        "role_code": p.role_code,
        "role_title": p.role_title,
        "department": p.department,
        "group_type": p.group_type,
        "software_access_enabled": bool(p.software_access_enabled),
        "is_pilot_member": bool(p.is_pilot_member),
        "is_active": bool(p.is_active),
        "home_zone": p.home_zone,
        "avatar_icon": (getattr(p, "avatar_icon", None) or "").strip()
        or resolve_default_persona_icon(p.role_code, p.group_type, p.full_name),
        "domain_knowledge_prompt": p.domain_knowledge_prompt,
        "initial_tasks": [str(x) for x in _parse_json_list(p.initial_tasks_json)],
        "default_activated_skill_ids": (
            [str(x) for x in _parse_json_list(raw_activated)]
            if raw_activated is not None
            else None
        ),
        "disabled_skill_ids": (
            [str(x) for x in _parse_json_list(raw_disabled)]
            if raw_disabled is not None
            else None
        ),
        "profile_traits": _parse_json_dict(getattr(p, "profile_traits_json", None)),
        "portal_url": p.portal_url,
        "login_username": p.login_username,
        "has_password": has_pw,
        "password_masked": mask_secret(p.login_password_enc),
        "account_configured": bool(
            (p.login_username or "").strip() and has_pw
        ),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _serialize_atlas(cfg: UrbanSimAtlasConfig | None, project_id: str) -> dict[str, Any]:
    if cfg is None:
        return {
            "project_id": project_id,
            "enabled": True,
            "atlas_api_url": "https://atlas.demego.vn",
            "has_api_key": False,
            "api_key_masked": "",
            "actor_persona": "END_USER",
            "source_mode": "FEDERATED_AUTO",
            "attach_screenshot_on_ask": False,
            "quota_per_min": 25,
            "max_asks_per_tick": 2,
            "guardrail_mode": "SAFE_WRITE",
            "record_prefix": "[SIM-BQL]",
            "blocked_keywords": [],
            "last_verified_at": None,
            "last_verified_project_id": None,
            "last_verified_project_name": None,
            "last_verified_scopes": [],
            "updated_at": None,
        }
    return {
        "project_id": cfg.project_id,
        "enabled": bool(cfg.enabled),
        "atlas_api_url": cfg.atlas_api_url,
        "has_api_key": bool(cfg.atlas_api_key_enc and cfg.atlas_api_key_enc.strip()),
        "api_key_masked": mask_secret(cfg.atlas_api_key_enc),
        "actor_persona": cfg.actor_persona,
        "source_mode": cfg.source_mode,
        "attach_screenshot_on_ask": bool(cfg.attach_screenshot_on_ask),
        "quota_per_min": int(cfg.quota_per_min),
        "max_asks_per_tick": int(cfg.max_asks_per_tick),
        "guardrail_mode": cfg.guardrail_mode,
        "record_prefix": cfg.record_prefix,
        "blocked_keywords": [str(k) for k in _parse_json_list(cfg.blocked_keywords_json)],
        "last_verified_at": cfg.last_verified_at,
        "last_verified_project_id": cfg.last_verified_project_id,
        "last_verified_project_name": cfg.last_verified_project_name,
        "last_verified_scopes": [str(s) for s in _parse_json_list(cfg.last_verified_scopes_json)],
        "updated_at": cfg.updated_at,
    }


def _serialize_run(run: UrbanSimRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "run_number": int(run.run_number),
        "run_dir": run.run_dir,
        "status": run.status,
        "pause_reason": run.pause_reason,
        "pid": run.pid,
        "step_count": int(run.step_count),
        "total_steps": int(run.total_steps),
        "active_agent_count": int(run.active_agent_count),
        "pilot_mode": bool(run.pilot_mode),
        "router_type": run.router_type,
        "total_tokens": int(run.total_tokens),
        "total_cost_usd": float(run.total_cost_usd),
        "error_message": run.error_message,
        "started_at": run.started_at,
        "paused_at": run.paused_at,
        "ended_at": run.ended_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _serialize_project_summary(
    session: Session, project: UrbanSimProject
) -> dict[str, Any]:
    personas = session.exec(
        select(UrbanSimPersona).where(UrbanSimPersona.project_id == project.id)
    ).all()
    zones = session.exec(
        select(UrbanSimZone).where(UrbanSimZone.project_id == project.id)
    ).all()
    checkpoints = session.exec(
        select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project.id)
    ).all()
    has_digital_map = bool(project.zone_map_image_rel) or any(
        (parse_polygon_json(getattr(z, "polygon_points_json", None)) is not None)
        for z in zones
    )
    atlas = session.get(UrbanSimAtlasConfig, project.id)
    latest_run = session.exec(
        select(UrbanSimRun)
        .where(UrbanSimRun.project_id == project.id)
        .order_by(UrbanSimRun.run_number.desc())  # type: ignore[union-attr]
    ).first()

    bql = [p for p in personas if p.group_type == "BQL"]
    residents = [p for p in personas if p.group_type == "RESIDENT"]
    configured_bql = [
        p
        for p in bql
        if (p.login_username or "").strip() and (p.login_password_enc or "").strip()
    ]
    return {
        "id": project.id,
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "default_portal_url": project.default_portal_url,
        "router_type": project.router_type,
        "num_steps": int(project.num_steps),
        "tick_seconds": int(project.tick_seconds),
        "start_time_iso": project.start_time_iso,
        "max_react_turns": int(project.max_react_turns),
        "max_cost_usd_per_run": float(project.max_cost_usd_per_run),
        "pilot_mode": bool(project.pilot_mode),
        "zone_map_image_rel": project.zone_map_image_rel,
        "has_zone_map_image": bool(project.zone_map_image_rel),
        "has_digital_map": has_digital_map,
        "map_prompt": getattr(project, "map_prompt", None) or "",
        "map_width": getattr(project, "map_width", None),
        "map_height": getattr(project, "map_height", None),
        "map_aspect_ratio": getattr(project, "map_aspect_ratio", None) or 1.6,
        "map_image_version": int(getattr(project, "map_image_version", 0) or 0),
        "map_image_updated_at": getattr(project, "map_image_updated_at", None),
        "llm_config_id": project.llm_config_id,
        "enable_sociological_debrief": bool(getattr(project, "enable_sociological_debrief", True)),
        "enable_competency_prepost_quiz": bool(getattr(project, "enable_competency_prepost_quiz", False)),
        "competency_rubric_json": getattr(project, "competency_rubric_json", None),
        "stats": {
            "total_personas": len(personas),
            "active_personas": sum(1 for p in personas if p.is_active),
            "pilot_personas": sum(1 for p in personas if p.is_active and p.is_pilot_member),
            "bql_count": len(bql),
            "resident_count": len(residents),
            "bql_credentials_configured": len(configured_bql),
            "zones_count": len(zones),
            "checkpoints_count": len(checkpoints),
            "atlas_key_configured": bool(atlas and (atlas.atlas_api_key_enc or "").strip()),
            "atlas_verified_at": atlas.last_verified_at if atlas else None,
        },
        "latest_run": _serialize_run(latest_run) if latest_run else None,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _require_project(session: Session, project_id: str) -> UrbanSimProject:
    proj = session.get(UrbanSimProject, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án mô phỏng.")
    return proj


# ==================== REQUEST SCHEMAS ====================


class ProjectCreateRequest(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=200)
    description: str = ""
    default_portal_url: str = "https://mulberrylane.sandbox.demego.vn"
    router_type: Literal["react", "codegen"] = "react"
    num_steps: int = Field(8, ge=1, le=200)
    tick_seconds: int = Field(900, ge=60, le=86400)
    start_time_iso: str = "2026-06-15T08:00:00+07:00"
    max_react_turns: int = Field(6, ge=2, le=20)
    max_cost_usd_per_run: float = Field(5.0, gt=0.0, le=500.0)
    pilot_mode: bool = True
    llm_config_id: str | None = None
    enable_sociological_debrief: bool = True
    enable_competency_prepost_quiz: bool = False
    competency_rubric_json: str | None = None
    seed_mulberrylane_template: bool = True


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    default_portal_url: str | None = None
    router_type: Literal["react", "codegen"] | None = None
    num_steps: int | None = Field(None, ge=1, le=200)
    tick_seconds: int | None = Field(None, ge=60, le=86400)
    start_time_iso: str | None = None
    max_react_turns: int | None = Field(None, ge=2, le=20)
    max_cost_usd_per_run: float | None = Field(None, gt=0.0, le=500.0)
    pilot_mode: bool | None = None
    llm_config_id: str | None = None
    enable_sociological_debrief: bool | None = None
    enable_competency_prepost_quiz: bool | None = None
    competency_rubric_json: str | None = None


class PersonaCreateRequest(BaseModel):
    agent_id: int | None = Field(None, ge=1)
    full_name: str = Field(..., min_length=1, max_length=160)
    role_code: str = Field("BQL_STAFF", min_length=1, max_length=64)
    role_title: str = Field(..., min_length=1, max_length=160)
    department: str = Field("Ban Quản lý", max_length=160)
    group_type: Literal["BQL", "RESIDENT"] = "BQL"
    software_access_enabled: bool = True
    is_pilot_member: bool = False
    is_active: bool = True
    home_zone: str = "LOBBY_MAIN"
    avatar_icon: str | None = Field(None, max_length=16)
    domain_knowledge_prompt: str = ""
    initial_tasks: list[str] = Field(default_factory=list)
    default_activated_skill_ids: list[str] | None = None
    disabled_skill_ids: list[str] | None = None
    profile_traits: dict[str, Any] | None = None
    portal_url: str | None = None
    login_username: str | None = None
    login_password: str | None = None


class PersonaUpdateRequest(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=160)
    role_code: str | None = None
    role_title: str | None = None
    department: str | None = None
    group_type: Literal["BQL", "RESIDENT"] | None = None
    software_access_enabled: bool | None = None
    is_pilot_member: bool | None = None
    is_active: bool | None = None
    home_zone: str | None = None
    avatar_icon: str | None = Field(None, max_length=16)
    domain_knowledge_prompt: str | None = None
    initial_tasks: list[str] | None = None
    default_activated_skill_ids: list[str] | None = None
    disabled_skill_ids: list[str] | None = None
    profile_traits: dict[str, Any] | None = None
    portal_url: str | None = None
    login_username: str | None = None
    login_password: str | None = None
    clear_password: bool = False


class ZoneAssignPersonasRequest(BaseModel):
    persona_ids: list[str] = Field(default_factory=list, max_length=200)
    fallback_zone_key: str | None = None


class AtlasConfigUpdateRequest(BaseModel):
    enabled: bool = True
    atlas_api_url: str = "https://atlas.demego.vn"
    atlas_api_key: str | None = None
    clear_api_key: bool = False
    actor_persona: Literal["END_USER", "ADMIN", "OPERATOR"] = "END_USER"
    source_mode: Literal["FEDERATED_AUTO", "LOCAL_ONLY", "HYBRID"] = "FEDERATED_AUTO"
    attach_screenshot_on_ask: bool = False
    quota_per_min: int = Field(25, ge=1, le=30)
    max_asks_per_tick: int = Field(2, ge=1, le=10)
    guardrail_mode: Literal["SAFE_WRITE", "READ_ONLY", "FULL_RBAC"] = "SAFE_WRITE"
    record_prefix: str = Field("[SIM-BQL]", max_length=40)
    blocked_keywords: list[str] | None = None


class AtlasTestConnectionRequest(BaseModel):
    atlas_api_url: str | None = None
    atlas_api_key: str | None = None


ZoneTypeLiteral = Literal[
    "LOBBY",
    "OFFICE",
    "TECHNICAL",
    "SECURITY",
    "TOWER",
    "UTILITY",
    "PARKING",
    "COMMERCIAL",
    "OTHER",
]


class ZoneCreateRequest(BaseModel):
    zone_key: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=160)
    zone_type: ZoneTypeLiteral = "OFFICE"
    description: str = Field("", max_length=500)
    ambient_signals: str = Field("", max_length=2000)
    sort_order: int = 99
    center_x_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    center_y_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    polygon_points: list[list[float]] | None = None
    fill_color: str | None = Field(None, max_length=32)


class ZoneUpdateRequest(BaseModel):
    zone_key: str | None = Field(None, min_length=2, max_length=64)
    name: str | None = Field(None, min_length=2, max_length=160)
    zone_type: ZoneTypeLiteral | None = None
    description: str | None = Field(None, max_length=500)
    ambient_signals: str | None = Field(None, max_length=2000)
    sort_order: int | None = None
    center_x_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    center_y_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    polygon_points: list[list[float]] | None = None
    fill_color: str | None = Field(None, max_length=32)


class ZoneLayoutItem(BaseModel):
    id: str = Field(..., min_length=1)
    polygon_points: list[list[float]] | None = None
    center_x_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    center_y_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    fill_color: str | None = Field(None, max_length=32)


class ZonesLayoutRequest(BaseModel):
    zones: list[ZoneLayoutItem] = Field(..., max_length=100)


class DigitalMapMetaPatchRequest(BaseModel):
    map_prompt: str | None = Field(None, max_length=MAX_PROMPT_CHARS)
    map_aspect_ratio: float | None = Field(None, ge=0.4, le=3.5, allow_inf_nan=False)


class DigitalMapGenerateRequest(BaseModel):
    map_prompt: str = Field(..., min_length=5, max_length=MAX_PROMPT_CHARS)
    use_image: bool = True
    max_zones: int = Field(12, ge=1, le=25)


class DigitalMapApplyZoneItem(BaseModel):
    zone_key: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=160)
    zone_type: ZoneTypeLiteral = "OTHER"
    description: str = Field("", max_length=500)
    ambient_signals: str = Field("", max_length=2000)
    fill_color: str | None = Field(None, max_length=32)
    polygon_points: list[list[float]] = Field(..., min_length=3, max_length=64)
    sort_order: int = 1


class DigitalMapApplyRequest(BaseModel):
    mode: Literal["MERGE", "REPLACE"] = "MERGE"
    map_prompt: str | None = Field(None, max_length=MAX_PROMPT_CHARS)
    aspect_ratio: float | None = Field(None, ge=0.4, le=3.5, allow_inf_nan=False)
    zones: list[DigitalMapApplyZoneItem] = Field(..., min_length=1, max_length=40)


class ZoneFromPointRequest(BaseModel):
    center_x_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    center_y_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    prompt: str = Field(..., min_length=5, max_length=MAX_PROMPT_CHARS)


CheckpointCategoryLiteral = Literal["security", "facility", "amenity", "service", "general"]


class CheckpointCreateRequest(BaseModel):
    checkpoint_key: str | None = Field(None, min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=160)
    x_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    y_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    icon_emoji: str = Field("📍", min_length=1, max_length=16)
    description_md: str = Field("", max_length=MAX_CHECKPOINT_MD_CHARS)
    category: CheckpointCategoryLiteral = "general"
    sort_order: int = 99


class CheckpointUpdateRequest(BaseModel):
    checkpoint_key: str | None = Field(None, min_length=2, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=160)
    x_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    y_pct: float | None = Field(None, ge=0.0, le=100.0, allow_inf_nan=False)
    icon_emoji: str | None = Field(None, min_length=1, max_length=16)
    description_md: str | None = Field(None, max_length=MAX_CHECKPOINT_MD_CHARS)
    category: CheckpointCategoryLiteral | None = None
    sort_order: int | None = None


class CheckpointLayoutItem(BaseModel):
    id: str = Field(..., min_length=1)
    x_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    y_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)


class CheckpointsLayoutRequest(BaseModel):
    checkpoints: list[CheckpointLayoutItem] = Field(..., max_length=150)


class CheckpointsGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=MAX_PROMPT_CHARS)
    max_checkpoints: int = Field(20, ge=1, le=50)


class CheckpointApplyItem(BaseModel):
    checkpoint_key: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=160)
    x_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    y_pct: float = Field(..., ge=0.0, le=100.0, allow_inf_nan=False)
    icon_emoji: str = Field("📍", min_length=1, max_length=16)
    description_md: str = Field("", max_length=MAX_CHECKPOINT_MD_CHARS)
    category: CheckpointCategoryLiteral = "general"
    sort_order: int = 99


class CheckpointsApplyBatchRequest(BaseModel):
    checkpoints: list[CheckpointApplyItem] = Field(..., min_length=1, max_length=50)


def _normalize_zone_key(raw: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", (raw or "").strip().upper()).strip("_")
    if len(clean) < 2:
        raise HTTPException(
            status_code=400,
            detail="Mã khu vực (zone_key) phải chứa ít nhất 2 ký tự chữ/số (A-Z, 0-9, _).",
        )
    return clean[:64]


def _serialize_zone(z: UrbanSimZone, persona_count: int = 0) -> dict[str, Any]:
    return {
        "id": z.id,
        "project_id": z.project_id,
        "zone_key": z.zone_key,
        "name": z.name,
        "zone_type": z.zone_type,
        "description": z.description,
        "ambient_signals": getattr(z, "ambient_signals", "") or "",
        "sort_order": int(z.sort_order),
        "persona_count": int(persona_count),
        "center_x_pct": getattr(z, "center_x_pct", None),
        "center_y_pct": getattr(z, "center_y_pct", None),
        "polygon_points": parse_polygon_json(getattr(z, "polygon_points_json", None)),
        "fill_color": getattr(z, "fill_color", None),
    }


def _serialize_checkpoint(cp: UrbanSimCheckpoint) -> dict[str, Any]:
    return {
        "id": cp.id,
        "project_id": cp.project_id,
        "checkpoint_key": cp.checkpoint_key,
        "name": cp.name,
        "x_pct": round(float(cp.x_pct), 2),
        "y_pct": round(float(cp.y_pct), 2),
        "icon_emoji": cp.icon_emoji or "📍",
        "description_md": cp.description_md or "",
        "zone_key": cp.zone_key,
        "category": cp.category or "general",
        "sort_order": int(cp.sort_order),
        "created_at": cp.created_at,
        "updated_at": cp.updated_at,
    }


def _default_project_zone(session: Session, project_id: str) -> str:
    first_zone = session.exec(
        select(UrbanSimZone)
        .where(UrbanSimZone.project_id == project_id)
        .order_by(UrbanSimZone.sort_order)
    ).first()
    return first_zone.zone_key if first_zone is not None else "LOBBY_MAIN"


class SupportFeedbackRequest(BaseModel):
    message_id: str = Field(..., min_length=1)
    session_id: str = ""
    vote: Literal["LIKE", "DISLIKE", "NEUTRAL"] = "LIKE"
    reason: str = ""
    category: str = "OTHER"


# ==================== PROJECT ENDPOINTS ====================


@router.get("/projects")
async def list_projects():
    """Liệt kê các dự án mô phỏng khu đô thị (tự động seed MulberryLane nếu trống)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    ensure_mulberrylane_seed(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        projects = session.exec(
            select(UrbanSimProject).order_by(UrbanSimProject.created_at)
        ).all()
        return {
            "success": True,
            "items": [_serialize_project_summary(session, p) for p in projects],
        }


@router.post("/projects")
async def create_project(payload: ProjectCreateRequest):
    """Tạo mới một dự án mô phỏng khu đô thị từ giao diện."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    try:
        clean_portal = validate_external_url(payload.default_portal_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        clean_rubric = validate_competency_rubric_json(payload.competency_rubric_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine(ws)
    with Session(engine) as session:
        dup = session.exec(
            select(UrbanSimProject).where(UrbanSimProject.slug == payload.slug.strip())
        ).first()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Slug '{payload.slug}' đã tồn tại.",
            )
        project = UrbanSimProject(
            slug=payload.slug.strip(),
            name=payload.name.strip(),
            description=payload.description.strip(),
            default_portal_url=clean_portal,
            router_type=payload.router_type,
            num_steps=payload.num_steps,
            tick_seconds=payload.tick_seconds,
            start_time_iso=payload.start_time_iso,
            max_react_turns=payload.max_react_turns,
            max_cost_usd_per_run=payload.max_cost_usd_per_run,
            pilot_mode=payload.pilot_mode,
            map_prompt=MULBERRYLANE_MAP_PROMPT if payload.seed_mulberrylane_template else None,
            map_aspect_ratio=1.6 if payload.seed_mulberrylane_template else None,
            llm_config_id=payload.llm_config_id,
            enable_sociological_debrief=bool(payload.enable_sociological_debrief),
            enable_competency_prepost_quiz=bool(payload.enable_competency_prepost_quiz),
            competency_rubric_json=clean_rubric,
        )
        session.add(project)
        session.flush()
        if payload.seed_mulberrylane_template:
            for z_key, z_name, z_type, z_desc, z_order, z_signals in MULBERRYLANE_ZONES:
                geom = MULBERRYLANE_ZONE_GEOMETRIES.get(z_key, {})
                session.add(
                    UrbanSimZone(
                        project_id=project.id,
                        zone_key=z_key,
                        name=z_name,
                        zone_type=z_type,
                        description=z_desc,
                        ambient_signals=z_signals,
                        sort_order=z_order,
                        center_x_pct=float(geom["center_x_pct"]) if "center_x_pct" in geom else None,  # type: ignore[arg-type]
                        center_y_pct=float(geom["center_y_pct"]) if "center_y_pct" in geom else None,  # type: ignore[arg-type]
                        fill_color=str(geom["fill_color"]) if "fill_color" in geom else None,
                        polygon_points_json=(
                            json.dumps(geom["polygon_points"])
                            if "polygon_points" in geom
                            else None
                        ),
                    )
                )
            for cp in MULBERRYLANE_CHECKPOINTS:
                session.add(
                    UrbanSimCheckpoint(
                        project_id=project.id,
                        checkpoint_key=str(cp["checkpoint_key"]),
                        name=str(cp["name"]),
                        x_pct=float(cp["x_pct"]),  # type: ignore[arg-type]
                        y_pct=float(cp["y_pct"]),  # type: ignore[arg-type]
                        icon_emoji=str(cp["icon_emoji"]),
                        description_md=str(cp["description_md"]),
                        zone_key=str(cp["zone_key"]),
                        category=str(cp["category"]),
                        sort_order=int(cp["sort_order"]),  # type: ignore[arg-type]
                    )
                )
            for item in MULBERRYLANE_PERSONAS:
                session.add(
                    UrbanSimPersona(
                        project_id=project.id,
                        agent_id=int(item["agent_id"]),
                        full_name=str(item["full_name"]),
                        role_code=str(item["role_code"]),
                        role_title=str(item["role_title"]),
                        department=str(item["department"]),
                        group_type=str(item["group_type"]),
                        software_access_enabled=bool(item["software_access_enabled"]),
                        is_pilot_member=bool(item["is_pilot_member"]),
                        is_active=True,
                        home_zone=str(item["home_zone"]),
                        domain_knowledge_prompt=str(item["domain_knowledge_prompt"]),
                        initial_tasks_json=json.dumps(item["initial_tasks"], ensure_ascii=False),
                        portal_url=clean_portal if item["software_access_enabled"] else None,
                    )
                )
        session.add(
            UrbanSimAtlasConfig(project_id=project.id)
        )
        session.commit()
        session.refresh(project)
        return {"success": True, "project": _serialize_project_summary(session, project)}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Lấy chi tiết dự án kèm tổng quan thống kê."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        return {"success": True, "project": _serialize_project_summary(session, proj)}


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdateRequest):
    """Cập nhật động cấu hình dự án trên DB (áp dụng khi Start hoặc Restart Run mới)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if payload.default_portal_url is not None:
            try:
                proj.default_portal_url = validate_external_url(payload.default_portal_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.name is not None:
            proj.name = payload.name.strip()
        if payload.description is not None:
            proj.description = payload.description.strip()
        if payload.router_type is not None:
            proj.router_type = payload.router_type
        if payload.num_steps is not None:
            proj.num_steps = payload.num_steps
        if payload.tick_seconds is not None:
            proj.tick_seconds = payload.tick_seconds
        if payload.start_time_iso is not None:
            proj.start_time_iso = payload.start_time_iso.strip()
        if payload.max_react_turns is not None:
            proj.max_react_turns = payload.max_react_turns
        if payload.max_cost_usd_per_run is not None:
            proj.max_cost_usd_per_run = payload.max_cost_usd_per_run
        if payload.pilot_mode is not None:
            proj.pilot_mode = payload.pilot_mode
        if "llm_config_id" in payload.model_fields_set:
            proj.llm_config_id = (payload.llm_config_id or "").strip() or None
        if payload.enable_sociological_debrief is not None:
            proj.enable_sociological_debrief = bool(payload.enable_sociological_debrief)
        if payload.enable_competency_prepost_quiz is not None:
            proj.enable_competency_prepost_quiz = bool(payload.enable_competency_prepost_quiz)
        if "competency_rubric_json" in payload.model_fields_set:
            try:
                proj.competency_rubric_json = validate_competency_rubric_json(
                    payload.competency_rubric_json
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.commit()
        session.refresh(proj)
        return {"success": True, "project": _serialize_project_summary(session, proj)}


@router.get("/projects/{project_id}/preflight")
async def get_project_preflight(project_id: str):
    """Kiểm tra mức độ sẵn sàng chạy thực tế (LLM Key, BQL Accounts, Atlas Key, Sandbox L2)."""
    import os

    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        personas = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        atlas = session.get(UrbanSimAtlasConfig, project_id)

        active = [p for p in personas if p.is_active]
        selected = (
            [p for p in active if p.is_pilot_member] or active
            if proj.pilot_mode
            else active
        )
        bql_selected = [p for p in selected if p.software_access_enabled]
        bql_missing_creds = [
            {"agent_id": p.agent_id, "full_name": p.full_name, "role_title": p.role_title}
            for p in bql_selected
            if not ((p.login_username or "").strip() and (p.login_password_enc or "").strip())
        ]
        from agentsociety2.backend.services.platform_resources import (
            resolve_llm_env_override,
        )
        from agentsociety2.config.llm_catalog import (
            DEFAULT_LLM_MODEL,
            DEFAULT_LLM_THINKING,
        )

        llm_overrides = resolve_llm_env_override(session, proj.llm_config_id, ws)
        effective_llm_key = (
            llm_overrides.get("AGENTSOCIETY_LLM_API_KEY")
            or os.getenv("AGENTSOCIETY_LLM_API_KEY", "").strip()
        )
        effective_llm_model = (
            llm_overrides.get("AGENTSOCIETY_LLM_MODEL")
            or os.getenv("AGENTSOCIETY_LLM_MODEL", "").strip()
            or DEFAULT_LLM_MODEL
        )
        effective_coder_model = (
            llm_overrides.get("AGENTSOCIETY_CODER_LLM_MODEL")
            or os.getenv("AGENTSOCIETY_CODER_LLM_MODEL", "").strip()
            or effective_llm_model
        )
        effective_thinking = (
            llm_overrides.get("AGENTSOCIETY_LLM_THINKING")
            or os.getenv("AGENTSOCIETY_LLM_THINKING", "").strip()
            or DEFAULT_LLM_THINKING
        )
        llm_key_ok = bool(effective_llm_key)
        atlas_key_ok = bool(atlas and (atlas.atlas_api_key_enc or "").strip())
        atlas_verified_ok = bool(atlas and atlas.last_verified_at)

        warnings: list[str] = []
        if not llm_key_ok:
            warnings.append("Chưa có API Key LLM (cả cấu hình LLM liên kết và AGENTSOCIETY_LLM_API_KEY đều trống).")
        if not atlas_key_ok:
            warnings.append(
                "Chưa cấu hình EvidenceAtlas API Key — phù hợp chạy thử L1 (mock), nhưng BQL sẽ không hỏi được CSKH thật ở L2."
            )
        elif not atlas_verified_ok:
            warnings.append("Đã nhập Atlas API Key nhưng chưa bấm Kiểm tra kết nối (/api/v1/me).")
        if bql_missing_creds:
            warnings.append(
                f"Còn {len(bql_missing_creds)}/{len(bql_selected)} nhân sự BQL chưa nhập tài khoản QLTN Sandbox."
            )

        return {
            "success": True,
            "preflight": {
                "llm_api_key_present": llm_key_ok,
                "effective_llm_model": effective_llm_model,
                "effective_coder_model": effective_coder_model,
                "effective_llm_thinking": effective_thinking,
                "active_selected_count": len(selected),
                "bql_selected_count": len(bql_selected),
                "bql_credentials_ready": len(bql_selected) - len(bql_missing_creds),
                "bql_missing_credentials": bql_missing_creds,
                "atlas_enabled": bool(atlas and atlas.enabled),
                "atlas_api_key_present": atlas_key_ok,
                "atlas_verified": atlas_verified_ok,
                "ready_for_l1": llm_key_ok and len(selected) > 0,
                "ready_for_l2_sandbox": bool(
                    llm_key_ok
                    and len(bql_selected) > 0
                    and len(bql_missing_creds) == 0
                    and atlas_key_ok
                ),
                "warnings": warnings,
            },
        }


# ==================== PERSONA ENDPOINTS ====================


@router.get("/projects/{project_id}/personas")
async def list_personas(project_id: str):
    """Liệt kê toàn bộ Persona (mật khẩu luôn trả ở dạng masked)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        rows = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .order_by(UrbanSimPersona.agent_id)
        ).all()
        return {"success": True, "items": [_serialize_persona(r) for r in rows]}


@router.post("/projects/{project_id}/personas")
async def create_persona(project_id: str, payload: PersonaCreateRequest):
    """Thêm mới một Persona (BQL hoặc Cư dân) vào dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        existing = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        used_ids = {r.agent_id for r in existing}
        aid = int(payload.agent_id) if payload.agent_id is not None else (max(used_ids, default=0) + 1)
        if aid in used_ids:
            raise HTTPException(
                status_code=409,
                detail=f"agent_id={aid} đã tồn tại trong dự án này.",
            )

        clean_portal: str | None = None
        if payload.portal_url is not None and payload.portal_url.strip():
            try:
                clean_portal = validate_external_url(payload.portal_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        elif payload.group_type == "BQL" and payload.software_access_enabled:
            clean_portal = proj.default_portal_url

        pw_enc: str | None = None
        if payload.login_password and not _is_mask_placeholder(payload.login_password):
            pw_enc = encrypt_secret(payload.login_password, ws)

        sw_enabled = False if payload.group_type == "RESIDENT" else bool(payload.software_access_enabled)
        act_skills = payload.default_activated_skill_ids
        if act_skills is not None and not sw_enabled:
            act_skills = [
                str(s).strip()
                for s in act_skills
                if str(s).strip() and str(s).strip() != "env:DemegoWebPortalEnv@bql-qltn-ops-vn"
            ]
        persona = UrbanSimPersona(
            project_id=project_id,
            agent_id=aid,
            full_name=payload.full_name.strip(),
            role_code=payload.role_code.strip(),
            role_title=payload.role_title.strip(),
            department=payload.department.strip(),
            group_type=payload.group_type,
            software_access_enabled=sw_enabled,
            is_pilot_member=payload.is_pilot_member,
            is_active=payload.is_active,
            home_zone=payload.home_zone.strip() or _default_project_zone(session, project_id),
            avatar_icon=(
                payload.avatar_icon.strip()[:16]
                if payload.avatar_icon and payload.avatar_icon.strip()
                else resolve_default_persona_icon(
                    payload.role_code.strip(), payload.group_type, payload.full_name.strip()
                )
            ),
            domain_knowledge_prompt=payload.domain_knowledge_prompt.strip(),
            initial_tasks_json=json.dumps(payload.initial_tasks, ensure_ascii=False),
            default_activated_skill_ids_json=(
                json.dumps(
                    [str(s).strip() for s in act_skills if str(s).strip()],
                    ensure_ascii=False,
                )
                if act_skills is not None
                else None
            ),
            disabled_skill_ids_json=(
                json.dumps(
                    [str(s).strip() for s in payload.disabled_skill_ids if str(s).strip()],
                    ensure_ascii=False,
                )
                if payload.disabled_skill_ids is not None
                else None
            ),
            profile_traits_json=(
                json.dumps(payload.profile_traits, ensure_ascii=False)
                if payload.profile_traits
                else None
            ),
            portal_url=clean_portal,
            login_username=payload.login_username.strip() if payload.login_username else None,
            login_password_enc=pw_enc,
        )
        session.add(persona)
        session.commit()
        session.refresh(persona)
        return {"success": True, "persona": _serialize_persona(persona)}


@router.get("/available-skills")
async def list_available_urban_sim_skills():
    """Liệt kê toàn bộ Agent Skill (/skills + built-in + env UrbanSim) để gắn cho từng Persona."""
    from agentsociety2.agent.base.skill_registry import get_skill_registry
    from agentsociety2.backend.path_security import custom_skills_root
    from agentsociety2.backend.routers.agent_skills import _ensure_env_skills_scanned

    ws = _ws_root()
    reg = get_skill_registry()
    reg.scan_builtin()
    c_root = custom_skills_root(str(ws))
    if c_root.is_dir():
        reg.scan_custom(c_root)
    _ensure_env_skills_scanned(reg)

    # Fallback scan for UrbanSim env skills in case env registry hasn't loaded modules yet
    contrib_skills_root = Path(__file__).resolve().parents[2] / "contrib" / "env" / "urban_sim_skills"
    if (contrib_skills_root / "bql").is_dir():
        reg.scan_env(contrib_skills_root / "bql", "DemegoWebPortalEnv")
    if (contrib_skills_root / "resident").is_dir():
        reg.scan_env(contrib_skills_root / "resident", "UrbanCommAndIncidentEnv")

    items = []
    for desc in sorted(reg.list_all(), key=lambda d: (d.source != "env", d.source != "custom", d.name.lower())):
        req_sw = desc.skill_id == "env:DemegoWebPortalEnv@bql-qltn-ops-vn"
        rec_group = (
            "BQL"
            if desc.skill_id == "env:DemegoWebPortalEnv@bql-qltn-ops-vn"
            else ("RESIDENT" if desc.skill_id == "env:UrbanCommAndIncidentEnv@urban-resident-vn" else "ALL")
        )
        items.append(
            {
                "skill_id": desc.skill_id,
                "name": desc.name,
                "description": desc.description,
                "source": desc.source,
                "source_label": desc.source_label,
                "requires_software_access": req_sw,
                "recommended_group": rec_group,
            }
        )
    return {"success": True, "items": items}


@router.get("/scenario-brief-template")
async def get_scenario_brief_template():
    """Trả về mẫu Thực trạng Khu đô thị chi tiết làm gợi ý nạp trực tiếp vào bối cảnh mô phỏng."""
    return {
        "success": True,
        "template": MULBERRYLANE_SCENARIO_BRIEF,
    }


@router.post("/projects/{project_id}/sync-accounting-persona")
async def sync_accounting_persona(project_id: str):
    """Bổ sung an toàn nhân sự Kế toán Công nợ (BQL_ACCOUNTANT) mà không ghi đè persona hiện hữu."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        existing = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        already = next(
            (p for p in existing if (p.role_code or "").strip().upper() == "BQL_ACCOUNTANT"),
            None,
        )
        if already is not None:
            return {
                "success": True,
                "created": False,
                "persona": _serialize_persona(already),
            }

        used_ids = {int(r.agent_id) for r in existing}
        preferred_id = int(ACCOUNTING_PERSONA_TEMPLATE["agent_id"])
        target_id = preferred_id if preferred_id not in used_ids else (max(used_ids, default=21) + 1)

        tpl = ACCOUNTING_PERSONA_TEMPLATE
        persona = UrbanSimPersona(
            project_id=project_id,
            agent_id=target_id,
            full_name=str(tpl["full_name"]),
            role_code=str(tpl["role_code"]),
            role_title=str(tpl["role_title"]),
            department=str(tpl["department"]),
            group_type=str(tpl["group_type"]),
            software_access_enabled=bool(tpl["software_access_enabled"]),
            is_pilot_member=bool(tpl["is_pilot_member"]),
            is_active=True,
            home_zone=str(tpl["home_zone"]),
            domain_knowledge_prompt=str(tpl["domain_knowledge_prompt"]),
            initial_tasks_json=json.dumps(tpl["initial_tasks"], ensure_ascii=False),
            portal_url=proj.default_portal_url,
            login_username=None,
            login_password_enc=None,
        )
        session.add(persona)
        session.commit()
        session.refresh(persona)
        return {
            "success": True,
            "created": True,
            "persona": _serialize_persona(persona),
        }


@router.patch("/projects/{project_id}/personas/{persona_id}")
async def update_persona(project_id: str, persona_id: str, payload: PersonaUpdateRequest):
    """Cập nhật Persona & tài khoản QLTN (chỉ mã hóa lại mật khẩu khi có nhập mật khẩu mới)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        persona = session.get(UrbanSimPersona, persona_id)
        if persona is None or persona.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Persona.")

        if payload.full_name is not None:
            persona.full_name = payload.full_name.strip()
        if payload.role_code is not None:
            persona.role_code = payload.role_code.strip()
        if payload.role_title is not None:
            persona.role_title = payload.role_title.strip()
        if payload.department is not None:
            persona.department = payload.department.strip()
        if payload.group_type is not None:
            persona.group_type = payload.group_type
            if payload.group_type == "RESIDENT":
                persona.software_access_enabled = False
        if payload.software_access_enabled is not None and persona.group_type != "RESIDENT":
            persona.software_access_enabled = bool(payload.software_access_enabled)
        if payload.is_pilot_member is not None:
            persona.is_pilot_member = bool(payload.is_pilot_member)
        if payload.is_active is not None:
            persona.is_active = bool(payload.is_active)
        if payload.home_zone is not None:
            persona.home_zone = payload.home_zone.strip() or _default_project_zone(session, project_id)
        if "avatar_icon" in payload.model_fields_set:
            clean_icon = (payload.avatar_icon or "").strip()[:16]
            persona.avatar_icon = clean_icon or resolve_default_persona_icon(
                persona.role_code, persona.group_type, persona.full_name
            )
        if payload.domain_knowledge_prompt is not None:
            persona.domain_knowledge_prompt = payload.domain_knowledge_prompt.strip()
        if payload.initial_tasks is not None:
            persona.initial_tasks_json = json.dumps(
                [str(t).strip() for t in payload.initial_tasks if str(t).strip()],
                ensure_ascii=False,
            )
        if "default_activated_skill_ids" in payload.model_fields_set:
            if payload.default_activated_skill_ids is None:
                persona.default_activated_skill_ids_json = None
            else:
                persona.default_activated_skill_ids_json = json.dumps(
                    [str(s).strip() for s in payload.default_activated_skill_ids if str(s).strip()],
                    ensure_ascii=False,
                )
        if "disabled_skill_ids" in payload.model_fields_set:
            if payload.disabled_skill_ids is None:
                persona.disabled_skill_ids_json = None
            else:
                persona.disabled_skill_ids_json = json.dumps(
                    [str(s).strip() for s in payload.disabled_skill_ids if str(s).strip()],
                    ensure_ascii=False,
                )
        if "profile_traits" in payload.model_fields_set:
            if not payload.profile_traits:
                persona.profile_traits_json = None
            else:
                persona.profile_traits_json = json.dumps(
                    payload.profile_traits,
                    ensure_ascii=False,
                )
        if payload.group_type == "RESIDENT" or not persona.software_access_enabled:
            if getattr(persona, "default_activated_skill_ids_json", None):
                cur_act = _parse_json_list(persona.default_activated_skill_ids_json)
                cleaned_act = [
                    str(s) for s in cur_act if str(s) != "env:DemegoWebPortalEnv@bql-qltn-ops-vn"
                ]
                persona.default_activated_skill_ids_json = json.dumps(
                    cleaned_act, ensure_ascii=False
                )
        if payload.portal_url is not None:
            if payload.portal_url.strip():
                try:
                    persona.portal_url = validate_external_url(payload.portal_url)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            else:
                persona.portal_url = None
        if payload.login_username is not None:
            persona.login_username = payload.login_username.strip() or None
        if payload.clear_password:
            persona.login_password_enc = None
        elif payload.login_password is not None and not _is_mask_placeholder(payload.login_password):
            persona.login_password_enc = encrypt_secret(payload.login_password, ws)

        persona.updated_at = _utcnow_iso()
        session.add(persona)
        session.commit()
        session.refresh(persona)
        return {"success": True, "persona": _serialize_persona(persona)}


@router.delete("/projects/{project_id}/personas/{persona_id}")
async def delete_persona(project_id: str, persona_id: str):
    """Xóa một Persona khỏi dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        persona = session.get(UrbanSimPersona, persona_id)
        if persona is None or persona.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Persona.")
        session.delete(persona)
        session.commit()
        return {"success": True, "deleted_id": persona_id}


# ==================== ATLAS & GUARDRAIL ENDPOINTS ====================


@router.get("/projects/{project_id}/atlas")
async def get_atlas_config(project_id: str):
    """Đọc cấu hình EvidenceAtlas & Guardrail (API Key luôn trả ở dạng masked)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        cfg = session.get(UrbanSimAtlasConfig, project_id)
        return {"success": True, "atlas": _serialize_atlas(cfg, project_id)}


@router.put("/projects/{project_id}/atlas")
async def update_atlas_config(project_id: str, payload: AtlasConfigUpdateRequest):
    """Cập nhật cấu hình EvidenceAtlas & Sandbox Guardrail vào DB."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    try:
        clean_url = validate_external_url(payload.atlas_api_url).rstrip("/")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        cfg = session.get(UrbanSimAtlasConfig, project_id)
        if cfg is None:
            cfg = UrbanSimAtlasConfig(project_id=project_id)

        cfg.enabled = bool(payload.enabled)
        cfg.atlas_api_url = clean_url
        if payload.clear_api_key:
            cfg.atlas_api_key_enc = None
            cfg.last_verified_at = None
        elif payload.atlas_api_key is not None and not _is_mask_placeholder(payload.atlas_api_key):
            cfg.atlas_api_key_enc = encrypt_secret(payload.atlas_api_key, ws)

        cfg.actor_persona = payload.actor_persona
        cfg.source_mode = payload.source_mode
        cfg.attach_screenshot_on_ask = bool(payload.attach_screenshot_on_ask)
        cfg.quota_per_min = int(payload.quota_per_min)
        cfg.max_asks_per_tick = int(payload.max_asks_per_tick)
        cfg.guardrail_mode = payload.guardrail_mode
        cfg.record_prefix = payload.record_prefix.strip() or "[SIM-BQL]"
        if payload.blocked_keywords is not None:
            cfg.blocked_keywords_json = json.dumps(
                [str(k).strip() for k in payload.blocked_keywords if str(k).strip()],
                ensure_ascii=False,
            )
        cfg.updated_at = _utcnow_iso()
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return {"success": True, "atlas": _serialize_atlas(cfg, project_id)}


@router.post("/projects/{project_id}/atlas/test-connection")
async def test_atlas_connection(
    project_id: str, payload: AtlasTestConnectionRequest | None = None
):
    """Kiểm tra kết nối EvidenceAtlas qua GET /api/v1/me (kiểm SSRF & đọc bound_project_id)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    body = payload or AtlasTestConnectionRequest()

    with Session(engine) as session:
        _require_project(session, project_id)
        cfg = session.get(UrbanSimAtlasConfig, project_id)
        raw_url = (body.atlas_api_url or (cfg.atlas_api_url if cfg else "https://atlas.demego.vn")).strip()
        try:
            target_url = validate_external_url(raw_url).rstrip("/")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        api_key = ""
        if body.atlas_api_key and not _is_mask_placeholder(body.atlas_api_key):
            api_key = body.atlas_api_key.strip()
        elif cfg and cfg.atlas_api_key_enc:
            api_key = decrypt_secret(cfg.atlas_api_key_enc, ws)

        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Chưa có EvidenceAtlas API Key để kiểm tra kết nối.",
            )

    me_endpoint = f"{target_url}/api/v1/me"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(me_endpoint, headers={"X-API-KEY": api_key})
    except httpx.TimeoutException:
        return {
            "success": False,
            "ok": False,
            "status_code": 504,
            "error": "Hết thời gian chờ khi kết nối tới EvidenceAtlas (/api/v1/me).",
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "ok": False,
            "status_code": 502,
            "error": f"Không kết nối được tới máy chủ EvidenceAtlas: {exc}",
        }

    if resp.status_code >= 400:
        return {
            "success": False,
            "ok": False,
            "status_code": resp.status_code,
            "error": f"EvidenceAtlas từ chối kết nối (HTTP {resp.status_code}): {resp.text[:300]}",
        }

    try:
        data = resp.json()
    except ValueError:
        return {
            "success": False,
            "ok": False,
            "status_code": 502,
            "error": "Phản hồi từ /api/v1/me không phải JSON hợp lệ.",
        }

    bound_project_id = str(data.get("bound_project_id") or data.get("project_id") or "")
    project_name = str(data.get("project_name") or "")
    scopes = data.get("scopes") if isinstance(data.get("scopes"), list) else []
    isolation_mode = str(data.get("isolation_mode") or "")
    verified_at = _utcnow_iso()

    with Session(engine) as session:
        cfg = session.get(UrbanSimAtlasConfig, project_id)
        if cfg is not None:
            cfg.last_verified_at = verified_at
            cfg.last_verified_project_id = bound_project_id
            cfg.last_verified_project_name = project_name
            cfg.last_verified_scopes_json = json.dumps(scopes, ensure_ascii=False)
            cfg.updated_at = verified_at
            session.add(cfg)
            session.commit()
            session.refresh(cfg)

    return {
        "success": True,
        "ok": True,
        "bound_project_id": bound_project_id,
        "project_name": project_name,
        "scopes": scopes,
        "isolation_mode": isolation_mode,
        "verified_at": verified_at,
    }


# ==================== ZONES, DIGITAL MAP & CHECKPOINT ENDPOINTS ====================


def _require_digital_map_or_409(session: Session, proj: UrbanSimProject) -> None:
    if not project_has_digital_map(session, proj):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DIGITAL_MAP_REQUIRED",
                "message": "Cần khởi tạo Bản đồ Số (tải ảnh mặt bằng 2D hoặc vẽ/tạo ít nhất 1 Khu vực Polygon) trước khi tạo Chốt/Pin.",
            },
        )


def _require_no_active_runs_or_409(session: Session, project_id: str) -> None:
    runs = session.exec(
        select(UrbanSimRun).where(UrbanSimRun.project_id == project_id)
    ).all()
    active = [r.id for r in runs if str(r.status or "").upper() in {"STARTING", "RUNNING", "PAUSING", "RESUMING"}]
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Đang có ca mô phỏng hoạt động ({', '.join(active)}). Vui lòng tạm dừng trước khi thay thế cấu trúc bản đồ.",
        )


@router.get("/projects/{project_id}/zones")
async def list_zones(project_id: str):
    """Liệt kê danh sách các khu vực (Zone Topology & Polygon) kèm trạng thái Bản đồ Số."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        rows = session.exec(
            select(UrbanSimZone)
            .where(UrbanSimZone.project_id == project_id)
            .order_by(UrbanSimZone.sort_order)
        ).all()
        personas = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        counts_by_zone: dict[str, int] = {}
        for p in personas:
            zk = (p.home_zone or "").strip()
            if zk:
                counts_by_zone[zk] = counts_by_zone.get(zk, 0) + 1
        return {
            "success": True,
            "has_zone_map_image": bool(proj.zone_map_image_rel),
            "has_digital_map": project_has_digital_map(session, proj),
            "map_prompt": getattr(proj, "map_prompt", None) or "",
            "map_width": getattr(proj, "map_width", None),
            "map_height": getattr(proj, "map_height", None),
            "map_aspect_ratio": getattr(proj, "map_aspect_ratio", None) or 1.6,
            "map_image_version": int(getattr(proj, "map_image_version", 0) or 0),
            "items": [
                _serialize_zone(z, counts_by_zone.get(z.zone_key, 0)) for z in rows
            ],
        }


@router.post("/projects/{project_id}/zones")
async def create_zone(project_id: str, payload: ZoneCreateRequest):
    """Thêm Zone mới cho dự án (hỗ trợ tọa độ tâm & Polygon)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    norm_pts: list[list[float]] | None = None
    cx = payload.center_x_pct
    cy = payload.center_y_pct
    if payload.polygon_points is not None:
        try:
            norm_pts, auto_cx, auto_cy = validate_and_normalize_polygon(payload.polygon_points)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if cx is None:
            cx = auto_cx
        if cy is None:
            cy = auto_cy

    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        key_norm = _normalize_zone_key(payload.zone_key)
        dup = session.exec(
            select(UrbanSimZone).where(
                UrbanSimZone.project_id == project_id,
                UrbanSimZone.zone_key == key_norm,
            )
        ).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f"Zone '{key_norm}' đã tồn tại.")
        zone = UrbanSimZone(
            project_id=project_id,
            zone_key=key_norm,
            name=payload.name.strip(),
            zone_type=payload.zone_type,
            description=payload.description.strip(),
            ambient_signals=payload.ambient_signals.strip(),
            sort_order=payload.sort_order,
            center_x_pct=cx,
            center_y_pct=cy,
            polygon_points_json=json.dumps(norm_pts) if norm_pts is not None else None,
            fill_color=(payload.fill_color or "").strip() or None,
        )
        session.add(zone)
        session.flush()
        recompute_checkpoint_zones(session, project_id)
        session.commit()
        session.refresh(zone)
        return {
            "success": True,
            "zone": _serialize_zone(zone, 0),
        }


@router.post("/projects/{project_id}/zones/map-image")
async def upload_zone_map_image(project_id: str, file: UploadFile = File(...)):
    """Upload ảnh sơ đồ 2D mặt bằng khu đô thị (atomic content-addressed, kiểm decompression bomb)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    data = await file.read(_MAX_MAP_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="File ảnh tải lên bị rỗng.")
    if len(data) > _MAX_MAP_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Kích thước ảnh sơ đồ vượt quá giới hạn 5 MB.",
        )
    ext, _media = _detect_raster_magic(data)
    try:
        img_w, img_h = parse_image_dimensions(data, ext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    new_ratio = round(img_w / max(1, img_h), 4)
    hash8 = hashlib.sha256(data).hexdigest()[:8]
    filename = f"{project_id}_{hash8}.{ext}"
    dest = resolve_urban_sim_map_image(ws, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(f".tmp_{uuid.uuid4().hex[:8]}_{filename}")

    engine = get_engine(ws)
    old_rel: str | None = None
    aspect_ratio_changed = False
    try:
        tmp_dest.write_bytes(data)
        os.replace(tmp_dest, dest)
    except OSError as exc:
        tmp_dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không thể ghi tệp ảnh lên ổ đĩa: {exc}") from exc

    with Session(engine) as session:
        proj = _require_project(session, project_id)
        old_rel = proj.zone_map_image_rel
        old_ratio = float(getattr(proj, "map_aspect_ratio", None) or 0.0)
        has_shapes = bool(
            session.exec(
                select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project_id)
            ).first()
            or any(
                parse_polygon_json(getattr(z, "polygon_points_json", None)) is not None
                for z in session.exec(
                    select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
                ).all()
            )
        )
        if has_shapes and old_ratio > 0 and abs(new_ratio - old_ratio) / old_ratio > 0.10:
            aspect_ratio_changed = True

        proj.zone_map_image_rel = filename
        proj.map_width = img_w
        proj.map_height = img_h
        proj.map_aspect_ratio = new_ratio
        proj.map_image_version = int(getattr(proj, "map_image_version", 0) or 0) + 1
        proj.map_image_updated_at = _utcnow_iso()
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.commit()
        session.refresh(proj)

    if old_rel and old_rel != filename:
        try:
            resolve_urban_sim_map_image(ws, old_rel).unlink(missing_ok=True)
        except HTTPException:
            pass

    return {
        "success": True,
        "filename": filename,
        "size_bytes": len(data),
        "map_width": img_w,
        "map_height": img_h,
        "map_aspect_ratio": new_ratio,
        "map_image_version": int(proj.map_image_version),
        "aspect_ratio_changed": aspect_ratio_changed,
    }


@router.get("/projects/{project_id}/zones/map-image")
async def get_zone_map_image(project_id: str):
    """Trả ảnh sơ đồ 2D đã upload (kèm header X-Content-Type-Options: nosniff)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if not proj.zone_map_image_rel:
            raise HTTPException(status_code=404, detail="Dự án chưa tải lên ảnh sơ đồ 2D.")
        img_path = resolve_urban_sim_map_image(ws, proj.zone_map_image_rel)
        if not img_path.is_file():
            raise HTTPException(status_code=404, detail="Không tìm thấy file ảnh sơ đồ trên ổ đĩa.")
        return FileResponse(
            img_path,
            headers={"X-Content-Type-Options": "nosniff"},
        )


@router.delete("/projects/{project_id}/zones/map-image")
async def delete_zone_map_image(
    project_id: str,
    clear_orphaned_checkpoints: bool = Query(False),
):
    """Xóa ảnh sơ đồ 2D tùy chọn (bảo vệ bất biến Bản đồ Số khi còn Chốt và không còn Polygon)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    old_rel: str | None = None
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        cps = session.exec(
            select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project_id)
        ).all()
        zones = session.exec(
            select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
        ).all()
        has_polygon_zone = any(
            parse_polygon_json(getattr(z, "polygon_points_json", None)) is not None
            for z in zones
        )
        if cps and not has_polygon_zone:
            if not clear_orphaned_checkpoints:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DIGITAL_MAP_REQUIRED",
                        "message": f"Không thể xóa ảnh 2D khi chưa có khu vực Polygon nào và đang có {len(cps)} Chốt/Pin (trừ khi clear_orphaned_checkpoints=true).",
                    },
                )
            for cp in cps:
                session.delete(cp)

        if proj.zone_map_image_rel:
            old_rel = proj.zone_map_image_rel
            proj.zone_map_image_rel = None
            proj.map_width = None
            proj.map_height = None
            proj.map_image_version = int(getattr(proj, "map_image_version", 0) or 0) + 1
            proj.map_image_updated_at = _utcnow_iso()
            proj.updated_at = _utcnow_iso()
            session.add(proj)
        session.commit()

    if old_rel:
        try:
            resolve_urban_sim_map_image(ws, old_rel).unlink(missing_ok=True)
        except HTTPException:
            pass
    return {"success": True}


@router.patch("/projects/{project_id}/zones/{zone_id}")
async def update_zone(project_id: str, zone_id: str, payload: ZoneUpdateRequest):
    """Cập nhật Zone (cascade đổi zone_key sang Persona & Checkpoint; recompute Point-in-Polygon)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        zone = session.get(UrbanSimZone, zone_id)
        if zone is None or zone.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Zone.")

        old_key = zone.zone_key
        poly_changed = False
        if payload.zone_key is not None:
            new_key = _normalize_zone_key(payload.zone_key)
            if new_key != old_key:
                dup = session.exec(
                    select(UrbanSimZone).where(
                        UrbanSimZone.project_id == project_id,
                        UrbanSimZone.zone_key == new_key,
                        UrbanSimZone.id != zone.id,
                    )
                ).first()
                if dup is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Mã khu vực '{new_key}' đã tồn tại trong dự án.",
                    )
                zone.zone_key = new_key
                attached_personas = session.exec(
                    select(UrbanSimPersona).where(
                        UrbanSimPersona.project_id == project_id,
                        UrbanSimPersona.home_zone == old_key,
                    )
                ).all()
                for p in attached_personas:
                    p.home_zone = new_key
                    p.updated_at = _utcnow_iso()
                    session.add(p)
                attached_cps = session.exec(
                    select(UrbanSimCheckpoint).where(
                        UrbanSimCheckpoint.project_id == project_id,
                        UrbanSimCheckpoint.zone_key == old_key,
                    )
                ).all()
                for cp in attached_cps:
                    cp.zone_key = new_key
                    cp.updated_at = _utcnow_iso()
                    session.add(cp)

        if payload.name is not None:
            clean_name = payload.name.strip()
            if not clean_name:
                raise HTTPException(status_code=400, detail="Tên khu vực không được để trống.")
            zone.name = clean_name
        if payload.zone_type is not None:
            zone.zone_type = payload.zone_type
        if payload.description is not None:
            zone.description = payload.description.strip()
        if payload.ambient_signals is not None:
            zone.ambient_signals = payload.ambient_signals.strip()
        if payload.sort_order is not None:
            zone.sort_order = int(payload.sort_order)
        if payload.fill_color is not None:
            zone.fill_color = payload.fill_color.strip() or None
        if "polygon_points" in payload.model_fields_set:
            if payload.polygon_points is None:
                zone.polygon_points_json = None
                poly_changed = True
            else:
                try:
                    norm_pts, auto_cx, auto_cy = validate_and_normalize_polygon(payload.polygon_points)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                zone.polygon_points_json = json.dumps(norm_pts)
                zone.center_x_pct = auto_cx
                zone.center_y_pct = auto_cy
                poly_changed = True
        if payload.center_x_pct is not None:
            zone.center_x_pct = round(float(payload.center_x_pct), 2)
        if payload.center_y_pct is not None:
            zone.center_y_pct = round(float(payload.center_y_pct), 2)

        session.add(zone)
        session.flush()
        if poly_changed:
            recompute_checkpoint_zones(session, project_id)
        session.commit()
        session.refresh(zone)

        persona_cnt = len(
            session.exec(
                select(UrbanSimPersona).where(
                    UrbanSimPersona.project_id == project_id,
                    UrbanSimPersona.home_zone == zone.zone_key,
                )
            ).all()
        )
        return {
            "success": True,
            "zone": _serialize_zone(zone, persona_cnt),
        }


@router.put("/projects/{project_id}/zones/{zone_id}/personas")
async def assign_zone_personas(
    project_id: str,
    zone_id: str,
    payload: ZoneAssignPersonasRequest,
):
    """Gắn/chuyển nguyên tử danh sách Nhân sự & Cư dân thuộc Khu vực (home_zone = zone.zone_key)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        zone = session.get(UrbanSimZone, zone_id)
        if zone is None or zone.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Khu vực.")

        all_zones = session.exec(
            select(UrbanSimZone)
            .where(UrbanSimZone.project_id == project_id)
            .order_by(UrbanSimZone.sort_order, UrbanSimZone.zone_key)
        ).all()
        other_zones = [z for z in all_zones if z.id != zone.id]
        target_ids = {str(pid).strip() for pid in payload.persona_ids if str(pid).strip()}

        all_personas = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        valid_persona_ids = {p.id for p in all_personas}
        unknown = target_ids - valid_persona_ids
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Danh sách nhân sự chứa ID không tồn tại trong dự án: {', '.join(sorted(unknown))}",
            )

        leaving = [
            p for p in all_personas if p.home_zone == zone.zone_key and p.id not in target_ids
        ]
        fallback_key: str | None = None
        if leaving:
            if not other_zones:
                raise HTTPException(
                    status_code=409,
                    detail="Không thể bỏ gắn nhân sự khỏi khu vực duy nhất của dự án. Hãy tạo thêm ít nhất 1 khu vực khác trước.",
                )
            req_fb = (payload.fallback_zone_key or "").strip().upper()
            if req_fb and any(z.zone_key == req_fb for z in other_zones):
                fallback_key = req_fb
            else:
                fallback_key = other_zones[0].zone_key

        now = _utcnow_iso()
        assigned_ids: list[str] = []
        reassigned_out_count = 0
        for p in all_personas:
            if p.id in target_ids:
                if p.home_zone != zone.zone_key:
                    p.home_zone = zone.zone_key
                    p.updated_at = now
                    session.add(p)
                assigned_ids.append(p.id)
            elif p.home_zone == zone.zone_key and fallback_key:
                p.home_zone = fallback_key
                p.updated_at = now
                session.add(p)
                reassigned_out_count += 1

        session.commit()
        session.refresh(zone)
        return {
            "success": True,
            "zone": _serialize_zone(zone, len(assigned_ids)),
            "assigned_persona_ids": assigned_ids,
            "reassigned_out_count": reassigned_out_count,
            "fallback_zone_key": fallback_key,
        }


@router.delete("/projects/{project_id}/zones/{zone_id}")
async def delete_zone(
    project_id: str,
    zone_id: str,
    reassign_to: str | None = None,
    clear_orphaned_checkpoints: bool = Query(False),
):
    """Xóa Zone khỏi dự án (bảo vệ home_zone Persona và bất biến Bản đồ Số khi còn Chốt/Pin)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        zone = session.get(UrbanSimZone, zone_id)
        if zone is None or zone.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Zone.")

        attached = session.exec(
            select(UrbanSimPersona).where(
                UrbanSimPersona.project_id == project_id,
                UrbanSimPersona.home_zone == zone.zone_key,
            )
        ).all()
        reassigned_count = 0
        if attached:
            target_key = (reassign_to or "").strip().upper()
            if not target_key:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Không thể xóa '{zone.name}' ({zone.zone_key}) vì đang có {len(attached)} "
                        "nhân sự/cư dân thuộc khu vực này. Hãy chọn khu vực thay thế để chuyển trước khi xóa."
                    ),
                )
            target_zone = session.exec(
                select(UrbanSimZone).where(
                    UrbanSimZone.project_id == project_id,
                    UrbanSimZone.zone_key == target_key,
                )
            ).first()
            if target_zone is None or target_zone.id == zone.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Khu vực chuyển đến '{target_key}' không hợp lệ.",
                )
            for p in attached:
                p.home_zone = target_zone.zone_key
                p.updated_at = _utcnow_iso()
                session.add(p)
            reassigned_count = len(attached)

        # Check dynamically whether deleting this zone leaves zero Digital Map while checkpoints exist
        cps = session.exec(
            select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project_id)
        ).all()
        if cps and not (proj.zone_map_image_rel or "").strip():
            other_zones = session.exec(
                select(UrbanSimZone).where(
                    UrbanSimZone.project_id == project_id,
                    UrbanSimZone.id != zone.id,
                )
            ).all()
            still_has_polygon = any(
                parse_polygon_json(getattr(z, "polygon_points_json", None)) is not None
                for z in other_zones
            )
            if not still_has_polygon:
                if not clear_orphaned_checkpoints:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "DIGITAL_MAP_REQUIRED",
                            "message": f"Không thể xóa khu vực Polygon cuối cùng khi dự án còn {len(cps)} Chốt/Pin (trừ khi chọn clear_orphaned_checkpoints=true).",
                        },
                    )
                for cp in cps:
                    session.delete(cp)

        session.delete(zone)
        session.flush()
        recompute_checkpoint_zones(session, project_id)
        session.commit()
        return {
            "success": True,
            "deleted_id": zone_id,
            "reassigned_personas": reassigned_count,
        }


@router.patch("/projects/{project_id}/digital-map")
async def update_digital_map_meta(project_id: str, payload: DigitalMapMetaPatchRequest):
    """Cập nhật prompt mô tả tổng thể & tỷ lệ khung của Bản đồ Số."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if "map_prompt" in payload.model_fields_set:
            proj.map_prompt = (payload.map_prompt or "").strip()
        if payload.map_aspect_ratio is not None:
            proj.map_aspect_ratio = round(float(payload.map_aspect_ratio), 4)
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.commit()
        session.refresh(proj)
        return {"success": True, "project": _serialize_project_summary(session, proj)}


@router.get("/projects/{project_id}/digital-map/geojson")
async def export_digital_map_geojson(project_id: str):
    """Xuất Bản đồ Số (Polygon Khu vực + Point Chốt/Pin) theo chuẩn GeoJSON FeatureCollection."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        zones = session.exec(
            select(UrbanSimZone)
            .where(UrbanSimZone.project_id == project_id)
            .order_by(UrbanSimZone.sort_order)
        ).all()
        cps = session.exec(
            select(UrbanSimCheckpoint)
            .where(UrbanSimCheckpoint.project_id == project_id)
            .order_by(UrbanSimCheckpoint.sort_order, UrbanSimCheckpoint.name)  # type: ignore[arg-type]
        ).all()
        return build_digital_map_geojson(proj, zones, cps)


@router.post("/projects/{project_id}/digital-map/generate")
async def generate_digital_map(project_id: str, payload: DigitalMapGenerateRequest):
    """Dùng LLM dự án (Vision fail-fast -> Text fallback minh bạch) sinh bản nháp Polygon Bản đồ Số."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        draft = await generate_digital_map_draft(
            session,
            proj,
            ws,
            map_prompt=payload.map_prompt,
            use_image=payload.use_image,
            max_zones=payload.max_zones,
        )
        return {"success": True, **draft}


@router.post("/projects/{project_id}/digital-map/apply")
async def apply_digital_map(project_id: str, payload: DigitalMapApplyRequest):
    """Áp dụng bản nháp Bản đồ Số (MERGE bảo toàn Persona hoặc REPLACE có kiểm soát active run & remap home_zone)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    validated_zones: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for idx, item in enumerate(payload.zones):
        zkey = _normalize_zone_key(item.zone_key)
        if zkey in seen_keys:
            raise HTTPException(status_code=400, detail=f"Trùng zone_key '{zkey}' trong danh sách áp dụng.")
        seen_keys.add(zkey)
        try:
            pts, cx, cy = validate_and_normalize_polygon(item.polygon_points)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Polygon của '{zkey}' không hợp lệ: {exc}",
            ) from exc
        validated_zones.append(
            {
                "zone_key": zkey,
                "name": item.name.strip(),
                "zone_type": item.zone_type,
                "description": item.description.strip(),
                "ambient_signals": item.ambient_signals.strip(),
                "fill_color": (item.fill_color or "").strip() or None,
                "polygon_points": pts,
                "center_x_pct": cx,
                "center_y_pct": cy,
                "sort_order": int(item.sort_order or (idx + 1)),
            }
        )

    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if payload.mode == "REPLACE":
            _require_no_active_runs_or_409(session, project_id)

        existing_zones = session.exec(
            select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
        ).all()
        by_key = {z.zone_key: z for z in existing_zones}

        if payload.mode == "REPLACE":
            target_keys = {vz["zone_key"] for vz in validated_zones}
            for ez in existing_zones:
                if ez.zone_key not in target_keys:
                    session.delete(ez)
            session.flush()

        for vz in validated_zones:
            ez = by_key.get(vz["zone_key"])
            if ez is not None:
                ez.name = vz["name"]
                ez.zone_type = vz["zone_type"]
                ez.description = vz["description"] or ez.description
                ez.ambient_signals = vz["ambient_signals"] or ez.ambient_signals
                ez.fill_color = vz["fill_color"] or ez.fill_color
                ez.polygon_points_json = json.dumps(vz["polygon_points"])
                ez.center_x_pct = vz["center_x_pct"]
                ez.center_y_pct = vz["center_y_pct"]
                ez.sort_order = vz["sort_order"]
                session.add(ez)
            else:
                session.add(
                    UrbanSimZone(
                        project_id=project_id,
                        zone_key=vz["zone_key"],
                        name=vz["name"],
                        zone_type=vz["zone_type"],
                        description=vz["description"],
                        ambient_signals=vz["ambient_signals"],
                        fill_color=vz["fill_color"],
                        polygon_points_json=json.dumps(vz["polygon_points"]),
                        center_x_pct=vz["center_x_pct"],
                        center_y_pct=vz["center_y_pct"],
                        sort_order=vz["sort_order"],
                    )
                )

        if payload.map_prompt is not None:
            proj.map_prompt = payload.map_prompt.strip()
        if payload.aspect_ratio is not None and not proj.zone_map_image_rel:
            proj.map_aspect_ratio = round(float(payload.aspect_ratio), 4)
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.flush()

        # Remap orphaned Persona home_zones in REPLACE mode
        valid_zone_keys = {vz["zone_key"] for vz in validated_zones}
        if payload.mode == "REPLACE" and validated_zones:
            fallback_zone_key = validated_zones[0]["zone_key"]
            personas = session.exec(
                select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
            ).all()
            for per in personas:
                if (per.home_zone or "").strip() not in valid_zone_keys:
                    per.home_zone = fallback_zone_key
                    per.updated_at = _utcnow_iso()
                    session.add(per)

        recompute_checkpoint_zones(session, project_id)
        session.commit()

        final_zones = session.exec(
            select(UrbanSimZone)
            .where(UrbanSimZone.project_id == project_id)
            .order_by(UrbanSimZone.sort_order)
        ).all()
        personas = session.exec(
            select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
        ).all()
        counts_by_zone: dict[str, int] = {}
        for p in personas:
            zk = (p.home_zone or "").strip()
            if zk:
                counts_by_zone[zk] = counts_by_zone.get(zk, 0) + 1
        return {
            "success": True,
            "mode": payload.mode,
            "has_digital_map": project_has_digital_map(session, proj),
            "zones": [_serialize_zone(z, counts_by_zone.get(z.zone_key, 0)) for z in final_zones],
        }


@router.put("/projects/{project_id}/zones/layout")
async def save_zones_layout(project_id: str, payload: ZonesLayoutRequest):
    """Lưu đồng loạt tọa độ Polygon / Tâm / Màu của các Zone trong 1 transaction atomic."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        zones_by_id = {
            z.id: z
            for z in session.exec(
                select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
            ).all()
        }
        # Validate ALL entries before mutating/committing (atomic rollback on any invalid item)
        prepared: list[tuple[UrbanSimZone, str | None, float | None, float | None, str | None]] = []
        for item in payload.zones:
            z = zones_by_id.get(item.id)
            if z is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy Zone ID '{item.id}' trong dự án.",
                )
            next_poly_json = z.polygon_points_json
            next_cx = item.center_x_pct if item.center_x_pct is not None else z.center_x_pct
            next_cy = item.center_y_pct if item.center_y_pct is not None else z.center_y_pct
            if "polygon_points" in item.model_fields_set:
                if item.polygon_points is None:
                    next_poly_json = None
                else:
                    try:
                        norm_pts, auto_cx, auto_cy = validate_and_normalize_polygon(item.polygon_points)
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Polygon của '{z.zone_key}' không hợp lệ: {exc}",
                        ) from exc
                    next_poly_json = json.dumps(norm_pts)
                    next_cx = auto_cx
                    next_cy = auto_cy
            next_color = (
                (item.fill_color.strip() or None)
                if item.fill_color is not None
                else z.fill_color
            )
            prepared.append((z, next_poly_json, next_cx, next_cy, next_color))

        for z, pjson, cx, cy, fcolor in prepared:
            z.polygon_points_json = pjson
            z.center_x_pct = cx
            z.center_y_pct = cy
            z.fill_color = fcolor
            session.add(z)
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.flush()
        recompute_checkpoint_zones(session, project_id)
        session.commit()
        return {"success": True, "updated_count": len(prepared)}


@router.post("/projects/{project_id}/zones/generate-from-point")
async def generate_zone_from_point(project_id: str, payload: ZoneFromPointRequest):
    """Sinh bản nháp Polygon 1 khu vực từ 1 điểm tâm (center_x_pct, center_y_pct) + Prompt mô tả."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        result = await generate_zone_from_point_draft(
            session,
            proj,
            ws,
            center_x_pct=payload.center_x_pct,
            center_y_pct=payload.center_y_pct,
            prompt=payload.prompt,
        )
        return {"success": True, **result}


@router.get("/projects/{project_id}/checkpoints")
async def list_checkpoints(project_id: str):
    """Liệt kê toàn bộ Chốt/Pin (Checkpoints) của dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        rows = session.exec(
            select(UrbanSimCheckpoint)
            .where(UrbanSimCheckpoint.project_id == project_id)
            .order_by(UrbanSimCheckpoint.sort_order, UrbanSimCheckpoint.name)  # type: ignore[arg-type]
        ).all()
        return {
            "success": True,
            "has_digital_map": project_has_digital_map(session, proj),
            "items": [_serialize_checkpoint(cp) for cp in rows],
        }


@router.post("/projects/{project_id}/checkpoints")
async def create_checkpoint(project_id: str, payload: CheckpointCreateRequest):
    """Tạo Chốt/Pin thủ công (chỉ cho phép khi đã có Bản đồ Số; trả 409 nếu chưa đủ điều kiện)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        _require_digital_map_or_409(session, proj)
        cp_key = normalize_map_key(payload.checkpoint_key or payload.name, prefix="CP")
        dup = session.exec(
            select(UrbanSimCheckpoint).where(
                UrbanSimCheckpoint.project_id == project_id,
                UrbanSimCheckpoint.checkpoint_key == cp_key,
            )
        ).first()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Mã chốt '{cp_key}' đã tồn tại trong dự án.",
            )
        xp = round(max(0.5, min(99.5, float(payload.x_pct))), 2)
        yp = round(max(0.5, min(99.5, float(payload.y_pct))), 2)
        zones = session.exec(
            select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
        ).all()
        zkey = find_containing_zone_key(xp, yp, zones)
        cp = UrbanSimCheckpoint(
            project_id=project_id,
            checkpoint_key=cp_key,
            name=payload.name.strip(),
            x_pct=xp,
            y_pct=yp,
            icon_emoji=(payload.icon_emoji or "📍").strip()[:16] or "📍",
            description_md=(payload.description_md or "").strip(),
            zone_key=zkey,
            category=payload.category,
            sort_order=int(payload.sort_order),
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        return {"success": True, "checkpoint": _serialize_checkpoint(cp)}


@router.put("/projects/{project_id}/checkpoints/layout")
async def save_checkpoints_layout(project_id: str, payload: CheckpointsLayoutRequest):
    """Cập nhật hàng loạt tọa độ kéo thả của các Chốt/Pin trong 1 transaction atomic."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        zones = session.exec(
            select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
        ).all()
        cps_by_id = {
            cp.id: cp
            for cp in session.exec(
                select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project_id)
            ).all()
        }
        prepared: list[tuple[UrbanSimCheckpoint, float, float, str | None]] = []
        for item in payload.checkpoints:
            cp = cps_by_id.get(item.id)
            if cp is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Không tìm thấy Chốt ID '{item.id}' trong dự án.",
                )
            xp = round(max(0.5, min(99.5, float(item.x_pct))), 2)
            yp = round(max(0.5, min(99.5, float(item.y_pct))), 2)
            zkey = find_containing_zone_key(xp, yp, zones)
            prepared.append((cp, xp, yp, zkey))

        now_iso = _utcnow_iso()
        for cp, xp, yp, zkey in prepared:
            cp.x_pct = xp
            cp.y_pct = yp
            cp.zone_key = zkey
            cp.updated_at = now_iso
            session.add(cp)
        session.commit()
        return {"success": True, "updated_count": len(prepared)}


@router.post("/projects/{project_id}/checkpoints/generate")
async def generate_checkpoints(project_id: str, payload: CheckpointsGenerateRequest):
    """Dùng AI Prompt + ngữ cảnh Bản đồ Số sinh danh sách Chốt/Pin dự kiến."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        result = await generate_checkpoints_draft(
            session,
            proj,
            ws,
            prompt=payload.prompt,
            max_checkpoints=payload.max_checkpoints,
        )
        return {"success": True, **result}


@router.post("/projects/{project_id}/checkpoints/apply-batch")
async def apply_checkpoints_batch(project_id: str, payload: CheckpointsApplyBatchRequest):
    """Lưu hàng loạt Chốt/Pin idempotent theo (project_id, checkpoint_key) trong 1 transaction atomic."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        _require_digital_map_or_409(session, proj)
        zones = session.exec(
            select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
        ).all()
        existing_by_key = {
            cp.checkpoint_key: cp
            for cp in session.exec(
                select(UrbanSimCheckpoint).where(UrbanSimCheckpoint.project_id == project_id)
            ).all()
        }
        seen_keys: set[str] = set()
        now_iso = _utcnow_iso()
        saved: list[UrbanSimCheckpoint] = []
        for idx, item in enumerate(payload.checkpoints):
            cp_key = normalize_map_key(item.checkpoint_key or item.name, prefix=f"CP_{idx + 1}")
            if cp_key in seen_keys:
                continue
            seen_keys.add(cp_key)
            xp = round(max(0.5, min(99.5, float(item.x_pct))), 2)
            yp = round(max(0.5, min(99.5, float(item.y_pct))), 2)
            zkey = find_containing_zone_key(xp, yp, zones)
            existing_cp = existing_by_key.get(cp_key)
            if existing_cp is not None:
                existing_cp.name = item.name.strip()
                existing_cp.x_pct = xp
                existing_cp.y_pct = yp
                existing_cp.icon_emoji = (item.icon_emoji or "📍").strip()[:16] or "📍"
                existing_cp.description_md = (item.description_md or "").strip()
                existing_cp.zone_key = zkey
                existing_cp.category = item.category
                existing_cp.sort_order = int(item.sort_order or (idx + 1))
                existing_cp.updated_at = now_iso
                session.add(existing_cp)
                saved.append(existing_cp)
            else:
                cp = UrbanSimCheckpoint(
                    project_id=project_id,
                    checkpoint_key=cp_key,
                    name=item.name.strip(),
                    x_pct=xp,
                    y_pct=yp,
                    icon_emoji=(item.icon_emoji or "📍").strip()[:16] or "📍",
                    description_md=(item.description_md or "").strip(),
                    zone_key=zkey,
                    category=item.category,
                    sort_order=int(item.sort_order or (idx + 1)),
                )
                session.add(cp)
                existing_by_key[cp_key] = cp
                saved.append(cp)

        session.commit()
        for cp in saved:
            session.refresh(cp)
        return {
            "success": True,
            "items": [_serialize_checkpoint(cp) for cp in saved],
        }


@router.patch("/projects/{project_id}/checkpoints/{checkpoint_id}")
async def update_checkpoint(
    project_id: str, checkpoint_id: str, payload: CheckpointUpdateRequest
):
    """Cập nhật thông tin / tọa độ / emoji / mô tả Markdown của một Chốt/Pin."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        cp = session.get(UrbanSimCheckpoint, checkpoint_id)
        if cp is None or cp.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Chốt/Pin.")
        if payload.checkpoint_key is not None:
            new_key = normalize_map_key(payload.checkpoint_key, prefix="CP")
            if new_key != cp.checkpoint_key:
                dup = session.exec(
                    select(UrbanSimCheckpoint).where(
                        UrbanSimCheckpoint.project_id == project_id,
                        UrbanSimCheckpoint.checkpoint_key == new_key,
                        UrbanSimCheckpoint.id != cp.id,
                    )
                ).first()
                if dup is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Mã chốt '{new_key}' đã tồn tại.",
                    )
                cp.checkpoint_key = new_key
        if payload.name is not None:
            clean_name = payload.name.strip()
            if not clean_name:
                raise HTTPException(status_code=400, detail="Tên chốt không được để trống.")
            cp.name = clean_name
        coords_changed = False
        if payload.x_pct is not None:
            cp.x_pct = round(max(0.5, min(99.5, float(payload.x_pct))), 2)
            coords_changed = True
        if payload.y_pct is not None:
            cp.y_pct = round(max(0.5, min(99.5, float(payload.y_pct))), 2)
            coords_changed = True
        if coords_changed:
            zones = session.exec(
                select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
            ).all()
            cp.zone_key = find_containing_zone_key(cp.x_pct, cp.y_pct, zones)
        if payload.icon_emoji is not None:
            cp.icon_emoji = payload.icon_emoji.strip()[:16] or "📍"
        if payload.description_md is not None:
            cp.description_md = payload.description_md.strip()
        if payload.category is not None:
            cp.category = payload.category
        if payload.sort_order is not None:
            cp.sort_order = int(payload.sort_order)
        cp.updated_at = _utcnow_iso()
        session.add(cp)
        session.commit()
        session.refresh(cp)
        return {"success": True, "checkpoint": _serialize_checkpoint(cp)}


@router.delete("/projects/{project_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(project_id: str, checkpoint_id: str):
    """Xóa một Chốt/Pin khỏi dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        cp = session.get(UrbanSimCheckpoint, checkpoint_id)
        if cp is None or cp.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Chốt/Pin.")
        session.delete(cp)
        session.commit()
        return {"success": True, "deleted_id": checkpoint_id}


# ==================== RUN LIFECYCLE ENDPOINTS ====================


@router.get("/projects/{project_id}/runs")
async def list_runs(project_id: str):
    """Liệt kê lịch sử các Run của dự án (tự đồng bộ metrics cho Run đang chạy)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    mgr = get_lifecycle_manager()
    with Session(engine) as session:
        _require_project(session, project_id)
        runs = session.exec(
            select(UrbanSimRun)
            .where(UrbanSimRun.project_id == project_id)
            .order_by(UrbanSimRun.run_number.desc())  # type: ignore[union-attr]
        ).all()
        changed = False
        for r in runs:
            if r.status in {"STARTING", "RUNNING", "PAUSING", "RESUMING"}:
                mgr._sync_run_metrics(session, r)
                changed = True
        if changed:
            session.commit()
        return {"success": True, "items": [_serialize_run(r) for r in runs]}


@router.post("/projects/{project_id}/runs/start")
async def start_run(project_id: str):
    """Biên dịch cấu hình DB hiện hành và khởi chạy Run mới."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    run = await get_lifecycle_manager().start_run(project_id)
    return {"success": True, "run": _serialize_run(run)}


@router.post("/projects/{project_id}/runs/{run_id}/pause")
async def pause_run(project_id: str, run_id: str):
    """Yêu cầu tạm dừng Run sạch tại ranh giới tick kế tiếp (tạo STOP_REQUESTED)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    run = await get_lifecycle_manager().pause_run(project_id, run_id)
    return {"success": True, "run": _serialize_run(run)}


@router.post("/projects/{project_id}/runs/{run_id}/resume")
async def resume_run(project_id: str, run_id: str):
    """Tiếp tục chạy lại từ checkpoint đã dừng của Run."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    run = await get_lifecycle_manager().resume_run(project_id, run_id)
    return {"success": True, "run": _serialize_run(run)}


@router.post("/projects/{project_id}/runs/restart")
async def restart_run(project_id: str):
    """Áp dụng cấu hình DB mới nhất và tạo Run mới hoàn toàn."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    run = await get_lifecycle_manager().restart_run(project_id)
    return {"success": True, "run": _serialize_run(run)}


@router.delete("/projects/{project_id}/runs/{run_id}")
async def delete_run(project_id: str, run_id: str):
    """Xóa Run và toàn bộ thư mục artifacts/screenshots trên ổ đĩa."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    await get_lifecycle_manager().delete_run(project_id, run_id)
    return {"success": True, "deleted_id": run_id}


# ==================== LIVE TELEMETRY, EVENTS, COST & SCREENSHOTS ====================


def _require_run_and_dir(
    session: Session, ws: Path, project_id: str, run_id: str
) -> tuple[UrbanSimProject, UrbanSimRun, Path]:
    proj = _require_project(session, project_id)
    run = session.get(UrbanSimRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy Run.")
    run_dir = resolve_urban_sim_run_dir(ws, run.run_dir)
    return proj, run, run_dir


def _parse_iso_preserving_tz(raw: str | None) -> datetime | None:
    """Parse ISO timestamp while preserving its original timezone offset."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _classify_sim_time_period(dt: datetime) -> dict[str, Any]:
    """Classify simulation hour into Vietnamese time-of-day band and day/night state."""
    h = int(dt.hour)
    if 6 <= h < 9:
        band, band_vi, period_vi, is_day = "MORNING_RUSH", "Sáng · Cao điểm", "Sáng", True
    elif 9 <= h < 12:
        band, band_vi, period_vi, is_day = "MORNING_WORK", "Sáng · Hành chính", "Sáng", True
    elif 12 <= h < 14:
        band, band_vi, period_vi, is_day = "NOON_REST", "Trưa · Nghỉ trưa", "Trưa", True
    elif 14 <= h < 17:
        band, band_vi, period_vi, is_day = "AFTERNOON_OPS", "Chiều · Hành chính", "Chiều", True
    elif 17 <= h < 18:
        band, band_vi, period_vi, is_day = "EVENING_RUSH", "Chiều tối · Cao điểm", "Chiều tối", True
    elif 18 <= h < 21:
        band, band_vi, period_vi, is_day = "EVENING_RUSH", "Tối · Cao điểm", "Tối", False
    else:
        band, band_vi, period_vi, is_day = "QUIET_NIGHT", "Đêm · Yên tĩnh", "Đêm", False
    return {
        "time_band": band,
        "time_band_label_vi": band_vi,
        "period_vi": period_vi,
        "is_daytime": is_day,
        "day_night_label_vi": "Ban ngày" if is_day else "Ban đêm",
    }


def _extract_run_sim_clock(
    run_dir: Path, project: UrbanSimProject, run: UrbanSimRun
) -> dict[str, Any]:
    """Build current simulation clock & day/night metadata from SOCIETY_STEP.json and steps.yaml."""
    start_raw = str(project.start_time_iso or "").strip() or None
    tick_seconds = int(project.tick_seconds or 900)

    steps_path = run_dir / "init" / "steps.yaml"
    if steps_path.is_file() and not steps_path.is_symlink():
        try:
            parsed = yaml.safe_load(steps_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                if parsed.get("start_t"):
                    start_raw = str(parsed["start_t"]).strip()
                raw_steps = parsed.get("steps")
                if isinstance(raw_steps, list):
                    for item in raw_steps:
                        if isinstance(item, dict) and item.get("type") == "run" and item.get("tick"):
                            tick_seconds = max(1, int(item["tick"]))
                            break
        except Exception:
            pass

    step_meta_path = run_dir / SOCIETY_STEP_JSON
    step_meta = _read_json_file(step_meta_path)
    current_raw = str(step_meta.get("current_time") or "").strip() or None

    tick_started_dt: datetime | None = None
    if step_meta_path.is_file():
        try:
            tick_started_dt = datetime.fromtimestamp(step_meta_path.stat().st_mtime, tz=UTC)
        except OSError:
            tick_started_dt = None
    if tick_started_dt is None:
        tick_started_dt = (
            _parse_iso_preserving_tz(run.started_at)
            or _parse_iso_preserving_tz(run.created_at)
            or datetime.now(UTC)
        )

    est_wall_sec = 45.0 if bool(run.pilot_mode) else 90.0
    started_dt_wall = _parse_iso_preserving_tz(run.started_at)
    if int(run.step_count or 0) >= 1 and started_dt_wall is not None:
        try:
            avg_wall = (
                tick_started_dt.astimezone(UTC) - started_dt_wall.astimezone(UTC)
            ).total_seconds() / max(1, int(run.step_count))
            if avg_wall > 5.0:
                est_wall_sec = max(25.0, min(240.0, round(avg_wall, 1)))
        except Exception:
            pass

    start_dt = _parse_iso_preserving_tz(start_raw)
    current_dt = _parse_iso_preserving_tz(current_raw)
    if current_dt is None and start_dt is not None:
        current_dt = start_dt + timedelta(seconds=max(0, int(run.step_count or 0)) * tick_seconds)
        current_raw = current_dt.isoformat()

    end_raw: str | None = None
    if start_dt is not None and int(run.total_steps or 0) > 0:
        end_raw = (start_dt + timedelta(seconds=int(run.total_steps) * tick_seconds)).isoformat()

    elapsed_seconds = max(0, int(run.step_count or 0) * tick_seconds)
    if start_dt is not None and current_dt is not None:
        elapsed_seconds = max(0, int(round((current_dt - start_dt).total_seconds())))
    day_index = (elapsed_seconds // 86400) + 1
    total_sim_days = (
        max(1, ((int(run.total_steps) * tick_seconds - 1) // 86400) + 1)
        if int(run.total_steps or 0) > 0
        else 1
    )

    period_info = (
        _classify_sim_time_period(current_dt)
        if current_dt is not None
        else {
            "time_band": None,
            "time_band_label_vi": None,
            "period_vi": None,
            "is_daytime": None,
            "day_night_label_vi": None,
        }
    )

    return {
        "current_sim_time": current_raw,
        "start_sim_time": start_dt.isoformat() if start_dt is not None else start_raw,
        "end_sim_time": end_raw,
        "tick_seconds": tick_seconds,
        "elapsed_seconds": elapsed_seconds,
        "tick_started_at": tick_started_dt.isoformat(),
        "estimated_tick_wall_seconds": est_wall_sec,
        "day_index": day_index,
        "total_sim_days": total_sim_days,
        **period_info,
    }


def _read_agent_workspace_summary(run_dir: Path, agent_id: int) -> dict[str, int]:
    """Read lightweight cognitive/workspace counters (episodes, todos, notes) for one agent."""
    out = {
        "episodes_count": 0,
        "todos_total": 0,
        "todos_completed": 0,
        "notes_count": 0,
    }
    agent_root = (run_dir / "agents" / f"agent_{int(agent_id):04d}").resolve()
    try:
        agent_root.relative_to(run_dir.resolve())
    except ValueError:
        return out
    if not agent_root.is_dir() or agent_root.is_symlink():
        return out

    ep_path = agent_root / "memory" / "episodes.jsonl"
    if ep_path.is_file() and not ep_path.is_symlink():
        try:
            raw_ep = ep_path.read_bytes()[: 2 * 1024 * 1024].decode("utf-8", errors="replace")
            out["episodes_count"] = sum(1 for ln in raw_ep.splitlines() if ln.strip())
        except OSError:
            pass

    todo_path = agent_root / "TODO.json"
    if todo_path.is_file() and not todo_path.is_symlink():
        try:
            raw_todo = todo_path.read_bytes()[: 512 * 1024].decode("utf-8", errors="replace")
            todo_data = json.loads(raw_todo)
            raw_todos = todo_data.get("todos") if isinstance(todo_data, dict) else None
            if isinstance(raw_todos, list):
                valid_todos = [t for t in raw_todos if isinstance(t, dict)]
                out["todos_total"] = len(valid_todos)
                out["todos_completed"] = sum(
                    1
                    for t in valid_todos
                    if str(t.get("status") or "").strip().lower() in {"completed", "done"}
                )
        except (OSError, ValueError):
            pass

    notes_dir = agent_root / "notes"
    if notes_dir.is_dir() and not notes_dir.is_symlink():
        note_exts = {".md", ".txt", ".json", ".yaml", ".yml", ""}
        count = 0
        try:
            for fp in notes_dir.rglob("*"):
                if count >= 50:
                    break
                if fp.is_symlink() or not fp.is_file():
                    continue
                if fp.suffix.lower() in note_exts:
                    count += 1
        except OSError:
            pass
        out["notes_count"] = count

    return out


@router.get("/projects/{project_id}/runs/{run_id}/map-image")
async def get_run_map_image(project_id: str, run_id: str):
    """Phục vụ ảnh 2D snapshot của chính Run (bảo toàn lịch sử bất biến, fallback dự án cho Run cũ)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, _run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        snap = _read_json_file(run_dir / "init" / "digital_map_snapshot.json")
        snap_fname = str(snap.get("snapshot_image_filename") or "").strip()
        if snap_fname:
            snap_path = resolve_under_root(run_dir, "init", Path(snap_fname).name)
            if snap_path.is_file():
                return FileResponse(
                    snap_path,
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        if proj.zone_map_image_rel:
            img_path = resolve_urban_sim_map_image(ws, proj.zone_map_image_rel)
            if img_path.is_file():
                return FileResponse(
                    img_path,
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        raise HTTPException(status_code=404, detail="Run này không có ảnh mặt bằng 2D.")


@router.get("/projects/{project_id}/runs/{run_id}/state")
async def get_run_state(project_id: str, run_id: str):
    """Trạng thái tổng hợp thời gian thực của Run (Snapshot Bản đồ Số + Live Movement Overlay + KPIs)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    mgr = get_lifecycle_manager()
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        mgr._sync_run_metrics(session, run)
        session.commit()
        session.refresh(run)

        personas = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .order_by(UrbanSimPersona.agent_id)
        ).all()
        sim_clock = _extract_run_sim_clock(run_dir, proj, run)
        run_payload = _serialize_run(run)
        run_payload["execution_phase"] = derive_execution_phase(
            run_dir, run.status, int(run.step_count), int(run.total_steps)
        )
        run_payload["current_sim_time"] = sim_clock.get("current_sim_time")

        snap = _read_json_file(run_dir / "init" / "digital_map_snapshot.json")
        has_snapshot = isinstance(snap, dict) and isinstance(snap.get("zones"), list)
        if has_snapshot:
            zones_source: list[dict[str, Any]] = [
                dict(z) for z in snap.get("zones", []) if isinstance(z, dict)
            ]
            checkpoints_source: list[dict[str, Any]] = [
                dict(cp) for cp in (snap.get("checkpoints") or []) if isinstance(cp, dict)
            ]
            snap_fname = str(snap.get("snapshot_image_filename") or "").strip()
            has_map_img = bool(
                snap_fname and (run_dir / "init" / Path(snap_fname).name).is_file()
            )
            map_version = int(snap.get("map_image_version") or 0)
            digital_map_meta = {
                "has_digital_map": bool(snap.get("has_digital_map")),
                "map_prompt": str(snap.get("map_prompt") or ""),
                "map_width": snap.get("map_width"),
                "map_height": snap.get("map_height"),
                "map_aspect_ratio": float(snap.get("map_aspect_ratio") or 1.6),
                "map_image_version": map_version,
                "has_map_image": has_map_img,
                "image_url": (
                    f"/api/v1/urban-sim/projects/{project_id}/runs/{run_id}/map-image?v={map_version}"
                    if has_map_img
                    else None
                ),
            }
        else:
            db_zones = session.exec(
                select(UrbanSimZone)
                .where(UrbanSimZone.project_id == project_id)
                .order_by(UrbanSimZone.sort_order)
            ).all()
            db_cps = session.exec(
                select(UrbanSimCheckpoint)
                .where(UrbanSimCheckpoint.project_id == project_id)
                .order_by(UrbanSimCheckpoint.sort_order, UrbanSimCheckpoint.name)  # type: ignore[arg-type]
            ).all()
            zones_source = [
                {
                    "id": z.id,
                    "zone_key": z.zone_key,
                    "name": z.name,
                    "zone_type": z.zone_type,
                    "description": z.description,
                    "center_x_pct": getattr(z, "center_x_pct", None),
                    "center_y_pct": getattr(z, "center_y_pct", None),
                    "polygon_points": parse_polygon_json(getattr(z, "polygon_points_json", None)),
                    "fill_color": getattr(z, "fill_color", None),
                }
                for z in db_zones
            ]
            checkpoints_source = [
                {
                    "id": cp.id,
                    "checkpoint_key": cp.checkpoint_key,
                    "name": cp.name,
                    "x_pct": round(float(cp.x_pct), 2),
                    "y_pct": round(float(cp.y_pct), 2),
                    "icon_emoji": cp.icon_emoji or "📍",
                    "description_md": cp.description_md or "",
                    "zone_key": cp.zone_key,
                    "category": cp.category or "general",
                }
                for cp in db_cps
            ]
            has_map_img = bool(proj.zone_map_image_rel)
            map_version = int(getattr(proj, "map_image_version", 0) or 0)
            digital_map_meta = {
                "has_digital_map": has_map_img or any(bool(z.get("polygon_points")) for z in zones_source),
                "map_prompt": getattr(proj, "map_prompt", None) or "",
                "map_width": getattr(proj, "map_width", None),
                "map_height": getattr(proj, "map_height", None),
                "map_aspect_ratio": float(getattr(proj, "map_aspect_ratio", None) or 1.6),
                "map_image_version": map_version,
                "has_map_image": has_map_img,
                "image_url": (
                    f"/api/v1/urban-sim/projects/{project_id}/runs/{run_id}/map-image?v={map_version}"
                    if has_map_img
                    else None
                ),
            }

        proj_meta = {
            "id": proj.id,
            "name": proj.name,
            "has_zone_map_image": digital_map_meta["has_map_image"],
            "has_digital_map": digital_map_meta["has_digital_map"],
            "max_cost_usd_per_run": float(proj.max_cost_usd_per_run),
        }

    comm_state = _read_json_file(
        run_dir / "env" / "UrbanCommAndIncidentEnv" / "state" / "ENV_STATE.json"
    )
    web_state = _read_json_file(
        run_dir / "env" / "DemegoWebPortalEnv" / "state" / "ENV_STATE.json"
    )
    atlas_state = _read_json_file(
        run_dir / "env" / "EvidenceAtlasSupportEnv" / "state" / "ENV_STATE.json"
    )
    llm_raw = _read_json_file(run_dir / LLM_STATS_JSON)
    cost_info = compute_run_cost(llm_raw)

    agent_zones = comm_state.get("agent_zones") or {}
    agent_positions = comm_state.get("agent_positions") or {}
    last_move_seq = int(comm_state.get("last_move_event_seq") or 0)
    mailboxes = comm_state.get("mailboxes") if isinstance(comm_state.get("mailboxes"), dict) else {}
    incidents_map = comm_state.get("incidents") or {}
    incidents = sorted(
        [v for v in incidents_map.values() if isinstance(v, dict)],
        key=lambda x: str(x.get("incident_id") or ""),
        reverse=True,
    )
    last_urls = web_state.get("last_urls") or {}
    actions_cnt = web_state.get("actions_count") or {}
    blocked_cnt = web_state.get("blocked_count") or {}
    bot_sessions = atlas_state.get("bot_sessions") or {}
    asks_cnt = atlas_state.get("total_asks_by_agent") or {}

    # Compute zone centers deterministically for fallback when zone lacks center_x/center_y
    z_centers: dict[str, tuple[float, float]] = {}
    z_cols = max(1, math.ceil(math.sqrt(max(1, len(zones_source)))))
    for z_idx, z_item in enumerate(zones_source):
        zkey = str(z_item.get("zone_key") or "")
        zx = z_item.get("center_x_pct")
        zy = z_item.get("center_y_pct")
        poly = z_item.get("polygon_points")
        if (zx is None or zy is None) and isinstance(poly, list) and len(poly) >= 3:
            try:
                pts = [(float(pt[0]), float(pt[1])) for pt in poly]
                zx = sum(pt[0] for pt in pts) / len(pts)
                zy = sum(pt[1] for pt in pts) / len(pts)
            except (TypeError, ValueError, IndexError):
                zx, zy = None, None
        if zx is None or zy is None:
            ri, ci = divmod(z_idx, z_cols)
            zx = 14.0 + (ci + 0.5) * (72.0 / z_cols)
            zy = 16.0 + (ri + 0.5) * (68.0 / max(1, math.ceil(len(zones_source) / z_cols)))
        zx_r = round(float(zx), 2)
        zy_r = round(float(zy), 2)
        z_item["center_x_pct"] = zx_r
        z_item["center_y_pct"] = zy_r
        if zkey:
            z_centers[zkey] = (zx_r, zy_r)

    stream_counts = {"COMM": 0, "WEB": 0, "ATLAS": 0, "INCIDENT": 0}
    events_path = run_dir / "urban_events.jsonl"
    latest_seq = 0
    per_agent_events: dict[int, dict[str, Any]] = {}
    agent_trails: dict[int, deque[dict[str, Any]]] = {}
    recent_movements: deque[dict[str, Any]] = deque(maxlen=30)
    live_move_overlay: dict[int, tuple[int, dict[str, Any]]] = {}

    if events_path.is_file():
        with open(events_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    ev = json.loads(line_s)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                st = str(ev.get("stream") or "").upper()
                if st in stream_counts:
                    stream_counts[st] += 1
                seq_val = int(ev.get("seq") or 0)
                if seq_val > latest_seq:
                    latest_seq = seq_val

                raw_aid = ev.get("agent_id")
                act_name = str(ev.get("action") or "")
                if isinstance(raw_aid, int) and not isinstance(raw_aid, bool):
                    bucket = per_agent_events.setdefault(
                        raw_aid,
                        {
                            "web_events": 0,
                            "web_fail": 0,
                            "atlas_events": 0,
                            "atlas_fail": 0,
                            "comm_events": 0,
                            "incident_events": 0,
                            "last_seq": -1,
                            "last_event": None,
                        },
                    )
                    ev_ok = bool(ev.get("ok", True))
                    if st == "WEB":
                        bucket["web_events"] += 1
                        if not ev_ok:
                            bucket["web_fail"] += 1
                    elif st == "ATLAS":
                        bucket["atlas_events"] += 1
                        if not ev_ok:
                            bucket["atlas_fail"] += 1
                    elif st == "COMM":
                        bucket["comm_events"] += 1
                    elif st == "INCIDENT":
                        bucket["incident_events"] += 1

                    if seq_val >= bucket["last_seq"]:
                        bucket["last_seq"] = seq_val
                        bucket["last_event"] = {
                            "action": act_name,
                            "stream": st,
                            "summary": str(ev.get("summary") or "").strip(),
                            "sim_time": ev.get("sim_time"),
                            "ok": ev_ok,
                        }

                    if act_name in {"move_to_zone", "move_to_checkpoint"}:
                        det = ev.get("details") if isinstance(ev.get("details"), dict) else {}
                        to_zone = str(det.get("to_zone") or "")
                        fallback_xy = z_centers.get(to_zone, (50.0, 50.0))
                        to_x = det.get("to_x_pct")
                        to_y = det.get("to_y_pct")
                        px = round(float(to_x), 2) if to_x is not None else fallback_xy[0]
                        py = round(float(to_y), 2) if to_y is not None else fallback_xy[1]
                        mv_pt = {
                            "seq": seq_val,
                            "action": act_name,
                            "x_pct": px,
                            "y_pct": py,
                            "zone_key": to_zone,
                            "checkpoint_key": det.get("checkpoint_key"),
                            "checkpoint_name": det.get("checkpoint_name"),
                            "icon_emoji": det.get("icon_emoji"),
                            "activity": str(det.get("activity") or ""),
                            "movement_status": str(det.get("movement_status") or "moving"),
                            "sim_time": ev.get("sim_time"),
                        }
                        agent_trails.setdefault(raw_aid, deque(maxlen=12)).append(mv_pt)
                        recent_movements.append(
                            {
                                **mv_pt,
                                "agent_id": raw_aid,
                                "agent_name": str(ev.get("agent_name") or ""),
                                "role_title": str(ev.get("role_title") or ""),
                                "from_x_pct": det.get("from_x_pct"),
                                "from_y_pct": det.get("from_y_pct"),
                                "from_zone": det.get("from_zone"),
                                "summary": str(ev.get("summary") or ""),
                            }
                        )
                        if seq_val > last_move_seq:
                            prev_ov = live_move_overlay.get(raw_aid)
                            if prev_ov is None or seq_val >= prev_ov[0]:
                                live_move_overlay[raw_aid] = (seq_val, mv_pt)

    incidents_related_by_agent: dict[int, int] = {}
    incidents_open_by_agent: dict[int, int] = {}
    for inc in incidents:
        is_open = str(inc.get("status") or "").upper() != "RESOLVED"
        seen_aids: set[int] = set()
        for key in ("reporter_id", "assigned_to_id"):
            val = inc.get(key)
            if isinstance(val, int) and not isinstance(val, bool):
                seen_aids.add(val)
        for aid_val in seen_aids:
            incidents_related_by_agent[aid_val] = incidents_related_by_agent.get(aid_val, 0) + 1
            if is_open:
                incidents_open_by_agent[aid_val] = incidents_open_by_agent.get(aid_val, 0) + 1

    screenshots_dir = run_dir / "artifacts" / "screenshots"
    agent_statuses: list[dict[str, Any]] = []
    for p in personas:
        aid_int = int(p.agent_id)
        aid_str = str(aid_int)
        latest_shot = screenshots_dir / f"agent_{aid_str}_latest.jpg"
        latest_meta_path = screenshots_dir / f"agent_{aid_str}_latest.meta.json"
        meta_details: dict[str, Any] = {}
        if latest_meta_path.is_file():
            loaded_meta = _read_json_file(latest_meta_path)
            if isinstance(loaded_meta, dict) and loaded_meta.get("latest_image_status"):
                meta_details["capture_status"] = loaded_meta.get("latest_image_status")
            elif isinstance(loaded_meta, dict) and loaded_meta.get("capture_status"):
                meta_details["capture_status"] = loaded_meta.get("capture_status")
        latest_status, latest_bytes = classify_screenshot_file(
            screenshots_dir,
            latest_shot.name if latest_shot.is_file() else None,
            meta_details,
        )

        ev_stats = per_agent_events.get(aid_int) or {}
        web_cnt = int(actions_cnt.get(aid_str) or 0) or int(ev_stats.get("web_events") or 0)
        atlas_cnt = int(asks_cnt.get(aid_str) or 0) or int(ev_stats.get("atlas_events") or 0)
        comm_cnt = int(ev_stats.get("comm_events") or 0)
        inc_action_cnt = int(ev_stats.get("incident_events") or 0)
        total_actions_cnt = web_cnt + atlas_cnt + comm_cnt + inc_action_cnt

        raw_inbox = mailboxes.get(aid_str)
        inbox_msgs = [m for m in raw_inbox if isinstance(m, dict)] if isinstance(raw_inbox, list) else []
        unread_cnt = sum(1 for m in inbox_msgs if not m.get("read"))
        ws_summary = _read_agent_workspace_summary(run_dir, aid_int)
        last_ev = ev_stats.get("last_event") if isinstance(ev_stats.get("last_event"), dict) else {}

        pos_state = agent_positions.get(aid_str) if isinstance(agent_positions.get(aid_str), dict) else {}
        cur_zone = str(agent_zones.get(aid_str) or p.home_zone)
        fb_x, fb_y = z_centers.get(cur_zone, (50.0, 50.0))
        cur_x = round(float(pos_state.get("x_pct")), 2) if pos_state.get("x_pct") is not None else fb_x
        cur_y = round(float(pos_state.get("y_pct")), 2) if pos_state.get("y_pct") is not None else fb_y
        cur_cp_key = pos_state.get("checkpoint_key")
        cur_cp_name = pos_state.get("checkpoint_name")
        cur_activity = str(pos_state.get("activity") or "")
        mv_status = str(pos_state.get("movement_status") or "idle")

        # Live mid-tick overlay from urban_events.jsonl (events strictly newer than last_move_event_seq)
        if aid_int in live_move_overlay:
            _, ov = live_move_overlay[aid_int]
            if ov.get("zone_key"):
                cur_zone = str(ov["zone_key"])
            cur_x = float(ov["x_pct"])
            cur_y = float(ov["y_pct"])
            cur_cp_key = ov.get("checkpoint_key")
            cur_cp_name = ov.get("checkpoint_name")
            cur_activity = str(ov.get("activity") or "")
            mv_status = str(ov.get("movement_status") or "moving")

        trail_list = list(agent_trails.get(aid_int) or [])

        agent_statuses.append(
            {
                "agent_id": p.agent_id,
                "full_name": p.full_name,
                "role_code": p.role_code,
                "role_title": p.role_title,
                "department": p.department,
                "group_type": p.group_type,
                "avatar_icon": (getattr(p, "avatar_icon", None) or "").strip()
                or resolve_default_persona_icon(p.role_code, p.group_type, p.full_name),
                "software_access_enabled": bool(p.software_access_enabled),
                "current_zone": cur_zone,
                "current_x_pct": cur_x,
                "current_y_pct": cur_y,
                "current_checkpoint_key": cur_cp_key,
                "current_checkpoint_name": cur_cp_name,
                "current_activity": cur_activity,
                "movement_status": mv_status,
                "recent_trail": trail_list,
                "current_url": str(last_urls.get(aid_str) or ""),
                "web_actions_count": web_cnt,
                "blocked_actions_count": int(blocked_cnt.get(aid_str) or 0),
                "atlas_asks_count": atlas_cnt,
                "bot_session_id": bot_sessions.get(aid_str),
                "latest_screenshot": latest_shot.name if latest_shot.is_file() else None,
                "latest_screenshot_status": latest_status,
                "latest_screenshot_bytes": latest_bytes,
                "total_actions_count": total_actions_cnt,
                "comm_actions_count": comm_cnt,
                "incident_actions_count": inc_action_cnt,
                "web_failed_count": int(ev_stats.get("web_fail") or 0),
                "atlas_failed_count": int(ev_stats.get("atlas_fail") or 0),
                "unread_messages_count": unread_cnt,
                "received_messages_count": len(inbox_msgs),
                "incidents_related_count": incidents_related_by_agent.get(aid_int, 0),
                "incidents_open_count": incidents_open_by_agent.get(aid_int, 0),
                "episodes_count": ws_summary["episodes_count"],
                "todos_total": ws_summary["todos_total"],
                "todos_completed": ws_summary["todos_completed"],
                "notes_count": ws_summary["notes_count"],
                "last_action": last_ev.get("action") or None,
                "last_action_stream": last_ev.get("stream") or None,
                "last_action_summary": last_ev.get("summary") or None,
                "last_action_sim_time": last_ev.get("sim_time") or None,
                "last_action_ok": last_ev.get("ok") if "ok" in last_ev else None,
            }
        )

    active_total = int(run.active_agent_count or len(agent_statuses))
    sim_clock["agents_completed_in_tick"] = min(
        active_total,
        sum(
            1
            for ag in agent_statuses
            if int(ag.get("episodes_count") or 0) > int(run.step_count or 0)
        ),
    )
    sim_clock["active_agent_count"] = active_total

    zone_cards: list[dict[str, Any]] = []
    for z in zones_source:
        zkey = str(z.get("zone_key") or "")
        agents_here = [
            {
                "agent_id": a["agent_id"],
                "full_name": a["full_name"],
                "role_title": a["role_title"],
                "group_type": a["group_type"],
            }
            for a in agent_statuses
            if a["current_zone"] == zkey
        ]
        open_inc_here = [
            inc
            for inc in incidents
            if inc.get("zone_key") == zkey and inc.get("status") != "RESOLVED"
        ]
        zone_cards.append(
            {
                "id": z.get("id"),
                "zone_key": zkey,
                "name": z.get("name", zkey),
                "zone_type": z.get("zone_type", "OTHER"),
                "description": z.get("description", ""),
                "center_x_pct": z.get("center_x_pct"),
                "center_y_pct": z.get("center_y_pct"),
                "polygon_points": z.get("polygon_points"),
                "fill_color": z.get("fill_color"),
                "open_incident_count": len(open_inc_here),
                "agents_here": agents_here,
                "open_incidents": open_inc_here,
            }
        )

    checkpoint_cards: list[dict[str, Any]] = []
    for cp in checkpoints_source:
        cpkey = str(cp.get("checkpoint_key") or "")
        cp_agents = [
            {
                "agent_id": a["agent_id"],
                "full_name": a["full_name"],
                "role_title": a["role_title"],
                "group_type": a["group_type"],
                "current_activity": a["current_activity"],
                "movement_status": a["movement_status"],
            }
            for a in agent_statuses
            if a.get("current_checkpoint_key") == cpkey
        ]
        checkpoint_cards.append(
            {
                "id": cp.get("id"),
                "checkpoint_key": cpkey,
                "name": cp.get("name", cpkey),
                "x_pct": cp.get("x_pct"),
                "y_pct": cp.get("y_pct"),
                "icon_emoji": cp.get("icon_emoji") or "📍",
                "description_md": cp.get("description_md") or "",
                "zone_key": cp.get("zone_key"),
                "category": cp.get("category") or "general",
                "agents_here": cp_agents,
            }
        )

    return {
        "success": True,
        "project": proj_meta,
        "digital_map": digital_map_meta,
        "run": run_payload,
        "sim_clock": sim_clock,
        "cost": cost_info,
        "stream_counts": stream_counts,
        "latest_seq": latest_seq,
        "zones": zone_cards,
        "checkpoints": checkpoint_cards,
        "agent_statuses": agent_statuses,
        "recent_movements": list(reversed(list(recent_movements))),
        "incidents": incidents,
    }


@router.get("/projects/{project_id}/runs/{run_id}/events")
async def get_run_events(
    project_id: str,
    run_id: str,
    since_seq: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    stream: str = Query("ALL"),
    agent_id: int | None = Query(None),
):
    """Đọc luồng sự kiện phân tách (COMM/WEB/ATLAS/INCIDENT) dạng incremental cursor `since_seq`."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _, _, run_dir = _require_run_and_dir(session, ws, project_id, run_id)

    events_path = run_dir / "urban_events.jsonl"
    if not events_path.is_file():
        return {"success": True, "items": [], "latest_seq": since_seq, "has_more": False}

    stream_norm = stream.strip().upper()
    matched: list[dict[str, Any]] = []
    file_latest_seq = since_seq
    with open(events_path, "r", encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            seq_val = int(ev.get("seq") or 0)
            if seq_val > file_latest_seq:
                file_latest_seq = seq_val
            if seq_val <= since_seq:
                continue
            if stream_norm and stream_norm != "ALL" and str(ev.get("stream") or "").upper() != stream_norm:
                continue
            if agent_id is not None and ev.get("agent_id") != agent_id:
                continue
            matched.append(ev)

    sliced = matched[:limit]
    has_more = len(matched) > limit
    returned_seq = int(sliced[-1]["seq"]) if sliced else file_latest_seq
    screenshots_dir = run_dir / "artifacts" / "screenshots"
    for ev in sliced:
        if str(ev.get("stream") or "").upper() == "WEB" and ev.get("screenshot_file"):
            st_status, st_bytes = classify_screenshot_file(
                screenshots_dir,
                ev.get("screenshot_file"),
                ev.get("details") if isinstance(ev.get("details"), dict) else None,
            )
            if st_status is not None:
                ev["screenshot_status"] = st_status
            if st_bytes is not None:
                ev["screenshot_bytes"] = st_bytes
    return {
        "success": True,
        "items": sliced,
        "latest_seq": returned_seq if has_more else file_latest_seq,
        "has_more": has_more,
    }


def _extract_atlas_qa_items(
    events_path: Path, agent_id: int | None = None
) -> list[dict[str, Any]]:
    """Đọc toàn bộ sự kiện luồng ATLAS từ ``urban_events.jsonl`` theo thứ tự ``seq`` tăng dần."""
    if not events_path.is_file():
        return []
    raw_events: list[dict[str, Any]] = []
    with open(events_path, "r", encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if str(ev.get("stream") or "").upper() != "ATLAS":
                continue
            if agent_id is not None and ev.get("agent_id") != agent_id:
                continue
            raw_events.append(ev)

    raw_events.sort(key=lambda item: int(item.get("seq") or 0))
    items: list[dict[str, Any]] = []
    for idx, ev in enumerate(raw_events, start=1):
        details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
        ok = bool(ev.get("ok"))
        question = str(details.get("question") or ev.get("summary") or "").strip()
        answer_markdown = str(details.get("answer") or "") if ok else ""
        error_text = (
            ""
            if ok
            else str(details.get("error") or details.get("answer") or ev.get("summary") or "")
        )
        items.append(
            {
                "index": idx,
                "seq": int(ev.get("seq") or 0),
                "sim_time": ev.get("sim_time"),
                "wall_time": ev.get("wall_time"),
                "agent_id": ev.get("agent_id"),
                "agent_name": str(ev.get("agent_name") or ""),
                "role_title": str(ev.get("role_title") or ""),
                "action": str(ev.get("action") or "ask_atlas_support"),
                "ok": ok,
                "bot_session_id": details.get("bot_session_id") or "",
                "assistant_message_id": details.get("assistant_message_id") or "",
                "route_hint": details.get("route_hint") or "",
                "mcp_used": bool(details.get("mcp_used")),
                "question": question,
                "answer_markdown": answer_markdown,
                "error": error_text,
                "evaluation_target": details.get("evaluation_target"),
            }
        )
    return items


def _render_atlas_qa_markdown(
    *,
    project_name: str,
    run: UrbanSimRun,
    items: list[dict[str, Any]],
    summary: dict[str, Any],
    exported_at: str,
    agent_id: int | None,
) -> str:
    """Kết xuất toàn bộ nội dung Hỏi Đáp CSKH thành tài liệu Markdown giữ nguyên Mermaid/bảng."""
    filter_label = f"Tác nhân #{agent_id}" if agent_id is not None else "Tất cả tác nhân"
    lines: list[str] = [
        f"# Hỏi Đáp CSKH — {project_name} (Run #{int(run.run_number)})",
        "",
        f"- **Run ID:** `{run.id}`",
        f"- **Trạng thái:** {run.status}",
        f"- **Tiến độ bước:** {int(run.step_count)} / {int(run.total_steps)}",
        f"- **Thời điểm xuất:** {exported_at}",
        f"- **Phạm vi lọc:** {filter_label}",
        (
            f"- **Tổng hợp:** {summary['total']} lượt "
            f"({summary['succeeded']} thành công, {summary['failed']} lỗi, "
            f"{summary['unique_agents']} tác nhân)"
        ),
        "",
    ]

    if not items:
        lines.append("_Chưa ghi nhận lượt hỏi đáp CSKH nào._")
        return "\n".join(lines) + "\n"

    for item in items:
        lines.extend(
            [
                "---",
                "",
                f"## {item['index']}. #{item['seq']} — {item['agent_name']}",
                "",
            ]
        )
        if item.get("role_title"):
            lines.append(f"- **Vai trò:** {item['role_title']}")
        if item.get("sim_time"):
            lines.append(f"- **Thời gian mô phỏng:** {item['sim_time']}")
        if item.get("wall_time"):
            lines.append(f"- **Thời gian thực:** {item['wall_time']}")
        if item.get("route_hint"):
            lines.append(f"- **Màn hình QLTN:** `{item['route_hint']}`")
        if item.get("bot_session_id"):
            lines.append(f"- **Session:** `{item['bot_session_id']}`")
        if item.get("assistant_message_id"):
            lines.append(f"- **Message ID:** `{item['assistant_message_id']}`")
        lines.append(f"- **Trạng thái:** {'Thành công' if item['ok'] else 'Lỗi'}")
        lines.extend(["", "### Câu hỏi", "", item["question"] or "_(Trống)_", ""])

        if item["ok"]:
            lines.extend(
                [
                    "### Trả lời CSKH",
                    "",
                    item["answer_markdown"].rstrip() if item["answer_markdown"] else "_(Không có nội dung)_",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "### Lỗi phản hồi",
                    "",
                    item["error"].rstrip() if item["error"] else "_(Không rõ lỗi)_",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


@router.get("/projects/{project_id}/runs/{run_id}/atlas-qa/export")
async def export_run_atlas_qa(
    project_id: str,
    run_id: str,
    format: Literal["markdown", "json"] = Query("markdown"),
    agent_id: int | None = Query(None),
):
    """Xuất toàn bộ nội dung Hỏi Đáp CSKH của Run ra file Markdown (.md) hoặc JSON (.json)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        project_name = proj.name
        run_meta = {
            "id": run.id,
            "run_number": int(run.run_number),
            "status": run.status,
            "step_count": int(run.step_count),
            "total_steps": int(run.total_steps),
            "pilot_mode": bool(run.pilot_mode),
            "router_type": run.router_type,
        }
        proj_meta = {"id": proj.id, "name": proj.name}

    items = _extract_atlas_qa_items(run_dir / "urban_events.jsonl", agent_id=agent_id)
    succeeded = sum(1 for item in items if item["ok"])
    failed = len(items) - succeeded
    unique_agents = len({item["agent_id"] for item in items if item.get("agent_id") is not None})
    summary = {
        "total": len(items),
        "succeeded": succeeded,
        "failed": failed,
        "unique_agents": unique_agents,
    }
    exported_at = _utcnow_iso()
    safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_meta["id"])
    suffix = f"_agent_{agent_id}" if agent_id is not None else ""
    ext = "md" if format == "markdown" else "json"
    filename = f"cskh-qa-run-{run_meta['run_number']}-{safe_run}{suffix}.{ext}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }

    if format == "json":
        payload = {
            "exported_at": exported_at,
            "project": proj_meta,
            "run": run_meta,
            "filter": {"agent_id": agent_id},
            "summary": summary,
            "items": items,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers=headers,
        )

    md_text = _render_atlas_qa_markdown(
        project_name=project_name,
        run=run,
        items=items,
        summary=summary,
        exported_at=exported_at,
        agent_id=agent_id,
    )
    return Response(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.get("/projects/{project_id}/runs/{run_id}/agents/{agent_id}/timeline")
async def get_run_agent_timeline(project_id: str, run_id: str, agent_id: int):
    """Dòng lịch sử nhận thức, suy nghĩ, hành động và bằng chứng theo từng Persona."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _, _, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        persona_row = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .where(UrbanSimPersona.agent_id == agent_id)
        ).first()
        if persona_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy Persona agent_id={agent_id} trong dự án.",
            )
        persona_dict = {
            "agent_id": int(persona_row.agent_id),
            "full_name": persona_row.full_name,
            "role_code": persona_row.role_code,
            "role_title": persona_row.role_title,
            "department": persona_row.department,
            "group_type": persona_row.group_type,
            "home_zone": persona_row.home_zone,
            "software_access_enabled": bool(persona_row.software_access_enabled),
        }

    payload = await asyncio.to_thread(
        build_agent_timeline,
        run_dir=run_dir,
        persona=persona_dict,
    )
    return {"success": True, **payload}


@router.get("/projects/{project_id}/runs/{run_id}/llm-stats")
async def get_run_llm_stats(project_id: str, run_id: str):
    """Chi phí token USD/VND chi tiết theo từng Model (bao gồm Cache Hit Rate & Ngân sách)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, _, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        budget = float(proj.max_cost_usd_per_run or 0.0)

    llm_raw = _read_json_file(run_dir / LLM_STATS_JSON)
    cost = compute_run_cost(llm_raw)
    budget_pct = (
        round(min(100.0, (float(cost.get("cost_usd", 0.0)) / budget) * 100.0), 1)
        if budget > 0
        else 0.0
    )
    return {
        "success": True,
        "max_cost_usd_per_run": budget,
        "budget_pct": budget_pct,
        **cost,
    }


@router.get("/projects/{project_id}/runs/{run_id}/screenshots/{filename}")
async def get_run_screenshot(project_id: str, run_id: str, filename: str):
    """Stream ảnh chụp thao tác trình duyệt Playwright của nhân sự BQL (chặn path traversal)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _, _, run_dir = _require_run_and_dir(session, ws, project_id, run_id)

    target = resolve_urban_sim_screenshot(run_dir, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh chụp màn hình.")
    return FileResponse(
        target,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/projects/{project_id}/runs/{run_id}/support-feedback")
async def send_support_feedback(
    project_id: str, run_id: str, payload: SupportFeedbackRequest
):
    """Gửi đánh giá LIKE/DISLIKE câu trả lời CSKH từ UI đồng bộ về EvidenceAtlas."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_run_and_dir(session, ws, project_id, run_id)
        cfg = session.get(UrbanSimAtlasConfig, project_id)
        if cfg is None or not (cfg.atlas_api_key_enc or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Chưa cấu hình EvidenceAtlas API Key trong dự án.",
            )
        try:
            atlas_url = validate_external_url(cfg.atlas_api_url).rstrip("/")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api_key = decrypt_secret(cfg.atlas_api_key_enc, ws)

    endpoint = f"{atlas_url}/api/v1/project/agent-messages/feedback"
    req_body: dict[str, Any] = {
        "message_id": payload.message_id.strip(),
        "session_id": payload.session_id.strip(),
        "source_kind": "QA_BOT",
        "vote": payload.vote,
        "reason": payload.reason.strip(),
    }
    if payload.vote == "DISLIKE":
        req_body["category"] = payload.category

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                endpoint,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json=req_body,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"Lỗi kết nối EvidenceAtlas: {exc}"
        ) from exc

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"EvidenceAtlas feedback lỗi ({resp.status_code}): {resp.text[:300]}",
        )
    return {"success": True, "status_code": resp.status_code}


# ==================== BQL COMPETENCY EVALUATION & AI AUDITOR ====================


def _persona_rows_to_fallback_dicts(personas: list[UrbanSimPersona]) -> list[dict[str, Any]]:
    return [
        {
            "agent_id": int(p.agent_id),
            "full_name": p.full_name,
            "role_code": p.role_code,
            "role_title": p.role_title,
            "department": p.department,
            "group_type": p.group_type,
            "home_zone": p.home_zone,
            "software_access_enabled": bool(p.software_access_enabled),
        }
        for p in personas
    ]


@router.get("/rubric-default")
async def get_default_rubric():
    """Trả về chuẩn Rubric mặc định (MulberryLane / QLTN v2) làm Single Source of Truth cho Frontend."""
    return {
        "success": True,
        "rubric": DEFAULT_MULBERRYLANE_RUBRIC.model_dump(),
    }


@router.get("/projects/{project_id}/runs/{run_id}/competency")
async def get_run_competency(project_id: str, run_id: str):
    """Đánh giá năng lực sử dụng QLTN và tri thức BQL theo Miller's Pyramid + 4 trục khoa học."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        personas = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .order_by(UrbanSimPersona.agent_id)
        ).all()
        rubric_json = getattr(proj, "competency_rubric_json", None)
        fallback = _persona_rows_to_fallback_dicts(list(personas))
        run_meta = {
            "id": run.id,
            "run_number": int(run.run_number),
            "status": run.status,
            "step_count": int(run.step_count),
            "total_steps": int(run.total_steps),
        }

    report = await asyncio.to_thread(
        evaluate_run_competency,
        run_dir=run_dir,
        project_rubric_json=rubric_json,
        fallback_personas=fallback,
    )
    return {"success": True, "data": {**report, "run": run_meta}}


class CompetencyAiAuditRequest(BaseModel):
    judge_llm_config_id: str = Field(..., min_length=1, max_length=128)


@router.post("/projects/{project_id}/runs/{run_id}/competency/ai-audit", status_code=202)
async def start_run_competency_ai_audit(
    project_id: str,
    run_id: str,
    payload: CompetencyAiAuditRequest,
):
    """Khởi chạy AI Auditor (G-Eval) bất đồng bộ theo yêu cầu cho 1 Run (khóa 409 nếu đang chạy)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        personas = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .order_by(UrbanSimPersona.agent_id)
        ).all()
        fallback = _persona_rows_to_fallback_dicts(list(personas))
        run_meta = {
            "id": run.id,
            "run_number": int(run.run_number),
            "status": run.status,
            "step_count": int(run.step_count),
            "total_steps": int(run.total_steps),
        }
        status_payload = await get_competency_audit_manager().start_audit(
            run_id=run_id,
            run_dir=run_dir,
            run_meta=run_meta,
            judge_llm_config_id=payload.judge_llm_config_id,
            workspace_root=ws,
            session=session,
            project_rubric_json=getattr(proj, "competency_rubric_json", None),
            fallback_personas=fallback,
        )
    return {"success": True, "data": status_payload}


@router.get("/projects/{project_id}/runs/{run_id}/competency/ai-audit")
async def get_run_competency_ai_audit(
    project_id: str,
    run_id: str,
    version: int | None = Query(None, ge=1),
):
    """Đọc trạng thái và danh sách các phiên bản chẩn đoán AI Auditor (v{N}) của Run."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _, _, run_dir = _require_run_and_dir(session, ws, project_id, run_id)

    audit_state = get_competency_audit_manager().get_audit_state(run_dir, version=version)
    return {"success": True, "data": audit_state}


@router.get("/projects/{project_id}/runs/{run_id}/competency/export")
async def export_run_competency(
    project_id: str,
    run_id: str,
    format: Literal["markdown", "json"] = Query("markdown"),
    audit_version: int | None = Query(None, ge=1),
):
    """Xuất báo cáo Đánh giá Năng lực BQL dạng Markdown (.md) hoặc JSON (.json) an toàn."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        personas = session.exec(
            select(UrbanSimPersona)
            .where(UrbanSimPersona.project_id == project_id)
            .order_by(UrbanSimPersona.agent_id)
        ).all()
        fallback = _persona_rows_to_fallback_dicts(list(personas))
        rubric_json = getattr(proj, "competency_rubric_json", None)
        proj_meta = {"id": proj.id, "name": proj.name}
        run_meta = {
            "id": run.id,
            "run_number": int(run.run_number),
            "status": run.status,
            "step_count": int(run.step_count),
            "total_steps": int(run.total_steps),
        }

    report = await asyncio.to_thread(
        evaluate_run_competency,
        run_dir=run_dir,
        project_rubric_json=rubric_json,
        fallback_personas=fallback,
    )
    audit_state = get_competency_audit_manager().get_audit_state(run_dir, version=audit_version)
    audit_result = audit_state.get("selected_result")

    safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_meta["id"])
    ext = "md" if format == "markdown" else "json"
    filename = f"competency-run-{run_meta['run_number']}-{safe_run}.{ext}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }

    if format == "json":
        payload = {
            "exported_at": _utcnow_iso(),
            "project": proj_meta,
            "run": run_meta,
            "competency": report,
            "ai_audit": audit_result,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers=headers,
        )

    md_text = render_competency_markdown(
        project_meta=proj_meta,
        run_meta=run_meta,
        report=report,
        audit_result=audit_result,
    )
    return Response(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )

