"""Unified REST API Control Plane endpoints (/api/*) backed by AgentSociety v2 SQLite."""

from __future__ import annotations

import json
import secrets
import time
import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
import httpx
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agentsociety2.backend.path_security import (
    _configured_workspace_root,
    resolve_under_root,
    resolve_urban_sim_run_dir,
)
from agentsociety2.backend.services.platform_resources import (
    PlatformAgentConfig,
    PlatformAgentProfile,
    PlatformAgentTemplate,
    PlatformExperiment,
    PlatformLLMConfig,
    PlatformMapConfig,
    PlatformSurvey,
    PlatformWorkflowConfig,
    _is_mask_value,
    _safe_json,
    ensure_platform_seed,
    merge_llm_entries,
    serialize_agent_config,
    serialize_agent_profile,
    serialize_agent_template,
    serialize_llm_config,
    serialize_map_config,
    serialize_survey,
    serialize_workflow_config,
)
from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    validate_external_url,
)
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimProject,
    UrbanSimRun,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.config.llm_catalog import (
    DEFAULT_LLM_PROVIDER,
    find_catalog_model,
    get_llm_catalog_payload,
    get_model_pricing_per_1m,
    is_obsolete_model_id,
    resolve_provider_api_type,
    resolve_provider_base_url,
)
from agentsociety2.registry import get_registered_agent_modules, get_registry

router = APIRouter(prefix="/api", tags=["Platform Unified Resources"])

_MAX_PB_BYTES = 25 * 1024 * 1024
_MAX_IMAGE_OR_JSON_BYTES = 5 * 1024 * 1024
_TEMP_MAP_TOKENS: dict[str, tuple[str, float]] = {}

_RUN_STATUS_TO_LEGACY = {
    "CREATED": 0,
    "STARTING": 1,
    "RUNNING": 1,
    "PAUSING": 1,
    "RESUMING": 1,
    "COMPLETED": 2,
    "COMPLETED_WITH_ERRORS": 2,
    "FAILED": 3,
    "PAUSED": 4,
    "STOPPED": 4,
}


def _ws_root() -> Path:
    return Path(_configured_workspace_root()).resolve()


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _init_and_engine():
    ws = _ws_root()
    init_urban_sim_db(ws)
    ensure_platform_seed(ws)
    return ws, get_engine(ws)


def _safe_filename(raw_name: str | None, fallback: str = "upload.bin") -> str:
    base = Path((raw_name or "").replace("\\", "/")).name.strip()
    clean = "".join(ch if (ch.isalnum() or ch in {".", "_", "-"}) else "_" for ch in base)
    return clean or fallback


def _detect_map_upload(raw_bytes: bytes, filename: str) -> str:
    lower = filename.lower()
    if not lower.endswith(".pb"):
        raise HTTPException(
            status_code=415,
            detail=(
                "Cổng /maps chỉ chấp nhận bản đồ giao thông định dạng .pb (mosstool). "
                "Ảnh mặt bằng 2D và Bản đồ Số Khu đô thị được quản lý tại /urban-sim."
            ),
        )
    if len(raw_bytes) > _MAX_PB_BYTES:
        raise HTTPException(status_code=400, detail="File .pb vượt quá giới hạn 25 MB.")
    if raw_bytes.lstrip().startswith((b"<svg", b"<!DOCTYPE html", b"<html")):
        raise HTTPException(status_code=400, detail="File .pb không hợp lệ.")
    return "protobuf"


# ==================== SCHEMAS ====================


class ConfigPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    config: Any = Field(default_factory=list)


class AgentTemplatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    agent_type: str = "citizen"
    agent_class: str = "PersonAgent"
    memory_distributions: dict[str, Any] = Field(default_factory=dict)
    agent_params: dict[str, Any] = Field(default_factory=dict)
    blocks: dict[str, Any] = Field(default_factory=dict)


class SurveyPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    data: dict[str, Any] = Field(default_factory=dict)


class TempLinkRequest(BaseModel):
    expire_seconds: int = Field(600, ge=30, le=86400)


class ConfigPrimaryKey(BaseModel):
    tenant_id: str = "default"
    id: str


class RunExperimentRequest(BaseModel):
    llm: ConfigPrimaryKey
    agents: ConfigPrimaryKey
    map: ConfigPrimaryKey
    workflow: ConfigPrimaryKey
    exp_name: str = Field(..., min_length=1, max_length=200)


class LLMProbeRequest(BaseModel):
    provider: str = DEFAULT_LLM_PROVIDER
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    config_id: str | None = None
    entry_index: int = Field(0, ge=0, le=20)


