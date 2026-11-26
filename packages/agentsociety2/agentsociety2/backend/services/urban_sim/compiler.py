"""Dynamic compiler: Database SSOT -> init_config.json, steps.yaml, prompt_overrides.json & encrypted vault."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentsociety2.backend.services.urban_sim.competency import (
    DEBRIEF_QUESTIONNAIRE_ID,
    QUIZ_POST_ID,
    QUIZ_PRE_ID,
    build_quiz_question_items,
    build_sociological_debrief_questions,
    parse_or_default_rubric,
)
from agentsociety2.backend.services.urban_sim.crypto import (
    decrypt_secret,
    encrypt_vault_blob,
)
from agentsociety2.backend.services.urban_sim.db import (
    UrbanSimAtlasConfig,
    UrbanSimPersona,
    UrbanSimProject,
    UrbanSimZone,
)
from agentsociety2.storage.workspace_state import atomic_write_text

URBAN_SIM_BASE_RULES = """<identity>
Bạn là một nhân sự hoặc cư dân người Việt đang sống và làm việc thực tế trong khu đô thị chung cư MulberryLane (không phải trợ lý AI). Hãy giữ đúng vai trò, tính cách, thông tin hồ sơ thực tế và nguyên tắc nghiệp vụ trong thẻ <agent>. Toàn bộ suy nghĩ (`thought`), ghi nhớ (`memories`), tin nhắn và câu hỏi BẮT BUỘC viết bằng 100% Tiếng Việt chuẩn tự nhiên (tuyệt đối không chêm từ ngoại ngữ như tiếng Nga, tiếng Hindi, tiếng Trung hoặc từ kỹ thuật lẫn lộn).
- QUY TẮC BẮT BUỘC VỀ `readonly` KHI GỌI `ask_env`:
  + CHỈ đặt `readonly=true` khi bạn thuần túy chỉ muốn đọc/quan sát (`observe_urban_inbox`, `observe_web_portal`).
  + BẮT BUỘC đặt **`readonly=false`** mỗi khi gọi bất kỳ hành động nào: `login_qltn_portal`, `click_web_text`, `click_web_element`, `fill_web_input`, `select_web_option`, `navigate_web_path`, `ask_atlas_support`, `report_resident_incident`, `send_urban_message`, `manage_incident`, `move_to_zone`. TUYỆT ĐỐI KHÔNG gộp lệnh "quan sát rồi đăng nhập/bấm/hỏi/gửi tin" trong `ask_env(..., readonly=true)`.
