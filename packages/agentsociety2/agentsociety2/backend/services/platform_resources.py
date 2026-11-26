"""Unified SQLite/SQLModel resource store for AgentSociety v2 Web Console."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Field, Session, SQLModel, select

from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimPersona,
    UrbanSimProject,
    get_engine,
    init_urban_sim_db,
)
from agentsociety2.config.llm_catalog import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_THINKING,
    get_model_pricing_per_1m,
    normalize_thinking_config,
    resolve_provider_api_type,
    resolve_provider_base_url,
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _is_mask_value(val: str | None) -> bool:
    clean = (val or "").strip()
    return not clean or set(clean) <= {"•", "*"}


class PlatformLLMConfig(SQLModel, table=True):
    __tablename__ = "platform_llm_configs"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    config_json: str = "[]"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformMapConfig(SQLModel, table=True):
    __tablename__ = "platform_map_configs"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    file_path: str = ""
    map_type: str = "urban_zones"  # "urban_zones" | "protobuf" | "image_2d"
    linked_project_id: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformAgentTemplate(SQLModel, table=True):
    __tablename__ = "platform_agent_templates"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    agent_type: str = "citizen"  # "citizen" | "supervisor"
    agent_class: str = "PersonAgent"
    memory_distributions_json: str = "{}"
    agent_params_json: str = "{}"
    blocks_json: str = "{}"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformAgentProfile(SQLModel, table=True):
    __tablename__ = "platform_agent_profiles"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    agent_type: str = "citizen"
    file_path: str = ""
    record_count: int = 0
    records_json: str = "[]"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformAgentConfig(SQLModel, table=True):
    __tablename__ = "platform_agent_configs"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    config_json: str = "{}"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformWorkflowConfig(SQLModel, table=True):
    __tablename__ = "platform_workflow_configs"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    description: str = ""
    config_json: str = "[]"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformSurvey(SQLModel, table=True):
    __tablename__ = "platform_surveys"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    data_json: str = "{}"
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class PlatformExperiment(SQLModel, table=True):
    __tablename__ = "platform_experiments"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    name: str
    num_day: int = 1
    status: int = 2  # 0=init, 1=running, 2=finished, 3=failed, 4=stopped
    cur_day: int = 0
    cur_t: int = 0
    config_json: str = "{}"
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    linked_project_id: str | None = None
    linked_run_id: str | None = None
    log_path: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


def _safe_json(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def serialize_llm_config(row: PlatformLLMConfig) -> dict[str, Any]:
    raw_items = _safe_json(row.config_json, [])
    safe_items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            enc = str(item.get("api_key_enc") or "")
            has_key = bool(enc.strip())
            provider = str(item.get("provider") or DEFAULT_LLM_PROVIDER).strip().lower()
            model = str(item.get("model") or DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
            coder_model = str(item.get("coder_model") or "").strip()
            thinking, effort = normalize_thinking_config(
                item.get("thinking"),
                item.get("reasoning_effort"),
            )
            api_type = resolve_provider_api_type(provider, item.get("api_type"))
            raw_base_url = str(item.get("base_url") or "").strip()
            safe_items.append(
                {
                    "provider": provider,
                    "model": model,
                    "coder_model": coder_model,
                    "base_url": raw_base_url,
                    "resolved_base_url": resolve_provider_base_url(provider, raw_base_url),
                    "api_key": mask_secret(enc) if has_key else "",
                    "has_api_key": has_key,
                    "thinking": thinking,
                    "reasoning_effort": effort or ("none" if thinking == "off" else ""),
                    "api_type": api_type,
                    "pricing": get_model_pricing_per_1m(model),
                }
            )
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "config": safe_items,
    }


def merge_llm_entries(
    incoming: list[dict[str, Any]],
    existing_raw_json: str | None = None,
    workspace_root: Path | None = None,
) -> str:
    existing_items = _safe_json(existing_raw_json, [])
    stored: list[dict[str, Any]] = []
    for idx, item in enumerate(incoming or []):
        if not isinstance(item, dict):
            continue
        raw_key = item.get("api_key")
        prev_enc = ""
        if isinstance(existing_items, list) and idx < len(existing_items):
            prev_item = existing_items[idx]
            if isinstance(prev_item, dict):
                prev_enc = str(prev_item.get("api_key_enc") or "")
        if _is_mask_value(raw_key):
            enc_key = prev_enc
        else:
            enc_key = encrypt_secret(str(raw_key), workspace_root)
        provider = str(item.get("provider") or DEFAULT_LLM_PROVIDER).strip().lower()
        model = str(item.get("model") or DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
        coder_model = str(item.get("coder_model") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        thinking, effort = normalize_thinking_config(
            item.get("thinking"),
            item.get("reasoning_effort"),
        )
        api_type = resolve_provider_api_type(provider, item.get("api_type"))
        stored.append(
            {
                "provider": provider,
                "model": model,
                "coder_model": coder_model,
                "base_url": base_url,
                "api_key_enc": enc_key,
                "thinking": thinking,
                "reasoning_effort": effort or ("none" if thinking == "off" else ""),
                "api_type": api_type,
            }
        )
    return json.dumps(stored, ensure_ascii=False)


def resolve_llm_env_override(
    session: Session,
    llm_config_id: str | None,
    workspace_root: Path | None = None,
) -> dict[str, str]:
    """Resolve Fernet-encrypted LLM credentials and model/thinking overrides for simulation subprocesses.

    Ghi đè đồng bộ cả vai trò ``LLM`` (Agent / ReActRouter) và ``CODER_LLM`` (CodeGenRouter)
    cũng như cấu hình ``THINKING`` / ``REASONING_EFFORT`` / ``API_TYPE`` để tránh bị dính biến cũ từ ``.env``.
    """
    if not llm_config_id:
        return {}
    row = session.get(PlatformLLMConfig, llm_config_id)
    if row is None:
        return {}
    entries = _safe_json(row.config_json, [])
    if not isinstance(entries, list) or not entries:
        return {}
    primary = entries[0] if isinstance(entries[0], dict) else {}
    provider = str(primary.get("provider") or DEFAULT_LLM_PROVIDER).strip().lower()
    model = str(primary.get("model") or "").strip() or DEFAULT_LLM_MODEL
    coder_model = str(primary.get("coder_model") or "").strip() or model
    base_url = resolve_provider_base_url(provider, primary.get("base_url"))
    api_type = resolve_provider_api_type(provider, primary.get("api_type"))
    thinking, effort = normalize_thinking_config(
        primary.get("thinking"),
        primary.get("reasoning_effort"),
    )

    overrides: dict[str, str] = {
        "AGENTSOCIETY_LLM_MODEL": model,
        "AGENTSOCIETY_CODER_LLM_MODEL": coder_model,
        "AGENTSOCIETY_LLM_API_BASE": base_url,
        "AGENTSOCIETY_CODER_LLM_API_BASE": base_url,
        "AGENTSOCIETY_LLM_API_TYPE": api_type,
        "AGENTSOCIETY_CODER_LLM_API_TYPE": api_type,
    }

    enc_key = str(primary.get("api_key_enc") or "").strip()
    if enc_key:
        plain = decrypt_secret(enc_key, workspace_root)
        if plain:
            overrides["AGENTSOCIETY_LLM_API_KEY"] = plain
            overrides["AGENTSOCIETY_CODER_LLM_API_KEY"] = plain

    if thinking in {"off", "on"}:
        overrides["AGENTSOCIETY_LLM_THINKING"] = thinking
        overrides["AGENTSOCIETY_CODER_LLM_THINKING"] = thinking
    else:
        overrides["AGENTSOCIETY_LLM_THINKING"] = ""
        overrides["AGENTSOCIETY_CODER_LLM_THINKING"] = ""

    if thinking == "on" and effort:
        overrides["AGENTSOCIETY_LLM_REASONING_EFFORT"] = effort
        overrides["AGENTSOCIETY_CODER_LLM_REASONING_EFFORT"] = effort
    else:
        overrides["AGENTSOCIETY_LLM_REASONING_EFFORT"] = ""
        overrides["AGENTSOCIETY_CODER_LLM_REASONING_EFFORT"] = ""

    return overrides


def serialize_map_config(row: PlatformMapConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "map_type": row.map_type,
        "linked_project_id": row.linked_project_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "config": {
            "file_path": row.file_path,
            "map_type": row.map_type,
            "linked_project_id": row.linked_project_id,
        },
    }


def serialize_agent_template(row: PlatformAgentTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "agent_type": row.agent_type,
        "agent_class": row.agent_class,
        "memory_distributions": _safe_json(row.memory_distributions_json, {}),
        "agent_params": _safe_json(row.agent_params_json, {}),
        "blocks": _safe_json(row.blocks_json, {}),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_agent_profile(row: PlatformAgentProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "agent_type": row.agent_type,
        "file_path": row.file_path,
        "record_count": int(row.record_count),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_agent_config(row: PlatformAgentConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "config": _safe_json(row.config_json, {"citizens": []}),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_workflow_config(row: PlatformWorkflowConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "config": _safe_json(row.config_json, []),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_survey(row: PlatformSurvey) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "data": _safe_json(row.data_json, {"pages": [{"name": "page1", "elements": []}]}),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def ensure_platform_seed(workspace_root: Path | None = None) -> None:
    """Idempotently seed v2 unified platform resources linked to MulberryLane."""
    init_urban_sim_db(workspace_root)
    engine = get_engine(workspace_root)
    with Session(engine) as session:
        mulberry = session.exec(
            select(UrbanSimProject).where(UrbanSimProject.slug == "mulberrylane")
        ).first()

        # 1. Seed Default LLM Config from runtime .env (preferring gpt-6-luna + thinking=off)
        if session.exec(select(PlatformLLMConfig)).first() is None:
            env_key = os.getenv("AGENTSOCIETY_LLM_API_KEY", "").strip()
            env_model = os.getenv("AGENTSOCIETY_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
            env_base = os.getenv("AGENTSOCIETY_LLM_API_BASE", "").strip()
            env_thinking = os.getenv("AGENTSOCIETY_LLM_THINKING", "").strip() or DEFAULT_LLM_THINKING
            thinking, effort = normalize_thinking_config(
                env_thinking,
                os.getenv("AGENTSOCIETY_LLM_REASONING_EFFORT"),
            )
            entry = {
                "provider": DEFAULT_LLM_PROVIDER,
                "model": env_model,
                "coder_model": "",
                "base_url": env_base,
                "api_key_enc": encrypt_secret(env_key, workspace_root) if env_key else "",
                "thinking": thinking,
                "reasoning_effort": effort or ("none" if thinking == "off" else ""),
                "api_type": resolve_provider_api_type(
                    DEFAULT_LLM_PROVIDER,
                    os.getenv("AGENTSOCIETY_LLM_API_TYPE"),
                ),
            }
            llm_row = PlatformLLMConfig(
                name="Default Runtime LLM (.env)",
                description="Cấu hình AI mặc định nạp từ biến môi trường Docker Runtime, dùng chung cho UrbanSim & thí nghiệm v2.",
                config_json=json.dumps([entry], ensure_ascii=False),
            )
            session.add(llm_row)
            session.flush()
            if mulberry is not None and not mulberry.llm_config_id:
                mulberry.llm_config_id = llm_row.id
                session.add(mulberry)

        # 2. Seed Map Configs (MulberryLane Zone Topology + optional beijing.pb)
        if session.exec(select(PlatformMapConfig)).first() is None:
            session.add(
                PlatformMapConfig(
                    name="MulberryLane — Sơ đồ 9 Khu vực (Zone Topology v2)",
                    description="Không gian mô phỏng động theo 9 Zone nghiệp vụ Chung cư MulberryLane (thay thế hoàn toàn bản đồ Bắc Kinh .pb).",
                    file_path="urban_sim://mulberrylane/zones",
                    map_type="urban_zones",
                    linked_project_id=mulberry.id if mulberry else None,
                )
            )
            pb_candidate = Path("/data/agentsociety_data/beijing.pb")
            if pb_candidate.is_file():
                session.add(
                    PlatformMapConfig(
                        name="Daily Mobility Map (beijing.pb)",
                        description="Bản đồ giao thông mẫu phục vụ riêng demo Daily Mobility.",
                        file_path=str(pb_candidate),
                        map_type="protobuf",
                    )
                )

        # 3. Seed Agent Templates
        citizen_tpl_id = ""
        sup_tpl_id = ""
        if session.exec(select(PlatformAgentTemplate)).first() is None:
            citizen_tpl = PlatformAgentTemplate(
                name="PersonAgent (AgentSociety v2)",
                description="Tác nhân v2 hỗ trợ kỹ năng ngữ cảnh, giao tiếp khu đô thị và tương tác đa bước.",
                agent_type="citizen",
                agent_class="PersonAgent",
                memory_distributions_json=json.dumps({}, ensure_ascii=False),
                agent_params_json=json.dumps(
                    {"max_react_turns": 6, "software_knowledge": "zero"},
                    ensure_ascii=False,
                ),
                blocks_json=json.dumps(
                    {
                        "UrbanCommIncidentEnv": {"enabled": True},
                        "DemegoWebPortalEnv": {"guardrail_mode": "SAFE_WRITE"},
                        "EvidenceAtlasSupportEnv": {"actor_persona": "END_USER"},
                    },
                    ensure_ascii=False,
                ),
            )
            sup_tpl = PlatformAgentTemplate(
                name="MulberryLane BQL Supervisor (ReAct)",
                description="Giám sát điều phối ReActRouter + ACL 2 tầng cho nhân sự Ban Quản lý.",
                agent_type="supervisor",
                agent_class="BQLReActSupervisor",
                memory_distributions_json=json.dumps({}, ensure_ascii=False),
                agent_params_json=json.dumps({"router_type": "react"}, ensure_ascii=False),
                blocks_json=json.dumps(
                    {"DailyGuidanceSkill": {"language": "vi"}},
                    ensure_ascii=False,
                ),
            )
            session.add(citizen_tpl)
            session.add(sup_tpl)
            session.flush()
            citizen_tpl_id = citizen_tpl.id
            sup_tpl_id = sup_tpl.id

        # 4. Seed Agent Profiles from MulberryLane 21 Personas
        profile_path = "agent_profiles/default/mulberrylane_21_personas.json"
        if session.exec(select(PlatformAgentProfile)).first() is None:
            personas = (
                session.exec(
                    select(UrbanSimPersona)
                    .where(UrbanSimPersona.project_id == mulberry.id)
                    .order_by(UrbanSimPersona.agent_id)
                ).all()
                if mulberry is not None
                else []
            )
            records = [
                {
                    "agent_id": p.agent_id,
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
            session.add(
                PlatformAgentProfile(
                    name="MulberryLane — 21 Persona (11 BQL + 10 Cư dân)",
                    description="Hồ sơ nhân khẩu & vai trò vận hành tòa nhà MulberryLane đồng bộ trực tiếp từ SQLite UrbanSim.",
                    agent_type="citizen",
                    file_path=profile_path,
                    record_count=len(records),
                    records_json=json.dumps(records, ensure_ascii=False),
                )
            )

        # 5. Seed Agent Configs
        if session.exec(select(PlatformAgentConfig)).first() is None:
            cfg = {
                "citizens": [
                    {
                        "agent_class": "PersonAgent",
                        "number": 21,
                        "template_id": citizen_tpl_id,
                        "memory_from_file": profile_path,
                        "agent_params": {"bql_count": 11, "resident_count": 10},
                    }
                ],
                "supervisor": {
                    "agent_class": "BQLReActSupervisor",
                    "template_id": sup_tpl_id,
                    "agent_params": {"router_type": "react"},
                },
            }
            session.add(
                PlatformAgentConfig(
                    name="Đội hình MulberryLane (11 BQL + 10 Cư dân)",
                    description="Cấu hình tập thể nhân sự Ban Quản lý (0 kiến thức QLTN) và Chủ hộ cư dân MulberryLane.",
                    config_json=json.dumps(cfg, ensure_ascii=False),
                )
            )

        # 6. Seed Workflow Configs
        if session.exec(select(PlatformWorkflowConfig)).first() is None:
            steps = [
                {
                    "type": "step",
                    "steps": 8,
                    "ticks_per_step": 900,
                    "description": "Ca vận hành 8 bước × 15 phút (Cư dân phát sinh sự vụ → Lễ tân/BQL xử lý trên QLTN & hỏi EvidenceAtlas).",
                }
            ]
            session.add(
                PlatformWorkflowConfig(
                    name="Kịch bản Vận hành MulberryLane (8 bước × 15 phút)",
                    description="Quy trình chuẩn cho bài toán mô phỏng phần mềm quản lý khu đô thị v2.",
                    config_json=json.dumps(steps, ensure_ascii=False),
                )
            )

        # 7. Seed Survey
        if session.exec(select(PlatformSurvey)).first() is None:
            survey_data = {
                "title": "Khảo sát Trải nghiệm Vận hành QLTN & Hài lòng Cư dân",
                "pages": [
                    {
                        "name": "page1",
                        "elements": [
                            {
                                "type": "rating",
                                "name": "qltn_usability",
                                "title": "Mức độ dễ thao tác trên cổng QLTN khi bắt đầu từ con số 0 (1-5)",
                                "rateMax": 5,
                            },
                            {
                                "type": "comment",
                                "name": "feedback_notes",
                                "title": "Điểm nghẽn nghiệp vụ hoặc câu hỏi cần CSKH EvidenceAtlas bổ sung",
                            },
                        ],
                    }
                ],
            }
            session.add(
                PlatformSurvey(
                    name="Khảo sát Trải nghiệm Vận hành QLTN & Hài lòng Cư dân MulberryLane",
                    data_json=json.dumps(survey_data, ensure_ascii=False),
                )
            )

        session.commit()
