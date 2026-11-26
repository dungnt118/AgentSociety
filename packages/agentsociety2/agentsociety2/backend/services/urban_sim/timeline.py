"""Tổng hợp dòng lịch sử nhận thức, hành động và bằng chứng theo từng Persona (Lớp 1 + Lớp 2)."""

from __future__ import annotations

import glob
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TOOL_LABELS_VI: dict[str, str] = {
    "observe": "Quan sát môi trường & hộp thư",
    "ask_env": "Thao tác / hỏi môi trường",
    "read": "Đọc tệp ghi chú",
    "write": "Ghi / cập nhật sổ tay",
    "append": "Ghi bổ sung sổ tay",
    "list": "Xem danh sách tệp",
    "grep": "Tìm trong sổ tay",
    "todo_list": "Xem danh sách việc cần làm",
    "todo_add": "Thêm việc cần làm",
    "todo_start": "Bắt đầu xử lý việc",
    "todo_update": "Cập nhật việc cần làm",
    "todo_complete": "Hoàn thành việc",
    "todo_defer": "Hoãn việc",
    "memory_recent": "Nhớ lại ký ức gần đây",
    "memory_search": "Tìm kiếm ký ức",
    "memory_range": "Truy xuất ký ức theo bước",
    "memory_read": "Đọc chi tiết ký ức",
    "activate_skill": "Kích hoạt kỹ năng",
    "deactivate_skill": "Tắt kỹ năng",
    "execute_skill_script": "Chạy script kỹ năng",
    "finish": "Hoàn tất lượt",
}

_EPISODE_TYPE_LABELS_VI: dict[str, str] = {
    "observation": "Quan sát",
    "routine": "Thao tác",
    "goal": "Mục tiêu tiếp theo",
    "commitment": "Cam kết",
    "resolution": "Hướng giải quyết",
    "preference": "Thói quen / Sở thích",
    "identity": "Bản sắc / Vai trò",
    "conflict": "Vướng mắc / Xung đột",
    "relationship": "Quan hệ phối hợp",
    "decision": "Quyết định",
    "reflection": "Đúc kết",
}

LOADING_SPLASH_HEURISTIC_MAX_BYTES = 18_000


def classify_screenshot_file(
    screenshots_dir: Path,
    filename: str | None,
    details: dict[str, Any] | None = None,
) -> tuple[str | None, int | None]:
    """Phân loại độ tin cậy ảnh chụp QLTN không ghi sửa dữ liệu cũ (chống loading splash).

    - Run mới (có ``details.capture_status`` / ``meta.capture_status``): ưu tiên trạng thái runtime
      (``READY`` | ``LOADING_TIMEOUT``), chỉ chuyển ``MISSING`` nếu file rỗng/không tồn tại.
    - Run lịch sử #1/#2 (chưa có metadata): dùng heuristic an toàn ``< 18 KB`` -> ``LOADING_SPLASH_SUSPECTED``.
    """
    raw_name = str(filename or "").strip()
    if not raw_name:
        return None, None
    safe_name = Path(raw_name).name
    target = screenshots_dir / safe_name

    raw_status = ""
    raw_bytes: int | None = None
    if isinstance(details, dict):
        raw_status = str(details.get("capture_status") or "").strip().upper()
        if isinstance(details.get("screenshot_bytes"), int):
            raw_bytes = int(details["screenshot_bytes"])

    size_bytes: int | None = raw_bytes
    if not _is_within_root(target, screenshots_dir) or target.is_symlink() or not target.is_file():
        return "MISSING", size_bytes
    try:
        size_bytes = target.stat().st_size
    except OSError:
        return "MISSING", size_bytes

    if size_bytes <= 0:
        return "MISSING", 0
    if raw_status in {"READY", "LOADING_TIMEOUT", "LOADING_SPLASH_SUSPECTED"}:
        return raw_status, size_bytes
    if size_bytes < LOADING_SPLASH_HEURISTIC_MAX_BYTES:
        return "LOADING_SPLASH_SUSPECTED", size_bytes
    return "READY", size_bytes

_INCIDENT_ID_RE = re.compile(r"\bINC-\d+\b")
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|pin|secret|token|api[_-]?key|authorization|cookie|credential)",
    re.IGNORECASE,
)