- Nếu bạn là Nhân sự Ban Quản lý (`BQL`, `software_access_enabled=true`): bạn có chuyên môn ngành Quản lý Vận hành Tòa nhà theo đúng chức danh, NHƯNG kiến thức sử dụng phần mềm web Demego QLTN ban đầu bằng 0 (lần đầu tiếp xúc phần mềm).
  1. Ở Tick 1, kiểm tra hộp thư (`observe_urban_inbox`) và **đăng nhập ngay QLTN** bằng `ask_env(..., readonly=false)` gọi `login_qltn_portal`.
  2. KHÔNG ĐƯỢC kết thúc lượt chỉ bằng lời hứa "lượt sau sẽ làm/sẽ tìm hiểu"! Ngay trong lượt hiện tại sau khi vào `/home` QLTN:
     - Nếu trong `notes/atlas_guides.md` chưa có hướng dẫn thao tác cho chức danh của bạn, hãy **gọi ngay `ask_env(..., readonly=false, ctx={"attach_screenshot": true})`** với `instruction="Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua ask_atlas_support: <câu hỏi tự nhiên>"` để hỏi đường dẫn/cách làm nghiệp vụ trên QLTN, rồi lưu lại vào `notes/atlas_guides.md`.
     - **Phản xạ Leo thang khi gặp sự cố (Failure-Escalation — áp dụng ở MỌI bước, kể cả khi đã có `notes/atlas_guides.md`):** Nếu gặp bất kỳ tình huống nào sau đây: (a) bấm hoặc tìm chức năng trên web thất bại (`ok=False`) sau 1–2 lần thử, (b) phần mềm báo không đủ quyền (`Bạn không có quyền xem...`) hoặc thiếu cấu hình biểu mẫu (`Không có loại phiếu`), hoặc (c) số liệu/danh sách trên màn hình mâu thuẫn bất thường (ví dụ badge báo `99+` nhưng bảng trống hoặc chỉ số mở bằng `0`), **KHÔNG dừng ở việc ghi chú thụ động** — hãy gọi ngay `ask_env(..., readonly=false, ctx={"attach_screenshot": true})` với `instruction="Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua ask_atlas_support: <mô tả màn hình và vướng mắc vừa gặp>"` (trong hạn mức cho phép mỗi bước) để nhận hướng dẫn xử lý thực tế.
     - Kênh CSKH này đại diện cho Đội ngũ trợ lý của Thần Nông (có thể gồm cả chuyên viên người thật và trợ lý hỗ trợ), vì vậy phần `<câu hỏi tự nhiên>` hãy giao tiếp như người với người: đi thẳng vào vướng mắc thực tế trên màn hình; **TUYỆT ĐỐI CẤM** nhắc tên `"EvidenceAtlas"`, `"bot"` hay `"agent_id"`, **CẤM** thêm câu ra lệnh định dạng kiểu chatbot như `"Vui lòng trả lời ngắn gọn bằng tiếng Việt"` hay viết `"kèm ảnh chụp màn hình"` vào nội dung câu hỏi.
     - Đồng thời dùng **`click_web_text` (`readonly=false`)** (vd: `"Phiếu yêu cầu"`, `"Phản ánh qua App"`, `"Công việc"`, `"Công việc thực thi"`, `"Danh sách bãi đỗ"`, `"Việc chờ"`, `"Cư dân"`) để mở trực tiếp phân hệ thật trên QLTN thay vì dừng mãi ở `/home`.
  3. Khi thấy sự vụ/tin nhắn từ Cư dân trong `observe_urban_inbox`: Lễ tân (`agent_id=3`) phải vừa kiểm tra/tạo phản ánh trên QLTN, vừa chuyển việc tới Kỹ thuật / An ninh / Kế toán Công nợ (đối với phản ánh phí dịch vụ, hóa đơn, công nợ, gạch nợ) qua `send_urban_message` (`readonly=false`) và phản hồi Cư dân ngay. Đồng thời luôn đọc `building_context.scenario_brief` và `building_context.building_signals` trong `observe_urban_inbox` để nắm thực trạng chung của khu đô thị trong ca làm việc.
  4. Ghi nhớ quy trình học được qua `finish(memories=[...])` và/hoặc `write("notes/atlas_guides.md", ...)` — TUYỆT ĐỐI KHÔNG tự ý ghi/chỉnh trực tiếp `MEMORY.md`.
- Nếu bạn là Cư dân Chủ hộ (`RESIDENT`, `software_access_enabled=false`): bạn KHÔNG có quyền truy cập phần mềm QLTN nội bộ hay kênh hỗ trợ CSKH nội bộ, và KHÔNG dùng bản đồ Bắc Kinh hay `story.yaml` cũ. Ở mỗi bước hãy gọi `observe_urban_inbox` (`readonly=True`), đọc `building_context.building_signals` và đối chiếu với ĐÚNG thông tin căn hộ, số nhân khẩu, biển số xe thật của bạn trong `<agent>` (tuyệt đối không bịa thêm xe nếu hồ sơ ghi 0 xe). Khi thấy trải nghiệm sự cố/bất tiện trực tiếp ảnh hưởng tới căn hộ hoặc xe thật của mình và `has_own_open_incident == false`, KHÔNG ĐƯỢC kết thúc lượt bằng "để lượt sau" — hãy gọi NGAY `ask_env(..., readonly=false)` dùng `report_resident_incident` (`recipient_agent_id=3`) hoặc `send_urban_message` gửi Lễ tân (`agent_id=3`) trong chính tick đó! Khi đã có sự vụ mở thì chỉ theo dõi/phản hồi tin mới từ Lễ tân.
</identity>

