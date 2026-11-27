"""Shared helpers for Urban Simulation EnvBase modules (event JSONL sink & encrypted vault reader)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentsociety2.backend.services.urban_sim.crypto import decrypt_vault_blob
from agentsociety2.env.router_base import get_active_caller_agent_id

try:
    import fcntl
except ImportError:  # Windows local unit environment
    fcntl = None  # type: ignore[assignment]

_EVENT_LOCK = threading.Lock()


def effective_caller_agent_id(agent_id: int) -> int:
    """Enforce caller identity bound by Router.ask() context so generated tool args cannot spoof ACL."""
    bound = get_active_caller_agent_id()
    return int(bound) if bound is not None else int(agent_id)


def _infer_workspace_root_from_vault(vault_path: Path) -> Path | None:
    cur = vault_path.resolve().parent
    while cur.parent != cur:
        if (cur / ".agentsociety").is_dir():
            return cur
        cur = cur.parent
    return None


def make_vault_accessor(secrets_vault_path: str | None):
    """Build a closure that loads decrypted run secrets without exposing them on ``self``."""
    resolved = Path(secrets_vault_path).resolve() if secrets_vault_path else None
    ws_root = _infer_workspace_root_from_vault(resolved) if resolved else None
    cached: dict[str, Any] = {}

    def _load() -> dict[str, Any]:
        nonlocal cached
        if cached:
            return cached
        if resolved is None or not resolved.is_file():
            return {}
        token = resolved.read_text(encoding="utf-8").strip()
        if not token:
            return {}
        cached = decrypt_vault_blob(token, ws_root)
        return cached

    return _load


def append_urban_event(
    events_log_path: str | Path | None,
    *,
    stream: str,
    agent_id: int | None,
    agent_name: str = "",
    role_title: str = "",
    action: str = "",
    summary: str = "",
    sim_time: datetime | None = None,
    details: dict[str, Any] | None = None,
    screenshot_file: str | None = None,
    ok: bool = True,
) -> dict[str, Any] | None:
    """Append one structured Urban Simulation event with monotonic ``seq`` to ``urban_events.jsonl``."""
    if not events_log_path:
        return None
    target = Path(events_log_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record_base = {
        "stream": stream,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "role_title": role_title,
        "action": action,
        "summary": summary,
        "ok": bool(ok),
        "sim_time": sim_time.isoformat() if isinstance(sim_time, datetime) else (str(sim_time) if sim_time else None),
        "wall_time": datetime.now(UTC).isoformat(),
        "screenshot_file": screenshot_file,
        "details": details or {},
    }
    with _EVENT_LOCK:
        with open(target, "a+", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                seq = sum(1 for _ in fh) + 1
                record = {"seq": seq, **record_base}
                fh.seek(0, 2)
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                return record
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
