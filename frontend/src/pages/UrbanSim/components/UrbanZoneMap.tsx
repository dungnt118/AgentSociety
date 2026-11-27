import {
    DeleteOutlined,
    EditOutlined,
    EnvironmentOutlined,
    PictureOutlined,
    PlusOutlined,
    PushpinOutlined,
    UploadOutlined,
    UserAddOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Badge,
    Button,
    Card,
    Col,
    Empty,
    Form,
    Input,
    InputNumber,
    Modal,
    Popconfirm,
    Row,
    Select,
    Space,
    Tabs,
    Tag,
    Typography,
    Upload,
    message,
} from "antd";
import type { UploadProps } from "antd";
import React, { useState } from "react";
import {
    AgentStatusRow,
    DigitalMapMeta,
    RecentMovementEvent,
    urbanSimApi,
    UrbanSimCheckpoint,
    UrbanSimPersona,
    UrbanSimZone,
    ZoneTopologyCard,
    ZoneType,
} from "../../../services/urbanSimApi";
import { DigitalUrbanMapCanvas } from "./DigitalUrbanMapCanvas";

const { Text } = Typography;
const { TextArea } = Input;

const ZONE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
    LOBBY: { label: "Sảnh & Lễ tân", color: "blue" },
    OFFICE: { label: "Văn phòng BQL", color: "geekblue" },
    TECHNICAL: { label: "Kỹ thuật M&E", color: "orange" },
    SECURITY: { label: "An ninh & Hầm", color: "volcano" },
    TOWER: { label: "Tháp Căn hộ", color: "green" },
    UTILITY: { label: "Tiện ích chung", color: "cyan" },
    PARKING: { label: "Bãi xe & Hầm", color: "purple" },
    COMMERCIAL: { label: "Thương mại / Dịch vụ", color: "gold" },
    OTHER: { label: "Khu vực khác", color: "default" },
};

const ZONE_TYPE_OPTIONS: Array<{ value: ZoneType; label: string }> = [
    { value: "LOBBY", label: "Sảnh & Lễ tân (LOBBY)" },
    { value: "OFFICE", label: "Văn phòng BQL (OFFICE)" },
    { value: "TECHNICAL", label: "Kỹ thuật M&E (TECHNICAL)" },
    { value: "SECURITY", label: "An ninh & Hầm (SECURITY)" },
    { value: "TOWER", label: "Tháp Căn hộ (TOWER)" },
    { value: "UTILITY", label: "Tiện ích chung (UTILITY)" },
    { value: "PARKING", label: "Bãi xe & Hầm (PARKING)" },
    { value: "COMMERCIAL", label: "Thương mại / Dịch vụ (COMMERCIAL)" },
    { value: "OTHER", label: "Khu vực khác (OTHER)" },
];

interface ZoneFormValues {
    zone_key: string;
    name: string;
    zone_type: ZoneType;
    fill_color?: string;
    description: string;
    ambient_signals: string;
    sort_order: number;
}

interface UrbanZoneMapProps {
    projectId: string;
    runId?: string;
    hasZoneMapImage: boolean;
    hasDigitalMap?: boolean;
    digitalMap?: DigitalMapMeta;
    topologyZones?: ZoneTopologyCard[];
    staticZones?: UrbanSimZone[];
    checkpoints?: UrbanSimCheckpoint[];
    staticPersonas?: UrbanSimPersona[];
    agentStatuses?: AgentStatusRow[];
    recentMovements?: RecentMovementEvent[];
    editableMap?: boolean;
    onOpenAgentTimeline?: (agentId: number) => void;
    onMapUpdated?: (hasImage: boolean) => void;
}

