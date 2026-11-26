import {
    ApiOutlined,
    ArrowLeftOutlined,
    CaretRightOutlined,
    ClockCircleOutlined,
    CommentOutlined,
    DollarOutlined,
    ExperimentOutlined,
    FileMarkdownOutlined,
    FileTextOutlined,
    FireOutlined,
    GlobalOutlined,
    HistoryOutlined,
    LikeOutlined,
    DislikeOutlined,
    MoonOutlined,
    PauseOutlined,
    PictureOutlined,
    ReloadOutlined,
    SortAscendingOutlined,
    SortDescendingOutlined,
    SunOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Checkbox,
    Col,
    Descriptions,
    Drawer,
    Empty,
    Grid,
    Modal,
    Progress,
    Row,
    Segmented,
    Select,
    Space,
    Spin,
    Table,
    Tabs,
    Tag,
    Tooltip,
    Typography,
    message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { formatAtlasText } from "../../components/markdownHelpers";
import { MarkdownWithMermaid } from "../../components/MarkdownWithMermaid";
import {
    AgentStatusRow,
    getScreenshotUrl,
    ModelCostBreakdown,
    urbanSimApi,
    UrbanEventItem,
    UrbanIncident,
    UrbanSimRunState,
} from "../../services/urbanSimApi";
import { CompetencyEvaluationTab } from "./components/CompetencyEvaluationTab";
import { PersonaTimelineDrawer } from "./components/PersonaTimelineDrawer";
import { UrbanZoneMap } from "./components/UrbanZoneMap";

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG_COLORS: Record<string, string> = {
    STARTING: "processing",
    RUNNING: "processing",
    PAUSING: "warning",
    PAUSED: "orange",
    RESUMING: "processing",
    COMPLETED: "success",
    COMPLETED_WITH_ERRORS: "gold",
    FAILED: "error",
};

interface ModelRowItem extends ModelCostBreakdown {
    model: string;
}

interface ParsedSimClock {
    time: string;
    date: string;
    shortDate: string;
    full: string;
}

function parseIsoPreservingTz(iso?: string | null): ParsedSimClock | null {
    if (!iso) return null;
    const raw = String(iso).trim();
    const epochMs = Date.parse(raw);
    if (Number.isNaN(epochMs)) return null;

    let offsetMinutes = -new Date(epochMs).getTimezoneOffset();
    const tzMatch = raw.match(/(Z|[+-]\d{2}:?\d{2})$/i);
    if (tzMatch) {
        const tz = tzMatch[1];
        if (tz.toUpperCase() === "Z") {
            offsetMinutes = 0;
        } else {
            const sign = tz[0] === "-" ? -1 : 1;
            const digits = tz.slice(1).replace(":", "");
            const hh = Number(digits.slice(0, 2));
            const mm = Number(digits.slice(2, 4));
            if (Number.isFinite(hh) && Number.isFinite(mm)) {
                offsetMinutes = sign * (hh * 60 + mm);
            }
        }
    }

    const d = new Date(epochMs + offsetMinutes * 60_000);
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
    const yyyy = d.getUTCFullYear();
    return {
        time: `${hh}:${mm}`,
        date: `${dd}/${mo}/${yyyy}`,
        shortDate: `${dd}/${mo}`,
        full: `${hh}:${mm} · ${dd}/${mo}/${yyyy}`,
    };
}

function formatTickShort(seconds?: number | null): string {
    if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return "";
    const sec = Math.round(seconds);
    if (sec % 3600 === 0) return `+${sec / 3600} giờ/bước`;
    if (sec >= 60 && sec % 60 === 0) return `+${sec / 60} phút/bước`;
    return `+${sec} giây/bước`;
}

function formatEventSimTime(iso?: string | null): string {
    const parsed = parseIsoPreservingTz(iso);
    if (!parsed) return iso ? String(iso) : "";
    return `${parsed.time} · ${parsed.shortDate}`;
}

function getAgentTotalActions(row: AgentStatusRow): number {
    if (typeof row.total_actions_count === "number") return row.total_actions_count;
    return (
        (row.web_actions_count || 0) +
        (row.atlas_asks_count || 0) +
        (row.comm_actions_count || 0) +
        (row.incident_actions_count || 0)
    );
}

function getAgentLearningScore(row: AgentStatusRow): number {
    return (row.episodes_count || 0) + (row.todos_total || 0) + (row.notes_count || 0);
}

const STREAM_TAG_COLORS: Record<string, string> = {
    WEB: "blue",
    ATLAS: "cyan",
    COMM: "purple",
    INCIDENT: "volcano",
};

export default function RunMonitorPage() {
    const { projectId = "", runId = "" } = useParams();
    const navigate = useNavigate();
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;

    const [loading, setLoading] = useState(true);
    const [runState, setRunState] = useState<UrbanSimRunState | null>(null);
    const [events, setEvents] = useState<UrbanEventItem[]>([]);
    const [agentFilter, setAgentFilter] = useState<number | "ALL">("ALL");
    const [activeTab, setActiveTab] = useState<string>("overview");
    const [timelineAgentId, setTimelineAgentId] = useState<number | null>(null);
    const [costDrawerOpen, setCostDrawerOpen] = useState(false);
    const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
    const [lightboxCaption, setLightboxCaption] = useState<string>("");
    const [actionBusy, setActionBusy] = useState(false);
    const [feedbackSent, setFeedbackSent] = useState<Record<string, "LIKE" | "DISLIKE">>({});
    const [exportingFormat, setExportingFormat] = useState<"markdown" | "json" | null>(null);
    const [exportFilteredOnly, setExportFilteredOnly] = useState(false);
    const [agentTableGroupFilter, setAgentTableGroupFilter] = useState<
        "ALL" | "BQL" | "RESIDENT" | "ACTIVE"
    >("ALL");
    const [agentSortMode, setAgentSortMode] = useState<"ACTIVITY" | "ID">("ACTIVITY");

    const latestSeqRef = useRef<number>(0);
    const stateDigestRef = useRef<string>("");

    const fetchIncremental = useCallback(async (forceFull = false) => {
        if (!projectId || !runId) return;
        const [st, firstEvRes] = await Promise.all([
            urbanSimApi.getRunState(projectId, runId),
            urbanSimApi.getRunEvents(projectId, runId, {
                since_seq: forceFull ? 0 : latestSeqRef.current,
                limit: 500,
                stream: "ALL",
            }),
        ]);

        const agentActivityDigest = (st.agent_statuses || []).reduce(
            (acc, ag) =>
                acc +
                getAgentTotalActions(ag) +
                (ag.episodes_count || 0) +
                (ag.todos_total || 0) +
                (ag.todos_completed || 0) +
                (ag.notes_count || 0) +
                (ag.unread_messages_count || 0) +
                (ag.incidents_open_count || 0),
            0
        );
        const nextDigest = JSON.stringify({
            status: st.run.status,
            step: st.run.step_count,
            simTime: st.sim_clock?.current_sim_time || st.run.current_sim_time || "",
            tok: st.run.total_tokens,
            cost: st.run.total_cost_usd,
            seq: st.latest_seq,
            inc: st.incidents.length,
            act: agentActivityDigest,
        });
        if (forceFull || nextDigest !== stateDigestRef.current) {
            stateDigestRef.current = nextDigest;
            setRunState(st);
        }

        if (forceFull) {
            const collected: UrbanEventItem[] = [...(firstEvRes.items || [])];
            let cursorSeq = firstEvRes.latest_seq || 0;
            let hasMore = Boolean(firstEvRes.has_more);
            for (let page = 1; page < 5 && hasMore; page += 1) {
                const nextRes = await urbanSimApi.getRunEvents(projectId, runId, {
                    since_seq: cursorSeq,
                    limit: 500,
                    stream: "ALL",
                });
                if (nextRes.items && nextRes.items.length > 0) {
                    collected.push(...nextRes.items);
                }
                if ((nextRes.latest_seq || 0) <= cursorSeq) break;
                cursorSeq = nextRes.latest_seq || cursorSeq;
                hasMore = Boolean(nextRes.has_more);
            }
            setEvents(collected.slice(-2500));
            latestSeqRef.current = cursorSeq;
        } else if (firstEvRes.items && firstEvRes.items.length > 0) {
            setEvents((prev) => {
                const seen = new Set(prev.map((x) => x.seq));
                const additions = firstEvRes.items.filter((x) => !seen.has(x.seq));
                if (additions.length === 0) return prev;
                return [...prev, ...additions].slice(-2500);
            });
            latestSeqRef.current = Math.max(latestSeqRef.current, firstEvRes.latest_seq || 0);
        }
    }, [projectId, runId]);

    useEffect(() => {
        let active = true;
        latestSeqRef.current = 0;
        stateDigestRef.current = "";
        async function initLoad() {
            try {
                await fetchIncremental(true);
            } catch (err) {
                if (active) {
                    message.error(err instanceof Error ? err.message : "Không tải được dữ liệu Run");
                }
            } finally {
                if (active) setLoading(false);
            }
        }
        void initLoad();
        return () => {
            active = false;
        };
    }, [fetchIncremental]);

    const runStatus = runState?.run.status || "";
    const isRunning = ["STARTING", "RUNNING", "PAUSING", "RESUMING"].includes(runStatus);

    useEffect(() => {
        if (!isRunning) return;
        const timer = window.setInterval(() => {
            void fetchIncremental(false).catch(() => {});
        }, 2500);
        return () => window.clearInterval(timer);
    }, [fetchIncremental, isRunning]);

    const handleControl = async (action: "pause" | "resume") => {
        if (!projectId || !runId) return;
        setActionBusy(true);
        try {
            if (action === "pause") {
                await urbanSimApi.pauseRun(projectId, runId);
                message.info("Đã gửi yêu cầu Pause — đợi hoàn tất tick hiện tại.");
            } else {
                await urbanSimApi.resumeRun(projectId, runId);
                message.success("Đã kích hoạt tiếp tục (Resume).");
            }
            await fetchIncremental(true);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Thao tác thất bại");
        } finally {
            setActionBusy(false);
        }
    };

    const handleVote = async (
        ev: UrbanEventItem,
        vote: "LIKE" | "DISLIKE"
    ) => {
        const msgId = String(ev.details?.assistant_message_id || "");
        const sessId = String(ev.details?.bot_session_id || "");
        if (!msgId) {
            message.warning("Sự kiện này chưa có assistant_message_id để đánh giá lên Atlas.");
            return;
        }
        try {
            await urbanSimApi.sendSupportFeedback(projectId, runId, {
                message_id: msgId,
                session_id: sessId,
                vote,
            });
            setFeedbackSent((prev) => ({ ...prev, [String(ev.seq)]: vote }));
            message.success(`Đã gửi đánh giá ${vote} đồng bộ về EvidenceAtlas.`);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Gửi đánh giá thất bại");
        }
    };

    const handleExportAtlasQa = async (format: "markdown" | "json") => {
        if (!projectId || !runId) return;
        setExportingFormat(format);
        try {
            const scopedAgent = exportFilteredOnly && agentFilter !== "ALL" ? agentFilter : null;
            const { blob, filename } = await urbanSimApi.exportAtlasQa(
                projectId,
                runId,
                format,
                scopedAgent
            );
            const objectUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = objectUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(objectUrl);
            message.success(`Đã xuất toàn bộ Hỏi Đáp CSKH (${filename}).`);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xuất nội dung Hỏi Đáp CSKH thất bại");
        } finally {
            setExportingFormat(null);
        }
    };

    const filteredEvents = useMemo(() => {
        const ordered = [...events].reverse();
        if (agentFilter === "ALL") return ordered;
        return ordered.filter((e) => e.agent_id === agentFilter);
    }, [agentFilter, events]);

    const webEvents = useMemo(() => filteredEvents.filter((e) => e.stream === "WEB"), [filteredEvents]);
    const atlasEvents = useMemo(() => filteredEvents.filter((e) => e.stream === "ATLAS"), [filteredEvents]);
    const commEvents = useMemo(
        () => filteredEvents.filter((e) => e.stream === "COMM" || e.stream === "INCIDENT"),
        [filteredEvents]
    );

    const modelRows: ModelRowItem[] = useMemo(() => {
        const models = runState?.cost?.models || {};
        return Object.entries(models).map(([model, info]) => ({
            model,
            ...info,
        }));
    }, [runState]);

    const displayedAgents = useMemo(() => {
        const list = runState?.agent_statuses || [];
        const filtered = list.filter((ag) => {
            if (agentTableGroupFilter === "BQL") return ag.group_type === "BQL";
            if (agentTableGroupFilter === "RESIDENT") return ag.group_type === "RESIDENT";
            if (agentTableGroupFilter === "ACTIVE") return getAgentTotalActions(ag) > 0;
            return true;
        });
        return [...filtered].sort((a, b) => {
            if (agentSortMode === "ACTIVITY") {
                const diff = getAgentTotalActions(b) - getAgentTotalActions(a);
                if (diff !== 0) return diff;
            }
            return a.agent_id - b.agent_id;
        });
    }, [runState, agentTableGroupFilter, agentSortMode]);

    const mostActiveAgent = useMemo(() => {
        const list = runState?.agent_statuses || [];
        let best: AgentStatusRow | null = null;
        let bestCount = 0;
        for (const ag of list) {
            const cnt = getAgentTotalActions(ag);
            if (cnt > bestCount) {
                bestCount = cnt;
                best = ag;
            }
        }
        return best;
    }, [runState]);

    if (loading || !runState) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}><Text type="secondary">Đang tải bảng giám sát Live Monitor...</Text></div>
            </div>
        );
    }

    const { run, sim_clock, cost, project, stream_counts, zones, incidents, agent_statuses } = runState;
    const openIncidentsCount = incidents.filter((i) => i.status !== "RESOLVED").length;
    const budget = Number(project.max_cost_usd_per_run || 0);
    const budgetPct = budget > 0 ? Math.min(100, Math.round((cost.cost_usd / budget) * 100)) : 0;

    const currentSimParsed = parseIsoPreservingTz(sim_clock?.current_sim_time || run.current_sim_time);
    const startSimParsed = parseIsoPreservingTz(sim_clock?.start_sim_time);
    const endSimParsed = parseIsoPreservingTz(sim_clock?.end_sim_time);
    const tickLabel = formatTickShort(sim_clock?.tick_seconds);
    const simWindowRange =
        startSimParsed && endSimParsed
            ? startSimParsed.shortDate === endSimParsed.shortDate
                ? `${startSimParsed.time} → ${endSimParsed.time}`
                : `${startSimParsed.time} ${startSimParsed.shortDate} → ${endSimParsed.time} ${endSimParsed.shortDate}`
            : null;
    const isDaytime = sim_clock?.is_daytime ?? true;
    const dayNightLabel = sim_clock?.day_night_label_vi || (isDaytime ? "Ban ngày" : "Ban đêm");

    const openLightbox = (filename: string, caption: string) => {
        setLightboxSrc(getScreenshotUrl(projectId, runId, filename));
        setLightboxCaption(caption);
    };

    const openPersonaTimeline = (aid: number) => {
        setTimelineAgentId(aid);
    };

    const incidentColumns: ColumnsType<UrbanIncident> = [
        { title: "Mã", dataIndex: "incident_id", key: "incident_id", width: 95 },
        { title: "Sự vụ", dataIndex: "title", key: "title" },
        { title: "Khu vực", dataIndex: "zone_key", key: "zone_key", width: 120 },
        { title: "Người báo", dataIndex: "reporter_name", key: "reporter_name" },
        {
            title: "Trạng thái",
            dataIndex: "status",
            key: "status",
            render: (st: string) => <Tag color={st === "RESOLVED" ? "green" : "volcano"}>{st}</Tag>,
        },
        { title: "Ghi chú xử lý", dataIndex: "resolution_note", key: "resolution_note" },
    ];

    const agentColumns: ColumnsType<AgentStatusRow> = [
        {
            title: "Tác nhân",
            key: "name",
            sorter: (a, b) => a.agent_id - b.agent_id,
            render: (_, row) => (
                <Space direction="vertical" size={2}>
                    <Space size={6} wrap>
                        <Text strong>#{row.agent_id} {row.full_name}</Text>
                        <Tag color={row.group_type === "BQL" ? "blue" : "purple"} style={{ marginInlineEnd: 0 }}>
                            {row.group_type === "BQL" ? "BQL" : "Cư dân"}
                        </Tag>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>{row.role_title}</Text>
                </Space>
            ),
        },
        {
            title: "Tổng hành động",
            key: "total_actions",
            width: 140,
            sorter: (a, b) => getAgentTotalActions(a) - getAgentTotalActions(b),
            render: (_, row) => {
                const total = getAgentTotalActions(row);
                const comm = row.comm_actions_count || 0;
                const inc = row.incident_actions_count || 0;
                const badgeColor = total >= 10 ? "green" : total > 0 ? "blue" : "default";
                const badgeText = total >= 10 ? "Sôi nổi" : total > 0 ? "Hoạt động" : "Chờ";
                return (
                    <Tooltip
                        title={`Web: ${row.web_actions_count} · Atlas: ${row.atlas_asks_count} · Giao tiếp: ${comm} · Sự vụ: ${inc}`}
                    >
                        <Space size={6}>
                            <Text strong style={{ fontSize: 15 }}>{total}</Text>
                            <Tag color={badgeColor} style={{ marginInlineEnd: 0 }}>{badgeText}</Tag>
                        </Space>
                    </Tooltip>
                );
            },
        },
        {
            title: "Chi tiết kênh",
            key: "counts",
            sorter: (a, b) =>
                (a.web_actions_count + a.atlas_asks_count + (a.comm_actions_count || 0)) -
                (b.web_actions_count + b.atlas_asks_count + (b.comm_actions_count || 0)),
            render: (_, row) => {
                const comm = row.comm_actions_count || 0;
                const incRel = row.incidents_related_count || 0;
                const incOpen = row.incidents_open_count || 0;
                const unread = row.unread_messages_count || 0;
                const webFail = row.web_failed_count || 0;
                const atlasFail = row.atlas_failed_count || 0;
                if (!row.software_access_enabled) {
                    return (
                        <Space direction="vertical" size={2}>
                            <Space size={6} wrap>
                                <Text style={{ fontSize: 12 }}>
                                    Giao tiếp: <Text strong>{comm}</Text> · Sự vụ: <Text strong>{incRel}</Text>
                                    {incOpen > 0 ? ` (${incOpen} mở)` : ""}
                                </Text>
                            </Space>
                            <Space size={4} wrap>
                                <Tag style={{ marginInlineEnd: 0, fontSize: 11 }}>Chỉ giao tiếp</Tag>
                                {unread > 0 && (
                                    <Tag color="purple" style={{ marginInlineEnd: 0, fontSize: 11 }}>
                                        {unread} chưa đọc
                                    </Tag>
                                )}
                            </Space>
                        </Space>
                    );
                }
                return (
                    <Space direction="vertical" size={2}>
                        <Text style={{ fontSize: 12 }}>
                            Web: <Text strong>{row.web_actions_count}</Text>
                            {row.blocked_actions_count > 0 ? ` (chặn ${row.blocked_actions_count})` : ""}
                            {webFail > 0 ? ` (lỗi ${webFail})` : ""}
                            {" · "}Atlas: <Text strong>{row.atlas_asks_count}</Text>
                            {atlasFail > 0 ? ` (lỗi ${atlasFail})` : ""}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                            Giao tiếp: {comm} · Sự vụ: {incRel}
                            {incOpen > 0 ? ` (${incOpen} mở)` : ""}
                            {unread > 0 ? ` · ${unread} chưa đọc` : ""}
                        </Text>
                    </Space>
                );
            },
        },
        {
            title: "Tự học & Việc",
            key: "learning",
            sorter: (a, b) => getAgentLearningScore(a) - getAgentLearningScore(b),
            render: (_, row) => {
                const ep = row.episodes_count || 0;
                const todoDone = row.todos_completed || 0;
                const todoTot = row.todos_total || 0;
                const notes = row.notes_count || 0;
                return (
                    <Space direction="vertical" size={2}>
                        <Text style={{ fontSize: 12 }}>
                            Ký ức: <Text strong>{ep}</Text> · Ghi chú: <Text strong>{notes}</Text>
                        </Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                            Todo: {todoDone}/{todoTot}
                        </Text>
                    </Space>
                );
            },
        },
        {
            title: "Zone & Màn hình",
            dataIndex: "current_url",
            key: "url",
            render: (url: string, row) => (
                <Space direction="vertical" size={2}>
                    <Tag color="geekblue" style={{ marginInlineEnd: 0, width: "fit-content" }}>
                        {row.current_zone}
                    </Tag>
                    <Space size={6}>
                        <Text ellipsis={{ tooltip: url }} style={{ maxWidth: 180, fontSize: 12 }}>
                            {url || (row.software_access_enabled ? "Chưa mở web" : "Chỉ giao tiếp")}
                        </Text>
                        {row.latest_screenshot && (
                            <Space size={4} wrap>
                                <Button
                                    size="small"
                                    icon={<PictureOutlined />}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        openLightbox(row.latest_screenshot!, `${row.full_name} — ${url}`);
                                    }}
                                >
                                    Ảnh
                                </Button>
                                {(row.latest_screenshot_status === "LOADING_TIMEOUT" ||
                                    row.latest_screenshot_status === "LOADING_SPLASH_SUSPECTED") && (
                                    <Tag color="orange" style={{ margin: 0, fontSize: 11 }}>
                                        {row.latest_screenshot_status === "LOADING_TIMEOUT"
                                            ? "Chụp khi đang tải (Timeout)"
                                            : "Nghi ảnh đang tải"}
                                    </Tag>
                                )}
                            </Space>
                        )}
                    </Space>
                </Space>
            ),
        },
        {
            title: "Hoạt động gần nhất",
            key: "last_activity",
            render: (_, row) => {
                if (!row.last_action_summary && !row.last_action) {
                    return <Text type="secondary" style={{ fontSize: 12 }}>Chưa có hành động</Text>;
                }
                const lastTime = formatEventSimTime(row.last_action_sim_time);
                const fullSummary = row.last_action_summary || row.last_action || "";
                const streamColor = STREAM_TAG_COLORS[row.last_action_stream || ""] || "default";
                return (
                    <Space direction="vertical" size={2} style={{ maxWidth: 230 }}>
                        <Space size={4} wrap>
                            {row.last_action_stream && (
                                <Tag color={streamColor} style={{ marginInlineEnd: 0, fontSize: 11 }}>
                                    {row.last_action_stream}
                                </Tag>
                            )}
                            {lastTime && (
                                <Text type="secondary" style={{ fontSize: 11 }}>{lastTime}</Text>
                            )}
                        </Space>
                        <Text ellipsis={{ tooltip: fullSummary }} style={{ maxWidth: 220, fontSize: 12 }}>
                            {fullSummary}
                        </Text>
                    </Space>
                );
            },
        },
        {
            title: "Hành trình",
            key: "timeline",
            render: (_, row) => (
                <Button
                    size="small"
                    type="link"
                    icon={<HistoryOutlined />}
                    onClick={(e) => {
                        e.stopPropagation();
                        openPersonaTimeline(row.agent_id);
                    }}
                >
                    Xem hành trình
                </Button>
            ),
        },
    ];

    const modelColumns: ColumnsType<ModelRowItem> = [
        { title: "Model", dataIndex: "model", key: "model" },
        { title: "Calls", dataIndex: "calls", key: "calls", align: "right" },
        {
            title: "Input",
            dataIndex: "input",
            key: "input",
            align: "right",
            render: (v: number) => v.toLocaleString(),
        },
        {
            title: "Cached",
            dataIndex: "cached_input",
            key: "cached",
            align: "right",
            render: (v: number) => v.toLocaleString(),
        },
        {
            title: "Output",
            dataIndex: "output",
            key: "output",
            align: "right",
            render: (v: number) => v.toLocaleString(),
        },
        {
            title: "USD",
            dataIndex: "cost_usd",
            key: "usd",
            align: "right",
            render: (v: number) => `$${v.toFixed(5)}`,
        },
        {
            title: "VND",
            dataIndex: "cost_vnd",
            key: "vnd",
            align: "right",
            render: (v: number) => `${Math.round(v).toLocaleString()} đ`,
        },
    ];

    return (
        <div style={{ padding: "16px", maxWidth: 1400, margin: "0 auto" }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card size="small">
                    <Row gutter={[12, 12]} align="middle" justify="space-between">
                        <Col xs={24} lg={14}>
                            <Space wrap>
                                <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/urban-sim")}>
                                    Điều phối
                                </Button>
                                <Title level={4} style={{ margin: 0 }}>
                                    Giám sát Run #{run.run_number}
                                </Title>
                                <Tag color={STATUS_TAG_COLORS[run.status] || "default"}>{run.status}</Tag>
                                {run.execution_phase === "PRE_QUIZ" && <Tag color="purple">Đang làm Pre-Quiz</Tag>}
                                {run.execution_phase === "POST_QUIZ" && <Tag color="purple">Đang làm Post-Quiz</Tag>}
                                <Tag>{run.pilot_mode ? "Pilot" : "Full"}</Tag>
                                <Tag>{run.router_type}</Tag>
                                {currentSimParsed && (
                                    <Tag
                                        icon={isDaytime ? <SunOutlined /> : <MoonOutlined />}
                                        color={isDaytime ? "gold" : "geekblue"}
                                        style={
                                            isDaytime
                                                ? undefined
                                                : {
                                                      background: "#eef2ff",
                                                      color: "#312e81",
                                                      borderColor: "#c7d2fe",
                                                  }
                                        }
                                    >
                                        {currentSimParsed.full} · {dayNightLabel}
                                        {sim_clock?.time_band_label_vi ? ` · ${sim_clock.time_band_label_vi}` : ""}
                                    </Tag>
                                )}
                            </Space>
                            <div style={{ marginTop: 4 }}>
                                <Text type="secondary">{project.name} · ID: {run.id}</Text>
                            </div>
                        </Col>
                        <Col xs={24} lg={10} style={{ display: "flex", justifyContent: isMobile ? "flex-start" : "flex-end", minWidth: 0 }}>
                            <Space wrap style={{ width: "100%", justifyContent: isMobile ? "flex-start" : "flex-end" }}>
                                <Select
                                    aria-label="Lọc theo tác nhân"
                                    style={{ width: isMobile ? "100%" : 220, maxWidth: "100%", minWidth: 0 }}
                                    value={agentFilter}
                                    onChange={(val) => setAgentFilter(val)}
                                    options={[
                                        { value: "ALL", label: "Tất cả tác nhân" },
                                        ...agent_statuses.map((a) => ({
                                            value: a.agent_id,
                                            label: `#${a.agent_id} ${a.full_name}`,
                                        })),
                                    ]}
                                />
                                <Button
                                    icon={<HistoryOutlined />}
                                    disabled={agent_statuses.length === 0}
                                    onClick={() => {
                                        const targetAid =
                                            agentFilter !== "ALL" ? agentFilter : agent_statuses[0]?.agent_id;
                                        if (targetAid !== undefined) {
                                            openPersonaTimeline(targetAid);
                                        }
                                    }}
                                >
                                    Hành trình Persona
                                </Button>
                                {["STARTING", "RUNNING"].includes(run.status) && (
                                    <Button
                                        icon={<PauseOutlined />}
                                        loading={actionBusy}
                                        onClick={() => void handleControl("pause")}
                                    >
                                        Pause
                                    </Button>
                                )}
                                {["PAUSED", "FAILED", "COMPLETED_WITH_ERRORS"].includes(run.status) && (
                                    <Button
                                        type="primary"
                                        icon={<CaretRightOutlined />}
                                        loading={actionBusy}
                                        onClick={() => void handleControl("resume")}
                                    >
                                        Resume
                                    </Button>
                                )}
                                <Button icon={<ReloadOutlined />} onClick={() => void fetchIncremental(true)}>
                                    Làm mới
                                </Button>
                            </Space>
                        </Col>
                    </Row>
                </Card>

                {run.pause_reason && run.status === "PAUSED" && (
                    <Alert
                        type="warning"
                        showIcon
                        message={`Run đang tạm dừng (${run.pause_reason})`}
                        description="Toàn bộ trạng thái Web storage_state, EvidenceAtlas bot_session_id và chỉ số token lũy kế đã lưu an toàn. Bấm Resume để chạy tiếp."
                    />
                )}
                {run.error_message && run.status === "FAILED" && (
                    <Alert type="error" showIcon message="Run gặp lỗi" description={run.error_message} />
                )}

                <Row gutter={[12, 12]}>
                    <Col xs={24} sm={12} md={8} lg={5}>
                        <Card size="small">
                            <Space style={{ width: "100%", justifyContent: "space-between" }} size={4}>
                                <Text type="secondary">
                                    <ClockCircleOutlined /> Thời gian & Tiến độ
                                </Text>
                                {currentSimParsed && (
                                    <Tag
                                        icon={isDaytime ? <SunOutlined /> : <MoonOutlined />}
                                        color={isDaytime ? "gold" : "geekblue"}
                                        style={{ marginInlineEnd: 0, fontSize: 11 }}
                                    >
                                        {dayNightLabel}
                                    </Tag>
                                )}
                            </Space>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
                                <span style={{ fontSize: 20, fontWeight: 700 }}>
                                    {currentSimParsed ? currentSimParsed.time : `${run.step_count} / ${run.total_steps}`}
                                </span>
                                {currentSimParsed && (
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                        {currentSimParsed.date}
                                        {(sim_clock?.day_index ?? 1) > 1 ? ` (Ngày ${sim_clock?.day_index})` : ""}
                                    </Text>
                                )}
                            </div>
                            <Progress
                                size="small"
                                percent={run.total_steps > 0 ? Math.round((run.step_count / run.total_steps) * 100) : 0}
                                format={() => `B${run.step_count}/${run.total_steps}`}
                            />
                            <Text type="secondary" style={{ fontSize: 11, display: "block" }}>
                                {sim_clock?.time_band_label_vi || "Đang khởi tạo"}
                                {simWindowRange ? ` · ${simWindowRange}` : ""}
                                {tickLabel ? ` (${tickLabel})` : ""}
                            </Text>
                        </Card>
                    </Col>
                    <Col xs={12} sm={12} md={8} lg={4}>
                        <Card size="small">
                            <Text type="secondary">Tác nhân hoạt động</Text>
                            <div style={{ fontSize: 20, fontWeight: 700 }}>{run.active_agent_count}</div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                {zones.length} Khu vực (Zero Bắc Kinh)
                            </Text>
                        </Card>
                    </Col>
                    <Col xs={12} sm={12} md={8} lg={5}>
                        <Card size="small">
                            <Text type="secondary">Sự vụ Cư dân ↔ BQL</Text>
                            <div style={{ fontSize: 20, fontWeight: 700 }}>
                                {incidents.length} <Text type="secondary" style={{ fontSize: 14 }}>({openIncidentsCount} mở)</Text>
                            </div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                Giao tiếp COMM: {stream_counts.COMM}
                            </Text>
                        </Card>
                    </Col>
                    <Col xs={12} sm={12} md={12} lg={5}>
                        <Card size="small">
                            <Text type="secondary">Thao tác Web / Hỏi Atlas</Text>
                            <div style={{ fontSize: 20, fontWeight: 700 }}>
                                {stream_counts.WEB} Web · {stream_counts.ATLAS} Atlas
                            </div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                Playwright + EvidenceAtlas CSKH
                            </Text>
                        </Card>
                    </Col>
                    <Col xs={24} sm={24} md={12} lg={5}>
                        <Card
                            size="small"
                            hoverable
                            onClick={() => setCostDrawerOpen(true)}
                            extra={<Button type="link" size="small" style={{ padding: 0 }}>Chi tiết</Button>}
                        >
                            <Text type="secondary"><DollarOutlined /> Chi phí Token</Text>
                            <div style={{ fontSize: 20, fontWeight: 700 }}>
                                ${cost.cost_usd.toFixed(4)}
                            </div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                ~{cost.cost_vnd.toLocaleString()} đ · Cache {(cost.cache_hit_rate * 100).toFixed(1)}% ({budgetPct}% trần)
                            </Text>
                        </Card>
                    </Col>
                </Row>

                <Card size="small">
                    <Tabs
                        activeKey={activeTab}
                        onChange={(k) => setActiveTab(k)}
                        items={[
                            {
                                key: "overview",
                                label: "Tổng quan & Khu vực",
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        <UrbanZoneMap
                                            projectId={projectId}
                                            hasZoneMapImage={project.has_zone_map_image}
                                            topologyZones={zones}
                                        />
                                        <Card size="small" title={`Danh sách Sự vụ Cư dân ↔ BQL (${incidents.length})`}>
                                            <Table
                                                rowKey="incident_id"
                                                columns={incidentColumns}
                                                dataSource={incidents}
                                                pagination={{ pageSize: 8 }}
                                                scroll={{ x: "max-content" }}
                                                locale={{ emptyText: "Chưa phát sinh sự vụ nào" }}
                                            />
                                        </Card>
                                        <Card
                                            size="small"
                                            title={`Trạng thái ${agent_statuses.length} Tác nhân`}
                                            extra={
                                                <Space wrap size={8}>
                                                    {mostActiveAgent && (
                                                        <Tag
                                                            color="volcano"
                                                            icon={<FireOutlined />}
                                                            style={{ cursor: "pointer", marginInlineEnd: 0 }}
                                                            onClick={() => openPersonaTimeline(mostActiveAgent.agent_id)}
                                                        >
                                                            Tích cực nhất: #{mostActiveAgent.agent_id} {mostActiveAgent.full_name} (
                                                            {getAgentTotalActions(mostActiveAgent)} HĐ)
                                                        </Tag>
                                                    )}
                                                    <Segmented
                                                        size="small"
                                                        value={agentTableGroupFilter}
                                                        onChange={(val) =>
                                                            setAgentTableGroupFilter(
                                                                val as "ALL" | "BQL" | "RESIDENT" | "ACTIVE"
                                                            )
                                                        }
                                                        options={[
                                                            { label: "Tất cả", value: "ALL" },
                                                            { label: "BQL", value: "BQL" },
                                                            { label: "Cư dân", value: "RESIDENT" },
                                                            { label: "Có hoạt động", value: "ACTIVE" },
                                                        ]}
                                                    />
                                                    <Button
                                                        size="small"
                                                        icon={
                                                            agentSortMode === "ACTIVITY" ? (
                                                                <SortDescendingOutlined />
                                                            ) : (
                                                                <SortAscendingOutlined />
                                                            )
                                                        }
                                                        onClick={() =>
                                                            setAgentSortMode((prev) =>
                                                                prev === "ACTIVITY" ? "ID" : "ACTIVITY"
                                                            )
                                                        }
                                                    >
                                                        {agentSortMode === "ACTIVITY" ? "Tích cực nhất" : "Theo #ID"}
                                                    </Button>
                                                </Space>
                                            }
                                        >
                                            <Table
                                                rowKey="agent_id"
                                                columns={agentColumns}
                                                dataSource={displayedAgents}
                                                pagination={{ pageSize: 21 }}
                                                scroll={{ x: "max-content" }}
                                                onRow={(row) => ({
                                                    onClick: () => openPersonaTimeline(row.agent_id),
                                                    style: { cursor: "pointer" },
                                                })}
                                            />
                                        </Card>
                                    </Space>
                                ),
                            },
                            {
                                key: "web",
                                label: (
                                    <Space size={6}>
                                        <GlobalOutlined />
                                        <span>Thao tác Web QLTN ({webEvents.length})</span>
                                    </Space>
                                ),
                                children: webEvents.length === 0 ? (
                                    <Empty description="Chưa ghi nhận thao tác trình duyệt Playwright nào" />
                                ) : (
                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                        {webEvents.map((ev) => {
                                            const shot = ev.screenshot_file;
                                            return (
                                                <Card key={ev.seq} size="small">
                                                    <Row gutter={[12, 8]} align="middle" justify="space-between">
                                                        <Col xs={24} md={shot ? 17 : 24}>
                                                            <Space wrap size={6}>
                                                                <Tag color={ev.ok ? "blue" : "red"}>#{ev.seq} {ev.action}</Tag>
                                                                {(ev.screenshot_status === "LOADING_TIMEOUT" ||
                                                                    ev.screenshot_status === "LOADING_SPLASH_SUSPECTED") && (
                                                                    <Tag color="orange">
                                                                        {ev.screenshot_status === "LOADING_TIMEOUT"
                                                                            ? "Trang đang tải (Timeout)"
                                                                            : `Nghi màn hình Loading${ev.screenshot_bytes ? ` (${Math.round(ev.screenshot_bytes / 1024)}KB)` : ""}`}
                                                                    </Tag>
                                                                )}
                                                                <Text
                                                                    strong
                                                                    style={ev.agent_id !== null ? { cursor: "pointer", color: "#1d4ed8" } : undefined}
                                                                    onClick={
                                                                        ev.agent_id !== null
                                                                            ? () => openPersonaTimeline(ev.agent_id!)
                                                                            : undefined
                                                                    }
                                                                >
                                                                    {ev.agent_name}
                                                                </Text>
                                                                <Text type="secondary" style={{ fontSize: 12 }}>({ev.role_title})</Text>
                                                                {ev.sim_time && (
                                                                    <Tooltip title={ev.sim_time}>
                                                                        <Text type="secondary" style={{ fontSize: 11 }}>
                                                                            {formatEventSimTime(ev.sim_time)}
                                                                        </Text>
                                                                    </Tooltip>
                                                                )}
                                                            </Space>
                                                            <Paragraph style={{ margin: "6px 0 2px" }}>{ev.summary}</Paragraph>
                                                            {typeof ev.details?.url === "string" && ev.details.url && (
                                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                                    URL: {ev.details.url}
                                                                </Text>
                                                            )}
                                                        </Col>
                                                        {shot && (
                                                            <Col xs={24} md={7} style={{ textAlign: isMobile ? "left" : "right" }}>
                                                                <img
                                                                    src={getScreenshotUrl(projectId, runId, shot)}
                                                                    alt={ev.summary}
                                                                    loading="eager"
                                                                    style={{
                                                                        width: 160,
                                                                        height: 96,
                                                                        objectFit: "cover",
                                                                        backgroundColor: "#f1f5f9",
                                                                        borderRadius: 6,
                                                                        border: "1px solid #e5e7eb",
                                                                        cursor: "pointer",
                                                                    }}
                                                                    onClick={() => openLightbox(shot, `${ev.agent_name} — ${ev.summary}`)}
                                                                />
                                                            </Col>
                                                        )}
                                                    </Row>
                                                </Card>
                                            );
                                        })}
                                    </Space>
                                ),
                            },
                            {
                                key: "atlas",
                                label: (
                                    <Space size={6}>
                                        <ApiOutlined />
                                        <span>Hỏi đáp CSKH EvidenceAtlas ({atlasEvents.length})</span>
                                    </Space>
                                ),
                                children: (
                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                        <Card size="small" style={{ background: "#f8fafc" }}>
                                            <Row gutter={[12, 8]} align="middle" justify="space-between">
                                                <Col xs={24} md={12}>
                                                    <Space wrap size={8}>
                                                        <Text strong>
                                                            Tổng số lượt Hỏi Đáp CSKH: {stream_counts.ATLAS}
                                                        </Text>
                                                        {agentFilter !== "ALL" && (
                                                            <Checkbox
                                                                checked={exportFilteredOnly}
                                                                onChange={(e) => setExportFilteredOnly(e.target.checked)}
                                                            >
                                                                Chỉ xuất tác nhân đang lọc
                                                            </Checkbox>
                                                        )}
                                                    </Space>
                                                </Col>
                                                <Col
                                                    xs={24}
                                                    md={12}
                                                    style={{
                                                        display: "flex",
                                                        justifyContent: isMobile ? "flex-start" : "flex-end",
                                                    }}
                                                >
                                                    <Space wrap>
                                                        <Button
                                                            icon={<FileMarkdownOutlined />}
                                                            loading={exportingFormat === "markdown"}
                                                            disabled={
                                                                (exportFilteredOnly && agentFilter !== "ALL"
                                                                    ? atlasEvents.length
                                                                    : stream_counts.ATLAS) === 0
                                                            }
                                                            onClick={() => void handleExportAtlasQa("markdown")}
                                                        >
                                                            Xuất Markdown (.md)
                                                        </Button>
                                                        <Button
                                                            icon={<FileTextOutlined />}
                                                            loading={exportingFormat === "json"}
                                                            disabled={
                                                                (exportFilteredOnly && agentFilter !== "ALL"
                                                                    ? atlasEvents.length
                                                                    : stream_counts.ATLAS) === 0
                                                            }
                                                            onClick={() => void handleExportAtlasQa("json")}
                                                        >
                                                            Xuất JSON (.json)
                                                        </Button>
                                                    </Space>
                                                </Col>
                                            </Row>
                                        </Card>

                                        {atlasEvents.length === 0 ? (
                                            <Empty description="Chưa có lượt hỏi đáp EvidenceAtlas nào" />
                                        ) : (
                                            atlasEvents.map((ev) => {
                                                const q = formatAtlasText(String(ev.details?.question || ev.summary));
                                                const ans = String(ev.details?.answer || ev.details?.error || "");
                                                const routeHint = String(ev.details?.route_hint || "");
                                                const sessId = String(ev.details?.bot_session_id || "");
                                                const voted = feedbackSent[String(ev.seq)];
                                                return (
                                                    <Card key={ev.seq} size="small">
                                                        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                                                            <Space wrap size={6}>
                                                                <Tag color={ev.ok ? "cyan" : "red"}>#{ev.seq} {ev.ok ? "Atlas QA" : "Atlas Lỗi"}</Tag>
                                                                <Text
                                                                    strong
                                                                    style={ev.agent_id !== null ? { cursor: "pointer", color: "#1d4ed8" } : undefined}
                                                                    onClick={
                                                                        ev.agent_id !== null
                                                                            ? () => openPersonaTimeline(ev.agent_id!)
                                                                            : undefined
                                                                    }
                                                                >
                                                                    {ev.agent_name}
                                                                </Text>
                                                                {routeHint && <Tag>{routeHint}</Tag>}
                                                                {ev.sim_time && (
                                                                    <Tooltip title={ev.sim_time}>
                                                                        <Text type="secondary" style={{ fontSize: 11 }}>
                                                                            {formatEventSimTime(ev.sim_time)}
                                                                        </Text>
                                                                    </Tooltip>
                                                                )}
                                                                {sessId && <Text type="secondary" style={{ fontSize: 11 }}>session: {sessId.slice(0, 12)}</Text>}
                                                            </Space>
                                                            {ev.ok && (
                                                                <Space size={4}>
                                                                    <Button
                                                                        size="small"
                                                                        type={voted === "LIKE" ? "primary" : "default"}
                                                                        icon={<LikeOutlined />}
                                                                        onClick={() => void handleVote(ev, "LIKE")}
                                                                    >
                                                                        Hữu ích
                                                                    </Button>
                                                                    <Button
                                                                        size="small"
                                                                        danger={voted === "DISLIKE"}
                                                                        icon={<DislikeOutlined />}
                                                                        onClick={() => void handleVote(ev, "DISLIKE")}
                                                                    >
                                                                        Chưa ổn
                                                                    </Button>
                                                                </Space>
                                                            )}
                                                        </Space>
                                                        <div style={{ marginTop: 8, background: "#f8fafc", padding: 8, borderRadius: 6 }}>
                                                            <Text strong>Câu hỏi BQL:</Text> <Text>{q}</Text>
                                                        </div>
                                                        {ans && (
                                                            <div
                                                                style={{
                                                                    marginTop: 6,
                                                                    background: ev.ok === false ? "#fef2f2" : "#f0fdf4",
                                                                    border: ev.ok === false ? "1px solid #fecaca" : "1px solid #bbf7d0",
                                                                    padding: "8px 10px",
                                                                    borderRadius: 6,
                                                                }}
                                                            >
                                                                <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                                    {ev.ok === false ? "Lỗi phản hồi CSKH Atlas:" : "Trả lời CSKH Atlas:"}
                                                                </Text>
                                                                {ev.ok === false ? (
                                                                    <Text type="danger">{formatAtlasText(ans)}</Text>
                                                                ) : (
                                                                    <MarkdownWithMermaid content={ans} />
                                                                )}
                                                            </div>
                                                        )}
                                                    </Card>
                                                );
                                            })
                                        )}
                                    </Space>
                                ),
                            },
                            {
                                key: "comm",
                                label: (
                                    <Space size={6}>
                                        <CommentOutlined />
                                        <span>Giao tiếp Cư dân ↔ Lễ tân ({commEvents.length})</span>
                                    </Space>
                                ),
                                children: commEvents.length === 0 ? (
                                    <Empty description="Chưa ghi nhận hội thoại cư dân hay điều phối nội bộ nào" />
                                ) : (
                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                        {commEvents.map((ev) => (
                                            <Card key={ev.seq} size="small">
                                                <Space wrap size={6}>
                                                    <Tag color={ev.stream === "INCIDENT" ? "volcano" : "purple"}>
                                                        #{ev.seq} {ev.action}
                                                    </Tag>
                                                    <Text
                                                        strong
                                                        style={ev.agent_id !== null ? { cursor: "pointer", color: "#1d4ed8" } : undefined}
                                                        onClick={
                                                            ev.agent_id !== null
                                                                ? () => openPersonaTimeline(ev.agent_id!)
                                                                : undefined
                                                        }
                                                    >
                                                        {ev.agent_name}
                                                    </Text>
                                                    {ev.sim_time && (
                                                        <Tooltip title={ev.sim_time}>
                                                            <Text type="secondary" style={{ fontSize: 11 }}>
                                                                {formatEventSimTime(ev.sim_time)}
                                                            </Text>
                                                        </Tooltip>
                                                    )}
                                                </Space>
                                                <Paragraph style={{ margin: "6px 0 0" }}>{ev.summary}</Paragraph>
                                            </Card>
                                        ))}
                                    </Space>
                                ),
                            },
                            {
                                key: "competency",
                                label: (
                                    <Space size={6}>
                                        <ExperimentOutlined />
                                        <span>Đánh giá Năng lực & Tri thức</span>
                                    </Space>
                                ),
                                children: (
                                    <CompetencyEvaluationTab
                                        active={activeTab === "competency"}
                                        projectId={projectId}
                                        runId={runId}
                                        agentFilter={agentFilter}
                                        agents={agent_statuses}
                                        onInspectAgent={openPersonaTimeline}
                                        onClearAgentFilter={() => setAgentFilter("ALL")}
                                    />
                                ),
                            },
                        ]}
                    />
                </Card>
            </Space>

            <Drawer
                title="Chi tiết Chi phí Token & Ngân sách (USD / VND)"
                placement="right"
                styles={{ wrapper: { width: isMobile ? "100%" : 780 } }}
                open={costDrawerOpen}
                onClose={() => setCostDrawerOpen(false)}
            >
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <Descriptions bordered size="small" column={isMobile ? 1 : 2}>
                        <Descriptions.Item label="Tổng chi phí (USD)">${cost.cost_usd.toFixed(5)}</Descriptions.Item>
                        <Descriptions.Item label="Quy đổi VND">{cost.cost_vnd.toLocaleString()} đ (tỷ giá {cost.usd_to_vnd.toLocaleString()})</Descriptions.Item>
                        <Descriptions.Item label="Tiết kiệm nhờ Prompt Cache">
                            ${cost.saved_by_cache_usd.toFixed(5)} (~{cost.saved_by_cache_vnd.toLocaleString()} đ)
                        </Descriptions.Item>
                        <Descriptions.Item label="Tỷ lệ Cache Hit">{(cost.cache_hit_rate * 100).toFixed(1)}%</Descriptions.Item>
                        <Descriptions.Item label="Tổng Calls">{cost.totals.calls.toLocaleString()}</Descriptions.Item>
                        <Descriptions.Item label="Scope">{cost.scope || "current_process"}</Descriptions.Item>
                    </Descriptions>

                    <Card size="small" title="Bảng phân bổ theo từng Model LLM">
                        <Table
                            size="small"
                            rowKey="model"
                            columns={modelColumns}
                            dataSource={modelRows}
                            pagination={false}
                            scroll={{ x: "max-content" }}
                            locale={{ emptyText: "Chưa có dữ liệu tiêu thụ Token trong LLM_STATS.json" }}
                        />
                    </Card>
                </Space>
            </Drawer>

            <PersonaTimelineDrawer
                open={timelineAgentId !== null}
                projectId={projectId}
                runId={runId}
                agentId={timelineAgentId}
                agents={agent_statuses}
                onClose={() => setTimelineAgentId(null)}
                onSelectAgent={(aid) => setTimelineAgentId(aid)}
                onOpenLightbox={openLightbox}
            />

            <Modal
                open={Boolean(lightboxSrc)}
                title={lightboxCaption || "Ảnh chụp màn hình QLTN"}
                footer={null}
                centered
                destroyOnHidden
                zIndex={1200}
                getContainer={() => document.body}
                styles={{
                    mask: { backgroundColor: "rgba(15, 23, 42, 0.78)", backdropFilter: "blur(2px)" },
                    container: { backgroundColor: "#ffffff" },
                }}
                width={isMobile ? "96%" : 960}
                onCancel={() => setLightboxSrc(null)}
            >
                {lightboxSrc && (
                    <img
                        src={lightboxSrc}
                        alt={lightboxCaption}
                        style={{ width: "100%", maxHeight: "75vh", objectFit: "contain", borderRadius: 6 }}
                    />
                )}
            </Modal>
        </div>
    );
}
