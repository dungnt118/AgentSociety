/* Daily Mobility Benchmark — Live Dashboard */

const POLL_MS = 2500;
const IDLE_POLL_MS = 30000;
const _t = (key, vars) => (window.DashboardI18n ? window.DashboardI18n.t(key, vars) : key);
const getIntentionLabel = (k) => (window.DashboardI18n ? window.DashboardI18n.intentionLabel(k) : k || "—");
const getScheduleActivityLabel = (k) => (window.DashboardI18n ? window.DashboardI18n.scheduleActivityLabel(k) : k || "—");
const getPositionKindLabel = (k) => (window.DashboardI18n ? window.DashboardI18n.positionKindLabel(k) : k || "—");
const getPositionKindLegend = (k) => (window.DashboardI18n ? window.DashboardI18n.positionKindLegend(k) : k || "");
const getPositionKindIcon = (k) => (window.DashboardI18n ? window.DashboardI18n.positionKindIcon(k) : { emoji: "📍", label: k || "" });

const INTENTION_ORDER = [
  "sleep",
  "home activity",
  "work",
  "commute",
  "eating out",
  "shopping",
  "leisure and entertainment",
  "other",
];

const POSITION_KIND_ORDER = ["home", "work", "moving", "meal_poi", "aoi", "unset"];

const COMMUTE_COLOR = "#2980b9";

const POSITION_KIND_ANCHORS = {
  home: { x: 70, y: 190 },
  work: { x: 330, y: 190 },
  moving: { x: 200, y: 110 },
  meal_poi: { x: 200, y: 155 },
  aoi: { x: 200, y: 155 },
  unset: { x: 200, y: 190 },
};

const AGENT_STORAGE_KEY = "dm_live_dashboard_agent_id";
const ENV_FILTER_STORAGE_KEY = "dm_env_filter_preset";
const MAP_VIEW_STORAGE_KEY = "dm_map_view_mode";

const CHART_TEXT = "#64748b";
const CHART_GRID = "rgba(100, 116, 139, 0.12)";

const ENV_KEY_KINDS = new Set([
  "move_to",
  "get_person",
  "find_nearby_pois",
  "enforce_meal",
  "enforce_commute",
  "meal_search",
  "harness_move",
  "codegen",
  "execute_skill",
  "primary_intention",
]);

const ACTIVITY_KEY_CATEGORIES = new Set([
  "env",
  "observe",
  "codegen",
  "skill",
  "plan",
  "harness",
  "questionnaire",
  "llm",
  "behavior",
  "step",
]);

const ENV_FN_COLORS = {
  move_to: "#2563eb",
  get_person: "#64748b",
  stop_trip: "#d97706",
  finish_trip: "#059669",
  find_nearby_pois: "#0d9488",
  enforce_meal: "#dc2626",
  meal_search: "#e74c3c",
  enforce_commute: "#7c3aed",
};

let state = null;
let selectedSlot = null;
let selectedAgentId = readStoredAgentId();
let needsChart = null;
let pollTimer = null;
let paintingMilestones = false;
const NEEDS_CHART_MILESTONE_PAD_TOP = 52;
let milestoneBySlot = new Map();
let schematicEndSlot = null;
let schematicFollowLive = true;
let schematicPlaying = false;
let schematicPlayTimer = null;
let envFilterPreset = readEnvFilterPreset();
let activityFilterCategories = new Set();
let activityFilterKinds = new Set();
let activitySearchQuery = "";
let activitySlotFrom = null;
let activitySlotTo = null;
let activitySlotFollowSelection = false;
let envFilterOnlyFail = false;
let lastSlotsDone = -1;
let mapViewMode = readMapViewMode();
const kpiAnim = { hunger: null, env: null };
let lastStateFingerprint = null;
let lastActivityRenderKey = null;
const seenActivityKeysByAgent = new Map();
let drawerMode = null;
let drawerReasonLang = "vi";
let drawerPromptLang = "vi";
const reasonTranslations = new Map();

const MILESTONE_LANE_STEP_PX = 15;
const MILESTONE_LABEL_PAD_PX = 26;

function milestoneLeftPercent(slot) {
  return ((slot + 0.5) / 48) * 100;
}

function estimateMilestoneWidthPx(m) {
  const text = String(m.label || "");
  return Math.min(118, Math.max(40, text.length * 6.2 + MILESTONE_LABEL_PAD_PX));
}

function layoutMilestones(milestones, containerWidthPx) {
  const width = Math.max(containerWidthPx, 320);
  const laneRight = [];
  const sorted = [...milestones].sort(
    (a, b) => a.slot - b.slot || String(a.kind || "").localeCompare(String(b.kind || "")),
  );
  return sorted.map((m) => {
    const centerPx = (width * (m.slot + 0.5)) / 48;
    const halfW = estimateMilestoneWidthPx(m) / 2;
    const left = centerPx - halfW;
    const right = centerPx + halfW;
    let lane = 0;
    while (lane < laneRight.length && laneRight[lane] > left - 8) {
      lane += 1;
    }
    if (lane === laneRight.length) {
      laneRight.push(right);
    } else {
      laneRight[lane] = Math.max(laneRight[lane], right);
    }
    return {
      ...m,
      lane,
      leftPct: milestoneLeftPercent(m.slot),
    };
  });
}

const milestoneLinesPlugin = {
  id: "milestoneLines",
  afterDraw(chart) {
    const items = chart.options.plugins?.milestoneLines?.items || [];
    if (!items.length) return;
    const { ctx, chartArea, scales } = chart;
    const xScale = scales.x;
    items.forEach((m) => {
      const x = xScale.getPixelForValue(m.slot);
      if (x < chartArea.left - 4 || x > chartArea.right + 4) return;
      const lane = m.lane || 0;
      ctx.save();
      ctx.strokeStyle = m.color || "#d97706";
      ctx.globalAlpha = 0.75;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = m.color || "#d97706";
      ctx.font = '600 10px "Noto Sans", "Noto Sans SC", system-ui, sans-serif';
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      const rawLabel = window.DashboardI18n ? window.DashboardI18n.milestoneLabel(m.label || "") : (m.label || "");
      const label = `${m.icon || ""}${rawLabel}`.trim();
      if (label) {
        ctx.fillText(label, x, chartArea.top - 4 - lane * MILESTONE_LANE_STEP_PX);
      }
      ctx.restore();
    });
  },
};

function $(id) {
  return document.getElementById(id);
}

function readEnvFilterPreset() {
  const v = localStorage.getItem(ENV_FILTER_STORAGE_KEY);
  return v === "all" || v === "fail" ? v : "key";
}

function readMapViewMode() {
  try {
    const v = localStorage.getItem(MAP_VIEW_STORAGE_KEY);
    return v === "geo" ? "geo" : "schematic";
  } catch {
    return "schematic";
  }
}

