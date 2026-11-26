import { fetchCustom } from "../components/fetch";

const API_BASE = "/api/v1/urban-sim";

export interface UrbanSimRun {
    id: string;
    project_id: string;
    run_number: number;
    run_dir: string;
    status: string;
    pause_reason: string | null;
    pid: number | null;
    step_count: number;
    total_steps: number;
    active_agent_count: number;
    pilot_mode: boolean;
    router_type: string;
    execution_phase?: "PRE_QUIZ" | "SIMULATING" | "POST_DEBRIEF" | "POST_QUIZ" | "DONE" | string;
    current_sim_time?: string | null;
    total_tokens: number;
    total_cost_usd: number;
    error_message: string | null;
    started_at: string | null;
    paused_at: string | null;
    ended_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface UrbanSimProjectStats {
    total_personas: number;
    active_personas: number;
    pilot_personas: number;
    bql_count: number;
    resident_count: number;
    bql_credentials_configured: number;
    zones_count: number;
    atlas_key_configured: boolean;
    atlas_verified_at: string | null;
}

export interface UrbanSimProjectSummary {
    id: string;
    slug: string;
    name: string;
    description: string;
    default_portal_url: string;
    router_type: "react" | "codegen";
    num_steps: number;
    tick_seconds: number;
    start_time_iso: string;
    max_react_turns: number;
    max_cost_usd_per_run: number;
    pilot_mode: boolean;
    zone_map_image_rel: string | null;
    has_zone_map_image: boolean;
    llm_config_id?: string | null;
    enable_sociological_debrief?: boolean;
    enable_competency_prepost_quiz?: boolean;
    competency_rubric_json?: string | null;
    stats: UrbanSimProjectStats;
    latest_run: UrbanSimRun | null;
    created_at: string;
    updated_at: string;
}

export interface UrbanSimPersona {
    id: string;
    project_id: string;
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    department: string;
    group_type: "BQL" | "RESIDENT";
    software_access_enabled: boolean;
    is_pilot_member: boolean;
    is_active: boolean;
    home_zone: string;
    domain_knowledge_prompt: string;
    initial_tasks: string[];
    portal_url: string | null;
    login_username: string | null;
    has_password: boolean;
    password_masked: string;
    account_configured: boolean;
    created_at: string;
    updated_at: string;
}

export interface UrbanSimAtlasConfig {
    project_id: string;
    enabled: boolean;
    atlas_api_url: string;
    has_api_key: boolean;
    api_key_masked: string;
    actor_persona: "END_USER" | "ADMIN" | "OPERATOR";
    source_mode: "FEDERATED_AUTO" | "LOCAL_ONLY" | "HYBRID";
    attach_screenshot_on_ask: boolean;
    quota_per_min: number;
    max_asks_per_tick: number;
    guardrail_mode: "SAFE_WRITE" | "READ_ONLY" | "FULL_RBAC";
    record_prefix: string;
    blocked_keywords: string[];
    last_verified_at: string | null;
    last_verified_project_id: string | null;
    last_verified_project_name: string | null;
    last_verified_scopes: string[];
    updated_at: string | null;
}

export interface UrbanSimZone {
    id: string;
    project_id: string;
    zone_key: string;
    name: string;
    zone_type: "LOBBY" | "OFFICE" | "TECHNICAL" | "SECURITY" | "TOWER";
    description: string;
    sort_order: number;
}

export interface PreflightReport {
    llm_api_key_present: boolean;
    effective_llm_model?: string;
    effective_coder_model?: string;
    effective_llm_thinking?: string;
    active_selected_count: number;
    bql_selected_count: number;
    bql_credentials_ready: number;
    bql_missing_credentials: Array<{
        agent_id: number;
        full_name: string;
        role_title: string;
    }>;
    atlas_enabled: boolean;
    atlas_api_key_present: boolean;
    atlas_verified: boolean;
    ready_for_l1: boolean;
    ready_for_l2_sandbox: boolean;
    warnings: string[];
}

export interface AtlasTestResult {
    success: boolean;
    ok: boolean;
    status_code?: number;
    error?: string;
    bound_project_id?: string;
    project_name?: string;
    scopes?: string[];
    isolation_mode?: string;
    verified_at?: string;
}

export interface TokenTotals {
    calls: number;
    input: number;
    cached_input: number;
    output: number;
}

export interface ModelCostBreakdown extends TokenTotals {
    cost_usd: number;
    cost_vnd: number;
    saved_by_cache_usd: number;
}

export interface LlmCostStats {
    available: boolean;
    scope?: string;
    step_count?: number;
    usd_to_vnd: number;
    cost_usd: number;
    cost_vnd: number;
    saved_by_cache_usd: number;
    saved_by_cache_vnd: number;
    cache_hit_rate: number;
    totals: TokenTotals;
    models: Record<string, ModelCostBreakdown>;
    agent_side?: { totals?: TokenTotals; models?: Record<string, TokenTotals> };
    router_side?: { totals?: TokenTotals; models?: Record<string, TokenTotals> };
    max_cost_usd_per_run?: number;
    budget_pct?: number;
}

export interface UrbanIncident {
    incident_id: string;
    reporter_id: number;
    reporter_name: string;
    zone_key: string;
    title: string;
    description: string;
    priority: string;
    status: string;
    assigned_to_id: number | null;
    resolution_note: string;
    created_at: string;
    updated_at: string;
}

export interface SimClockInfo {
    current_sim_time: string | null;
    start_sim_time: string | null;
    end_sim_time: string | null;
    tick_seconds: number;
    elapsed_seconds?: number;
    time_band: string | null;
    time_band_label_vi: string | null;
    period_vi: string | null;
    is_daytime: boolean | null;
    day_night_label_vi: string | null;
    day_index: number;
    total_sim_days?: number;
}

export interface AgentStatusRow {
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    department: string;
    group_type: "BQL" | "RESIDENT";
    software_access_enabled: boolean;
    current_zone: string;
    current_url: string;
    web_actions_count: number;
    blocked_actions_count: number;
    atlas_asks_count: number;
    bot_session_id: string | null;
    latest_screenshot: string | null;
    latest_screenshot_status?: "READY" | "LOADING_TIMEOUT" | "LOADING_SPLASH_SUSPECTED" | "MISSING" | null;
    latest_screenshot_bytes?: number | null;
    total_actions_count?: number;
    comm_actions_count?: number;
    incident_actions_count?: number;
    web_failed_count?: number;
    atlas_failed_count?: number;
    unread_messages_count?: number;
    received_messages_count?: number;
    incidents_related_count?: number;
    incidents_open_count?: number;
    episodes_count?: number;
    todos_total?: number;
    todos_completed?: number;
    notes_count?: number;
    last_action?: string | null;
    last_action_stream?: string | null;
    last_action_summary?: string | null;
    last_action_sim_time?: string | null;
    last_action_ok?: boolean | null;
}

export interface ZoneTopologyCard {
    zone_key: string;
    name: string;
    zone_type: string;
    description: string;
    agents_here: Array<{
        agent_id: number;
        full_name: string;
        role_title: string;
        group_type: string;
    }>;
    open_incidents: UrbanIncident[];
}

export interface UrbanSimRunState {
    project: {
        id: string;
        name: string;
        has_zone_map_image: boolean;
        max_cost_usd_per_run: number;
    };
    run: UrbanSimRun;
    sim_clock?: SimClockInfo;
    cost: LlmCostStats;
    stream_counts: {
        COMM: number;
        WEB: number;
        ATLAS: number;
        INCIDENT: number;
    };
    latest_seq: number;
    zones: ZoneTopologyCard[];
    incidents: UrbanIncident[];
    agent_statuses: AgentStatusRow[];
}

export interface UrbanEventItem {
    seq: number;
    stream: "COMM" | "WEB" | "ATLAS" | "INCIDENT" | string;
    agent_id: number | null;
    agent_name: string;
    role_title: string;
    action: string;
    summary: string;
    ok: boolean;
    sim_time: string | null;
    wall_time: string;
    screenshot_file: string | null;
    screenshot_status?: "READY" | "LOADING_TIMEOUT" | "LOADING_SPLASH_SUSPECTED" | "MISSING" | null;
    screenshot_bytes?: number | null;
    details: Record<string, unknown>;
}

export interface PersonaMemoryEpisode {
    id: string;
    step_index: number;
    time: string | null;
    type: string;
    type_label: string;
    importance: number | null;
    keywords: string[];
    text: string;
}

export interface PersonaWorkspaceAction {
    action: string;
    path: string;
    summary_vi: string;
}

export interface PersonaTechnicalTool {
    action: string;
    label_vi: string;
    ok: boolean;
    args: unknown;
    observation_preview: string;
}

export interface PersonaTechnicalTurn {
    turn: number;
    thought: string | null;
    actions: PersonaTechnicalTool[];
}

export interface PersonaTurnThought {
    turn: number;
    thought: string;
    action_labels: string[];
}

export interface PersonaTimelineStep {
    step_index: number;
    sim_time: string | null;
    zone: string | null;
    time_band: string | null;
    unread_messages: number | null;
    open_incidents_owned: number | null;
    step_summary: string;
    end_reason: string;
    thoughts: string[];
    turn_thoughts?: PersonaTurnThought[];
    episodes: PersonaMemoryEpisode[];
    workspace_actions: PersonaWorkspaceAction[];
    web_events: UrbanEventItem[];
    atlas_events: UrbanEventItem[];
    comm_events: UrbanEventItem[];
    related_incidents: UrbanIncident[];
    technical_turns: PersonaTechnicalTurn[];
    technical_turn_count: number;
    technical_tool_count: number;
}

export interface PersonaNoteFile {
    path: string;
    size_bytes: number;
    content: string;
}

export interface PersonaTodoItem {
    id: string;
    title: string;
    kind?: string;
    status: string;
    priority?: number;
    notes?: string;
}

export interface PersonaTimelineResponse {
    agent: {
        agent_id: number;
        full_name: string;
        role_code: string;
        role_title: string;
        department: string;
        group_type: "BQL" | "RESIDENT";
        home_zone: string;
        software_access_enabled: boolean;
    };
    summary: {
        total_steps: number;
        thoughts_steps_count?: number;
        episodes_count: number;
        web_events_count: number;
        loading_screenshots_count?: number;
        atlas_events_count: number;
        comm_events_count: number;
        related_incidents_count: number;
        notes_count: number;
        todos_count: number;
    };
    steps: PersonaTimelineStep[];
    memory_md: string;
    todos: PersonaTodoItem[];
    notes: PersonaNoteFile[];
    all_related_incidents: UrbanIncident[];
}

export interface NullableMetric {
    value: number | null;
    status: string;
}

export interface AxisCohortStat {
    mean: number | null;
    valid_n: number;
    eligible_bql_n: number;
}

export interface AgentFrictionTag {
    stage: string;
    label: string;
    count: number;
    sample_seqs: number[];
}

export interface AgentCompetencyRow {
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    department: string;
    interaction_mode: "write_ops" | "oversight" | string;
    miller_level: "M0" | "M1" | "M2" | "M3" | "M4";
    miller_gate_reasons: string[];
    flags: string[];
    safety_violation: boolean;
    blocked_by_readonly_policy: number;
    blocked_by_unsafe_action: number;
    metrics: {
        effectiveness: NullableMetric;
        lostness_l_first: NullableMetric;
        cskh_conversion: NullableMetric;
        normalized_change_c: NullableMetric;
    };
    diagnostic_index: number | null;
    non_compensatory_warning: string | null;
    quiz: {
        pre_score_pct: number | null;
        post_score_pct: number | null;
        pre_epistemic_honesty_rate: number | null;
        partial_data: boolean;
    };
    activity: {
        login_ok: number;
        succeeded_web_ops: number;
        non_login_web_actions: number;
        failed_web_attempts: number;
        write_ops_count: number;
        unique_target_modules: string[];
        atlas_asks_total: number;
        atlas_asks_ok: number;
        atlas_converted: number;
        incident_manage_count: number;
        comm_count: number;
        thought_count: number;
    };
    retention: {
        has_retention: boolean;
        notes_files_count: number;
        notes_bytes: number;
        memory_md_bytes: number;
        episodes_count: number;
    };
    friction_tags: AgentFrictionTag[];
    debrief?: AgentDebriefData | null;
}

export interface DebriefEvidenceAnchor {
    seq: number;
    stream: string;
    action: string;
    ok: boolean;
    url: string | null;
    screenshot_path: string | null;
    summary: string;
}

export interface DebriefIncidentItem {
    incident_idx: number;
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    context_task: string;
    screen_or_url: string;
    what_happened: string;
    cskh_outcome: string;
    root_cause_category: "KNOWLEDGE_GAP" | "SOFTWARE_UX_BUG" | "WORKFLOW_FRICTION" | string;
    severity: "S1_CRITICAL" | "S2_HIGH" | "S3_MEDIUM" | string;
    suggestion: string;
    grounding_status: "VERIFIED_BY_LOG" | "UNGROUNDED_SELF_REPORT" | string;
    evidence_anchors: DebriefEvidenceAnchor[];
}

export interface AgentDebriefData {
    umux_capabilities: number | null;
    umux_ease: number | null;
    umux_lite_score: number | null;
    seq_ease: number | null;
    workload_effort: number | null;
    workload_frustration: number | null;
    workload_effort_100: number | null;
    workload_frustration_100: number | null;
    workload_subset_100: number | null;
    cskh_accuracy: number | null;
    cskh_helpfulness: number | null;
    cskh_quality: number | null;
    cskh_status: "VALID" | "NO_CSKH_ASK" | "CSKH_ALL_FAILED" | string;
    bias_flags: string[];
    incidents: DebriefIncidentItem[];
    reflection_vi: string;
    parse_failed: boolean;
}

export interface SociologicalDebriefSummary {
    available: boolean;
    status: "NOT_AVAILABLE" | "PARTIAL" | "COMPLETE" | string;
    respondents_n: number;
    eligible_bql_n: number;
    parse_failures_count: number;
    umux_lite_mean: number | null;
    seq_mean: number | null;
    workload_effort_mean_100: number | null;
    workload_frustration_mean_100: number | null;
    workload_subset_mean_100: number | null;
    cskh_quality_mean: number | null;
    cskh_valid_n: number;
    cskh_all_failed_n: number;
    bias_warnings_count: number;
    cit_total_count: number;
    cit_verified_count: number;
    actionable_backlog: {
        knowledge_gaps: DebriefIncidentItem[];
        software_ux_bugs: DebriefIncidentItem[];
        workflow_frictions: DebriefIncidentItem[];
    };
}

export interface ExcludedAgentInfo {
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    group_type: string;
    exclude_reason: string;
}

export interface CompetencyReport {
    schema_version: string;
    generated_at: string;
    participant_source: string;
    guardrail_mode: string;
    latest_seq: number;
    run_models: string[];
    run_model_families: string[];
    methodology: {
        framework: string;
        references: string[];
    };
    cohort_summary: {
        eligible_bql_n: number;
        excluded_count: number;
        miller_distribution: Record<"M0" | "M1" | "M2" | "M3" | "M4", number>;
        safety_violations_count: number;
        retention_active_count: number;
        axes: {
            effectiveness: AxisCohortStat;
            lostness_l_first: AxisCohortStat;
            cskh_conversion: AxisCohortStat;
            normalized_change_c: AxisCohortStat;
        };
        quiz_summary: {
            available: boolean;
            status: string;
            assessment_mode: string;
            partial_data: boolean;
            pre_avg_pct: AxisCohortStat;
            post_avg_pct: AxisCohortStat;
            epistemic_honesty_avg: AxisCohortStat;
        };
        sociological_debrief?: SociologicalDebriefSummary;
    };
    sociological_debrief?: SociologicalDebriefSummary;
    agents: AgentCompetencyRow[];
    excluded_agents: ExcludedAgentInfo[];
}

export interface AiAuditStatusInfo {
    run_id?: string;
    status: "IDLE" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "INTERRUPTED_ON_RESTART" | string;
    version?: number;
    latest_version?: number | null;
    result_file?: string | null;
    judge_config_id?: string;
    judge_config_name?: string;
    judge_provider?: string;
    judge_model?: string;
    judge_model_family?: string;
    run_models?: string[];
    run_model_families?: string[];
    same_family_bias_warning?: boolean;
    as_of_run_status?: string;
    as_of_step_count?: number;
    as_of_latest_seq?: number;
    agents_total?: number;
    agents_completed?: number;
    error?: string | null;
    started_at?: string;
    updated_at?: string;
    completed_at?: string;
}

export interface AiAuditCitation {
    seq: number | null;
    step_index: number | null;
    quote: string;
    verified: boolean;
    flag: string | null;
}

export interface AiAuditAgentItem {
    agent_id: number;
    full_name: string;
    role_code: string;
    role_title: string;
    miller_level: string;
    parse_ok: boolean;
    scores: {
        navigation_mastery: number | null;
        procedure_accuracy: number | null;
        help_seeking_efficiency: number | null;
        closed_loop_execution: number | null;
    };
    primary_root_cause: string;
    root_causes: Array<{ category: string; title: string; detail: string }>;
    summary_vi: string;
    recommendations: string[];
    citations: AiAuditCitation[];
    unverified_citations_count: number;
    flags: string[];
}

export interface AiAuditRootCauseEntry {
    agent_id: number;
    full_name: string;
    role_title: string;
    title: string;
    detail: string;
}

export interface AiAuditResult {
    schema_version: string;
    run_id: string;
    version: number;
    completed_at: string;
    judge: {
        config_id: string;
        config_name: string;
        provider: string;
        model: string;
        model_family: string;
    };
    run_models: string[];
    run_model_families: string[];
    same_family_bias_warning: boolean;
    snapshot_boundary: {
        as_of_run_status: string;
        as_of_step_count: number;
        as_of_latest_seq: number;
    };
    judge_usage: {
        calls: number;
        input_tokens: number;
        cached_input_tokens: number;
        output_tokens: number;
        cost_usd: number;
        note: string;
    };
    unverified_citations_total: number;
    root_cause_groups: {
        ui_ux_friction: AiAuditRootCauseEntry[];
        cskh_knowledge_gap: AiAuditRootCauseEntry[];
        agent_execution_error: AiAuditRootCauseEntry[];
    };
    agent_audits: AiAuditAgentItem[];
}

export interface AiAuditStateResponse {
    status: AiAuditStatusInfo;
    versions: number[];
    latest_version: number | null;
    selected_version: number | null;
    latest_result: AiAuditResult | null;
    selected_result: AiAuditResult | null;
}

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const headers: Record<string, string> = isFormData
        ? { ...(options.headers as Record<string, string> | undefined) }
        : { "Content-Type": "application/json", ...(options.headers as Record<string, string> | undefined) };

