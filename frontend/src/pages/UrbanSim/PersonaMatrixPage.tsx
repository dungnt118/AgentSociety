import {
    ArrowLeftOutlined,
    CheckCircleOutlined,
    DeleteOutlined,
    EditOutlined,
    LockOutlined,
    PlusOutlined,
    SearchOutlined,
    WarningOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Card,
    Checkbox,
    Col,
    Drawer,
    Form,
    Grid,
    Input,
    InputNumber,
    Popconfirm,
    Row,
    Segmented,
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
import { useNavigate, useParams } from "react-router";
import {
    urbanSimApi,
    UrbanSimPersona,
    UrbanSimProjectSummary,
    UrbanSimZone,
} from "../../services/urbanSimApi";

const { Title, Text } = Typography;
const { TextArea } = Input;

interface PersonaFormValues {
    agent_id?: number;
    full_name: string;
    role_code: string;
    role_title: string;
    department: string;
    group_type: "BQL" | "RESIDENT";
    software_access_enabled: boolean;
    is_pilot_member: boolean;
    is_active: boolean;
    home_zone: string;
    portal_url?: string;
    login_username?: string;
    login_password?: string;
    clear_password?: boolean;
    domain_knowledge_prompt: string;
    initial_tasks_text: string;
}

export default function PersonaMatrixPage() {
    const { projectId = "" } = useParams();
    const navigate = useNavigate();
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;

    const [loading, setLoading] = useState(true);
    const [project, setProject] = useState<UrbanSimProjectSummary | null>(null);
    const [personas, setPersonas] = useState<UrbanSimPersona[]>([]);
    const [zones, setZones] = useState<UrbanSimZone[]>([]);
    const [groupFilter, setGroupFilter] = useState<"ALL" | "BQL" | "RESIDENT">("ALL");
    const [searchText, setSearchText] = useState("");
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [editing, setEditing] = useState<UrbanSimPersona | null>(null);
    const [saving, setSaving] = useState(false);
    const [syncingAccounting, setSyncingAccounting] = useState(false);
    const [form] = Form.useForm<PersonaFormValues>();

    const reloadData = useCallback(async () => {
        if (!projectId) return;
        const [proj, perList, zoneRes] = await Promise.all([
            urbanSimApi.getProject(projectId),
            urbanSimApi.listPersonas(projectId),
            urbanSimApi.listZones(projectId),
        ]);
        setProject(proj);
        setPersonas(perList);
        setZones(zoneRes.items || []);
    }, [projectId]);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            try {
                await reloadData();
            } catch (err) {
                if (active) {
                    message.error(err instanceof Error ? err.message : "Không tải được danh sách Persona");
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

    const openEditDrawer = (persona: UrbanSimPersona | null) => {
        setEditing(persona);
        if (persona) {
            form.setFieldsValue({
                agent_id: persona.agent_id,
                full_name: persona.full_name,
                role_code: persona.role_code,
                role_title: persona.role_title,
                department: persona.department,
                group_type: persona.group_type,
                software_access_enabled: persona.software_access_enabled,
                is_pilot_member: persona.is_pilot_member,
                is_active: persona.is_active,
                home_zone: persona.home_zone,
                portal_url: persona.portal_url || "",
                login_username: persona.login_username || "",
                login_password: "",
                clear_password: false,
                domain_knowledge_prompt: persona.domain_knowledge_prompt,
                initial_tasks_text: (persona.initial_tasks || []).join("\n"),
            });
        } else {
            form.setFieldsValue({
                full_name: "",
                role_code: "BQL_STAFF",
                role_title: "Nhân sự BQL",
                department: "Ban Quản lý",
                group_type: "BQL",
                software_access_enabled: true,
                is_pilot_member: false,
                is_active: true,
                home_zone: zones[0]?.zone_key || "LOBBY_MAIN",
                portal_url: project?.default_portal_url || "",
                login_username: "",
                login_password: "",
                clear_password: false,
                domain_knowledge_prompt: "",
                initial_tasks_text: "",
            });
        }
        setDrawerOpen(true);
    };

    const handleSubmit = async (values: PersonaFormValues) => {
        if (!projectId) return;
        setSaving(true);
        const tasks = (values.initial_tasks_text || "")
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean);
        const payload: Record<string, unknown> = {
            full_name: values.full_name,
            role_code: values.role_code,
            role_title: values.role_title,
            department: values.department,
            group_type: values.group_type,
            software_access_enabled: values.group_type === "RESIDENT" ? false : values.software_access_enabled,
            is_pilot_member: values.is_pilot_member,
            is_active: values.is_active,
            home_zone: values.home_zone,
            portal_url: (values.portal_url ?? "").trim(),
            login_username: (values.login_username ?? "").trim(),
            domain_knowledge_prompt: values.domain_knowledge_prompt,
            initial_tasks: tasks,
        };
        if (values.clear_password) {
            payload.clear_password = true;
        } else if (values.login_password && values.login_password.trim()) {
            payload.login_password = values.login_password.trim();
        }
        if (!editing && values.agent_id) {
            payload.agent_id = values.agent_id;
        }

        try {
            if (editing) {
                await urbanSimApi.updatePersona(projectId, editing.id, payload);
                message.success(`Đã cập nhật "${values.full_name}".`);
            } else {
                await urbanSimApi.createPersona(projectId, payload);
                message.success(`Đã thêm Persona "${values.full_name}".`);
            }
            setDrawerOpen(false);
            await reloadData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu Persona thất bại");
        } finally {
            setSaving(false);
        }
    };

    const handleQuickToggle = async (persona: UrbanSimPersona, field: "is_active" | "is_pilot_member", val: boolean) => {
        try {
            await urbanSimApi.updatePersona(projectId, persona.id, { [field]: val });
            await reloadData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Cập nhật nhanh thất bại");
        }
    };

    const handleDelete = async (personaId: string) => {
        try {
            await urbanSimApi.deletePersona(projectId, personaId);
            await reloadData();
            message.success("Đã xóa Persona.");
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xóa Persona thất bại");
        }
    };

    const handleSyncAccountingPersona = async () => {
        if (!projectId) return;
        setSyncingAccounting(true);
        try {
            const res = await urbanSimApi.syncAccountingPersona(projectId);
            await reloadData();
            if (res.created) {
                message.success(`Đã bổ sung vai trò Kế toán Công nợ (#${res.persona.agent_id} ${res.persona.full_name}).`);
            } else {
                message.info(`Dự án đã có vai trò Kế toán Công nợ (#${res.persona.agent_id} ${res.persona.full_name}).`);
            }
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Đồng bộ Kế toán Công nợ thất bại");
        } finally {
            setSyncingAccounting(false);
        }
    };

    const filtered = personas.filter((p) => {
        if (groupFilter !== "ALL" && p.group_type !== groupFilter) return false;
        if (!searchText.trim()) return true;
        const q = searchText.trim().toLowerCase();
        return (
            p.full_name.toLowerCase().includes(q) ||
            p.role_title.toLowerCase().includes(q) ||
            p.department.toLowerCase().includes(q) ||
            p.home_zone.toLowerCase().includes(q) ||
            String(p.agent_id) === q
        );
    });

    const columns: ColumnsType<UrbanSimPersona> = [
        {
            title: "ID",
            dataIndex: "agent_id",
            key: "agent_id",
            width: 64,
            render: (id: number) => <Text strong>#{id}</Text>,
        },
        {
            title: "Họ tên & Chức danh",
            key: "identity",
            render: (_, p) => (
                <Space direction="vertical" size={0}>
                    <Text strong>{p.full_name}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                        {p.role_title} · {p.department}
                    </Text>
                </Space>
            ),
        },
        {
            title: "Nhóm & Khu vực",
            key: "group",
            render: (_, p) => (
                <Space direction="vertical" size={2}>
                    <Tag color={p.group_type === "BQL" ? "blue" : "purple"}>
                        {p.group_type === "BQL" ? "Ban Quản lý (BQL)" : "Cư dân Chủ hộ"}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 11 }}>{p.home_zone}</Text>
                </Space>
            ),
        },
        {
            title: "Phần mềm QLTN & Tài khoản",
            key: "portal",
            render: (_, p) => {
                if (!p.software_access_enabled || p.group_type === "RESIDENT") {
                    return (
                        <Tag icon={<LockOutlined />} color="default">
                            Không dùng phần mềm (Chỉ giao tiếp Lễ tân)
                        </Tag>
                    );
                }
                return (
                    <Space direction="vertical" size={2}>
                        <Text style={{ fontSize: 12 }}>
                            URL: {p.portal_url || project?.default_portal_url}
                        </Text>
                        {p.account_configured ? (
                            <Tag color="green" icon={<CheckCircleOutlined />}>
                                {p.login_username} · MK: {p.password_masked || "••••••"}
                            </Tag>
                        ) : (
                            <Tag color="warning" icon={<WarningOutlined />}>
                                {p.login_username ? `Thiếu MK (${p.login_username})` : "Chưa cấu hình tài khoản"}
                            </Tag>
                        )}
                    </Space>
                );
            },
        },
        {
            title: "Pilot / Bật",
            key: "flags",
            render: (_, p) => (
                <Space>
                    <Switch
                        size="small"
                        checked={p.is_pilot_member}
                        checkedChildren="Pilot"
                        unCheckedChildren="Full"
                        onChange={(val) => void handleQuickToggle(p, "is_pilot_member", val)}
                    />
                    <Switch
                        size="small"
                        checked={p.is_active}
                        checkedChildren="Bật"
                        unCheckedChildren="Tắt"
                        onChange={(val) => void handleQuickToggle(p, "is_active", val)}
                    />
                </Space>
            ),
        },
        {
            title: "Thao tác",
            key: "actions",
            render: (_, p) => (
                <Space>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openEditDrawer(p)}>
                        Sửa
                    </Button>
                    <Popconfirm title={`Xóa Persona #${p.agent_id}?`} onConfirm={() => void handleDelete(p.id)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    if (loading) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}><Text type="secondary">Đang tải danh sách Persona...</Text></div>
            </div>
        );
    }

    const bqlCount = personas.filter((p) => p.group_type === "BQL").length;
    const resCount = personas.filter((p) => p.group_type === "RESIDENT").length;
    const hasAccountantPersona = personas.some((p) => p.role_code === "BQL_ACCOUNTANT");

    return (
        <div style={{ padding: "16px", maxWidth: 1380, margin: "0 auto" }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card size="small">
                    <Row gutter={[12, 12]} align="middle" justify="space-between">
                        <Col xs={24} md={16}>
                            <Space wrap>
                                <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/urban-sim")}>
                                    Trung tâm Mô phỏng
                                </Button>
                                <Title level={4} style={{ margin: 0 }}>
                                    Ma trận Nhân sự & Cư dân ({personas.length} Persona)
                                </Title>
                            </Space>
                            <div style={{ marginTop: 4 }}>
                                <Text type="secondary">
                                    Dự án: {project?.name} · {bqlCount} Ban Quản lý (kiến thức phần mềm ban đầu = 0) + {resCount} Cư dân Chủ hộ
                                </Text>
                            </div>
                        </Col>
                        <Col xs={24} md={8} style={{ display: "flex", justifyContent: "flex-end" }}>
                            <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditDrawer(null)}>
                                Thêm Persona
                            </Button>
                        </Col>
                    </Row>
                </Card>

                <Alert
                    type="info"
                    showIcon
                    message="Nguyên tắc bảo mật mật khẩu & Phân quyền"
                    description="Mật khẩu QLTN của từng nhân sự BQL được mã hóa bằng Fernet AES trước khi lưu SQLite và luôn hiển thị dạng ẩn (••••••). Cư dân Chủ hộ mặc định bị khóa quyền phần mềm BQL ở cả Prompt lẫn tầng Tool ACL."
                />

                {!hasAccountantPersona && (
                    <Alert
                        type="warning"
                        showIcon
                        message="Chưa có vai trò Kế toán Công nợ & Phí dịch vụ (BQL_ACCOUNTANT)"
                        description="Dự án khu đô thị nên có nhân sự Kế toán Công nợ để kiểm thử hóa đơn phí quản lý, thanh toán & đối soát sổ quỹ (vẫn bảo toàn an toàn không bấm khóa sổ/xóa chứng từ)."
                        action={
                            <Button
                                type="primary"
                                size="small"
                                icon={<PlusOutlined />}
                                loading={syncingAccounting}
                                onClick={() => void handleSyncAccountingPersona()}
                            >
                                Bổ sung Kế toán Công nợ (BQL_ACCOUNTANT)
                            </Button>
                        }
                    />
                )}

                <Card size="small">
                    <Row gutter={[12, 12]} align="middle" justify="space-between" style={{ marginBottom: 12 }}>
                        <Col xs={24} md={12}>
                            <Segmented
                                value={groupFilter}
                                onChange={(val) => setGroupFilter(val as "ALL" | "BQL" | "RESIDENT")}
                                options={[
                                    { label: `Tất cả (${personas.length})`, value: "ALL" },
                                    { label: `Ban Quản lý - BQL (${bqlCount})`, value: "BQL" },
                                    { label: `Cư dân Chủ hộ (${resCount})`, value: "RESIDENT" },
                                ]}
                            />
                        </Col>
                        <Col xs={24} md={8}>
                            <Input
                                prefix={<SearchOutlined />}
                                placeholder="Tìm theo tên, chức danh, khu vực..."
                                value={searchText}
                                onChange={(e) => setSearchText(e.target.value)}
                                allowClear
                            />
                        </Col>
                    </Row>

                    <Table
                        rowKey="id"
                        columns={columns}
                        dataSource={filtered}
                        pagination={{ pageSize: 25 }}
                        scroll={{ x: "max-content" }}
                    />
                </Card>
            </Space>

            <Drawer
                title={editing ? `Cấu hình Persona #${editing.agent_id}: ${editing.full_name}` : "Thêm Persona mới"}
                placement="right"
                styles={{ wrapper: { width: isMobile ? "100%" : 560 } }}
                open={drawerOpen}
                onClose={() => setDrawerOpen(false)}
                extra={
                    <Space>
                        <Button onClick={() => setDrawerOpen(false)}>Đóng</Button>
                        <Button type="primary" loading={saving} onClick={() => form.submit()}>
                            Lưu thay đổi
                        </Button>
                    </Space>
                }
            >
                <Form form={form} layout="vertical" onFinish={handleSubmit}>
                    {!editing && (
                        <Form.Item name="agent_id" label="Mã Agent ID (để trống tự tăng)">
                            <InputNumber min={1} style={{ width: "100%" }} />
                        </Form.Item>
                    )}
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Form.Item name="full_name" label="Họ và tên" rules={[{ required: true }]}>
                                <Input />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="role_title" label="Chức danh" rules={[{ required: true }]}>
                                <Input />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="group_type" label="Nhóm vai trò">
                                <Select
                                    options={[
                                        { value: "BQL", label: "Ban Quản lý (Dùng QLTN + Hỏi Atlas)" },
                                        { value: "RESIDENT", label: "Cư dân Chủ hộ (Chỉ giao tiếp Lễ tân)" },
                                    ]}
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="home_zone" label="Khu vực (Zone mặc định)">
                                <Select
                                    options={zones.map((z) => ({ value: z.zone_key, label: `${z.name} (${z.zone_key})` }))}
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="role_code" label="Mã vai trò">
                                <Input />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="department" label="Phòng ban / Tòa">
                                <Input />
                            </Form.Item>
                        </Col>
                    </Row>

                    <Form.Item noStyle shouldUpdate={(prev, cur) => prev.group_type !== cur.group_type}>
                        {({ getFieldValue }) => {
                            const grp = getFieldValue("group_type");
                            if (grp === "RESIDENT") {
                                return (
                                    <Alert
                                        type="info"
                                        showIcon
                                        style={{ marginBottom: 12 }}
                                        message="Cư dân không đăng nhập phần mềm BQL — chỉ gửi sự vụ tới Lễ tân."
                                    />
                                );
                            }
                            return (
                                <Card size="small" title="Tài khoản đăng nhập Phần mềm QLTN" style={{ marginBottom: 12 }}>
                                    <Form.Item name="software_access_enabled" label="Cho phép truy cập QLTN" valuePropName="checked">
                                        <Switch />
                                    </Form.Item>
                                    <Form.Item name="portal_url" label="Link đích QLTN riêng (để trống dùng link mặc định dự án)">
                                        <Input placeholder="https://mulberrylane.sandbox.demego.vn" />
                                    </Form.Item>
                                    <Form.Item name="login_username" label="Tên đăng nhập / Email QLTN">
                                        <Input autoComplete="off" placeholder="vd: letan.mulberry@demego.vn" />
                                    </Form.Item>
                                    <Form.Item
                                        name="login_password"
                                        label="Mật khẩu QLTN (để trống nếu giữ nguyên mật khẩu cũ)"
                                    >
                                        <Input.Password autoComplete="new-password" placeholder={editing?.has_password ? "•••••• (đã lưu)" : "Nhập mật khẩu QLTN"} />
                                    </Form.Item>
                                    {editing?.has_password && (
                                        <Form.Item name="clear_password" valuePropName="checked" style={{ marginBottom: 0 }}>
                                            <Checkbox>Xóa mật khẩu đã lưu khỏi Database</Checkbox>
                                        </Form.Item>
                                    )}
                                </Card>
                            );
                        }}
                    </Form.Item>

                    <Row gutter={12}>
                        <Col span={12}>
                            <Form.Item name="is_pilot_member" label="Thuộc nhóm Pilot (9 tác nhân)" valuePropName="checked">
                                <Switch />
                            </Form.Item>
                        </Col>
                        <Col span={12}>
                            <Form.Item name="is_active" label="Kích hoạt khi chạy" valuePropName="checked">
                                <Switch />
                            </Form.Item>
                        </Col>
                    </Row>

                    <Form.Item name="domain_knowledge_prompt" label="Kiến thức nghiệp vụ chuyên môn (KHÔNG chứa hướng dẫn phần mềm)">
                        <TextArea rows={4} />
                    </Form.Item>

                    <Form.Item name="initial_tasks_text" label="Các nhiệm vụ / tình huống khởi đầu (mỗi dòng 1 ý)">
                        <TextArea rows={4} />
                    </Form.Item>
                </Form>
            </Drawer>
        </div>
    );
}
