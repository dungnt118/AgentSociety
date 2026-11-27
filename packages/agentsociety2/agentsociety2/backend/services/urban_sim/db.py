"""SQLite/SQLModel schema & session management for Dynamic Urban Simulation."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import UniqueConstraint, event, text
from sqlmodel import Field, Session, SQLModel, create_engine, select

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
    map_prompt: str | None = None
    map_width: int | None = None
    map_height: int | None = None
    map_aspect_ratio: float | None = None
    map_image_version: int = 0
    map_image_updated_at: str | None = None
    llm_config_id: str | None = None
    enable_sociological_debrief: bool = True
    enable_competency_prepost_quiz: bool = False
    competency_rubric_json: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


def resolve_default_persona_icon(
    role_code: str = "",
    group_type: str = "BQL",
    full_name: str = "",
) -> str:
    """Return a readable default emoji icon matching the persona's role or resident profile."""
    rc = (role_code or "").strip().upper()
    gt = (group_type or "BQL").strip().upper()
    name_low = (full_name or "").strip().lower()
    if gt == "RESIDENT":
        if any(tok in name_low for tok in ("bà ", "chị ", "cô ", "nữ")):
            return "👩"
        if any(tok in name_low for tok in ("ông ", "anh ", "chú ", "nam")):
            return "👨"
        return "🧑"
    role_map = {
        "BQL_DIRECTOR": "👔",
        "BQL_ASSISTANT": "📋",
        "BQL_RECEPTIONIST": "🛎️",
        "SEC_LEAD": "🛡️",
        "SEC_STAFF": "👮",
        "ENG_LEAD": "👷",
        "ENG_STAFF": "🔧",
        "BQL_ACCOUNTANT": "🧮",
        "CLEAN_STAFF": "🧹",
        "HOUSEKEEPING": "🧹",
    }
    if rc in role_map:
        return role_map[rc]
    if "SEC" in rc or "AN_NINH" in rc:
        return "👮"
    if "ENG" in rc or "TECH" in rc or "KY_THUAT" in rc:
        return "🔧"
    if "ACCOUNT" in rc or "KE_TOAN" in rc:
        return "🧮"
    if "RECEPT" in rc or "LE_TAN" in rc:
        return "🛎️"
    return "🧑‍💼"


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
    avatar_icon: str | None = None
    domain_knowledge_prompt: str = ""
    initial_tasks_json: str = "[]"
    portal_url: str | None = None
    login_username: str | None = None
    login_password_enc: str | None = None
    default_activated_skill_ids_json: str | None = None
    disabled_skill_ids_json: str | None = None
    profile_traits_json: str | None = None
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
    zone_type: str = "OFFICE"  # "LOBBY" | "OFFICE" | "TECHNICAL" | "SECURITY" | "TOWER" | "UTILITY" | "PARKING" | "COMMERCIAL" | "OTHER"
    description: str = ""
    ambient_signals: str = ""
    sort_order: int = 0
    center_x_pct: float | None = None
    center_y_pct: float | None = None
    polygon_points_json: str | None = None
    fill_color: str | None = None