    const resp = await fetchCustom(url, { ...options, headers });
    const text = await resp.text();
    let parsed: Record<string, unknown> = {};
    if (text) {
        try {
            parsed = JSON.parse(text) as Record<string, unknown>;
        } catch {
            parsed = {};
        }
    }
    if (!resp.ok) {
        const msg =
            (typeof parsed.detail === "string" && parsed.detail) ||
            (typeof parsed.error === "string" && parsed.error) ||
            `HTTP ${resp.status}: Yêu cầu không thành công`;
        throw new Error(msg);
    }
    return parsed as unknown as T;
}

export function getScreenshotUrl(projectId: string, runId: string, filename: string): string {
    return `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/screenshots/${encodeURIComponent(filename)}`;
}

export function getZoneMapImageUrl(projectId: string, versionKey?: string): string {
    const base = `${API_BASE}/projects/${encodeURIComponent(projectId)}/zones/map-image`;
    return versionKey ? `${base}?v=${encodeURIComponent(versionKey)}` : base;
}

export interface RubricRoleRule {
    role_code: string;
    label: string;
    interaction_mode: "write_ops" | "oversight";
    target_url_patterns: string[];
    expected_min_steps: number;
    min_actions_for_lostness: number;
    expected_target_modules_for_m3: number;
}

