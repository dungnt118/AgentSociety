import {
    AlertOutlined,
    CheckCircleOutlined,
    DownloadOutlined,
    ExperimentOutlined,
    HistoryOutlined,
    InfoCircleOutlined,
    RobotOutlined,
    SafetyOutlined,
    WarningOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Badge,
    Button,
    Card,
    Col,
    Collapse,
    Empty,
    Grid,
    Row,
    Select,
    Space,
    Spin,
    Table,
    Tag,
    Tooltip,
    Typography,
    message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useEffect, useMemo, useState } from "react";
import {
    AgentCompetencyRow,
    AgentStatusRow,
    AiAuditRootCauseEntry,
    AiAuditStateResponse,
    CompetencyReport,
    DebriefIncidentItem,
    LlmConfigListItem,
    NullableMetric,
    urbanSimApi,
} from "../../../services/urbanSimApi";

const { Text, Paragraph } = Typography;

interface CompetencyEvaluationTabProps {
    projectId: string;
    runId: string;
    active: boolean;
    agentFilter: number | "ALL";
    agents: AgentStatusRow[];
    onInspectAgent: (agentId: number) => void;
    onClearAgentFilter: () => void;
}

const MILLER_COLORS: Record<string, string> = {
    M0: "default",
    M1: "orange",
    M2: "blue",
    M3: "cyan",
    M4: "green",
};

const MILLER_LABELS_VI: Record<string, string> = {
    M0: "M0 · Chưa đăng nhập",
    M1: "M1 · Mới nhận diện",
    M2: "M2 · Đúng phân hệ",
    M3: "M3 · Thao tác được",
    M4: "M4 · Vận hành khép kín",
};

const METRIC_STATUS_HINTS_VI: Record<string, string> = {
    TARGET_NOT_REACHED: "Chưa mở đúng phân hệ mục tiêu theo vai trò",
    INCONCLUSIVE_LOW_ACTIVITY: "Chưa đủ mẫu thao tác web tối thiểu để kết luận độ lệch",
    DIRECT_SHORTCUT: "Đi thẳng vào phân hệ mục tiêu ngay từ đường dẫn trực tiếp",
    NO_WEB_ACTIVITY: "Chưa có thao tác Web nào",
    NO_CSKH_ASK: "Chưa hỏi CSKH Thần Nông",
    NO_QUIZ_DATA: "Run chưa bật Pre/Post Quiz hoặc thiếu bài nộp",
    CEILING_UNCHANGED: "Đạt điểm trần 100% ở cả Pre và Post",
    FLOOR_UNCHANGED: "Điểm 0% ở cả Pre và Post",
    UNCHANGED: "Điểm Post bằng Pre",
};

function inferModelFamilyClient(modelName?: string): string {
    const raw = String(modelName || "").trim().toLowerCase();
    if (!raw) return "unknown";
    const tokens = raw.split(/[/:\s]+/).filter(Boolean);
    for (let i = tokens.length - 1; i >= 0; i -= 1) {
        const t = tokens[i];
        if (t.includes("claude") || t === "anthropic") return "anthropic";
        if (/^(gpt|o1|o3|o4|chatgpt)/.test(t)) return "openai";
        if (t.includes("gemini") || t.includes("gemma")) return "google";
        if (t.includes("deepseek")) return "deepseek";
        if (t.includes("qwen") || t.includes("qwq")) return "qwen";
        if (t.includes("grok")) return "xai";
        if (t.includes("mistral") || t.includes("mixtral")) return "mistral";
        if (t.includes("llama")) return "meta";
    }
    return "unknown";
}

function renderNullablePercent(metric: NullableMetric | undefined): React.ReactNode {
    if (!metric || metric.value === null || Number.isNaN(metric.value)) {
        const hint = METRIC_STATUS_HINTS_VI[metric?.status || ""] || metric?.status || "Chưa có dữ liệu";
        return (
            <Tooltip title={hint}>
                <Tag color="default">N/A</Tag>
            </Tooltip>
        );
    }
    const pct = Math.round(metric.value * 1000) / 10;
    return <Text strong>{pct.toFixed(1)}%</Text>;
}

function renderLostness(metric: NullableMetric | undefined): React.ReactNode {
    if (!metric || metric.value === null || Number.isNaN(metric.value)) {
        const hint = METRIC_STATUS_HINTS_VI[metric?.status || ""] || metric?.status || "Chưa đủ dữ liệu";
        const tagLabel =
            metric?.status === "INCONCLUSIVE_LOW_ACTIVITY"
                ? "Thiếu mẫu"
                : metric?.status === "TARGET_NOT_REACHED"
                  ? "Chưa tới đích"
                  : "N/A";
        return (
            <Tooltip title={hint}>
                <Tag color={metric?.status === "TARGET_NOT_REACHED" ? "orange" : "default"}>
                    {tagLabel}
                </Tag>
            </Tooltip>
        );
    }
    const val = metric.value;
    const color = val <= 0.4 ? "green" : val <= 0.65 ? "orange" : "red";
    return (
        <Tooltip
            title={
                metric.status === "DIRECT_SHORTCUT"
                    ? "L_first = 0.000 (Đi thẳng tới phân hệ mục tiêu)"
                    : `Smith Lostness L_first = ${val.toFixed(3)} (<= 0.4 là điều hướng hiệu quả)`
            }
        >
            <Tag color={color}>{val.toFixed(3)}</Tag>
        </Tooltip>
    );
}