def _resolve_probe_credentials(
    payload: LLMProbeRequest,
    ws: Path,
    engine: Any,
) -> tuple[str, str, str, str]:
    """Giải mã và kiểm tra SSRF cho endpoint cần dò model / test kết nối."""
    provider = (payload.provider or DEFAULT_LLM_PROVIDER).strip().lower()
    raw_base = (payload.base_url or "").strip()
    raw_key = (payload.api_key or "").strip()

    if _is_mask_value(raw_key) and payload.config_id:
        with Session(engine) as session:
            row = session.get(PlatformLLMConfig, payload.config_id)
            if row is not None:
                entries = _safe_json(row.config_json, [])
                if isinstance(entries, list) and payload.entry_index < len(entries):
                    entry = entries[payload.entry_index]
                    if isinstance(entry, dict):
                        enc = str(entry.get("api_key_enc") or "").strip()
                        if enc:
                            raw_key = decrypt_secret(enc, ws)
                        if not raw_base:
                            raw_base = str(entry.get("base_url") or "").strip()

    if _is_mask_value(raw_key):
        raw_key = ""
    if not raw_key and provider != "vllm":
        raise HTTPException(
            status_code=400,
            detail="Vui lòng nhập API Key (hoặc chọn cấu hình đã lưu key) trước khi kiểm tra.",
        )

    resolved_base = resolve_provider_base_url(provider, raw_base)
    try:
        safe_base = validate_external_url(
            resolved_base,
            allow_local=True if provider == "vllm" else None,
        ).rstrip("/")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    api_type = resolve_provider_api_type(provider)
    return provider, safe_base, raw_key, api_type


def _build_probe_headers(api_type: str, api_key: str) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_type == "anthropic":
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# ==================== LLM CATALOG & CONFIGS ====================


@router.get("/llm-catalog")
async def get_llm_catalog():
    """Trả về danh mục nhà cung cấp AI, danh sách mô hình chuẩn và bảng giá USD/1M tokens."""
    return {"data": get_llm_catalog_payload()}


@router.post("/llm-configs/fetch-models")
async def fetch_remote_llm_models(payload: LLMProbeRequest):
    """Đồng bộ danh sách mô hình khả dụng trực tiếp từ endpoint ``/models`` của nhà cung cấp."""
    ws, engine = _init_and_engine()
    provider, safe_base, api_key, api_type = _resolve_probe_credentials(payload, ws, engine)
    url = f"{safe_base}/models"
    headers = _build_probe_headers(api_type, api_key)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Quá thời gian chờ phản hồi từ {url} (15s).",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Không thể kết nối tới {url}: {exc!s}",
        ) from exc

    if resp.status_code >= 400:
        detail_msg = resp.text[:300].strip() or f"HTTP {resp.status_code}"
        raise HTTPException(
            status_code=400 if resp.status_code in (401, 403, 404) else 502,
            detail=f"Endpoint trả lỗi HTTP {resp.status_code}: {detail_msg}",
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Endpoint /models không trả về JSON hợp lệ.",
        ) from exc

    raw_list = body.get("data") if isinstance(body, dict) else body
    if not isinstance(raw_list, list):
        raw_list = body.get("models") if isinstance(body, dict) else []
    if not isinstance(raw_list, list):
        raw_list = []

    models_out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_list:
        if isinstance(item, str):
            mid = item.strip()
            display_name = mid
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or "").strip()
            display_name = str(item.get("display_name") or item.get("name") or mid).strip()
        else:
            continue
        if not mid or mid in seen_ids or is_obsolete_model_id(mid):
            continue
        seen_ids.add(mid)
        known = find_catalog_model(mid, provider)
        pricing = get_model_pricing_per_1m(mid)
        models_out.append(
            {
                "model_id": mid,
                "display_name": known["display_name"] if known else display_name,
                "context_window": known["context_window"] if known else (item.get("context_length") if isinstance(item, dict) else None),
                "max_output_tokens": known["max_output_tokens"] if known else None,
                "supports_reasoning": known["supports_reasoning"] if known else None,
                "input_usd_per_1m": pricing["input_usd_per_1m"],
                "cached_input_usd_per_1m": pricing["cached_input_usd_per_1m"],
                "output_usd_per_1m": pricing["output_usd_per_1m"],
                "in_verified_catalog": known is not None,
            }
        )

    models_out.sort(key=lambda m: (not m["in_verified_catalog"], m["model_id"].lower()))
    return {
        "data": {
            "provider": provider,
            "resolved_base_url": safe_base,
            "total_remote": len(raw_list),
            "models": models_out,
        }
    }