export interface RubricQuizQuestion {
    id: string;
    topic: string;
    skill_domain: string;
    prompt_stem: string;
    options: {
        OPT_A: string;
        OPT_B: string;
        OPT_C: string;
        OPT_D: string;
        [key: string]: string;
    };
    correct_choice: "OPT_A" | "OPT_B" | "OPT_C" | "OPT_D";
}

export interface CompetencyRubricData {
    version: string;
    roles: Record<string, RubricRoleRule>;
    quiz_questions: RubricQuizQuestion[];
}

export interface LlmConfigListItem {
    id: string;
    name: string;
    description?: string;
    config?: Array<{
        provider?: string;
        model?: string;
        coder_model?: string;
        thinking?: string;
        reasoning_effort?: string;
        has_api_key?: boolean;
    }>;
}

export const urbanSimApi = {
    listLlmConfigs: async (): Promise<LlmConfigListItem[]> => {
        const res = await requestJson<{ data?: LlmConfigListItem[] }>("/api/llm-configs");
        return res.data || [];
    },
    listProjects: async (): Promise<UrbanSimProjectSummary[]> => {
        const res = await requestJson<{ items: UrbanSimProjectSummary[] }>(`${API_BASE}/projects`);
        return res.items || [];
    },
    createProject: async (payload: Partial<UrbanSimProjectSummary> & { slug: string; name: string; seed_mulberrylane_template?: boolean }): Promise<UrbanSimProjectSummary> => {
        const res = await requestJson<{ project: UrbanSimProjectSummary }>(`${API_BASE}/projects`, {
            method: "POST",
            body: JSON.stringify(payload),
        });
        return res.project;
    },
    getProject: async (projectId: string): Promise<UrbanSimProjectSummary> => {
        const res = await requestJson<{ project: UrbanSimProjectSummary }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}`);
        return res.project;
    },
    updateProject: async (projectId: string, payload: Partial<UrbanSimProjectSummary>): Promise<UrbanSimProjectSummary> => {
        const res = await requestJson<{ project: UrbanSimProjectSummary }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        });
        return res.project;
    },
    getPreflight: async (projectId: string): Promise<PreflightReport> => {
        const res = await requestJson<{ preflight: PreflightReport }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/preflight`);
        return res.preflight;
    },
    listPersonas: async (projectId: string): Promise<UrbanSimPersona[]> => {
        const res = await requestJson<{ items: UrbanSimPersona[] }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/personas`);
        return res.items || [];
    },
    createPersona: async (projectId: string, payload: Record<string, unknown>): Promise<UrbanSimPersona> => {
        const res = await requestJson<{ persona: UrbanSimPersona }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/personas`, {
            method: "POST",
            body: JSON.stringify(payload),
        });
        return res.persona;
    },
    updatePersona: async (projectId: string, personaId: string, payload: Record<string, unknown>): Promise<UrbanSimPersona> => {
        const res = await requestJson<{ persona: UrbanSimPersona }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/personas/${encodeURIComponent(personaId)}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        });
        return res.persona;
    },
    deletePersona: async (projectId: string, personaId: string): Promise<void> => {
        await requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/personas/${encodeURIComponent(personaId)}`, {
            method: "DELETE",
        });
    },
    getAtlasConfig: async (projectId: string): Promise<UrbanSimAtlasConfig> => {
        const res = await requestJson<{ atlas: UrbanSimAtlasConfig }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/atlas`);
        return res.atlas;
    },
    updateAtlasConfig: async (projectId: string, payload: Record<string, unknown>): Promise<UrbanSimAtlasConfig> => {
        const res = await requestJson<{ atlas: UrbanSimAtlasConfig }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/atlas`, {
            method: "PUT",
            body: JSON.stringify(payload),
        });
        return res.atlas;
    },
    testAtlasConnection: async (projectId: string, payload?: { atlas_api_url?: string; atlas_api_key?: string }): Promise<AtlasTestResult> => {
        return requestJson<AtlasTestResult>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/atlas/test-connection`, {
            method: "POST",
            body: JSON.stringify(payload || {}),
        });
    },
    listZones: async (projectId: string): Promise<{ has_zone_map_image: boolean; items: UrbanSimZone[] }> => {
        return requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/zones`);
    },
    uploadZoneMapImage: async (projectId: string, file: File): Promise<{ filename: string; size_bytes: number }> => {
        const form = new FormData();
        form.append("file", file);
        return requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/zones/map-image`, {
            method: "POST",
            body: form,
        });
    },
    deleteZoneMapImage: async (projectId: string): Promise<void> => {
        await requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/zones/map-image`, {
            method: "DELETE",
        });
    },
    listRuns: async (projectId: string): Promise<UrbanSimRun[]> => {
        const res = await requestJson<{ items: UrbanSimRun[] }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs`);
        return res.items || [];
    },
    startRun: async (projectId: string): Promise<UrbanSimRun> => {
        const res = await requestJson<{ run: UrbanSimRun }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/start`, {
            method: "POST",
        });
        return res.run;
    },
    pauseRun: async (projectId: string, runId: string): Promise<UrbanSimRun> => {
        const res = await requestJson<{ run: UrbanSimRun }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/pause`, {
            method: "POST",
        });
        return res.run;
    },
    resumeRun: async (projectId: string, runId: string): Promise<UrbanSimRun> => {
        const res = await requestJson<{ run: UrbanSimRun }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/resume`, {
            method: "POST",
        });
        return res.run;
    },
    restartRun: async (projectId: string): Promise<UrbanSimRun> => {
        const res = await requestJson<{ run: UrbanSimRun }>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/restart`, {
            method: "POST",
        });
        return res.run;
    },
    deleteRun: async (projectId: string, runId: string): Promise<void> => {
        await requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`, {
            method: "DELETE",
        });
    },
    getRunState: async (projectId: string, runId: string): Promise<UrbanSimRunState> => {
        return requestJson<UrbanSimRunState>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/state`);
    },
    getRunEvents: async (
        projectId: string,
        runId: string,
        params: { since_seq?: number; limit?: number; stream?: string; agent_id?: number | null } = {}
    ): Promise<{ items: UrbanEventItem[]; latest_seq: number; has_more: boolean }> => {
        const qs = new URLSearchParams();
        if (params.since_seq !== undefined) qs.set("since_seq", String(params.since_seq));
        if (params.limit !== undefined) qs.set("limit", String(params.limit));
        if (params.stream) qs.set("stream", params.stream);
        if (params.agent_id !== undefined && params.agent_id !== null) qs.set("agent_id", String(params.agent_id));
        return requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/events?${qs.toString()}`);
    },
    getRunLlmStats: async (projectId: string, runId: string): Promise<LlmCostStats> => {
        return requestJson<LlmCostStats>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/llm-stats`);
    },
    getAgentTimeline: async (
        projectId: string,
        runId: string,
        agentId: number
    ): Promise<PersonaTimelineResponse> => {
        return requestJson<PersonaTimelineResponse>(
            `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(String(agentId))}/timeline`
        );
    },
    sendSupportFeedback: async (
        projectId: string,
        runId: string,
        payload: { message_id: string; session_id?: string; vote: "LIKE" | "DISLIKE" | "NEUTRAL"; reason?: string }
    ): Promise<void> => {
        await requestJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/support-feedback`, {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    exportAtlasQa: async (
        projectId: string,
        runId: string,
        format: "markdown" | "json",
        agentId?: number | null
    ): Promise<{ blob: Blob; filename: string }> => {
        const qs = new URLSearchParams({ format });
        if (agentId !== undefined && agentId !== null) {
            qs.set("agent_id", String(agentId));
        }
        const url = `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/atlas-qa/export?${qs.toString()}`;
        const resp = await fetchCustom(url);
        if (!resp.ok) {
            const text = await resp.text();
            let detail = `HTTP ${resp.status}: Xuất dữ liệu CSKH thất bại`;
            if (text) {
                try {
                    const parsed = JSON.parse(text) as { detail?: string; error?: string };
                    detail = parsed.detail || parsed.error || detail;
                } catch {
                    // ignore non-JSON body
                }
            }
            throw new Error(detail);
        }
        const disposition = resp.headers.get("content-disposition") || "";
        const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
        const ext = format === "markdown" ? "md" : "json";
        const filename = match?.[1] ? decodeURIComponent(match[1]) : `cskh-qa-${runId}.${ext}`;
        const blob = await resp.blob();
        return { blob, filename };
    },
    getRunCompetency: async (projectId: string, runId: string): Promise<CompetencyReport> => {
        const res = await requestJson<{ data: CompetencyReport }>(
            `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/competency`
        );
        return res.data;
    },
    triggerCompetencyAiAudit: async (
        projectId: string,
        runId: string,
        judgeLlmConfigId: string
    ): Promise<AiAuditStatusInfo> => {
        const res = await requestJson<{ data: AiAuditStatusInfo }>(
            `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/competency/ai-audit`,
            {
                method: "POST",
                body: JSON.stringify({ judge_llm_config_id: judgeLlmConfigId }),
            }
        );
        return res.data;
    },
    getCompetencyAiAudit: async (
        projectId: string,
        runId: string,
        version?: number
    ): Promise<AiAuditStateResponse> => {
        const qs = version !== undefined ? `?version=${encodeURIComponent(String(version))}` : "";
        const res = await requestJson<{ data: AiAuditStateResponse }>(
            `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/competency/ai-audit${qs}`
        );
        return res.data;
    },
    exportRunCompetency: async (
        projectId: string,
        runId: string,
        format: "markdown" | "json",
        auditVersion?: number
    ): Promise<{ blob: Blob; filename: string }> => {
        const qs = new URLSearchParams({ format });
        if (auditVersion !== undefined) {
            qs.set("audit_version", String(auditVersion));
        }
        const url = `${API_BASE}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/competency/export?${qs.toString()}`;
        const resp = await fetchCustom(url);
        if (!resp.ok) {
            const text = await resp.text();
            let detail = `HTTP ${resp.status}: Xuất báo cáo năng lực thất bại`;
            if (text) {
                try {
                    const parsed = JSON.parse(text) as { detail?: string; error?: string };
                    detail = parsed.detail || parsed.error || detail;
                } catch {
                    // ignore non-JSON body
                }
            }
            throw new Error(detail);
        }
        const disposition = resp.headers.get("content-disposition") || "";
        const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
        const ext = format === "markdown" ? "md" : "json";
        const filename = match?.[1] ? decodeURIComponent(match[1]) : `competency-${runId}.${ext}`;
        const blob = await resp.blob();
        return { blob, filename };
    },
    getDefaultRubric: async (): Promise<CompetencyRubricData> => {
        const res = await requestJson<{ rubric: CompetencyRubricData }>(`${API_BASE}/rubric-default`);
        return res.rubric;
    },
    getScenarioBriefTemplate: async (): Promise<string> => {
        const res = await requestJson<{ template: string }>(`${API_BASE}/scenario-brief-template`);
        return res.template || "";
    },
    syncAccountingPersona: async (
        projectId: string
    ): Promise<{ created: boolean; persona: UrbanSimPersona }> => {
        return requestJson<{ created: boolean; persona: UrbanSimPersona }>(
            `${API_BASE}/projects/${encodeURIComponent(projectId)}/sync-accounting-persona`,
            { method: "POST" }
        );
    },
};
