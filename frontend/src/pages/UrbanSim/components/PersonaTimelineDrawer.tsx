import {
    ApiOutlined,
    BulbOutlined,
    CheckCircleOutlined,
    CloseCircleOutlined,
    CodeOutlined,
    CommentOutlined,
    FileTextOutlined,
    GlobalOutlined,
    HistoryOutlined,
    PictureOutlined,
    ReloadOutlined,
    UnorderedListOutlined,
    WarningOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Col,
    Collapse,
    Drawer,
    Empty,
    Grid,
    Row,
    Segmented,
    Select,
    Space,
    Spin,
    Tabs,
    Tag,
    Typography,
    message,
} from "antd";
import React, { useEffect, useMemo, useState } from "react";
import { formatAtlasText } from "../../../components/markdownHelpers";
import { MarkdownWithMermaid } from "../../../components/MarkdownWithMermaid";
import {
    AgentStatusRow,
    getScreenshotUrl,
    PersonaTimelineResponse,
    PersonaTimelineStep,
    urbanSimApi,
} from "../../../services/urbanSimApi";

const { Text, Paragraph } = Typography;

type StepFilterMode = "all" | "active" | "web" | "atlas" | "comm";

const EPISODE_TAG_COLORS: Record<string, string> = {
    observation: "blue",
    routine: "geekblue",
    goal: "gold",
    commitment: "purple",
    resolution: "green",
    preference: "cyan",
    identity: "volcano",
    conflict: "red",
    relationship: "magenta",
    decision: "cyan",
    reflection: "magenta",
};

const TODO_STATUS_COLORS: Record<string, string> = {
    completed: "success",
    done: "success",
    in_progress: "processing",
    pending: "default",
    deferred: "warning",
};

function formatClockOnly(simTime: string | null): string {
    if (!simTime) return "—";
    const m = String(simTime).match(/T(\d{2}:\d{2})/);
    if (m) return m[1];
    return String(simTime);
}

export interface PersonaTimelineDrawerProps {
    open: boolean;
    projectId: string;
    runId: string;
    agentId: number | null;
    agents: AgentStatusRow[];
    onClose: () => void;
    onSelectAgent: (agentId: number) => void;
    onOpenLightbox: (filename: string, caption: string) => void;
}