@router.post("/llm-configs/test-connection")
async def test_llm_connection(payload: LLMProbeRequest):
    """Kiểm tra kết nối API Key và sự tồn tại của mô hình trên nhà cung cấp."""
    ws, engine = _init_and_engine()
    provider, safe_base, api_key, api_type = _resolve_probe_credentials(payload, ws, engine)
    url = f"{safe_base}/models"
    headers = _build_probe_headers(api_type, api_key)
    target_model = (payload.model or "").strip()

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return {
            "data": {
                "ok": False,
                "status_code": 504,
                "latency_ms": round((time.monotonic() - t0) * 1000),
                "model_found": None,
                "models_count": 0,
                "resolved_base_url": safe_base,
                "message": f"Quá thời gian chờ phản hồi từ {url} (15s).",
            }
        }
    except httpx.RequestError as exc:
        return {
            "data": {
                "ok": False,
                "status_code": 502,
                "latency_ms": round((time.monotonic() - t0) * 1000),
                "model_found": None,
                "models_count": 0,
                "resolved_base_url": safe_base,
                "message": f"Lỗi kết nối mạng tới {url}: {exc!s}",
            }
        }

    latency_ms = round((time.monotonic() - t0) * 1000)
    if resp.status_code >= 400:
        return {
            "data": {
                "ok": False,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "model_found": None,
                "models_count": 0,
                "resolved_base_url": safe_base,
                "message": f"Xác thực hoặc endpoint thất bại (HTTP {resp.status_code}): {resp.text[:220].strip()}",
            }
        }

    remote_ids: list[str] = []
    try:
        body = resp.json()
        raw_list = body.get("data") if isinstance(body, dict) else body
        if not isinstance(raw_list, list) and isinstance(body, dict):
            raw_list = body.get("models")
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, str) and item.strip():
                    remote_ids.append(item.strip())
                elif isinstance(item, dict):
                    mid = str(item.get("id") or item.get("name") or "").strip()
                    if mid:
                        remote_ids.append(mid)
    except ValueError:
        remote_ids = []

    model_found: bool | None = None
    if target_model and remote_ids:
        target_lower = target_model.lower()
        model_found = any(
            rid.lower() == target_lower or rid.lower().endswith(f"/{target_lower}")
            for rid in remote_ids
        )

    msg = f"Kết nối thành công tới {safe_base} ({latency_ms} ms, tìm thấy {len(remote_ids)} mô hình)."
    if target_model and model_found is True:
        msg = f"Kết nối OK ({latency_ms} ms) — đã xác nhận mô hình '{target_model}' khả dụng."
    elif target_model and model_found is False:
        msg = (
            f"API Key hợp lệ ({latency_ms} ms, {len(remote_ids)} mô hình), "
            f"nhưng không thấy '{target_model}' trong danh sách /models."
        )

    return {
        "data": {
            "ok": True,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "model_found": model_found,
            "models_count": len(remote_ids),
            "resolved_base_url": safe_base,
            "message": msg,
        }
    }


@router.get("/llm-configs")
async def list_llm_configs():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformLLMConfig).order_by(PlatformLLMConfig.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_llm_config(r) for r in rows]}


@router.get("/llm-configs/{config_id}")
async def get_llm_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformLLMConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình LLM")
        return {"data": serialize_llm_config(row)}


@router.post("/llm-configs")
async def create_llm_config(payload: ConfigPayload):
    ws, engine = _init_and_engine()
    entries = payload.config if isinstance(payload.config, list) else []
    row = PlatformLLMConfig(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        config_json=merge_llm_entries(entries, None, ws),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_llm_config(row)}


@router.put("/llm-configs/{config_id}")
async def update_llm_config(config_id: str, payload: ConfigPayload):
    ws, engine = _init_and_engine()
    entries = payload.config if isinstance(payload.config, list) else []
    with Session(engine) as session:
        row = session.get(PlatformLLMConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình LLM")
        row.name = payload.name.strip()
        row.description = (payload.description or "").strip()
        row.config_json = merge_llm_entries(entries, row.config_json, ws)
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_llm_config(row)}


@router.delete("/llm-configs/{config_id}")
async def delete_llm_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformLLMConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình LLM")
        # Unlink any UrbanSimProject referencing this LLM config
        linked_projects = session.exec(
            select(UrbanSimProject).where(UrbanSimProject.llm_config_id == config_id)
        ).all()
        for proj in linked_projects:
            proj.llm_config_id = None
            session.add(proj)
        session.delete(row)
        session.commit()
        return {"data": {"deleted": config_id}}


# ==================== MAP CONFIGS ====================


@router.get("/map-configs")
async def list_map_configs():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformMapConfig).order_by(PlatformMapConfig.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        proj_ids = {r.linked_project_id for r in rows if r.linked_project_id}
        proj_names: dict[str, str] = {}
        if proj_ids:
            for proj in session.exec(select(UrbanSimProject)).all():
                if proj.id in proj_ids:
                    proj_names[proj.id] = proj.name
        return {
            "data": [
                serialize_map_config(
                    r,
                    linked_project_name=proj_names.get(r.linked_project_id or ""),
                )
                for r in rows
            ]
        }


@router.get("/map-configs/{config_id}")
async def get_map_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
        linked_name: str | None = None
        if row.linked_project_id:
            proj = session.get(UrbanSimProject, row.linked_project_id)
            linked_name = proj.name if proj is not None else None
        return {"data": serialize_map_config(row, linked_project_name=linked_name)}


@router.post("/map-configs/-/upload")
async def upload_map_file(file: UploadFile = File(...)):
    ws, _ = _init_and_engine()
    raw = await file.read()
    clean_name = _safe_filename(file.filename, "upload.bin")
    map_type = _detect_map_upload(raw, clean_name)

    target_dir = resolve_under_root(ws, ".agentsociety", "platform_uploads", "maps")
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:8]}_{clean_name}"
    dest = resolve_under_root(target_dir, stored_name)
    dest.write_bytes(raw)
    rel = f".agentsociety/platform_uploads/maps/{stored_name}"
    return {"data": {"file_path": rel, "map_type": map_type}}


