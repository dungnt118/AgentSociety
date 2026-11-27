import {
    ArrowLeftOutlined,
    CheckCircleOutlined,
    DeleteOutlined,
    EditOutlined,
    LockOutlined,
    PlusOutlined,
    SearchOutlined,
    ThunderboltOutlined,
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
    PersonaProfileTraits,
    urbanSimApi,
    UrbanSimPersona,
    UrbanSimProjectSummary,
    UrbanSimSkillOption,
    UrbanSimZone,
} from "../../services/urbanSimApi";

const { Title, Text } = Typography;
const { TextArea } = Input;

const PERSONALITY_TAG_SUGGESTIONS = [
    "Cẩn thận",
    "Nhiệt tình",
    "Nghiêm túc",
    "Khó tính",
    "Chu đáo",
    "Kỹ tính",
    "Nhanh nhẹn",
    "Ưa sạch sẽ",
    "Hay giao lưu",
    "Thích thể thao",
];

const PERSONA_ICON_PRESETS = [
    "👔", "📋", "🛎️", "🛡️", "👮", "👷", "🔧", "🧮",
    "🧹", "🧑‍💼", "🧑", "👨", "👩", "🏃", "🚴", "🐕",
];

function resolveDefaultPersonaIconFE(roleCode = "", groupType = "BQL", fullName = ""): string {
    const rc = roleCode.toUpperCase();
    const low = fullName.toLowerCase();
    if (groupType === "RESIDENT") {
        if (low.includes("bà ") || low.includes("chị ") || low.includes("cô ")) return "👩";
        if (low.includes("ông ") || low.includes("anh ") || low.includes("chú ")) return "👨";
        return "🧑";
    }
    const map: Record<string, string> = {
        BQL_DIRECTOR: "👔",
        BQL_ASSISTANT: "📋",
        BQL_RECEPTIONIST: "🛎️",
        SEC_LEAD: "🛡️",
        SEC_STAFF: "👮",
        ENG_LEAD: "👷",
        ENG_STAFF: "🔧",
        BQL_ACCOUNTANT: "🧮",
    };
    if (map[rc]) return map[rc];
    if (rc.includes("SEC")) return "👮";
    if (rc.includes("ENG") || rc.includes("TECH")) return "🔧";
    if (rc.includes("ACCOUNT")) return "🧮";
    return "🧑‍💼";
}

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
    avatar_icon?: string;
    portal_url?: string;
    login_username?: string;
    login_password?: string;
    clear_password?: boolean;
    domain_knowledge_prompt: string;
    initial_tasks_text: string;
    default_activated_skill_ids?: string[];
    disabled_skill_ids?: string[];
    trait_age?: number | null;
    trait_gender?: string;
    trait_occupation?: string;
    trait_personality_tags?: string[];
    trait_communication_style?: string;
    trait_daily_routine?: string;
    trait_background_story?: string;
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
    const [availableSkills, setAvailableSkills] = useState<UrbanSimSkillOption[]>([]);
    const [groupFilter, setGroupFilter] = useState<"ALL" | "BQL" | "RESIDENT">("ALL");
    const [searchText, setSearchText] = useState("");
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [editing, setEditing] = useState<UrbanSimPersona | null>(null);
    const [saving, setSaving] = useState(false);
    const [syncingAccounting, setSyncingAccounting] = useState(false);
    const [form] = Form.useForm<PersonaFormValues>();

    const reloadData = useCallback(async () => {
        if (!projectId) return;
        const [proj, perList, zoneRes, skillList] = await Promise.all([
            urbanSimApi.getProject(projectId),
            urbanSimApi.listPersonas(projectId),
            urbanSimApi.listZones(projectId),
            urbanSimApi.listAvailableSkills().catch(() => []),
        ]);
        setProject(proj);
        setPersonas(perList);
        setZones(zoneRes.items || []);
        setAvailableSkills(skillList);
    }, [projectId]);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            try {
                await reloadData();
            } catch (err) {
                if (active) {
                    message.error(err instanceof Error ? err.message : "Không tải được danh sách Nhân sự & Cư dân");
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
            const traits = persona.profile_traits || {};
            const defaultActivated =
                persona.default_activated_skill_ids ??
                (persona.group_type === "BQL" && persona.software_access_enabled
                    ? ["env:DemegoWebPortalEnv@bql-qltn-ops-vn"]
                    : ["env:UrbanCommAndIncidentEnv@urban-resident-vn"]);
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
                avatar_icon:
                    persona.avatar_icon ||
                    resolveDefaultPersonaIconFE(persona.role_code, persona.group_type, persona.full_name),
                portal_url: persona.portal_url || "",
                login_username: persona.login_username || "",
                login_password: "",
                clear_password: false,
                domain_knowledge_prompt: persona.domain_knowledge_prompt,
                initial_tasks_text: (persona.initial_tasks || []).join("\n"),
                default_activated_skill_ids: defaultActivated,
                disabled_skill_ids: persona.disabled_skill_ids || [],
                trait_age: traits.age ?? null,
                trait_gender: traits.gender || undefined,
                trait_occupation: traits.occupation || "",
                trait_personality_tags: traits.personality_tags || [],
                trait_communication_style: traits.communication_style || "",
                trait_daily_routine: traits.daily_routine || "",
                trait_background_story: traits.background_story || "",
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
                home_zone: zones[0]?.zone_key || "",
                avatar_icon: "🧑‍💼",
                portal_url: project?.default_portal_url || "",
                login_username: "",
                login_password: "",
                clear_password: false,
                domain_knowledge_prompt: "",
                initial_tasks_text: "",
                default_activated_skill_ids: ["env:DemegoWebPortalEnv@bql-qltn-ops-vn"],
                disabled_skill_ids: [],
                trait_age: null,
                trait_gender: undefined,
                trait_occupation: "",
                trait_personality_tags: [],
                trait_communication_style: "",
                trait_daily_routine: "",
                trait_background_story: "",
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
        const swEnabled = values.group_type === "RESIDENT" ? false : Boolean(values.software_access_enabled);
        const activatedSkills = (values.default_activated_skill_ids || []).filter(
            (sid) => swEnabled || sid !== "env:DemegoWebPortalEnv@bql-qltn-ops-vn"
        );
        const disabledSkills = (values.disabled_skill_ids || []).filter(
            (sid) => !activatedSkills.includes(sid)
        );
        const profileTraits: PersonaProfileTraits = {};
        if (typeof values.trait_age === "number" && Number.isFinite(values.trait_age)) {
            profileTraits.age = values.trait_age;
        }
        if (values.trait_gender && values.trait_gender.trim()) {
            profileTraits.gender = values.trait_gender.trim();
        }
        if (values.trait_occupation && values.trait_occupation.trim()) {
            profileTraits.occupation = values.trait_occupation.trim();
        }
        if (values.trait_personality_tags && values.trait_personality_tags.length > 0) {
            profileTraits.personality_tags = values.trait_personality_tags;
        }
        if (values.trait_communication_style && values.trait_communication_style.trim()) {
            profileTraits.communication_style = values.trait_communication_style.trim();
        }
        if (values.trait_daily_routine && values.trait_daily_routine.trim()) {
            profileTraits.daily_routine = values.trait_daily_routine.trim();
        }
        if (values.trait_background_story && values.trait_background_story.trim()) {
            profileTraits.background_story = values.trait_background_story.trim();
        }

        const payload: Record<string, unknown> = {
            full_name: values.full_name,
            role_code: values.role_code,
            role_title: values.role_title,
            department: values.department,
            group_type: values.group_type,
            software_access_enabled: swEnabled,
            is_pilot_member: values.is_pilot_member,
            is_active: values.is_active,
            home_zone: values.home_zone,
            avatar_icon: (values.avatar_icon || "").trim() || undefined,
            portal_url: (values.portal_url ?? "").trim(),
            login_username: (values.login_username ?? "").trim(),
            domain_knowledge_prompt: values.domain_knowledge_prompt,
            initial_tasks: tasks,
            default_activated_skill_ids: activatedSkills,
            disabled_skill_ids: disabledSkills,
            profile_traits: Object.keys(profileTraits).length > 0 ? profileTraits : {},
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
            width: 78,
            render: (id: number, p: UrbanSimPersona) => (
                <Space size={4}>
                    <span style={{ fontSize: 16 }}>
                        {p.avatar_icon || resolveDefaultPersonaIconFE(p.role_code, p.group_type, p.full_name)}
                    </span>
                    <Text strong>#{id}</Text>
                </Space>
            ),
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
            render: (_, p) => {
                const traits = p.profile_traits || {};
                const customSkillCount = (p.default_activated_skill_ids || []).length;
                return (
                    <Space direction="vertical" size={2}>
                        <Tag color={p.group_type === "BQL" ? "blue" : "purple"}>
                            {p.group_type === "BQL" ? "Ban Quản lý (BQL)" : "Cư dân Chủ hộ"}
                        </Tag>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            Khu vực: {p.home_zone}
                        </Text>
                        <Space wrap size={4}>
                            {customSkillCount > 0 && (
                                <Tag color="cyan" icon={<ThunderboltOutlined />} style={{ fontSize: 11, marginInlineEnd: 0 }}>
                                    {customSkillCount} kỹ năng
                                </Tag>
                            )}
                            {(traits.personality_tags || []).slice(0, 2).map((tag) => (
                                <Tag key={tag} style={{ fontSize: 11, marginInlineEnd: 0 }}>
                                    {tag}
                                </Tag>
                            ))}
                        </Space>
                    </Space>
                );
            },
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
                            <Form.Item name="home_zone" label="Khu vực mặc định">
                                <Select
                                    placeholder="Chọn khu vực từ Sơ đồ Khu đô thị"
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
                        <Col xs={24}>
                            <Form.Item name="avatar_icon" label="Icon đại diện trên Bản đồ Số (thay cho badge số)">
                                <Input style={{ width: 120 }} placeholder="vd: 👮" />
                            </Form.Item>
                            <Space wrap size={4} style={{ marginTop: -8, marginBottom: 12 }}>
                                {PERSONA_ICON_PRESETS.map((ic) => (
                                    <Button
                                        key={ic}
                                        size="small"
                                        onClick={() => form.setFieldValue("avatar_icon", ic)}
                                    >
                                        {ic}
                                    </Button>
                                ))}
                            </Space>
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

                    <Card
                        size="small"
                        title={
                            <Space>
                                <ThunderboltOutlined />
                                <span>Kỹ năng Agent từ Kho /skills</span>
                            </Space>
                        }
                        extra={
                            <Button type="link" size="small" onClick={() => navigate("/skills")}>
                                Mở Kho Kỹ năng (/skills)
                            </Button>
                        }
                        style={{ marginBottom: 12 }}
                    >
                        <Form.Item noStyle shouldUpdate={(prev, cur) => prev.group_type !== cur.group_type || prev.software_access_enabled !== cur.software_access_enabled}>
                            {({ getFieldValue }) => {
                                const isSwAllowed = getFieldValue("group_type") !== "RESIDENT" && Boolean(getFieldValue("software_access_enabled"));
                                const skillOpts = availableSkills.map((sk) => ({
                                    value: sk.skill_id,
                                    label: `${sk.name} [${sk.source_label}]${sk.requires_software_access && !isSwAllowed ? " (Khóa — cần quyền QLTN)" : ""}`,
                                    disabled: sk.requires_software_access && !isSwAllowed,
                                }));
                                return (
                                    <>
                                        <Form.Item
                                            name="default_activated_skill_ids"
                                            label="Kỹ năng kích hoạt mặc định cho nhân vật"
                                            extra="Các kỹ năng (SKILL.md) đã chọn sẽ được nạp thẳng vào Agent khi chạy mô phỏng."
                                        >
                                            <Select
                                                mode="multiple"
                                                allowClear
                                                showSearch
                                                optionFilterProp="label"
                                                placeholder="Chọn kỹ năng từ /skills hoặc kỹ năng vai trò"
                                                options={skillOpts}
                                            />
                                        </Form.Item>
                                        <Form.Item
                                            name="disabled_skill_ids"
                                            label="Kỹ năng tắt (không dùng)"
                                            style={{ marginBottom: 0 }}
                                        >
                                            <Select
                                                mode="multiple"
                                                allowClear
                                                showSearch
                                                optionFilterProp="label"
                                                placeholder="Chọn kỹ năng cần tắt với nhân vật này (nếu có)"
                                                options={availableSkills.map((sk) => ({
                                                    value: sk.skill_id,
                                                    label: `${sk.name} [${sk.source_label}]`,
                                                }))}
                                            />
                                        </Form.Item>
                                    </>
                                );
                            }}
                        </Form.Item>
                    </Card>

                    <Card size="small" title="Đặc tính cá nhân & Thói quen (Profile Traits)" style={{ marginBottom: 12 }}>
                        <Row gutter={12}>
                            <Col xs={12} sm={8}>
                                <Form.Item name="trait_age" label="Tuổi">
                                    <InputNumber min={6} max={100} style={{ width: "100%" }} placeholder="vd: 34" />
                                </Form.Item>
                            </Col>
                            <Col xs={12} sm={8}>
                                <Form.Item name="trait_gender" label="Giới tính">
                                    <Select
                                        allowClear
                                        placeholder="Chọn"
                                        options={[
                                            { value: "Nam", label: "Nam" },
                                            { value: "Nữ", label: "Nữ" },
                                            { value: "Khác", label: "Khác" },
                                        ]}
                                    />
                                </Form.Item>
                            </Col>
                            <Col xs={24} sm={8}>
                                <Form.Item name="trait_occupation" label="Nghề nghiệp">
                                    <Input placeholder="vd: Kỹ sư phần mềm" />
                                </Form.Item>
                            </Col>
                            <Col xs={24}>
                                <Form.Item name="trait_personality_tags" label="Thẻ tính cách (chọn hoặc tự nhập)">
                                    <Select
                                        mode="tags"
                                        allowClear
                                        placeholder="vd: Cẩn thận, Khó tính, Thích thể thao..."
                                        options={PERSONALITY_TAG_SUGGESTIONS.map((t) => ({ value: t, label: t }))}
                                    />
                                </Form.Item>
                            </Col>
                            <Col xs={24} sm={12}>
                                <Form.Item name="trait_communication_style" label="Phong cách giao tiếp">
                                    <Input placeholder="vd: Thẳng thắn, đòi hỏi xử lý nhanh" />
                                </Form.Item>
                            </Col>
                            <Col xs={24} sm={12}>
                                <Form.Item name="trait_daily_routine" label="Thói quen theo khung giờ">
                                    <Input placeholder="vd: Sáng 07:00 chạy bộ, Tối 19:00 bơi/BBQ" />
                                </Form.Item>
                            </Col>
                            <Col xs={24}>
                                <Form.Item name="trait_background_story" label="Hoàn cảnh / Tiểu sử chi tiết" style={{ marginBottom: 0 }}>
                                    <TextArea rows={2} placeholder="Mô tả bối cảnh sống, gia đình, mối quan tâm nổi bật của nhân vật..." />
                                </Form.Item>
                            </Col>
                        </Row>
                    </Card>

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
