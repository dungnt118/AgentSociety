"""Urban Communication & Incident Environment (100% Dynamic Zone Topology — Zero Beijing Map)."""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from agentsociety2.contrib.env._urban_events_sink import (
    append_urban_event,
    effective_caller_agent_id,
)
from agentsociety2.env import EnvBase, tool
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


class UrbanIncident(BaseModel):
    incident_id: str
    reporter_id: int
    reporter_name: str
    zone_key: str
    title: str
    description: str
    priority: str = "NORMAL"
    status: str = "OPEN"  # OPEN | ASSIGNED | IN_PROGRESS | RESOLVED
    assigned_to_id: int | None = None
    resolution_note: str = ""
    created_at: str
    updated_at: str


class UrbanCommAndIncidentEnv(EnvBase):
    """Môi trường giao tiếp nội bộ khu đô thị (Cư dân ↔ Lễ tân ↔ BQL) & quản lý sự vụ/vị trí Zone cấu hình động (không phụ thuộc bản đồ Bắc Kinh)."""

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("current_zone", "TEXT"),
        ColumnDef("current_x_pct", "REAL"),
        ColumnDef("current_y_pct", "REAL"),
        ColumnDef("current_checkpoint_key", "TEXT"),
        ColumnDef("current_activity", "TEXT"),
        ColumnDef("unread_messages", "INTEGER"),
        ColumnDef("open_incidents_owned", "INTEGER"),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_messages", "INTEGER"),
        ColumnDef("total_incidents", "INTEGER"),
        ColumnDef("open_incidents", "INTEGER"),
        ColumnDef("resolved_incidents", "INTEGER"),
    ]

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        return True

    @classmethod
    def description(cls) -> str:
        return "Môi trường giao tiếp cư dân <-> Lễ tân <-> BQL, báo cáo sự vụ thực tế và di chuyển trực quan giữa các Khu vực (Zone) & Chốt/Pin (Checkpoint) trong khu đô thị."

    @classmethod
    def skill_dirs(cls) -> list:
        return [Path(__file__).resolve().parent / "urban_sim_skills" / "resident"]

    def __init__(
        self,
        project_name: str = "Khu đô thị",
        scenario_brief: str = "",
        personas: list[dict[str, Any]] | None = None,
        zones: list[dict[str, Any]] | None = None,
        checkpoints: list[dict[str, Any]] | None = None,
        bql_agent_ids: list[int] | None = None,
        resident_agent_ids: list[int] | None = None,
        events_log_path: str | None = None,
    ):
        super().__init__()
        self._project_name = project_name
        self._scenario_brief = str(scenario_brief or "").strip()[:4000]
        self._personas: dict[int, dict[str, Any]] = {
            int(p["agent_id"]): dict(p) for p in (personas or [])
        }
        self._zones: dict[str, dict[str, Any]] = {}
        raw_zones = list(zones or [])
        cols = max(1, math.ceil(math.sqrt(max(1, len(raw_zones)))))
        for idx, z in enumerate(raw_zones):
            zkey = str(z["zone_key"])
            raw_sig = z.get("ambient_signals")
            if isinstance(raw_sig, list):
                sig_lines = [str(x).strip()[:350] for x in raw_sig if str(x).strip()][:6]
            else:
                sig_lines = [
                    ln.strip()[:350]
                    for ln in str(raw_sig or "").splitlines()
                    if ln.strip()
                ][:6]
            cx = z.get("center_x_pct")
            cy = z.get("center_y_pct")
            poly = z.get("polygon_points")
            if (cx is None or cy is None) and isinstance(poly, list) and len(poly) >= 3:
                try:
                    pts = [(float(pt[0]), float(pt[1])) for pt in poly]
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                except (TypeError, ValueError, IndexError):
                    cx, cy = None, None
            if cx is None or cy is None:
                row_i, col_i = divmod(idx, cols)
                cx = round(14.0 + (col_i + 0.5) * (72.0 / cols), 2)
                cy = round(16.0 + (row_i + 0.5) * (68.0 / max(1, math.ceil(len(raw_zones) / cols))), 2)
            self._zones[zkey] = {
                **dict(z),
                "center_x_pct": round(float(cx), 2),
                "center_y_pct": round(float(cy), 2),
                "description": str(z.get("description") or "").strip()[:240],
                "ambient_signals_list": sig_lines,
            }

        self._checkpoints: dict[str, dict[str, Any]] = {}
        for cp in checkpoints or []:
            if not isinstance(cp, dict):
                continue
            ckey = str(cp.get("checkpoint_key") or "").strip().upper()
            if not ckey:
                continue
            self._checkpoints[ckey] = {
                **dict(cp),
                "checkpoint_key": ckey,
                "name": str(cp.get("name") or ckey).strip(),
                "x_pct": round(float(cp.get("x_pct") or 50.0), 2),
                "y_pct": round(float(cp.get("y_pct") or 50.0), 2),
                "icon_emoji": str(cp.get("icon_emoji") or "📍").strip() or "📍",
                "description_md": str(cp.get("description_md") or "").strip(),
                "zone_key": cp.get("zone_key"),
                "category": str(cp.get("category") or "general").strip().lower(),
            }

        self._bql_ids: set[int] = {int(x) for x in (bql_agent_ids or [])}
        self._resident_ids: set[int] = {int(x) for x in (resident_agent_ids or [])}
        self._events_log_path = events_log_path

        self._lock = asyncio.Lock()
        self._mailboxes: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._incidents: dict[str, UrbanIncident] = {}
        default_z = self._default_zone_key()
        self._agent_zones: dict[int, str] = {
            aid: str(meta.get("home_zone") or default_z)
            for aid, meta in self._personas.items()
        }
        self._agent_positions: dict[int, dict[str, Any]] = {}
        for aid, zkey in self._agent_zones.items():
            zx, zy = self._zone_center(zkey)
            self._agent_positions[aid] = {
                "x_pct": zx,
                "y_pct": zy,
                "zone_key": zkey,
                "checkpoint_key": None,
                "checkpoint_name": None,
                "activity": "",
                "movement_status": "idle",
                "updated_at": None,
            }
        self._last_move_event_seq: int = 0
        self._next_msg_id = 1
        self._next_inc_id = 1

    def _zone_center(self, zone_key: str) -> tuple[float, float]:
        zmeta = self._zones.get(zone_key)
        if zmeta and zmeta.get("center_x_pct") is not None and zmeta.get("center_y_pct") is not None:
            return round(float(zmeta["center_x_pct"]), 2), round(float(zmeta["center_y_pct"]), 2)
        return 50.0, 50.0

    def _default_zone_key(self) -> str:
        for zk, zv in self._zones.items():
            if str(zv.get("zone_type") or "").upper() == "LOBBY":
                return zk
        if self._zones:
            return next(iter(self._zones.keys()))
        return "LOBBY_MAIN"

    def _persona_label(self, agent_id: int) -> tuple[str, str]:
        meta = self._personas.get(int(agent_id), {})
        return str(meta.get("full_name") or f"Agent-{agent_id}"), str(
            meta.get("role_title") or ""
        )

    def _default_receptionist_id(self) -> int:
        for aid, meta in self._personas.items():
            if meta.get("role_code") == "BQL_RECEPTIONIST":
                return int(aid)
        return next(iter(sorted(self._bql_ids)), 1)

    async def to_workspace(self, workspace_path=None) -> None:
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            return
        payload = {
            "mailboxes": {str(k): v for k, v in self._mailboxes.items()},
            "incidents": {
                k: v.model_dump(mode="json") for k, v in self._incidents.items()
            },
            "agent_zones": {str(k): v for k, v in self._agent_zones.items()},
            "agent_positions": {str(k): v for k, v in self._agent_positions.items()},
            "last_move_event_seq": int(self._last_move_event_seq),
            "next_msg_id": self._next_msg_id,
            "next_inc_id": self._next_inc_id,
        }
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    async def restore(self, workspace_path) -> bool:
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._mailboxes = defaultdict(
            list,
            {int(k): list(v) for k, v in (state.get("mailboxes") or {}).items()},
        )
        self._incidents = {
            k: UrbanIncident.model_validate(v)
            for k, v in (state.get("incidents") or {}).items()
        }
        for k, v in (state.get("agent_zones") or {}).items():
            self._agent_zones[int(k)] = str(v)

        saved_positions = state.get("agent_positions") or {}
        if isinstance(saved_positions, dict):
            for k, pos in saved_positions.items():
                if not isinstance(pos, dict):
                    continue
                aid = int(k)
                zkey = str(pos.get("zone_key") or self._agent_zones.get(aid, self._default_zone_key()))
                zx, zy = self._zone_center(zkey)
                self._agent_positions[aid] = {
                    "x_pct": round(float(pos.get("x_pct") if pos.get("x_pct") is not None else zx), 2),
                    "y_pct": round(float(pos.get("y_pct") if pos.get("y_pct") is not None else zy), 2),
                    "zone_key": zkey,
                    "checkpoint_key": pos.get("checkpoint_key"),
                    "checkpoint_name": pos.get("checkpoint_name"),
                    "activity": str(pos.get("activity") or ""),
                    "movement_status": str(pos.get("movement_status") or "idle"),
                    "updated_at": pos.get("updated_at"),
                }
        for aid, zkey in self._agent_zones.items():
            if aid not in self._agent_positions:
                zx, zy = self._zone_center(zkey)
                self._agent_positions[aid] = {
                    "x_pct": zx,
                    "y_pct": zy,
                    "zone_key": zkey,
                    "checkpoint_key": None,
                    "checkpoint_name": None,
                    "activity": "",
                    "movement_status": "idle",
                    "updated_at": None,
                }
        self._last_move_event_seq = int(state.get("last_move_event_seq") or 0)
        self._next_msg_id = int(state.get("next_msg_id") or 1)
        self._next_inc_id = int(state.get("next_inc_id") or 1)
        return True

    def _build_ambient_context(
        self,
        agent_id: int,
        current_zone: str,
        nearby_cps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Tạo tín hiệu bối cảnh vận hành khu đô thị 100% động theo cấu hình Zone trong DB & khung giờ."""
        sim_dt = getattr(self, "t", None)
        sim_time_iso = sim_dt.isoformat() if isinstance(sim_dt, datetime) else ""
        h = sim_dt.hour if isinstance(sim_dt, datetime) else 9
        m = sim_dt.minute if isinstance(sim_dt, datetime) else 0

        zone_meta = self._zones.get(current_zone, {})
        zone_name = str(zone_meta.get("name") or current_zone)
        zone_desc = str(zone_meta.get("description") or "").strip()
        configured_signals = list(zone_meta.get("ambient_signals_list") or [])

        if 6 <= h < 9:
            time_band = "MORNING_RUSH"
            rhythm_note = (
                f"Ca sáng cao điểm tại {zone_name} ({self._project_name}): khung giờ cư dân đi làm/đi học "
                "và các bộ phận BQL (Lễ tân, Kỹ thuật, An ninh, Kế toán Công nợ) khởi động rà soát vận hành."
            )
        elif 9 <= h < 12:
            time_band = "MORNING_WORK"
            rhythm_note = (
                f"Khung giờ hành chính buổi sáng tại {zone_name} ({self._project_name}): tiếp nhận và giải quyết "
                "phản ánh cư dân, phiếu yêu cầu, công việc bảo trì, bãi đỗ xe và công nợ/phí dịch vụ."
            )
        elif 12 <= h < 14:
            time_band = "NOON_REST"
            rhythm_note = (
                f"Giờ nghỉ trưa tại {zone_name} ({self._project_name}): hạn chế tiếng ồn/thi công, "
                "trực sảnh và giao nhận bưu kiện nhẹ."
            )
        elif 14 <= h < 17:
            time_band = "AFTERNOON_OPS"
            rhythm_note = (
                f"Khung giờ hành chính buổi chiều tại {zone_name} ({self._project_name}): xử lý nốt công việc trong ngày, "
                "giao nhận bưu phẩm và đối chiếu thông báo/phí dịch vụ."
            )
        elif 17 <= h < 21:
            time_band = "EVENING_RUSH"
            rhythm_note = (
                f"Giờ cao điểm buổi tối tại {zone_name} ({self._project_name}): mật độ đi lại và gửi xe tăng cao, "
                "tải điện nước sinh hoạt và chiếu sáng hành lang tăng."
            )
        else:
            time_band = "QUIET_NIGHT"
            rhythm_note = (
                f"Khung giờ yên tĩnh ban đêm tại {zone_name} ({self._project_name}): siết chặt kiểm soát ra vào, "
                "thẻ từ, an ninh và tiếng ồn khu căn hộ."
            )

        building_signals: list[str] = list(configured_signals)
        if not building_signals and zone_desc:
            building_signals.append(f"Ngữ cảnh khu vực {zone_name}: {zone_desc}")
        building_signals.append(rhythm_note)

        open_in_zone = sum(
            1
            for inc in self._incidents.values()
            if inc.status != "RESOLVED" and inc.zone_key == current_zone
        )
        open_total = sum(1 for inc in self._incidents.values() if inc.status != "RESOLVED")
        has_own_open = any(
            inc.reporter_id == agent_id and inc.status != "RESOLVED"
            for inc in self._incidents.values()
        )
        receptionist_id = self._default_receptionist_id()
        cp_list_txt = ", ".join(
            f"{c.get('icon_emoji', '📍')} {c.get('checkpoint_key')} ({c.get('name')})"
            for c in (nearby_cps or [])[:5]
        )
        cp_hint = ""
        if cp_list_txt:
            cp_hint = (
                f" Các Chốt thực địa gần đây trên Bản đồ Số: {cp_list_txt}. "
                "Hãy chủ động gọi ask_env(..., readonly=False) với move_to_checkpoint hoặc move_to_zone để di chuyển trực quan trên bản đồ."
            )
        elif self._checkpoints:
            cp_hint = (
                f" Trên Bản đồ Số hiện có {len(self._checkpoints)} Chốt/Pin địa điểm trong map_context.nearby_checkpoints: "
                "hãy chủ động gọi ask_env(..., readonly=False) với move_to_checkpoint hoặc move_to_zone để di chuyển trực quan trên bản đồ."
            )

        if agent_id in self._bql_ids:
            guidance = (
                f"Bạn là nhân sự Ban Quản lý (BQL) đang công tác tại {zone_name} ({current_zone}) lúc {h:02d}:{m:02d} "
                f"(toàn dự án đang có {open_total} sự vụ mở). Hãy kiểm tra hộp thư/sự vụ được giao, tác nghiệp QLTN đúng vai trò "
                "và chủ động tuần tra / kiểm tra hiện trường thực tế (đặc biệt trong lúc chờ CSKH phản hồi)."
                + (
                    cp_hint
                    or " Khi di chuyển giữa các khu vực làm việc, hãy gọi move_to_zone (readonly=False)."
                )
            )
        else:
            guidance = (
                (
                    "Bạn đang có sự vụ mở chưa đóng: ưu tiên kiểm tra tin nhắn mới từ Lễ tân/BQL để phối hợp, chỉ nhắn thêm nếu cần hỏi tiến độ hoặc phản hồi mới (gọi ask_env với readonly=False)."
                    + cp_hint
                )
                if has_own_open
                else (
                    "Bạn là cư dân thật tại căn hộ của mình. Hãy đối chiếu ĐÚNG thông tin căn hộ, số nhân khẩu và phương tiện/thẻ trong hồ sơ <agent> với building_signals tại "
                    f"{zone_name} ({current_zone}) lúc {h:02d}:{m:02d}: nếu phát sinh nhu cầu hoặc bất tiện thực tế, "
                    f"hãy chủ động gọi ask_env(..., readonly=False) dùng report_resident_incident hoặc send_urban_message tới Lễ tân (agent_id={receptionist_id})."
                    + cp_hint
                )
            )
        return {
            "project_name": self._project_name,
            "scenario_brief": self._scenario_brief,
            "sim_time": sim_time_iso,
            "time_band": time_band,
            "zone_key": current_zone,
            "current_zone_detail": {
                "zone_key": current_zone,
                "name": zone_name,
                "zone_type": str(zone_meta.get("zone_type") or ""),
                "description": zone_desc,
                "ambient_signals": configured_signals,
            },
            "building_signals": building_signals,
            "open_incidents_in_zone": open_in_zone,
            "open_incidents_total": open_total,
            "has_own_open_incident": has_own_open,
            "autonomy_guidance": guidance,
        }

    @tool(readonly=True, kind="observe")
    async def observe_urban_inbox(self, agent_id: int) -> dict[str, Any]:
        """Quan sát hộp thư đến, các sự vụ liên quan và danh bạ khu vực/nhân sự của agent."""
        aid = effective_caller_agent_id(agent_id)
        async with self._lock:
            inbox = self._mailboxes.get(aid, [])
            unread = [m for m in inbox if not m.get("read")]
            for m in unread:
                m["read"] = True
            recent_inbox = inbox[-8:]

            if aid in self._bql_ids:
                visible_incidents = [
                    inc.model_dump(mode="json")
                    for inc in self._incidents.values()
                    if inc.status != "RESOLVED"
                ][-15:]
            else:
                visible_incidents = [
                    inc.model_dump(mode="json")
                    for inc in self._incidents.values()
                    if inc.reporter_id == aid
                ][-10:]

            bql_contacts = [
                {
                    "agent_id": m["agent_id"],
                    "full_name": m["full_name"],
                    "role_title": m["role_title"],
                    "zone": m.get("home_zone"),
                }
                for m in self._personas.values()
                if m.get("group_type") == "BQL"
            ]
            current_zone = self._agent_zones.get(aid, self._default_zone_key())
            cur_pos = self._agent_positions.get(aid) or {}
            cur_x = float(cur_pos.get("x_pct") if cur_pos.get("x_pct") is not None else self._zone_center(current_zone)[0])
            cur_y = float(cur_pos.get("y_pct") if cur_pos.get("y_pct") is not None else self._zone_center(current_zone)[1])
            nearby_cps: list[dict[str, Any]] = []
            if self._checkpoints:
                ranked = sorted(
                    self._checkpoints.values(),
                    key=lambda cp: (
                        0 if cp.get("zone_key") == current_zone else 1,
                        math.hypot(float(cp["x_pct"]) - cur_x, float(cp["y_pct"]) - cur_y),
                    ),
                )[:12]
                for cp in ranked:
                    raw_md = str(cp.get("description_md") or "").replace("#", "").strip()
                    first_line = next((ln.strip(" -*") for ln in raw_md.splitlines() if ln.strip()), "")
                    nearby_cps.append(
                        {
                            "checkpoint_key": cp["checkpoint_key"],
                            "name": cp["name"],
                            "icon_emoji": cp.get("icon_emoji") or "📍",
                            "zone_key": cp.get("zone_key"),
                            "category": cp.get("category") or "general",
                            "summary": first_line[:120],
                        }
                    )

            ambient = self._build_ambient_context(aid, current_zone, nearby_cps=nearby_cps)
            return {
                "agent_id": aid,
                "current_zone": current_zone,
                "current_checkpoint_key": cur_pos.get("checkpoint_key"),
                "current_x_pct": round(cur_x, 2),
                "current_y_pct": round(cur_y, 2),
                "current_activity": cur_pos.get("activity") or "",
                "map_context": {
                    "current_zone": current_zone,
                    "current_checkpoint_key": cur_pos.get("checkpoint_key"),
                    "current_x_pct": round(cur_x, 2),
                    "current_y_pct": round(cur_y, 2),
                    "current_activity": cur_pos.get("activity") or "",
                    "nearby_checkpoints": nearby_cps,
                },
                "sim_time": ambient["sim_time"],
                "building_context": ambient,
                "unread_count": len(unread),
                "recent_messages": recent_inbox,
                "visible_incidents": visible_incidents,
                "bql_contacts": bql_contacts if aid in self._bql_ids else [
                    c for c in bql_contacts if c["agent_id"] == self._default_receptionist_id()
                ],
                "zones": list(self._zones.keys()),
                "zone_details": [
                    {
                        "zone_key": zk,
                        "name": zv.get("name", zk),
                        "zone_type": zv.get("zone_type", ""),
                        "description": zv.get("description", ""),
                        "ambient_signals": zv.get("ambient_signals_list", []),
                    }
                    for zk, zv in self._zones.items()
                ],
            }

    @tool(readonly=False)
    async def report_resident_incident(
        self,
        agent_id: int,
        title: str,
        description: str,
        zone_key: str = "",
        recipient_agent_id: int | None = None,
        priority: str = "NORMAL",
    ) -> dict[str, Any]:
        """Gửi báo cáo sự vụ/yêu cầu dịch vụ từ cư dân (hoặc nhân sự) tới Lễ tân."""
        aid = effective_caller_agent_id(agent_id)
        target_id = int(recipient_agent_id or self._default_receptionist_id())
        async with self._lock:
            inc_id = f"INC-{self._next_inc_id:04d}"
            self._next_inc_id += 1
            r_name, r_role = self._persona_label(aid)
            zone = zone_key.strip() or self._agent_zones.get(aid, self._default_zone_key())
            now_str = self.t.isoformat()
            inc = UrbanIncident(
                incident_id=inc_id,
                reporter_id=aid,
                reporter_name=r_name,
                zone_key=zone,
                title=title.strip() or "Phản ánh cư dân",
                description=description.strip(),
                priority=priority.upper() if priority.upper() in {"LOW", "NORMAL", "HIGH", "URGENT"} else "NORMAL",
                status="OPEN",
                created_at=now_str,
                updated_at=now_str,
            )
            self._incidents[inc_id] = inc

            msg_id = self._next_msg_id
            self._next_msg_id += 1
            msg = {
                "message_id": msg_id,
                "sender_id": aid,
                "sender_name": r_name,
                "recipient_id": target_id,
                "incident_id": inc_id,
                "content": f"[{inc_id} - {inc.title}] {inc.description}",
                "timestamp": now_str,
                "read": False,
            }
            self._mailboxes[target_id].append(msg)

        t_name, _ = self._persona_label(target_id)
        append_urban_event(
            self._events_log_path,
            stream="COMM",
            agent_id=aid,
            agent_name=r_name,
            role_title=r_role,
            action="report_resident_incident",
            summary=f"{r_name} -> {t_name}: [{inc_id}] {inc.title}",
            sim_time=self.t,
            details={"incident": inc.model_dump(mode="json"), "recipient_id": target_id},
        )
        return {"ok": True, "incident": inc.model_dump(mode="json"), "sent_to_agent_id": target_id}

    @tool(readonly=False)
    async def send_urban_message(
        self,
        agent_id: int,
        recipient_agent_id: int,
        content: str,
        related_incident_id: str = "",
    ) -> dict[str, Any]:
        """Gửi tin nhắn trao đổi trực tiếp giữa Cư dân ↔ Lễ tân hoặc điều phối giữa các nhân sự BQL."""
        aid = effective_caller_agent_id(agent_id)
        target_id = int(recipient_agent_id)
        if target_id not in self._personas:
            return {"ok": False, "error": f"Không tìm thấy người nhận agent_id={target_id}"}
        if aid in self._resident_ids and target_id not in self._bql_ids:
            return {"ok": False, "error": "Cư dân chỉ giao tiếp với bộ phận Lễ tân/BQL."}

        async with self._lock:
            msg_id = self._next_msg_id
            self._next_msg_id += 1
            s_name, s_role = self._persona_label(aid)
            t_name, _ = self._persona_label(target_id)
            now_str = self.t.isoformat()
            msg = {
                "message_id": msg_id,
                "sender_id": aid,
                "sender_name": s_name,
                "recipient_id": target_id,
                "incident_id": related_incident_id.strip() or None,
                "content": content.strip(),
                "timestamp": now_str,
                "read": False,
            }
            self._mailboxes[target_id].append(msg)

        append_urban_event(
            self._events_log_path,
            stream="COMM",
            agent_id=aid,
            agent_name=s_name,
            role_title=s_role,
            action="send_urban_message",
            summary=f"{s_name} -> {t_name}: {content.strip()[:140]}",
            sim_time=self.t,
            details={"recipient_id": target_id, "recipient_name": t_name, "incident_id": related_incident_id, "content": content.strip()},
        )
        return {"ok": True, "message_id": msg_id, "recipient_id": target_id}

    @tool(readonly=False)
    async def manage_incident(
        self,
        agent_id: int,
        incident_id: str,
        new_status: str = "IN_PROGRESS",
        assign_to_agent_id: int | None = None,
        resolution_note: str = "",
    ) -> dict[str, Any]:
        """Điều phối/cập nhật trạng thái sự vụ nội bộ (Chỉ dành cho Ban Quản Lý)."""
        aid = effective_caller_agent_id(agent_id)
        if aid not in self._bql_ids:
            return {
                "ok": False,
                "error": "ACCESS_DENIED: Cư dân không có quyền điều phối sự vụ nội bộ BQL.",
            }
        allowed_status = {"OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED"}
        st = new_status.strip().upper()
        if st not in allowed_status:
            return {"ok": False, "error": f"Trạng thái '{new_status}' không hợp lệ."}

        async with self._lock:
            inc = self._incidents.get(incident_id.strip())
            if inc is None:
                return {"ok": False, "error": f"Không tìm thấy sự vụ {incident_id}"}
            inc.status = st
            if assign_to_agent_id is not None:
                inc.assigned_to_id = int(assign_to_agent_id)
            if resolution_note.strip():
                inc.resolution_note = resolution_note.strip()
            inc.updated_at = self.t.isoformat()

            actor_name, actor_role = self._persona_label(aid)
            if assign_to_agent_id is not None and int(assign_to_agent_id) in self._personas:
                msg_id = self._next_msg_id
                self._next_msg_id += 1
                self._mailboxes[int(assign_to_agent_id)].append(
                    {
                        "message_id": msg_id,
                        "sender_id": aid,
                        "sender_name": actor_name,
                        "recipient_id": int(assign_to_agent_id),
                        "incident_id": inc.incident_id,
                        "content": f"[Phân công {inc.incident_id}] {inc.title} — Trạng thái: {st}. {resolution_note.strip()}",
                        "timestamp": inc.updated_at,
                        "read": False,
                    }
                )
            inc_dump = inc.model_dump(mode="json")

        append_urban_event(
            self._events_log_path,
            stream="INCIDENT",
            agent_id=aid,
            agent_name=actor_name,
            role_title=actor_role,
            action="manage_incident",
            summary=f"[{inc.incident_id}] -> {st} ({resolution_note.strip()[:100] or 'Cập nhật xử lý'})",
            sim_time=self.t,
            details=inc_dump,
        )
        return {"ok": True, "incident": inc_dump}

    @tool(readonly=False)
    async def move_to_zone(
        self,
        agent_id: int,
        zone_key: str,
        activity: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Di chuyển sang khu vực (Zone) khác trong khu đô thị và cập nhật tọa độ trên Bản đồ Số."""
        aid = effective_caller_agent_id(agent_id)
        z = zone_key.strip()
        if self._zones and z not in self._zones:
            return {"ok": False, "error": f"Khu vực '{z}' không tồn tại. Khả dụng: {list(self._zones.keys())}"}
        to_x, to_y = self._zone_center(z)
        act_text = (activity or reason or "").strip()[:140]
        now_str = self.t.isoformat() if isinstance(getattr(self, "t", None), datetime) else ""
        async with self._lock:
            prev = self._agent_zones.get(aid, self._default_zone_key())
            prev_pos = self._agent_positions.get(aid) or {}
            from_x = float(prev_pos.get("x_pct") if prev_pos.get("x_pct") is not None else self._zone_center(prev)[0])
            from_y = float(prev_pos.get("y_pct") if prev_pos.get("y_pct") is not None else self._zone_center(prev)[1])
            from_cp = prev_pos.get("checkpoint_key")
            self._agent_zones[aid] = z
            self._agent_positions[aid] = {
                "x_pct": to_x,
                "y_pct": to_y,
                "zone_key": z,
                "checkpoint_key": None,
                "checkpoint_name": None,
                "activity": act_text,
                "movement_status": "moving",
                "updated_at": now_str,
            }
        name, role = self._persona_label(aid)
        ev_rec = append_urban_event(
            self._events_log_path,
            stream="COMM",
            agent_id=aid,
            agent_name=name,
            role_title=role,
            action="move_to_zone",
            summary=f"{name} di chuyển {prev} -> {z}" + (f" ({act_text})" if act_text else ""),
            sim_time=getattr(self, "t", None),
            details={
                "from_zone": prev,
                "to_zone": z,
                "from_checkpoint_key": from_cp,
                "from_x_pct": round(from_x, 2),
                "from_y_pct": round(from_y, 2),
                "to_x_pct": to_x,
                "to_y_pct": to_y,
                "activity": act_text,
                "movement_status": "moving",
            },
        )
        if isinstance(ev_rec, dict) and ev_rec.get("seq"):
            self._last_move_event_seq = max(self._last_move_event_seq, int(ev_rec["seq"]))
        return {
            "ok": True,
            "agent_id": aid,
            "zone_key": z,
            "x_pct": to_x,
            "y_pct": to_y,
            "activity": act_text,
        }

    @tool(readonly=False)
    async def move_to_checkpoint(
        self,
        agent_id: int,
        checkpoint_key: str,
        activity: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Di chuyển tới một Chốt/Pin địa điểm cụ thể trên Bản đồ Số (tuần tra, kiểm tra, sinh hoạt tiện ích)."""
        aid = effective_caller_agent_id(agent_id)
        ckey = checkpoint_key.strip().upper()
        cp = self._checkpoints.get(ckey)
        if cp is None:
            for item in self._checkpoints.values():
                if item.get("name", "").strip().lower() == checkpoint_key.strip().lower():
                    cp = item
                    ckey = item["checkpoint_key"]
                    break
        if cp is None:
            return {
                "ok": False,
                "error": f"Chốt '{checkpoint_key}' không tồn tại trên Bản đồ Số. Khả dụng: {list(self._checkpoints.keys())[:15]}",
            }
        to_x = round(float(cp["x_pct"]), 2)
        to_y = round(float(cp["y_pct"]), 2)
        cp_zone = cp.get("zone_key")
        act_text = (activity or note or "").strip()[:140]
        cat = str(cp.get("category") or "general").lower()
        mv_status = {
            "security": "patrolling",
            "facility": "working",
            "service": "working",
            "amenity": "leisure",
        }.get(cat, "moving")
        now_str = self.t.isoformat() if isinstance(getattr(self, "t", None), datetime) else ""
        async with self._lock:
            prev_zone = self._agent_zones.get(aid, self._default_zone_key())
            prev_pos = self._agent_positions.get(aid) or {}
            from_x = float(prev_pos.get("x_pct") if prev_pos.get("x_pct") is not None else self._zone_center(prev_zone)[0])
            from_y = float(prev_pos.get("y_pct") if prev_pos.get("y_pct") is not None else self._zone_center(prev_zone)[1])
            from_cp = prev_pos.get("checkpoint_key")
            next_zone = str(cp_zone) if cp_zone and (not self._zones or cp_zone in self._zones) else prev_zone
            self._agent_zones[aid] = next_zone
            self._agent_positions[aid] = {
                "x_pct": to_x,
                "y_pct": to_y,
                "zone_key": next_zone,
                "checkpoint_key": ckey,
                "checkpoint_name": cp["name"],
                "activity": act_text or cp["name"],
                "movement_status": mv_status,
                "updated_at": now_str,
            }
        name, role = self._persona_label(aid)
        ev_rec = append_urban_event(
            self._events_log_path,
            stream="COMM",
            agent_id=aid,
            agent_name=name,
            role_title=role,
            action="move_to_checkpoint",
            summary=f"{name} -> {cp.get('icon_emoji', '📍')} {cp['name']}" + (f" ({act_text})" if act_text else ""),
            sim_time=getattr(self, "t", None),
            details={
                "from_zone": prev_zone,
                "to_zone": next_zone,
                "from_checkpoint_key": from_cp,
                "checkpoint_key": ckey,
                "checkpoint_name": cp["name"],
                "icon_emoji": cp.get("icon_emoji") or "📍",
                "from_x_pct": round(from_x, 2),
                "from_y_pct": round(from_y, 2),
                "to_x_pct": to_x,
                "to_y_pct": to_y,
                "activity": act_text or cp["name"],
                "movement_status": mv_status,
                "note": note.strip()[:200],
            },
        )
        if isinstance(ev_rec, dict) and ev_rec.get("seq"):
            self._last_move_event_seq = max(self._last_move_event_seq, int(ev_rec["seq"]))
        return {
            "ok": True,
            "agent_id": aid,
            "checkpoint_key": ckey,
            "checkpoint_name": cp["name"],
            "icon_emoji": cp.get("icon_emoji") or "📍",
            "zone_key": next_zone,
            "x_pct": to_x,
            "y_pct": to_y,
            "activity": act_text or cp["name"],
            "movement_status": mv_status,
            "description_md": cp.get("description_md") or "",
        }

    async def step(self, tick: int, t: datetime):
        self.t = t
        async with self._lock:
            step_idx = int(getattr(self, "_step_idx", 0)) + 1
            self._step_idx = step_idx
            records = []
            for aid in sorted(self._personas):
                unread_cnt = sum(1 for m in self._mailboxes.get(aid, []) if not m.get("read"))
                owned_open = sum(
                    1
                    for inc in self._incidents.values()
                    if inc.status != "RESOLVED" and (inc.assigned_to_id == aid or inc.reporter_id == aid)
                )
                cur_z = self._agent_zones.get(aid, self._default_zone_key())
                pos = self._agent_positions.get(aid) or {}
                zx, zy = self._zone_center(cur_z)
                records.append(
                    {
                        "agent_id": aid,
                        "current_zone": cur_z,
                        "current_x_pct": float(pos.get("x_pct") if pos.get("x_pct") is not None else zx),
                        "current_y_pct": float(pos.get("y_pct") if pos.get("y_pct") is not None else zy),
                        "current_checkpoint_key": pos.get("checkpoint_key") or "",
                        "current_activity": pos.get("activity") or "",
                        "unread_messages": unread_cnt,
                        "open_incidents_owned": owned_open,
                    }
                )
            total_msgs = sum(len(v) for v in self._mailboxes.values())
            total_inc = len(self._incidents)
            open_inc = sum(1 for inc in self._incidents.values() if inc.status != "RESOLVED")
            res_inc = sum(1 for inc in self._incidents.values() if inc.status == "RESOLVED")

        await self._write_agent_state_batch(step_idx, t, records)
        await self._write_env_state(
            step_idx,
            t,
            total_messages=total_msgs,
            total_incidents=total_inc,
            open_incidents=open_inc,
            resolved_incidents=res_inc,
        )