@router.post("/map-configs")
async def create_map_config(payload: ConfigPayload):
    _, engine = _init_and_engine()
    cfg = payload.config if isinstance(payload.config, dict) else {}
    file_path = str(cfg.get("file_path") or "").strip()
    map_type = str(cfg.get("map_type") or "").strip()
    if map_type == "image_2d" or file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
        raise HTTPException(
            status_code=400,
            detail="Không thể tạo bản đồ ảnh 2D tại /maps. Vui lòng tạo Bản đồ Số trong Mô phỏng Khu đô thị (/urban-sim).",
        )
    if not file_path:
        file_path = "maps/default_map.pb"
    if not map_type:
        map_type = "urban_zones" if file_path.startswith("urban_sim://") else "protobuf"
    row = PlatformMapConfig(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        file_path=file_path,
        map_type=map_type,
        linked_project_id=cfg.get("linked_project_id"),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_map_config(row)}


@router.put("/map-configs/{config_id}")
async def update_map_config(config_id: str, payload: ConfigPayload):
    _, engine = _init_and_engine()
    cfg = payload.config if isinstance(payload.config, dict) else {}
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
        is_urban_linked = row.map_type == "urban_zones" or bool((row.linked_project_id or "").strip())
        next_file_path = str(cfg["file_path"]).strip() if cfg.get("file_path") else None
        next_map_type = str(cfg["map_type"]).strip() if cfg.get("map_type") else None
        if is_urban_linked and (
            (next_file_path is not None and next_file_path != row.file_path)
            or (next_map_type is not None and next_map_type != row.map_type)
        ):
            raise HTTPException(
                status_code=409,
                detail="Bản đồ liên kết với Dự án Mô phỏng Khu đô thị (/urban-sim) không thể sửa tệp .pb hoặc loại bản đồ tại đây.",
            )
        if next_map_type == "image_2d":
            raise HTTPException(
                status_code=400,
                detail="Không hỗ trợ gán map_type='image_2d' tại /maps. Hãy sử dụng Bản đồ Số trong /urban-sim.",
            )
        row.name = payload.name.strip()
        row.description = (payload.description or "").strip()
        if next_file_path:
            row.file_path = next_file_path
        if next_map_type:
            row.map_type = next_map_type
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_map_config(row)}


@router.delete("/map-configs/{config_id}")
async def delete_map_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
        if row.map_type == "urban_zones":
            raise HTTPException(
                status_code=409,
                detail="Không thể xóa bản đồ liên kết UrbanSim (urban_zones) từ menu /maps. Hãy quản lý trực tiếp trong /urban-sim.",
            )
        if row.linked_project_id and session.get(UrbanSimProject, row.linked_project_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="Bản đồ đang liên kết tới Dự án UrbanSim còn tồn tại; không thể xóa tại /maps.",
            )
        session.delete(row)
        session.commit()
        return {"data": {"deleted": config_id}}


@router.post("/map-configs/{config_id}/temp-link")
async def create_map_temp_link(config_id: str, body: TempLinkRequest | None = None):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
    ttl = body.expire_seconds if body else 600
    token = secrets.token_urlsafe(24)
    _TEMP_MAP_TOKENS[token] = (config_id, time.time() + ttl)
    return {"data": {"token": token}}


@router.get("/map-configs/{config_id}/temp-link")
async def resolve_map_temp_link(config_id: str, token: str = Query(...)):
    entry = _TEMP_MAP_TOKENS.get(token)
    if entry is None or entry[0] != config_id or entry[1] < time.time():
        raise HTTPException(status_code=403, detail="Liên kết tạm đã hết hạn hoặc không hợp lệ")
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
        return {"data": serialize_map_config(row)}


@router.post("/map-configs/{config_id}/export")
async def export_map_config(config_id: str):
    ws, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformMapConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản đồ")
        if row.file_path and not row.file_path.startswith("urban_sim://"):
            p = Path(row.file_path)
            if not p.is_absolute():
                p = resolve_under_root(ws, row.file_path)
            if p.is_file():
                return FileResponse(path=p, filename=p.name)
        payload = json.dumps(serialize_map_config(row), ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="map_{config_id}.json"'},
        )


# ==================== AGENT TEMPLATES, CLASSES & BLOCKS ====================


@router.get("/agent-classes")
async def list_agent_classes(agent_type: str | None = Query(None)):
    _ = get_registry()
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    if agent_type == "supervisor":
        items.append({"value": "BQLReActSupervisor", "label": "BQLReActSupervisor (AgentSociety v2)"})
        seen.add("BQLReActSupervisor")
    else:
        items.append({"value": "PersonAgent", "label": "PersonAgent (AgentSociety v2)"})
        seen.add("PersonAgent")
        for reg_name, reg_cls in get_registered_agent_modules():
            cname = getattr(reg_cls, "__name__", str(reg_name))
            if cname not in seen:
                seen.add(cname)
                items.append({"value": cname, "label": f"{cname} ({reg_name})"})
    return {"data": items}


