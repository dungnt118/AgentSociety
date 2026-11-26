"""Lifecycle Manager (Start / Pause / Resume / Restart / Reconcile) & Cost Aggregation for UrbanSim."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from agentsociety2.backend.path_security import (
    _configured_workspace_root,
    resolve_urban_sim_run_dir,
)
from agentsociety2.backend.services.urban_sim.compiler import compile_run_from_db
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimAtlasConfig,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimRun,
    UrbanSimZone,
    get_engine,
)
from agentsociety2.config.llm_catalog import resolve_model_rates_usd
from agentsociety2.logger import get_logger
from agentsociety2.society.society import (
    LLM_STATS_JSON,
    SOCIETY_JSON,
    SOCIETY_STEP_JSON,
    STOP_REQUESTED_FILE,
)
from agentsociety2.storage.workspace_state import atomic_write_text

logger = get_logger()

_ACTIVE_RUN_STATUSES = {"STARTING", "RUNNING", "PAUSING", "RESUMING"}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _usd_to_vnd() -> float:
    raw = os.getenv("DASHBOARD_USD_TO_VND", "").strip()
    try:
        val = float(raw) if raw else 25500.0
        return val if val > 0 else 25500.0
    except ValueError:
        return 25500.0


def _resolve_rates(model_name: str) -> tuple[float, float, float]:
    return resolve_model_rates_usd(model_name)


def compute_run_cost(llm_stats: dict[str, Any] | None) -> dict[str, Any]:
    """Compute exact USD / VND breakdown + prompt cache savings from ``LLM_STATS.json``."""
    usd_to_vnd = _usd_to_vnd()
    if not isinstance(llm_stats, dict) or not llm_stats:
        return {
            "available": False,
            "usd_to_vnd": usd_to_vnd,
            "cost_usd": 0.0,
            "cost_vnd": 0,
            "saved_by_cache_usd": 0.0,
            "saved_by_cache_vnd": 0,
            "cache_hit_rate": 0.0,
            "totals": {"calls": 0, "input": 0, "cached_input": 0, "output": 0},
            "models": {},
            "agent_side": {"totals": {"calls": 0, "input": 0, "cached_input": 0, "output": 0}},
            "router_side": {"totals": {"calls": 0, "input": 0, "cached_input": 0, "output": 0}},
        }

    models_in = llm_stats.get("models") or {}
    models_out: dict[str, Any] = {}
    total_cost = 0.0
    total_saved = 0.0

    for model_name, raw_stats in models_in.items():
        if not isinstance(raw_stats, dict):
            continue
        rates = _resolve_rates(model_name)
        in_tok = int(raw_stats.get("input", 0) or 0)
        cached_tok = min(int(raw_stats.get("cached_input", 0) or 0), in_tok)
        out_tok = int(raw_stats.get("output", 0) or 0)
        uncached_tok = max(0, in_tok - cached_tok)
        cost = uncached_tok * rates[0] + cached_tok * rates[1] + out_tok * rates[2]
        saved = max(0.0, cached_tok * (rates[0] - rates[1]))
        total_cost += cost
        total_saved += saved
        models_out[model_name] = {
            "calls": int(raw_stats.get("calls", 0) or 0),
            "input": in_tok,
            "cached_input": cached_tok,
            "output": out_tok,
            "cost_usd": round(cost, 6),
            "cost_vnd": round(cost * usd_to_vnd),
            "saved_by_cache_usd": round(saved, 6),
        }

    return {
        "available": True,
        "scope": llm_stats.get("scope", "current_process"),
        "step_count": int(llm_stats.get("step_count", 0) or 0),
        "usd_to_vnd": usd_to_vnd,
        "cost_usd": round(total_cost, 6),
        "cost_vnd": round(total_cost * usd_to_vnd),
        "saved_by_cache_usd": round(total_saved, 6),
        "saved_by_cache_vnd": round(total_saved * usd_to_vnd),
        "cache_hit_rate": float(llm_stats.get("cache_hit_rate", 0.0) or 0.0),
        "totals": llm_stats.get("totals") or {"calls": 0, "input": 0, "cached_input": 0, "output": 0},
        "models": models_out,
        "agent_side": llm_stats.get("agent_side") or {},
        "router_side": llm_stats.get("router_side") or {},
    }


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _read_json_safe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class UrbanSimLifecycleManager:
    """Thread/async-safe lifecycle controller for dynamic database simulation runs."""

    def __init__(self, workspace_root: Path | None = None):
        self._explicit_workspace_root = workspace_root
        self._project_locks: dict[str, asyncio.Lock] = {}
        self._watchers: dict[str, asyncio.Task[None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _workspace_root(self) -> Path:
        if self._explicit_workspace_root is not None:
            return Path(self._explicit_workspace_root).resolve()
        return Path(_configured_workspace_root()).resolve()

    def _lock_for(self, project_id: str) -> asyncio.Lock:
        if project_id not in self._project_locks:
            self._project_locks[project_id] = asyncio.Lock()
        return self._project_locks[project_id]

    def _sync_run_metrics(self, session: Session, run: UrbanSimRun) -> UrbanSimRun:
        run_dir = Path(run.run_dir)
        step_meta = _read_json_safe(run_dir / SOCIETY_STEP_JSON)
        pid_meta = _read_json_safe(run_dir / "pid.json")
        llm_stats = _read_json_safe(run_dir / LLM_STATS_JSON)

        if "step_count" in step_meta:
            run.step_count = int(step_meta.get("step_count") or 0)
        elif "step_count" in pid_meta:
            run.step_count = int(pid_meta.get("step_count") or 0)

        if llm_stats:
            cost_info = compute_run_cost(llm_stats)
            totals = cost_info.get("totals") or {}
            run.total_tokens = int(totals.get("input", 0)) + int(totals.get("output", 0))
            run.total_cost_usd = float(cost_info.get("cost_usd", 0.0))

        run.updated_at = _utcnow_iso()
        session.add(run)
        return run

    async def reconcile_on_startup(self) -> None:
        """Reconcile any runs left in active states across container restarts (FND-QA-01 / FND-QA-13)."""
        ws = self._workspace_root()
        engine = get_engine(ws)
        with Session(engine) as session:
            active_runs = session.exec(
                select(UrbanSimRun).where(UrbanSimRun.status.in_(list(_ACTIVE_RUN_STATUSES)))
            ).all()
            for run in active_runs:
                run_dir = Path(run.run_dir)
                (run_dir / STOP_REQUESTED_FILE).unlink(missing_ok=True)
                pid_meta = _read_json_safe(run_dir / "pid.json")
                step_meta = _read_json_safe(run_dir / SOCIETY_STEP_JSON)
                pid_status = str(pid_meta.get("status") or "").lower()
                if _pid_alive(run.pid):
                    # Live process still exists in same PID namespace
                    continue
                self._sync_run_metrics(session, run)
                if pid_status == "completed":
                    run.status = "COMPLETED"
                    run.ended_at = run.ended_at or _utcnow_iso()
                elif pid_status == "completed_with_errors":
                    run.status = "COMPLETED_WITH_ERRORS"
                    run.ended_at = run.ended_at or _utcnow_iso()
                elif pid_status == "paused":
                    run.status = "PAUSED"
                    run.paused_at = run.paused_at or _utcnow_iso()
                    run.pause_reason = str(pid_meta.get("pause_reason") or "paused")
                elif step_meta and step_meta.get("pending_update") is None:
                    run.status = "PAUSED"
                    run.paused_at = _utcnow_iso()
                    run.pause_reason = "container_restarted"
                else:
                    run.status = "FAILED"
                    run.ended_at = _utcnow_iso()
                    run.error_message = (
                        str(pid_meta.get("error") or "")
                        or "Tiến trình mô phỏng bị ngắt đột ngột giữa tick khi container khởi động lại."
                    )
                run.pid = None
                session.add(run)
            session.commit()

    async def _spawn_cli(
        self,
        *,
        run_id: str,
        project_id: str,
        config_path: Path,
        steps_path: Path,
        run_dir: Path,
        resume: bool,
        env_overrides: dict[str, str] | None = None,
    ) -> int:
        ws = self._workspace_root()
        cmd = [
            sys.executable,
            "-m",
            "agentsociety2.society.cli",
            "--config",
            str(config_path),
            "--steps",
            str(steps_path),
            "--run-dir",
            str(run_dir),
            "--experiment-id",
            run_id,
            "--log-level",
            "INFO",
            "--log-file",
            str(run_dir / "output.log"),
        ]
        if resume:
            cmd.append("--resume")
        env = dict(os.environ)
        if env_overrides:
            for k, v in env_overrides.items():
                if v == "":
                    env.pop(k, None)
                else:
                    env[k] = v
        env["WORKSPACE_PATH"] = str(ws)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ws),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self._processes[run_id] = proc
        task = asyncio.create_task(self._watch_process(run_id, project_id, proc, run_dir))
        self._watchers[run_id] = task
        return int(proc.pid)

    async def _watch_process(
        self,
        run_id: str,
        project_id: str,
        proc: asyncio.subprocess.Process,
        run_dir: Path,
    ) -> None:
        ws = self._workspace_root()
        engine = get_engine(ws)
        try:
            while proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    with Session(engine) as session:
                        run = session.get(UrbanSimRun, run_id)
                        if run is not None:
                            self._sync_run_metrics(session, run)
                            session.commit()
                    continue

            rc = int(proc.returncode or 0)
            pid_meta = _read_json_safe(run_dir / "pid.json")
            step_meta = _read_json_safe(run_dir / SOCIETY_STEP_JSON)
            pid_status = str(pid_meta.get("status") or "").lower()

            with Session(engine) as session:
                run = session.get(UrbanSimRun, run_id)
                if run is None:
                    return
                self._sync_run_metrics(session, run)
                run.pid = None
                if pid_status == "paused":
                    run.status = "PAUSED"
                    run.paused_at = _utcnow_iso()
                    run.pause_reason = str(pid_meta.get("pause_reason") or "user_requested")
                elif pid_status == "completed":
                    run.status = "COMPLETED"
                    run.ended_at = _utcnow_iso()
                    run.pause_reason = None
                elif pid_status == "completed_with_errors":
                    run.status = "COMPLETED_WITH_ERRORS"
                    run.ended_at = _utcnow_iso()
                elif (
                    rc == 0
                    and step_meta.get("pending_update") is None
                    and run.step_count >= run.total_steps
                    and run.total_steps > 0
                    and int(step_meta.get("completed_step_count", 0) or 0)
                    >= _count_expected_top_level_steps(run_dir)
                ):
                    run.status = "COMPLETED"
                    run.ended_at = _utcnow_iso()
                else:
                    run.status = "FAILED"
                    run.ended_at = _utcnow_iso()
                    run.error_message = (
                        str(pid_meta.get("error") or "")
                        or f"Tiến trình mô phỏng kết thúc bất thường (exit={rc}). Xem output.log."
                    )
                run.updated_at = _utcnow_iso()
                session.add(run)
                session.commit()
        finally:
            self._processes.pop(run_id, None)
            self._watchers.pop(run_id, None)

    def _assert_no_active_run(self, session: Session, project_id: str) -> None:
        active = session.exec(
            select(UrbanSimRun).where(
                UrbanSimRun.project_id == project_id,
                UrbanSimRun.status.in_(list(_ACTIVE_RUN_STATUSES)),
            )
        ).first()
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Dự án đang có Run '{active.id}' ở trạng thái '{active.status}'. Hãy đợi hoặc Pause trước khi bắt đầu Run mới.",
            )

    async def start_run(self, project_id: str) -> UrbanSimRun:
        ws = self._workspace_root()
        engine = get_engine(ws)
        async with self._lock_for(project_id):
            with Session(engine) as session:
                project = session.get(UrbanSimProject, project_id)
                if project is None:
                    raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
                self._assert_no_active_run(session, project_id)

                from agentsociety2.backend.services.platform_resources import (
                    resolve_llm_env_override,
                )

                llm_env_overrides = resolve_llm_env_override(
                    session, project.llm_config_id, ws
                )

                personas = session.exec(
                    select(UrbanSimPersona).where(UrbanSimPersona.project_id == project_id)
                ).all()
                atlas = session.get(UrbanSimAtlasConfig, project_id)
                zones = session.exec(
                    select(UrbanSimZone).where(UrbanSimZone.project_id == project_id)
                ).all()
                prev_runs = session.exec(
                    select(UrbanSimRun).where(UrbanSimRun.project_id == project_id)
                ).all()
                next_num = max([r.run_number for r in prev_runs], default=0) + 1
                run_id = f"urbrun_{next_num:03d}_{uuid.uuid4().hex[:6]}"
                run_dir = (ws / "urban_sim_runs" / project.slug / run_id).resolve()

                try:
                    bundle = compile_run_from_db(
                        project=project,
                        personas=list(personas),
                        atlas=atlas,
                        zones=list(zones),
                        run_dir=run_dir,
                        workspace_root=ws,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

                run = UrbanSimRun(
                    id=run_id,
                    project_id=project_id,
                    run_number=next_num,
                    run_dir=str(run_dir),
                    status="STARTING",
                    step_count=0,
                    total_steps=int(max(1, project.num_steps)),
                    active_agent_count=bundle.active_agent_count,
                    pilot_mode=bool(project.pilot_mode),
                    router_type=project.router_type,
                    started_at=_utcnow_iso(),
                )
                session.add(run)
                session.commit()
                session.refresh(run)

            try:
                pid = await self._spawn_cli(
                    run_id=run_id,
                    project_id=project_id,
                    config_path=bundle.config_path,
                    steps_path=bundle.steps_path,
                    run_dir=run_dir,
                    resume=False,
                    env_overrides=llm_env_overrides,
                )
            except Exception as exc:
                with Session(engine) as session:
                    failed_run = session.get(UrbanSimRun, run_id)
                    if failed_run is not None:
                        failed_run.status = "FAILED"
                        failed_run.error_message = str(exc)
                        failed_run.ended_at = _utcnow_iso()
                        session.add(failed_run)
                        session.commit()
                raise HTTPException(status_code=500, detail=f"Không thể khởi chạy tiến trình: {exc}") from exc

            with Session(engine) as session:
                live_run = session.get(UrbanSimRun, run_id)
                assert live_run is not None
                live_run.pid = pid
                live_run.status = "RUNNING"
                live_run.updated_at = _utcnow_iso()
                session.add(live_run)
                session.commit()
                session.refresh(live_run)
                return live_run

    async def pause_run(self, project_id: str, run_id: str) -> UrbanSimRun:
        ws = self._workspace_root()
        engine = get_engine(ws)
        async with self._lock_for(project_id):
            with Session(engine) as session:
                run = session.get(UrbanSimRun, run_id)
                if run is None or run.project_id != project_id:
                    raise HTTPException(status_code=404, detail="Không tìm thấy Run")
                if run.status not in {"STARTING", "RUNNING"}:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Không thể Pause Run ở trạng thái '{run.status}'",
                    )
                run_dir = Path(run.run_dir)
                atomic_write_text(run_dir / STOP_REQUESTED_FILE, "user_requested\n")
                run.status = "PAUSING"
                run.pause_reason = "user_requested"
                run.updated_at = _utcnow_iso()
                session.add(run)
                session.commit()
                session.refresh(run)
                return run

    async def resume_run(self, project_id: str, run_id: str) -> UrbanSimRun:
        ws = self._workspace_root()
        engine = get_engine(ws)
        async with self._lock_for(project_id):
            with Session(engine) as session:
                self._assert_no_active_run(session, project_id)
                run = session.get(UrbanSimRun, run_id)
                if run is None or run.project_id != project_id:
                    raise HTTPException(status_code=404, detail="Không tìm thấy Run")
                if run.status not in {"PAUSED", "FAILED", "COMPLETED_WITH_ERRORS"}:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Chỉ có thể Resume khi Run đang ở trạng thái PAUSED/FAILED (hiện tại: {run.status})",
                    )
                run_dir = Path(run.run_dir)
                if not (run_dir / SOCIETY_JSON).is_file():
                    raise HTTPException(
                        status_code=409,
                        detail="Run chưa có checkpoint SOCIETY.json. Hãy bấm Restart để tạo Run mới.",
                    )
                step_meta = _read_json_safe(run_dir / SOCIETY_STEP_JSON)
                if step_meta.get("pending_update") is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Checkpoint bị gián đoạn giữa tick (pending_update={step_meta.get('pending_update')}). Hãy bấm Restart để áp dụng cấu hình DB vào Run mới.",
                    )
                config_path = run_dir / "init" / "init_config.json"
                steps_path = run_dir / "init" / "steps.yaml"
                if not config_path.is_file() or not steps_path.is_file():
                    raise HTTPException(status_code=409, detail="Thiếu file init_config.json / steps.yaml của Run")
                (run_dir / STOP_REQUESTED_FILE).unlink(missing_ok=True)
                from agentsociety2.backend.services.platform_resources import (
                    resolve_llm_env_override,
                )

                proj = session.get(UrbanSimProject, project_id)
                llm_env_overrides = resolve_llm_env_override(
                    session, proj.llm_config_id if proj else None, ws
                )

                run.status = "RESUMING"
                run.pause_reason = None
                run.error_message = None
                run.ended_at = None
                run.updated_at = _utcnow_iso()
                session.add(run)
                session.commit()

            pid = await self._spawn_cli(
                run_id=run_id,
                project_id=project_id,
                config_path=config_path,
                steps_path=steps_path,
                run_dir=run_dir,
                resume=True,
                env_overrides=llm_env_overrides,
            )
            with Session(engine) as session:
                live_run = session.get(UrbanSimRun, run_id)
                assert live_run is not None
                live_run.pid = pid
                live_run.status = "RUNNING"
                live_run.updated_at = _utcnow_iso()
                session.add(live_run)
                session.commit()
                session.refresh(live_run)
                return live_run

    async def restart_run(self, project_id: str) -> UrbanSimRun:
        """Compile latest DB configuration and start a fresh Run."""
        return await self.start_run(project_id)

    async def delete_run(self, project_id: str, run_id: str) -> None:
        ws = self._workspace_root()
        engine = get_engine(ws)
        async with self._lock_for(project_id):
            with Session(engine) as session:
                run = session.get(UrbanSimRun, run_id)
                if run is None or run.project_id != project_id:
                    raise HTTPException(status_code=404, detail="Không tìm thấy Run")
                if run.status in _ACTIVE_RUN_STATUSES:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Không thể xóa Run đang chạy ({run.status}). Hãy Pause trước.",
                    )
                safe_dir = resolve_urban_sim_run_dir(ws, run.run_dir)
                from agentsociety2.backend.services.urban_sim.competency import (
                    get_competency_audit_manager,
                )

                await get_competency_audit_manager().cancel_audit_for_run(run_id)
                if safe_dir.exists():
                    shutil.rmtree(safe_dir, ignore_errors=True)
                session.delete(run)
                session.commit()


def _count_expected_top_level_steps(run_dir: Path) -> int:
    """Đọc số lượng step cấp 1 từ ``init/steps.yaml`` (mặc định 1 nếu không đọc được)."""
    import yaml

    steps_path = run_dir / "init" / "steps.yaml"
    if not steps_path.is_file():
        return 1
    try:
        parsed = yaml.safe_load(steps_path.read_text(encoding="utf-8"))
        steps = parsed.get("steps") if isinstance(parsed, dict) else None
        if isinstance(steps, list) and steps:
            return len(steps)
    except Exception:
        pass
    return 1


def derive_execution_phase(
    run_dir: Path, run_status: str, step_count: int, total_steps: int
) -> str:
    """Suy ra giai đoạn thực thi hiện tại của Run: PRE_QUIZ | SIMULATING | POST_DEBRIEF | POST_QUIZ | DONE."""
    import yaml

    if str(run_status or "").upper() in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}:
        return "DONE"
    steps_path = run_dir / "init" / "steps.yaml"
    steps: list[dict[str, Any]] = []
    if steps_path.is_file():
        try:
            parsed = yaml.safe_load(steps_path.read_text(encoding="utf-8"))
            raw = parsed.get("steps") if isinstance(parsed, dict) else None
            if isinstance(raw, list):
                steps = [s for s in raw if isinstance(s, dict)]
        except Exception:
            steps = []
    if not steps or len(steps) == 1:
        return "SIMULATING" if run_status in _ACTIVE_RUN_STATUSES or step_count < total_steps else "DONE"

    step_meta = _read_json_safe(run_dir / SOCIETY_STEP_JSON)
    completed = int(step_meta.get("completed_step_count", 0) or 0)
    if completed >= len(steps):
        return "DONE"
    cur = steps[completed]
    if cur.get("type") == "questionnaire":
        qid = str(cur.get("questionnaire_id") or "").strip()
        if qid == "bql_sociological_debrief":
            return "POST_DEBRIEF"
        if qid == "bql_competency_post" or "post" in qid:
            return "POST_QUIZ"
        return "PRE_QUIZ"
    return "SIMULATING"