function renderNormalizedChange(metric: NullableMetric | undefined): React.ReactNode {
    if (!metric || metric.value === null || Number.isNaN(metric.value)) {
        const hint = METRIC_STATUS_HINTS_VI[metric?.status || ""] || metric?.status || "Chưa bật Quiz";
        return (
            <Tooltip title={hint}>
                <Tag color="default">N/A</Tag>
            </Tooltip>
        );
    }
    const val = metric.value;
    const color = val >= 0.5 ? "green" : val > 0 ? "blue" : val === 0 ? "default" : "red";
    return <Tag color={color}>{val >= 0 ? `+${val.toFixed(2)}` : val.toFixed(2)}</Tag>;
}

export const CompetencyEvaluationTab: React.FC<CompetencyEvaluationTabProps> = ({
    projectId,
    runId,
    active,
    agentFilter,
    agents,
    onInspectAgent,
    onClearAgentFilter,
}) => {
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;

    const requestKey = active && projectId && runId ? `${projectId}:${runId}` : "";
    const [loadedState, setLoadedState] = useState<{
        key: string;
        report: CompetencyReport | null;
        auditState: AiAuditStateResponse | null;
        llmConfigs: LlmConfigListItem[];
        error: string | null;
    }>({ key: "", report: null, auditState: null, llmConfigs: [], error: null });

    const [selectedJudgeId, setSelectedJudgeId] = useState<string>("");
    const [selectedAuditVersion, setSelectedAuditVersion] = useState<number | undefined>(undefined);
    const [triggerBusy, setTriggerBusy] = useState(false);
    const [exportingFormat, setExportingFormat] = useState<"markdown" | "json" | null>(null);

    const loading = Boolean(requestKey && loadedState.key !== requestKey);

    useEffect(() => {
        if (!requestKey || !projectId || !runId) return;
        let alive = true;
        async function runLoad() {
            try {
                const [reportRes, auditRes, llmsRes] = await Promise.all([
                    urbanSimApi.getRunCompetency(projectId, runId),
                    urbanSimApi.getCompetencyAiAudit(projectId, runId, selectedAuditVersion),
                    urbanSimApi.listLlmConfigs().catch(() => [] as LlmConfigListItem[]),
                ]);
                if (!alive) return;
                setLoadedState({
                    key: requestKey,
                    report: reportRes,
                    auditState: auditRes,
                    llmConfigs: llmsRes,
                    error: null,
                });
                setSelectedJudgeId((prev) => {
                    if (prev) return prev;
                    const fromStatus = auditRes?.status?.judge_config_id;
                    if (fromStatus) return fromStatus;
                    return llmsRes[0]?.id || "";
                });
            } catch (err) {
                if (!alive) return;
                setLoadedState({
                    key: requestKey,
                    report: null,
                    auditState: null,
                    llmConfigs: [],
                    error: err instanceof Error ? err.message : "Không tải được báo cáo đánh giá năng lực",
                });
            }
        }
        void runLoad();
        return () => {
            alive = false;
        };
    }, [requestKey, projectId, runId, selectedAuditVersion]);

    const auditStatusStr = loadedState.auditState?.status?.status || "IDLE";
    const isAuditPolling = Boolean(
        active && (auditStatusStr === "QUEUED" || auditStatusStr === "RUNNING")
    );

    useEffect(() => {
        if (!isAuditPolling || !projectId || !runId) return;
        const timer = window.setInterval(async () => {
            try {
                const updated = await urbanSimApi.getCompetencyAiAudit(
                    projectId,
                    runId,
                    selectedAuditVersion
                );
                setLoadedState((prev) => ({ ...prev, auditState: updated }));
            } catch {
                // ignore transient poll error
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [isAuditPolling, projectId, runId, selectedAuditVersion]);

    const report = loadedState.key === requestKey ? loadedState.report : null;
    const auditState = loadedState.key === requestKey ? loadedState.auditState : null;
    const llmConfigs = useMemo(
        () => (loadedState.key === requestKey ? loadedState.llmConfigs : []),
        [loadedState.key, loadedState.llmConfigs, requestKey]
    );
    const loadError = loadedState.key === requestKey ? loadedState.error : null;

    const selectedJudgeInfo = useMemo(() => {
        const found = llmConfigs.find((item) => item.id === selectedJudgeId);
        const first = found?.config?.[0];
        const modelName = first?.model || "";
        const family = inferModelFamilyClient(modelName);
        const runFamilies = report?.run_model_families || [];
        const sameFamilyBias = Boolean(
            found && family !== "unknown" && runFamilies.includes(family)
        );
        return { found, modelName, family, sameFamilyBias };
    }, [llmConfigs, selectedJudgeId, report]);

    const selectedAgentObj = useMemo(() => {
        if (agentFilter === "ALL") return null;
        return agents.find((a) => a.agent_id === agentFilter) || null;
    }, [agentFilter, agents]);

    const isResidentSelected = Boolean(
        selectedAgentObj && selectedAgentObj.group_type !== "BQL"
    );

    const visibleRows = useMemo(() => {
        const list = report?.agents || [];
        if (agentFilter === "ALL") return list;
        if (isResidentSelected) return [];
        return list.filter((r) => r.agent_id === agentFilter);
    }, [report, agentFilter, isResidentSelected]);

    const handleTriggerAiAudit = async () => {
        if (!selectedJudgeId) {
            message.warning("Vui lòng chọn cấu hình Judge LLM trước khi chạy AI Auditor.");
            return;
        }
        setTriggerBusy(true);
        try {
            await urbanSimApi.triggerCompetencyAiAudit(projectId, runId, selectedJudgeId);
            setSelectedAuditVersion(undefined);
            const refreshed = await urbanSimApi.getCompetencyAiAudit(projectId, runId);
            setLoadedState((prev) => ({ ...prev, auditState: refreshed }));
            message.success("Đã kích hoạt AI Auditor (G-Eval) chạy nền cho Run này.");
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể kích hoạt AI Auditor");
        } finally {
            setTriggerBusy(false);
        }
    };

    const handleExport = async (format: "markdown" | "json") => {
        setExportingFormat(format);
        try {
            const { blob, filename } = await urbanSimApi.exportRunCompetency(
                projectId,
                runId,
                format,
                auditState?.selected_version ?? undefined
            );
            const objectUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(objectUrl);
            message.success(`Đã xuất báo cáo đánh giá (${filename}).`);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xuất báo cáo thất bại");
        } finally {
            setExportingFormat(null);
        }
    };

    const columns: ColumnsType<AgentCompetencyRow> = [
        {
            title: "Nhân sự BQL",
            key: "persona",
            fixed: isMobile ? undefined : "left",
            width: 220,
            render: (_, row) => (
                <Space direction="vertical" size={1}>
                    <Text strong style={{ color: "#1d4ed8", cursor: "pointer" }}>
                        #{row.agent_id} {row.full_name}
                    </Text>
                    <Space size={4} wrap>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                            {row.role_title}
                        </Text>
                        <Tag style={{ fontSize: 11 }}>{row.interaction_mode === "oversight" ? "Giám sát" : "Tác nghiệp"}</Tag>
                    </Space>
                </Space>
            ),
        },
        {
            title: "Bậc Miller (M0–M4)",
            key: "miller",
            width: 190,
            render: (_, row) => (
                <Space direction="vertical" size={3}>
                    <Tooltip
                        title={
                            <div>
                                {row.miller_gate_reasons.map((r, i) => (
                                    <div key={i}>• {r}</div>
                                ))}
                            </div>
                        }
                    >
                        <Tag color={MILLER_COLORS[row.miller_level] || "default"} style={{ fontWeight: 600 }}>
                            {MILLER_LABELS_VI[row.miller_level] || row.miller_level}
                        </Tag>
                    </Tooltip>
                    <Space size={4} wrap>
                        {row.safety_violation && (
                            <Tag color="red" icon={<WarningOutlined />}>
                                SAFETY_VIOLATION ({row.blocked_by_unsafe_action})
                            </Tag>
                        )}
                        {row.flags.includes("READ_ONLY_VERIFIED") && (
                            <Tag color="purple">READ_ONLY_VERIFIED</Tag>
                        )}
                    </Space>
                </Space>
            ),
        },
        {
            title: "Effectiveness",
            key: "eff",
            width: 115,
            render: (_, row) => (
                <Space direction="vertical" size={0}>
                    {renderNullablePercent(row.metrics.effectiveness)}
                    <Text type="secondary" style={{ fontSize: 11 }}>
                        {row.activity.succeeded_web_ops} ok · {row.activity.failed_web_attempts} lỗi
                    </Text>
                </Space>
            ),
        },
        {
            title: "Lostness (L_first)",
            key: "lostness",
            width: 130,
            render: (_, row) => renderLostness(row.metrics.lostness_l_first),
        },
        {
            title: "Chuyển hóa CSKH",
            key: "cskh",
            width: 135,
            render: (_, row) => (
                <Space direction="vertical" size={0}>
                    {renderNullablePercent(row.metrics.cskh_conversion)}
                    <Text type="secondary" style={{ fontSize: 11 }}>
                        {row.activity.atlas_converted}/{row.activity.atlas_asks_ok} lượt
                    </Text>
                </Space>
            ),
        },
        {
            title: "Ghi nhớ (3 kho)",
            key: "retention",
            width: 135,
            render: (_, row) => (
                <Space direction="vertical" size={0}>
                    <Tag color={row.retention.has_retention ? "green" : "default"}>
                        {row.retention.has_retention ? "Có ghi chép" : "Trống"}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                        {row.retention.notes_files_count} note · {row.retention.episodes_count} ký ức
                    </Text>
                </Space>
            ),
        },
        {
            title: "Pre → Post (c)",
            key: "quiz",
            width: 125,
            render: (_, row) => (
                <Space direction="vertical" size={0}>
                    {renderNormalizedChange(row.metrics.normalized_change_c)}
                    {row.quiz.pre_score_pct !== null && (
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            {row.quiz.pre_score_pct}% → {row.quiz.post_score_pct ?? "?"}%
                        </Text>
                    )}
                </Space>
            ),
        },
        {
            title: "UMUX / CIT",
            key: "debrief",
            width: 145,
            render: (_, row) => {
                const d = row.debrief;
                if (!d) return <Tag>Chưa phỏng vấn</Tag>;
                if (d.parse_failed) return <Tag color="red">Lỗi parse</Tag>;
                return (
                    <Space direction="vertical" size={2}>
                        <Space size={4} wrap>
                            <Tag color={d.umux_lite_score !== null && d.umux_lite_score >= 68 ? "green" : "blue"}>
                                UMUX {d.umux_lite_score !== null ? d.umux_lite_score.toFixed(0) : "N/A"}
                            </Tag>
                            <Tag color={d.incidents.length > 0 ? "volcano" : "default"}>
                                {d.incidents.length} CIT
                            </Tag>
                        </Space>
                        {d.bias_flags.length > 0 && (
                            <Tooltip title={d.bias_flags.join(", ")}>
                                <Tag color="gold" style={{ fontSize: 10 }}>Cảnh báo thiên lệch</Tag>
                            </Tooltip>
                        )}
                    </Space>
                );
            },
        },
        {
            title: "Tham khảo (Kane)",
            key: "diag",
            width: 120,
            render: (_, row) =>
                row.diagnostic_index === null ? (
                    <Tag>N/A</Tag>
                ) : (
                    <Space size={4}>
                        <Text>{row.diagnostic_index.toFixed(1)}</Text>
                        {row.non_compensatory_warning && (
                            <Tooltip title={row.non_compensatory_warning}>
                                <InfoCircleOutlined style={{ color: "#fa8c16" }} />
                            </Tooltip>
                        )}
                    </Space>
                ),
        },
        {
            title: "Hành trình",
            key: "action",
            width: 115,
            render: (_, row) => (
                <Button
                    size="small"
                    type="link"
                    icon={<HistoryOutlined />}
                    onClick={(e) => {
                        e.stopPropagation();
                        onInspectAgent(row.agent_id);
                    }}
                >
                    Xem nhật ký
                </Button>
            ),
        },
    ];

    if (loading) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}>
                    <Text type="secondary">Đang phân tích năng lực QLTN & tri thức BQL...</Text>
                </div>
            </div>
        );
    }

    if (loadError) {
        return <Alert type="error" showIcon message="Lỗi tải đánh giá năng lực" description={loadError} />;
    }

    if (!report) {
        return <Empty description="Chưa có dữ liệu đánh giá cho Run này." />;
    }

    const cs = report.cohort_summary;
    const debriefSummary = cs.sociological_debrief || report.sociological_debrief;
    const selectedResult = auditState?.selected_result || null;

    const renderCitBucket = (title: string, color: string, items: DebriefIncidentItem[]) => (
        <Card
            size="small"
            title={
                <Space>
                    <Tag color={color}>{items.length}</Tag>
                    <span>{title}</span>
                </Space>
            }
            style={{ height: "100%" }}
        >
            {items.length === 0 ? (
                <Text type="secondary">Không ghi nhận sự cố thuộc nhóm này.</Text>
            ) : (
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    {items.map((item) => (
                        <div
                            key={`${item.agent_id}-${item.incident_idx}`}
                            style={{
                                padding: 8,
                                background: "#f8fafc",
                                borderRadius: 6,
                                border: "1px solid #e2e8f0",
                            }}
                        >
                            <Space wrap size={4} style={{ marginBottom: 4 }}>
                                <Text
                                    strong
                                    style={{ color: "#1d4ed8", cursor: "pointer" }}
                                    onClick={() => onInspectAgent(item.agent_id)}
                                >
                                    #{item.agent_id} {item.full_name}
                                </Text>
                                <Tag color={item.grounding_status === "VERIFIED_BY_LOG" ? "green" : "orange"}>
                                    {item.grounding_status === "VERIFIED_BY_LOG"
                                        ? "VERIFIED_BY_LOG"
                                        : "UNGROUNDED_SELF_REPORT"}
                                </Tag>
                                <Tag
                                    color={
                                        item.severity === "CRITICAL" || item.severity === "S1_CRITICAL"
                                            ? "red"
                                            : item.severity === "MAJOR" || item.severity === "S2_HIGH"
                                              ? "orange"
                                              : "blue"
                                    }
                                >
                                    {item.severity}
                                </Tag>
                            </Space>
                            <div style={{ fontWeight: 600, fontSize: 12 }}>
                                {item.context_task || "(Chưa nêu tác vụ)"}{" "}
                                {item.screen_or_url ? <Text type="secondary">· {item.screen_or_url}</Text> : null}
                            </div>
                            <Paragraph style={{ margin: "4px 0", fontSize: 12 }}>
                                {item.what_happened}
                            </Paragraph>
                            {item.suggestion && (
                                <Text type="secondary" style={{ fontSize: 12, display: "block" }}>
                                    Đề xuất: {item.suggestion}
                                </Text>
                            )}
                            {item.evidence_anchors && item.evidence_anchors.length > 0 && (
                                <Space wrap size={4} style={{ marginTop: 4 }}>
                                    {item.evidence_anchors.slice(0, 3).map((anc) => (
                                        <Tag
                                            key={`${anc.stream}-${anc.seq}`}
                                            style={{ fontSize: 11, cursor: "pointer" }}
                                            onClick={() => onInspectAgent(item.agent_id)}
                                        >
                                            seq #{anc.seq} · {anc.action}
                                        </Tag>
                                    ))}
                                </Space>
                            )}
                        </div>
                    ))}
                </Space>
            )}
        </Card>
    );
    const renderRootCauseBucket = (
        title: string,
        color: string,
        items: AiAuditRootCauseEntry[]
    ) => (
        <Card
            size="small"
            title={
                <Space>
                    <Tag color={color}>{items.length}</Tag>
                    <span>{title}</span>
                </Space>
            }
            style={{ height: "100%" }}
        >
            {items.length === 0 ? (
                <Text type="secondary">Chưa ghi nhận vấn đề thuộc nhóm này.</Text>
            ) : (
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    {items.map((item, idx) => (
                        <div
                            key={`${item.agent_id}-${idx}`}
                            style={{
                                padding: 8,
                                background: "#f8fafc",
                                borderRadius: 6,
                                border: "1px solid #e2e8f0",
                            }}
                        >
                            <Text
                                strong
                                style={{ color: "#1d4ed8", cursor: "pointer" }}
                                onClick={() => onInspectAgent(item.agent_id)}
                            >
                                #{item.agent_id} {item.full_name}
                            </Text>
                            <div style={{ fontWeight: 600, marginTop: 2 }}>{item.title}</div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                {item.detail}
                            </Text>
                        </div>
                    ))}
                </Space>
            )}
        </Card>
    );

    return (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
                type="info"
                showIcon
                icon={<ExperimentOutlined />}
                message="Hệ thống Đánh giá Khoa học Phi Bù Trừ (Miller M0–M4 · Kane 2013 · ISO 9241-11 / Smith L_first · Polson-Lewis · Marx-Cummings c · G-Eval)"
                description={
                    <Space direction="vertical" size={2}>
                        <Text style={{ fontSize: 12 }}>
                            Nguồn tác nhân SSOT: <Tag>{report.participant_source}</Tag> · Mẫu số BQL:{" "}
                            <Text strong>{cs.eligible_bql_n} BQL</Text> (loại trừ {cs.excluded_count} tác nhân Cư dân/không quyền QLTN) · Model thực thi:{" "}
                            <Text code>{report.run_models.join(", ") || "N/A"}</Text>
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                            Điểm thấp ở cổng cứng (chưa mở đúng phân hệ / không điều phối sự vụ / SAFETY_VIOLATION) không thể được bù trừ bằng ghi chú hay lý thuyết.
                        </Text>
                    </Space>
                }
            />

            {isResidentSelected && selectedAgentObj && (
                <Alert
                    type="info"
                    showIcon
                    message={`Tác nhân #${selectedAgentObj.agent_id} ${selectedAgentObj.full_name} thuộc nhóm Cư dân (${selectedAgentObj.group_type})`}
                    description="Cư dân không được cấp tài khoản phần mềm QLTN nên nằm ngoài phạm vi đánh giá năng lực vận hành QLTN BQL."
                    action={
                        <Button size="small" type="primary" onClick={onClearAgentFilter}>
                            Xem toàn bộ {cs.eligible_bql_n} BQL
                        </Button>
                    }
                />
            )}

            <Row gutter={[12, 12]}>
                <Col xs={24} sm={12} lg={6}>
                    <Card size="small">
                        <Text type="secondary">Phân bố Bậc Miller (M0 → M4)</Text>
                        <div style={{ marginTop: 8 }}>
                            <Space wrap size={4}>
                                {(["M0", "M1", "M2", "M3", "M4"] as const).map((lvl) => (
                                    <Tag key={lvl} color={MILLER_COLORS[lvl]}>
                                        {lvl}: {cs.miller_distribution[lvl] ?? 0}
                                    </Tag>
                                ))}
                            </Space>
                        </div>
                        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6 }}>
                            Vi phạm an toàn: {cs.safety_violations_count} · Lưu ghi chép: {cs.retention_active_count}/{cs.eligible_bql_n}
                        </Text>
                    </Card>
                </Col>
                <Col xs={12} sm={12} lg={4}>
                    <Card size="small">
                        <Text type="secondary">Effectiveness TB</Text>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>
                            {cs.axes.effectiveness.mean !== null
                                ? `${(cs.axes.effectiveness.mean * 100).toFixed(1)}%`
                                : "N/A"}
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            Hợp lệ: {cs.axes.effectiveness.valid_n}/{cs.eligible_bql_n} BQL
                        </Text>
                    </Card>
                </Col>
                <Col xs={12} sm={12} lg={4}>
                    <Card size="small">
                        <Text type="secondary">Lostness L_first TB</Text>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>
                            {cs.axes.lostness_l_first.mean !== null
                                ? cs.axes.lostness_l_first.mean.toFixed(3)
                                : "N/A"}
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            Hợp lệ: {cs.axes.lostness_l_first.valid_n}/{cs.eligible_bql_n} (≤0.4 tốt)
                        </Text>
                    </Card>
                </Col>
                <Col xs={12} sm={12} lg={5}>
                    <Card size="small">
                        <Text type="secondary">Chuyển hóa CSKH TB</Text>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>
                            {cs.axes.cskh_conversion.mean !== null
                                ? `${(cs.axes.cskh_conversion.mean * 100).toFixed(1)}%`
                                : "N/A"}
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            Hỏi → mở/thao tác QLTN (0..2 tick): {cs.axes.cskh_conversion.valid_n}/{cs.eligible_bql_n}
                        </Text>
                    </Card>
                </Col>
                <Col xs={12} sm={12} lg={5}>
                    <Card size="small">
                        <Text type="secondary">Pre → Post (Marx-Cummings c)</Text>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>
                            {cs.quiz_summary.available && cs.axes.normalized_change_c.mean !== null
                                ? cs.axes.normalized_change_c.mean.toFixed(3)
                                : "Chưa bật Quiz"}
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            {cs.quiz_summary.available
                                ? `${cs.quiz_summary.assessment_mode} · ${cs.quiz_summary.status}`
                                : "Chế độ Open-Notes từ Run bật Quiz"}
                        </Text>
                    </Card>
                </Col>
            </Row>

            <Card
                size="small"
                title={
                    <Space wrap>
                        <InfoCircleOutlined style={{ color: "#1677ff" }} />
                        <span>Tiếng nói Người dùng BQL &amp; Phát hiện Lỗ hổng (Sociological Debrief · Behavioral Triangulation)</span>
                        {debriefSummary?.available && (
                            <>
                                <Tag color={debriefSummary.status === "COMPLETE" ? "green" : "orange"}>
                                    {debriefSummary.status} ({debriefSummary.respondents_n}/{debriefSummary.eligible_bql_n} BQL)
                                </Tag>
                                <Tag color="blue">
                                    {debriefSummary.cit_verified_count}/{debriefSummary.cit_total_count} CIT đối chứng log
                                </Tag>
                            </>
                        )}
                    </Space>
                }
            >
                {!debriefSummary || !debriefSummary.available ? (
                    <Alert
                        type="info"
                        showIcon
                        message="Chưa có dữ liệu Phỏng vấn Cuối ca (Sociological Debrief)"
                        description="Run này được chạy trước khi bật Sociological Debrief hoặc chưa kết thúc bước phỏng vấn cuối ca. Các Run mới mặc định bật Sociological Debrief để thu thập UMUX-Lite, SEQ, Workload, chất lượng CSKH và backlog CIT."
                    />
                ) : (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        {debriefSummary.bias_warnings_count > 0 && (
                            <Alert
                                type="warning"
                                showIcon
                                message={`Cảnh báo Thiên lệch Phản hồi (${debriefSummary.bias_warnings_count} nhân sự có ACQUIESCENCE_BIAS / CSKH_POS_BIAS)`}
                                description="Phát hiện nhân sự chấm điểm hài lòng cao bất chấp hành vi thực tế có lỗi thao tác hoặc chưa hỏi CSKH EvidenceAtlas. Cần đối chiếu log thực thi (Triangulation) trước khi kết luận."
                            />
                        )}
                        <Row gutter={[12, 12]}>
                            <Col xs={12} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">UMUX-Lite (0–100)</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700 }}>
                                        {debriefSummary.umux_lite_mean !== null
                                            ? debriefSummary.umux_lite_mean.toFixed(1)
                                            : "N/A"}
                                    </div>
                                    <Text type="secondary" style={{ fontSize: 11 }}>
                                        Hữu ích &amp; Dễ dùng (Lah 2020)
                                    </Text>
                                </Card>
                            </Col>
                            <Col xs={12} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">SEQ Dễ thao tác (1–7)</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700 }}>
                                        {debriefSummary.seq_mean !== null
                                            ? debriefSummary.seq_mean.toFixed(2)
                                            : "N/A"}
                                    </div>
                                    <Text type="secondary" style={{ fontSize: 11 }}>
                                        Sauro &amp; Dumas 2009 (≥ 5.0 thuận tiện)
                                    </Text>
                                </Card>
                            </Col>
                            <Col xs={12} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">Áp lực Workload (0–100)</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700 }}>
                                        {debriefSummary.workload_subset_mean_100 !== null
                                            ? debriefSummary.workload_subset_mean_100.toFixed(1)
                                            : "N/A"}
                                    </div>
                                    <Text type="secondary" style={{ fontSize: 11 }}>
                                        Effort: {debriefSummary.workload_effort_mean_100?.toFixed(0) ?? "N/A"} · Frustration:{" "}
                                        {debriefSummary.workload_frustration_mean_100?.toFixed(0) ?? "N/A"}
                                    </Text>
                                </Card>
                            </Col>
                            <Col xs={12} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">Chất lượng CSKH (D&amp;M 1–7)</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700 }}>
                                        {debriefSummary.cskh_quality_mean !== null
                                            ? debriefSummary.cskh_quality_mean.toFixed(2)
                                            : "N/A"}
                                    </div>
                                    <Text type="secondary" style={{ fontSize: 11 }}>
                                        Hợp lệ: {debriefSummary.cskh_valid_n} · CSKH lỗi toàn bộ: {debriefSummary.cskh_all_failed_n}
                                    </Text>
                                </Card>
                            </Col>
                        </Row>

                        <Row gutter={[12, 12]}>
                            <Col xs={24} md={8}>
                                {renderCitBucket(
                                    "Thiếu Tri thức CSKH (Knowledge Gaps)",
                                    "orange",
                                    debriefSummary.actionable_backlog.knowledge_gaps || []
                                )}
                            </Col>
                            <Col xs={24} md={8}>
                                {renderCitBucket(
                                    "Lỗi UX Phần mềm (Software UX Bugs)",
                                    "red",
                                    debriefSummary.actionable_backlog.software_ux_bugs || []
                                )}
                            </Col>
                            <Col xs={24} md={8}>
                                {renderCitBucket(
                                    "Tắc nghẽn Quy trình (Workflow Frictions)",
                                    "blue",
                                    debriefSummary.actionable_backlog.workflow_frictions || []
                                )}
                            </Col>
                        </Row>
                    </Space>
                )}
            </Card>

            <Card
                size="small"
                title={`Ma trận Năng lực Phần mềm QLTN (${visibleRows.length} BQL)`}
                extra={
                    <Space wrap>
                        <Button
                            size="small"
                            icon={<DownloadOutlined />}
                            loading={exportingFormat === "markdown"}
                            onClick={() => void handleExport("markdown")}
                        >
                            Xuất Markdown
                        </Button>
                        <Button
                            size="small"
                            icon={<DownloadOutlined />}
                            loading={exportingFormat === "json"}
                            onClick={() => void handleExport("json")}
                        >
                            Xuất JSON
                        </Button>
                    </Space>
                }
            >
                <Table
                    size="small"
                    rowKey="agent_id"
                    columns={columns}
                    dataSource={visibleRows}
                    pagination={false}
                    scroll={{ x: "max-content" }}
                    onRow={(row) => ({
                        onClick: () => onInspectAgent(row.agent_id),
                        style: { cursor: "pointer" },
                    })}
                    locale={{ emptyText: "Không có nhân sự BQL phù hợp bộ lọc hiện tại" }}
                />
            </Card>

            <Card
                size="small"
                title={
                    <Space wrap>
                        <RobotOutlined />
                        <span>AI Auditor Chẩn đoán Gốc rễ (G-Eval Bất đồng bộ)</span>
                        {auditStatusStr !== "IDLE" && (
                            <Badge
                                status={
                                    auditStatusStr === "COMPLETED"
                                        ? "success"
                                        : auditStatusStr === "RUNNING" || auditStatusStr === "QUEUED"
                                          ? "processing"
                                          : "error"
                                }
                                text={`${auditStatusStr}${
                                    auditState?.status?.agents_total
                                        ? ` (${auditState.status.agents_completed || 0}/${auditState.status.agents_total} BQL)`
                                        : ""
                                }`}
                            />
                        )}
                    </Space>
                }
            >
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <Row gutter={[12, 12]} align="middle">
                        <Col xs={24} md={12}>
                            <Space direction="vertical" size={4} style={{ width: "100%" }}>
                                <Text strong>Chọn Mô hình Giám khảo (Judge LLM độc lập — Zheng et al. 2023)</Text>
                                <Select
                                    aria-label="Chọn cấu hình Judge LLM"
                                    style={{ width: "100%" }}
                                    placeholder="Chọn bộ cấu hình từ menu LLM (khuyên dùng khác họ model chạy)"
                                    value={selectedJudgeId || undefined}
                                    onChange={(val) => setSelectedJudgeId(val)}
                                    options={llmConfigs.map((cfg) => {
                                        const first = cfg.config?.[0];
                                        const label = first?.model
                                            ? `${cfg.name} (${first.provider || "llm"}: ${first.model})`
                                            : cfg.name;
                                        return { value: cfg.id, label };
                                    })}
                                />
                            </Space>
                        </Col>
                        <Col xs={24} md={12}>
                            <Space wrap style={{ width: "100%", justifyContent: isMobile ? "flex-start" : "flex-end" }}>
                                {(auditState?.versions?.length || 0) > 0 && (
                                    <Select
                                        aria-label="Chọn phiên bản AI Audit"
                                        style={{ width: 150 }}
                                        value={auditState?.selected_version ?? undefined}
                                        onChange={(val) => setSelectedAuditVersion(val)}
                                        options={(auditState?.versions || []).map((v) => ({
                                            value: v,
                                            label: `Phiên bản v${v}`,
                                        }))}
                                    />
                                )}
                                <Button
                                    type="primary"
                                    icon={<RobotOutlined />}
                                    loading={triggerBusy || isAuditPolling}
                                    disabled={!selectedJudgeId}
                                    onClick={() => void handleTriggerAiAudit()}
                                >
                                    {isAuditPolling ? "Đang chấm điểm..." : "Chạy AI Auditor (G-Eval)"}
                                </Button>
                            </Space>
                        </Col>
                    </Row>

                    {selectedJudgeInfo.sameFamilyBias && (
                        <Alert
                            type="warning"
                            showIcon
                            message="Cảnh báo Thiên vị Cùng họ Mô hình (SAME_FAMILY_BIAS_WARNING)"
                            description={`Judge đang chọn (${selectedJudgeInfo.modelName}, họ "${selectedJudgeInfo.family}") cùng họ với mô hình thực thi phiên chạy (${report.run_models.join(", ")}). Để kết quả G-Eval khách quan hơn theo Zheng et al. (2023), hãy cân nhắc chọn Judge thuộc họ mô hình khác (vd: Anthropic Claude vs OpenAI GPT).`}
                        />
                    )}

                    {auditState?.status?.error && auditStatusStr === "FAILED" && (
                        <Alert
                            type="error"
                            showIcon
                            message="Tác vụ AI Auditor gặp lỗi"
                            description={auditState.status.error}
                        />
                    )}

                    {selectedResult && (
                        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                            <Space wrap size={8}>
                                <Tag color="blue" icon={<CheckCircleOutlined />}>
                                    Phiên bản v{selectedResult.version}
                                </Tag>
                                <Tag>
                                    Judge: {selectedResult.judge.provider} / {selectedResult.judge.model}
                                </Tag>
                                <Tag color="gold">
                                    Chi phí riêng Judge: ${selectedResult.judge_usage.cost_usd.toFixed(5)} (không gộp LLM_STATS.json)
                                </Tag>
                                <Tag>
                                    Snapshot tại bước {selectedResult.snapshot_boundary.as_of_step_count} · seq #{selectedResult.snapshot_boundary.as_of_latest_seq}
                                </Tag>
                                {selectedResult.unverified_citations_total > 0 && (
                                    <Tag color="red" icon={<AlertOutlined />}>
                                        UNVERIFIED_CITATION: {selectedResult.unverified_citations_total} trích dẫn chưa khớp nhật ký
                                    </Tag>
                                )}
                            </Space>

                            <Row gutter={[12, 12]}>
                                <Col xs={24} md={8}>
                                    {renderRootCauseBucket(
                                        "Điểm nghẽn UI/UX Phần mềm QLTN",
                                        "volcano",
                                        selectedResult.root_cause_groups?.ui_ux_friction || []
                                    )}
                                </Col>
                                <Col xs={24} md={8}>
                                    {renderRootCauseBucket(
                                        "Thiếu hụt Kho Tri thức / CSKH Thần Nông",
                                        "orange",
                                        selectedResult.root_cause_groups?.cskh_knowledge_gap || []
                                    )}
                                </Col>
                                <Col xs={24} md={8}>
                                    {renderRootCauseBucket(
                                        "Lỗi Thực thi Tác nhân / Kịch bản",
                                        "purple",
                                        selectedResult.root_cause_groups?.agent_execution_error || []
                                    )}
                                </Col>
                            </Row>

                            <Collapse
                                size="small"
                                items={[
                                    {
                                        key: "detail-verdicts",
                                        label: `Chi tiết nhận xét & trích dẫn của Judge (${selectedResult.agent_audits.length} BQL)`,
                                        children: (
                                            <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                {selectedResult.agent_audits.map((au) => (
                                                    <Card key={au.agent_id} size="small">
                                                        <Space wrap style={{ marginBottom: 4 }}>
                                                            <Text
                                                                strong
                                                                style={{ color: "#1d4ed8", cursor: "pointer" }}
                                                                onClick={() => onInspectAgent(au.agent_id)}
                                                            >
                                                                #{au.agent_id} {au.full_name}
                                                            </Text>
                                                            <Tag color={MILLER_COLORS[au.miller_level] || "default"}>
                                                                {au.miller_level}
                                                            </Tag>
                                                            <Tag color="geekblue">{au.primary_root_cause}</Tag>
                                                            {au.unverified_citations_count > 0 && (
                                                                <Tag color="red">UNVERIFIED_CITATION</Tag>
                                                            )}
                                                        </Space>
                                                        <Paragraph style={{ marginBottom: 6 }}>{au.summary_vi}</Paragraph>
                                                        {au.citations.length > 0 && (
                                                            <Space wrap size={4}>
                                                                {au.citations.map((c, idx) => (
                                                                    <Tag
                                                                        key={idx}
                                                                        color={c.verified ? "green" : "red"}
                                                                        icon={<SafetyOutlined />}
                                                                    >
                                                                        {c.seq !== null ? `seq #${c.seq}` : `step #${c.step_index}`}
                                                                        {c.verified ? " (đã đối soát)" : " (KHÔNG KHỚP)"}
                                                                    </Tag>
                                                                ))}
                                                            </Space>
                                                        )}
                                                    </Card>
                                                ))}
                                            </Space>
                                        ),
                                    },
                                ]}
                            />
                        </Space>
                    )}
                </Space>
            </Card>
        </Space>
    );
};