function storeMapViewMode(mode) {
  try {
    localStorage.setItem(MAP_VIEW_STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

function setMapView(mode) {
  mapViewMode = mode === "geo" ? "geo" : "schematic";
  storeMapViewMode(mapViewMode);

  const schematicPane = $("schematic-pane");
  const geoPane = $("geo-map-pane");
  schematicPane?.classList.toggle("map-pane-active", mapViewMode === "schematic");
  geoPane?.classList.toggle("map-pane-active", mapViewMode === "geo");
  if (schematicPane) schematicPane.setAttribute("aria-hidden", mapViewMode !== "schematic");
  if (geoPane) geoPane.setAttribute("aria-hidden", mapViewMode !== "geo");

  document.querySelectorAll(".view-tab[data-map-view]").forEach((btn) => {
    const active = btn.dataset.mapView === mapViewMode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });

  const desc = $("map-view-desc");
  if (desc) {
    desc.textContent =
      mapViewMode === "geo"
        ? _t("map.descGeo")
        : _t("map.descSchematic");
  }

  if (mapViewMode === "geo") {
    window.GeoMapView?.invalidateSize();
    if (state) updateGeoMapView(state);
  }
}

function updateGeoMapView(data) {
  if (mapViewMode !== "geo" || !window.GeoMapView) return;
  const endSlot = resolveSchematicEndSlot(data);
  const done = data.meta?.slots_done ?? 0;
  const progressEnd = schematicProgressEndSlot(data);
  const latestSlot = progressEnd >= 0 ? progressEnd : null;

  const posColors = data.position_kind_colors || data.location_colors || {};
  const intentColors = data.intention_colors || {};
  const result = window.GeoMapView.render({
    data,
    endSlot,
    selectedSlot,
    latestSlot,
    positionColor: (kind) => positionColor(posColors, kind),
    intentionColor: (intent) => intentionColor(intentColors, intent),
    labels: {
      intention: window.DashboardI18n ? window.DashboardI18n.intentionLabelsMap() : {},
      position: window.DashboardI18n ? window.DashboardI18n.positionLabelsMap() : {},
    },
  });

  const status = $("schematic-status");
  if (!status || mapViewMode !== "geo") return;
  status.classList.remove("mismatch");
  if (result.pointCount === 0) {
    status.textContent = result.message || _t("map.noGeoCoords");
    return;
  }
  const cur = (data.slots || [])[endSlot];
  if (!cur) {
    status.textContent = _t("map.geoCount", { count: result.pointCount });
    return;
  }
  const intentTxt = getIntentionLabel(cur.intention);
  const locTxt = formatMobilityLabel(cur, data.live);
  const coordTxt =
    cur.lat != null ? ` · ${Number(cur.lat).toFixed(5)}, ${Number(cur.lng).toFixed(5)}` : "";
  status.textContent = _t("map.geoStatus", {
    slot: endSlot + 1,
    time: cur.time_label,
    intent: intentTxt,
    loc: locTxt,
    coord: coordTxt,
  });
}

function storeEnvFilterPreset(preset) {
  envFilterPreset = preset;
  localStorage.setItem(ENV_FILTER_STORAGE_KEY, preset);
}

function intentionColor(colors, key) {
  return (colors && colors[key]) || "#94a3b8";
}

function positionColor(colors, key) {
  const c = colors || {};
  return c[key] || c[null] || "#94a3b8";
}

function isMovingPoint(p) {
  if (!p) return false;
  const status = String(p.status || "").toLowerCase();
  return (
    status === "moving" ||
    p.position_kind === "moving" ||
    p.intention === "commute"
  );
}

function isCommuteSegment(prev, cur) {
  return isMovingPoint(prev) || isMovingPoint(cur);
}

function targetAoiLabel(targetId, homeAoi, workAoi) {
  if (window.DashboardI18n) return window.DashboardI18n.targetLabel(targetId, homeAoi, workAoi);
  if (targetId == null) return null;
  if (homeAoi != null && targetId === homeAoi) return _t("map.homeShort");
  if (workAoi != null && targetId === workAoi) return _t("map.workShort");
  return `AOI ${targetId}`;
}

function formatMobilityLabel(slot, live) {
  const snap = live?.snapshot;
  const status = String(slot?.status ?? snap?.status ?? "").toLowerCase();
  const kind = slot?.position_kind ?? snap?.position_kind;
  const targetId = slot?.target_aoi_id ?? snap?.target_aoi_id;
  const homeAoi = slot?.home_aoi ?? snap?.home_aoi;
  const workAoi = slot?.work_aoi ?? snap?.work_aoi;

  if (status === "moving" || kind === "moving") {
    const dest = targetAoiLabel(targetId, homeAoi, workAoi);
    return dest ? _t("map.movingTo", { dest }) : _t("map.moving");
  }

  if (live?.location_label && live.location_label !== "—") {
    return window.DashboardI18n ? window.DashboardI18n.locationLabel(live.location_label) : live.location_label;
  }
  return humanLocationLabel(slot, live);
}

function humanLocationLabel(slot, live) {
  if (!slot) return "—";
  const base = getPositionKindLabel(slot.position_kind);
  if (slot.poi_name) return `${base} · ${slot.poi_name}`;
  if (slot.position_label && !/^moving · aoi=/.test(slot.position_label)) {
    if (!/aoi=\d{6,}/.test(slot.position_label) || slot.position_kind === "meal_poi") {
      return window.DashboardI18n ? window.DashboardI18n.locationLabel(slot.position_label) : slot.position_label;
    }
  }
  return base;
}

function haversineMeters(lat1, lng1, lat2, lng2) {
  const R = 6378137;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
    Math.cos((lat2 * Math.PI) / 180) *
    Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

function formatDistanceM(m) {
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function isIntentPositionMismatch(intention, positionKind) {
  if (!intention || !positionKind) return false;
  if (intention === "commute" || positionKind === "moving") return false;
  if (intention === "work" && positionKind !== "work") return true;
  if (intention === "sleep" && positionKind !== "home") return true;
  if (intention === "home activity" && positionKind !== "home") return true;
  if (intention === "eating out" && positionKind !== "meal_poi" && positionKind !== "aoi") {
    return true;
  }
  if (positionKind === "work" && (intention === "home activity" || intention === "sleep")) {
    return true;
  }
  if (positionKind === "work" && intention === "eating out") return true;
  return false;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatUpdated(iso) {
  if (!iso) return "—";
  try {
    const locale = window.DashboardI18n ? window.DashboardI18n.timeLocale() : "vi-VN";
    return new Date(iso).toLocaleTimeString(locale, { hour12: false });
  } catch {
    return iso;
  }
}

function readStoredAgentId() {
  try {
    const raw = localStorage.getItem(AGENT_STORAGE_KEY);
    if (raw != null && raw !== "") {
      const n = Number(raw);
      if (Number.isInteger(n) && n > 0) return n;
    }
  } catch {
    /* ignore */
  }
  const params = new URLSearchParams(window.location.search);
  const fromUrl = Number(params.get("agent_id"));
  if (Number.isInteger(fromUrl) && fromUrl > 0) return fromUrl;
  return 1;
}

function storeAgentId(agentId) {
  try {
    localStorage.setItem(AGENT_STORAGE_KEY, String(agentId));
  } catch {
    /* ignore */
  }
}

function animateNumber(el, target, formatter = (v) => String(v)) {
  if (!el) return;
  const from = Number(el.dataset.value);
  const to = Number(target);
  if (Number.isNaN(to)) {
    el.textContent = formatter(target);
    return;
  }
  if (!Number.isNaN(from) && from === to) {
    el.textContent = formatter(to);
    el.dataset.value = String(to);
    return;
  }
  const start = Number.isNaN(from) ? to : from;
  el.dataset.value = String(to);
  const duration = 420;
  const t0 = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - t0) / duration);
    const eased = 1 - (1 - t) ** 3;
    const cur = start + (to - start) * eased;
    el.textContent = formatter(cur);
    if (t < 1) requestAnimationFrame(frame);
    else el.textContent = formatter(to);
  }
  requestAnimationFrame(frame);
}

function pulseKpiCard(selector) {
  const card = document.querySelector(selector);
  if (!card) return;
  card.classList.remove("kpi-pulse");
  void card.offsetWidth;
  card.classList.add("kpi-pulse");
}

async function fetchState() {
  const url = `/api/live-state?agent_id=${encodeURIComponent(selectedAgentId)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.error) msg = String(body.error);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return res.json();
}

function syncAgentSelect(data) {
  const select = $("agent-select");
  if (!select) return;
  const agents = data.meta?.available_agents || [data.meta?.agent_id ?? 1];
  const current = Number(data.meta?.agent_id ?? selectedAgentId);
  selectedAgentId = current;
  storeAgentId(current);
  select.innerHTML = agents
    .map((id) => `<option value="${id}">${escapeHtml(_t("nav.agentOption", { id }))}</option>`)
    .join("");
  select.value = String(current);
  select.disabled = agents.length <= 1;
}

function updateRunStatus(data) {
  const done = data.meta?.slots_done ?? 0;
  const complete = done >= 48;
  const dot = $("status-dot");
  const text = $("status-text");
  if (dot) dot.classList.toggle("idle", complete);
  if (text) {
    const aid = data.meta?.agent_id ?? selectedAgentId;
    const time = formatUpdated(data.meta?.updated_at);
    text.textContent = complete
      ? _t("nav.statusDone", { id: aid, time })
      : _t("nav.statusRunning", { id: aid, time });
  }
}

function countRecordedMeals(data) {
  const windows = data.meal_state?.restored_windows || data.live?.meal_state?.restored_windows;
  if (Array.isArray(windows)) return windows.length;
  if (windows && typeof windows === "object") return Object.keys(windows).length;
  let n = 0;
  (data.milestones || []).forEach((m) => {
    if (m.kind === "meal" || /餐|早饭|午饭|晚饭|早餐|午餐|晚餐|breakfast|lunch|dinner|bữa/i.test(m.label || "")) {
      n += 1;
    }
  });
  return n;
}

function formatUsd(usd) {
  const v = Number(usd);
  if (!Number.isFinite(v)) return "—";
  if (v === 0) return "$0.00";
  if (v >= 1) return `$${v.toFixed(2)}`;
  if (v >= 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(4)}`;
}

function formatVnd(vnd) {
  const v = Number(vnd);
  if (!Number.isFinite(v)) return "—";
  return `~${Math.round(v).toLocaleString("vi-VN")}₫`;
}

function formatCompactTokens(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "0 tok";
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M tok`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K tok`;
  return `${Math.round(v)} tok`;
}

function updateKpiCards(data) {
  const done = data.meta?.slots_done ?? 0;
  const t = data.timing || {};
  const needs = data.live?.needs || {};
  const activity = data.activity_log || {};
  const allRecords = activity.records || [];
  const failCount = allRecords.filter((r) => r.ok === false).length;

  const progressEl = $("kpi-progress");
  if (progressEl) progressEl.textContent = `${done} / 48`;
  const bar = $("kpi-bar-fill");
  if (bar) bar.style.width = `${Math.min(100, (done / 48) * 100)}%`;

  const clockEl = $("kpi-clock");
  if (clockEl) {
    const label = t.sim_time_label || "—";
    clockEl.textContent = label;
  }
  const stepEl = $("kpi-step");
  if (stepEl) {
    const steps = t.step_count != null ? _t("kpi.stepPrefix", { step: t.step_count }) : _t("kpi.stepEmpty");
    const translatedStatus = t.run_status && window.DashboardI18n ? window.DashboardI18n.runStatusLabel(t.run_status) : t.run_status;
    const status = translatedStatus ? ` · ${translatedStatus}` : "";
    stepEl.textContent = `${steps}${status}`;
  }

  const hungerRaw = needs.hunger ?? data.needs?.hunger?.[Math.max(0, done - 1)];
  const hungerEl = $("kpi-hunger");
  if (hungerEl && hungerRaw != null) {
    const pct = Number(hungerRaw) * 100;
    animateNumber(hungerEl, pct, (v) => `${v.toFixed(0)}%`);
    hungerEl.classList.toggle("kpi-warn", pct >= 75);
  } else if (hungerEl) {
    hungerEl.textContent = "—";
  }

  const mealsEl = $("kpi-meals");
  if (mealsEl) {
    const n = countRecordedMeals(data);
    mealsEl.textContent = _t("kpi.mealsRecorded", { count: n });
  }

  const envEl = $("kpi-env");
  if (envEl) animateNumber(envEl, allRecords.length, (v) => String(Math.round(v)));
  const envFailEl = $("kpi-env-fail");
  if (envFailEl) {
    envFailEl.textContent = _t("kpi.activityFail", { count: failCount });
    envFailEl.classList.toggle("kpi-danger", failCount > 0);
  }

  const llm = data.llm_stats;
  const costEl = $("kpi-cost");
  const tokensEl = $("kpi-tokens");
  if (costEl && tokensEl) {
    if (!llm || !llm.available) {
      costEl.textContent = "—";
      tokensEl.textContent = _t("kpi.costEmpty");
    } else {
      const totals = llm.totals || {};
      const totalTok = (totals.input || 0) + (totals.output || 0);
      const hitPct = ((llm.cache_hit_rate || 0) * 100).toFixed(1);
      if (llm.pricing_known) {
        costEl.textContent = formatUsd(llm.cost_usd);
        tokensEl.textContent = _t("kpi.costSub", {
          vnd: formatVnd(llm.cost_vnd),
          calls: totals.calls || 0,
          tokens: formatCompactTokens(totalTok),
          rate: hitPct,
        });
      } else {
        costEl.textContent = formatCompactTokens(totalTok);
        tokensEl.textContent = _t("kpi.costSubNoPrice", {
          calls: totals.calls || 0,
          tokens: formatCompactTokens(totalTok),
        });
      }
    }
  }

  if (done > lastSlotsDone && lastSlotsDone >= 0) {
    pulseKpiCard(".kpi-progress");
  }
  lastSlotsDone = done;
}

function renderLegendChips(container, chips) {
  if (!container) return;
  if (!chips.length) {
    container.innerHTML = `<span class="legend-empty">${escapeHtml(_t("legend.empty"))}</span>`;
    return;
  }
  container.innerHTML = chips
    .map((c) => {
      const icon = c.iconEmoji
        ? `<span class="lg-swatch" aria-hidden="true" style="font-size:11px;background:transparent;border:none">${escapeHtml(c.iconEmoji)}</span>`
        : `<i class="lg-swatch" style="background:${c.color}"></i>`;
      const title = c.title ? ` title="${escapeHtml(c.title)}"` : "";
      return `<span class="lg-chip"${title}>${icon}<span>${escapeHtml(c.label)}</span></span>`;
    })
    .join("");
}

function collectIntentionLegendItems(data) {
  const colors = data.intention_colors || {};
  const used = new Set();
  (data.slots || []).forEach((s) => {
    if (s.filled && s.intention) used.add(s.intention);
  });
  Object.keys(data.intent_mix || {}).forEach((k) => used.add(k));
  return INTENTION_ORDER.filter((k) => used.has(k)).map((k) => ({
    color: intentionColor(colors, k),
    label: getIntentionLabel(k),
    title: k,
  }));
}

function collectPositionLegendItems(data) {
  const colors = data.position_kind_colors || data.location_colors || {};
  return POSITION_KIND_ORDER.map((k) => ({
    color: positionColor(colors, k),
    label: getPositionKindLabel(k),
    title: getPositionKindLegend(k),
    iconEmoji: getPositionKindIcon(k).emoji,
  }));
}

function renderTimelineLegends(data) {
  const intent = collectIntentionLegendItems(data);
  const pos = collectPositionLegendItems(data);
  const combined = [
    ...intent.map((c) => ({ ...c, group: _t("timeline.groupIntent") })),
    ...pos.map((c) => ({ ...c, group: _t("timeline.groupPos") })),
  ];
  renderLegendChips($("timeline-legend-inline"), combined);
}

function renderSchematicLegends(data) {
  const intent = collectIntentionLegendItems(data);
  const pos = collectPositionLegendItems(data);
  renderLegendChips($("schematic-legend-row"), [...intent.slice(0, 5), ...pos]);
}

function clampNeed(v) {
  if (v == null || Number.isNaN(Number(v))) return null;
  return Math.min(1, Math.max(0, Number(v)));
}

const SCHEMATIC_PAD_X = 55;
const SCHEMATIC_PAD_Y = 45;
const SCHEMATIC_W = 400 - SCHEMATIC_PAD_X * 2;
const SCHEMATIC_H = 220 - SCHEMATIC_PAD_Y;
const OVERLAP_THRESHOLD_PX = 16;
const CLUSTER_FAN_RADIUS = 20;
const CLUSTER_FAN_RADIUS_MAX = 36;

function schematicBounds(lngs, lats) {
  let minLng = Math.min(...lngs);
  let maxLng = Math.max(...lngs);
  let minLat = Math.min(...lats);
  let maxLat = Math.max(...lats);
  if (maxLng - minLng < 1e-5) {
    minLng -= 0.002;
    maxLng += 0.002;
  }
  if (maxLat - minLat < 1e-5) {
    minLat -= 0.002;
    maxLat += 0.002;
  }
  return { minLng, maxLng, minLat, maxLat };
}

function projectLngLat(lng, lat, bounds) {
  const { minLng, maxLng, minLat, maxLat } = bounds;
  return {
    x: SCHEMATIC_PAD_X + ((lng - minLng) / (maxLng - minLng)) * SCHEMATIC_W,
    y: SCHEMATIC_PAD_Y + (1 - (lat - minLat) / (maxLat - minLat)) * SCHEMATIC_H,
  };
}

function schematicLocationKey(p) {
  if (isMovingPoint(p) && (p.lng == null || p.lat == null)) {
    return `moving-slot:${p.slot}`;
  }
  if (p.lng != null && p.lat != null) {
    if (isMovingPoint(p)) {
      return `moving-ll:${Number(p.lng).toFixed(5)},${Number(p.lat).toFixed(5)}`;
    }
    return `ll:${Number(p.lng).toFixed(5)},${Number(p.lat).toFixed(5)}`;
  }
  const kind = p.position_kind || "aoi";
  if (kind === "moving") return `moving-slot:${p.slot}`;
  return `kind:${kind}`;
}

function clusterCentroid(batch) {
  const cx = batch.reduce((s, p) => s + p.x, 0) / batch.length;
  const cy = batch.reduce((s, p) => s + p.y, 0) / batch.length;
  return { cx, cy };
}

/** 同地多时段：绕质心环形展开，避免节点完全重叠 */
function spreadOverlappingSchematicPoints(points) {
  if (points.length < 2) {
    points.forEach((p) => {
      p._baseX = p.x;
      p._baseY = p.y;
      p._clusterSize = 1;
    });
    return points;
  }

  const byKey = new Map();
  for (const p of points) {
    const key = schematicLocationKey(p);
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(p);
  }

  const batches = [];
  const consumed = new Set();
  for (const [key, batch] of byKey) {
    if (consumed.has(key)) continue;
    let merged = [...batch];
    consumed.add(key);
    let { cx, cy } = clusterCentroid(merged);

    for (const [otherKey, other] of byKey) {
      if (consumed.has(otherKey)) continue;
      const { cx: ox, cy: oy } = clusterCentroid(other);
      if ((cx - ox) ** 2 + (cy - oy) ** 2 <= OVERLAP_THRESHOLD_PX ** 2) {
        merged = merged.concat(other);
        consumed.add(otherKey);
        ({ cx, cy } = clusterCentroid(merged));
      }
    }
    batches.push(merged);
  }

  for (const batch of batches) {
    if (batch.length === 1) {
      const p = batch[0];
      p._baseX = p.x;
      p._baseY = p.y;
      p._clusterSize = 1;
      p._clusterId = `${p._baseX},${p._baseY}`;
      continue;
    }

    batch.sort((a, b) => a.slot - b.slot);
    const { cx, cy } = clusterCentroid(batch);
    const n = batch.length;
    const radius = Math.min(
      CLUSTER_FAN_RADIUS_MAX,
      CLUSTER_FAN_RADIUS + Math.max(0, n - 2) * 2.5,
    );
    const clusterId = `${cx.toFixed(1)},${cy.toFixed(1)}`;
    const useFullCircle = n > 5;
    const angleStep = useFullCircle ? (2 * Math.PI) / n : Math.min(0.55, 0.12 * (n - 1));
    const startAngle = useFullCircle
      ? -Math.PI / 2
      : -Math.PI / 2 - (angleStep * (n - 1)) / 2;

    batch.forEach((p, i) => {
      p._baseX = cx;
      p._baseY = cy;
      p._clusterSize = n;
      p._clusterId = clusterId;
      p._clusterIndex = i;
      const angle = startAngle + i * angleStep;
      p.x = cx + radius * Math.cos(angle);
      p.y = cy + radius * Math.sin(angle);
    });
  }

  return points;
}

function formatClusterRange(batch) {
  const slots = batch.map((p) => p.slot + 1).sort((a, b) => a - b);
  if (slots.length <= 4) return _t("map.clusterRangeShort", { slots: slots.join(", ") });
  return _t("map.clusterRangeLong", {
    first: slots[0],
    last: slots[slots.length - 1],
    count: slots.length,
  });
}

function clusterMismatchHint(batch) {
  const mism = batch.filter((p) => isIntentPositionMismatch(p.intention, p.position_kind));
  if (!mism.length) return "";
  const intents = [...new Set(mism.map((p) => getIntentionLabel(p.intention)))];
  return _t("map.clusterMismatch", {
    n: mism.length,
    intents: intents.slice(0, 2).join("/"),
  });
}

function applyLiveToSchematicPoints(pts, data) {
  const live = data.live?.snapshot;
  if (!pts.length || !live) return pts;
  const last = pts[pts.length - 1];
  last.position_kind = live.position_kind || last.position_kind;
  last.position_label = live.position_label || last.position_label;
  last.poi_name = live.poi_name || last.poi_name;
  last.live = true;
  if (live.lng != null && live.lat != null) {
    const lngs = pts.map((p) => p.lng).filter((v) => v != null);
    const lats = pts.map((p) => p.lat).filter((v) => v != null);
    lngs.push(live.lng);
    lats.push(live.lat);
    const bounds = schematicBounds(lngs, lats);
    last.lng = live.lng;
    last.lat = live.lat;
    const xy = projectLngLat(live.lng, live.lat, bounds);
    last.x = xy.x;
    last.y = xy.y;
  }
  return pts;
}

function schematicLandmarkCoords(slots, bounds) {
  const withCoords = slots.filter((s) => s.lng != null && s.lat != null);
  if (!withCoords.length || !bounds) return null;
  const homeSlots = withCoords.filter((s) => s.position_kind === "home");
  const workSlots = withCoords.filter((s) => s.position_kind === "work");
  const avg = (items) => {
    const lng = items.reduce((a, s) => a + s.lng, 0) / items.length;
    const lat = items.reduce((a, s) => a + s.lat, 0) / items.length;
    return projectLngLat(lng, lat, bounds);
  };
  return {
    home: homeSlots.length ? avg(homeSlots) : null,
    work: workSlots.length ? avg(workSlots) : null,
  };
}

function schematicPoints(data) {
  const slots = (data.slots || []).filter((s) => s.filled);
  const withCoords = slots.filter((s) => s.lng != null && s.lat != null);

  if (withCoords.length >= 1) {
    const lngs = withCoords.map((s) => s.lng);
    const lats = withCoords.map((s) => s.lat);
    const bounds = schematicBounds(lngs, lats);
    const pts = slots.map((s) => {
      if (s.lng != null && s.lat != null) {
        const xy = projectLngLat(s.lng, s.lat, bounds);
        return pointFromSlot(s, xy.x, xy.y);
      }
      const anchor = POSITION_KIND_ANCHORS[s.position_kind] || POSITION_KIND_ANCHORS.aoi;
      const jitter = isMovingPoint({ position_kind: s.position_kind, status: s.status })
        ? ((s.slot % 7) - 3) * 10
        : ((s.slot % 5) - 2) * 6;
      return pointFromSlot(
        s,
        anchor.x + jitter,
        anchor.y + ((s.slot % 3) - 1) * 5,
      );
    });
    const out = applyLiveToSchematicPoints(pts, data);
    out._schematicBounds = bounds;
    out._landmarks = schematicLandmarkCoords(withCoords, bounds);
    return out;
  }

  const pts = slots.map((s) => {
    const anchor = POSITION_KIND_ANCHORS[s.position_kind] || POSITION_KIND_ANCHORS.aoi;
    const jitter = isMovingPoint({ position_kind: s.position_kind, status: s.status })
      ? ((s.slot % 7) - 3) * 10
      : ((s.slot % 5) - 2) * 6;
    return pointFromSlot(
      s,
      anchor.x + jitter,
      anchor.y + ((s.slot % 3) - 1) * 5,
    );
  });
  return applyLiveToSchematicPoints(pts, data);
}

function pointFromSlot(s, x, y) {
  return {
    slot: s.slot,
    intention: s.intention,
    position_kind: s.position_kind,
    position_label: s.position_label,
    poi_name: s.poi_name,
    status: s.status,
    target_aoi_id: s.target_aoi_id,
    home_aoi: s.home_aoi,
    work_aoi: s.work_aoi,
    lng: s.lng,
    lat: s.lat,
    time_label: s.time_label,
    x,
    y,
  };
}

function svgEl(name, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

function initSchematic() {
  const svg = $("schematic");
  if (!svg) return;
  svg.innerHTML = `
    <defs>
      <marker id="trail-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/>
      </marker>
      <marker id="trail-arrow-commute" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#2980b9"/>
      </marker>
      <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
        <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#e2e8f2" stroke-width="0.8"/>
      </pattern>
      <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="2" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <rect width="400" height="260" fill="#f8fafc" rx="8"/>
    <rect width="400" height="260" fill="url(#grid)"/>
    <g id="schematic-anchors"></g>
    <g id="schematic-clusters"></g>
    <g id="schematic-trail"></g>
    <g id="schematic-nodes"></g>
  `;
}

function drawLandmark(anchorsG, x, y, kind, caption, posColors) {
  const g = svgEl("g", { class: "schematic-landmark" });
  g.appendChild(
    svgEl("circle", {
      cx: x,
      cy: y,
      r: 22,
      fill: "#ffffff",
      stroke: positionColor(posColors, kind),
      "stroke-width": 2,
      opacity: 0.96,
    }),
  );
  const icon = svgEl("text", {
    x,
    y: y + 6,
    "text-anchor": "middle",
    "font-size": 16,
  });
  icon.textContent = getPositionKindIcon(kind).emoji || "📍";
  g.appendChild(icon);
  const cap = svgEl("text", {
    x,
    y: y + 36,
    "text-anchor": "middle",
    fill: positionColor(posColors, kind),
    "font-size": 11,
    "font-weight": 600,
    "font-family": '"Noto Sans", "Noto Sans SC", sans-serif',
  });
  cap.textContent = caption;
  g.appendChild(cap);
  anchorsG.appendChild(g);
}

function schematicProgressEndSlot(data) {
  const done = data.meta?.slots_done ?? 0;
  return done > 0 ? Math.min(47, done - 1) : 0;
}

function resolveSchematicEndSlot(data) {
  const progressEnd = schematicProgressEndSlot(data);
  if (schematicFollowLive || schematicEndSlot == null) {
    if (selectedSlot != null && selectedSlot <= progressEnd) return selectedSlot;
    return progressEnd;
  }
  return Math.min(schematicEndSlot, progressEnd);
}

function syncSchematicControls(data) {
  const end = resolveSchematicEndSlot(data);
  const progressEnd = schematicProgressEndSlot(data);
  const slider = $("schematic-slider");
  if (!slider) return;
  slider.max = String(Math.max(0, progressEnd));
  if (Number(slider.value) > progressEnd || schematicFollowLive) {
    slider.value = String(end);
  }
  const label = $("schematic-slider-label");
  if (label) label.textContent = _t("map.slotProgress", { cur: end + 1, total: progressEnd + 1 });
  const follow = $("schematic-follow-live");
  if (follow) follow.checked = schematicFollowLive;
  const playBtn = $("schematic-play");
  if (playBtn) playBtn.textContent = schematicPlaying ? _t("map.pause") : _t("map.play");
}

function drawCommuteTargetHints(trailG, points, homeLm, workLm, latestSlot, selectedSlot) {
  const focusSlot = selectedSlot != null ? selectedSlot : latestSlot;
  const focus = points.find((p) => p.slot === focusSlot);
  if (!focus || !isMovingPoint(focus) || focus.target_aoi_id == null) return;

  let tx = null;
  let ty = null;
  let caption = targetAoiLabel(focus.target_aoi_id, focus.home_aoi, focus.work_aoi);
  if (focus.target_aoi_id === focus.home_aoi && homeLm) {
    tx = homeLm.x;
    ty = homeLm.y;
  } else if (focus.target_aoi_id === focus.work_aoi && workLm) {
    tx = workLm.x;
    ty = workLm.y;
  }
  if (tx == null || ty == null) return;

  trailG.appendChild(
    svgEl("line", {
      x1: focus.x,
      y1: focus.y,
      x2: tx,
      y2: ty,
      stroke: COMMUTE_COLOR,
      "stroke-width": 1.5,
      "stroke-dasharray": "4 5",
      opacity: 0.55,
      class: "trail-target",
    }),
  );
  trailG.appendChild(
    svgEl("circle", {
      cx: tx,
      cy: ty,
      r: 10,
      fill: "none",
      stroke: COMMUTE_COLOR,
      "stroke-width": 1.5,
      "stroke-dasharray": "3 2",
      opacity: 0.7,
    }),
  );
  if (caption) {
    const cap = svgEl("text", {
      x: (focus.x + tx) / 2,
      y: (focus.y + ty) / 2 - 8,
      "text-anchor": "middle",
      fill: COMMUTE_COLOR,
      "font-size": 9,
      "font-weight": 600,
      "font-family": '"Noto Sans", "Noto Sans SC", sans-serif',
    });
    cap.textContent = `→ ${caption}`;
    trailG.appendChild(cap);
  }
}

function drawClusterRings(points, clusterG, posColors) {
  const seen = new Map();
  for (const p of points) {
    if ((p._clusterSize || 1) < 2 || !p._clusterId) continue;
    if (seen.has(p._clusterId)) continue;
    const batch = points.filter((q) => q._clusterId === p._clusterId);
    seen.set(p._clusterId, batch);
  }

  seen.forEach((batch) => {
    const n = batch.length;
    const { cx, cy } = clusterCentroid(batch);
    const kind = batch[0].position_kind;
    const radius =
      Math.min(CLUSTER_FAN_RADIUS_MAX, CLUSTER_FAN_RADIUS + Math.max(0, n - 2) * 2.5) + 10;
    const stroke = positionColor(posColors, kind);

    clusterG.appendChild(
      svgEl("circle", {
        cx,
        cy,
        r: radius,
        fill: stroke,
        "fill-opacity": 0.06,
        stroke,
        "stroke-width": 1.5,
        "stroke-dasharray": "5 4",
        opacity: 0.85,
        class: "cluster-ring",
      }),
    );

    const dot = svgEl("circle", {
      cx,
      cy,
      r: 3,
      fill: stroke,
      opacity: 0.5,
      class: "cluster-core",
    });
    clusterG.appendChild(dot);

    const cap = svgEl("text", {
      x: cx,
      y: cy + radius + 13,
      "text-anchor": "middle",
      fill: "#64748b",
      "font-size": 9,
      "font-weight": 600,
      "font-family": '"Noto Sans", "Noto Sans SC", sans-serif',
      class: "cluster-label",
    });
    cap.textContent = _t("map.clusterCaption", {
      n,
      range: formatClusterRange(batch),
      hint: clusterMismatchHint(batch),
    });
    clusterG.appendChild(cap);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = batch
      .map(
        (p) =>
          `#${p.slot + 1} ${p.time_label} · ${getIntentionLabel(p.intention)}`,
      )
      .join("\n");
    clusterG.appendChild(title);
  });
}

function milestoneMarkerTitle(m) {
  const mLabel = window.DashboardI18n ? window.DashboardI18n.milestoneLabel(m.label) : m.label;
  return _t("timeline.milestoneClick", {
    slot: m.slot + 1,
    label: mLabel,
    kind: m.kind ? ` (${m.kind})` : "",
  });
}

function appendTrailSegment(trailG, prev, cur, stroke, intentColors, segIndex = 0) {
  const dist = Math.hypot(cur.x - prev.x, cur.y - prev.y);
  const sameCluster =
    prev._clusterId && prev._clusterId === cur._clusterId && (prev._clusterSize || 1) > 1;
  const commute = isCommuteSegment(prev, cur);
  const segStroke = commute ? COMMUTE_COLOR : stroke;

  if (dist < 4) return;

  if (sameCluster && dist < OVERLAP_THRESHOLD_PX * 1.2 && !commute) {
    const bx = prev._baseX ?? (prev.x + cur.x) / 2;
    const by = prev._baseY ?? (prev.y + cur.y) / 2;
    trailG.appendChild(
      svgEl("path", {
        d: `M ${prev.x} ${prev.y} Q ${bx} ${by} ${cur.x} ${cur.y}`,
        fill: "none",
        stroke: segStroke,
        "stroke-width": 2,
        opacity: 0.45,
        "stroke-linecap": "round",
        class: "trail-dwell",
      }),
    );
    return;
  }

  const lineAttrs = {
    x1: prev.x,
    y1: prev.y,
    x2: cur.x,
    y2: cur.y,
    stroke: segStroke,
    "stroke-width": commute ? 2.5 : dist < 12 ? 2 : 2.5,
    opacity: commute ? 0.75 : dist < 12 ? 0.45 : 0.6,
    "stroke-linecap": "round",
    class: commute ? "trail-commute" : "trail-segment",
  };
  if (commute) lineAttrs["stroke-dasharray"] = "7 5";
  if (dist >= 8 || commute) {
    lineAttrs["marker-end"] = commute ? "url(#trail-arrow-commute)" : "url(#trail-arrow)";
  }
  trailG.appendChild(svgEl("line", lineAttrs));

  const mx = (prev.x + cur.x) / 2;
  const my = (prev.y + cur.y) / 2;
  const labelLift = 8 + (segIndex % 3) * 11 + (commute ? 4 : 0);
  const seq = svgEl("text", {
    x: mx,
    y: my - labelLift,
    "text-anchor": "middle",
    fill: commute ? COMMUTE_COLOR : "#475569",
    "font-size": 9,
    "font-weight": 700,
    "font-family": '"JetBrains Mono", monospace',
  });
  let label = `${prev.slot + 1}→${cur.slot + 1}`;
  if (commute) label += ` ${_t("map.commuteLabel")}`;
  if (prev.lat != null && cur.lat != null && prev.lng != null && cur.lng != null) {
    const m = haversineMeters(prev.lat, prev.lng, cur.lat, cur.lng);
    if (m >= 80) label += ` · ${formatDistanceM(m)}`;
  }
  seq.textContent = label;
  trailG.appendChild(seq);
}

function updateSchematic(data) {
  const allPoints = schematicPoints(data);
  const endSlot = resolveSchematicEndSlot(data);
  syncSchematicControls(data);
  let points = allPoints.filter((p) => p.slot <= endSlot);
  spreadOverlappingSchematicPoints(points);

  const intentColors = data.intention_colors || {};
  const posColors = data.position_kind_colors || data.location_colors || {};
  const latestSlot = points.length > 0 ? points[points.length - 1].slot : null;

  const trailG = document.getElementById("schematic-trail");
  const clusterG = document.getElementById("schematic-clusters");
  const nodesG = document.getElementById("schematic-nodes");
  const anchorsG = document.getElementById("schematic-anchors");
  if (!trailG || !nodesG || !anchorsG) return;

  trailG.innerHTML = "";
  if (clusterG) clusterG.innerHTML = "";
  nodesG.innerHTML = "";
  anchorsG.innerHTML = "";

  const landmarks = allPoints._landmarks;
  const homeLm = landmarks?.home || POSITION_KIND_ANCHORS.home;
  const workLm = landmarks?.work || POSITION_KIND_ANCHORS.work;
  drawLandmark(anchorsG, homeLm.x, homeLm.y, "home", _t("map.homeShort"), posColors);
  if (landmarks?.work || (data.slots || []).some((s) => s.position_kind === "work")) {
    drawLandmark(anchorsG, workLm.x, workLm.y, "work", _t("map.workShort"), posColors);
  }

  if (clusterG) drawClusterRings(points, clusterG, posColors);

  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const stroke = positionColor(posColors, cur.position_kind);
    appendTrailSegment(trailG, prev, cur, stroke, intentColors, i);
  }

  drawCommuteTargetHints(trailG, points, homeLm, workLm, latestSlot, selectedSlot);

  const sortedPoints = [...points].sort((a, b) => {
    const score = (p) =>
      (p.slot === latestSlot ? 100 : 0) +
      (p.slot === selectedSlot ? 50 : 0) +
      p.slot;
    return score(a) - score(b);
  });

  sortedPoints.forEach((p) => {
    const icon = getPositionKindIcon(p.position_kind || "aoi");
    const isSelected = selectedSlot === p.slot;
    const isLatest = latestSlot === p.slot;
    const inCluster = (p._clusterSize || 1) > 1;
    const moving = isMovingPoint(p);
    const mismatch = isSelected && isIntentPositionMismatch(p.intention, p.position_kind);
    const g = svgEl("g", {
      class: `schematic-node${isSelected ? " selected" : ""}${isLatest ? " latest" : ""}${mismatch ? " mismatch" : ""}${p.live ? " live" : ""}${moving ? " moving" : ""}${inCluster && !isSelected && !isLatest ? " clustered" : ""}`,
    });
    let r = 12;
    if (inCluster && !isSelected && !isLatest) r = 9;
    if (isLatest) r = 15;
    if (isSelected) r = 17;
    const nodeStroke = moving
      ? COMMUTE_COLOR
      : intentionColor(intentColors, p.intention);
    g.appendChild(
      svgEl("circle", {
        class: "node-pos",
        cx: p.x,
        cy: p.y,
        r,
        fill: positionColor(posColors, p.position_kind),
        stroke: nodeStroke,
        "stroke-width": isLatest ? 3.5 : 2.5,
        "stroke-dasharray": moving ? "4 2" : undefined,
        opacity: 0.95,
        filter: isLatest ? "url(#node-glow)" : undefined,
      }),
    );
    const label = svgEl("text", {
      x: p.x,
      y: p.y + 5,
      "text-anchor": "middle",
      "font-size": isLatest ? 15 : 13,
    });
    label.textContent = icon.emoji;
    g.appendChild(label);
    const order = svgEl("text", {
      x: p.x,
      y: p.y - (isLatest ? 22 : 18),
      "text-anchor": "middle",
      fill: "#0f172a",
      "font-size": 9,
      "font-weight": 700,
      "font-family": '"JetBrains Mono", monospace',
    });
    order.textContent = `#${p.slot + 1}`;
    g.appendChild(order);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    const intentTxt = getIntentionLabel(p.intention);
    const locTxt = getPositionKindLabel(p.position_kind) || icon.label;
    const clusterHint =
      inCluster && p._clusterSize > 1
        ? `\n${_t("map.clusterTooltip", { n: p._clusterSize, idx: p._clusterIndex + 1 })}`
        : "";
    title.textContent = _t("map.tipSlot", {
      slot: p.slot + 1,
      time: p.time_label,
      intent: intentTxt,
      loc: locTxt,
      poi: p.poi_name ? ` · ${p.poi_name}` : "",
      cluster: clusterHint,
    });
    g.appendChild(title);
    g.addEventListener("click", () => selectSlot(p.slot));
    nodesG.appendChild(g);
  });

  const status = $("schematic-status");
  if (!status) return;
  status.classList.remove("mismatch");
  if (!points.length) {
    status.textContent = _t("map.waitingDetail");
  } else {
    const cur = points[points.length - 1];
    const slotRec = (data.slots || [])[cur.slot] || cur;
    const intentTxt = getIntentionLabel(cur.intention);
    let locTxt = formatMobilityLabel(slotRec, data.live);
    const hunger = data.live?.needs?.hunger ?? slotRec.needs?.hunger;
    const hungerTxt = hunger != null ? _t("map.hungerInline", { pct: (Number(hunger) * 100).toFixed(0) }) : "";
    const mismatch =
      isIntentPositionMismatch(slotRec.intention, slotRec.position_kind);
    if (mismatch && selectedSlot === cur.slot) {
      status.classList.add("mismatch");
      locTxt += _t("map.mismatchNote");
    }
    const clusterNote =
      (cur._clusterSize || 1) > 1
        ? _t("map.clusterNote", { n: cur._clusterSize })
        : "";
    status.textContent = _t("map.currentStatus", {
      slot: cur.slot + 1,
      time: cur.time_label,
      intent: intentTxt,
      loc: locTxt,
      cluster: clusterNote,
      hunger: hungerTxt,
    });
  }

  renderSchematicLegends(data);
  if (mapViewMode === "geo") updateGeoMapView(data);
}

function updateLocationPanel(data) {
  updateSchematic(data);
}

function isPlanIntentionMismatch(planIntention, actualIntention) {
  if (!planIntention || !actualIntention) return false;
  return planIntention !== actualIntention;
}

function scheduleColor(colors, activity) {
  return colors?.[activity] || "#cbd5e1";
}

function slotDriftInfo(s) {
  const planMismatch =
    s.filled && s.plan?.intention && isPlanIntentionMismatch(s.plan.intention, s.intention);
  const posMismatch = s.filled && isIntentPositionMismatch(s.intention, s.position_kind);
  return { planMismatch, posMismatch, any: planMismatch || posMismatch };
}

let timelineTooltipEl = null;

function getTimelineTooltip() {
  if (!timelineTooltipEl) {
    timelineTooltipEl = document.createElement("div");
    timelineTooltipEl.id = "timeline-tooltip";
    timelineTooltipEl.className = "timeline-tooltip hidden";
    timelineTooltipEl.setAttribute("role", "tooltip");
    document.body.appendChild(timelineTooltipEl);
  }
  return timelineTooltipEl;
}

function buildTimelineTooltipHtml(s, data) {
  const sch = data.schedule || {};

  const planText = !sch.available
    ? _t("timeline.noPlanGen")
    : !s.plan
      ? _t("timeline.noPlanBlock")
      : getScheduleActivityLabel(s.plan.activity) || s.plan.label || s.plan.activity;

  const intText = s.filled ? getIntentionLabel(s.intention) : _t("timeline.pending");
  const rawPos =
    s.filled && (s.position_label || s.position_kind != null)
      ? (s.position_label
        ? (window.DashboardI18n ? window.DashboardI18n.locationLabel(s.position_label) : s.position_label)
        : getPositionKindLabel(s.position_kind))
      : _t("timeline.noSnapshot");

  const { planMismatch, posMismatch } = slotDriftInfo(s);
  const driftLines = [];
  if (planMismatch) {
    driftLines.push(
      _t("timeline.driftPlan", {
        plan: getIntentionLabel(s.plan.intention),
        actual: getIntentionLabel(s.intention),
      }),
    );
  }
  if (posMismatch) {
    driftLines.push(
      _t("timeline.driftPos", {
        intent: getIntentionLabel(s.intention),
        pos: getPositionKindLabel(s.position_kind),
      }),
    );
  }

  const ms = milestoneBySlot.get(s.slot);
  const msText = ms
    ? (window.DashboardI18n ? window.DashboardI18n.milestoneLabel(ms.label || "") : (ms.label || ""))
    : "";
  const msLine = ms
    ? `<div class="tt-row tt-ms">${escapeHtml(ms.icon || "")} ${escapeHtml(msText)}</div>`
    : "";

  const timeExtra = s.simulation_time ? ` · ${escapeHtml(s.simulation_time)}` : "";
  const driftBlock = driftLines.length
    ? `<div class="tt-drift">${driftLines.map((line) => escapeHtml(line)).join("<br>")}</div>`
    : "";

  return `<div class="tt-title">${escapeHtml(_t("timeline.tipTitle", { slot: s.slot + 1, time: s.time_label || "", extra: "" }))}${timeExtra}</div>
    <div class="tt-row"><span class="tt-k">${escapeHtml(_t("timeline.plan"))}</span><span>${escapeHtml(String(planText))}</span></div>
    <div class="tt-row"><span class="tt-k">${escapeHtml(_t("timeline.intent"))}</span><span>${escapeHtml(String(intText))}</span></div>
    <div class="tt-row"><span class="tt-k">${escapeHtml(_t("timeline.loc"))}</span><span>${escapeHtml(String(rawPos))}</span></div>
    ${msLine}
    ${driftBlock}`;
}

function positionTimelineTooltip(evt) {
  const tip = getTimelineTooltip();
  if (tip.classList.contains("hidden")) return;
  const pad = 12;
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
  const rect = tip.getBoundingClientRect();
  if (rect.right > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
  if (rect.bottom > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

function showTimelineTooltip(evt, s, data) {
  const tip = getTimelineTooltip();
  tip.innerHTML = buildTimelineTooltipHtml(s, data);
  tip.classList.remove("hidden");
  positionTimelineTooltip(evt);
}

function hideTimelineTooltip() {
  getTimelineTooltip().classList.add("hidden");
}

function createMiniCell(className, color, empty) {
  const el = document.createElement("span");
  el.className = `tl-mini ${className}${empty ? " empty" : ""}`;
  el.setAttribute("aria-hidden", "true");
  if (!empty && color) el.style.background = color;
  return el;
}

function buildTimelineColumns(data, progressSlot) {
  const container = $("timeline-slot-columns");
  if (!container) return;
  container.innerHTML = "";

  const slots = data.slots || [];
  const sch = data.schedule || {};
  const planColors = sch.activity_colors || {};
  const intColors = data.intention_colors || {};
  const posColors = data.position_kind_colors || data.location_colors || {};

  slots.forEach((s) => {
    const col = document.createElement("button");
    col.type = "button";
    col.className = "tl-slot-col";

    const { planMismatch, posMismatch, any } = slotDriftInfo(s);
    if (any) col.classList.add("tl-slot-col--drift");
    if (planMismatch && posMismatch) col.classList.add("tl-slot-col--drift-both");
    else if (planMismatch) col.classList.add("tl-slot-col--drift-plan");
    else if (posMismatch) col.classList.add("tl-slot-col--drift-pos");

    if (milestoneBySlot.has(s.slot)) col.classList.add("milestone-hit");
    if (s.slot === selectedSlot) col.classList.add("selected");
    if (s.slot === progressSlot) col.classList.add("progress");
    col.dataset.slot = String(s.slot);

    const planEmpty = !sch.available || !s.plan;
    const planColor = planEmpty ? null : scheduleColor(planColors, s.plan.activity);
    col.appendChild(createMiniCell("tl-mini-plan", planColor, planEmpty));

    const intEmpty = !s.filled;
    col.appendChild(
      createMiniCell("tl-mini-intent", intEmpty ? null : intentionColor(intColors, s.intention), intEmpty),
    );

    const posEmpty = !s.filled && s.position_kind == null && !s.position_label;
    col.appendChild(
      createMiniCell(
        "tl-mini-loc",
        posEmpty ? null : positionColor(posColors, s.position_kind),
        posEmpty,
      ),
    );

    col.addEventListener("mouseenter", (e) => showTimelineTooltip(e, s, data));
    col.addEventListener("mousemove", positionTimelineTooltip);
    col.addEventListener("mouseleave", hideTimelineTooltip);
    col.addEventListener("click", () => {
      if (s.filled || s.position_kind != null || s.position_label || s.plan) selectSlot(s.slot);
    });

    container.appendChild(col);
  });
}

function renderSchedulePanel(data) {
  const sch = data.schedule || {};
  const diaryEl = $("schedule-diary");
  const tbody = $("schedule-table-body");
  const metaEl = $("schedule-meta");
  const descEl = $("schedule-desc");
  if (!tbody) return;

  if (!sch.available) {
    if (diaryEl) diaryEl.textContent = _t("schedule.notReady");
    if (metaEl) metaEl.innerHTML = "";
    if (descEl) descEl.textContent = _t("schedule.waitTimetable");
    tbody.innerHTML =
      `<tr><td colspan="4" class="empty-hint">${escapeHtml(_t("schedule.empty"))}</td></tr>`;
    return;
  }

  const prefs = sch.preferences || {};
  const prefBits = [];
  if (prefs.wake_time != null) prefBits.push(_t("schedule.wake", { time: formatHour(prefs.wake_time) }));
  if (prefs.work_start != null) prefBits.push(_t("schedule.workStart", { time: formatHour(prefs.work_start) }));
  if (prefs.work_end != null) prefBits.push(_t("schedule.workEnd", { time: formatHour(prefs.work_end) }));
  if (sch.norm_strength != null) prefBits.push(_t("schedule.normStrength", { pct: (Number(sch.norm_strength) * 100).toFixed(0) }));
  if (metaEl) {
    metaEl.innerHTML = prefBits.map((t) => `<span class="schedule-chip">${escapeHtml(t)}</span>`).join("");
  }
  if (descEl) {
    descEl.textContent = sch.scheduled_activity
      ? _t("schedule.currentBlock", { activity: formatScheduleActivity(sch.scheduled_activity) })
      : _t("schedule.defaultLoaded");
  }
  if (diaryEl) diaryEl.textContent = sch.daily_diary || "—";

  const colors = sch.activity_colors || {};
  const currentActivity = sch.scheduled_activity?.activity;
  tbody.innerHTML = (sch.blocks || [])
    .map((block) => {
      const activity = block.activity || "home_activity";
      const isCurrent = currentActivity && activity === currentActivity;
      const meal = block.meal_window
        ? escapeHtml(window.DashboardI18n ? window.DashboardI18n.mealWindowLabel(block.meal_window) : String(block.meal_window))
        : "—";
      const range = `${formatHour(block.start)}–${formatHour(block.end)}`;
      return `<tr class="${isCurrent ? "schedule-row-current" : ""}">
        <td class="mono">${range}</td>
        <td><span class="schedule-activity-pill" style="background:${scheduleColor(colors, activity)}22;color:${scheduleColor(colors, activity)}">${escapeHtml(getScheduleActivityLabel(activity))}</span></td>
        <td>${meal}</td>
        <td class="schedule-norm">${escapeHtml(block.norm || "—")}</td>
      </tr>`;
    })
    .join("");
}

function formatHour(hour) {
  const h = Math.floor(Number(hour));
  const m = Math.round((Number(hour) - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m >= 60 ? 0 : m).padStart(2, "0")}`;
}

function formatScheduleActivity(slot) {
  if (!slot || typeof slot !== "object") return "—";
  const activity = slot.activity || "—";
  return getScheduleActivityLabel(activity);
}

function buildTimeAxis() {
  const axis = $("time-axis");
  if (!axis) return;
  const ticks = document.createElement("div");
  ticks.className = "ticks";
  for (let h = 0; h < 24; h++) {
    const span = document.createElement("span");
    span.className = "tick";
    span.textContent = `${String(h).padStart(2, "0")}:00`;
    ticks.appendChild(span);
  }
  axis.innerHTML = "";
  axis.appendChild(document.createElement("div"));
  axis.appendChild(ticks);
}

function milestonePointRadii(done, milestones) {
  const radii = Array.from({ length: 48 }, () => 2);
  const hover = Array.from({ length: 48 }, () => 5);
  milestones.forEach((m) => {
    const slot = m.slot;
    if (slot < done) {
      radii[slot] = 7;
      hover[slot] = 9;
    }
  });
  return { radii, hover };
}

function initNeedsChart() {
  const canvas = $("needs-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  needsChart = new Chart(ctx, {
    type: "line",
    plugins: [milestoneLinesPlugin],
    data: {
      labels: Array.from({ length: 48 }, (_, i) => {
        const h = Math.floor(i / 2);
        const m = i % 2 ? "30" : "00";
        return `${String(h).padStart(2, "0")}:${m}`;
      }),
      datasets: [
        {
          label: _t("needs.hunger"),
          data: [],
          borderColor: "#dc2626",
          backgroundColor: "rgba(220,38,38,0.08)",
          fill: true,
          tension: 0.35,
          spanGaps: false,
          pointRadius: 2,
          pointHoverRadius: 6,
          borderWidth: 2.5,
        },
        {
          label: _t("needs.energy"),
          data: [],
          borderColor: "#2563eb",
          backgroundColor: "rgba(37,99,235,0.06)",
          fill: true,
          tension: 0.35,
          spanGaps: false,
          pointRadius: 2,
          pointHoverRadius: 6,
          borderWidth: 2.5,
        },
        {
          label: _t("needs.stress"),
          data: [],
          borderColor: "#7c3aed",
          backgroundColor: "rgba(124,58,237,0.06)",
          fill: true,
          tension: 0.35,
          spanGaps: false,
          pointRadius: 2,
          pointHoverRadius: 6,
          borderWidth: 2.5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 320, easing: "easeOutQuart" },
      interaction: { mode: "index", intersect: false },
      layout: {
        padding: { top: NEEDS_CHART_MILESTONE_PAD_TOP, right: 8, bottom: 4, left: 4 },
      },
      plugins: {
        legend: { display: false },
        milestoneLines: { items: [] },
        tooltip: {
          backgroundColor: "rgba(15,23,42,0.92)",
          titleFont: { family: '"Noto Sans", "Noto Sans SC", sans-serif', size: 12 },
          bodyFont: { family: '"Noto Sans", "Noto Sans SC", sans-serif', size: 12 },
          padding: 10,
          cornerRadius: 8,
          callbacks: {
            title(items) {
              if (!items.length) return "";
              return _t("needs.tooltipTitle", { slot: items[0].dataIndex + 1, time: items[0].label });
            },
            label(ctx) {
              const v = ctx.parsed.y;
              if (v == null) return `${ctx.dataset.label}: —`;
              return `${ctx.dataset.label}: ${(v * 100).toFixed(1)}%`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: CHART_TEXT, maxTicksLimit: 12, font: { size: 10 } },
          grid: { color: CHART_GRID },
        },
        y: {
          min: 0,
          max: 1,
          ticks: {
            color: CHART_TEXT,
            stepSize: 0.25,
            callback: (v) => `${Math.round(Number(v) * 100)}%`,
          },
          grid: { color: CHART_GRID },
        },
      },
      onClick: (_, elements) => {
        if (elements.length) selectSlot(elements[0].index);
      },
    },
  });
}

function updateNeedsChart(data) {
  if (!needsChart) return;
  const needs = data.needs || {};
  const done = data.meta?.slots_done ?? 0;
  const milestones = data.milestones || [];
  const mapNeed = (arr) => (arr || []).map((v, i) => (i < done ? clampNeed(v) : null));
  needsChart.data.datasets[0].data = mapNeed(needs.hunger);
  needsChart.data.datasets[1].data = mapNeed(needs.energy);
  needsChart.data.datasets[2].data = mapNeed(needs.stress);

  const { radii, hover } = milestonePointRadii(done, milestones);
  const pointColors = Array.from({ length: 48 }, (_, i) => milestoneBySlot.get(i)?.color || null);
  needsChart.data.datasets.forEach((ds) => {
    ds.pointRadius = [...radii];
    ds.pointHoverRadius = [...hover];
    ds.pointBackgroundColor = pointColors.map((c, i) =>
      i < done ? c || ds.borderColor : "transparent",
    );
    ds.pointBorderColor = pointColors.map((c, i) => (i < done && c ? c : ds.borderColor));
  });
  const chartMilestones = milestones.filter((m) => m.slot < done);
  const chartWidth = Math.max(needsChart.width || 640, 320);
  needsChart.options.plugins.milestoneLines.items = layoutMilestones(chartMilestones, chartWidth);

  if (selectedSlot != null && selectedSlot < done) {
    needsChart.setActiveElements([
      { datasetIndex: 0, index: selectedSlot },
      { datasetIndex: 1, index: selectedSlot },
      { datasetIndex: 2, index: selectedSlot },
    ]);
  } else {
    needsChart.setActiveElements([]);
  }
  needsChart.update("none");
}

function activityCategoryColor(data, category) {
  return data?.activity_log?.category_colors?.[category] || "#94a3b8";
}

function activityCategoryLabel(data, category) {
  const fallback = data?.activity_log?.category_labels?.[category] || category;
  return window.DashboardI18n ? window.DashboardI18n.activityCategoryLabel(category, fallback) : fallback;
}

function activitySlotFilterBounds() {
  if (activitySlotFrom == null && activitySlotTo == null) return null;
  const from = activitySlotFrom ?? 0;
  const to = activitySlotTo ?? 47;
  return [Math.min(from, to), Math.max(from, to)];
}

function formatSlotOptionLabel(slot, data) {
  const s = (data?.slots || [])[slot];
  const time = s?.time_label || s?.simulation_time?.slice(11, 16) || "";
  const h = Math.floor(slot / 2);
  const m = slot % 2 ? "30" : "00";
  const clock = time || `${String(h).padStart(2, "0")}:${m}`;
  return `${slot + 1} · ${clock}`;
}

function syncActivitySlotFilterUi(data) {
  const fromEl = $("activity-slot-from");
  const toEl = $("activity-slot-to");
  const followEl = $("activity-slot-follow");
  if (!fromEl || !toEl) return;

  if (!fromEl.dataset.initialized) {
    const opts = [`<option value="">${escapeHtml(_t("activity.allSlots"))}</option>`];
    for (let slot = 0; slot < 48; slot += 1) {
      const label = formatSlotOptionLabel(slot, data);
      opts.push(`<option value="${slot}">${escapeHtml(label)}</option>`);
    }
    fromEl.innerHTML = opts.join("");
    toEl.innerHTML = opts.join("");
    fromEl.dataset.initialized = "1";
  }

  fromEl.value = activitySlotFrom == null ? "" : String(activitySlotFrom);
  toEl.value = activitySlotTo == null ? "" : String(activitySlotTo);
  if (followEl) followEl.checked = activitySlotFollowSelection;
}

function setActivitySlotFilter(from, to, { follow = false, refresh = true } = {}) {
  activitySlotFrom = from;
  activitySlotTo = to;
  if (follow != null) activitySlotFollowSelection = follow;
  if (state) {
    syncActivitySlotFilterUi(state);
    if (refresh) updateEnvCalls(state);
  }
}

function clearActivitySlotFilter() {
  activitySlotFrom = null;
  activitySlotTo = null;
  if (state) {
    syncActivitySlotFilterUi(state);
    updateEnvCalls(state);
  }
}

function applyActivitySlotFilterFromSelection() {
  if (selectedSlot == null) return;
  setActivitySlotFilter(selectedSlot, selectedSlot);
}

function onActivitySlotFilterChange() {
  const fromEl = $("activity-slot-from");
  const toEl = $("activity-slot-to");
  if (!fromEl || !toEl) return;
  activitySlotFrom = fromEl.value === "" ? null : Number(fromEl.value);
  activitySlotTo = toEl.value === "" ? null : Number(toEl.value);
  if (activitySlotFrom != null || activitySlotTo != null) {
    envFilterPreset = "custom";
    document.querySelectorAll(".env-btn[data-preset]").forEach((btn) => {
      btn.classList.remove("active");
    });
  }
  if (state) updateEnvCalls(state);
}

function activityRecordPassesFilter(r, data) {
  const bounds = activitySlotFilterBounds();
  if (bounds) {
    if (r.slot == null || r.slot < bounds[0] || r.slot > bounds[1]) return false;
  }
  if (envFilterOnlyFail && r.ok !== false) return false;
  if (envFilterPreset === "fail") return r.ok === false;
  if (activityFilterCategories.size > 0 && !activityFilterCategories.has(r.category)) {
    return false;
  }
  if (activityFilterKinds.size > 0 && !activityFilterKinds.has(r.kind)) return false;
  if (envFilterPreset === "key") {
    return ACTIVITY_KEY_CATEGORIES.has(r.category) || ENV_KEY_KINDS.has(r.kind);
  }
  if (activitySearchQuery) {
    const hay = `${r.label || ""} ${r.kind || ""} ${r.summary || ""} ${r.detail || ""} ${r.source || ""}`.toLowerCase();
    if (!hay.includes(activitySearchQuery)) return false;
  }
  return true;
}

function applyEnvFilterPreset(preset) {
  storeEnvFilterPreset(preset);
  envFilterOnlyFail = preset === "fail";
  activityFilterCategories.clear();
  activityFilterKinds.clear();
  document.querySelectorAll(".env-btn[data-preset]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.preset === preset);
  });
  document.querySelectorAll(".activity-cat-chip").forEach((chip) => {
    chip.classList.remove("active");
  });
  if (state) updateEnvCalls(state);
}

function toggleActivityCategoryFilter(category) {
  if (activityFilterCategories.has(category)) activityFilterCategories.delete(category);
  else activityFilterCategories.add(category);
  envFilterPreset = "custom";
  envFilterOnlyFail = false;
  document.querySelectorAll(".env-btn[data-preset]").forEach((btn) => {
    btn.classList.remove("active");
  });
  if (state) updateEnvCalls(state);
}

function buildActivityCategoryFilters(data) {
  const group = $("activity-cat-filters");
  if (!group) return;
  const summary = data.activity_log?.summary || {};
  const byCat = summary.by_category || {};
  const cats = Object.keys(byCat).sort(
    (a, b) => (byCat[b] || 0) - (byCat[a] || 0),
  );
  group.innerHTML = cats
    .map((cat) => {
      const color = activityCategoryColor(data, cat);
      const active = activityFilterCategories.has(cat) ? " active" : "";
      const label = activityCategoryLabel(data, cat);
      return `<button type="button" class="activity-cat-chip${active}" data-category="${escapeHtml(cat)}" style="--cat-color:${color}">${escapeHtml(label)} <strong>${byCat[cat]}</strong></button>`;
    })
    .join("");
  group.querySelectorAll(".activity-cat-chip").forEach((chip) => {
    chip.addEventListener("click", () => toggleActivityCategoryFilter(chip.dataset.category));
  });
}

function activityRecordKey(r) {
  return `${r.slot ?? ""}|${r.category ?? ""}|${r.kind ?? ""}|${r.simulation_time ?? ""}|${r.summary ?? ""}|${r.ok ?? ""}`;
}

function updateEnvCalls(data) {
  const summaryEl = $("env-summary");
  const list = $("env-calls-list");
  const activity = data.activity_log || {};
  const allRecords = activity.records || [];
  const summary = activity.summary || {};
  const records = allRecords.filter((r) => activityRecordPassesFilter(r, data));

  const agentId = Number(data.meta?.agent_id ?? selectedAgentId);
  const lang = window.DashboardI18n ? window.DashboardI18n.getLang() : "vi";
  const renderKey = JSON.stringify({
    agentId,
    lang,
    preset: envFilterPreset,
    onlyFail: envFilterOnlyFail,
    cats: [...activityFilterCategories].sort(),
    kinds: [...activityFilterKinds].sort(),
    q: activitySearchQuery,
    bounds: activitySlotFilterBounds(),
    total: allRecords.length,
    shown: records.length,
    head: records.length ? activityRecordKey(records[0]) : null,
    tail: records.length ? activityRecordKey(records[records.length - 1]) : null,
    byCat: summary.by_category || null,
  });
  if (renderKey === lastActivityRenderKey) {
    return;
  }
  lastActivityRenderKey = renderKey;

  syncActivitySlotFilterUi(data);
  buildActivityCategoryFilters(data);

  if (!summaryEl || !list) return;

  if (!allRecords.length) {
    summaryEl.innerHTML =
      `<span class="env-empty">${escapeHtml(_t("activity.emptyAll"))}</span>`;
    list.innerHTML = "";
    return;
  }

  const filteredCounts = {};
  for (const r of records) {
    const kind = r.kind || "—";
    filteredCounts[kind] = (filteredCounts[kind] || 0) + 1;
  }
  const kindBits = Object.entries(filteredCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([kind, n]) => `<span class="env-stat-chip">${escapeHtml(kind)} <strong>${n}</strong></span>`)
    .join("");

  const shownFails = records.filter((r) => r.ok === false).length;
  const slotBounds = activitySlotFilterBounds();
  const slotChip = slotBounds
    ? `<span class="env-stat-chip">${_t("activity.slotRange", { from: slotBounds[0] + 1, to: slotBounds[1] + 1 })}</span>`
    : "";

  summaryEl.innerHTML = `
    <span class="env-stat-chip env-stat-total">${_t("activity.showing", { shown: records.length, total: allRecords.length })}</span>
    ${slotChip}
    <span class="env-stat-chip ${shownFails ? "env-stat-warn" : ""}">${_t("activity.failedBadge", { count: shownFails })}</span>
    ${kindBits}
  `;

  if (!records.length) {
    list.innerHTML = `<li class="env-empty">${escapeHtml(_t("activity.emptyFiltered"))}</li>`;
    return;
  }

  let seenKeys = seenActivityKeysByAgent.get(agentId);
  const firstSeenBatch = !seenKeys;
  if (!seenKeys) {
    seenKeys = new Set();
    seenActivityKeysByAgent.set(agentId, seenKeys);
  }
  const scrollWrap = list.parentElement;
  const prevScrollTop = scrollWrap ? scrollWrap.scrollTop : list.scrollTop;

  list.innerHTML = [...records]
    .reverse()
    .map((r) => {
      const cat = r.category || "tool";
      const color = activityCategoryColor(data, cat);
      const slot = r.slot != null ? r.slot + 1 : "—";
      const catLabel = activityCategoryLabel(data, cat);
      const itemLabel = window.DashboardI18n
        ? window.DashboardI18n.activityRecordLabel(r.label || r.kind || "—")
        : (r.label || r.kind || "—");
      const summaryText = window.DashboardI18n
        ? window.DashboardI18n.activitySummaryText(r.summary || "—")
        : (r.summary || "—");
      const status =
        r.ok === false ? _t("activity.statusFail") : r.ok === true ? _t("activity.statusOk") : "—";
      const recKey = activityRecordKey(r);
      const isNew = !firstSeenBatch && !seenKeys.has(recKey);
      seenKeys.add(recKey);
      return `
    <li class="env-call-item activity-item${r.ok === false ? " failed" : ""}${isNew ? " is-new" : ""}" data-slot="${escapeHtml(r.slot ?? "")}" data-category="${escapeHtml(cat)}">
      <div class="env-call-head">
        <span class="env-fn-tag activity-cat-tag" style="border-color:${color};color:${color}">${escapeHtml(catLabel)}</span>
        <span class="env-fn-tag activity-kind-tag">${escapeHtml(itemLabel)}</span>
        <span class="env-call-meta">${escapeHtml(_t("activity.itemMeta", { slot, source: r.source || "—" }))}</span>
        <span class="env-call-status">${status}</span>
      </div>
      <div class="env-call-detail">
        <span>${escapeHtml(summaryText)}</span>
        ${r.detail ? `<span class="env-call-ret">→ ${escapeHtml(r.detail)}</span>` : ""}
      </div>
    </li>`;
    })
    .join("");

  if (scrollWrap) {
    scrollWrap.scrollTop = prevScrollTop;
  } else {
    list.scrollTop = prevScrollTop;
  }

  list.querySelectorAll("li[data-slot]").forEach((li) => {
    const slot = li.dataset.slot;
    if (slot === "") return;
    li.addEventListener("click", () => selectSlot(Number(slot)));
  });
}

function selectSlot(slot) {
  selectedSlot = slot;
  schematicFollowLive = false;
  schematicEndSlot = slot;
  if (activitySlotFollowSelection) {
    activitySlotFrom = slot;
    activitySlotTo = slot;
  }
  if (state) render(state);
  openDrawer(slot);
}

function stopSchematicPlay() {
  schematicPlaying = false;
  if (schematicPlayTimer) {
    clearInterval(schematicPlayTimer);
    schematicPlayTimer = null;
  }
}

function stepSchematic(delta) {
  if (!state) return;
  const max = schematicProgressEndSlot(state);
  schematicFollowLive = false;
  const cur = resolveSchematicEndSlot(state);
  schematicEndSlot = Math.max(0, Math.min(max, cur + delta));
  const slider = $("schematic-slider");
  if (slider) slider.value = String(schematicEndSlot);
  updateLocationPanel(state);
}

function toggleSchematicPlay() {
  if (!state) return;
  if (schematicPlaying) {
    stopSchematicPlay();
    updateLocationPanel(state);
    return;
  }
  schematicFollowLive = false;
  schematicPlaying = true;
  const playBtn = $("schematic-play");
  if (playBtn) playBtn.textContent = _t("map.pause");
  schematicPlayTimer = setInterval(() => {
    if (!state) {
      stopSchematicPlay();
      return;
    }
    const max = schematicProgressEndSlot(state);
    const cur = resolveSchematicEndSlot(state);
    if (cur >= max) {
      stopSchematicPlay();
      updateLocationPanel(state);
      return;
    }
    schematicEndSlot = cur + 1;
    const slider = $("schematic-slider");
    if (slider) slider.value = String(schematicEndSlot);
    updateLocationPanel(state);
  }, 700);
}

async function requestViTranslation(text) {
  const res = await fetch("/api/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_lang: "vi" }),
  });
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* ignore */
  }
  if (!res.ok || !body?.translated) {
    throw new Error(body?.error || `HTTP ${res.status}`);
  }
  return {
    translated: String(body.translated),
    cached: Boolean(body.cached),
    model: body.model || "gpt-5.4-nano",
  };
}

function renderLangSwitchHtml(target, currentMode) {
  return `<div class="inline-lang-toggle" role="group">
    <button type="button" class="inline-lang-btn${currentMode === "vi" ? " active" : ""}" data-target="${target}" data-lang="vi">${escapeHtml(_t("drawer.viewVi"))}</button>
    <button type="button" class="inline-lang-btn${currentMode === "en" ? " active" : ""}" data-target="${target}" data-lang="en">${escapeHtml(_t("drawer.viewOriginal"))}</button>
  </div>`;
}

function openCostDrawer() {
  const drawer = $("detail-drawer");
  const body = $("drawer-body");
  if (!drawer || !body) return;
  drawerMode = "cost";

  const eyebrow = drawer.querySelector(".drawer-eyebrow");
  if (eyebrow) eyebrow.textContent = _t("cost.drawerEyebrow");
  $("drawer-title").textContent = _t("cost.drawerTitle");

  const llm = state?.llm_stats;
  if (!llm || !llm.available) {
    body.innerHTML = `<p class="empty-hint">${escapeHtml(_t("cost.noData"))}</p>`;
  } else {
    const totals = llm.totals || {};
    const totalTok = (totals.input || 0) + (totals.output || 0);
    const hitPct = ((llm.cache_hit_rate || 0) * 100).toFixed(1);
    const models = Object.entries(llm.models || {});
    const agentTotals = llm.agent_side?.totals || {};
    const routerTotals = llm.router_side?.totals || {};
    const modelRows = models
      .map(([name, m]) => {
        const inputStr = `${Number(m.input || 0).toLocaleString("en-US")} (${Number(m.cached_input || 0).toLocaleString("en-US")})`;
        const outputStr = Number(m.output || 0).toLocaleString("en-US");
        const costStr = m.pricing_known
          ? `${formatUsd(m.cost_usd)}<br/><small>${escapeHtml(formatVnd(m.cost_vnd))}</small>`
          : "—";
        return `<tr>
          <td class="mono">${escapeHtml(name)}</td>
          <td class="num">${m.calls || 0}</td>
          <td class="num">${escapeHtml(inputStr)}</td>
          <td class="num">${escapeHtml(outputStr)}</td>
          <td class="num">${costStr}</td>
        </tr>`;
      })
      .join("");

    body.innerHTML = `
      <div class="detail-grid">
        <div class="detail-card full">
          <label>${escapeHtml(_t("cost.totalCost"))}</label>
          <div class="value">${llm.pricing_known ? `${escapeHtml(formatUsd(llm.cost_usd))} · ${escapeHtml(formatVnd(llm.cost_vnd))}` : "—"}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.totalCalls"))}</label>
          <div class="value mono">${Number(totals.calls || 0).toLocaleString("en-US")}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.totalTokens"))}</label>
          <div class="value mono">${Number(totalTok).toLocaleString("en-US")}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.inputTokens"))}</label>
          <div class="value mono">${Number(totals.input || 0).toLocaleString("en-US")}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.cachedTokens"))}</label>
          <div class="value mono">${Number(totals.cached_input || 0).toLocaleString("en-US")} (${hitPct}%)</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.outputTokens"))}</label>
          <div class="value mono">${Number(totals.output || 0).toLocaleString("en-US")}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("cost.agentSide"))}</label>
          <div class="value">${escapeHtml(_t("cost.sideDetail", {
            calls: agentTotals.calls || 0,
            input: formatCompactTokens(agentTotals.input || 0),
            output: formatCompactTokens(agentTotals.output || 0),
          }))}</div>
        </div>
        <div class="detail-card full">
          <label>${escapeHtml(_t("cost.routerSide"))}</label>
          <div class="value">${escapeHtml(_t("cost.sideDetail", {
            calls: routerTotals.calls || 0,
            input: formatCompactTokens(routerTotals.input || 0),
            output: formatCompactTokens(routerTotals.output || 0),
          }))}</div>
        </div>
      </div>
      ${llm.pricing_known
        ? `<div class="cost-savings">${escapeHtml(_t("cost.cacheSaved", {
          usd: formatUsd(llm.saved_by_cache_usd),
          vnd: formatVnd(llm.saved_by_cache_vnd),
          rate: hitPct,
        }))}</div>`
        : ""
      }
      <div class="q-section">
        <h3>${escapeHtml(_t("cost.byModel"))}</h3>
        <table class="cost-table">
          <thead>
            <tr>
              <th>${escapeHtml(_t("cost.colModel"))}</th>
              <th class="num">${escapeHtml(_t("cost.colCalls"))}</th>
              <th class="num">${escapeHtml(_t("cost.colInput"))}</th>
              <th class="num">${escapeHtml(_t("cost.colOutput"))}</th>
              <th class="num">${escapeHtml(_t("cost.colCost"))}</th>
            </tr>
          </thead>
          <tbody>${modelRows}</tbody>
        </table>
      </div>
      <p class="cost-note">${escapeHtml(_t("cost.disclaimer", { rate: Number(llm.usd_to_vnd || 25500).toLocaleString("vi-VN") }))}</p>
    `;
  }

  drawer.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
}

function openDrawer(slot) {
  const drawer = $("detail-drawer");
  const s = (state?.slots || [])[slot];
  if (!drawer || !s) return;
  drawerMode = "slot";
  selectedSlot = slot;

  const eyebrow = drawer.querySelector(".drawer-eyebrow");
  if (eyebrow) eyebrow.textContent = _t("drawer.eyebrow");

  $("drawer-title").textContent = _t("drawer.title", {
    slot: slot + 1,
    time: s.time_label,
    sim: s.simulation_time ? ` (${s.simulation_time})` : "",
  });

  const colors = state.intention_colors || {};
  const body = $("drawer-body");

  if (!s.filled) {
    const mealTxt = s.plan?.meal_window
      ? ` · ${window.DashboardI18n ? window.DashboardI18n.mealWindowLabel(s.plan.meal_window) : s.plan.meal_window}`
      : "";
    const planBlock = s.plan
      ? `<div class="detail-card full plan-block">
          <label>${escapeHtml(_t("drawer.planHeader", { range: s.plan.time_range || "—" }))}</label>
          <div class="value">${escapeHtml(getScheduleActivityLabel(s.plan.activity) || s.plan.label || "—")}${escapeHtml(mealTxt)}</div>
          ${s.plan.norm ? `<p class="plan-norm">${escapeHtml(s.plan.norm)}</p>` : ""}
        </div>`
      : "";
    body.innerHTML = `${planBlock}<p class="empty-hint">${escapeHtml(_t("drawer.notCompleted"))}</p>`;
  } else {
    const q = s.questionnaire || {};
    const answers = (q.responses || [])
      .filter((r) => Number(r.agent_id) === Number(state?.meta?.agent_id ?? 1))
      .flatMap((r) => r.answers || []);
    const primary = answers.find((a) => a.question_id === "primary_intention");
    const prompt =
      (q.questions || []).find((x) => x.id === "primary_intention")?.prompt || "";

    const fmtNeed = (v) => (v != null ? `${(Number(v) * 100).toFixed(0)}%` : "—");
    const mealTag = s.plan?.meal_window
      ? `<span class="plan-meal-tag">${escapeHtml(window.DashboardI18n ? window.DashboardI18n.mealWindowLabel(s.plan.meal_window) : s.plan.meal_window)}</span>`
      : "";
    const rawPosLabel = s.position_label
      ? (window.DashboardI18n ? window.DashboardI18n.locationLabel(s.position_label) : s.position_label)
      : "—";

    const isViDash = (window.DashboardI18n?.getLang() || "vi") === "vi";
    const translatedPrompt = isViDash && window.DashboardI18n?.translateSurveyPrompt
      ? window.DashboardI18n.translateSurveyPrompt(prompt)
      : null;
    const showViPrompt = Boolean(translatedPrompt && drawerPromptLang === "vi");
    const promptShown = showViPrompt ? translatedPrompt : prompt;

    const cachedReason = s.reason ? reasonTranslations.get(s.reason) : null;
    const showViReason = Boolean(isViDash && s.reason && drawerReasonLang === "vi");
    let reasonBodyHtml = "";
    if (s.reason) {
      if (!showViReason) {
        reasonBodyHtml = `<div id="drawer-reason-text">${escapeHtml(s.reason)}</div>`;
      } else if (cachedReason) {
        const badgeKey = cachedReason.cached ? "drawer.translateCached" : "drawer.translateLive";
        reasonBodyHtml = `<div id="drawer-reason-text">${escapeHtml(cachedReason.translated)}</div>
          <div class="translate-status" id="drawer-reason-status">${escapeHtml(_t(badgeKey, { model: cachedReason.model }))}</div>`;
      } else {
        reasonBodyHtml = `<div class="translate-status" id="drawer-reason-status">${escapeHtml(_t("drawer.translating"))}</div>
          <div class="reason-fallback" id="drawer-reason-text">${escapeHtml(s.reason)}</div>`;
      }
    }

    body.innerHTML = `
      ${s.plan
        ? `<div class="detail-card full plan-block">
            <label>${escapeHtml(_t("drawer.planHeader", { range: s.plan.time_range || "—" }))}</label>
            <div class="value">
              <span class="intention-pill" style="background:${scheduleColor(state.schedule?.activity_colors, s.plan.activity)}18;color:${scheduleColor(state.schedule?.activity_colors, s.plan.activity)}">
                ${escapeHtml(getScheduleActivityLabel(s.plan.activity) || s.plan.label || "—")}
              </span>
              ${mealTag}
            </div>
            ${s.plan.norm ? `<p class="plan-norm">${escapeHtml(s.plan.norm)}</p>` : ""}
            ${isPlanIntentionMismatch(s.plan.intention, s.intention) ? `<p class="plan-deviation-note">${escapeHtml(_t("drawer.planMismatch"))}</p>` : ""}
          </div>`
        : ""
      }
      <div class="detail-grid">
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.mainIntent"))}</label>
          <span class="intention-pill value" style="background:${intentionColor(colors, s.intention)}18;color:${intentionColor(colors, s.intention)}">
            ${escapeHtml(getIntentionLabel(s.intention))}
          </span>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.posType"))}</label>
          <div class="value">${escapeHtml(getPositionKindLabel(s.position_kind))}</div>
        </div>
        <div class="detail-card full">
          <label>${escapeHtml(_t("drawer.posRaw"))}</label>
          <div class="value mono">${escapeHtml(rawPosLabel)}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.simTime"))}</label>
          <div class="value">${escapeHtml(s.simulation_time || s.time_label || "—")}</div>
        </div>
        <div class="detail-card">
          <label>AOI</label>
          <div class="value mono">${s.aoi_id ?? "—"}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.homeAoi"))}</label>
          <div class="value mono">${s.home_aoi ?? state?.home_aoi ?? "—"}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.workAoi"))}</label>
          <div class="value mono">${s.work_aoi ?? state?.work_aoi ?? "—"}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.engineStatus"))}</label>
          <div class="value">${escapeHtml(s.status || "—")}${isMovingPoint(s) ? escapeHtml(_t("drawer.onTheWay")) : ""}</div>
        </div>
        ${s.target_aoi_id != null
        ? `<div class="detail-card"><label>${escapeHtml(_t("drawer.commuteTarget"))}</label><div class="value">${escapeHtml(targetAoiLabel(s.target_aoi_id, s.home_aoi, s.work_aoi) || String(s.target_aoi_id))}</div></div>`
        : ""
      }
        ${s.poi_name
        ? `<div class="detail-card full"><label>POI</label><div class="value">${escapeHtml(s.poi_name)}${s.poi_category ? ` · ${escapeHtml(s.poi_category)}` : ""}</div></div>`
        : ""
      }
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.hunger"))}</label>
          <div class="value need-val need-hunger">${fmtNeed(s.needs?.hunger)}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.energy"))}</label>
          <div class="value need-val need-energy">${fmtNeed(s.needs?.energy)}</div>
        </div>
        <div class="detail-card">
          <label>${escapeHtml(_t("drawer.stress"))}</label>
          <div class="value need-val need-stress">${fmtNeed(s.needs?.stress)}</div>
        </div>
        ${s.lng != null
        ? `<div class="detail-card full"><label>${escapeHtml(_t("drawer.coords"))}</label><div class="value mono">${s.lat?.toFixed(5)}, ${s.lng?.toFixed(5)}</div></div>`
        : ""
      }
        ${s.artifact_file
        ? `<div class="detail-card full"><label>${escapeHtml(_t("drawer.artifactFile"))}</label><div class="value mono">${escapeHtml(s.artifact_file)}</div></div>`
        : ""
      }
      </div>
      ${s.reason
        ? `<div class="reason-block">
            <div class="drawer-section-head">
              <strong>${escapeHtml(_t("drawer.agentReason"))}</strong>
              ${isViDash ? renderLangSwitchHtml("reason", drawerReasonLang) : ""}
            </div>
            ${reasonBodyHtml}
          </div>`
        : ""
      }
      ${primary?.raw_response || primary?.raw_text
        ? `<div class="q-section"><h3>${escapeHtml(_t("drawer.rawResponse"))}</h3><pre class="q-prompt">${escapeHtml(primary.raw_response || primary.raw_text)}</pre></div>`
        : ""
      }
      ${prompt
        ? `<div class="q-section">
            <div class="drawer-section-head">
              <h3>${escapeHtml(_t("drawer.promptExcerpt"))}</h3>
              ${translatedPrompt ? renderLangSwitchHtml("prompt", drawerPromptLang) : ""}
            </div>
            <div class="q-prompt">${escapeHtml(promptShown.slice(0, 1400))}${promptShown.length > 1400 ? "…" : ""}</div>
          </div>`
        : ""
      }
      <details class="raw-json">
        <summary>${escapeHtml(_t("drawer.rawJson"))}</summary>
        <pre>${escapeHtml(JSON.stringify(q, null, 2))}</pre>
      </details>
    `;

    body.querySelectorAll(".inline-lang-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.target;
        const lang = btn.dataset.lang;
        if (target === "reason" && lang !== drawerReasonLang) {
          drawerReasonLang = lang;
          openDrawer(slot);
        } else if (target === "prompt" && lang !== drawerPromptLang) {
          drawerPromptLang = lang;
          openDrawer(slot);
        }
      });
    });

    if (showViReason && !cachedReason) {
      const sourceText = s.reason;
      requestViTranslation(sourceText)
        .then((res) => {
          reasonTranslations.set(sourceText, res);
          if (
            drawerMode !== "slot" ||
            selectedSlot !== slot ||
            drawerReasonLang !== "vi" ||
            drawer.classList.contains("hidden")
          ) {
            return;
          }
          const textEl = $("drawer-reason-text");
          const statusEl = $("drawer-reason-status");
          if (textEl) {
            textEl.textContent = res.translated;
            textEl.classList.remove("reason-fallback");
          }
          if (statusEl) {
            const badgeKey = res.cached ? "drawer.translateCached" : "drawer.translateLive";
            statusEl.textContent = _t(badgeKey, { model: res.model });
            statusEl.classList.remove("error");
          }
        })
        .catch((err) => {
          if (
            drawerMode !== "slot" ||
            selectedSlot !== slot ||
            drawerReasonLang !== "vi" ||
            drawer.classList.contains("hidden")
          ) {
            return;
          }
          const statusEl = $("drawer-reason-status");
          if (statusEl) {
            statusEl.textContent = _t("drawer.translateError", { err: err.message });
            statusEl.classList.add("error");
          }
        });
    }
  }

  drawer.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  const drawer = $("detail-drawer");
  if (!drawer) return;
  drawerMode = null;
  drawer.classList.add("hidden");
  drawer.setAttribute("aria-hidden", "true");
}

function updateMilestoneUi(data) {
  const milestones = data.milestones || [];
  milestoneBySlot = new Map(milestones.map((m) => [m.slot, m]));

  const legend = $("milestone-legend");
  if (legend) {
    if (!milestones.length) {
      legend.innerHTML =
        `<span class="m-tag" style="cursor:default;opacity:0.7">${escapeHtml(_t("needs.milestonesEmpty"))}</span>`;
    } else {
      legend.innerHTML = milestones
        .map((m) => {
          const mLabel = window.DashboardI18n ? window.DashboardI18n.milestoneLabel(m.label) : m.label;
          return `<button type="button" class="m-tag" data-slot="${m.slot}" title="${escapeHtml(_t("timeline.milestoneTagTitle", { slot: m.slot + 1 }))}">
              <i class="m-dot" style="background:${m.color}"></i>${m.icon || ""} ${escapeHtml(mLabel)}
            </button>`;
        })
        .join("");
      legend.querySelectorAll(".m-tag[data-slot]").forEach((btn) => {
        btn.addEventListener("click", () => selectSlot(Number(btn.dataset.slot)));
      });
    }
  }

}

function paintTimelineMilestones(milestones) {
  const row = $("milestone-markers");
  if (!row) return;
  if (paintingMilestones) return;
  paintingMilestones = true;
  try {
    const rulerWidth =
      row.clientWidth || row.parentElement?.clientWidth || timelineInnerWidth() || 760;
    const laid = layoutMilestones(milestones, rulerWidth);
    const maxLane = laid.reduce((n, m) => Math.max(n, m.lane), 0);
    row.style.minHeight = `${Math.max(28, 12 + (maxLane + 1) * 26)}px`;
    row.innerHTML = "";
    laid.forEach((m) => {
      const mLabel = window.DashboardI18n ? window.DashboardI18n.milestoneLabel(m.label) : m.label;
      const el = document.createElement("button");
      el.type = "button";
      el.className = "marker";
      el.dataset.slot = String(m.slot);
      el.style.left = `${m.leftPct}%`;
      el.style.top = `${m.lane * 26}px`;
      el.style.borderColor = m.color;
      el.innerHTML = `<span class="marker-icon" aria-hidden="true">${escapeHtml(m.icon || "")}</span><span class="marker-text">${escapeHtml(mLabel)}</span>`;
      el.title = milestoneMarkerTitle(m);
      el.addEventListener("click", () => selectSlot(m.slot));
      row.appendChild(el);
    });
    paintMilestoneConnectors(laid);
  } finally {
    paintingMilestones = false;
  }
}

function timelineInnerWidth() {
  const inner = document.querySelector(".timeline-inner");
  return inner?.clientWidth || null;
}

function paintMilestoneConnectors(laid) {
  const svg = $("milestone-connectors");
  const inner = document.querySelector(".timeline-inner");
  const row = $("milestone-markers");
  const slotsRow = $("timeline-slot-columns");
  const ticks = document.querySelector(".tl-timeaxis .ticks");
  if (!svg || !inner || !row || !slotsRow || !laid.length) {
    if (svg) svg.innerHTML = "";
    return;
  }

  const innerBox = inner.getBoundingClientRect();
  const slotsBox = slotsRow.getBoundingClientRect();
  const w = innerBox.width;
  const h = innerBox.height;
  if (w < 1 || h < 1) return;

  svg.setAttribute("width", String(w));
  svg.setAttribute("height", String(h));
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = "";

  const slotLeft = slotsBox.left - innerBox.left;
  const slotW = slotsBox.width;
  const ticksBox = ticks?.getBoundingClientRect();
  const yEnd = ticksBox
    ? ticksBox.top + ticksBox.height / 2 - innerBox.top
    : slotsBox.bottom - innerBox.top;
  const ySlotTop = slotsBox.top - innerBox.top;

  const NS = "http://www.w3.org/2000/svg";
  laid.forEach((m) => {
    const markerEl = row.querySelector(`.marker[data-slot="${m.slot}"]`);
    const xSlot = slotLeft + ((m.slot + 0.5) / 48) * slotW;
    const yStart = markerEl
      ? markerEl.getBoundingClientRect().bottom - innerBox.top + 2
      : row.getBoundingClientRect().bottom - innerBox.top;
    const color = m.color || "#94a3b8";
    const isSelected = selectedSlot === m.slot;

    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", String(xSlot));
    line.setAttribute("y1", String(yStart));
    line.setAttribute("x2", String(xSlot));
    line.setAttribute("y2", String(yEnd));
    line.setAttribute("stroke", color);
    line.setAttribute("stroke-width", isSelected ? "2" : "1.5");
    line.setAttribute("stroke-dasharray", isSelected ? "none" : "4 3");
    line.setAttribute("opacity", isSelected ? "0.95" : "0.65");
    svg.appendChild(line);

    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", String(xSlot));
    dot.setAttribute("cy", String(yEnd));
    dot.setAttribute("r", isSelected ? "4" : "3");
    dot.setAttribute("fill", color);
    dot.setAttribute("stroke", "#fff");
    dot.setAttribute("stroke-width", "1.5");
    svg.appendChild(dot);

    const slotDot = document.createElementNS(NS, "circle");
    slotDot.setAttribute("cx", String(xSlot));
    slotDot.setAttribute("cy", String(ySlotTop));
    slotDot.setAttribute("r", "2.5");
    slotDot.setAttribute("fill", color);
    slotDot.setAttribute("opacity", "0.85");
    svg.appendChild(slotDot);
  });
}

function computeStateFingerprint(data) {
  if (!data) return "";
  const meta = data.meta ? { ...data.meta } : {};
  delete meta.updated_at;
  return JSON.stringify({
    lang: window.DashboardI18n ? window.DashboardI18n.getLang() : "vi",
    meta,
    timing: data.timing,
    needs: data.needs,
    milestones: data.milestones,
    positions: data.positions,
    slots: data.slots,
    schedule: data.schedule,
    llm_stats: data.llm_stats,
    records: data.activity_log?.records || [],
    live: data.live,
  });
}

function render(data) {
  state = data;
  syncAgentSelect(data);
  updateRunStatus(data);
  updateKpiCards(data);
  renderTimelineLegends(data);
  renderSchedulePanel(data);

  const done = data.meta?.slots_done ?? 0;
  const progressSlot = done < 48 ? done : null;

  buildTimelineColumns(data, progressSlot);

  updateMilestoneUi(data);
  requestAnimationFrame(() => {
    if (state === data) paintTimelineMilestones(data.milestones || []);
  });

  updateLocationPanel(data);
  updateNeedsChart(data);
  updateEnvCalls(data);
}

function scheduleNextPoll(data) {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  const status = String(data?.timing?.run_status || "").toLowerCase();
  const isTerminal = status === "completed" || status === "completed_with_errors" || status === "failed";
  const delay = isTerminal ? IDLE_POLL_MS : POLL_MS;
  pollTimer = setTimeout(() => tick({ force: false }), delay);
}

async function tick({ force = false } = {}) {
  try {
    const data = await fetchState();
    const fp = computeStateFingerprint(data);
    if (!force && fp === lastStateFingerprint) {
      state = data;
      updateRunStatus(data);
    } else {
      lastStateFingerprint = fp;
      render(data);
    }
    scheduleNextPoll(data);
  } catch (err) {
    console.error(err);
    const text = $("status-text");
    const dot = $("status-dot");
    const aid = selectedAgentId;
    if (text) {
      text.textContent = state
        ? _t("nav.statusRefreshErr", { id: aid, err: err.message })
        : _t("nav.statusConnectErr", { err: err.message });
    }
    if (dot) dot.classList.toggle("idle", !state);
    scheduleNextPoll(state);
  }
}

function applyLanguageChange(nextLang) {
  if (!window.DashboardI18n) return;
  window.DashboardI18n.setLang(nextLang);
  lastStateFingerprint = null;
  lastActivityRenderKey = null;
  if (needsChart) {
    needsChart.data.datasets[0].label = _t("needs.hunger");
    needsChart.data.datasets[1].label = _t("needs.energy");
    needsChart.data.datasets[2].label = _t("needs.stress");
    needsChart.update("none");
  }
  const fromEl = $("activity-slot-from");
  if (fromEl) delete fromEl.dataset.initialized;
  window.GeoMapView?.refreshLanguage?.();
  setMapView(mapViewMode);
  if (state) {
    render(state);
    const drawer = $("detail-drawer");
    if (drawer && !drawer.classList.contains("hidden")) {
      if (drawerMode === "cost") {
        openCostDrawer();
      } else if (drawerMode === "slot" && selectedSlot != null) {
        openDrawer(selectedSlot);
      }
    }
  }
}

function bindUi() {
  $("lang-select")?.addEventListener("change", (e) => {
    applyLanguageChange(e.target.value);
  });

  $("manual-refresh-btn")?.addEventListener("click", () => {
    tick({ force: true });
  });

  const costCard = $("kpi-cost-card");
  if (costCard) {
    costCard.addEventListener("click", () => openCostDrawer());
    costCard.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openCostDrawer();
      }
    });
  }

  $("drawer-close")?.addEventListener("click", closeDrawer);
  $("drawer-backdrop")?.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  $("agent-select")?.addEventListener("change", (e) => {
    const next = Number(e.target.value);
    if (!Number.isInteger(next) || next === selectedAgentId) return;
    selectedAgentId = next;
    storeAgentId(next);
    selectedSlot = null;
    schematicEndSlot = null;
    schematicFollowLive = true;
    lastSlotsDone = -1;
    lastStateFingerprint = null;
    lastActivityRenderKey = null;
    stopSchematicPlay();
    closeDrawer();
    tick({ force: true });
  });

  $("schematic-play")?.addEventListener("click", toggleSchematicPlay);
  $("schematic-step-back")?.addEventListener("click", () => stepSchematic(-1));
  $("schematic-step-fwd")?.addEventListener("click", () => stepSchematic(1));
  $("schematic-slider")?.addEventListener("input", (e) => {
    schematicFollowLive = false;
    schematicEndSlot = Number(e.target.value);
    if (state) updateLocationPanel(state);
  });
  $("schematic-follow-live")?.addEventListener("change", (e) => {
    schematicFollowLive = e.target.checked;
    if (schematicFollowLive) schematicEndSlot = null;
    if (state) updateLocationPanel(state);
  });

  document.querySelectorAll(".view-tab[data-map-view]").forEach((btn) => {
    btn.addEventListener("click", () => setMapView(btn.dataset.mapView));
  });

  document.querySelectorAll(".env-btn[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => applyEnvFilterPreset(btn.dataset.preset));
  });
  $("activity-search")?.addEventListener("input", (e) => {
    activitySearchQuery = String(e.target.value || "").trim().toLowerCase();
    if (activitySearchQuery) {
      envFilterPreset = "custom";
      document.querySelectorAll(".env-btn[data-preset]").forEach((btn) => {
        btn.classList.remove("active");
      });
    }
    if (state) updateEnvCalls(state);
  });
  $("activity-slot-from")?.addEventListener("change", onActivitySlotFilterChange);
  $("activity-slot-to")?.addEventListener("change", onActivitySlotFilterChange);
  $("activity-slot-use-selected")?.addEventListener("click", applyActivitySlotFilterFromSelection);
  $("activity-slot-clear")?.addEventListener("click", clearActivitySlotFilter);
  $("activity-slot-follow")?.addEventListener("change", (e) => {
    activitySlotFollowSelection = e.target.checked;
    if (activitySlotFollowSelection && selectedSlot != null) {
      setActivitySlotFilter(selectedSlot, selectedSlot, { follow: true });
    }
  });
  applyEnvFilterPreset(envFilterPreset);
}

function onResize() {
  needsChart?.resize();
  if (state) paintTimelineMilestones(state.milestones || []);
}

function start() {
  window.DashboardI18n?.applyStatic();
  initSchematic();
  buildTimeAxis();
  initNeedsChart();
  window.GeoMapView?.setSelectHandler((slot) => selectSlot(slot));
  setMapView(mapViewMode);
  bindUi();
  tick({ force: true });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(onResize, 150);
  });
}

start();