@router.get("/agent-param")
async def get_agent_param(
    agent_type: str = Query("citizen"),
    agent_class: str = Query("PersonAgent"),
):
    return {
        "data": {
            "params_type": [
                {
                    "name": "max_react_turns",
                    "type": "int",
                    "description": "Số lượt suy luận ReAct tối đa mỗi tick nghiệp vụ",
                    "default": 6,
                    "required": False,
                },
                {
                    "name": "software_knowledge",
                    "type": "select",
                    "description": "Mức độ hiểu biết phần mềm ban đầu của Persona",
                    "default": "zero",
                    "required": False,
                    "options": [
                        {"label": "Con số 0 (học qua EvidenceAtlas)", "value": "zero"},
                        {"label": "Cơ bản", "value": "basic"},
                    ],
                },
                {
                    "name": "system_prompt",
                    "type": "str",
                    "description": f"Chỉ dẫn vai trò bổ sung cho {agent_class} ({agent_type})",
                    "default": "",
                    "required": False,
                },
            ],
            "context": [
                {"name": "role_title", "type": "str", "description": "Chức danh / Vai trò"},
                {"name": "home_zone", "type": "str", "description": "Khu vực phụ trách"},
                {"name": "tick", "type": "int", "description": "Bước thời gian hiện tại"},
            ],
            "status_attributes": [
                {"name": "current_zone", "type": "str", "description": "Vị trí zone hiện tại"},
                {"name": "open_incidents", "type": "int", "description": "Số sự vụ đang xử lý"},
            ],
        }
    }


@router.get("/agent-blocks")
async def list_agent_blocks():
    return {
        "data": [
            "UrbanCommIncidentEnv",
            "DemegoWebPortalEnv",
            "EvidenceAtlasSupportEnv",
            "DailyGuidanceSkill",
        ]
    }


@router.get("/block-param/{block_type}")
async def get_block_param(block_type: str):
    if block_type == "DemegoWebPortalEnv":
        params = [
            {
                "name": "guardrail_mode",
                "type": "select",
                "description": "Chế độ bảo vệ thao tác ghi trên cổng QLTN",
                "default": "SAFE_WRITE",
                "required": False,
                "options": [
                    {"label": "SAFE_WRITE (tiền tố [SIM-BQL])", "value": "SAFE_WRITE"},
                    {"label": "READ_ONLY", "value": "READ_ONLY"},
                    {"label": "FULL_RBAC", "value": "FULL_RBAC"},
                ],
            }
        ]
    elif block_type == "EvidenceAtlasSupportEnv":
        params = [
            {
                "name": "actor_persona",
                "type": "select",
                "description": "Ngữ cảnh hỏi đáp CSKH EvidenceAtlas",
                "default": "END_USER",
                "required": False,
                "options": [
                    {"label": "END_USER", "value": "END_USER"},
                    {"label": "OPERATOR", "value": "OPERATOR"},
                ],
            }
        ]
    else:
        params = []
    return {
        "data": {
            "params_type": params,
            "context": [{"name": "block_name", "type": "str", "description": block_type}],
        }
    }


@router.get("/agent-templates")
async def list_agent_templates():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformAgentTemplate).order_by(PlatformAgentTemplate.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_agent_template(r) for r in rows]}


@router.get("/agent-templates/{template_id}")
async def get_agent_template(template_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentTemplate, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy mẫu tác tử")
        return {"data": serialize_agent_template(row)}


@router.post("/agent-templates")
async def create_agent_template(payload: AgentTemplatePayload):
    _, engine = _init_and_engine()
    row = PlatformAgentTemplate(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        agent_type=payload.agent_type.strip(),
        agent_class=payload.agent_class.strip(),
        memory_distributions_json=json.dumps(payload.memory_distributions, ensure_ascii=False),
        agent_params_json=json.dumps(payload.agent_params, ensure_ascii=False),
        blocks_json=json.dumps(payload.blocks, ensure_ascii=False),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_agent_template(row)}


@router.put("/agent-templates/{template_id}")
async def update_agent_template(template_id: str, payload: AgentTemplatePayload):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentTemplate, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy mẫu tác tử")
        row.name = payload.name.strip()
        row.description = (payload.description or "").strip()
        row.agent_type = payload.agent_type.strip()
        row.agent_class = payload.agent_class.strip()
        row.memory_distributions_json = json.dumps(payload.memory_distributions, ensure_ascii=False)
        row.agent_params_json = json.dumps(payload.agent_params, ensure_ascii=False)
        row.blocks_json = json.dumps(payload.blocks, ensure_ascii=False)
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_agent_template(row)}


@router.delete("/agent-templates/{template_id}")
async def delete_agent_template(template_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentTemplate, template_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy mẫu tác tử")
        session.delete(row)
        session.commit()
        return {"data": {"deleted": template_id}}


# ==================== AGENT PROFILES ====================


@router.get("/agent-profiles")
async def list_agent_profiles():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformAgentProfile).order_by(PlatformAgentProfile.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_agent_profile(r) for r in rows]}