export const UrbanZoneMap: React.FC<UrbanZoneMapProps> = ({
    projectId,
    runId,
    hasZoneMapImage,
    hasDigitalMap,
    digitalMap,
    topologyZones,
    staticZones,
    checkpoints = [],
    staticPersonas,
    agentStatuses = [],
    recentMovements = [],
    editableMap = false,
    onOpenAgentTimeline,
    onMapUpdated,
}) => {
    const isLiveMonitor = Boolean(topologyZones);
    const [imgVersion, setImgVersion] = useState<string>("1");
    const [uploading, setUploading] = useState(false);
    const [aspectWarning, setAspectWarning] = useState(false);

    const [zoneModalOpen, setZoneModalOpen] = useState(false);
    const [editingZone, setEditingZone] = useState<ZoneTopologyCard | null>(null);
    const [savingZone, setSavingZone] = useState(false);
    const [zoneForm] = Form.useForm<ZoneFormValues>();

    const [reassignTarget, setReassignTarget] = useState<string>("");
    const [deletingZone, setDeletingZone] = useState<ZoneTopologyCard | null>(null);
    const [deletingBusy, setDeletingBusy] = useState(false);

    const cards: ZoneTopologyCard[] = topologyZones
        ? topologyZones
        : (staticZones || []).map((z) => ({
            id: z.id,
            zone_key: z.zone_key,
            name: z.name,
            zone_type: z.zone_type,
            description: z.description,
            ambient_signals: z.ambient_signals || "",
            persona_count: z.persona_count ?? 0,
            center_x_pct: z.center_x_pct,
            center_y_pct: z.center_y_pct,
            polygon_points: z.polygon_points,
            fill_color: z.fill_color,
            agents_here: [],
            open_incidents: [],
        }));

    const effectiveHasDigitalMap =
        typeof hasDigitalMap === "boolean"
            ? hasDigitalMap
            : Boolean(hasZoneMapImage || cards.some((c) => Array.isArray(c.polygon_points) && c.polygon_points.length >= 3));

    const handleUpload: UploadProps["customRequest"] = async (options) => {
        const rawFile = options.file;
        if (!(rawFile instanceof File)) {
            return;
        }
        const allowedMime = ["image/png", "image/jpeg", "image/webp"];
        if (rawFile.type && !allowedMime.includes(rawFile.type.toLowerCase())) {
            const err = new Error("Chỉ chấp nhận ảnh PNG, JPEG hoặc WEBP (từ chối SVG/HTML).");
            message.error(err.message);
            options.onError?.(err);
            return;
        }
        if (rawFile.size > 5 * 1024 * 1024) {
            const err = new Error("Kích thước ảnh sơ đồ vượt quá 5 MB.");
            message.error(err.message);
            options.onError?.(err);
            return;
        }
        setUploading(true);
        try {
            const res = await urbanSimApi.uploadZoneMapImage(projectId, rawFile);
            setAspectWarning(Boolean(res.aspect_ratio_changed));
            setImgVersion(String(res.map_image_version ?? Date.now()));
            message.success("Đã tải lên sơ đồ mặt bằng 2D.");
            onMapUpdated?.(true);
            options.onSuccess?.({});
        } catch (err) {
            const errMsg = err instanceof Error ? err.message : "Tải ảnh thất bại";
            message.error(errMsg);
            options.onError?.(err instanceof Error ? err : new Error(errMsg));
        } finally {
            setUploading(false);
        }
    };

    const handleDeleteMap = async () => {
        try {
            await urbanSimApi.deleteZoneMapImage(projectId);
            setAspectWarning(false);
            message.success("Đã gỡ ảnh sơ đồ 2D.");
            onMapUpdated?.(false);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể xóa ảnh");
        }
    };

    const openZoneModal = (zone: ZoneTopologyCard | null) => {
        setEditingZone(zone);
        if (zone) {
            const matchedStatic = staticZones?.find((s) => s.zone_key === zone.zone_key);
            zoneForm.setFieldsValue({
                zone_key: zone.zone_key,
                name: zone.name,
                zone_type: (zone.zone_type as ZoneType) || "OFFICE",
                fill_color: zone.fill_color || matchedStatic?.fill_color || "#0ea5e9",
                description: zone.description || "",
                ambient_signals: zone.ambient_signals || "",
                sort_order: matchedStatic?.sort_order ?? 1,
            });
        } else {
            zoneForm.setFieldsValue({
                zone_key: "",
                name: "",
                zone_type: cards.length === 0 ? "LOBBY" : "TOWER",
                fill_color: "#0ea5e9",
                description: "",
                ambient_signals: "",
                sort_order: cards.length + 1,
            });
        }
        setZoneModalOpen(true);
    };

    const [assignModalZone, setAssignModalZone] = useState<ZoneTopologyCard | null>(null);
    const [assignSelectedIds, setAssignSelectedIds] = useState<string[]>([]);
    const [assignFallbackZoneKey, setAssignFallbackZoneKey] = useState<string>("");
    const [assigningBusy, setAssigningBusy] = useState(false);

    const openAssignModal = (zone: ZoneTopologyCard) => {
        const currentlyInZone = (staticPersonas || [])
            .filter((p) => p.home_zone === zone.zone_key)
            .map((p) => p.id);
        const others = cards.filter((c) => c.zone_key !== zone.zone_key);
        setAssignModalZone(zone);
        setAssignSelectedIds(currentlyInZone);
        setAssignFallbackZoneKey(others[0]?.zone_key || "");
    };

    const handleSaveAssignPersonas = async () => {
        if (!assignModalZone?.id) return;
        setAssigningBusy(true);
        try {
            const res = await urbanSimApi.assignZonePersonas(
                projectId,
                assignModalZone.id,
                assignSelectedIds,
                assignFallbackZoneKey || undefined
            );
            const movedMsg =
                res.reassigned_out_count > 0 && res.fallback_zone_key
                    ? ` (đã chuyển ${res.reassigned_out_count} người bỏ chọn sang ${res.fallback_zone_key})`
                    : "";
            message.success(
                `Đã gắn ${res.assigned_persona_ids.length} Nhân sự/Cư dân vào "${assignModalZone.name}"${movedMsg}.`
            );
            setAssignModalZone(null);
            onMapUpdated?.(hasZoneMapImage);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Gắn Nhân sự/Cư dân thất bại");
        } finally {
            setAssigningBusy(false);
        }
    };

    const handleSaveZone = async (values: ZoneFormValues) => {
        setSavingZone(true);
        try {
            if (editingZone?.id) {
                await urbanSimApi.updateZone(projectId, editingZone.id, {
                    zone_key: values.zone_key,
                    name: values.name,
                    zone_type: values.zone_type,
                    fill_color: values.fill_color || undefined,
                    description: values.description || "",
                    ambient_signals: values.ambient_signals || "",
                    sort_order: Number(values.sort_order ?? 99),
                });
                message.success(`Đã cập nhật khu vực "${values.name}".`);
            } else {
                await urbanSimApi.createZone(projectId, {
                    zone_key: values.zone_key,
                    name: values.name,
                    zone_type: values.zone_type,
                    fill_color: values.fill_color || undefined,
                    description: values.description || "",
                    ambient_signals: values.ambient_signals || "",
                    sort_order: Number(values.sort_order ?? 99),
                });
                message.success(`Đã thêm khu vực "${values.name}".`);
            }
            setZoneModalOpen(false);
            onMapUpdated?.(hasZoneMapImage);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu khu vực thất bại");
        } finally {
            setSavingZone(false);
        }
    };

    const handleDirectDeleteZone = async (zone: ZoneTopologyCard) => {
        if (!zone.id) return;
        const otherZones = cards.filter((c) => c.zone_key !== zone.zone_key);
        if ((zone.persona_count || 0) > 0) {
            setReassignTarget(otherZones[0]?.zone_key || "");
            setDeletingZone(zone);
            return;
        }
        try {
            await urbanSimApi.deleteZone(projectId, zone.id);
            message.success(`Đã xóa khu vực "${zone.name}".`);
            onMapUpdated?.(hasZoneMapImage);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể xóa khu vực");
        }
    };

    const handleConfirmReassignDelete = async () => {
        if (!deletingZone?.id || !reassignTarget) return;
        setDeletingBusy(true);
        try {
            const res = await urbanSimApi.deleteZone(projectId, deletingZone.id, reassignTarget);
            message.success(
                `Đã xóa khu vực "${deletingZone.name}" và chuyển ${res.reassigned_personas} nhân sự/cư dân sang ${reassignTarget}.`
            );
            setDeletingZone(null);
            onMapUpdated?.(hasZoneMapImage);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xóa khu vực thất bại");
        } finally {
            setDeletingBusy(false);
        }
    };

    const otherZonesForDelete = deletingZone
        ? cards.filter((c) => c.zone_key !== deletingZone.zone_key)
        : [];

    const zoneCardsContent = (
        <>
            {cards.length === 0 ? (
                <Card size="small">
                    <Empty
                        description="Dự án chưa có Khu vực nào. Hãy thêm ít nhất 1 Khu vực để gắn vị trí cho nhân sự/cư dân và nạp ngữ cảnh động."
                    >
                        {editableMap && (
                            <Button type="primary" icon={<PlusOutlined />} onClick={() => openZoneModal(null)}>
                                Thêm khu vực đầu tiên
                            </Button>
                        )}
                    </Empty>
                </Card>
            ) : (
                <Row gutter={[12, 12]}>
                    {cards.map((z) => {
                        const meta = ZONE_TYPE_LABELS[z.zone_type] || { label: z.zone_type, color: "default" };
                        const signalLines = (z.ambient_signals || "")
                            .split(/\r?\n/)
                            .map((s) => s.trim())
                            .filter(Boolean);
                        const attachedPersonas = (staticPersonas || []).filter((p) => p.home_zone === z.zone_key);
                        const personaTotal = staticPersonas ? attachedPersonas.length : z.persona_count ?? 0;
                        return (
                            <Col key={z.zone_key} xs={24} sm={12} lg={8}>
                                <Card
                                    size="small"
                                    title={
                                        <Space wrap size={6}>
                                            <EnvironmentOutlined />
                                            <Text strong>{z.name}</Text>
                                        </Space>
                                    }
                                    extra={
                                        <Space size={4} wrap>
                                            <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
                                            {z.open_incidents.length > 0 && (
                                                <Badge count={z.open_incidents.length} title="Sự vụ đang mở" />
                                            )}
                                            {editableMap && z.id && (
                                                <>
                                                    <Button
                                                        size="small"
                                                        type="text"
                                                        aria-label={`Gắn người vào khu vực ${z.zone_key}`}
                                                        title="Gắn Nhân sự & Cư dân vào Khu vực này"
                                                        icon={<UserAddOutlined />}
                                                        onClick={() => openAssignModal(z)}
                                                    />
                                                    <Button
                                                        size="small"
                                                        type="text"
                                                        aria-label={`Sửa khu vực ${z.zone_key}`}
                                                        icon={<EditOutlined />}
                                                        onClick={() => openZoneModal(z)}
                                                    />
                                                    {personaTotal > 0 ? (
                                                        <Button
                                                            size="small"
                                                            type="text"
                                                            danger
                                                            aria-label={`Xóa khu vực ${z.zone_key}`}
                                                            icon={<DeleteOutlined />}
                                                            onClick={() => void handleDirectDeleteZone(z)}
                                                        />
                                                    ) : (
                                                        <Popconfirm
                                                            title={`Xóa khu vực "${z.name}" (${z.zone_key})?`}
                                                            okText="Xóa"
                                                            cancelText="Hủy"
                                                            onConfirm={() => void handleDirectDeleteZone(z)}
                                                        >
                                                            <Button
                                                                size="small"
                                                                type="text"
                                                                danger
                                                                aria-label={`Xóa khu vực ${z.zone_key}`}
                                                                icon={<DeleteOutlined />}
                                                            />
                                                        </Popconfirm>
                                                    )}
                                                </>
                                            )}
                                        </Space>
                                    }
                                    style={{ height: "100%" }}
                                >
                                    <Space wrap size={4} style={{ marginBottom: 6 }}>
                                        <Tag style={{ fontSize: 11 }}>{z.zone_key}</Tag>
                                        <Tag color="blue" style={{ fontSize: 11 }}>
                                            {personaTotal} Persona mặc định
                                        </Tag>
                                        {signalLines.length > 0 ? (
                                            <Tag color="green" style={{ fontSize: 11 }}>
                                                {signalLines.length} tín hiệu động
                                            </Tag>
                                        ) : (
                                            <Tag style={{ fontSize: 11 }}>Theo giờ hệ thống</Tag>
                                        )}
                                    </Space>
                                    {attachedPersonas.length > 0 && (
                                        <Space wrap size={4} style={{ marginBottom: 6 }}>
                                            {attachedPersonas.slice(0, 5).map((p) => (
                                                <Tag
                                                    key={p.id}
                                                    color={p.group_type === "BQL" ? "geekblue" : "purple"}
                                                    style={{ fontSize: 11, marginInlineEnd: 0 }}
                                                >
                                                    {p.full_name}
                                                </Tag>
                                            ))}
                                            {attachedPersonas.length > 5 && (
                                                <Tag style={{ fontSize: 11 }}>+{attachedPersonas.length - 5}</Tag>
                                            )}
                                        </Space>
                                    )}
                                    <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                                        {z.description || z.zone_key}
                                    </Text>
                                    {signalLines.length > 0 && (
                                        <div
                                            style={{
                                                background: "#f6ffed",
                                                border: "1px solid #b7eb8f",
                                                borderRadius: 6,
                                                padding: "6px 8px",
                                                marginBottom: 8,
                                            }}
                                        >
                                            <Text strong style={{ fontSize: 11, display: "block", color: "#389e0d" }}>
                                                Tín hiệu ngữ cảnh nạp cho Agent:
                                            </Text>
                                            {signalLines.slice(0, 2).map((line, idx) => (
                                                <Text key={idx} style={{ fontSize: 11, display: "block", color: "#434343" }}>
                                                    • {line.length > 140 ? `${line.slice(0, 140)}…` : line}
                                                </Text>
                                            ))}
                                            {signalLines.length > 2 && (
                                                <Text type="secondary" style={{ fontSize: 11 }}>
                                                    +{signalLines.length - 2} dòng khác (bấm Sửa để xem hết)
                                                </Text>
                                            )}
                                        </div>
                                    )}
                                    {isLiveMonitor ? (
                                        <>
                                            <div style={{ marginBottom: 4 }}>
                                                <Text style={{ fontSize: 12, fontWeight: 600 }}>
                                                    Tác nhân đang hiện diện ({z.agents_here.length}):
                                                </Text>
                                            </div>
                                            {z.agents_here.length === 0 ? (
                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                    Hiện không có tác nhân nào đang đứng tại khu vực này
                                                </Text>
                                            ) : (
                                                <Space size={[4, 4]} wrap>
                                                    {z.agents_here.map((ag) => (
                                                        <Tag
                                                            key={ag.agent_id}
                                                            color={ag.group_type === "BQL" ? "blue" : "purple"}
                                                            style={{ marginInlineEnd: 0, cursor: onOpenAgentTimeline ? "pointer" : "default" }}
                                                            title={ag.role_title}
                                                            onClick={() => onOpenAgentTimeline?.(ag.agent_id)}
                                                        >
                                                            #{ag.agent_id} {ag.full_name}
                                                        </Tag>
                                                    ))}
                                                </Space>
                                            )}
                                        </>
                                    ) : (() => {
                                        const defaultPersonasHere = (staticPersonas || []).filter(
                                            (p) => p.home_zone === z.zone_key
                                        );
                                        const defaultCount = staticPersonas
                                            ? defaultPersonasHere.length
                                            : (z.persona_count ?? 0);
                                        return (
                                            <>
                                                <div style={{ marginBottom: 4 }}>
                                                    <Text style={{ fontSize: 12, fontWeight: 600 }}>
                                                        Persona mặc định tại đây ({defaultCount}):
                                                    </Text>
                                                </div>
                                                {defaultPersonasHere.length > 0 ? (
                                                    <Space size={[4, 4]} wrap>
                                                        {defaultPersonasHere.map((p) => (
                                                            <Tag
                                                                key={p.id}
                                                                color={p.group_type === "BQL" ? "blue" : "purple"}
                                                                style={{
                                                                    marginInlineEnd: 0,
                                                                    opacity: p.is_active ? 1 : 0.55,
                                                                }}
                                                                title={`${p.role_title} · ${p.department || p.group_type}${p.is_active ? "" : " (Đang tắt)"}`}
                                                            >
                                                                #{p.agent_id} {p.full_name}
                                                                {p.is_active ? "" : " (Tắt)"}
                                                            </Tag>
                                                        ))}
                                                    </Space>
                                                ) : defaultCount === 0 ? (
                                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                                        Chưa có Persona nào gắn vị trí mặc định tại đây
                                                    </Text>
                                                ) : (
                                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                                        {defaultCount} Persona đang chọn khu vực này làm vị trí mặc định
                                                    </Text>
                                                )}
                                            </>
                                        );
                                    })()}
                                    {z.open_incidents.length > 0 && (
                                        <div style={{ marginTop: 8, paddingTop: 6, borderTop: "1px dashed #f0f0f0" }}>
                                            {z.open_incidents.map((inc) => (
                                                <div key={inc.incident_id} style={{ fontSize: 12, color: "#cf1322" }}>
                                                    • [{inc.incident_id}] {inc.title} ({inc.status})
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </Card>
                            </Col>
                        );
                    })}
                </Row>
            )}
        </>
    );

    const checkpointCardsContent = (
        <Row gutter={[12, 12]}>
            {checkpoints.length === 0 ? (
                <Col span={24}>
                    <Empty
                        description={
                            effectiveHasDigitalMap
                                ? "Chưa có Chốt/Pin nào. Hãy dùng công cụ 'Đặt Chốt' hoặc 'AI Sinh Chốt' trên Bản đồ Số."
                                : "Hãy tạo Bản đồ Số (Ảnh 2D hoặc Polygon Khu vực) trước khi thêm Chốt/Pin."
                        }
                    />
                </Col>
            ) : (
                checkpoints.map((cp) => (
                    <Col key={cp.id} xs={24} sm={12} lg={8}>
                        <Card
                            size="small"
                            title={
                                <Space size={6}>
                                    <span>{cp.icon_emoji || "📍"}</span>
                                    <Text strong>{cp.name}</Text>
                                </Space>
                            }
                            extra={
                                editableMap ? (
                                    <Popconfirm
                                        title={`Xóa chốt "${cp.name}"?`}
                                        okText="Xóa"
                                        cancelText="Hủy"
                                        onConfirm={() => {
                                            void urbanSimApi
                                                .deleteCheckpoint(projectId, cp.id)
                                                .then(() => {
                                                    message.success(`Đã xóa chốt "${cp.name}".`);
                                                    onMapUpdated?.(hasZoneMapImage);
                                                })
                                                .catch((err) =>
                                                    message.error(err instanceof Error ? err.message : "Xóa chốt thất bại")
                                                );
                                        }}
                                    >
                                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                                    </Popconfirm>
                                ) : (
                                    <Tag>{cp.zone_key || "Ngoài Khu vực"}</Tag>
                                )
                            }
                        >
                            <Space wrap size={4} style={{ marginBottom: 6 }}>
                                <Tag>{cp.checkpoint_key}</Tag>
                                <Tag color="blue">{cp.zone_key || "Ngoài Khu vực"}</Tag>
                                <Tag>({cp.x_pct.toFixed(1)}%, {cp.y_pct.toFixed(1)}%)</Tag>
                            </Space>
                            <Text type="secondary" style={{ fontSize: 12, display: "block" }}>
                                {(cp.description_md || "Chưa có mô tả Markdown").slice(0, 180)}
                            </Text>
                        </Card>
                    </Col>
                ))
            )}
        </Row>
    );

    return (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Card
                size="small"
                title={
                    <Space wrap>
                        <PictureOutlined />
                        <span>
                            Bản đồ Số Khu đô thị ({cards.length} Khu vực · {checkpoints.length} Chốt/Pin)
                        </span>
                    </Space>
                }
                extra={
                    editableMap ? (
                        <Space wrap>
                            <Button
                                type="primary"
                                size="small"
                                icon={<PlusOutlined />}
                                onClick={() => openZoneModal(null)}
                            >
                                Thêm khu vực
                            </Button>
                            <Upload
                                accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                                showUploadList={false}
                                customRequest={handleUpload}
                            >
                                <Button icon={<UploadOutlined />} loading={uploading} size="small">
                                    Tải ảnh 2D (≤ 5MB)
                                </Button>
                            </Upload>
                            {hasZoneMapImage && (
                                <Popconfirm title="Xóa ảnh sơ đồ 2D?" onConfirm={handleDeleteMap}>
                                    <Button danger icon={<DeleteOutlined />} size="small">Gỡ ảnh</Button>
                                </Popconfirm>
                            )}
                        </Space>
                    ) : undefined
                }
            >
                {aspectWarning && (
                    <Alert
                        type="warning"
                        showIcon
                        closable
                        onClose={() => setAspectWarning(false)}
                        style={{ marginBottom: 12 }}
                        message="Ảnh 2D mới có tỷ lệ khung hình khác biệt đáng kể (>10%) so với ảnh cũ"
                        description="Vui lòng kiểm tra và kéo chỉnh nhẹ lại Polygon Khu vực / vị trí Chốt nếu cần khớp sát bản vẽ mới."
                    />
                )}
                <Tabs
                    size="small"
                    defaultActiveKey="canvas"
                    items={[
                        {
                            key: "canvas",
                            label: (
                                <Space size={4}>
                                    <PictureOutlined />
                                    <span>{isLiveMonitor ? "Bản đồ Số Trực quan Live" : "Bản đồ Số (Polygon & Chốt)"}</span>
                                </Space>
                            ),
                            children: (
                                <DigitalUrbanMapCanvas
                                    mode={isLiveMonitor ? "live" : "edit"}
                                    projectId={projectId}
                                    runId={runId}
                                    zones={cards}
                                    checkpoints={checkpoints}
                                    personas={staticPersonas}
                                    digitalMap={digitalMap}
                                    hasZoneMapImage={hasZoneMapImage}
                                    hasDigitalMap={effectiveHasDigitalMap}
                                    imgCacheKey={imgVersion}
                                    agentStatuses={agentStatuses}
                                    recentMovements={recentMovements}
                                    onOpenAgentTimeline={onOpenAgentTimeline}
                                    onRefreshMap={() => onMapUpdated?.(hasZoneMapImage)}
                                    onEditZoneDetails={editableMap ? openZoneModal : undefined}
                                    onAssignZonePersonas={editableMap ? openAssignModal : undefined}
                                    onDeleteZone={editableMap ? (z) => void handleDirectDeleteZone(z) : undefined}
                                />
                            ),
                        },
                        {
                            key: "checkpoints",
                            label: (
                                <Space size={4}>
                                    <PushpinOutlined />
                                    <span>Chốt &amp; Pin ({checkpoints.length})</span>
                                </Space>
                            ),
                            children: checkpointCardsContent,
                        },
                        {
                            key: "cards",
                            label: (
                                <Space size={4}>
                                    <EnvironmentOutlined />
                                    <span>Quản lý Khu vực ({cards.length})</span>
                                </Space>
                            ),
                            children: zoneCardsContent,
                        },
                    ]}
                />
            </Card>

            <Modal
                title={editingZone ? `Chỉnh sửa Khu vực: ${editingZone.name}` : "Thêm Khu vực mới"}
                open={zoneModalOpen}
                destroyOnHidden
                width={660}
                onCancel={() => setZoneModalOpen(false)}
                footer={[
                    editingZone?.id && staticPersonas ? (
                        <Button
                            key="assign"
                            icon={<UserAddOutlined />}
                            style={{ float: "left" }}
                            onClick={() => {
                                const z = editingZone;
                                setZoneModalOpen(false);
                                openAssignModal(z);
                            }}
                        >
                            Gắn Nhân sự &amp; Cư dân
                        </Button>
                    ) : null,
                    <Button key="cancel" onClick={() => setZoneModalOpen(false)}>
                        Hủy
                    </Button>,
                    <Button key="ok" type="primary" loading={savingZone} onClick={() => zoneForm.submit()}>
                        {editingZone ? "Lưu thay đổi" : "Tạo khu vực"}
                    </Button>,
                ]}
            >
                <Form form={zoneForm} layout="vertical" onFinish={handleSaveZone}>
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="zone_key"
                                label="Mã khu vực (zone_key)"
                                rules={[{ required: true, message: "Nhập mã khu vực (vd: TOWER_R1)" }]}
                                extra={
                                    editingZone
                                        ? "Nếu đổi mã, hệ thống tự cập nhật home_zone cho toàn bộ Persona thuộc khu vực này."
                                        : "Chỉ gồm chữ in hoa, số, gạch dưới (tự chuẩn hóa)."
                                }
                            >
                                <Input placeholder="vd: TOWER_R1 hoặc BASEMENT_B1" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="name"
                                label="Tên hiển thị khu vực"
                                rules={[{ required: true, message: "Nhập tên khu vực" }]}
                            >
                                <Input placeholder="vd: Tòa R1 — Khối căn hộ" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={11}>
                            <Form.Item name="zone_type" label="Loại khu vực" rules={[{ required: true }]}>
                                <Select options={ZONE_TYPE_OPTIONS} />
                            </Form.Item>
                        </Col>
                        <Col xs={12} sm={6}>
                            <Form.Item name="fill_color" label="Màu Polygon">
                                <Input type="color" />
                            </Form.Item>
                        </Col>
                        <Col xs={12} sm={7}>
                            <Form.Item name="sort_order" label="Thứ tự hiển thị">
                                <InputNumber min={0} max={9999} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                    </Row>
                    <Form.Item
                        name="description"
                        label="Mô tả vai trò / Đặc điểm khu vực (≤ 240 ký tự khi nạp Agent)"
                        extra="Giúp Agent phân biệt chức năng từng khu vực trong bản đồ khu đô thị."
                    >
                        <TextArea
                            rows={2}
                            maxLength={240}
                            showCount
                            placeholder="vd: Khối căn hộ tầng 1-30, có 4 thang máy khách và 1 thang hàng."
                        />
                    </Form.Item>
                    <Form.Item
                        name="ambient_signals"
                        label="Tín hiệu Ngữ cảnh Động tại khu vực (Mỗi dòng 1 tình huống — Nạp vào building_signals)"
                        extra="Hoàn toàn động theo dự án bạn cấu hình. Nếu để trống, Agent chỉ nhận mô tả khu vực và nhịp thời gian chung theo giờ."
                    >
                        <TextArea
                            rows={4}
                            maxLength={2000}
                            showCount
                            placeholder={
                                "vd:\nThang máy khách số 2 rung lắc nhẹ ở tầng cao từ sáng nay.\nHóa đơn phí nước tháng này có hộ phản ánh chưa khớp chỉ số."
                            }
                        />
                    </Form.Item>
                </Form>
            </Modal>

            <Modal
                title={`Chuyển Nhân sự/Cư dân trước khi xóa "${deletingZone?.name || ""}"`}
                open={Boolean(deletingZone)}
                destroyOnHidden
                onCancel={() => setDeletingZone(null)}
                onOk={() => void handleConfirmReassignDelete()}
                confirmLoading={deletingBusy}
                okButtonProps={{ danger: true, disabled: !reassignTarget || otherZonesForDelete.length === 0 }}
                okText="Chuyển & Xóa khu vực"
                cancelText="Hủy"
            >
                {otherZonesForDelete.length === 0 ? (
                    <Alert
                        type="error"
                        showIcon
                        message="Không thể xóa khu vực duy nhất đang chứa Persona"
                        description={`Đang có ${deletingZone?.persona_count || 0} nhân sự/cư dân thuộc khu vực này và chưa có khu vực khác để chuyển sang.`}
                    />
                ) : (
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                        <Alert
                            type="warning"
                            showIcon
                            message={`Khu vực "${deletingZone?.name}" đang được ${deletingZone?.persona_count || 0} Persona chọn làm vị trí mặc định.`}
                            description="Chọn khu vực thay thế để tự động chuyển toàn bộ các Persona đó trước khi xóa:"
                        />
                        <Select
                            style={{ width: "100%" }}
                            value={reassignTarget}
                            onChange={(val) => setReassignTarget(val)}
                            options={otherZonesForDelete.map((oz) => ({
                                value: oz.zone_key,
                                label: `${oz.name} (${oz.zone_key})`,
                            }))}
                        />
                    </Space>
                )}
            </Modal>

            <Modal
                title={`Gắn Nhân sự & Cư dân vào "${assignModalZone?.name || ""}"`}
                open={Boolean(assignModalZone)}
                destroyOnHidden
                width={620}
                onCancel={() => setAssignModalZone(null)}
                onOk={() => void handleSaveAssignPersonas()}
                confirmLoading={assigningBusy}
                okText="Lưu gắn người"
                cancelText="Hủy"
            >
                {assignModalZone && (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <Alert
                            type="info"
                            showIcon
                            message={`Khu vực đích: ${assignModalZone.name} (${assignModalZone.zone_key})`}
                            description="Chọn các Persona (Ban Quản lý & Cư dân) đặt vị trí mặc định tại Khu vực này. Các Persona đang thuộc Khu vực khác khi được chọn sẽ tự chuyển về đây."
                        />
                        <div>
                            <Text strong style={{ display: "block", marginBottom: 6 }}>
                                Danh sách Nhân sự &amp; Cư dân ({assignSelectedIds.length} đã chọn)
                            </Text>
                            <Select
                                mode="multiple"
                                allowClear
                                showSearch
                                optionFilterProp="label"
                                style={{ width: "100%" }}
                                placeholder="Chọn Nhân sự & Cư dân..."
                                value={assignSelectedIds}
                                onChange={(vals) => setAssignSelectedIds(vals)}
                                options={(staticPersonas || []).map((p) => ({
                                    value: p.id,
                                    label: `${p.group_type === "BQL" ? "[BQL]" : "[Cư dân]"} ${p.full_name} — ${p.role_title} (Hiện tại: ${p.home_zone})`,
                                }))}
                            />
                        </div>
                        {cards.some((c) => c.zone_key !== assignModalZone.zone_key) && (
                            <div>
                                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                                    Nếu bỏ chọn người đang ở Khu vực này, tự động chuyển họ sang:
                                </Text>
                                <Select
                                    style={{ width: "100%" }}
                                    value={assignFallbackZoneKey}
                                    onChange={(val) => setAssignFallbackZoneKey(val)}
                                    options={cards
                                        .filter((c) => c.zone_key !== assignModalZone.zone_key)
                                        .map((oz) => ({
                                            value: oz.zone_key,
                                            label: `${oz.name} (${oz.zone_key})`,
                                        }))}
                                />
                            </div>
                        )}
                    </Space>
                )}
            </Modal>
        </Space>
    );
};
