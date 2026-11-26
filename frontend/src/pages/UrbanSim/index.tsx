import {
    ApiOutlined,
    CaretRightOutlined,
    DeleteOutlined,
    EyeOutlined,
    PauseOutlined,
    PlusOutlined,
    QuestionCircleOutlined,
    ReloadOutlined,
    SaveOutlined,
    TeamOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Col,
    Form,
    Grid,
    Input,
    InputNumber,
    Modal,
    Popconfirm,
    Popover,
    Row,
    Select,
    Space,
    Spin,
    Switch,
    Table,
    Tag,
    Typography,
    message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import {
    PreflightReport,
    urbanSimApi,
    UrbanSimProjectSummary,
    UrbanSimRun,
    UrbanSimZone,
} from "../../services/urbanSimApi";
import { UrbanZoneMap } from "./components/UrbanZoneMap";
import { RubricJsonEditor } from "./components/RubricJsonEditor";
import { MarkdownRichTextEditor } from "../../components/MarkdownRichTextEditor";

const { Title, Text } = Typography;

const RUN_STATUS_COLORS: Record<string, string> = {
    CREATED: "default",
    STARTING: "processing",
    RUNNING: "processing",
    PAUSING: "warning",
    PAUSED: "orange",
    RESUMING: "processing",
    COMPLETED: "success",
    COMPLETED_WITH_ERRORS: "gold",
    FAILED: "error",
};

interface ProjectFormValues {
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
    llm_config_id?: string | null;
    enable_competency_prepost_quiz?: boolean;
    competency_rubric_json?: string | null;
}

interface NewProjectValues {
    slug: string;
    name: string;
    description?: string;
    default_portal_url: string;
    seed_mulberrylane_template: boolean;
}

function formatDurationShort(totalSeconds: number): string {
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return "0 giây";
    const sec = Math.round(totalSeconds);
    const days = Math.floor(sec / 86400);
    const hours = Math.floor((sec % 86400) / 3600);
    const minutes = Math.floor((sec % 3600) / 60);
    const remSec = sec % 60;
    const parts: string[] = [];
    if (days > 0) parts.push(`${days} ngày`);
    if (hours > 0) parts.push(`${hours} giờ`);
    if (minutes > 0 && days === 0) parts.push(`${minutes} phút`);
    if (remSec > 0 && days === 0 && hours === 0) parts.push(`${remSec} giây`);
    return parts.join(" ") || `${sec} giây`;
}

function formatSimTimeWindow(startIso: string | undefined, totalSeconds: number): string | null {
    if (!startIso || !Number.isFinite(totalSeconds) || totalSeconds <= 0) return null;
    const raw = startIso.trim();
    const epochMs = Date.parse(raw);
    if (Number.isNaN(epochMs)) return null;

    // Giữ nguyên múi giờ ghi trong chuỗi ISO (vd +07:00, Z) để không lệch theo trình duyệt
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

    const fmt = (ms: number) => {
        const d = new Date(ms + offsetMinutes * 60_000);
        const hh = String(d.getUTCHours()).padStart(2, "0");
        const mm = String(d.getUTCMinutes()).padStart(2, "0");
        const dd = String(d.getUTCDate()).padStart(2, "0");
        const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
        return { time: `${hh}:${mm}`, date: `${dd}/${mo}` };
    };

    const startFmt = fmt(epochMs);
    const endFmt = fmt(epochMs + totalSeconds * 1000);
    if (startFmt.date === endFmt.date) {
        return `${startFmt.time} → ${endFmt.time} (${startFmt.date})`;
    }
    return `${startFmt.time} ${startFmt.date} → ${endFmt.time} ${endFmt.date}`;
}

function FieldHelpPopover({ title, content }: { title: string; content: React.ReactNode }) {
    return (
        <Popover
            trigger="click"
            title={title}
            content={<div style={{ maxWidth: 320, fontSize: 13, lineHeight: 1.5 }}>{content}</div>}
        >
            <QuestionCircleOutlined
                aria-label={`Giải thích: ${title}`}
                onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                }}
                style={{ color: "#1677ff", cursor: "pointer", marginLeft: 4, fontSize: 13 }}
            />
        </Popover>
    );
}

