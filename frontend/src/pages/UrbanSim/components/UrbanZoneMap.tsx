import { DeleteOutlined, EnvironmentOutlined, PictureOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, Badge, Button, Card, Col, Popconfirm, Row, Space, Tag, Typography, Upload, message } from "antd";
import type { UploadProps } from "antd";
import React, { useState } from "react";
import { getZoneMapImageUrl, urbanSimApi, UrbanSimZone, ZoneTopologyCard } from "../../../services/urbanSimApi";

const { Text } = Typography;

const ZONE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
    LOBBY: { label: "Sảnh & Lễ tân", color: "blue" },
    OFFICE: { label: "Văn phòng BQL", color: "geekblue" },
    TECHNICAL: { label: "Kỹ thuật M&E", color: "orange" },
    SECURITY: { label: "An ninh & Hầm", color: "volcano" },
    TOWER: { label: "Tháp Căn hộ", color: "green" },
};

interface UrbanZoneMapProps {
    projectId: string;
    hasZoneMapImage: boolean;
    topologyZones?: ZoneTopologyCard[];
    staticZones?: UrbanSimZone[];
    editableMap?: boolean;
    onMapUpdated?: (hasImage: boolean) => void;
}

export const UrbanZoneMap: React.FC<UrbanZoneMapProps> = ({
    projectId,
    hasZoneMapImage,
    topologyZones,
    staticZones,
    editableMap = false,
    onMapUpdated,
}) => {
    const [imgVersion, setImgVersion] = useState<string>("1");
    const [uploading, setUploading] = useState(false);
    const [imgError, setImgError] = useState(false);

    const cards: ZoneTopologyCard[] = topologyZones
        ? topologyZones
        : (staticZones || []).map((z) => ({
            zone_key: z.zone_key,
            name: z.name,
            zone_type: z.zone_type,
            description: z.description,
            agents_here: [],
            open_incidents: [],
        }));

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
            await urbanSimApi.uploadZoneMapImage(projectId, rawFile);
            setImgError(false);
            setImgVersion(String(Date.now()));
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
            setImgError(false);
            message.success("Đã gỡ ảnh sơ đồ 2D (giữ chế độ thẻ Topology).");
            onMapUpdated?.(false);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể xóa ảnh");
        }
    };

    return (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            {editableMap && (
                <Card
                    size="small"
                    title={<Space><PictureOutlined /><span>Sơ đồ mặt bằng 2D khu đô thị (Tùy chọn — Không dùng bản đồ Bắc Kinh)</span></Space>}
                    extra={
                        <Space wrap>
                            <Upload
                                accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                                showUploadList={false}
                                customRequest={handleUpload}
                            >
                                <Button icon={<UploadOutlined />} loading={uploading} size="small">
                                    Tải ảnh PNG/JPG/WEBP (≤ 5MB)
                                </Button>
                            </Upload>
                            {hasZoneMapImage && (
                                <Popconfirm title="Xóa ảnh sơ đồ 2D và quay về sơ đồ thẻ?" onConfirm={handleDeleteMap}>
                                    <Button danger icon={<DeleteOutlined />} size="small">Gỡ ảnh</Button>
                                </Popconfirm>
                            )}
                        </Space>
                    }
                >
                    {hasZoneMapImage && !imgError ? (
                        <div style={{ textAlign: "center", background: "#fafafa", borderRadius: 8, padding: 12 }}>
                            <img
                                src={getZoneMapImageUrl(projectId, imgVersion)}
                                alt="Sơ đồ mặt bằng MulberryLane"
                                style={{ maxWidth: "100%", maxHeight: 360, objectFit: "contain", borderRadius: 6 }}
                                onError={() => setImgError(true)}
                            />
                        </div>
                    ) : (
                        <Alert
                            type="info"
                            showIcon
                            message="Đang hiển thị Sơ đồ Khu vực dạng Thẻ (Zone Topology)"
                            description="Bạn có thể tải lên ảnh mặt bằng 2D PNG/JPEG/WEBP (tùy chọn) hoặc sử dụng trực tiếp lưới Zone nghiệp vụ bên dưới."
                        />
                    )}
                </Card>
            )}

            {!editableMap && hasZoneMapImage && !imgError && (
                <Card size="small" title={<Space><PictureOutlined /><span>Sơ đồ 2D Khu đô thị</span></Space>}>
                    <div style={{ textAlign: "center", background: "#fafafa", borderRadius: 8, padding: 8 }}>
                        <img
                            src={getZoneMapImageUrl(projectId, imgVersion)}
                            alt="Sơ đồ 2D Khu đô thị"
                            style={{ maxWidth: "100%", maxHeight: 320, objectFit: "contain", borderRadius: 6 }}
                            onError={() => setImgError(true)}
                        />
                    </div>
                </Card>
            )}

            <Row gutter={[12, 12]}>
                {cards.map((z) => {
                    const meta = ZONE_TYPE_LABELS[z.zone_type] || { label: z.zone_type, color: "default" };
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
                                    <Space size={6}>
                                        <Tag color={meta.color}>{meta.label}</Tag>
                                        {z.open_incidents.length > 0 && (
                                            <Badge count={z.open_incidents.length} title="Sự vụ đang mở" />
                                        )}
                                    </Space>
                                }
                                style={{ height: "100%" }}
                            >
                                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                                    {z.description || z.zone_key}
                                </Text>
                                <div style={{ marginBottom: 6 }}>
                                    <Text style={{ fontSize: 12, fontWeight: 600 }}>
                                        Hiện diện ({z.agents_here.length}):
                                    </Text>
                                </div>
                                {z.agents_here.length === 0 ? (
                                    <Text type="secondary" style={{ fontSize: 12 }}>Chưa có tác nhân tại khu vực</Text>
                                ) : (
                                    <Space size={[4, 4]} wrap>
                                        {z.agents_here.map((ag) => (
                                            <Tag
                                                key={ag.agent_id}
                                                color={ag.group_type === "BQL" ? "blue" : "purple"}
                                                style={{ marginInlineEnd: 0 }}
                                            >
                                                #{ag.agent_id} {ag.full_name}
                                            </Tag>
                                        ))}
                                    </Space>
                                )}
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
        </Space>
    );
};
