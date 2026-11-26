import {
    ApiOutlined,
    ArrowLeftOutlined,
    CheckCircleOutlined,
    SafetyCertificateOutlined,
    SaveOutlined,
    ThunderboltOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Checkbox,
    Col,
    Form,
    Input,
    InputNumber,
    Row,
    Select,
    Space,
    Spin,
    Switch,
    Tag,
    Typography,
    message,
} from "antd";
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import {
    AtlasTestResult,
    urbanSimApi,
    UrbanSimAtlasConfig,
    UrbanSimProjectSummary,
} from "../../services/urbanSimApi";

const { Title, Text } = Typography;
const { TextArea } = Input;

interface AtlasFormValues {
    enabled: boolean;
    atlas_api_url: string;
    atlas_api_key?: string;
    clear_api_key?: boolean;
    actor_persona: "END_USER" | "ADMIN" | "OPERATOR";
    source_mode: "FEDERATED_AUTO" | "LOCAL_ONLY" | "HYBRID";
    attach_screenshot_on_ask: boolean;
    quota_per_min: number;
    max_asks_per_tick: number;
    guardrail_mode: "SAFE_WRITE" | "READ_ONLY" | "FULL_RBAC";
    record_prefix: string;
    blocked_keywords_text: string;
}

export default function AtlasConfigPage() {
    const { projectId = "" } = useParams();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [project, setProject] = useState<UrbanSimProjectSummary | null>(null);
    const [atlas, setAtlas] = useState<UrbanSimAtlasConfig | null>(null);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<AtlasTestResult | null>(null);
    const [testError, setTestError] = useState<string | null>(null);
    const [form] = Form.useForm<AtlasFormValues>();

    const reloadData = useCallback(async () => {
        if (!projectId) return;
        const [proj, cfg] = await Promise.all([
            urbanSimApi.getProject(projectId),
            urbanSimApi.getAtlasConfig(projectId),
        ]);
        setProject(proj);
        setAtlas(cfg);
        form.setFieldsValue({
            enabled: cfg.enabled,
            atlas_api_url: cfg.atlas_api_url,
            atlas_api_key: "",
            clear_api_key: false,
            actor_persona: cfg.actor_persona,
            source_mode: cfg.source_mode,
            attach_screenshot_on_ask: cfg.attach_screenshot_on_ask,
            quota_per_min: cfg.quota_per_min,
            max_asks_per_tick: cfg.max_asks_per_tick,
            guardrail_mode: cfg.guardrail_mode,
            record_prefix: cfg.record_prefix,
            blocked_keywords_text: (cfg.blocked_keywords || []).join("\n"),
        });
    }, [form, projectId]);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            try {
                await reloadData();
            } catch (err) {
                if (active) {
                    message.error(err instanceof Error ? err.message : "Không tải được cấu hình EvidenceAtlas");
                }
            } finally {
                if (active) setLoading(false);
            }
        }
        void initLoad();
        return () => {
            active = false;
        };
    }, [reloadData]);

    const handleSave = async (values: AtlasFormValues) => {
        if (!projectId) return;
        setSaving(true);
        const keywords = (values.blocked_keywords_text || "")
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean);
        const payload: Record<string, unknown> = {
            enabled: values.enabled,
            atlas_api_url: values.atlas_api_url,
            actor_persona: values.actor_persona,
            source_mode: values.source_mode,
            attach_screenshot_on_ask: values.attach_screenshot_on_ask,
            quota_per_min: values.quota_per_min,
            max_asks_per_tick: values.max_asks_per_tick,
            guardrail_mode: values.guardrail_mode,
            record_prefix: values.record_prefix,
            blocked_keywords: keywords,
        };
        if (values.clear_api_key) {
            payload.clear_api_key = true;
        } else if (values.atlas_api_key && values.atlas_api_key.trim()) {
            payload.atlas_api_key = values.atlas_api_key.trim();
        }
        try {
            await urbanSimApi.updateAtlasConfig(projectId, payload);
            await reloadData();
            message.success("Đã lưu cấu hình EvidenceAtlas & Guardrail vào Database.");
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu cấu hình thất bại");
        } finally {
            setSaving(false);
        }
    };

    const handleTestConnection = async () => {
        if (!projectId) return;
        setTesting(true);
        setTestError(null);
        setTestResult(null);
        const values = form.getFieldsValue();
        try {
            const res = await urbanSimApi.testAtlasConnection(projectId, {
                atlas_api_url: values.atlas_api_url,
                atlas_api_key: values.atlas_api_key?.trim() || undefined,
            });
            setTestResult(res);
            if (res.ok) {
                message.success("Kết nối EvidenceAtlas (/api/v1/me) thành công!");
                await reloadData();
            } else {
                setTestError(res.error || "Kết nối Atlas thất bại");
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Lỗi kiểm tra kết nối";
            setTestError(msg);
            message.error(msg);
        } finally {
            setTesting(false);
        }
    };

    if (loading) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}><Text type="secondary">Đang tải cấu hình EvidenceAtlas...</Text></div>
            </div>
        );
    }

    return (
        <div style={{ padding: "16px", maxWidth: 1120, margin: "0 auto" }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card size="small">
                    <Row gutter={[12, 12]} align="middle" justify="space-between">
                        <Col xs={24} md={16}>
                            <Space wrap>
                                <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/urban-sim")}>
                                    Trung tâm Mô phỏng
                                </Button>
                                <Title level={4} style={{ margin: 0 }}>
                                    Cổng CSKH EvidenceAtlas & Sandbox Guardrail
                                </Title>
                            </Space>
                            <div style={{ marginTop: 4 }}>
                                <Text type="secondary">Dự án: {project?.name}</Text>
                            </div>
                        </Col>
                        <Col xs={24} md={8} style={{ display: "flex", justifyContent: "flex-end" }}>
                            {atlas?.last_verified_at ? (
                                <Tag color="green" icon={<CheckCircleOutlined />}>
                                    Đã xác thực: {atlas.last_verified_project_name || atlas.last_verified_project_id}
                                </Tag>
                            ) : (
                                <Tag color="orange" icon={<ApiOutlined />}>Chưa xác thực kết nối</Tag>
                            )}
                        </Col>
                    </Row>
                </Card>

                {testError && (
                    <Alert
                        type="error"
                        showIcon
                        closable
                        onClose={() => setTestError(null)}
                        message="Kiểm tra kết nối EvidenceAtlas bị từ chối / thất bại"
                        description={testError}
                    />
                )}

                {testResult && testResult.ok && (
                    <Alert
                        type="success"
                        showIcon
                        message={`Kết nối thành công tới dự án EvidenceAtlas: ${testResult.project_name || testResult.bound_project_id}`}
                        description={
                            <Space direction="vertical" size={2}>
                                <Text>bound_project_id: <Text code>{testResult.bound_project_id || "-"}</Text></Text>
                                <Text>scopes: {(testResult.scopes || []).join(", ") || "mặc định"}</Text>
                                <Text>verified_at: {testResult.verified_at}</Text>
                            </Space>
                        }
                    />
                )}

                <Form form={form} layout="vertical" onFinish={handleSave}>
                    <Row gutter={[12, 12]}>
                        <Col xs={24} lg={14}>
                            <Card
                                size="small"
                                title={<Space><ApiOutlined /><span>EvidenceAtlas Public API v1 (CSKH Nhà cung cấp)</span></Space>}
                            >
                                <Form.Item name="enabled" label="Bật hỏi đáp CSKH EvidenceAtlas cho BQL" valuePropName="checked">
                                    <Switch />
                                </Form.Item>
                                <Form.Item
                                    name="atlas_api_url"
                                    label="Atlas API URL"
                                    rules={[{ required: true, message: "Nhập Atlas URL" }]}
                                >
                                    <Input placeholder="https://atlas.demego.vn" />
                                </Form.Item>
                                <Form.Item
                                    name="atlas_api_key"
                                    label="Project API Key (header X-API-KEY)"
                                >
                                    <Input.Password
                                        autoComplete="new-password"
                                        placeholder={atlas?.has_api_key ? `${atlas.api_key_masked} (đã lưu mã hóa)` : "Nhập sk-proj-... hoặc Project API Key của Atlas"}
                                    />
                                </Form.Item>
                                {atlas?.has_api_key && (
                                    <Form.Item name="clear_api_key" valuePropName="checked">
                                        <Checkbox>Xóa API Key đã lưu khỏi Database</Checkbox>
                                    </Form.Item>
                                )}

                                <Row gutter={12}>
                                    <Col xs={12}>
                                        <Form.Item name="actor_persona" label="actor_persona">
                                            <Select
                                                options={[
                                                    { value: "END_USER", label: "END_USER (Khuyên dùng)" },
                                                    { value: "OPERATOR", label: "OPERATOR" },
                                                    { value: "ADMIN", label: "ADMIN" },
                                                ]}
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12}>
                                        <Form.Item name="source_mode" label="source_mode">
                                            <Select
                                                options={[
                                                    { value: "FEDERATED_AUTO", label: "FEDERATED_AUTO (Khuyên dùng)" },
                                                    { value: "LOCAL_ONLY", label: "LOCAL_ONLY" },
                                                    { value: "HYBRID", label: "HYBRID" },
                                                ]}
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12}>
                                        <Form.Item name="quota_per_min" label="Quota toàn cục (req/phút)">
                                            <InputNumber min={1} max={30} style={{ width: "100%" }} />
                                        </Form.Item>
                                    </Col>
                                    <Col xs={12}>
                                        <Form.Item name="max_asks_per_tick" label="Số câu hỏi tối đa / bước / người">
                                            <InputNumber min={1} max={10} style={{ width: "100%" }} />
                                        </Form.Item>
                                    </Col>
                                </Row>

                                <Form.Item
                                    name="attach_screenshot_on_ask"
                                    label="Đính kèm ảnh chụp màn hình QLTN gần nhất khi hỏi (<= 1.5MB)"
                                    valuePropName="checked"
                                >
                                    <Switch />
                                </Form.Item>

                                <Space wrap>
                                    <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
                                        Lưu cấu hình Atlas
                                    </Button>
                                    <Button
                                        icon={<ThunderboltOutlined />}
                                        loading={testing}
                                        onClick={() => void handleTestConnection()}
                                    >
                                        Kiểm tra kết nối (/api/v1/me)
                                    </Button>
                                </Space>
                            </Card>
                        </Col>

                        <Col xs={24} lg={10}>
                            <Card
                                size="small"
                                title={<Space><SafetyCertificateOutlined /><span>Guardrail An toàn trên QLTN Sandbox</span></Space>}
                            >
                                <Form.Item name="guardrail_mode" label="Chế độ bảo vệ thao tác Web">
                                    <Select
                                        options={[
                                            { value: "SAFE_WRITE", label: "SAFE_WRITE (Khuyên dùng: gắn tiền tố & chặn xóa/chốt sổ)" },
                                            { value: "READ_ONLY", label: "READ_ONLY (Chỉ cho xem, chặn mọi nút ghi)" },
                                            { value: "FULL_RBAC", label: "FULL_RBAC (Theo quyền tài khoản QLTN)" },
                                        ]}
                                    />
                                </Form.Item>
                                <Form.Item name="record_prefix" label="Tiền tố đánh dấu bản ghi mô phỏng">
                                    <Input placeholder="[SIM-BQL]" />
                                </Form.Item>
                                <Form.Item
                                    name="blocked_keywords_text"
                                    label="Từ khóa nút nguy hiểm bị chặn cứng trong SAFE_WRITE (mỗi dòng 1 cụm từ)"
                                >
                                    <TextArea rows={7} />
                                </Form.Item>
                            </Card>
                        </Col>
                    </Row>
                </Form>
            </Space>
        </div>
    );
}