export default function UrbanSimConsolePage() {
    const navigate = useNavigate();
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;
    const [loading, setLoading] = useState(true);
    const [projects, setProjects] = useState<UrbanSimProjectSummary[]>([]);
    const [selectedId, setSelectedId] = useState<string>("");
    const [preflight, setPreflight] = useState<PreflightReport | null>(null);
    const [runs, setRuns] = useState<UrbanSimRun[]>([]);
    const [zones, setZones] = useState<UrbanSimZone[]>([]);
    const [llmConfigs, setLlmConfigs] = useState<Array<{ id: string; name: string; modelLabel: string }>>([]);
    const [saving, setSaving] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [form] = Form.useForm<ProjectFormValues>();
    const [createForm] = Form.useForm<NewProjectValues>();
    const watchedNumSteps = Form.useWatch("num_steps", form);
    const watchedTickSeconds = Form.useWatch("tick_seconds", form);
    const watchedStartTimeIso = Form.useWatch("start_time_iso", form);

    const selectedProject = projects.find((p) => p.id === selectedId) || null;
    const effectiveNumSteps = Number(watchedNumSteps ?? selectedProject?.num_steps ?? 0);
    const effectiveTickSeconds = Number(watchedTickSeconds ?? selectedProject?.tick_seconds ?? 0);
    const totalSimSeconds =
        effectiveNumSteps > 0 && effectiveTickSeconds > 0
            ? effectiveNumSteps * effectiveTickSeconds
            : 0;
    const perTickText = effectiveTickSeconds > 0 ? formatDurationShort(effectiveTickSeconds) : null;
    const totalSimText = totalSimSeconds > 0 ? formatDurationShort(totalSimSeconds) : null;
    const simWindowText = formatSimTimeWindow(
        watchedStartTimeIso ?? selectedProject?.start_time_iso,
        totalSimSeconds
    );
    const latestRun = runs[0] || null;
    const isLatestActive = Boolean(
        latestRun && ["STARTING", "RUNNING", "PAUSING", "RESUMING"].includes(latestRun.status)
    );
    const canResumeLatest = Boolean(
        latestRun && ["PAUSED", "FAILED", "COMPLETED_WITH_ERRORS"].includes(latestRun.status)
    );

    const loadProjectDetails = useCallback(async (projectId: string) => {
        const [projDetail, pf, runList, zoneRes] = await Promise.all([
            urbanSimApi.getProject(projectId),
            urbanSimApi.getPreflight(projectId),
            urbanSimApi.listRuns(projectId),
            urbanSimApi.listZones(projectId),
        ]);
        setProjects((prev) => prev.map((p) => (p.id === projectId ? projDetail : p)));
        setPreflight(pf);
        setRuns(runList);
        setZones(zoneRes.items || []);
        form.setFieldsValue({
            name: projDetail.name,
            description: projDetail.description,
            default_portal_url: projDetail.default_portal_url,
            router_type: projDetail.router_type,
            num_steps: projDetail.num_steps,
            tick_seconds: projDetail.tick_seconds,
            start_time_iso: projDetail.start_time_iso,
            max_react_turns: projDetail.max_react_turns,
            max_cost_usd_per_run: projDetail.max_cost_usd_per_run,
            pilot_mode: projDetail.pilot_mode,
            llm_config_id: projDetail.llm_config_id ?? undefined,
            enable_competency_prepost_quiz: Boolean(projDetail.enable_competency_prepost_quiz),
            competency_rubric_json: projDetail.competency_rubric_json ?? "",
        });
    }, [form]);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            try {
                const [list, llmList] = await Promise.all([
                    urbanSimApi.listProjects(),
                    urbanSimApi.listLlmConfigs().catch(() => []),
                ]);
                if (!active) return;
                setProjects(list);
                setLlmConfigs(
                    llmList.map((item) => {
                        const first = item.config?.[0];
                        const suffix = first?.model
                            ? ` (${first.provider || 'llm'}: ${first.model} · Reasoning: ${(first.thinking || 'off').toUpperCase()})`
                            : '';
                        return { id: item.id, name: item.name, modelLabel: `${item.name}${suffix}` };
                    })
                );
                if (list.length > 0) {
                    const targetId = list[0].id;
                    setSelectedId(targetId);
                    await loadProjectDetails(targetId);
                }
            } catch (err) {
                if (active) {
                    message.error(err instanceof Error ? err.message : "Không tải được danh sách dự án");
                }
            } finally {
                if (active) setLoading(false);
            }
        }
        void initLoad();
        return () => {
            active = false;
        };
    }, [loadProjectDetails]);

    useEffect(() => {
        if (!selectedId || !isLatestActive) return;
        const timer = window.setInterval(async () => {
            try {
                const [runList, pf] = await Promise.all([
                    urbanSimApi.listRuns(selectedId),
                    urbanSimApi.getPreflight(selectedId),
                ]);
                setRuns(runList);
                setPreflight(pf);
            } catch {
                // ignore transient polling failure
            }
        }, 3000);
        return () => window.clearInterval(timer);
    }, [selectedId, isLatestActive]);

    const handleSelectProject = async (pid: string) => {
        setSelectedId(pid);
        try {
            await loadProjectDetails(pid);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không tải được chi tiết dự án");
        }
    };

    const handleSaveConfig = async (values: ProjectFormValues) => {
        if (!selectedId) return;
        setSaving(true);
        try {
            const cleanRubric = (values.competency_rubric_json || "").trim();
            await urbanSimApi.updateProject(selectedId, {
                ...values,
                llm_config_id: values.llm_config_id ?? null,
                enable_competency_prepost_quiz: Boolean(values.enable_competency_prepost_quiz),
                competency_rubric_json: cleanRubric ? cleanRubric : null,
            });
            await loadProjectDetails(selectedId);
            message.success("Đã lưu cấu hình dự án vào Database (áp dụng ở Start/Restart tiếp theo).");
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu cấu hình thất bại");
        } finally {
            setSaving(false);
        }
    };

    const handleCreateProject = async (values: NewProjectValues) => {
        try {
            const created = await urbanSimApi.createProject(values);
            const list = await urbanSimApi.listProjects();
            setProjects(list);
            setSelectedId(created.id);
            setCreateModalOpen(false);
            createForm.resetFields();
            await loadProjectDetails(created.id);
            message.success(`Đã tạo dự án "${created.name}".`);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Tạo dự án thất bại");
        }
    };

    const handleRunAction = async (kind: "start" | "pause" | "resume" | "restart", runId?: string) => {
        if (!selectedId) return;
        setActionLoading(true);
        try {
            if (kind === "start") {
                const run = await urbanSimApi.startRun(selectedId);
                message.success(`Đã khởi chạy Run #${run.run_number}.`);
            } else if (kind === "pause" && runId) {
                await urbanSimApi.pauseRun(selectedId, runId);
                message.info("Đã gửi tín hiệu Pause — mô phỏng sẽ dừng sạch sau tick hiện tại.");
            } else if (kind === "resume" && runId) {
                const run = await urbanSimApi.resumeRun(selectedId, runId);
                message.success(`Đã tiếp tục Run #${run.run_number}.`);
            } else if (kind === "restart") {
                const run = await urbanSimApi.restartRun(selectedId);
                message.success(`Đã Restart áp dụng cấu hình DB mới vào Run #${run.run_number}.`);
            }
            await loadProjectDetails(selectedId);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Thao tác điều khiển Run thất bại");
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeleteRun = async (runId: string) => {
        if (!selectedId) return;
        try {
            await urbanSimApi.deleteRun(selectedId, runId);
            await loadProjectDetails(selectedId);
            message.success("Đã xóa Run và dọn toàn bộ thư mục artifacts.");
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể xóa Run");
        }
    };

    const runColumns: ColumnsType<UrbanSimRun> = [
        {
            title: "Run #",
            dataIndex: "run_number",
            key: "run_number",
            render: (val: number, rec) => (
                <Space direction="vertical" size={0}>
                    <Text strong>Run #{val}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>{rec.id}</Text>
                </Space>
            ),
        },
        {
            title: "Trạng thái",
            dataIndex: "status",
            key: "status",
            render: (st: string, rec) => (
                <Space direction="vertical" size={2}>
                    <Tag color={RUN_STATUS_COLORS[st] || "default"}>{st}</Tag>
                    {rec.pause_reason && <Text type="secondary" style={{ fontSize: 11 }}>{rec.pause_reason}</Text>}
                </Space>
            ),
        },
        {
            title: "Phạm vi",
            key: "scope",
            render: (_, rec) => (
                <Space direction="vertical" size={0}>
                    <Text>{rec.pilot_mode ? "Pilot" : "Đầy đủ"} ({rec.active_agent_count} tác nhân)</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>Router: {rec.router_type}</Text>
                </Space>
            ),
        },
        {
            title: "Tiến độ",
            key: "progress",
            render: (_, rec) => <Text>{rec.step_count} / {rec.total_steps} tick</Text>,
        },
        {
            title: "Chi phí Token",
            key: "cost",
            render: (_, rec) => (
                <Space direction="vertical" size={0}>
                    <Text>${Number(rec.total_cost_usd || 0).toFixed(4)}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>{Number(rec.total_tokens || 0).toLocaleString()} tokens</Text>
                </Space>
            ),
        },
        {
            title: "Hành động",
            key: "actions",
            render: (_, rec) => (
                <Space wrap>
                    <Button
                        size="small"
                        type="primary"
                        ghost
                        icon={<EyeOutlined />}
                        onClick={() => navigate(`/urban-sim/${selectedId}/runs/${rec.id}/monitor`)}
                    >
                        Live Monitor
                    </Button>
                    {["PAUSED", "FAILED", "COMPLETED_WITH_ERRORS"].includes(rec.status) && !isLatestActive && (
                        <Button
                            size="small"
                            icon={<CaretRightOutlined />}
                            onClick={() => handleRunAction("resume", rec.id)}
                        >
                            Resume
                        </Button>
                    )}
                    {!["STARTING", "RUNNING", "PAUSING", "RESUMING"].includes(rec.status) && (
                        <Popconfirm title="Xóa Run này và toàn bộ ảnh/log trên ổ đĩa?" onConfirm={() => handleDeleteRun(rec.id)}>
                            <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                    )}
                </Space>
            ),
        },
    ];

    if (loading) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}><Text type="secondary">Đang tải Trung tâm Mô phỏng Khu đô thị...</Text></div>
            </div>
        );
    }

    return (
        <div style={{ padding: "16px", maxWidth: 1380, margin: "0 auto" }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card size="small">
                    <Row gutter={[12, 12]} align="middle" justify="space-between">
                        <Col xs={24} lg={14}>
                            <Title level={4} style={{ margin: 0 }}>
                                Mô phỏng Vận hành Khu đô thị (Dynamic DB Control Plane)
                            </Title>
                            <Text type="secondary">
                                Cấu hình linh động 100% trên Database (Zero Beijing Map) — Hỗ trợ Start / Pause / Resume / Restart
                            </Text>
                        </Col>
                        <Col xs={24} lg={10} style={{ display: "flex", justifyContent: isMobile ? "flex-start" : "flex-end", minWidth: 0 }}>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, width: "100%", justifyContent: isMobile ? "flex-start" : "flex-end", minWidth: 0 }}>
                                <Select
                                    aria-label="Chọn dự án mô phỏng"
                                    style={{ flex: isMobile ? "1 1 100%" : "0 1 300px", minWidth: 0, maxWidth: "100%" }}
                                    value={selectedId}
                                    onChange={handleSelectProject}
                                    options={projects.map((p) => ({ value: p.id, label: p.name }))}
                                />
                                <Button icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
                                    Dự án mới
                                </Button>
                            </div>
                        </Col>
                    </Row>
                </Card>

                {selectedProject && (
                    <>
                        <Row gutter={[12, 12]}>
                            <Col xs={24} sm={12} md={6}>
                                <Card size="small" hoverable onClick={() => navigate(`/urban-sim/${selectedId}/personas`)}>
                                    <Text type="secondary">Ma trận Nhân sự & Cư dân</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
                                        {selectedProject.stats.bql_count} BQL · {selectedProject.stats.resident_count} Cư dân
                                    </div>
                                    <Tag color="blue" style={{ marginTop: 6 }} icon={<TeamOutlined />}>
                                        Tài khoản QLTN: {selectedProject.stats.bql_credentials_configured}/{selectedProject.stats.bql_count}
                                    </Tag>
                                </Card>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                                <Card size="small" hoverable onClick={() => navigate(`/urban-sim/${selectedId}/atlas`)}>
                                    <Text type="secondary">Cổng CSKH EvidenceAtlas</Text>
                                    <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                                        {selectedProject.stats.atlas_key_configured ? "Đã nhập API Key" : "Chưa nhập API Key"}
                                    </div>
                                    <Tag
                                        color={selectedProject.stats.atlas_verified_at ? "green" : "orange"}
                                        style={{ marginTop: 6 }}
                                        icon={<ApiOutlined />}
                                    >
                                        {selectedProject.stats.atlas_verified_at ? "Đã xác thực /api/v1/me" : "Cần kiểm tra kết nối"}
                                    </Tag>
                                </Card>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">Phạm vi Tác nhân mỗi Run</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
                                        {selectedProject.pilot_mode
                                            ? `Pilot (${selectedProject.stats.pilot_personas} tác nhân)`
                                            : `Đầy đủ (${selectedProject.stats.active_personas} tác nhân)`}
                                    </div>
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                        Router: {selectedProject.router_type === "react" ? "ReAct (Web UI)" : "CodeGen"}
                                    </Text>
                                </Card>
                            </Col>
                            <Col xs={24} sm={12} md={6}>
                                <Card size="small">
                                    <Text type="secondary">Ngân sách & Lần chạy mới nhất</Text>
                                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
                                        Trần ${selectedProject.max_cost_usd_per_run.toFixed(2)} / Run
                                    </div>
                                    {latestRun ? (
                                        <Tag color={RUN_STATUS_COLORS[latestRun.status] || "default"} style={{ marginTop: 6 }}>
                                            Run #{latestRun.run_number}: {latestRun.status}
                                        </Tag>
                                    ) : (
                                        <Text type="secondary" style={{ fontSize: 12 }}>Chưa có Run nào</Text>
                                    )}
                                </Card>
                            </Col>
                        </Row>

                        {preflight && preflight.warnings.length > 0 && (
                            <Alert
                                type={preflight.ready_for_l2_sandbox ? "info" : "warning"}
                                showIcon
                                message={
                                    preflight.ready_for_l2_sandbox
                                        ? "Sẵn sàng chạy thực tế Sandbox L2"
                                        : "Kiểm tra điều kiện sẵn sàng (Preflight)"
                                }
                                description={
                                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                                        {preflight.warnings.map((w, idx) => (
                                            <li key={idx}>{w}</li>
                                        ))}
                                    </ul>
                                }
                                action={
                                    <Space direction="vertical" size={4}>
                                        <Button size="small" onClick={() => navigate(`/urban-sim/${selectedId}/personas`)}>
                                            Cấu hình Tài khoản BQL
                                        </Button>
                                        <Button size="small" onClick={() => navigate(`/urban-sim/${selectedId}/atlas`)}>
                                            Cấu hình Atlas Key
                                        </Button>
                                    </Space>
                                }
                            />
                        )}

                        <Card size="small" title="Điều khiển Vòng đời Mô phỏng (Lifecycle Control)">
                            <Space wrap>
                                <Button
                                    type="primary"
                                    icon={<CaretRightOutlined />}
                                    loading={actionLoading}
                                    disabled={isLatestActive || !preflight?.ready_for_l1}
                                    onClick={() => handleRunAction("start")}
                                >
                                    Bắt đầu Run mới (Start)
                                </Button>
                                <Button
                                    icon={<PauseOutlined />}
                                    loading={actionLoading}
                                    disabled={!isLatestActive || !latestRun}
                                    onClick={() => latestRun && handleRunAction("pause", latestRun.id)}
                                >
                                    Tạm dừng (Pause)
                                </Button>
                                <Button
                                    icon={<CaretRightOutlined />}
                                    loading={actionLoading}
                                    disabled={!canResumeLatest || isLatestActive || !latestRun}
                                    onClick={() => latestRun && handleRunAction("resume", latestRun.id)}
                                >
                                    Tiếp tục (Resume)
                                </Button>
                                <Popconfirm
                                    title="Biên dịch cấu hình DB mới nhất và tạo Run mới?"
                                    onConfirm={() => handleRunAction("restart")}
                                    disabled={isLatestActive}
                                >
                                    <Button icon={<ReloadOutlined />} loading={actionLoading} disabled={isLatestActive}>
                                        Khởi chạy lại áp dụng DB (Restart)
                                    </Button>
                                </Popconfirm>
                                {latestRun && (
                                    <Button
                                        type="default"
                                        icon={<EyeOutlined />}
                                        onClick={() => navigate(`/urban-sim/${selectedId}/runs/${latestRun.id}/monitor`)}
                                    >
                                        Mở Live Monitor (Run #{latestRun.run_number})
                                    </Button>
                                )}
                                <Button icon={<TeamOutlined />} onClick={() => navigate(`/urban-sim/${selectedId}/personas`)}>
                                    Quản lý 21 Persona
                                </Button>
                                <Button icon={<ApiOutlined />} onClick={() => navigate(`/urban-sim/${selectedId}/atlas`)}>
                                    EvidenceAtlas & Guardrail
                                </Button>
                            </Space>
                        </Card>

                        <Card size="small" title="Cấu hình Dự án & Kịch bản (Lưu động Database)">
                            <Form form={form} layout="vertical" onFinish={handleSaveConfig}>
                                <Row gutter={12}>
                                    <Col xs={24} md={12}>
                                        <Form.Item
                                            name="name"
                                            label="Tên dự án"
                                            rules={[{ required: true, message: "Nhập tên dự án" }]}
                                            extra="Tên hiển thị trên danh sách chọn dự án, trang Giám sát Run và báo cáo đánh giá."
                                        >
                                            <Input placeholder="vd: Chung cư MulberryLane — Vận hành Toàn cảnh (21 Persona)" />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={12}>
                                        <Form.Item
                                            name="default_portal_url"
                                            label="URL Cổng QLTN mặc định"
                                            rules={[{ required: true, message: "Nhập URL phần mềm QLTN" }]}
                                            extra="Link đăng nhập phần mềm QLTN dùng chung cho nhóm BQL (trừ nhân sự cấu hình link riêng)."
                                        >
                                            <Input placeholder="vd: https://mulberrylane.sandbox.demego.vn" />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} sm={12} md={6}>
                                        <Form.Item
                                            name="router_type"
                                            label={
                                                <span>
                                                    Chiến lược Router
                                                    <FieldHelpPopover
                                                        title="Chiến lược điều phối công cụ (Router)"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    <strong>ReActRouter (Khuyên dùng):</strong> Tác nhân suy nghĩ từng bước, bấm Web QLTN hoặc hỏi CSKH theo phản hồi thực tế sau mỗi lượt.
                                                                </div>
                                                                <div>
                                                                    <strong>CodeGenRouter:</strong> Sinh mã để gọi công cụ hàng loạt, phù hợp kịch bản mô phỏng thuần túy không cần tương tác Web UI.
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra="Chọn ReAct cho kịch bản có thao tác trình duyệt Web QLTN."
                                        >
                                            <Select
                                                options={[
                                                    { value: "react", label: "ReActRouter (Khuyên dùng Web UI)" },
                                                    { value: "codegen", label: "CodeGenRouter" },
                                                ]}
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12} sm={6} md={4}>
                                        <Form.Item
                                            name="num_steps"
                                            label={
                                                <span>
                                                    Số bước (Ticks)
                                                    <FieldHelpPopover
                                                        title="Số bước mô phỏng (Ticks)"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Tổng số vòng lặp chạy nối tiếp của kịch bản. Ở mỗi Tick, tất cả tác nhân đang bật sẽ đọc tin mới, suy nghĩ và hành động 1 lượt.
                                                                </div>
                                                                <div>
                                                                    <strong>Công thức:</strong> Tổng thời gian giả lập = <code>Số bước × Giây/Tick</code>
                                                                    {totalSimText ? (
                                                                        <> (hiện tại: <strong>{effectiveNumSteps} × {perTickText} = {totalSimText}</strong>).</>
                                                                    ) : "."}
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra={totalSimText ? `Tổng: ${totalSimText} giả lập` : undefined}
                                            rules={[{ required: true }]}
                                        >
                                            <InputNumber min={1} max={200} style={{ width: "100%" }} />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12} sm={6} md={4}>
                                        <Form.Item
                                            name="tick_seconds"
                                            label={
                                                <span>
                                                    Giây / Tick
                                                    <FieldHelpPopover
                                                        title="Bước nhảy thời gian giả lập (Giây / Tick)"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Mỗi Tick cộng thêm số giây này vào <strong>đồng hồ giả lập</strong>{perTickText ? <> (hiện tại <strong>{effectiveTickSeconds}s = {perTickText}/tick</strong>)</> : ""}.
                                                                </div>
                                                                <div>
                                                                    <strong>Không chờ thời gian thực:</strong> hệ thống chạy xong thao tác của các tác nhân là sang Tick tiếp theo ngay, không ngủ chờ đủ {perTickText || "thời gian này"} ngoài đời.
                                                                </div>
                                                                <div>
                                                                    <strong>Đánh đổi:</strong> Giá trị càng nhỏ thì nhịp thời gian càng chi tiết nhưng cần nhiều Tick hơn → tốn nhiều token và chạy lâu hơn.
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra={perTickText ? `= ${perTickText} / tick` : undefined}
                                            rules={[{ required: true }]}
                                        >
                                            <InputNumber min={60} max={86400} style={{ width: "100%" }} />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12} sm={12} md={5}>
                                        <Form.Item
                                            name="max_cost_usd_per_run"
                                            label="Trần ngân sách (USD)"
                                            extra="Chạm ngưỡng này Run sẽ tự tạm dừng an toàn (vd: 5.0 USD)."
                                        >
                                            <InputNumber min={0.1} max={500} step={0.5} placeholder="vd: 5.0" style={{ width: "100%" }} />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12} sm={12} md={5}>
                                        <Form.Item
                                            name="pilot_mode"
                                            label="Chế độ Pilot (9 tác nhân)"
                                            valuePropName="checked"
                                            extra="Pilot chạy 9 tác nhân nòng cốt để test nhanh; Full chạy đủ 21 tác nhân."
                                        >
                                            <Switch checkedChildren="Pilot (9)" unCheckedChildren="Full (21)" />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={12}>
                                        <Form.Item
                                            name="llm_config_id"
                                            label="Cấu hình LLM liên thông (từ menu LLM)"
                                            extra={
                                                <Space wrap size={4} style={{ marginTop: 4 }}>
                                                    {preflight?.effective_llm_model && (
                                                        <Tag color="green" style={{ margin: 0 }}>
                                                            Model hiệu lực: {preflight.effective_llm_model}
                                                        </Tag>
                                                    )}
                                                    {preflight?.effective_llm_thinking && (
                                                        <Tag color="blue" style={{ margin: 0 }}>
                                                            Reasoning: {preflight.effective_llm_thinking.toUpperCase()}
                                                        </Tag>
                                                    )}
                                                    <Button
                                                        type="link"
                                                        size="small"
                                                        style={{ padding: 0, height: 'auto' }}
                                                        onClick={() => navigate('/llms')}
                                                    >
                                                        Mở trang Cấu hình AI / LLM
                                                    </Button>
                                                </Space>
                                            }
                                        >
                                            <Select
                                                allowClear
                                                placeholder="Mặc định (.env Runtime) hoặc chọn bộ LLM đã lưu"
                                                options={llmConfigs.map((l) => ({ value: l.id, label: l.modelLabel }))}
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={12}>
                                        <Form.Item
                                            name="start_time_iso"
                                            label={
                                                <span>
                                                    Mốc thời gian bắt đầu mô phỏng (ISO-8601)
                                                    <FieldHelpPopover
                                                        title="Đồng hồ giả lập vs Thời gian thực"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Mốc giờ khởi điểm đưa vào bối cảnh của tác nhân. Sau mỗi Tick, đồng hồ giả lập tự cộng thêm <strong>Giây / Tick</strong>.
                                                                </div>
                                                                <div>
                                                                    Lưu ý: Các phiếu/bản ghi tạo trực tiếp trên phần mềm QLTN sandbox vẫn mang thời gian thực của máy chủ tại lúc thao tác.
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra={
                                                simWindowText && perTickText
                                                    ? `Khung giờ giả lập: ${simWindowText} · ${effectiveNumSteps} ticks × ${perTickText}`
                                                    : undefined
                                            }
                                        >
                                            <Input placeholder="vd: 2026-06-15T08:00:00+07:00" />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={24}>
                                        <Form.Item
                                            name="description"
                                            label={
                                                <span>
                                                    Mô tả kịch bản (Markdown RichText)
                                                    <FieldHelpPopover
                                                        title="Mô tả kịch bản mô phỏng"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Tài liệu bối cảnh chung của dự án: mục tiêu vận hành, nhóm nhân sự tham gia, phân hệ phần mềm cần thử nghiệm và quy trình phối hợp BQL ↔ Cư dân ↔ EvidenceAtlas.
                                                                </div>
                                                                <div>
                                                                    <strong>Ví dụ cấu trúc nên viết:</strong>
                                                                    <br />• <code>## Bối cảnh &amp; Mục tiêu</code> (link cổng QLTN, quy mô khu đô thị)
                                                                    <br />• <code>### Kịch bản chính</code> (danh sách tình huống phát sinh)
                                                                    <br />• <code>```mermaid</code> (sơ đồ luồng xử lý nếu cần)
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra="Dùng Markdown để trình bày bối cảnh, mục tiêu vận hành, danh sách tình huống hoặc sơ đồ luồng (bấm Song song / Xem trước để kiểm tra định dạng)."
                                        >
                                            <MarkdownRichTextEditor
                                                minRows={5}
                                                maxRows={14}
                                                defaultMode="split"
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={10}>
                                        <Form.Item
                                            name="enable_competency_prepost_quiz"
                                            label={
                                                <span>
                                                    Bật khảo sát Tri thức Pre/Post Quiz (Marx-Cummings c)
                                                    <FieldHelpPopover
                                                        title="Cơ chế Khảo sát Tri thức Pre/Post Quiz"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Khi bật, hệ thống tự động chèn <strong>2 bài trắc nghiệm</strong> vào Run mới cho các nhân sự BQL được cấp quyền dùng phần mềm (<code>software_access_enabled</code>):
                                                                </div>
                                                                <div>
                                                                    <strong>1. Pre-Test (Tick 0):</strong> Đo kiến thức nền trước khi tác nhân bắt đầu thao tác QLTN.
                                                                </div>
                                                                <div>
                                                                    <strong>2. Post-Test (Sau Tick cuối):</strong> Chế độ <em>Open-Notes Retrieval</em> — tác nhân được phép tra cứu trí nhớ &amp; ghi chú <code>notes/</code> đã tích lũy sau khi dùng QLTN và hỏi CSKH EvidenceAtlas.
                                                                </div>
                                                                <div>
                                                                    <strong>Mã trả lời:</strong> <code>OPT_A..OPT_D</code> hoặc <code>CHUA_BIET</code> (đo độ trung thực nhận thức, tránh đoán bừa) để tính chỉ số tiến bộ chuẩn hóa <strong>Marx-Cummings c</strong> ở tab <em>Đánh giá Năng lực</em>.
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            valuePropName="checked"
                                            extra="Ví dụ: Tick 0 tác nhân chọn CHUA_BIET/sai (Pre 20%) → sau khi hỏi CSKH Atlas và thao tác QLTN đạt Post 83% (c = +0.79). Chỉ áp dụng ở Run mới cho nhóm BQL dùng phần mềm."
                                        >
                                            <Switch checkedChildren="Bật Pre/Post" unCheckedChildren="Tắt" />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={24} md={14}>
                                        <Form.Item
                                            name="competency_rubric_json"
                                            label={
                                                <span>
                                                    Rubric phân hệ &amp; bộ câu hỏi tùy biến (JSON, &lt;= 64KB)
                                                    <FieldHelpPopover
                                                        title="Cách cấu hình Rubric JSON & Bộ câu hỏi"
                                                        content={
                                                            <Space direction="vertical" size={6}>
                                                                <div>
                                                                    Dùng để tùy biến <strong>quy chuẩn đánh giá từng vai trò BQL</strong> (<code>roles</code>) và <strong>ngân hàng câu hỏi Pre/Post Quiz</strong> (<code>quiz_questions</code>) cho dự án mới ngoài MulberryLane.
                                                                </div>
                                                                <div>
                                                                    <strong>Nếu để trống:</strong> Dùng mặc định 7 vai trò MulberryLane (+ fallback <code>BQL_STAFF</code>) và 6 câu hỏi chuẩn QLTN v2.
                                                                </div>
                                                                <div>
                                                                    <strong>Mẹo nhanh:</strong> Bấm nút <strong>Chèn mẫu JSON</strong> hoặc <strong>Xem cấu trúc</strong> ngay trên thanh công cụ khung nhập để xem mô tả chi tiết từng trường và áp dụng mẫu sẵn.
                                                                </div>
                                                            </Space>
                                                        }
                                                    />
                                                </span>
                                            }
                                            extra="Để trống để dùng chuẩn mặc định MulberryLane (7 role_code + fallback BQL_STAFF & 6 câu hỏi). Nếu tùy biến theo hệ thống mới, bấm 'Chèn mẫu JSON' hoặc 'Xem cấu trúc' ở thanh trên."
                                        >
                                            <RubricJsonEditor />
                                        </Form.Item>
                                    </Col>
                                </Row>
                                <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
                                    Lưu cấu hình vào Database
                                </Button>
                            </Form>
                        </Card>

                        <UrbanZoneMap
                            projectId={selectedProject.id}
                            hasZoneMapImage={selectedProject.has_zone_map_image}
                            staticZones={zones}
                            editableMap
                            onMapUpdated={() => void loadProjectDetails(selectedProject.id)}
                        />

                        <Card size="small" title={`Lịch sử các lần chạy (${runs.length})`}>
                            <Table
                                rowKey="id"
                                columns={runColumns}
                                dataSource={runs}
                                pagination={{ pageSize: 6 }}
                                scroll={{ x: "max-content" }}
                                locale={{ emptyText: "Chưa có lần chạy nào. Hãy bấm Bắt đầu Run mới." }}
                            />
                        </Card>
                    </>
                )}
            </Space>

            <Modal
                title="Tạo dự án mô phỏng khu đô thị mới"
                open={createModalOpen}
                width={isMobile ? "96vw" : 760}
                onCancel={() => setCreateModalOpen(false)}
                onOk={() => createForm.submit()}
                okText="Tạo dự án"
                cancelText="Hủy"
            >
                <Form
                    form={createForm}
                    layout="vertical"
                    initialValues={{
                        default_portal_url: "https://mulberrylane.sandbox.demego.vn",
                        seed_mulberrylane_template: true,
                    }}
                    onFinish={handleCreateProject}
                >
                    <Form.Item
                        name="slug"
                        label="Mã định danh (slug)"
                        rules={[{ required: true, message: "Nhập slug không dấu (vd: royal-city)" }]}
                        extra="Dùng làm mã định danh duy nhất trên URL và thư mục lưu trữ (chỉ gồm chữ thường, số, dấu gạch ngang)."
                    >
                        <Input placeholder="vd: khu-do-thi-royal-city" />
                    </Form.Item>
                    <Form.Item
                        name="name"
                        label="Tên dự án"
                        rules={[{ required: true, message: "Nhập tên dự án" }]}
                        extra="Tên đầy đủ dễ nhận biết khi chuyển đổi giữa nhiều dự án mô phỏng."
                    >
                        <Input placeholder="vd: Chung cư Royal City — Kiểm thử BQL mới" />
                    </Form.Item>
                    <Form.Item
                        name="description"
                        label="Mô tả kịch bản (Markdown RichText)"
                        extra="Ghi rõ bối cảnh vận hành, mục tiêu thử nghiệm hoặc kịch bản mẫu bằng Markdown."
                    >
                        <MarkdownRichTextEditor
                            minRows={4}
                            maxRows={10}
                            defaultMode="edit"
                            allowFullscreen={false}
                        />
                    </Form.Item>
                    <Form.Item
                        name="default_portal_url"
                        label="URL phần mềm QLTN mặc định"
                        extra="Địa chỉ trang web QLTN sandbox mà các tác nhân BQL sẽ đăng nhập để thao tác."
                    >
                        <Input placeholder="vd: https://mulberrylane.sandbox.demego.vn" />
                    </Form.Item>
                    <Form.Item
                        name="seed_mulberrylane_template"
                        label="Nạp sẵn khung 21 Persona & 9 Zone mẫu từ MulberryLane"
                        valuePropName="checked"
                        extra="Bật để tạo sẵn 11 nhân sự BQL + 10 cư dân và sơ đồ 9 khu vực mẫu, giúp chạy thử ngay."
                    >
                        <Switch />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
}