def _redact_args(value: Any, *, max_str: int = 500, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:max_str]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            if _SENSITIVE_KEY_RE.search(ks):
                out[ks] = "***REDACTED***"
            else:
                out[ks] = _redact_args(v, max_str=max_str, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_args(item, max_str=max_str, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str] + "…"
    return value


def _parse_iso_ts(value: str | None) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).timestamp()


def _safe_read_text(path: Path, *, max_bytes: int) -> str:
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="replace")


def _safe_read_json(path: Path) -> dict[str, Any]:
    txt = _safe_read_text(path, max_bytes=512 * 1024)
    if not txt:
        return {}
    try:
        parsed = json.loads(txt)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _obs_to_text(obs_raw: Any, *, max_len: int = 500) -> str:
    if isinstance(obs_raw, dict):
        text = str(obs_raw.get("observation") or "")
        if not text:
            text = json.dumps(obs_raw, ensure_ascii=False)
    else:
        text = str(obs_raw or "")
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len] + "…"


def _extract_observe_context(obs_text: str) -> dict[str, Any]:
    raw = obs_text.strip()
    if not raw.startswith("{"):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    inbox = parsed.get("observe_urban_inbox")
    if not isinstance(inbox, dict):
        return {}
    bc = inbox.get("building_context") if isinstance(inbox.get("building_context"), dict) else {}
    unread = inbox.get("unread_messages")
    incidents = inbox.get("open_incidents")
    return {
        "current_zone": inbox.get("current_zone"),
        "time_band": bc.get("time_band"),
        "unread_messages": len(unread) if isinstance(unread, list) else None,
        "open_incidents_count": len(incidents) if isinstance(incidents, list) else None,
    }


def _describe_workspace_action(span_name: str, attrs: dict[str, Any]) -> str | None:
    rel_path = str(attrs.get("workspace.normalized_path") or attrs.get("workspace.path") or "").strip()
    if not rel_path:
        return None
    if span_name == "workspace.read_text":
        return f"Đã đọc sổ tay `{rel_path}`"
    if span_name == "workspace.write_text":
        return f"Đã ghi / cập nhật sổ tay `{rel_path}`"
    if span_name == "workspace.append_text":
        return f"Đã ghi bổ sung vào `{rel_path}`"
    if span_name == "workspace.grep":
        pat = str(attrs.get("grep.pattern") or "").strip()
        return f"Đã tìm kiếm `{pat}` trong `{rel_path}`" if pat else f"Đã tìm kiếm trong `{rel_path}`"
    return None


def _friendly_env_tool_label(action: str, obs_preview: str, args: Any = None) -> str:
    base_label = _TOOL_LABELS_VI.get(action, action)
    if action != "ask_env":
        return base_label
    # Ưu tiên nhận diện hành động thực tế trước login_qltn_portal (already_logged_in) và observe_*
    if "ask_atlas_support" in obs_preview:
        return "Nhắn hỏi CSKH Thần Nông"
    if "click_web_" in obs_preview:
        return "Bấm thao tác trên QLTN"
    if "fill_web_input" in obs_preview or "select_web_option" in obs_preview:
        return "Nhập liệu biểu mẫu QLTN"
    if "navigate_web_path" in obs_preview:
        return "Chuyển màn hình QLTN"
    if "report_resident_incident" in obs_preview:
        return "Gửi báo cáo sự cố cư dân"
    if "send_urban_message" in obs_preview:
        return "Gửi tin nhắn nội bộ / phản hồi"
    if "manage_incident" in obs_preview or "update_incident_status" in obs_preview:
        return "Cập nhật trạng thái sự vụ"
    if "move_to_zone" in obs_preview:
        return "Di chuyển khu vực"
    if "login_qltn_portal" in obs_preview and '"already_logged_in": true' not in obs_preview.lower():
        return "Đăng nhập cổng QLTN"

    # Nếu observation bị cắt ngắn hoặc bị shadowed bởi already_logged_in, suy từ instruction/ctx
    if isinstance(args, dict):
        ctx = args.get("ctx") if isinstance(args.get("ctx"), dict) else {}
        instr = str(args.get("instruction") or "").lower()
        if ctx.get("attach_screenshot") or "ask_atlas_support" in instr or "cskh" in instr or "đội hỗ trợ" in instr or "đội ngũ hỗ trợ" in instr:
            return "Nhắn hỏi CSKH Thần Nông"
        if "bấm [" in instr or "bấm mục" in instr or "click" in instr:
            return "Bấm thao tác trên QLTN"
        if "điền" in instr or "chọn" in instr:
            return "Nhập liệu biểu mẫu QLTN"

    if "observe_web_portal" in obs_preview:
        return "Quan sát màn hình QLTN"
    if "observe_urban_inbox" in obs_preview:
        return "Quan sát hộp thư & bối cảnh tòa nhà"
    if "login_qltn_portal" in obs_preview:
        return "Đăng nhập cổng QLTN"
    return base_label


