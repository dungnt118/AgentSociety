"""SQLite/SQLModel schema & session management for Dynamic Urban Simulation."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import event, text
from sqlmodel import Field, Session, SQLModel, create_engine

_DB_LOCK = threading.Lock()
_ENGINE_CACHE: dict[str, object] = {}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class UrbanSimProject(SQLModel, table=True):
    __tablename__ = "urban_sim_projects"

    id: str = Field(default_factory=lambda: _new_id("proj"), primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    description: str = ""
    default_portal_url: str = "https://mulberrylane.sandbox.demego.vn"
    router_type: str = "react"  # "react" | "codegen"
    num_steps: int = 8
    tick_seconds: int = 900
    start_time_iso: str = "2026-06-15T08:00:00+07:00"
    max_react_turns: int = 6
    max_cost_usd_per_run: float = 5.0
    pilot_mode: bool = True
    zone_map_image_rel: str | None = None
    llm_config_id: str | None = None
    enable_sociological_debrief: bool = True
    enable_competency_prepost_quiz: bool = False
    competency_rubric_json: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class UrbanSimPersona(SQLModel, table=True):
    __tablename__ = "urban_sim_personas"

    id: str = Field(default_factory=lambda: _new_id("per"), primary_key=True)
    project_id: str = Field(foreign_key="urban_sim_projects.id", index=True)
    agent_id: int = Field(index=True)
    full_name: str
    role_code: str = Field(index=True)
    role_title: str
    department: str
    group_type: str = "BQL"  # "BQL" | "RESIDENT"
    software_access_enabled: bool = True
    is_pilot_member: bool = False
    is_active: bool = True
    home_zone: str = "LOBBY_MAIN"
    domain_knowledge_prompt: str = ""
    initial_tasks_json: str = "[]"
    portal_url: str | None = None
    login_username: str | None = None
    login_password_enc: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


class UrbanSimAtlasConfig(SQLModel, table=True):
    __tablename__ = "urban_sim_atlas_configs"

    project_id: str = Field(foreign_key="urban_sim_projects.id", primary_key=True)
    enabled: bool = True
    atlas_api_url: str = "https://atlas.demego.vn"
    atlas_api_key_enc: str | None = None
    actor_persona: str = "END_USER"
    source_mode: str = "FEDERATED_AUTO"
    attach_screenshot_on_ask: bool = False
    quota_per_min: int = 25
    max_asks_per_tick: int = 2
    guardrail_mode: str = "SAFE_WRITE"  # "SAFE_WRITE" | "READ_ONLY" | "FULL_RBAC"
    record_prefix: str = "[SIM-BQL]"
    blocked_keywords_json: str = (
        '["xóa tất cả", "xóa hàng loạt", "xóa vĩnh viễn", "khóa tài khoản", '
        '"đổi mật khẩu", "chốt sổ", "bulk delete", "delete all", "close period"]'
    )
    last_verified_at: str | None = None
    last_verified_project_id: str | None = None
    last_verified_project_name: str | None = None
    last_verified_scopes_json: str = "[]"
    updated_at: str = Field(default_factory=_utcnow_iso)


class UrbanSimZone(SQLModel, table=True):
    __tablename__ = "urban_sim_zones"

    id: str = Field(default_factory=lambda: _new_id("zone"), primary_key=True)
    project_id: str = Field(foreign_key="urban_sim_projects.id", index=True)
    zone_key: str = Field(index=True)
    name: str
    zone_type: str = "OFFICE"  # "LOBBY" | "OFFICE" | "TECHNICAL" | "SECURITY" | "TOWER"
    description: str = ""
    sort_order: int = 0


class UrbanSimRun(SQLModel, table=True):
    __tablename__ = "urban_sim_runs"

    id: str = Field(default_factory=lambda: _new_id("run"), primary_key=True)
    project_id: str = Field(foreign_key="urban_sim_projects.id", index=True)
    run_number: int = 1
    run_dir: str
    status: str = "CREATED"
    pause_reason: str | None = None
    pid: int | None = None
    step_count: int = 0
    total_steps: int = 0
    active_agent_count: int = 0
    pilot_mode: bool = True
    router_type: str = "react"
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_message: str | None = None
    started_at: str | None = None
    paused_at: str | None = None
    ended_at: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


def resolve_db_path(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        base = Path(workspace_root).resolve()
    else:
        raw = os.getenv("WORKSPACE_PATH", "").strip() or "/workspace"
        base = Path(raw).expanduser().resolve()
    db_dir = base / ".agentsociety"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "urban_sim.db"


def _ensure_urban_sim_migrations(engine) -> None:
    """Idempotent SQLite schema migration for ``urban_sim_projects``."""
    with Session(engine) as session:
        cols = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(urban_sim_projects)")).all()
        }
        if not cols:
            return
        changed = False
        if "llm_config_id" not in cols:
            session.exec(text("ALTER TABLE urban_sim_projects ADD COLUMN llm_config_id TEXT"))
            changed = True
        if "enable_competency_prepost_quiz" not in cols:
            session.exec(
                text(
                    "ALTER TABLE urban_sim_projects "
                    "ADD COLUMN enable_competency_prepost_quiz INTEGER NOT NULL DEFAULT 0"
                )
            )
            changed = True
        if "enable_sociological_debrief" not in cols:
            session.exec(
                text(
                    "ALTER TABLE urban_sim_projects "
                    "ADD COLUMN enable_sociological_debrief INTEGER NOT NULL DEFAULT 1"
                )
            )
            changed = True
        if "competency_rubric_json" not in cols:
            session.exec(
                text("ALTER TABLE urban_sim_projects ADD COLUMN competency_rubric_json TEXT")
            )
            changed = True
        if changed:
            session.commit()


def get_engine(workspace_root: Path | None = None):
    db_path = resolve_db_path(workspace_root)
    key = str(db_path)
    with _DB_LOCK:
        engine = _ENGINE_CACHE.get(key)
        if engine is None:
            engine = create_engine(
                f"sqlite:///{key}",
                echo=False,
                connect_args={"check_same_thread": False, "timeout": 15.0},
            )

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _connection_record):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                cur.execute("PRAGMA busy_timeout=5000;")
                cur.execute("PRAGMA foreign_keys=ON;")
                cur.close()

            SQLModel.metadata.create_all(engine)
            _ensure_urban_sim_migrations(engine)
            _ENGINE_CACHE[key] = engine
        return engine


def init_urban_sim_db(workspace_root: Path | None = None):
    # Ensure unified platform resource SQLModels are registered in SQLModel.metadata
    import agentsociety2.backend.services.platform_resources  # noqa: F401

    engine = get_engine(workspace_root)
    SQLModel.metadata.create_all(engine)
    _ensure_urban_sim_migrations(engine)
    with Session(engine) as session:
        session.exec(text("SELECT 1"))
    return engine


def get_session(workspace_root: Path | None = None) -> Iterator[Session]:
    engine = get_engine(workspace_root)
    with Session(engine) as session:
        yield session
