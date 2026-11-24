/* Daily Mobility Benchmark — Multi-language UI (vi default / en / zh) */
(function initDashboardI18n(global) {
  const LANG_STORAGE_KEY = "dm_dashboard_lang";
  const SUPPORTED_LANGS = ["vi", "en", "zh"];

  const STRINGS = {
    vi: {
      "meta.title": "Daily Mobility — Bảng điều khiển mô phỏng di chuyển hằng ngày",
      "nav.subtitle": "48 khung giờ · Bước 30 phút · Mô phỏng di chuyển đa tác tử",
      "nav.agent": "Cư dân",
      "nav.language": "Ngôn ngữ",
      "nav.connecting": "Đang kết nối…",
      "nav.agentOption": "Cư dân {id}",
      "nav.statusDone": "Cư dân {id} · Đã hoàn tất · {time}",
      "nav.statusRunning": "Cư dân {id} · Đang chạy · {time}",
      "nav.statusRefreshErr": "Cư dân {id} · Lỗi làm mới: {err}",
      "nav.statusConnectErr": "Lỗi kết nối: {err}",

      "kpi.progressLabel": "Tiến độ mô phỏng",
      "kpi.clockLabel": "Thời gian mô phỏng",
      "kpi.stepPrefix": "Bước mô phỏng #{step}",
      "kpi.stepEmpty": "Bước mô phỏng —",
      "kpi.hungerLabel": "Mức độ đói hiện tại",
      "kpi.mealsRecorded": "Đã ghi nhận {count} bữa ăn",
      "kpi.activityLabel": "Nhật ký hoạt động",
      "kpi.activityFail": "Thất bại {count} lần",

      "needs.title": "Đường cong nhu cầu sinh lý",
      "needs.desc": "Đói / Năng lượng / Căng thẳng · 48 khung giờ",
      "needs.hunger": "Đói",
      "needs.energy": "Năng lượng",
      "needs.stress": "Căng thẳng",
      "needs.milestones": "Cột mốc",
      "needs.milestonesEmpty": "Chưa có cột mốc (Thức dậy / Ăn uống sẽ hiện khi mô phỏng tiến triển)",
      "needs.tooltipTitle": "Khung giờ {slot} · {time}",

      "map.title": "Vị trí & Quỹ đạo",
      "map.tabSchematic": "Sơ đồ",
      "map.tabGeo": "Bản đồ Bắc Kinh",
      "map.ariaTabs": "Chế độ xem bản đồ",
      "map.descSchematic": "Sơ đồ · Nét đứt xanh = Đang di chuyển · Cùng vị trí xếp vòng",
      "map.descGeo": "Bản đồ Bắc Kinh · Nét đứt xanh = Đang di chuyển · Nền Gaode/OSM",
      "map.play": "▶ Phát",
      "map.pause": "⏸ Tạm dừng",
      "map.playTitle": "Tự động phát",
      "map.slotInitial": "Khung 1",
      "map.slotProgress": "Khung {cur} / {total}",
      "map.followLive": "Theo dõi trực tiếp",
      "map.ariaSchematic": "Sơ đồ vị trí",
      "map.ariaGeo": "Quỹ đạo trên bản đồ Bắc Kinh",
      "map.geoHint": "Chuyển nền bản đồ: Tiêu chuẩn (Gaode) / Vệ tinh (Gaode) / OpenStreetMap",
      "map.waiting": "Đang chờ dữ liệu…",
      "map.waitingDetail": "Đang chờ dữ liệu khảo sát và vị trí…",
      "map.noGeoCoords": "Chưa có tọa độ bản đồ",
      "map.noGeoCoordsDetail": "Chưa có dữ liệu tọa độ (cần snapshot khảo sát có tọa độ; khung không tọa độ chỉ hiện ở sơ đồ)",
      "map.noLib": "Chưa tải được thư viện bản đồ",
      "map.geoCount": "Bản đồ · Đang hiển thị {count} khung giờ có tọa độ",
      "map.geoStatus": "Bản đồ · Khung {slot} ({time}) · {intent} · {loc}{coord}",
      "map.commuteLabel": "Di chuyển",
      "map.moving": "Đang di chuyển",
      "map.movingTo": "Đang di chuyển → {dest}",
      "map.dest": "Điểm đến: {dest}",
      "map.destGeneric": "Điểm đến",
      "map.homeShort": "Nhà",
      "map.workShort": "Cơ quan",
      "map.clusterNote": " · Cùng vị trí {n} khung (đã xếp vòng)",
      "map.clusterCaption": "Cùng vị trí {n} khung · {range}{hint}",
      "map.clusterRangeShort": "Khung {slots}",
      "map.clusterRangeLong": "Khung {first}–{last} ({count})",
      "map.clusterMismatch": " · ⚠ {n} ô lệch ý định & vị trí ({intents})",
      "map.clusterTooltip": "Lưu trú cùng vị trí: {n} khung (vòng #{idx})",
      "map.geoClusterTooltip": "Cùng vị trí {n} khung · Mở rộng #{idx}",
      "map.mismatchNote": " (vị trí snapshot có thể khác với ý định khảo sát)",
      "map.currentStatus": "Hiện tại · Khung {slot} ({time}) · Ý định: {intent} · Vị trí: {loc}{cluster}{hunger}",
      "map.hungerInline": " · Đói {pct}%",
      "map.tipSlot": "Khung #{slot} · {time}\nÝ định: {intent}\nVị trí: {loc}{poi}{cluster}",
      "map.geoPopup": "<strong>Khung {slot}</strong> · {time}<br/>Ý định: {intent}<br/>Vị trí: {pos}{poi}{move}{cluster}",
      "map.geoLayerStd": "Tiêu chuẩn (Gaode)",
      "map.geoLayerSat": "Vệ tinh (Gaode)",
      "map.geoLayerOsm": "OpenStreetMap",

      "schedule.title": "Kế hoạch trong ngày",
      "schedule.descDefault": "Từ nhịp sinh học · Lập đầu ngày · Theo chuẩn mực xã hội",
      "schedule.waitTimetable": "Đang chờ lịch trình đầu ngày…",
      "schedule.notReady": "Chưa có kế hoạch: cần hoàn thành ít nhất một bước rhythm hook (agents/…/state/rhythm_state.json).",
      "schedule.empty": "Chưa có lịch trình trong ngày",
      "schedule.wake": "Thức dậy {time}",
      "schedule.workStart": "Vào làm {time}",
      "schedule.workEnd": "Tan làm {time}",
      "schedule.normStrength": "Mức tuân thủ {pct}%",
      "schedule.currentBlock": "Đoạn kế hoạch hiện tại: {activity}",
      "schedule.defaultLoaded": "Lịch trình đầu ngày · nhịp sinh học",
      "schedule.colTime": "Khung giờ",
      "schedule.colActivity": "Hoạt động",
      "schedule.colMeal": "Bữa ăn",
      "schedule.colNorm": "Quy chuẩn",

      "timeline.title": "Kế hoạch · Ý định · Vị trí",
      "timeline.desc": "Mỗi cột = Kế hoạch + Ý định + Vị trí · Viền cam nhạt khi lệch · Di chuột xem chi tiết",
      "timeline.plan": "Kế hoạch",
      "timeline.intent": "Ý định",
      "timeline.loc": "Vị trí",
      "timeline.groupIntent": "Ý định",
      "timeline.groupPos": "Vị trí",
      "timeline.noPlanGen": "Chưa tạo kế hoạch",
      "timeline.noPlanBlock": "Không có mục kế hoạch",
      "timeline.pending": "Chưa hoàn tất",
      "timeline.noSnapshot": "Không có snapshot",
      "timeline.driftPlan": "Kế hoạch → Ý định: {plan} ≠ {actual}",
      "timeline.driftPos": "Ý định ↔ Vị trí: {intent} có thể không khớp {pos}",
      "timeline.tipTitle": "Khung {slot} · {time}{extra}",
      "timeline.milestoneClick": "Khung {slot} · {label}{kind} · Bấm để định vị",
      "timeline.milestoneTagTitle": "Khung {slot} · Bấm để xem",

      "activity.title": "Nhật ký hoạt động cư dân",
      "activity.desc": "Môi trường · Quan sát · Codegen · Kỹ năng · Kế hoạch di chuyển · Quyết định LLM · Harness · Khảo sát",
      "activity.presetKey": "Chính",
      "activity.presetAll": "Tất cả",
      "activity.presetFail": "Chỉ lỗi",
      "activity.search": "Tìm kiếm",
      "activity.searchPlaceholder": "Tìm tóm tắt / chi tiết…",
      "activity.slotLabel": "Khung giờ",
      "activity.slotFromAria": "Từ khung giờ",
      "activity.slotToAria": "Đến khung giờ",
      "activity.allSlots": "Tất cả",
      "activity.useSelected": "Khung đang chọn",
      "activity.clear": "Xóa lọc",
      "activity.followSelection": "Theo khung đang chọn",
      "activity.emptyAll": "Chưa có nhật ký hoạt động (sẽ xuất hiện khi mô phỏng chạy gọi môi trường, quan sát, Codegen, kỹ năng…)",
      "activity.emptyFiltered": "Không có bản ghi khớp bộ lọc, thử chọn \"Tất cả\" hoặc bỏ lọc danh mục",
      "activity.showing": "Hiển thị <strong>{shown}</strong> / {total} mục",
      "activity.slotRange": "Khung <strong>{from}–{to}</strong>",
      "activity.failedBadge": "Thất bại <strong>{count}</strong>",
      "activity.statusFail": "✗ Thất bại",
      "activity.statusOk": "✓ Thành công",
      "activity.itemMeta": "Khung {slot} · {source}",

      "drawer.eyebrow": "Chi tiết & Truy vết khảo sát",
      "drawer.titleDefault": "Khung —",
      "drawer.title": "Khung {slot} · {time}{sim}",
      "drawer.close": "Đóng",
      "drawer.planHeader": "Kế hoạch ({range})",
      "drawer.planMismatch": "Khác với ý định dự kiến theo kế hoạch",
      "drawer.notCompleted": "Khung giờ này chưa hoàn tất khảo sát, vui lòng chờ mô phỏng chạy tiếp.",
      "drawer.mainIntent": "Ý định chính",
      "drawer.posType": "Loại vị trí",
      "drawer.posRaw": "Vị trí (nguyên văn snapshot)",
      "drawer.simTime": "Thời gian mô phỏng",
      "drawer.homeAoi": "AOI nhà (hồ sơ)",
      "drawer.workAoi": "AOI cơ quan (hồ sơ)",
      "drawer.engineStatus": "Trạng thái động cơ",
      "drawer.onTheWay": " · Đang trên đường",
      "drawer.commuteTarget": "Đích di chuyển",
      "drawer.hunger": "Đói",
      "drawer.energy": "Năng lượng",
      "drawer.stress": "Căng thẳng",
      "drawer.coords": "Tọa độ",
      "drawer.artifactFile": "Tệp kết quả",
      "drawer.agentReason": "Lý do của cư dân",
      "drawer.rawResponse": "Phản hồi gốc",
      "drawer.promptExcerpt": "Nội dung hỏi khảo sát (trích)",
      "drawer.rawJson": "JSON khảo sát đầy đủ (truy vết)",

      "legend.empty": "Chưa có dữ liệu",
      "runStatus.running": "Đang chạy",
      "runStatus.completed": "Đã hoàn tất",
      "runStatus.completed_with_errors": "Hoàn tất (có lỗi)",
      "runStatus.failed": "Thất bại",
      "runStatus.not_started": "Chưa chạy",
      "runStatus.unknown": "Không rõ",
    },

    en: {
      "meta.title": "Daily Mobility Benchmark — Live Dashboard",
      "nav.subtitle": "48 slots · 30-min step · Multi-agent daily mobility simulation",
      "nav.agent": "Agent",
      "nav.language": "Language",
      "nav.connecting": "Connecting…",
      "nav.agentOption": "Agent {id}",
      "nav.statusDone": "Agent {id} · Completed · {time}",
      "nav.statusRunning": "Agent {id} · Running · {time}",
      "nav.statusRefreshErr": "Agent {id} · Refresh failed: {err}",
      "nav.statusConnectErr": "Connection failed: {err}",

      "kpi.progressLabel": "Simulation Progress",
      "kpi.clockLabel": "Simulation Time",
      "kpi.stepPrefix": "Engine step #{step}",
      "kpi.stepEmpty": "Engine step —",
      "kpi.hungerLabel": "Current Hunger",
      "kpi.mealsRecorded": "{count} meals recorded",
      "kpi.activityLabel": "Activity Records",
      "kpi.activityFail": "{count} failed",

      "needs.title": "Physiological Needs",
      "needs.desc": "Hunger / Energy / Stress · 48 slots",
      "needs.hunger": "Hunger",
      "needs.energy": "Energy",
      "needs.stress": "Stress",
      "needs.milestones": "Milestones",
      "needs.milestonesEmpty": "No milestones yet (wake / meals appear as simulation advances)",
      "needs.tooltipTitle": "Slot {slot} · {time}",

      "map.title": "Location & Trajectory",
      "map.tabSchematic": "Schematic",
      "map.tabGeo": "Beijing Map",
      "map.ariaTabs": "Map views",
      "map.descSchematic": "Schematic · Dashed blue = Commuting · Ring layout for same place",
      "map.descGeo": "Beijing Map · Dashed blue = Commuting · Gaode/OSM base layers",
      "map.play": "▶ Play",
      "map.pause": "⏸ Pause",
      "map.playTitle": "Auto-play",
      "map.slotInitial": "Slot 1",
      "map.slotProgress": "Slot {cur} / {total}",
      "map.followLive": "Follow live",
      "map.ariaSchematic": "Location schematic",
      "map.ariaGeo": "Beijing map trajectory",
      "map.geoHint": "Layers: Gaode Standard / Gaode Satellite / OpenStreetMap",
      "map.waiting": "Waiting for data…",
      "map.waitingDetail": "Waiting for questionnaire & location data…",
      "map.noGeoCoords": "No map coordinates yet",
      "map.noGeoCoordsDetail": "No coordinates yet (requires questionnaire snapshots with lat/lng; slots without coordinates appear in Schematic only)",
      "map.noLib": "Map library not loaded",
      "map.geoCount": "Map · Showing {count} slots with coordinates",
      "map.geoStatus": "Map · Slot {slot} ({time}) · {intent} · {loc}{coord}",
      "map.commuteLabel": "Commute",
      "map.moving": "Commuting",
      "map.movingTo": "Commuting → {dest}",
      "map.dest": "Destination: {dest}",
      "map.destGeneric": "Destination",
      "map.homeShort": "Home",
      "map.workShort": "Work",
      "map.clusterNote": " · {n} slots at same place (ring layout)",
      "map.clusterCaption": "{n} slots at same place · {range}{hint}",
      "map.clusterRangeShort": "Slots {slots}",
      "map.clusterRangeLong": "Slots {first}–{last} ({count})",
      "map.clusterMismatch": " · ⚠ {n} intent-location mismatch ({intents})",
      "map.clusterTooltip": "Same place dwell: {n} slots (ring #{idx})",
      "map.geoClusterTooltip": "{n} slots at same place · Spread #{idx}",
      "map.mismatchNote": " (location snapshot may differ from questionnaire intention)",
      "map.currentStatus": "Current · Slot {slot} ({time}) · Intent: {intent} · Location: {loc}{cluster}{hunger}",
      "map.hungerInline": " · Hunger {pct}%",
      "map.tipSlot": "Slot #{slot} · {time}\nIntent: {intent}\nLocation: {loc}{poi}{cluster}",
      "map.geoPopup": "<strong>Slot {slot}</strong> · {time}<br/>Intent: {intent}<br/>Location: {pos}{poi}{move}{cluster}",
      "map.geoLayerStd": "Gaode Standard",
      "map.geoLayerSat": "Gaode Satellite",
      "map.geoLayerOsm": "OpenStreetMap",

      "schedule.title": "Daily Schedule",
      "schedule.descDefault": "From rhythm · Generated at start of day · Social norm",
      "schedule.waitTimetable": "Waiting for start-of-day timetable…",
      "schedule.notReady": "Schedule not generated yet: requires at least one rhythm hook step (agents/…/state/rhythm_state.json).",
      "schedule.empty": "No daily schedule yet",
      "schedule.wake": "Wake {time}",
      "schedule.workStart": "Work start {time}",
      "schedule.workEnd": "Work end {time}",
      "schedule.normStrength": "Norm {pct}%",
      "schedule.currentBlock": "Current scheduled block: {activity}",
      "schedule.defaultLoaded": "Start-of-day timetable · rhythm daily_schedule",
      "schedule.colTime": "Time",
      "schedule.colActivity": "Activity",
      "schedule.colMeal": "Meal",
      "schedule.colNorm": "Norm",

      "timeline.title": "Plan · Intention · Location",
      "timeline.desc": "Column = Plan + Intent + Location · Orange border = drift · Hover for details",
      "timeline.plan": "Plan",
      "timeline.intent": "Intent",
      "timeline.loc": "Location",
      "timeline.groupIntent": "Intent",
      "timeline.groupPos": "Location",
      "timeline.noPlanGen": "No schedule yet",
      "timeline.noPlanBlock": "No plan block",
      "timeline.pending": "Pending",
      "timeline.noSnapshot": "No snapshot",
      "timeline.driftPlan": "Plan → Intent: {plan} ≠ {actual}",
      "timeline.driftPos": "Intent ↔ Location: {intent} may mismatch {pos}",
      "timeline.tipTitle": "Slot {slot} · {time}{extra}",
      "timeline.milestoneClick": "Slot {slot} · {label}{kind} · Click to inspect",
      "timeline.milestoneTagTitle": "Slot {slot} · Click to inspect",

      "activity.title": "Agent Activity Log",
      "activity.desc": "Env · Observe · Codegen · Skills · Mobility Plan · LLM · Harness · Questionnaire",
      "activity.presetKey": "Key",
      "activity.presetAll": "All",
      "activity.presetFail": "Failed only",
      "activity.search": "Search",
      "activity.searchPlaceholder": "Search summary/detail…",
      "activity.slotLabel": "Slot",
      "activity.slotFromAria": "Start slot",
      "activity.slotToAria": "End slot",
      "activity.allSlots": "All",
      "activity.useSelected": "Selected slot",
      "activity.clear": "Clear",
      "activity.followSelection": "Follow selected slot",
      "activity.emptyAll": "No activity records yet (appears as simulation runs env, observe, codegen, skills, etc.)",
      "activity.emptyFiltered": "No matching records; switch to All or clear category filters",
      "activity.showing": "Showing <strong>{shown}</strong> / {total} records",
      "activity.slotRange": "Slots <strong>{from}–{to}</strong>",
      "activity.failedBadge": "Failed <strong>{count}</strong>",
      "activity.statusFail": "✗ Failed",
      "activity.statusOk": "✓ OK",
      "activity.itemMeta": "Slot {slot} · {source}",

      "drawer.eyebrow": "Questionnaire Provenance",
      "drawer.titleDefault": "Slot —",
      "drawer.title": "Slot {slot} · {time}{sim}",
      "drawer.close": "Close",
      "drawer.planHeader": "Plan ({range})",
      "drawer.planMismatch": "Differs from scheduled intention",
      "drawer.notCompleted": "Questionnaire for this slot is not completed yet.",
      "drawer.mainIntent": "Primary Intention",
      "drawer.posType": "Location Type",
      "drawer.posRaw": "Location (raw snapshot)",
      "drawer.simTime": "Simulation Time",
      "drawer.homeAoi": "Profile Home AOI",
      "drawer.workAoi": "Profile Work AOI",
      "drawer.engineStatus": "Engine Status",
      "drawer.onTheWay": " · In transit",
      "drawer.commuteTarget": "Commute Target",
      "drawer.hunger": "Hunger",
      "drawer.energy": "Energy",
      "drawer.stress": "Stress",
      "drawer.coords": "Coordinates",
      "drawer.artifactFile": "Artifact File",
      "drawer.agentReason": "Agent Reasoning",
      "drawer.rawResponse": "Raw Response",
      "drawer.promptExcerpt": "Questionnaire Prompt (excerpt)",
      "drawer.rawJson": "Full Questionnaire JSON",

      "legend.empty": "No data",
      "runStatus.running": "running",
      "runStatus.completed": "completed",
      "runStatus.completed_with_errors": "completed with errors",
      "runStatus.failed": "failed",
      "runStatus.not_started": "not started",
      "runStatus.unknown": "unknown",
    },

    zh: {
      "meta.title": "Daily Mobility Benchmark",
      "nav.subtitle": "48 时段 · 30 分钟步长 · 多智能体日常出行仿真",
      "nav.agent": "智能体",
      "nav.language": "语言",
      "nav.connecting": "连接中…",
      "nav.agentOption": "智能体 {id}",
      "nav.statusDone": "智能体 {id} · 已完成 · {time}",
      "nav.statusRunning": "智能体 {id} · 运行中 · {time}",
      "nav.statusRefreshErr": "智能体 {id} · 刷新失败：{err}",
      "nav.statusConnectErr": "连接失败：{err}",

      "kpi.progressLabel": "仿真进度",
      "kpi.clockLabel": "仿真时刻",
      "kpi.stepPrefix": "引擎步 #{step}",
      "kpi.stepEmpty": "引擎步 —",
      "kpi.hungerLabel": "当前饥饿度",
      "kpi.mealsRecorded": "已记餐 {count} 次",
      "kpi.activityLabel": "活动记录",
      "kpi.activityFail": "失败 {count} 次",

      "needs.title": "生理需求曲线",
      "needs.desc": "饥饿 / 精力 / 压力 · 48 时段",
      "needs.hunger": "饥饿",
      "needs.energy": "精力",
      "needs.stress": "压力",
      "needs.milestones": "里程碑",
      "needs.milestonesEmpty": "暂无里程碑（起床/就餐等会在问卷推进后出现）",
      "needs.tooltipTitle": "时段 {slot} · {time}",

      "map.title": "位置与轨迹",
      "map.tabSchematic": "示意图",
      "map.tabGeo": "北京地图",
      "map.ariaTabs": "地图视图",
      "map.descSchematic": "示意图 · 蓝色虚线=通勤/路程中 · 同地环形展开",
      "map.descGeo": "北京地图 · 蓝色虚线=通勤 · 高德/OSM 底图",
      "map.play": "▶ 播放",
      "map.pause": "⏸ 暂停",
      "map.playTitle": "自动播放",
      "map.slotInitial": "Slot 1",
      "map.slotProgress": "时段 {cur} / {total}",
      "map.followLive": "跟随实时",
      "map.ariaSchematic": "位置示意图",
      "map.ariaGeo": "北京地图轨迹",
      "map.geoHint": "底图可切换：高德标准 / 高德影像 / OpenStreetMap",
      "map.waiting": "等待数据…",
      "map.waitingDetail": "等待问卷与位置数据…",
      "map.noGeoCoords": "暂无地图坐标",
      "map.noGeoCoordsDetail": "暂无经纬度数据（需问卷快照含坐标；无坐标时段仅在示意图显示）",
      "map.noLib": "地图库未加载",
      "map.geoCount": "地图 · 已显示 {count} 个有时段坐标",
      "map.geoStatus": "地图 · 时段 {slot}（{time}）· {intent} · {loc}{coord}",
      "map.commuteLabel": "通勤",
      "map.moving": "通勤途中",
      "map.movingTo": "通勤途中 → {dest}",
      "map.dest": "目的地：{dest}",
      "map.destGeneric": "目的地",
      "map.homeShort": "家",
      "map.workShort": "单位",
      "map.clusterNote": " · 同地 {n} 时段（已环形展开）",
      "map.clusterCaption": "同地 {n} 时段 · {range}{hint}",
      "map.clusterRangeShort": "时段 {slots}",
      "map.clusterRangeLong": "时段 {first}–{last}（共 {count}）",
      "map.clusterMismatch": " · ⚠ {n} 格意图与位置不符（如意图={intents}）",
      "map.clusterTooltip": "同地驻留：{n} 个时段（环形展开 #{idx}）",
      "map.geoClusterTooltip": "同地 {n} 时段 · 展开 #{idx}",
      "map.mismatchNote": "（位置快照与问卷意图可能不一致）",
      "map.currentStatus": "当前 · 时段 {slot}（{time}）· 意图：{intent} · 位置：{loc}{cluster}{hunger}",
      "map.hungerInline": " · 饥饿 {pct}%",
      "map.tipSlot": "时段 #{slot} · {time}\n意图：{intent}\n位置：{loc}{poi}{cluster}",
      "map.geoPopup": "<strong>时段 {slot}</strong> · {time}<br/>意图：{intent}<br/>位置：{pos}{poi}{move}{cluster}",
      "map.geoLayerStd": "高德标准",
      "map.geoLayerSat": "高德影像",
      "map.geoLayerOsm": "OpenStreetMap",

      "schedule.title": "日计划表",
      "schedule.descDefault": "来自 rhythm · 日初生成 · 按 social norm 执行",
      "schedule.waitTimetable": "等待日初 timetable …",
      "schedule.notReady": "计划尚未生成：需至少完成一步 rhythm hook（agents/…/state/rhythm_state.json）。",
      "schedule.empty": "暂无 daily_schedule",
      "schedule.wake": "起床 {time}",
      "schedule.workStart": "上班 {time}",
      "schedule.workEnd": "下班 {time}",
      "schedule.normStrength": "规范强度 {pct}%",
      "schedule.currentBlock": "当前计划段：{activity}",
      "schedule.defaultLoaded": "日初 timetable · rhythm daily_schedule",
      "schedule.colTime": "时段",
      "schedule.colActivity": "活动",
      "schedule.colMeal": "餐次",
      "schedule.colNorm": "规范说明",

      "timeline.title": "计划 · 意图 · 位置",
      "timeline.desc": "每列=计划+意图+位置 · 不一致列淡橙框 · 悬停看详情",
      "timeline.plan": "计划",
      "timeline.intent": "意图",
      "timeline.loc": "位置",
      "timeline.groupIntent": "意图",
      "timeline.groupPos": "位置",
      "timeline.noPlanGen": "计划未生成",
      "timeline.noPlanBlock": "无计划块",
      "timeline.pending": "未完成",
      "timeline.noSnapshot": "无快照",
      "timeline.driftPlan": "计划→意图：{plan} ≠ {actual}",
      "timeline.driftPos": "意图↔位置：{intent} 与 {pos} 可能不符",
      "timeline.tipTitle": "时段 {slot} · {time}{extra}",
      "timeline.milestoneClick": "时段 {slot} · {label}{kind} · 点击定位",
      "timeline.milestoneTagTitle": "时段 {slot} · 点击查看",

      "activity.title": "Agent 活动记录",
      "activity.desc": "环境 · 观察 · Codegen · 技能 · 移动计划 · LLM 决策 · Harness · 问卷",
      "activity.presetKey": "关键",
      "activity.presetAll": "全部",
      "activity.presetFail": "仅失败",
      "activity.search": "搜索",
      "activity.searchPlaceholder": "搜索摘要/详情…",
      "activity.slotLabel": "时段",
      "activity.slotFromAria": "起始时段",
      "activity.slotToAria": "结束时段",
      "activity.allSlots": "全部",
      "activity.useSelected": "选中时段",
      "activity.clear": "清除",
      "activity.followSelection": "跟随时间轴选中",
      "activity.emptyAll": "暂无活动记录（实验推进后将出现环境调用、观察、Codegen、技能等）",
      "activity.emptyFiltered": "当前筛选无记录，可切换「全部」或取消类别筛选",
      "activity.showing": "显示 <strong>{shown}</strong> / {total} 条",
      "activity.slotRange": "时段 <strong>{from}–{to}</strong>",
      "activity.failedBadge": "失败 <strong>{count}</strong>",
      "activity.statusFail": "✗ 失败",
      "activity.statusOk": "✓ 成功",
      "activity.itemMeta": "时段 {slot} · {source}",

      "drawer.eyebrow": "问卷溯源",
      "drawer.titleDefault": "Slot —",
      "drawer.title": "时段 {slot} · {time}{sim}",
      "drawer.close": "关闭",
      "drawer.planHeader": "计划（{range}）",
      "drawer.planMismatch": "与计划映射的意图不同",
      "drawer.notCompleted": "该时段问卷尚未完成，请等待实验推进。",
      "drawer.mainIntent": "主要意图",
      "drawer.posType": "位置类型",
      "drawer.posRaw": "位置（快照原文）",
      "drawer.simTime": "仿真时刻",
      "drawer.homeAoi": "档案 home AOI",
      "drawer.workAoi": "档案 work AOI",
      "drawer.engineStatus": "引擎状态",
      "drawer.onTheWay": " · 路程中",
      "drawer.commuteTarget": "通勤目标",
      "drawer.hunger": "饥饿",
      "drawer.energy": "精力",
      "drawer.stress": "压力",
      "drawer.coords": "坐标",
      "drawer.artifactFile": "产物文件",
      "drawer.agentReason": "智能体理由",
      "drawer.rawResponse": "原始回答",
      "drawer.promptExcerpt": "问卷提示（节选）",
      "drawer.rawJson": "完整问卷 JSON（溯源）",

      "legend.empty": "暂无数据",
      "runStatus.running": "running",
      "runStatus.completed": "completed",
      "runStatus.completed_with_errors": "completed_with_errors",
      "runStatus.failed": "failed",
      "runStatus.not_started": "not_started",
      "runStatus.unknown": "unknown",
    },
  };

  const INTENTION_LABELS = {
    vi: {
      sleep: "Ngủ",
      "home activity": "Ở nhà",
      work: "Làm việc",
      shopping: "Mua sắm",
      "eating out": "Ăn ngoài",
      "leisure and entertainment": "Giải trí",
      other: "Khác",
      commute: "Di chuyển",
    },
    en: {
      sleep: "Sleep",
      "home activity": "Home activity",
      work: "Work",
      shopping: "Shopping",
      "eating out": "Eating out",
      "leisure and entertainment": "Leisure",
      other: "Other",
      commute: "Commute",
    },
    zh: {
      sleep: "睡眠",
      "home activity": "居家",
      work: "工作",
      shopping: "购物",
      "eating out": "外出就餐",
      "leisure and entertainment": "休闲",
      other: "其他",
      commute: "通勤",
    },
  };

  const SCHEDULE_ACTIVITY_LABELS = {
    vi: {
      sleep: "Ngủ",
      home_activity: "Ở nhà",
      work: "Làm việc / Di chuyển",
      meal: "Ăn uống",
      return_home: "Về nhà",
    },
    en: {
      sleep: "Sleep",
      home_activity: "Home",
      work: "Work / Commute",
      meal: "Meal",
      return_home: "Return home",
    },
    zh: {
      sleep: "睡眠",
      home_activity: "居家",
      work: "工作/通勤",
      meal: "用餐",
      return_home: "回家",
    },
  };

  const MEAL_WINDOW_LABELS = {
    vi: {
      breakfast: "Bữa sáng",
      lunch: "Bữa trưa",
      dinner: "Bữa tối",
      snack: "Ăn nhẹ",
    },
    en: {
      breakfast: "Breakfast",
      lunch: "Lunch",
      dinner: "Dinner",
      snack: "Snack",
    },
    zh: {
      breakfast: "早餐",
      lunch: "午餐",
      dinner: "晚餐",
      snack: "加餐",
    },
  };

  const POSITION_KIND_LABELS = {
    vi: {
      home: "Tại nhà",
      work: "Tại nơi làm việc",
      moving: "Đang di chuyển",
      meal_poi: "Điểm ăn uống",
      aoi: "Địa điểm ngoài (AOI)",
      unset: "Chưa rõ",
    },
    en: {
      home: "At home",
      work: "At work",
      moving: "Commuting",
      meal_poi: "Meal POI",
      aoi: "Other AOI",
      unset: "Unknown",
    },
    zh: {
      home: "在家",
      work: "在单位",
      moving: "通勤途中",
      meal_poi: "就餐地点",
      aoi: "在外部地点",
      unset: "位置未知",
    },
  };

  const POSITION_KIND_LEGEND = {
    vi: {
      home: "AOI trùng với nhà trong hồ sơ",
      work: "AOI trùng với nơi làm việc trong hồ sơ",
      moving: "status = moving, đang trên đường di chuyển",
      meal_poi: "Nhà hàng / Quán ăn (POI ẩm thực)",
      aoi: "Có AOI, khác nhà và nơi làm việc",
      unset: "Chưa có AOI (ví dụ mới khởi hành)",
    },
    en: {
      home: "AOI matches profile home",
      work: "AOI matches profile work",
      moving: "status = moving, in transit without fixed AOI",
      meal_poi: "Restaurant / Dining POI",
      aoi: "Has AOI, neither home nor work",
      unset: "No AOI (e.g., trip starting)",
    },
    zh: {
      home: "AOI 匹配档案 home",
      work: "AOI 匹配档案 work",
      moving: "status = moving，途中无固定 AOI",
      meal_poi: "餐厅 / 餐饮 POI",
      aoi: "有 AOI，未匹配 home/work",
      unset: "无 AOI（如起程未落点）",
    },
  };

  const POSITION_KIND_EMOJI = {
    home: "🏠",
    work: "🏢",
    moving: "🚶",
    meal_poi: "🍽",
    aoi: "📍",
    unset: "❓",
  };

  const ACTIVITY_CATEGORY_LABELS = {
    vi: {
      env: "Gọi môi trường",
      observe: "Quan sát",
      codegen: "Codegen",
      skill: "Thực thi kỹ năng",
      tool: "Không gian / Công cụ",
      plan: "Kế hoạch di chuyển",
      harness: "Harness",
      needs: "Nhu cầu",
      step: "Bước mô phỏng",
      questionnaire: "Khảo sát",
      llm: "Quyết định LLM",
      behavior: "Theo dõi hành vi",
      system: "Hệ thống",
    },
    en: {
      env: "Env Call",
      observe: "Observe",
      codegen: "Codegen",
      skill: "Skill Exec",
      tool: "Workspace/Tool",
      plan: "Mobility Plan",
      harness: "Harness",
      needs: "Needs",
      step: "Step",
      questionnaire: "Questionnaire",
      llm: "LLM Decision",
      behavior: "Behavior Trace",
      system: "System",
    },
    zh: {
      env: "环境调用",
      observe: "观察",
      codegen: "Codegen",
      skill: "技能执行",
      tool: "工作区/工具",
      plan: "移动计划",
      harness: "Harness",
      needs: "需求",
      step: "仿真步",
      questionnaire: "问卷",
      llm: "LLM 决策",
      behavior: "行为追踪",
      system: "系统",
    },
  };

  const ACTIVITY_RECORD_LABELS = {
    vi: {
      "读取文件": "Đọc tệp",
      "写入文件": "Ghi tệp",
      "激活技能": "Kích hoạt kỹ năng",
      "执行技能": "Thực thi kỹ năng",
      "结束步进": "Kết thúc bước",
      "完成": "Hoàn tất",
      "移动计划": "Kế hoạch di chuyển",
      "记餐状态": "Trạng thái bữa ăn",
      "仿真步": "Bước mô phỏng",
      "需求更新": "Cập nhật nhu cầu",
      "Harness 移动": "Harness di chuyển",
      "搜索餐厅": "Tìm nhà hàng",
      "强制通勤": "Ép di chuyển",
      "强制就餐": "Ép dùng bữa",
      "上下文压缩": "Nén ngữ cảnh",
      "写入记忆": "Ghi bộ nhớ",
      "Harness 告警": "Cảnh báo Harness",
      "错误": "Lỗi",
      "技能激活": "Kích hoạt kỹ năng",
      "运行错误": "Lỗi chạy",
      "步进异常结束": "Bước kết thúc bất thường",
      "LLM 工具选择": "LLM chọn công cụ",
      "问卷意图": "Ý định khảo sát",
      "无工具": "Không gọi công cụ",
    },
    en: {
      "读取文件": "Read file",
      "写入文件": "Write file",
      "激活技能": "Activate skill",
      "执行技能": "Execute skill",
      "结束步进": "Done step",
      "完成": "Finish",
      "移动计划": "Mobility plan",
      "记餐状态": "Meal state",
      "仿真步": "Sim step",
      "需求更新": "Needs update",
      "Harness 移动": "Harness move",
      "搜索餐厅": "Meal search",
      "强制通勤": "Enforce commute",
      "强制就餐": "Enforce meal",
      "上下文压缩": "Compact context",
      "写入记忆": "Memory handoff",
      "Harness 告警": "Harness warning",
      "错误": "Error",
      "技能激活": "Skill activated",
      "运行错误": "Runtime error",
      "步进异常结束": "Abnormal step end",
      "LLM 工具选择": "LLM tool choice",
      "问卷意图": "Survey intention",
      "无工具": "No tools",
    },
  };

  const MILESTONE_LABELS = {
    vi: {
      "起床": "Thức dậy",
      "入睡": "Đi ngủ",
      "出门": "Ra khỏi nhà",
      "上班": "Đi làm",
      "回家": "Về nhà",
      "早餐": "Bữa sáng",
      "早饭": "Bữa sáng",
      "午餐": "Bữa trưa",
      "午饭": "Bữa trưa",
      "晚餐": "Bữa tối",
      "晚饭": "Bữa tối",
      "家": "Nhà",
      "单位": "Cơ quan",
    },
    en: {
      "起床": "Wake up",
      "入睡": "Bedtime",
      "出门": "Leave home",
      "上班": "At work",
      "回家": "Return home",
      "早餐": "Breakfast",
      "早饭": "Breakfast",
      "午餐": "Lunch",
      "午饭": "Lunch",
      "晚餐": "Dinner",
      "晚饭": "Dinner",
      "家": "Home",
      "单位": "Work",
    },
  };

  const LOCATION_LABELS = {
    vi: {
      "在家": "Tại nhà",
      "在单位": "Tại nơi làm việc",
      "通勤途中": "Đang di chuyển",
      "就餐地点": "Điểm ăn uống",
      "在外部地点": "Địa điểm ngoài (AOI)",
      "位置未知": "Chưa rõ",
      "家": "Nhà",
      "单位": "Cơ quan",
    },
    en: {
      "在家": "At home",
      "在单位": "At work",
      "通勤途中": "Commuting",
      "就餐地点": "Meal POI",
      "在外部地点": "Other AOI",
      "位置未知": "Unknown",
      "家": "Home",
      "单位": "Work",
    },
  };

  function normalizeLang(raw) {
    if (!raw) return "vi";
    const base = String(raw).toLowerCase().split(/[-_]/)[0];
    return SUPPORTED_LANGS.includes(base) ? base : "vi";
  }

  let currentLang = (function readInitialLang() {
    try {
      const saved = global.localStorage?.getItem(LANG_STORAGE_KEY);
      if (saved) return normalizeLang(saved);
    } catch {
      /* ignore */
    }
    return "vi";
  })();

  function t(key, vars) {
    const table = STRINGS[currentLang] || STRINGS.vi;
    let text = table[key] ?? STRINGS.en[key] ?? key;
    if (vars && typeof vars === "object") {
      for (const [k, v] of Object.entries(vars)) {
        text = text.replaceAll(`{${k}}`, v == null ? "" : String(v));
      }
    }
    return text;
  }

  function timeLocale() {
    if (currentLang === "vi") return "vi-VN";
    if (currentLang === "en") return "en-US";
    return "zh-CN";
  }

  function applyStatic(root = global.document) {
    if (!root) return;
    if (global.document?.documentElement) {
      global.document.documentElement.lang = currentLang === "zh" ? "zh-CN" : currentLang;
      global.document.title = t("meta.title");
    }
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
    });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.dataset.i18nTitle));
    });
    root.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
    });
    const langSel = global.document?.getElementById("lang-select");
    if (langSel && langSel.value !== currentLang) {
      langSel.value = currentLang;
    }
  }

  function setLang(lang) {
    currentLang = normalizeLang(lang);
    try {
      global.localStorage?.setItem(LANG_STORAGE_KEY, currentLang);
    } catch {
      /* ignore */
    }
    applyStatic();
    return currentLang;
  }

  function getLang() {
    return currentLang;
  }

  function intentionLabel(key) {
    if (!key) return "—";
    return (INTENTION_LABELS[currentLang] || INTENTION_LABELS.vi)[key] || key;
  }

  function scheduleActivityLabel(key) {
    if (!key) return "—";
    return (SCHEDULE_ACTIVITY_LABELS[currentLang] || SCHEDULE_ACTIVITY_LABELS.vi)[key] || key;
  }

  function mealWindowLabel(key) {
    if (!key) return "—";
    const norm = String(key).toLowerCase();
    return (MEAL_WINDOW_LABELS[currentLang] || MEAL_WINDOW_LABELS.vi)[norm] || key;
  }

  function positionKindLabel(key) {
    if (!key) return "—";
    return (POSITION_KIND_LABELS[currentLang] || POSITION_KIND_LABELS.vi)[key] || key;
  }

  function positionKindLegend(key) {
    return (POSITION_KIND_LEGEND[currentLang] || POSITION_KIND_LEGEND.vi)[key] || key;
  }

  function positionKindIcon(key) {
    return {
      emoji: POSITION_KIND_EMOJI[key] || "📍",
      label: positionKindLabel(key),
    };
  }

  function runStatusLabel(status) {
    if (!status) return "";
    const key = `runStatus.${String(status).toLowerCase()}`;
    const translated = t(key);
    return translated === key ? String(status) : translated;
  }

  function targetLabel(targetId, homeAoi, workAoi) {
    if (targetId == null) return null;
    if (homeAoi != null && targetId === homeAoi) return t("map.homeShort");
    if (workAoi != null && targetId === workAoi) return t("map.workShort");
    return `AOI ${targetId}`;
  }

  function activityCategoryLabel(cat, fallback) {
    const dict = ACTIVITY_CATEGORY_LABELS[currentLang] || ACTIVITY_CATEGORY_LABELS.vi;
    if (dict[cat]) return dict[cat];
    if (currentLang !== "zh" && fallback && /[\u4e00-\u9fff]/.test(fallback)) {
      return cat;
    }
    return fallback || cat;
  }

  function activityRecordLabel(raw) {
    if (!raw) return "—";
    if (currentLang === "zh") return raw;
    const dict = ACTIVITY_RECORD_LABELS[currentLang] || ACTIVITY_RECORD_LABELS.vi;
    return dict[raw] || raw;
  }

  function activitySummaryText(raw) {
    if (!raw) return "—";
    if (currentLang === "zh") return raw;
    const dict = ACTIVITY_RECORD_LABELS[currentLang] || ACTIVITY_RECORD_LABELS.vi;
    return String(raw).replaceAll("无工具", dict["无工具"] || "No tools");
  }

  function translatePlaceToken(tok) {
    const map = MILESTONE_LABELS[currentLang] || {};
    if (map[tok]) return map[tok];
    if (/^外(.+)$/.test(tok)) {
      const tail = tok.slice(1);
      return currentLang === "vi" ? `Ngoài(${tail})` : `Out(${tail})`;
    }
    return tok;
  }

  function milestoneLabel(raw) {
    if (!raw) return "";
    if (currentLang === "zh") return raw;
    const dict = MILESTONE_LABELS[currentLang] || MILESTONE_LABELS.vi;
    if (dict[raw]) return dict[raw];
    if (String(raw).includes("→")) {
      return String(raw)
        .split("→")
        .map((part) => translatePlaceToken(part.trim()))
        .join(" → ");
    }
    return raw;
  }

  function locationLabel(raw) {
    if (!raw) return raw;
    if (currentLang === "zh") return raw;
    const dict = LOCATION_LABELS[currentLang] || LOCATION_LABELS.vi;
    if (dict[raw]) return dict[raw];
    if (/^在外部地点(\s*·\s*.+)?$/.test(raw)) {
      return String(raw).replace("在外部地点", dict["在外部地点"]);
    }
    return raw;
  }

  function intentionLabelsMap() {
    return INTENTION_LABELS[currentLang] || INTENTION_LABELS.vi;
  }

  function positionLabelsMap() {
    return POSITION_KIND_LABELS[currentLang] || POSITION_KIND_LABELS.vi;
  }

  global.DashboardI18n = {
    getLang,
    setLang,
    t,
    timeLocale,
    applyStatic,
    intentionLabel,
    scheduleActivityLabel,
    mealWindowLabel,
    positionKindLabel,
    positionKindLegend,
    positionKindIcon,
    runStatusLabel,
    targetLabel,
    activityCategoryLabel,
    activityRecordLabel,
    activitySummaryText,
    milestoneLabel,
    locationLabel,
    intentionLabelsMap,
    positionLabelsMap,
  };
})(window);