<decision_workflow>
Mọi hành động BẮT BUỘC dùng OpenAI tool calls. Có thể gộp nhiều lệnh đọc độc lập trong cùng một lượt.
- (Chỉ ở chế độ step) Trước khi gọi `ask_env` ở mỗi lượt, hãy viết 1–2 câu ngắn gọn ở ngôi thứ nhất bằng Tiếng Việt tự nhiên (đồng thời điền vào tham số `thought` của `ask_env`) nêu rõ mục tiêu/suy nghĩ khởi phát của chính nhân vật (ví dụ: "Tôi sẽ mở mục Phiếu yêu cầu trên QLTN để kiểm tra xem hôm nay có phản ánh mới nào không"); tuyệt đối không viết JSON thô hay tên hàm kỹ thuật vào phần suy nghĩ này.
1. Đọc kỹ `<agent>`, `<turn_state>`, `<todo_context>`, `<activated_skills>` và `<recent_observations>`.
2. Kiểm tra hộp thư/sự vụ (`observe_urban_inbox`) và trạng thái màn hình hiện tại (với BQL). Cập nhật danh sách việc cần làm (`todo_*`) khi phù hợp.
3. Để thao tác môi trường (đăng nhập web, bấm menu, báo sự cố/gửi tin), gọi `ask_env` với `readonly=false` và nêu rõ hành động bằng Tiếng Việt. Riêng khi cần nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua `ask_atlas_support`, hãy viết đúng lời hỏi tự nhiên như nhân sự đang trao đổi với người hỗ trợ (không dùng văn phong ra lệnh cho bot hay nhồi từ khóa điều khiển định dạng).
4. Kết thúc mỗi tick bằng một lần gọi `finish`: ở chế độ `step` hãy điền những thông tin/kinh nghiệm mới học được vào `memories` bằng Tiếng Việt để nhớ sang bước tiếp theo; ở chế độ `ask` trả đúng câu trả lời vào `answer`.
</decision_workflow>"""


def _sanitize_legacy_bql_prompt_text(text: str) -> str:
    """Làm sạch mềm các cụm nhắc 'EvidenceAtlas' từ bản seed cũ khi biên dịch Run mới."""
    cleaned = str(text or "")
    if not cleaned:
        return ""
    replacements = [
        (r"ask_atlas_support\s*/\s*EvidenceAtlas", "ask_atlas_support — kênh hỗ trợ CSKH Thần Nông"),
        (r"\bhỏi\s+CSKH\s+EvidenceAtlas\b", "nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông"),
        (r"\bHỏi\s+CSKH\s+EvidenceAtlas\b", "Nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông"),
        (r"\bhỏi\s+EvidenceAtlas\b", "nhắn hỏi Đội ngũ CSKH Thần Nông"),
        (r"\bHỏi\s+EvidenceAtlas\b", "Nhắn hỏi Đội ngũ CSKH Thần Nông"),
        (r"\bEvidenceAtlas\b", "Đội ngũ CSKH Thần Nông"),
    ]
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned)
    return cleaned


@dataclass(frozen=True)
class CompiledRunBundle:
    config_path: Path
    steps_path: Path
    vault_path: Path
    prompt_overrides_path: Path
    active_agent_count: int
    bql_software_count: int
    resident_count: int


def compile_run_from_db(
    *,
    project: UrbanSimProject,
    personas: list[UrbanSimPersona],
    atlas: UrbanSimAtlasConfig | None,
    zones: list[UrbanSimZone],
    run_dir: Path,
    workspace_root: Path | None = None,
) -> CompiledRunBundle:
    """Compile active DB configuration into clean simulation inputs under ``run_dir`` without leaking secrets."""
    run_dir = Path(run_dir).resolve()
    init_dir = run_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = (run_dir / "artifacts" / "screenshots").resolve()
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    active = [p for p in personas if p.is_active]
    if project.pilot_mode:
        pilot_filtered = [p for p in active if p.is_pilot_member]
        if pilot_filtered:
            active = pilot_filtered
    active.sort(key=lambda item: item.agent_id)
    if not active:
        raise ValueError("Dự án chưa có Persona nào được bật (is_active=True) để chạy mô phỏng.")

    software_ids = sorted(p.agent_id for p in active if p.software_access_enabled)
    resident_ids = sorted(p.agent_id for p in active if not p.software_access_enabled)
    bql_ids = sorted(p.agent_id for p in active if p.group_type == "BQL")

    # Build directory of safe public persona descriptors (NO credentials)
    agent_directory = [
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
        for p in active
    ]
    zone_directory = [
        {
            "zone_key": z.zone_key,
            "name": z.name,
            "zone_type": z.zone_type,
            "description": z.description,
        }
        for z in sorted(zones, key=lambda item: item.sort_order)
    ]

    # Build encrypted runtime secret vault (0 plaintext passwords or API keys in init_config.json!)
    portal_credentials: dict[str, dict[str, str]] = {}
    for p in active:
        if p.software_access_enabled:
            portal_credentials[str(p.agent_id)] = {
                "portal_url": (p.portal_url or project.default_portal_url).strip(),
                "username": (p.login_username or "").strip(),
                "password": decrypt_secret(p.login_password_enc, workspace_root),
            }

    blocked_keywords: list[str] = []
    atlas_secret: dict[str, Any] = {
        "enabled": bool(atlas and atlas.enabled),
        "atlas_api_url": (atlas.atlas_api_url if atlas else "https://atlas.demego.vn").strip(),
        "atlas_api_key": decrypt_secret(atlas.atlas_api_key_enc, workspace_root) if atlas else "",
        "actor_persona": (atlas.actor_persona if atlas else "END_USER"),
        "source_mode": (atlas.source_mode if atlas else "FEDERATED_AUTO"),
        "attach_screenshot_on_ask": bool(atlas and atlas.attach_screenshot_on_ask),
        "quota_per_min": int(atlas.quota_per_min if atlas else 25),
        "max_asks_per_tick": int(atlas.max_asks_per_tick if atlas else 2),
    }
    guardrail_mode = atlas.guardrail_mode if atlas else "SAFE_WRITE"
    record_prefix = atlas.record_prefix if atlas else "[SIM-BQL]"
    if atlas and atlas.blocked_keywords_json:
        try:
            loaded_kw = json.loads(atlas.blocked_keywords_json)
            if isinstance(loaded_kw, list):
                blocked_keywords = [str(k).strip().lower() for k in loaded_kw if str(k).strip()]
        except json.JSONDecodeError:
            blocked_keywords = []

    vault_path = (run_dir / ".run_secrets.enc").resolve()
    vault_token = encrypt_vault_blob(
        {"portal_credentials": portal_credentials, "atlas": atlas_secret},
        workspace_root,
    )
    atomic_write_text(vault_path, vault_token)
    try:
        os.chmod(vault_path, 0o600)
    except OSError:
        pass

    scenario_brief = (getattr(project, "description", "") or "").strip()[:4000]
    env_modules: list[dict[str, Any]] = [
        {
            "module_type": "UrbanCommAndIncidentEnv",
            "kwargs": {
                "project_name": project.name,
                "scenario_brief": scenario_brief,
                "personas": agent_directory,
                "zones": zone_directory,
                "bql_agent_ids": bql_ids,
                "resident_agent_ids": resident_ids,
                "events_log_path": str((run_dir / "urban_events.jsonl").resolve()),
            },
        }
    ]

    if software_ids:
        env_modules.append(
            {
                "module_type": "DemegoWebPortalEnv",
                "kwargs": {
                    "allowed_agent_ids": software_ids,
                    "default_portal_url": project.default_portal_url,
                    "secrets_vault_path": str(vault_path),
                    "screenshots_dir": str(screenshots_dir),
                    "events_log_path": str((run_dir / "urban_events.jsonl").resolve()),
                    "guardrail_mode": guardrail_mode,
                    "record_prefix": record_prefix,
                    "blocked_keywords": blocked_keywords,
                    "personas_meta": {
                        str(item["agent_id"]): {
                            "full_name": item["full_name"],
                            "role_title": item["role_title"],
                        }
                        for item in agent_directory
                    },
                },
            }
        )
        if atlas and atlas.enabled:
            env_modules.append(
                {
                    "module_type": "EvidenceAtlasSupportEnv",
                    "kwargs": {
                        "allowed_agent_ids": software_ids,
                        "secrets_vault_path": str(vault_path),
                        "screenshots_dir": str(screenshots_dir),
                        "events_log_path": str((run_dir / "urban_events.jsonl").resolve()),
                        "atlas_api_url": atlas.atlas_api_url,
                        "actor_persona": atlas.actor_persona,
                        "source_mode": atlas.source_mode,
                        "attach_screenshot_on_ask": bool(atlas.attach_screenshot_on_ask),
                        "quota_per_min": int(atlas.quota_per_min),
                        "max_asks_per_tick": int(atlas.max_asks_per_tick),
                        "personas_meta": {
                            str(item["agent_id"]): {
                                "full_name": item["full_name"],
                                "role_title": item["role_title"],
                            }
                            for item in agent_directory
                        },
                    },
                }
            )

    receptionist_id = next(
        (p.agent_id for p in active if p.role_code == "BQL_RECEPTIONIST"),
        next((p.agent_id for p in active if p.group_type == "BQL"), 1),
    )

    agents_cfg: list[dict[str, Any]] = []
    for p in active:
        try:
            tasks = json.loads(p.initial_tasks_json or "[]")
            if not isinstance(tasks, list):
                tasks = []
        except json.JSONDecodeError:
            tasks = []
        is_bql_or_sw = bool(p.software_access_enabled or p.group_type == "BQL")
        clean_tasks = [
            _sanitize_legacy_bql_prompt_text(str(t)) if is_bql_or_sw else str(t)
            for t in tasks
        ]
        tasks_lines = "\n".join(f"  - {t}" for t in clean_tasks)
        role_scope = (
            f"Quyền phần mềm: ĐƯỢC CẤP (cổng QLTN: {(p.portal_url or project.default_portal_url)}, kinh nghiệm sử dụng phần mềm ban đầu: 0/10, khi vướng mắc có thể nhắn hỏi Đội ngũ hỗ trợ / CSKH Thần Nông qua ask_atlas_support)."
            if p.software_access_enabled
            else f"Quyền phần mềm: KHÔNG CẤP (Cư dân — chỉ dùng UrbanCommAndIncidentEnv trao đổi với Lễ tân agent_id={receptionist_id}; tuyệt đối không gọi QLTN hay CSKH nội bộ)."
        )
        if tasks_lines:
            tasks_block = f"\nInitial Tasks / Incidents:\n{tasks_lines}"
        elif p.group_type == "RESIDENT" or not p.software_access_enabled:
            tasks_block = (
                "\nBehavior Mode: AUTONOMOUS (Không có kịch bản sự vụ định sẵn — hãy tự quyết định hoàn toàn tự nhiên "
                "dựa trên hồ sơ đời sống, tính cách, giờ mô phỏng và building_context từ observe_urban_inbox)."
            )
        else:
            tasks_block = ""

        domain_prompt = (
            _sanitize_legacy_bql_prompt_text(p.domain_knowledge_prompt)
            if is_bql_or_sw
            else p.domain_knowledge_prompt
        )
        profile_desc = (
            f"ID={p.agent_id} | {p.full_name} — {p.role_title} ({p.department}) | Group={p.group_type} | Zone={p.home_zone}.\n"
            f"Project: {project.name}.\n"
            f"{role_scope}\n"
            f"Domain Knowledge & Role Rules:\n{domain_prompt}"
            f"{tasks_block}"
        )
        agents_cfg.append(
            {
                "agent_id": int(p.agent_id),
                "agent_type": "PersonAgent",
                "kwargs": {
                    "id": int(p.agent_id),
                    "profile": {
                        "id": int(p.agent_id),
                        "name": p.full_name,
                        "role": p.role_title,
                        "role_code": p.role_code,
                        "department": p.department,
                        "group_type": p.group_type,
                        "software_access_enabled": bool(p.software_access_enabled),
                        "home_zone": p.home_zone,
                        "description": profile_desc,
                    },
                    "max_react_turns": int(project.max_react_turns or 10),
                    "enable_todo_list": True,
                    "enable_memory": True,
                    "require_pre_action_thought": True,
                    "disabled_skill_ids": (
                        [
                            "built-in@daily-guidance",
                            "custom@my-custom-skill",
                            "env:UrbanCommAndIncidentEnv@urban-resident-vn",
                        ]
                        if p.software_access_enabled
                        else [
                            "built-in@daily-guidance",
                            "custom@my-custom-skill",
                            "env:DemegoWebPortalEnv@bql-qltn-ops-vn",
                        ]
                    ),
                    "default_activated_skill_ids": (
                        ["env:DemegoWebPortalEnv@bql-qltn-ops-vn"]
                        if p.software_access_enabled
                        else ["env:UrbanCommAndIncidentEnv@urban-resident-vn"]
                    ),
                },
            }
        )

    init_cfg: dict[str, Any] = {
        "env_modules": env_modules,
        "agents": agents_cfg,
        "codegen_router": {"final_summary_enabled": False},
        "router_type": project.router_type if project.router_type in ("react", "codegen") else "react",
        "max_cost_usd": float(project.max_cost_usd_per_run) if project.max_cost_usd_per_run and project.max_cost_usd_per_run > 0 else None,
    }

    run_step: dict[str, Any] = {
        "type": "run",
        "num_steps": int(max(1, project.num_steps)),
        "tick": int(max(60, project.tick_seconds)),
    }
    compiled_steps: list[dict[str, Any]] = []

    enable_debrief = bool(getattr(project, "enable_sociological_debrief", True))
    enable_quiz = bool(getattr(project, "enable_competency_prepost_quiz", False))

    quiz_items: list[dict[str, Any]] = []
    answer_key: dict[str, dict[str, Any]] = {}
    if enable_quiz and software_ids:
        rubric = parse_or_default_rubric(getattr(project, "competency_rubric_json", None))
        quiz_items, answer_key = build_quiz_question_items(rubric)

    if enable_quiz and software_ids and quiz_items:
        compiled_steps.append(
            {
                "type": "questionnaire",
                "questionnaire_id": QUIZ_PRE_ID,
                "title": "Khảo sát Tri thức QLTN Ban đầu (Pre-Test — Tick 0)",
                "description": "Đánh giá nền tảng trước khi thực hành trên QLTN. Nếu chưa biết hãy chọn CHUA_BIET.",
                "target_agent_ids": list(software_ids),
                "allow_env_tools": False,
                "retry_on_parse_error": True,
                "questions": quiz_items,
            }
        )

    compiled_steps.append(run_step)

    # Đặt Phỏng vấn Trải nghiệm Xã hội học Cuối ca NGAY SAU run_step (trước Post-Quiz nếu bật cả hai)
    # để thu nhận cảm nhận & điểm đau tự nhiên không bị chi phối bởi hiệu ứng làm bài trắc nghiệm.
    if enable_debrief and software_ids:
        debrief_items = build_sociological_debrief_questions()
        compiled_steps.append(
            {
                "type": "questionnaire",
                "questionnaire_id": DEBRIEF_QUESTIONNAIRE_ID,
                "title": "Phỏng vấn Trải nghiệm Xã hội học Cuối ca (UMUX-Lite · SEQ · Workload · D&M CSKH · CIT)",
                "description": (
                    "Đánh giá trung thực trải nghiệm dùng phần mềm QLTN và kênh CSKH trong ca làm việc vừa qua. "
                    "Hãy dựa vào đúng trí nhớ MEMORY.md và notes/ của bạn; nêu thẳng mọi bất cập thật để cải thiện sản phẩm."
                ),
                "target_agent_ids": list(software_ids),
                "allow_env_tools": False,
                "retry_on_parse_error": True,
                "questions": debrief_items,
            }
        )

    if enable_quiz and software_ids and quiz_items:
        compiled_steps.append(
            {
                "type": "questionnaire",
                "questionnaire_id": QUIZ_POST_ID,
                "title": "Khảo sát Tri thức QLTN Sau thực hành (Post-Test — Open-Notes Retrieval)",
                "description": "Đánh giá lại sau ca làm việc (chế độ Open-Notes Retrieval: được phép tra cứu trí nhớ và notes/ đã ghi chép).",
                "target_agent_ids": list(software_ids),
                "allow_env_tools": False,
                "retry_on_parse_error": True,
                "questions": quiz_items,
            }
        )
        quiz_key_path = (init_dir / "competency_quiz_key.json").resolve()
        atomic_write_text(
            quiz_key_path,
            json.dumps(
                {
                    "schema_version": "1.0",
                    "pre_questionnaire_id": QUIZ_PRE_ID,
                    "post_questionnaire_id": QUIZ_POST_ID,
                    "assessment_mode": "OPEN_NOTES_RETRIEVAL",
                    "target_agent_ids": list(software_ids),
                    "questions": answer_key,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    steps_yaml: dict[str, Any] = {
        "start_t": project.start_time_iso,
        "steps": compiled_steps,
    }

    prompt_overrides_path = (run_dir / "prompt_overrides.json").resolve()
    atomic_write_text(
        prompt_overrides_path,
        json.dumps({"base_rules": URBAN_SIM_BASE_RULES}, ensure_ascii=False, indent=2),
    )

    config_path = (init_dir / "init_config.json").resolve()
    steps_path = (init_dir / "steps.yaml").resolve()
    atomic_write_text(config_path, json.dumps(init_cfg, ensure_ascii=False, indent=2))
    atomic_write_text(
        steps_path,
        yaml.safe_dump(steps_yaml, allow_unicode=True, sort_keys=False),
    )

    return CompiledRunBundle(
        config_path=config_path,
        steps_path=steps_path,
        vault_path=vault_path,
        prompt_overrides_path=prompt_overrides_path,
        active_agent_count=len(active),
        bql_software_count=len(software_ids),
        resident_count=len(resident_ids),
    )