export const PersonaTimelineDrawer: React.FC<PersonaTimelineDrawerProps> = ({
    open,
    projectId,
    runId,
    agentId,
    agents,
    onClose,
    onSelectAgent,
    onOpenLightbox,
}) => {
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;

    const [loadedState, setLoadedState] = useState<{
        key: string;
        data: PersonaTimelineResponse | null;
    }>({ key: "", data: null });
    const [filterMode, setFilterMode] = useState<StepFilterMode>("all");
    const [reloadNonce, setReloadNonce] = useState(0);

    const requestKey =
        open && agentId !== null ? `${projectId}|${runId}|${agentId}|${reloadNonce}` : "";
    const loading = Boolean(requestKey) && loadedState.key !== requestKey;
    const timeline =
        open && agentId !== null && loadedState.data?.agent.agent_id === agentId
            ? loadedState.data
            : null;

    useEffect(() => {
        if (!requestKey || agentId === null) return;
        let cancelled = false;
        async function fetchIt(targetAid: number, key: string) {
            try {
                const res = await urbanSimApi.getAgentTimeline(projectId, runId, targetAid);
                if (!cancelled) {
                    setLoadedState({ key, data: res });
                }
            } catch (err) {
                if (!cancelled) {
                    setLoadedState((prev) => ({ key, data: prev.data }));
                    message.error(
                        err instanceof Error ? err.message : "Không tải được dòng lịch sử Persona"
                    );
                }
            }
        }
        void fetchIt(agentId, requestKey);
        return () => {
            cancelled = true;
        };
    }, [requestKey, projectId, runId, agentId]);

    const currentAgentMeta = useMemo(
        () => agents.find((a) => a.agent_id === agentId) || null,
        [agents, agentId]
    );

    const filteredSteps = useMemo(() => {
        const steps = timeline?.steps || [];
        if (filterMode === "all") return steps;
        if (filterMode === "web") return steps.filter((s) => s.web_events.length > 0);
        if (filterMode === "atlas") return steps.filter((s) => s.atlas_events.length > 0);
        if (filterMode === "comm") {
            return steps.filter((s) => s.comm_events.length > 0 || s.related_incidents.length > 0);
        }
        return steps.filter(
            (s) =>
                s.thoughts.length > 0 ||
                s.web_events.length > 0 ||
                s.atlas_events.length > 0 ||
                s.comm_events.length > 0 ||
                s.workspace_actions.length > 0 ||
                s.episodes.length > 0
        );
    }, [timeline, filterMode]);

    const jumpToStep = (stepIndex: number) => {
        const el = document.getElementById(`persona-step-${stepIndex}`);
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    const renderStepCard = (step: PersonaTimelineStep) => {
        const clock = formatClockOnly(step.sim_time);
        const hasTechnical = step.technical_turns.some((t) => t.actions.length > 0);
        const agentDisplayName = timeline?.agent.full_name || currentAgentMeta?.full_name || `#${agentId}`;

        return (
            <Card
                key={step.step_index}
                id={`persona-step-${step.step_index}`}
                size="small"
                style={{
                    borderLeft: "4px solid #2563eb",
                    background: "#ffffff",
                }}
            >
                {/* 1. Mốc thời gian giả lập & Bối cảnh */}
                <Space wrap style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }}>
                    <Space wrap size={6}>
                        <Tag color="blue" style={{ fontWeight: 700, fontSize: 13 }}>
                            {clock} · Bước {step.step_index}
                        </Tag>
                        {step.zone && <Tag color="geekblue">{step.zone}</Tag>}
                        {step.time_band && <Tag>{step.time_band}</Tag>}
                        {typeof step.unread_messages === "number" && step.unread_messages > 0 && (
                            <Tag color="purple">{step.unread_messages} tin chưa đọc</Tag>
                        )}
                    </Space>
                    <Space wrap size={4}>
                        {step.episodes.length > 0 && <Tag color="cyan">{step.episodes.length} ký ức</Tag>}
                        {step.web_events.length > 0 && <Tag color="processing">{step.web_events.length} Web</Tag>}
                        {step.atlas_events.length > 0 && <Tag color="green">{step.atlas_events.length} CSKH</Tag>}
                        {step.related_incidents.length > 0 && (
                            <Tag color="volcano">{step.related_incidents.length} sự vụ</Tag>
                        )}
                    </Space>
                </Space>

                {/* CHẶNG 1: Ý định & Tự thoại khởi phát (Pre-action) -> CHẶNG 2: Hành động -> CHẶNG 3: Tổng kết & Ký ức hậu bước (Post-step) */}
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    {/* Chặng 1: Ý định & Tự thoại khởi phát (Pre-action) */}
                    {step.turn_thoughts && step.turn_thoughts.length > 0 ? (
                        <div
                            style={{
                                background: "#f5f3ff",
                                borderLeft: "3px solid #7c3aed",
                                padding: "8px 12px",
                                borderRadius: 6,
                            }}
                        >
                            <Text strong style={{ color: "#5b21b6", display: "block", marginBottom: 4 }}>
                                <BulbOutlined /> Chặng 1 · Tự thoại & Ý định khởi phát (Trước hành động)
                            </Text>
                            {step.turn_thoughts.map((tt, idx) => (
                                <div
                                    key={`tt-${step.step_index}-${tt.turn}-${idx}`}
                                    style={{
                                        marginBottom: idx === step.turn_thoughts!.length - 1 ? 0 : 6,
                                        color: "#1e1b4b",
                                    }}
                                >
                                    <Tag color="purple" style={{ fontSize: 11 }}>Lượt {tt.turn}</Tag>
                                    <Text style={{ color: "#1e1b4b" }}>{tt.thought}</Text>
                                    {tt.action_labels.length > 0 && (
                                        <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                                            → {tt.action_labels.join(" · ")}
                                        </Text>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : step.thoughts.length > 0 ? (
                        <div
                            style={{
                                background: "#f5f3ff",
                                borderLeft: "3px solid #7c3aed",
                                padding: "8px 12px",
                                borderRadius: 6,
                            }}
                        >
                            <Text strong style={{ color: "#5b21b6", display: "block", marginBottom: 4 }}>
                                <BulbOutlined /> Chặng 1 · Tự thoại & Ý định khởi phát (Trước hành động)
                            </Text>
                            {step.thoughts.map((th, idx) => (
                                <Paragraph
                                    key={`th-${step.step_index}-${idx}`}
                                    style={{ margin: idx === step.thoughts.length - 1 ? 0 : "0 0 6px", color: "#1e1b4b" }}
                                >
                                    {th}
                                </Paragraph>
                            ))}
                        </div>
                    ) : (
                        <div
                            style={{
                                background: "#f8fafc",
                                borderLeft: "3px solid #cbd5e1",
                                padding: "6px 10px",
                                borderRadius: 6,
                            }}
                        >
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                <BulbOutlined /> Chặng 1 · Tự thoại trước hành động: Chưa ghi nhận tự thoại pre-action ở bước này (Run lịch sử hoặc lượt tool không phát content; tự thoại sẽ tự động ghi từ Run bật cờ mới).
                            </Text>
                        </div>
                    )}

                    {/* Chặng 2: Hành động thực tế trên Sổ tay / Web QLTN / CSKH / Giao tiếp */}
                    {step.workspace_actions.length > 0 && (
                        <Space wrap size={6}>
                            {step.workspace_actions.map((wa, idx) => (
                                <Tag key={`ws-${step.step_index}-${idx}`} icon={<FileTextOutlined />} color="default">
                                    {wa.summary_vi}
                                </Tag>
                            ))}
                        </Space>
                    )}

                    {/* 2b. Thao tác trên Web QLTN kèm ảnh */}
                    {step.web_events.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <Text strong style={{ color: "#1d4ed8" }}>
                                <GlobalOutlined /> Chặng 2 · Thao tác trên phần mềm QLTN
                            </Text>
                            {step.web_events.map((ev) => {
                                const isLoadingShot =
                                    ev.screenshot_status === "LOADING_TIMEOUT" ||
                                    ev.screenshot_status === "LOADING_SPLASH_SUSPECTED";
                                return (
                                <Card key={ev.seq} size="small" style={{ background: "#f8fafc" }}>
                                    <Row gutter={[12, 8]} align="middle" justify="space-between">
                                        <Col xs={24} md={ev.screenshot_file ? 17 : 24}>
                                            <Space wrap size={6}>
                                                <Tag color={ev.ok ? "blue" : "red"}>#{ev.seq}</Tag>
                                                {isLoadingShot && (
                                                    <Tag color="orange">
                                                        {ev.screenshot_status === "LOADING_TIMEOUT"
                                                            ? "Trang đang tải (Timeout)"
                                                            : `Nghi màn hình Loading${ev.screenshot_bytes ? ` (${Math.round(ev.screenshot_bytes / 1024)}KB)` : ""}`}
                                                    </Tag>
                                                )}
                                                <Text strong>{ev.summary}</Text>
                                            </Space>
                                            {typeof ev.details?.url === "string" && ev.details.url && (
                                                <div style={{ marginTop: 4 }}>
                                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                                        Màn hình: {ev.details.url}
                                                    </Text>
                                                </div>
                                            )}
                                            {isLoadingShot && (
                                                <div style={{ marginTop: 4 }}>
                                                    <Text type="warning" style={{ fontSize: 11 }}>
                                                        Ảnh chụp lúc giao diện đang ở màn hình tải ứng dụng — không chứa dữ liệu nghiệp vụ đầy đủ.
                                                    </Text>
                                                </div>
                                            )}
                                        </Col>
                                        {ev.screenshot_file && (
                                            <Col xs={24} md={7} style={{ textAlign: isMobile ? "left" : "right" }}>
                                                <img
                                                    src={getScreenshotUrl(projectId, runId, ev.screenshot_file)}
                                                    alt={ev.summary}
                                                    loading="eager"
                                                    style={{
                                                        width: 144,
                                                        height: 86,
                                                        objectFit: "cover",
                                                        backgroundColor: "#f1f5f9",
                                                        borderRadius: 6,
                                                        border: isLoadingShot ? "2px solid #f59e0b" : "1px solid #cbd5e1",
                                                        cursor: "pointer",
                                                    }}
                                                    onClick={() =>
                                                        onOpenLightbox(
                                                            ev.screenshot_file!,
                                                            `${agentDisplayName} (${clock}) — ${ev.summary}`
                                                        )
                                                    }
                                                />
                                            </Col>
                                        )}
                                    </Row>
                                </Card>
                                );
                            })}
                        </div>
                    )}

                    {/* 2c. Hỏi đáp Đội ngũ CSKH Thần Nông / EvidenceAtlas */}
                    {step.atlas_events.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <Text strong style={{ color: "#0f766e" }}>
                                <ApiOutlined /> Trao đổi Đội ngũ Hỗ trợ / CSKH
                            </Text>
                            {step.atlas_events.map((ev) => {
                                const q = formatAtlasText(String(ev.details?.question || ev.summary));
                                const ans = String(ev.details?.answer || ev.details?.error || "");
                                return (
                                    <Card key={ev.seq} size="small">
                                        <div style={{ marginBottom: 6 }}>
                                            <Tag color={ev.ok ? "cyan" : "red"}>#{ev.seq}</Tag>
                                            <Text strong>Câu hỏi: </Text>
                                            <Text>{q}</Text>
                                        </div>
                                        {ans && (
                                            <div
                                                style={{
                                                    background: ev.ok === false ? "#fef2f2" : "#f0fdf4",
                                                    border: ev.ok === false ? "1px solid #fecaca" : "1px solid #bbf7d0",
                                                    padding: "8px 10px",
                                                    borderRadius: 6,
                                                }}
                                            >
                                                {ev.ok === false ? (
                                                    <Text type="danger">{formatAtlasText(ans)}</Text>
                                                ) : (
                                                    <MarkdownWithMermaid content={ans} />
                                                )}
                                            </div>
                                        )}
                                    </Card>
                                );
                            })}
                        </div>
                    )}

                    {/* 2d. Giao tiếp Cư dân ↔ BQL & Sự vụ liên quan */}
                    {(step.comm_events.length > 0 || step.related_incidents.length > 0) && (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <Text strong style={{ color: "#7e22ce" }}>
                                <CommentOutlined /> Giao tiếp & Sự vụ liên quan
                            </Text>
                            {step.related_incidents.map((inc) => (
                                <div
                                    key={inc.incident_id}
                                    style={{
                                        background: "#fff7ed",
                                        border: "1px solid #fed7aa",
                                        borderRadius: 6,
                                        padding: "6px 10px",
                                    }}
                                >
                                    <Space wrap size={6}>
                                        <Tag color={inc.status === "RESOLVED" ? "green" : "volcano"}>
                                            {inc.incident_id} · {inc.status}
                                        </Tag>
                                        <Text strong>{inc.title}</Text>
                                    </Space>
                                    <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                                        Người báo: {inc.reporter_name} · Khu vực: {inc.zone_key}
                                        {inc.resolution_note ? ` · Ghi chú: ${inc.resolution_note}` : ""}
                                    </div>
                                </div>
                            ))}
                            {step.comm_events.map((ev) => (
                                <div
                                    key={ev.seq}
                                    style={{
                                        background: "#faf5ff",
                                        border: "1px solid #e9d5ff",
                                        borderRadius: 6,
                                        padding: "6px 10px",
                                    }}
                                >
                                    <Space wrap size={6}>
                                        <Tag color="purple">#{ev.seq}</Tag>
                                        <Text>{ev.summary}</Text>
                                    </Space>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Chặng 3: Tổng kết & Ghi nhớ Hậu bước (Post-step episodes.jsonl từ finish) */}
                    {(step.step_summary || step.episodes.length > 0) && (
                        <div
                            style={{
                                background: "#f8fafc",
                                border: "1px solid #e2e8f0",
                                borderRadius: 6,
                                padding: "8px 10px",
                            }}
                        >
                            <Text strong style={{ display: "block", marginBottom: 6, color: "#0f172a" }}>
                                Chặng 3 · Tổng kết & Ghi nhớ Hậu bước (Post-step)
                            </Text>
                            {step.step_summary && (
                                <div style={{ marginBottom: step.episodes.length > 0 ? 6 : 0, color: "#334155" }}>
                                    <Text strong>Tóm tắt bước: </Text>
                                    <Text>{step.step_summary}</Text>
                                </div>
                            )}
                            {step.episodes.length > 0 && (
                                <Space direction="vertical" size={6} style={{ width: "100%" }}>
                                    {step.episodes.map((ep) => (
                                        <div key={ep.id || `${step.step_index}-${ep.text.slice(0, 20)}`} style={{ lineHeight: 1.5 }}>
                                            <Tag color={EPISODE_TAG_COLORS[ep.type] || "default"} style={{ marginRight: 6 }}>
                                                {ep.type_label || ep.type}
                                            </Tag>
                                            <Text>{ep.text}</Text>
                                        </div>
                                    ))}
                                </Space>
                            )}
                        </div>
                    )}

                    {/* 4. Chi tiết thao tác kỹ thuật / Tool Call — MẶC ĐỊNH ĐÓNG GỌN kiểu ChatGPT/Claude/Antigravity */}
                    {hasTechnical && (
                        <Collapse
                            ghost
                            size="small"
                            items={[
                                {
                                    key: `tech-${step.step_index}`,
                                    label: (
                                        <Text type="secondary" style={{ fontSize: 12 }}>
                                            <CodeOutlined /> Chi tiết thao tác kỹ thuật ({step.technical_turn_count} lượt suy luận · {step.technical_tool_count} lệnh công cụ)
                                        </Text>
                                    ),
                                    children: (
                                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                            {step.technical_turns
                                                .filter((t) => t.actions.length > 0)
                                                .map((turnItem) => (
                                                    <div
                                                        key={`t-${step.step_index}-${turnItem.turn}`}
                                                        style={{
                                                            background: "#f8fafc",
                                                            border: "1px solid #e2e8f0",
                                                            borderRadius: 6,
                                                            padding: "8px 10px",
                                                        }}
                                                    >
                                                        <Text strong style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                                                            {turnItem.turn === 0
                                                                ? "Quan sát tự động đầu khung giờ"
                                                                : `Lượt suy luận #${turnItem.turn}`}
                                                        </Text>
                                                        {turnItem.thought && (
                                                            <Paragraph
                                                                style={{ fontSize: 12, color: "#475569", margin: "0 0 6px" }}
                                                            >
                                                                {turnItem.thought}
                                                            </Paragraph>
                                                        )}
                                                        <Space direction="vertical" size={6} style={{ width: "100%" }}>
                                                            {turnItem.actions.map((act, aIdx) => (
                                                                <div
                                                                    key={`a-${step.step_index}-${turnItem.turn}-${aIdx}`}
                                                                    style={{
                                                                        background: "#ffffff",
                                                                        border: "1px solid #e2e8f0",
                                                                        borderRadius: 4,
                                                                        padding: "6px 8px",
                                                                        fontSize: 12,
                                                                    }}
                                                                >
                                                                    <Space wrap size={6}>
                                                                        {act.ok ? (
                                                                            <CheckCircleOutlined style={{ color: "#16a34a" }} />
                                                                        ) : (
                                                                            <CloseCircleOutlined style={{ color: "#dc2626" }} />
                                                                        )}
                                                                        <Text strong>{act.label_vi}</Text>
                                                                        <Tag style={{ fontSize: 11 }}>{act.action}</Tag>
                                                                    </Space>
                                                                    {act.args !== undefined && act.args !== null && (
                                                                        <pre
                                                                            style={{
                                                                                margin: "4px 0 0",
                                                                                padding: "4px 6px",
                                                                                background: "#f1f5f9",
                                                                                borderRadius: 4,
                                                                                fontSize: 11,
                                                                                overflowX: "auto",
                                                                                whiteSpace: "pre-wrap",
                                                                                wordBreak: "break-word",
                                                                            }}
                                                                        >
                                                                            {typeof act.args === "string"
                                                                                ? act.args
                                                                                : JSON.stringify(act.args, null, 2)}
                                                                        </pre>
                                                                    )}
                                                                    {act.observation_preview && (
                                                                        <div
                                                                            style={{
                                                                                marginTop: 4,
                                                                                color: "#475569",
                                                                                whiteSpace: "pre-wrap",
                                                                                wordBreak: "break-word",
                                                                            }}
                                                                        >
                                                                            Kết quả: {act.observation_preview}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </Space>
                                                    </div>
                                                ))}
                                        </Space>
                                    ),
                                },
                            ]}
                        />
                    )}
                </Space>
            </Card>
        );
    };

    const headerAgent = timeline?.agent || currentAgentMeta;

    return (
        <Drawer
            placement="right"
            destroyOnHidden
            open={open}
            onClose={onClose}
            styles={{ wrapper: { width: isMobile ? "100%" : "min(960px, 92vw)" } }}
            title={
                <Space wrap size={8} style={{ width: "100%", justifyContent: "space-between" }}>
                    <Space wrap size={8}>
                        <HistoryOutlined />
                        <span>
                            {headerAgent
                                ? `Hành trình & Tư duy: #${headerAgent.agent_id} ${headerAgent.full_name}`
                                : "Hành trình & Tư duy Persona"}
                        </span>
                        {headerAgent && (
                            <Tag color={headerAgent.group_type === "BQL" ? "blue" : "purple"}>
                                {headerAgent.group_type}
                            </Tag>
                        )}
                    </Space>
                    <Space wrap size={6}>
                        <Select
                            aria-label="Chọn nhân vật xem hành trình"
                            style={{ width: isMobile ? 200 : 250 }}
                            size="small"
                            value={agentId ?? undefined}
                            onChange={(val) => onSelectAgent(val)}
                            options={agents.map((a) => ({
                                value: a.agent_id,
                                label: `#${a.agent_id} ${a.full_name}`,
                            }))}
                        />
                        <Button
                            size="small"
                            icon={<ReloadOutlined />}
                            loading={loading}
                            onClick={() => setReloadNonce((n) => n + 1)}
                        >
                            Làm mới
                        </Button>
                    </Space>
                </Space>
            }
        >
            {loading && !timeline ? (
                <div style={{ padding: 48, textAlign: "center" }}>
                    <Spin size="large" />
                    <div style={{ marginTop: 12 }}>
                        <Text type="secondary">Đang hợp nhất ký ức, tư duy và thao tác của nhân vật...</Text>
                    </div>
                </div>
            ) : !timeline ? (
                <Empty description="Chọn một nhân vật để xem dòng lịch sử hoạt động" />
            ) : (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    {/* Khối KPI mini */}
                    <Row gutter={[8, 8]}>
                        <Col xs={12} sm={8} md={4}>
                            <Card size="small">
                                <Text type="secondary" style={{ fontSize: 12 }}>Khung giờ</Text>
                                <div style={{ fontSize: 18, fontWeight: 700 }}>{timeline.summary.total_steps}</div>
                            </Card>
                        </Col>
                        <Col xs={12} sm={8} md={5}>
                            <Card size="small">
                                <Text type="secondary" style={{ fontSize: 12 }}>Ký ức / Nhận thức</Text>
                                <div style={{ fontSize: 18, fontWeight: 700 }}>{timeline.summary.episodes_count}</div>
                            </Card>
                        </Col>
                        <Col xs={12} sm={8} md={5}>
                            <Card size="small">
                                <Text type="secondary" style={{ fontSize: 12 }}>Thao tác Web QLTN</Text>
                                <div style={{ fontSize: 18, fontWeight: 700 }}>{timeline.summary.web_events_count}</div>
                                {(timeline.summary.loading_screenshots_count ?? 0) > 0 && (
                                    <Text type="warning" style={{ fontSize: 11 }}>
                                        {timeline.summary.loading_screenshots_count} ảnh chụp lúc đang tải
                                    </Text>
                                )}
                            </Card>
                        </Col>
                        <Col xs={12} sm={12} md={5}>
                            <Card size="small">
                                <Text type="secondary" style={{ fontSize: 12 }}>Hỏi CSKH</Text>
                                <div style={{ fontSize: 18, fontWeight: 700 }}>{timeline.summary.atlas_events_count}</div>
                            </Card>
                        </Col>
                        <Col xs={24} sm={12} md={5}>
                            <Card size="small">
                                <Text type="secondary" style={{ fontSize: 12 }}>Sự vụ liên quan</Text>
                                <div style={{ fontSize: 18, fontWeight: 700 }}>
                                    {timeline.summary.related_incidents_count}
                                </div>
                            </Card>
                        </Col>
                    </Row>

                    <Tabs
                        defaultActiveKey="timeline"
                        items={[
                            {
                                key: "timeline",
                                label: `Dòng thời gian theo giờ giả lập (${timeline.steps.length})`,
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                                            <Segmented
                                                value={filterMode}
                                                onChange={(val) => setFilterMode(val as StepFilterMode)}
                                                options={[
                                                    { label: "Tất cả", value: "all" },
                                                    { label: "Có hoạt động", value: "active" },
                                                    { label: "Có Web QLTN", value: "web" },
                                                    { label: "Có hỏi CSKH", value: "atlas" },
                                                    { label: "Sự vụ / Giao tiếp", value: "comm" },
                                                ]}
                                            />
                                        </Space>

                                        {filteredSteps.length > 0 && (
                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                                {filteredSteps.map((s) => (
                                                    <Button
                                                        key={`jump-${s.step_index}`}
                                                        size="small"
                                                        onClick={() => jumpToStep(s.step_index)}
                                                    >
                                                        {formatClockOnly(s.sim_time)} (B{s.step_index})
                                                    </Button>
                                                ))}
                                            </div>
                                        )}

                                        {filteredSteps.length === 0 ? (
                                            <Empty description="Không có khung giờ nào khớp bộ lọc đã chọn" />
                                        ) : (
                                            <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                {filteredSteps.map((st) => renderStepCard(st))}
                                            </Space>
                                        )}
                                    </Space>
                                ),
                            },
                            {
                                key: "memory",
                                label: `Trí nhớ, Việc cần làm & Sổ tay (${timeline.summary.todos_count + timeline.summary.notes_count})`,
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        {timeline.all_related_incidents.length > 0 && (
                                            <Card
                                                size="small"
                                                title={
                                                    <Space size={6}>
                                                        <WarningOutlined style={{ color: "#ea580c" }} />
                                                        <span>Tổng hợp Sự vụ liên quan ({timeline.all_related_incidents.length})</span>
                                                    </Space>
                                                }
                                            >
                                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                    {timeline.all_related_incidents.map((inc) => (
                                                        <Alert
                                                            key={inc.incident_id}
                                                            type={inc.status === "RESOLVED" ? "success" : "warning"}
                                                            showIcon
                                                            message={`${inc.incident_id} [${inc.status}] — ${inc.title}`}
                                                            description={`Người báo: ${inc.reporter_name} · Khu vực: ${inc.zone_key}${inc.resolution_note ? ` · Xử lý: ${inc.resolution_note}` : ""}`}
                                                        />
                                                    ))}
                                                </Space>
                                            </Card>
                                        )}

                                        <Card
                                            size="small"
                                            title={
                                                <Space size={6}>
                                                    <UnorderedListOutlined />
                                                    <span>Danh sách việc nhân vật đang theo dõi (TODO.json · {timeline.todos.length})</span>
                                                </Space>
                                            }
                                        >
                                            {timeline.todos.length === 0 ? (
                                                <Empty description="Chưa có việc nào trong TODO.json" />
                                            ) : (
                                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                    {timeline.todos.map((td) => (
                                                        <Card key={td.id} size="small" style={{ background: "#f8fafc" }}>
                                                            <Space wrap size={6}>
                                                                <Tag color={TODO_STATUS_COLORS[td.status] || "default"}>
                                                                    {td.status}
                                                                </Tag>
                                                                <Text strong>{td.title}</Text>
                                                                {td.priority !== undefined && (
                                                                    <Tag>Ưu tiên: {td.priority}</Tag>
                                                                )}
                                                            </Space>
                                                            {td.notes && (
                                                                <div style={{ marginTop: 4, color: "#475569", fontSize: 12 }}>
                                                                    {td.notes}
                                                                </div>
                                                            )}
                                                        </Card>
                                                    ))}
                                                </Space>
                                            )}
                                        </Card>

                                        <Card
                                            size="small"
                                            title={
                                                <Space size={6}>
                                                    <FileTextOutlined />
                                                    <span>Sổ tay tự học của nhân vật (notes/* · {timeline.notes.length})</span>
                                                </Space>
                                            }
                                        >
                                            {timeline.notes.length === 0 ? (
                                                <Empty description="Nhân vật chưa tạo file ghi chú nào trong notes/" />
                                            ) : (
                                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                    {timeline.notes.map((nf) => (
                                                        <Card
                                                            key={nf.path}
                                                            size="small"
                                                            title={nf.path}
                                                            extra={
                                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                                    {nf.size_bytes.toLocaleString()} bytes
                                                                </Text>
                                                            }
                                                        >
                                                            <MarkdownWithMermaid content={nf.content} />
                                                        </Card>
                                                    ))}
                                                </Space>
                                            )}
                                        </Card>

                                        <Card
                                            size="small"
                                            title={
                                                <Space size={6}>
                                                    <PictureOutlined />
                                                    <span>Trí nhớ dài hạn (MEMORY.md)</span>
                                                </Space>
                                            }
                                        >
                                            {timeline.memory_md ? (
                                                <MarkdownWithMermaid content={timeline.memory_md} />
                                            ) : (
                                                <Empty description="Chưa có dữ liệu MEMORY.md" />
                                            )}
                                        </Card>
                                    </Space>
                                ),
                            },
                        ]}
                    />
                </Space>
            )}
        </Drawer>
    );
};
