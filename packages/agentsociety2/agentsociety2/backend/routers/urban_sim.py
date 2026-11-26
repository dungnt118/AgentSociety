"""Dynamic Urban Simulation REST API Control Plane (/api/v1/urban-sim/*)."""

from __future__ import annotations

import asyncio
import json
import re
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
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    UrbanSimZone,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.backend.services.urban_sim.lifecycle import (
    UrbanSimLifecycleManager,
    compute_run_cost,
    derive_execution_phase,
)
from agentsociety2.backend.services.urban_sim.seed_mulberrylane import (
    MULBERRYLANE_PERSONAS,
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


def _serialize_persona(p: UrbanSimPersona) -> dict[str, Any]:
    has_pw = bool(p.login_password_enc and p.login_password_enc.strip())
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
        "domain_knowledge_prompt": p.domain_knowledge_prompt,
        "initial_tasks": [str(x) for x in _parse_json_list(p.initial_tasks_json)],
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
        "llm_config_id": project.llm_config_id,
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
    domain_knowledge_prompt: str = ""
    initial_tasks: list[str] = Field(default_factory=list)
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
    domain_knowledge_prompt: str | None = None
    initial_tasks: list[str] | None = None
    portal_url: str | None = None
    login_username: str | None = None
    login_password: str | None = None
    clear_password: bool = False


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


class ZoneCreateRequest(BaseModel):
    zone_key: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=160)
    zone_type: Literal["LOBBY", "OFFICE", "TECHNICAL", "SECURITY", "TOWER"] = "OFFICE"
    description: str = ""
    sort_order: int = 99


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
            llm_config_id=payload.llm_config_id,
            enable_competency_prepost_quiz=bool(payload.enable_competency_prepost_quiz),
            competency_rubric_json=clean_rubric,
        )
        session.add(project)
        session.flush()
        if payload.seed_mulberrylane_template:
            for z_key, z_name, z_type, z_desc, z_order in MULBERRYLANE_ZONES:
                session.add(
                    UrbanSimZone(
                        project_id=project.id,
                        zone_key=z_key,
                        name=z_name,
                        zone_type=z_type,
                        description=z_desc,
                        sort_order=z_order,
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
            home_zone=payload.home_zone.strip() or "LOBBY_MAIN",
            domain_knowledge_prompt=payload.domain_knowledge_prompt.strip(),
            initial_tasks_json=json.dumps(payload.initial_tasks, ensure_ascii=False),
            portal_url=clean_portal,
            login_username=payload.login_username.strip() if payload.login_username else None,
            login_password_enc=pw_enc,
        )
        session.add(persona)
        session.commit()
        session.refresh(persona)
        return {"success": True, "persona": _serialize_persona(persona)}


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
            persona.home_zone = payload.home_zone.strip() or "LOBBY_MAIN"
        if payload.domain_knowledge_prompt is not None:
            persona.domain_knowledge_prompt = payload.domain_knowledge_prompt.strip()
        if payload.initial_tasks is not None:
            persona.initial_tasks_json = json.dumps(
                [str(t).strip() for t in payload.initial_tasks if str(t).strip()],
                ensure_ascii=False,
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


# ==================== ZONES & 2D FLOORPLAN MAP ENDPOINTS ====================


@router.get("/projects/{project_id}/zones")
async def list_zones(project_id: str):
    """Liệt kê danh sách các khu vực (Zone Topology) của dự án."""
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
        return {
            "success": True,
            "has_zone_map_image": bool(proj.zone_map_image_rel),
            "items": [
                {
                    "id": z.id,
                    "project_id": z.project_id,
                    "zone_key": z.zone_key,
                    "name": z.name,
                    "zone_type": z.zone_type,
                    "description": z.description,
                    "sort_order": int(z.sort_order),
                }
                for z in rows
            ],
        }


@router.post("/projects/{project_id}/zones")
async def create_zone(project_id: str, payload: ZoneCreateRequest):
    """Thêm Zone mới cho dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        key_norm = payload.zone_key.strip().upper().replace(" ", "_")
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
            sort_order=payload.sort_order,
        )
        session.add(zone)
        session.commit()
        session.refresh(zone)
        return {
            "success": True,
            "zone": {
                "id": zone.id,
                "project_id": zone.project_id,
                "zone_key": zone.zone_key,
                "name": zone.name,
                "zone_type": zone.zone_type,
                "description": zone.description,
                "sort_order": int(zone.sort_order),
            },
        }


@router.delete("/projects/{project_id}/zones/{zone_id}")
async def delete_zone(project_id: str, zone_id: str):
    """Xóa một Zone khỏi dự án."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        _require_project(session, project_id)
        zone = session.get(UrbanSimZone, zone_id)
        if zone is None or zone.project_id != project_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy Zone.")
        session.delete(zone)
        session.commit()
        return {"success": True, "deleted_id": zone_id}


@router.post("/projects/{project_id}/zones/map-image")
async def upload_zone_map_image(project_id: str, file: UploadFile = File(...)):
    """Upload ảnh sơ đồ 2D mặt bằng khu đô thị (chỉ PNG/JPEG/WEBP <= 5MB, kiểm magic bytes)."""
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

    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if proj.zone_map_image_rel:
            try:
                old_path = resolve_urban_sim_map_image(ws, proj.zone_map_image_rel)
                old_path.unlink(missing_ok=True)
            except HTTPException:
                pass
        filename = f"{project_id}.{ext}"
        dest = resolve_urban_sim_map_image(ws, filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        proj.zone_map_image_rel = filename
        proj.updated_at = _utcnow_iso()
        session.add(proj)
        session.commit()
        return {"success": True, "filename": filename, "size_bytes": len(data)}


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
async def delete_zone_map_image(project_id: str):
    """Xóa ảnh sơ đồ 2D tùy chọn để quay về hiển thị thẻ Topology thuần túy."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    with Session(engine) as session:
        proj = _require_project(session, project_id)
        if proj.zone_map_image_rel:
            try:
                resolve_urban_sim_map_image(ws, proj.zone_map_image_rel).unlink(missing_ok=True)
            except HTTPException:
                pass
            proj.zone_map_image_rel = None
            proj.updated_at = _utcnow_iso()
            session.add(proj)
            session.commit()
        return {"success": True}


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

    step_meta = _read_json_file(run_dir / SOCIETY_STEP_JSON)
    current_raw = str(step_meta.get("current_time") or "").strip() or None

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


@router.get("/projects/{project_id}/runs/{run_id}/state")
async def get_run_state(project_id: str, run_id: str):
    """Trạng thái tổng hợp thời gian thực của Run (KPIs, Sim Clock, Zone Topology, Incidents, Agents, Cost)."""
    ws = _ws_root()
    init_urban_sim_db(ws)
    engine = get_engine(ws)
    mgr = get_lifecycle_manager()
    with Session(engine) as session:
        proj, run, run_dir = _require_run_and_dir(session, ws, project_id, run_id)
        mgr._sync_run_metrics(session, run)
        session.commit()
        session.refresh(run)

        zones = session.exec(
            select(UrbanSimZone)
            .where(UrbanSimZone.project_id == project_id)
            .order_by(UrbanSimZone.sort_order)
        ).all()
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
        proj_meta = {
            "id": proj.id,
            "name": proj.name,
            "has_zone_map_image": bool(proj.zone_map_image_rel),
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

    stream_counts = {"COMM": 0, "WEB": 0, "ATLAS": 0, "INCIDENT": 0}
    events_path = run_dir / "urban_events.jsonl"
    latest_seq = 0
    per_agent_events: dict[int, dict[str, Any]] = {}
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
                            "action": str(ev.get("action") or ""),
                            "stream": st,
                            "summary": str(ev.get("summary") or "").strip(),
                            "sim_time": ev.get("sim_time"),
                            "ok": ev_ok,
                        }

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

        agent_statuses.append(
            {
                "agent_id": p.agent_id,
                "full_name": p.full_name,
                "role_code": p.role_code,
                "role_title": p.role_title,
                "department": p.department,
                "group_type": p.group_type,
                "software_access_enabled": bool(p.software_access_enabled),
                "current_zone": str(agent_zones.get(aid_str) or p.home_zone),
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

    zone_cards: list[dict[str, Any]] = []
    for z in zones:
        agents_here = [
            {
                "agent_id": a["agent_id"],
                "full_name": a["full_name"],
                "role_title": a["role_title"],
                "group_type": a["group_type"],
            }
            for a in agent_statuses
            if a["current_zone"] == z.zone_key
        ]
        open_inc_here = [
            inc
            for inc in incidents
            if inc.get("zone_key") == z.zone_key and inc.get("status") != "RESOLVED"
        ]
        zone_cards.append(
            {
                "zone_key": z.zone_key,
                "name": z.name,
                "zone_type": z.zone_type,
                "description": z.description,
                "agents_here": agents_here,
                "open_incidents": open_inc_here,
            }
        )

    return {
        "success": True,
        "project": proj_meta,
        "run": run_payload,
        "sim_clock": sim_clock,
        "cost": cost_info,
        "stream_counts": stream_counts,
        "latest_seq": latest_seq,
        "zones": zone_cards,
        "incidents": incidents,
        "agent_statuses": agent_statuses,
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