def _resolve_event_step(
    ev_sim_time: str | None,
    step_slots: list[tuple[int, float]],
    sim_time_to_step: dict[str, int],
) -> int:
    if not step_slots:
        return 1
    if ev_sim_time and ev_sim_time in sim_time_to_step:
        return sim_time_to_step[ev_sim_time]
    ev_ts = _parse_iso_ts(ev_sim_time)
    if ev_ts is None:
        return step_slots[0][0]
    for idx, (step_idx, start_ts) in enumerate(step_slots):
        if idx + 1 < len(step_slots):
            next_ts = step_slots[idx + 1][1]
            if start_ts <= ev_ts < next_ts:
                return step_idx
    if ev_ts < step_slots[0][1]:
        return step_slots[0][0]
    return step_slots[-1][0]


def build_agent_timeline(
    *,
    run_dir: Path,
    persona: dict[str, Any],
    max_steps: int = 200,
) -> dict[str, Any]:
    """Hợp nhất trace, ký ức episodes, sổ tay, replay và sự kiện thành dòng lịch sử thống nhất cho 1 Persona."""
    aid = int(persona["agent_id"])
    agent_root = (run_dir / "agents" / f"agent_{aid:04d}").resolve()

    # 1. Hồ sơ trí nhớ dài hạn, việc cần làm & sổ tay tự học
    memory_md = ""
    todos: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    episodes_by_step: dict[int, list[dict[str, Any]]] = {}
    all_episodes_count = 0

    if agent_root.is_dir() and not agent_root.is_symlink():
        mem_path = agent_root / "MEMORY.md"
        if _is_within_root(mem_path, agent_root):
            memory_md = _safe_read_text(mem_path, max_bytes=64 * 1024)

        todo_path = agent_root / "TODO.json"
        if _is_within_root(todo_path, agent_root):
            todo_data = _safe_read_json(todo_path)
            raw_todos = todo_data.get("todos")
            if isinstance(raw_todos, list):
                todos = [t for t in raw_todos if isinstance(t, dict)]

        ep_path = agent_root / "memory" / "episodes.jsonl"
        if _is_within_root(ep_path, agent_root) and ep_path.is_file() and not ep_path.is_symlink():
            for line in _safe_read_text(ep_path, max_bytes=2 * 1024 * 1024).splitlines():
                s = line.strip()
                if not s:
                    continue
                try:
                    ep = json.loads(s)
                except ValueError:
                    continue
                if not isinstance(ep, dict):
                    continue
                step_idx = int(ep.get("step_index") or ep.get("step_count") or 1)
                ep_type = str(ep.get("type") or "observation").strip()
                episodes_by_step.setdefault(step_idx, []).append(
                    {
                        "id": str(ep.get("id") or ""),
                        "step_index": step_idx,
                        "time": ep.get("time"),
                        "type": ep_type,
                        "type_label": _EPISODE_TYPE_LABELS_VI.get(ep_type, ep_type),
                        "importance": ep.get("importance"),
                        "keywords": list(ep.get("keywords") or [])[:8],
                        "text": str(ep.get("text") or "").strip(),
                    }
                )
                all_episodes_count += 1

        notes_dir = agent_root / "notes"
        if notes_dir.is_dir() and not notes_dir.is_symlink() and _is_within_root(notes_dir, agent_root):
            for fp in sorted(notes_dir.rglob("*"))[:20]:
                if not fp.is_file() or fp.is_symlink() or not _is_within_root(fp, agent_root):
                    continue
                if fp.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml", ""}:
                    continue
                content = _safe_read_text(fp, max_bytes=24 * 1024)
                rel = fp.relative_to(agent_root).as_posix()
                notes.append(
                    {
                        "path": rel,
                        "size_bytes": len(content.encode("utf-8")),
                        "content": content,
                    }
                )

    # 2. Quét trace/trace_*.jsonl với pre-filter chuỗi nhanh cho đúng agent.id
    needle_a = f'"agent.id": {aid}'
    needle_b = f'"agent.id":{aid}'
    spans_by_trace: dict[str, list[dict[str, Any]]] = {}
    trace_files = sorted(glob.glob(str(run_dir / "trace" / "trace_*.jsonl")))
    for fp in trace_files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if needle_a not in line and needle_b not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    res = rec.get("resource") if isinstance(rec.get("resource"), dict) else {}
                    if res.get("agent.id") != aid:
                        continue
                    tid = str(rec.get("trace_id") or "")
                    if tid:
                        spans_by_trace.setdefault(tid, []).append(rec)
        except OSError:
            continue

    step_data: dict[int, dict[str, Any]] = {}
    agent_step_traces: list[tuple[int, int, str, dict[str, Any]]] = []
    for tid, spans in spans_by_trace.items():
        for sp in spans:
            if sp.get("name") == "agent.step":
                attrs = sp.get("attributes") if isinstance(sp.get("attributes"), dict) else {}
                step_idx = int(attrs.get("step.count") or 0)
                start_ns = int(sp.get("start_time_ns") or 0)
                agent_step_traces.append((step_idx, start_ns, tid, sp))

    agent_step_traces.sort(key=lambda item: (item[0] if item[0] > 0 else 999999, item[1]))
    for idx_pos, (raw_step, _, tid, root_sp) in enumerate(agent_step_traces, start=1):
        step_idx = raw_step if raw_step > 0 else idx_pos
        root_attrs = root_sp.get("attributes") if isinstance(root_sp.get("attributes"), dict) else {}
        in_sum = root_attrs.get("input.summary") if isinstance(root_attrs.get("input.summary"), dict) else {}
        out_sum = root_attrs.get("output.summary") if isinstance(root_attrs.get("output.summary"), dict) else {}

        sim_time = str(in_sum.get("time") or "").strip() or None
        step_summary = str(out_sum.get("result") or "").strip()
        end_reason = ""

        child_spans = sorted(
            spans_by_trace.get(tid, []),
            key=lambda s: (
                int((s.get("attributes") or {}).get("event.sequence") or 0),
                int(s.get("start_time_ns") or 0),
            ),
        )

        # Ánh xạ span_id -> turn number để gom react.tool về đúng react.turn
        turn_spans_map: dict[str, dict[str, Any]] = {}
        turns_order: list[dict[str, Any]] = []
        observe_tools: list[dict[str, Any]] = []
        workspace_actions: list[dict[str, Any]] = []
        seen_ws: set[str] = set()
        thoughts: list[str] = []
        observe_ctx: dict[str, Any] = {}

        for sp in child_spans:
            nm = str(sp.get("name") or "")
            attrs = sp.get("attributes") if isinstance(sp.get("attributes"), dict) else {}
            if nm == "react.loop":
                end_reason = str(attrs.get("react.end_reason") or end_reason)
                if not step_summary:
                    loop_out = attrs.get("output.summary") if isinstance(attrs.get("output.summary"), dict) else {}
                    step_summary = str(loop_out.get("final") or "").strip()
            elif nm == "react.turn":
                turn_no = int(attrs.get("react.turn") or (len(turns_order) + 1))
                thought = str(attrs.get("react.thought") or "").strip()
                if thought and thought not in thoughts:
                    thoughts.append(thought)
                turn_obj = {
                    "turn": turn_no,
                    "thought": thought or None,
                    "actions": [],
                }
                turn_spans_map[str(sp.get("span_id") or "")] = turn_obj
                turns_order.append(turn_obj)
            elif nm.startswith("workspace."):
                desc = _describe_workspace_action(nm, attrs)
                rel_p = str(attrs.get("workspace.normalized_path") or attrs.get("workspace.path") or "").strip()
                if desc and desc not in seen_ws:
                    seen_ws.add(desc)
                    workspace_actions.append({"action": nm, "path": rel_p, "summary_vi": desc})

        for sp in child_spans:
            if sp.get("name") != "react.tool":
                continue
            attrs = sp.get("attributes") if isinstance(sp.get("attributes"), dict) else {}
            act = str(attrs.get("react.action") or "tool")
            obs_prev = _obs_to_text(attrs.get("output.summary"), max_len=500)
            if act == "observe" and not observe_ctx:
                observe_ctx = _extract_observe_context(obs_prev)
            raw_args = attrs.get("input.args")
            clean_args = _redact_args(raw_args) if isinstance(raw_args, (dict, list)) else raw_args
            tool_item = {
                "action": act,
                "label_vi": _friendly_env_tool_label(act, obs_prev, raw_args),
                "ok": bool(attrs.get("result.ok", True)),
                "args": clean_args,
                "observation_preview": obs_prev,
            }
            parent_id = str(sp.get("parent_span_id") or "")
            if parent_id in turn_spans_map:
                turn_spans_map[parent_id]["actions"].append(tool_item)
            elif act == "observe":
                observe_tools.append(tool_item)
            elif turns_order:
                turns_order[-1]["actions"].append(tool_item)
            else:
                observe_tools.append(tool_item)

        technical_turns: list[dict[str, Any]] = []
        if observe_tools:
            technical_turns.append({"turn": 0, "thought": None, "actions": observe_tools})
        technical_turns.extend(turns_order)

        step_data[step_idx] = {
            "step_index": step_idx,
            "sim_time": sim_time,
            "zone": observe_ctx.get("current_zone"),
            "time_band": observe_ctx.get("time_band"),
            "unread_messages": observe_ctx.get("unread_messages"),
            "open_incidents_owned": observe_ctx.get("open_incidents_count"),
            "step_summary": step_summary,
            "end_reason": end_reason,
            "thoughts": thoughts,
            "workspace_actions": workspace_actions,
            "technical_turns": technical_turns,
        }

    # 3. Hợp nhất dữ liệu replay/urban_comm_and_incident_agent_state.*.jsonl (zone theo từng step)
    replay_state_by_step: dict[int, dict[str, Any]] = {}
    for fp in sorted(glob.glob(str(run_dir / "replay" / "urban_comm_and_incident_agent_state.*.jsonl"))):
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        row = json.loads(s)
                    except ValueError:
                        continue
                    if int(row.get("agent_id") or -1) != aid:
                        continue
                    st = int(row.get("step") or 0)
                    if st > 0:
                        replay_state_by_step[st] = row
        except OSError:
            continue

    for st, row in replay_state_by_step.items():
        slot = step_data.setdefault(
            st,
            {
                "step_index": st,
                "sim_time": row.get("t"),
                "zone": None,
                "time_band": None,
                "unread_messages": None,
                "open_incidents_owned": None,
                "step_summary": "",
                "end_reason": "",
                "thoughts": [],
                "workspace_actions": [],
                "technical_turns": [],
            },
        )
        if row.get("t") and not slot.get("sim_time"):
            slot["sim_time"] = row.get("t")
        if row.get("current_zone"):
            slot["zone"] = row.get("current_zone")
        if row.get("unread_messages") is not None:
            slot["unread_messages"] = int(row.get("unread_messages") or 0)
        if row.get("open_incidents_owned") is not None:
            slot["open_incidents_owned"] = int(row.get("open_incidents_owned") or 0)

    # Bảo đảm mọi step có episode đều xuất hiện
    for st, eps in episodes_by_step.items():
        slot = step_data.setdefault(
            st,
            {
                "step_index": st,
                "sim_time": eps[0].get("time") if eps else None,
                "zone": None,
                "time_band": None,
                "unread_messages": None,
                "open_incidents_owned": None,
                "step_summary": "",
                "end_reason": "",
                "thoughts": [],
                "workspace_actions": [],
                "technical_turns": [],
            },
        )
        if not slot.get("sim_time") and eps and eps[0].get("time"):
            slot["sim_time"] = eps[0]["time"]

    # Xây dựng bảng tra thời gian từng bước
    ordered_steps = sorted(step_data.keys())
    step_slots: list[tuple[int, float]] = []
    sim_time_to_step: dict[str, int] = {}
    for st in ordered_steps:
        st_time = step_data[st].get("sim_time")
        if st_time and st_time not in sim_time_to_step:
            sim_time_to_step[str(st_time)] = st
        ts = _parse_iso_ts(st_time)
        if ts is not None:
            step_slots.append((st, ts))

    # 4. Đọc urban_events.jsonl & ENV_STATE.json để ghép bằng chứng Web / Atlas / Giao tiếp / Sự vụ
    web_by_step: dict[int, list[dict[str, Any]]] = {}
    atlas_by_step: dict[int, list[dict[str, Any]]] = {}
    comm_by_step: dict[int, list[dict[str, Any]]] = {}
    web_count = 0
    loading_shots_count = 0
    atlas_count = 0
    comm_count = 0
    screenshots_dir = run_dir / "artifacts" / "screenshots"

    events_path = run_dir / "urban_events.jsonl"
    if events_path.is_file():
        for line in _safe_read_text(events_path, max_bytes=16 * 1024 * 1024).splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
            except ValueError:
                continue
            details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
            ev_aid = ev.get("agent_id")
            rec_id = details.get("recipient_id")
            is_sender = ev_aid == aid
            is_recipient = rec_id == aid
            if not is_sender and not is_recipient:
                continue

            stream = str(ev.get("stream") or "").upper()
            ev_sim = str(ev.get("sim_time") or "").strip() or None
            if not step_slots:
                step_data.setdefault(
                    1,
                    {
                        "step_index": 1,
                        "sim_time": ev_sim,
                        "zone": persona.get("home_zone"),
                        "time_band": None,
                        "unread_messages": None,
                        "open_incidents_owned": None,
                        "step_summary": "",
                        "end_reason": "",
                        "thoughts": [],
                        "workspace_actions": [],
                        "technical_turns": [],
                    },
                )
                step_ts = _parse_iso_ts(ev_sim) or 0.0
                step_slots = [(1, step_ts)]
                if ev_sim:
                    sim_time_to_step[ev_sim] = 1

            target_step = _resolve_event_step(ev_sim, step_slots, sim_time_to_step)
            if stream == "WEB" and is_sender:
                shot_status, shot_bytes = classify_screenshot_file(
                    screenshots_dir, ev.get("screenshot_file"), details
                )
                if shot_status is not None:
                    ev["screenshot_status"] = shot_status
                if shot_bytes is not None:
                    ev["screenshot_bytes"] = shot_bytes
                if shot_status in {"LOADING_TIMEOUT", "LOADING_SPLASH_SUSPECTED"}:
                    loading_shots_count += 1
                web_by_step.setdefault(target_step, []).append(ev)
                web_count += 1
            elif stream == "ATLAS" and is_sender:
                atlas_by_step.setdefault(target_step, []).append(ev)
                atlas_count += 1
            elif stream in {"COMM", "INCIDENT"}:
                comm_by_step.setdefault(target_step, []).append(ev)
                comm_count += 1

    comm_state = _safe_read_json(run_dir / "env" / "UrbanCommAndIncidentEnv" / "state" / "ENV_STATE.json")
    incidents_map = comm_state.get("incidents") if isinstance(comm_state.get("incidents"), dict) else {}
    mailboxes = comm_state.get("mailboxes") if isinstance(comm_state.get("mailboxes"), dict) else {}
    agent_mail_inc_ids: set[str] = set()
    for msg in mailboxes.get(str(aid), []) if isinstance(mailboxes.get(str(aid)), list) else []:
        if isinstance(msg, dict) and msg.get("incident_id"):
            agent_mail_inc_ids.add(str(msg["incident_id"]))

    # Gắn sự vụ liên quan theo từng step & tổng hợp toàn run
    all_related_ids: set[str] = set()
    for iid, inc in incidents_map.items():
        if not isinstance(inc, dict):
            continue
        if (
            inc.get("reporter_id") == aid
            or inc.get("assigned_to_id") == aid
            or iid in agent_mail_inc_ids
        ):
            all_related_ids.add(str(iid))

    steps_out: list[dict[str, Any]] = []
    for st in sorted(step_data.keys())[:max_steps]:
        base = step_data[st]
        eps = episodes_by_step.get(st, [])
        w_evs = web_by_step.get(st, [])
        a_evs = atlas_by_step.get(st, [])
        c_evs = comm_by_step.get(st, [])

        # Phát hiện mã sự vụ INC-xxxx xuất hiện trong bước này
        step_inc_ids: set[str] = set()
        text_blobs = [base.get("step_summary") or "", *base.get("thoughts", [])]
        text_blobs.extend(ep.get("text") or "" for ep in eps)
        text_blobs.extend(ev.get("summary") or "" for ev in [*w_evs, *a_evs, *c_evs])
        for blob in text_blobs:
            for m in _INCIDENT_ID_RE.findall(str(blob)):
                step_inc_ids.add(m)
                all_related_ids.add(m)
        for ev in c_evs:
            iid_ev = (ev.get("details") or {}).get("incident_id")
            if iid_ev:
                step_inc_ids.add(str(iid_ev))
                all_related_ids.add(str(iid_ev))

        related_incs = [
            incidents_map[iid]
            for iid in sorted(step_inc_ids)
            if isinstance(incidents_map.get(iid), dict)
        ]

        tech_turns = base.get("technical_turns") or []
        tool_call_count = sum(len(t.get("actions") or []) for t in tech_turns)
        turn_thoughts = [
            {
                "turn": int(t.get("turn") or 0),
                "thought": t["thought"],
                "action_labels": [
                    str(a.get("label_vi") or a.get("action") or "")
                    for a in (t.get("actions") or [])
                    if a.get("label_vi") or a.get("action")
                ],
            }
            for t in tech_turns
            if t.get("thought")
        ]

        steps_out.append(
            {
                "step_index": st,
                "sim_time": base.get("sim_time"),
                "zone": base.get("zone") or persona.get("home_zone"),
                "time_band": base.get("time_band"),
                "unread_messages": base.get("unread_messages"),
                "open_incidents_owned": base.get("open_incidents_owned"),
                "step_summary": base.get("step_summary") or "",
                "end_reason": base.get("end_reason") or "",
                "thoughts": base.get("thoughts") or [],
                "turn_thoughts": turn_thoughts,
                "episodes": eps,
                "workspace_actions": base.get("workspace_actions") or [],
                "web_events": w_evs,
                "atlas_events": a_evs,
                "comm_events": c_evs,
                "related_incidents": related_incs,
                "technical_turns": tech_turns,
                "technical_turn_count": len([t for t in tech_turns if int(t.get("turn") or 0) > 0]),
                "technical_tool_count": tool_call_count,
            }
        )

    all_related_incidents = sorted(
        [incidents_map[iid] for iid in all_related_ids if isinstance(incidents_map.get(iid), dict)],
        key=lambda x: str(x.get("incident_id") or ""),
    )

    return {
        "agent": {
            "agent_id": aid,
            "full_name": persona.get("full_name", f"Tác nhân #{aid}"),
            "role_code": persona.get("role_code", ""),
            "role_title": persona.get("role_title", ""),
            "department": persona.get("department", ""),
            "group_type": persona.get("group_type", "BQL"),
            "home_zone": persona.get("home_zone", ""),
            "software_access_enabled": bool(persona.get("software_access_enabled")),
        },
        "summary": {
            "total_steps": len(steps_out),
            "thoughts_steps_count": sum(1 for s in steps_out if s.get("thoughts")),
            "episodes_count": all_episodes_count,
            "web_events_count": web_count,
            "loading_screenshots_count": loading_shots_count,
            "atlas_events_count": atlas_count,
            "comm_events_count": comm_count,
            "related_incidents_count": len(all_related_incidents),
            "notes_count": len(notes),
            "todos_count": len(todos),
        },
        "steps": steps_out,
        "memory_md": memory_md,
        "todos": todos,
        "notes": notes,
        "all_related_incidents": all_related_incidents,
    }