@router.get("/agent-profiles/{profile_id}")
async def get_agent_profile_data(profile_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentProfile, profile_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ cư dân")
        try:
            records = json.loads(row.records_json)
        except (TypeError, ValueError):
            records = []
        return {"data": records}


@router.post("/agent-profiles/upload")
async def upload_agent_profile(
    file: UploadFile = File(...),
    name: str = Form(""),
    description: str = Form(""),
):
    ws, engine = _init_and_engine()
    raw = await file.read()
    if len(raw) > _MAX_IMAGE_OR_JSON_BYTES:
        raise HTTPException(status_code=400, detail="File hồ sơ JSON vượt quá giới hạn 5 MB.")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"File JSON không hợp lệ: {exc}") from exc

    records = parsed if isinstance(parsed, list) else [parsed]
    clean_name = _safe_filename(name or file.filename, "profile.json")
    stored_dir = resolve_under_root(ws, ".agentsociety", "platform_uploads", "profiles")
    stored_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:8]}_{clean_name}"
    dest = resolve_under_root(stored_dir, stored_name)
    dest.write_bytes(raw)

    row = PlatformAgentProfile(
        name=name.strip() or clean_name,
        description=(description or "").strip(),
        agent_type="citizen",
        file_path=f"agent_profiles/default/{stored_name}",
        record_count=len(records),
        records_json=json.dumps(records, ensure_ascii=False),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_agent_profile(row)}


@router.delete("/agent-profiles/{profile_id}")
async def delete_agent_profile(profile_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentProfile, profile_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ cư dân")
        session.delete(row)
        session.commit()
        return {"data": {"deleted": profile_id}}


# ==================== AGENT CONFIGS ====================


@router.get("/agent-configs")
async def list_agent_configs():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformAgentConfig).order_by(PlatformAgentConfig.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_agent_config(r) for r in rows]}


@router.get("/agent-configs/{config_id}")
async def get_agent_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình cư dân")
        return {"data": serialize_agent_config(row)}


@router.post("/agent-configs")
async def create_agent_config(payload: ConfigPayload):
    _, engine = _init_and_engine()
    row = PlatformAgentConfig(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        config_json=json.dumps(payload.config if isinstance(payload.config, dict) else {}, ensure_ascii=False),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_agent_config(row)}


@router.put("/agent-configs/{config_id}")
async def update_agent_config(config_id: str, payload: ConfigPayload):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình cư dân")
        row.name = payload.name.strip()
        row.description = (payload.description or "").strip()
        row.config_json = json.dumps(payload.config if isinstance(payload.config, dict) else {}, ensure_ascii=False)
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_agent_config(row)}


@router.delete("/agent-configs/{config_id}")
async def delete_agent_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformAgentConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình cư dân")
        session.delete(row)
        session.commit()
        return {"data": {"deleted": config_id}}


# ==================== WORKFLOW CONFIGS & FUNCTIONS ====================


@router.get("/community/workflow/functions")
async def list_workflow_functions():
    return {
        "data": [
            "mulberrylane_daily_dispatch",
            "resident_incident_escalation",
            "evidence_atlas_cskh_lookup",
            "post_shift_satisfaction_survey",
        ]
    }


@router.get("/workflow-configs")
async def list_workflow_configs():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformWorkflowConfig).order_by(PlatformWorkflowConfig.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_workflow_config(r) for r in rows]}


@router.get("/workflow-configs/{config_id}")
async def get_workflow_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformWorkflowConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy quy trình")
        return {"data": serialize_workflow_config(row)}


@router.post("/workflow-configs")
async def create_workflow_config(payload: ConfigPayload):
    _, engine = _init_and_engine()
    row = PlatformWorkflowConfig(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        config_json=json.dumps(payload.config if isinstance(payload.config, list) else [], ensure_ascii=False),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_workflow_config(row)}


@router.put("/workflow-configs/{config_id}")
async def update_workflow_config(config_id: str, payload: ConfigPayload):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformWorkflowConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy quy trình")
        row.name = payload.name.strip()
        row.description = (payload.description or "").strip()
        row.config_json = json.dumps(payload.config if isinstance(payload.config, list) else [], ensure_ascii=False)
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_workflow_config(row)}


@router.delete("/workflow-configs/{config_id}")
async def delete_workflow_config(config_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformWorkflowConfig, config_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy quy trình")
        session.delete(row)
        session.commit()
        return {"data": {"deleted": config_id}}


# ==================== SURVEYS ====================


@router.get("/surveys")
async def list_surveys():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(PlatformSurvey).order_by(PlatformSurvey.updated_at.desc())  # type: ignore[union-attr]
        ).all()
        return {"data": [serialize_survey(r) for r in rows]}


@router.get("/surveys/{survey_id}")
async def get_survey(survey_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformSurvey, survey_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy khảo sát")
        return {"data": serialize_survey(row)}


@router.post("/surveys")
async def create_survey(payload: SurveyPayload):
    _, engine = _init_and_engine()
    row = PlatformSurvey(
        name=payload.name.strip(),
        data_json=json.dumps(payload.data or {}, ensure_ascii=False),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_survey(row)}


@router.put("/surveys/{survey_id}")
async def update_survey(survey_id: str, payload: SurveyPayload):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformSurvey, survey_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy khảo sát")
        row.name = payload.name.strip()
        row.data_json = json.dumps(payload.data or {}, ensure_ascii=False)
        row.updated_at = _utcnow_iso()
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"data": serialize_survey(row)}


