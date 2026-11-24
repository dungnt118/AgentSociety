#!/usr/bin/env python3
"""Run Prisoner's Dilemma (2 agents x 2 rounds) into a workspace experiment directory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from agentsociety2.env import create_env_router_proxy
from agentsociety2.society import AgentSociety

NUM_ROUNDS = 2
MODULE = "PrisonersDilemmaEnv"
_FAILURE_MARKERS = (
    "CRITICAL FAILURE",
    "LLMDispatchError",
    "Failed to get valid response after",
    "No deployments available for selected model",
)


def _write_pid(
    pid_file: Path,
    *,
    status: str,
    run_dir: Path,
    experiment_id: str,
    start_time: str,
    step_count: int,
    simulation_time: str | None = None,
    end_time: str | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "status": status,
        "experiment_id": experiment_id,
        "start_time": start_time,
        "run_dir": str(run_dir.resolve()),
        "step_count": step_count,
    }
    if simulation_time is not None:
        payload["simulation_time"] = simulation_time
    if end_time is not None:
        payload["end_time"] = end_time
    if error is not None:
        payload["error"] = error
    pid_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _history(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "env" / MODULE / "state" / "ENV_STATE.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("round_history") or [])


def _find_critical_failures(run_dir: Path) -> list[str]:
    hits: list[str] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".log", ".json", ".jsonl", ".txt", ".md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(marker in text for marker in _FAILURE_MARKERS):
            hits.append(str(path.relative_to(run_dir)))
    return hits


def _prepare_run_dir(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for child in list(run_dir.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


async def run_experiment(run_dir: Path, experiment_id: str) -> None:
    _prepare_run_dir(run_dir)
    pid_file = run_dir / "pid.json"
    start_time = datetime.now(UTC).isoformat()
    _write_pid(
        pid_file,
        status="running",
        run_dir=run_dir,
        experiment_id=experiment_id,
        start_time=start_time,
        step_count=0,
    )

    agent_names = ["Agent A", "Agent B"]
    agent_specs = [
        {"id": i + 1, "profile": {"id": i + 1, "name": name}, "config": {}}
        for i, name in enumerate(agent_names)
    ]

    society: AgentSociety | None = None
    try:
        env_router = await create_env_router_proxy([MODULE], {MODULE: {}}, run_dir=run_dir)
        society = AgentSociety(
            agent_specs=agent_specs,
            agent_class_name="PrisonersDilemmaAgent",
            env_router=env_router,
            start_t=datetime.now(),
            run_dir=run_dir,
            enable_replay=True,
        )
        await society.init()

        print("=== Prisoner's Dilemma (Real LLM Run) ===", flush=True)
        print(f"Run dir: {run_dir}", flush=True)
        print(f"Running {NUM_ROUNDS} rounds with {agent_names}...", flush=True)
        t0 = time.perf_counter()

        for round_num in range(1, NUM_ROUNDS + 1):
            print(f"--- Round {round_num}/{NUM_ROUNDS} ---", flush=True)
            await society.step(tick=1)
            _write_pid(
                pid_file,
                status="running",
                run_dir=run_dir,
                experiment_id=experiment_id,
                start_time=start_time,
                step_count=society.step_count,
                simulation_time=society.current_time.isoformat(),
            )
            hist = _history(run_dir)
            if hist:
                latest = hist[-1]
                print(
                    f"  A={latest.get('agent_a_action')} "
                    f"B={latest.get('agent_b_action')} "
                    f"payoffs=({latest.get('agent_a_payoff')}, "
                    f"{latest.get('agent_b_payoff')})",
                    flush=True,
                )
            else:
                print("  (no round settled yet)", flush=True)

        wall = time.perf_counter() - t0
        stats = society.all_token_stats()
        sim_time = society.current_time.isoformat()
        step_count = society.step_count
        await society.close()
        society = None

        (run_dir / "LLM_STATS.json").write_text(
            json.dumps(stats, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        hits = _find_critical_failures(run_dir)
        if hits:
            raise RuntimeError(f"LLM critical failure markers found: {', '.join(hits[:8])}")

        history = _history(run_dir)
        if len(history) != NUM_ROUNDS:
            raise RuntimeError(f"Expected {NUM_ROUNDS} rounds, got {len(history)}")

        _write_pid(
            pid_file,
            status="completed",
            run_dir=run_dir,
            experiment_id=experiment_id,
            start_time=start_time,
            step_count=step_count,
            simulation_time=sim_time,
            end_time=datetime.now(UTC).isoformat(),
        )

        print(f"Rounds recorded: {len(history)}", flush=True)
        print(f"Token stats: {json.dumps(stats, ensure_ascii=False)}", flush=True)
        print(f"WALL_SEC={wall:.2f}", flush=True)
        print("SUCCESS=True", flush=True)
    except Exception as exc:
        if society is not None:
            try:
                await society.close()
            except Exception:
                pass
        _write_pid(
            pid_file,
            status="failed",
            run_dir=run_dir,
            experiment_id=experiment_id,
            start_time=start_time,
            step_count=0,
            end_time=datetime.now(UTC).isoformat(),
            error=str(exc),
        )
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Prisoner's Dilemma experiment")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path("/workspace/hypothesis_2/experiment_1/run"),
        help="Target experiment run directory",
    )
    parser.add_argument(
        "--experiment-id",
        default="2_1",
        help="Experiment identifier recorded in pid.json",
    )
    args = parser.parse_args()
    asyncio.run(run_experiment(args.run_dir, args.experiment_id))


if __name__ == "__main__":
    main()