class UrbanSimCheckpoint(SQLModel, table=True):
    __tablename__ = "urban_sim_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "checkpoint_key",
            name="uq_urban_sim_checkpoints_project_key",
        ),
    )

    id: str = Field(default_factory=lambda: _new_id("cp"), primary_key=True)
    project_id: str = Field(foreign_key="urban_sim_projects.id", index=True)
    checkpoint_key: str = Field(index=True)
    name: str
    x_pct: float
    y_pct: float
    icon_emoji: str = "📍"
    description_md: str = ""
    zone_key: str | None = Field(default=None, index=True)
    category: str = "general"  # "security" | "facility" | "amenity" | "service" | "general"
    sort_order: int = 0
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)


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
    """Idempotent SQLite schema migration for ``urban_sim_projects``, ``urban_sim_zones`` & ``urban_sim_checkpoints``."""
    with Session(engine) as session:
        cols = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(urban_sim_projects)")).all()
        }
        changed = False
        if cols:
            project_migrations = [
                ("llm_config_id", "ALTER TABLE urban_sim_projects ADD COLUMN llm_config_id TEXT"),
                (
                    "enable_competency_prepost_quiz",
                    "ALTER TABLE urban_sim_projects ADD COLUMN enable_competency_prepost_quiz INTEGER NOT NULL DEFAULT 0",
                ),
                (
                    "enable_sociological_debrief",
                    "ALTER TABLE urban_sim_projects ADD COLUMN enable_sociological_debrief INTEGER NOT NULL DEFAULT 1",
                ),
                (
                    "competency_rubric_json",
                    "ALTER TABLE urban_sim_projects ADD COLUMN competency_rubric_json TEXT",
                ),
                ("map_prompt", "ALTER TABLE urban_sim_projects ADD COLUMN map_prompt TEXT"),
                ("map_width", "ALTER TABLE urban_sim_projects ADD COLUMN map_width INTEGER"),
                ("map_height", "ALTER TABLE urban_sim_projects ADD COLUMN map_height INTEGER"),
                ("map_aspect_ratio", "ALTER TABLE urban_sim_projects ADD COLUMN map_aspect_ratio REAL"),
                (
                    "map_image_version",
                    "ALTER TABLE urban_sim_projects ADD COLUMN map_image_version INTEGER NOT NULL DEFAULT 0",
                ),
                (
                    "map_image_updated_at",
                    "ALTER TABLE urban_sim_projects ADD COLUMN map_image_updated_at TEXT",
                ),
            ]
            for col_name, ddl in project_migrations:
                if col_name not in cols:
                    session.exec(text(ddl))
                    changed = True

        zone_cols = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(urban_sim_zones)")).all()
        }
        if zone_cols:
            zone_migrations = [
                (
                    "ambient_signals",
                    "ALTER TABLE urban_sim_zones ADD COLUMN ambient_signals TEXT NOT NULL DEFAULT ''",
                ),
                ("center_x_pct", "ALTER TABLE urban_sim_zones ADD COLUMN center_x_pct REAL"),
                ("center_y_pct", "ALTER TABLE urban_sim_zones ADD COLUMN center_y_pct REAL"),
                (
                    "polygon_points_json",
                    "ALTER TABLE urban_sim_zones ADD COLUMN polygon_points_json TEXT",
                ),
                ("fill_color", "ALTER TABLE urban_sim_zones ADD COLUMN fill_color TEXT"),
            ]
            for col_name, ddl in zone_migrations:
                if col_name not in zone_cols:
                    session.exec(text(ddl))
                    changed = True

        persona_cols = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(urban_sim_personas)")).all()
        }
        if persona_cols:
            persona_migrations = [
                (
                    "default_activated_skill_ids_json",
                    "ALTER TABLE urban_sim_personas ADD COLUMN default_activated_skill_ids_json TEXT",
                ),
                (
                    "disabled_skill_ids_json",
                    "ALTER TABLE urban_sim_personas ADD COLUMN disabled_skill_ids_json TEXT",
                ),
                (
                    "profile_traits_json",
                    "ALTER TABLE urban_sim_personas ADD COLUMN profile_traits_json TEXT",
                ),
                (
                    "avatar_icon",
                    "ALTER TABLE urban_sim_personas ADD COLUMN avatar_icon TEXT",
                ),
            ]
            for col_name, ddl in persona_migrations:
                if col_name not in persona_cols:
                    session.exec(text(ddl))
                    changed = True

        cp_cols = {
            row[1]
            for row in session.exec(text("PRAGMA table_info(urban_sim_checkpoints)")).all()
        }
        if cp_cols:
            session.exec(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_urban_sim_checkpoints_project_key "
                    "ON urban_sim_checkpoints(project_id, checkpoint_key)"
                )
            )
            changed = True

        # Idempotently backfill MulberryLane default zone signals & digital map geometry when missing
        if zone_cols:
            ml_proj = session.exec(
                select(UrbanSimProject).where(UrbanSimProject.slug == "mulberrylane")
            ).first()
            if ml_proj is not None:
                from agentsociety2.backend.services.urban_sim.seed_mulberrylane import (
                    MULBERRYLANE_ZONES,
                    backfill_mulberrylane_digital_map,
                )

                ml_zones = session.exec(
                    select(UrbanSimZone).where(UrbanSimZone.project_id == ml_proj.id)
                ).all()
                if ml_zones and all(not (mz.ambient_signals or "").strip() for mz in ml_zones):
                    sig_by_key = {item[0]: item[5] for item in MULBERRYLANE_ZONES if len(item) > 5}
                    for mz in ml_zones:
                        if mz.zone_key in sig_by_key:
                            mz.ambient_signals = sig_by_key[mz.zone_key]
                            session.add(mz)
                    changed = True

                if backfill_mulberrylane_digital_map(session, ml_proj):
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