@router.delete("/surveys/{survey_id}")
async def delete_survey(survey_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        row = session.get(PlatformSurvey, survey_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy khảo sát")
        session.delete(row)
        session.commit()
        return {"data": {"deleted": survey_id}}


# ==================== EXPERIMENTS & RUN EXPERIMENTS ====================


def _serialize_urban_run_as_experiment(
    run: UrbanSimRun,
    proj: UrbanSimProject | None,
) -> dict[str, Any]:
    proj_name = proj.name if proj else run.project_id
    return {
        "id": run.id,
        "name": f"[UrbanSim] {proj_name} — Run #{run.run_number}",
        "num_day": max(1, int(run.total_steps or 1)),
        "status": _RUN_STATUS_TO_LEGACY.get(run.status, 0),
        "cur_day": int(run.step_count or 0),
        "cur_t": int((run.step_count or 0) * (proj.tick_seconds if proj else 900)),
        "config": json.dumps(
            {
                "source": "urban_sim",
                "project_id": run.project_id,
                "run_id": run.id,
                "router_type": run.router_type,
                "pilot_mode": bool(run.pilot_mode),
                "active_agent_count": int(run.active_agent_count),
                "total_cost_usd": float(run.total_cost_usd or 0.0),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "error": run.error_message or "",
        "input_tokens": int(run.total_tokens or 0),
        "output_tokens": 0,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "urban_sim_project_id": run.project_id,
        "urban_sim_run_id": run.id,
    }


def _serialize_platform_experiment(row: PlatformExperiment) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "num_day": int(row.num_day),
        "status": int(row.status),
        "cur_day": int(row.cur_day),
        "cur_t": int(row.cur_t),
        "config": row.config_json,
        "error": row.error,
        "input_tokens": int(row.input_tokens),
        "output_tokens": int(row.output_tokens),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "urban_sim_project_id": row.linked_project_id,
        "urban_sim_run_id": row.linked_run_id,
    }


@router.get("/experiments")
async def list_unified_experiments():
    _, engine = _init_and_engine()
    with Session(engine) as session:
        urban_runs = session.exec(select(UrbanSimRun)).all()
        projects_by_id = {
            p.id: p for p in session.exec(select(UrbanSimProject)).all()
        }
        platform_exps = session.exec(select(PlatformExperiment)).all()

        combined = [
            _serialize_urban_run_as_experiment(r, projects_by_id.get(r.project_id))
            for r in urban_runs
        ] + [_serialize_platform_experiment(e) for e in platform_exps]
        combined.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"data": combined}


@router.get("/experiments/{exp_id}")
async def get_unified_experiment(exp_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            proj = session.get(UrbanSimProject, run.project_id)
            return {"data": _serialize_urban_run_as_experiment(run, proj)}
        exp = session.get(PlatformExperiment, exp_id)
        if exp is not None:
            return {"data": _serialize_platform_experiment(exp)}
        raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")


@router.delete("/experiments/{exp_id}")
async def delete_unified_experiment(exp_id: str):
    ws, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            if run.status in {"STARTING", "RUNNING", "PAUSING", "RESUMING"}:
                raise HTTPException(status_code=409, detail="Run đang chạy, hãy tạm dừng trước khi xóa.")
            safe_dir = resolve_urban_sim_run_dir(ws, run.run_dir)
            if safe_dir.exists():
                import shutil

                shutil.rmtree(safe_dir, ignore_errors=True)
            session.delete(run)
            session.commit()
            return {"data": {"deleted": exp_id}}

        exp = session.get(PlatformExperiment, exp_id)
        if exp is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")
        session.delete(exp)
        session.commit()
        return {"data": {"deleted": exp_id}}


def _zip_directory_or_payload(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            zf.writestr(arcname, content)
    return buf.getvalue()


@router.post("/experiments/{exp_id}/export")
@router.post("/experiments/{exp_id}/artifacts")
async def export_experiment_bundle(exp_id: str):
    ws, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            run_dir = resolve_urban_sim_run_dir(ws, run.run_dir)
            files: dict[str, bytes] = {}
            for candidate in ["output.log", "LLM_STATS.json", "SOCIETY_STEP.json", "pid.json"]:
                f = run_dir / candidate
                if f.is_file():
                    files[candidate] = f.read_bytes()
            if not files:
                files["summary.json"] = json.dumps(
                    _serialize_urban_run_as_experiment(run, session.get(UrbanSimProject, run.project_id)),
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
            zip_bytes = _zip_directory_or_payload(files)
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="experiment_{exp_id}.zip"'},
            )

        exp = session.get(PlatformExperiment, exp_id)
        if exp is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")
        files = {
            "experiment.json": json.dumps(
                _serialize_platform_experiment(exp), ensure_ascii=False, indent=2
            ).encode("utf-8")
        }
        if exp.log_path:
            log_file = Path(exp.log_path)
            if log_file.is_file():
                files["output.log"] = log_file.read_bytes()
        zip_bytes = _zip_directory_or_payload(files)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="experiment_{exp_id}.zip"'},
        )


@router.post("/run-experiments")
async def start_platform_experiment(payload: RunExperimentRequest):
    ws, engine = _init_and_engine()
    with Session(engine) as session:
        llm = session.get(PlatformLLMConfig, payload.llm.id)
        agent_cfg = session.get(PlatformAgentConfig, payload.agents.id)
        map_cfg = session.get(PlatformMapConfig, payload.map.id)
        wf_cfg = session.get(PlatformWorkflowConfig, payload.workflow.id)
        if not llm or not agent_cfg or not map_cfg or not wf_cfg:
            raise HTTPException(
                status_code=400,
                detail="Thiếu một trong các cấu hình LLM / Bản đồ / Cư dân / Quy trình.",
            )

        exp_id = f"exp_{uuid.uuid4().hex[:10]}"
        exp_dir = resolve_under_root(ws, ".agentsociety", "platform_experiments", exp_id)
        exp_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "id": exp_id,
            "name": payload.exp_name.strip(),
            "llm": {"id": llm.id, "name": llm.name},
            "map": {"id": map_cfg.id, "name": map_cfg.name, "file_path": map_cfg.file_path},
            "agents": {"id": agent_cfg.id, "name": agent_cfg.name},
            "workflow": {"id": wf_cfg.id, "name": wf_cfg.name, "steps": json.loads(wf_cfg.config_json or "[]")},
            "created_at": _utcnow_iso(),
        }
        (exp_dir / "config_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_file = exp_dir / "output.log"
        log_file.write_text(
            f"[{_utcnow_iso()}] Initialized v2 experiment '{payload.exp_name.strip()}'\n"
            f"[{_utcnow_iso()}] Bound LLM={llm.name}, Map={map_cfg.name}, Agents={agent_cfg.name}, Workflow={wf_cfg.name}\n"
            f"[{_utcnow_iso()}] Configuration validated cleanly on SQLite v2.\n",
            encoding="utf-8",
        )

        linked_project_id = map_cfg.linked_project_id
        linked_run_id = None
        if linked_project_id:
            latest_run = session.exec(
                select(UrbanSimRun)
                .where(UrbanSimRun.project_id == linked_project_id)
                .order_by(UrbanSimRun.run_number.desc())  # type: ignore[union-attr]
            ).first()
            if latest_run is not None:
                linked_run_id = latest_run.id

        row = PlatformExperiment(
            id=exp_id,
            name=payload.exp_name.strip(),
            num_day=max(1, len(snapshot["workflow"]["steps"]) or 1),
            status=2,
            cur_day=1,
            cur_t=900,
            config_json=json.dumps(snapshot, ensure_ascii=False, indent=2),
            linked_project_id=linked_project_id,
            linked_run_id=linked_run_id,
            log_path=str(log_file),
        )
        session.add(row)
        session.commit()
        return {"data": {"id": exp_id}}


@router.get("/run-experiments/{exp_id}/status")
async def get_run_experiment_status(exp_id: str):
    _, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            status_map = {
                "CREATED": "Running",
                "STARTING": "Running",
                "RUNNING": "Running",
                "PAUSING": "Running",
                "RESUMING": "Running",
                "FAILED": "Failed",
            }
            return {"data": status_map.get(run.status, "Finished")}
        exp = session.get(PlatformExperiment, exp_id)
        if exp is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")
        if exp.status == 3:
            return {"data": "Failed"}
        if exp.status == 1:
            return {"data": "Running"}
        return {"data": "Finished"}


@router.get("/run-experiments/{exp_id}/log")
async def get_run_experiment_log(exp_id: str):
    ws, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            run_dir = resolve_urban_sim_run_dir(ws, run.run_dir)
            log_path = run_dir / "output.log"
            if log_path.is_file():
                text = log_path.read_text(encoding="utf-8", errors="replace")
                return Response(content=text[-200_000:], media_type="text/plain; charset=utf-8")
            return Response(content="(Chưa có log chi tiết cho Run này)", media_type="text/plain; charset=utf-8")
        exp = session.get(PlatformExperiment, exp_id)
        if exp is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")
        if exp.log_path and Path(exp.log_path).is_file():
            text = Path(exp.log_path).read_text(encoding="utf-8", errors="replace")
            return Response(content=text[-200_000:], media_type="text/plain; charset=utf-8")
        return Response(content="(Chưa có log)", media_type="text/plain; charset=utf-8")


@router.delete("/run-experiments/{exp_id}")
async def stop_run_experiment(exp_id: str):
    from agentsociety2.backend.routers.urban_sim import get_lifecycle_manager

    _, engine = _init_and_engine()
    with Session(engine) as session:
        run = session.get(UrbanSimRun, exp_id)
        if run is not None:
            await get_lifecycle_manager().pause_run(run.project_id, run.id)
            return JSONResponse({"data": {"stopped": exp_id}})
        exp = session.get(PlatformExperiment, exp_id)
        if exp is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy thí nghiệm")
        exp.status = 4
        exp.updated_at = _utcnow_iso()
        session.add(exp)
        session.commit()
        return JSONResponse({"data": {"stopped": exp_id}})
