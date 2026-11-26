import {
    CheckCircleOutlined,
    CloudDownloadOutlined,
    CloudSyncOutlined,
    CloudUploadOutlined,
    DeleteOutlined,
    DownloadOutlined,
    ExclamationCircleOutlined,
    HistoryOutlined,
    InboxOutlined,
    KeyOutlined,
    LockOutlined,
    ReloadOutlined,
    RollbackOutlined,
    SafetyCertificateOutlined,
    SearchOutlined,
    UnlockOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Badge,
    Button,
    Card,
    Checkbox,
    Col,
    Descriptions,
    Divider,
    Input,
    Popconfirm,
    Radio,
    Result,
    Row,
    Select,
    Space,
    Spin,
    Switch,
    Table,
    Tabs,
    Tag,
    Typography,
    Upload,
    message,
} from "antd";
import type { UploadFile } from "antd";
import dayjs from "dayjs";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
    BackupInventoryResponse,
    BackupScopeMeta,
    BackupStatusResponse,
    RestoreExecuteResponse,
    RestorePreviewResponse,
    ScopeDiffItem,
    SnapshotRecord,
    getStoredAdminBackupKey,
    setStoredAdminBackupKey,
    systemBackupApi,
} from "../../services/systemBackupApi";

const { Title, Text } = Typography;
const { Dragger } = Upload;

const GROUP_ORDER = ["ai_runtime", "urban_sim", "platform", "workspace"];

function formatBytes(bytes: number): string {
    if (!bytes || bytes <= 0) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function SystemBackupPage() {
    const [activeTab, setActiveTab] = useState<string>("export");
    const [statusLoading, setStatusLoading] = useState<boolean>(true);
    const [statusInfo, setStatusInfo] = useState<BackupStatusResponse | null>(null);
    const [adminKeyInput, setAdminKeyInput] = useState<string>(() => getStoredAdminBackupKey());

    const [inventoryLoading, setInventoryLoading] = useState<boolean>(false);
    const [inventory, setInventory] = useState<BackupInventoryResponse | null>(null);

    // Export state
    const [selectedScopes, setSelectedScopes] = useState<string[]>([]);
    const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
    const [includeSecrets, setIncludeSecrets] = useState<boolean>(false);
    const [exportPassphrase, setExportPassphrase] = useState<string>("");
    const [exportPassphraseConfirm, setExportPassphraseConfirm] = useState<string>("");
    const [exportNotes, setExportNotes] = useState<string>("");
    const [exporting, setExporting] = useState<boolean>(false);

    // Restore state
    const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
    const [selectedRestoreFile, setSelectedRestoreFile] = useState<File | null>(null);
    const [restoreMode, setRestoreMode] = useState<"MERGE_UPSERT" | "REPLACE_SCOPE">("MERGE_UPSERT");
    const [restoreSecrets, setRestoreSecrets] = useState<boolean>(true);
    const [restorePassphrase, setRestorePassphrase] = useState<string>("");
    const [restoreScopes, setRestoreScopes] = useState<string[]>([]);
    const [createPreRestoreSnapshot, setCreatePreRestoreSnapshot] = useState<boolean>(true);
    const [previewing, setPreviewing] = useState<boolean>(false);
    const [previewData, setPreviewData] = useState<RestorePreviewResponse | null>(null);
    const [confirmApplyChecked, setConfirmApplyChecked] = useState<boolean>(false);
    const [replaceConfirmText, setReplaceConfirmText] = useState<string>("");
    const [restoring, setRestoring] = useState<boolean>(false);
    const [restoreResult, setRestoreResult] = useState<RestoreExecuteResponse | null>(null);

    // Snapshots state
    const [snapshots, setSnapshots] = useState<SnapshotRecord[]>([]);
    const [snapshotsLoading, setSnapshotsLoading] = useState<boolean>(false);
    const [manualSnapNote, setManualSnapNote] = useState<string>("");
    const [creatingSnap, setCreatingSnap] = useState<boolean>(false);
    const [rollingBackId, setRollingBackId] = useState<string | null>(null);

    const isUnlocked = useMemo(() => {
        if (!statusInfo) return false;
        return !statusInfo.admin_key_required || statusInfo.admin_key_valid;
    }, [statusInfo]);

    const loadAllData = useCallback(async (showSpinner = true) => {
        if (showSpinner) {
            setStatusLoading(true);
        }
        try {
            const st = await systemBackupApi.getStatus();
            setStatusInfo(st);
            if (!st.admin_key_required || st.admin_key_valid) {
                setInventoryLoading(true);
                setSnapshotsLoading(true);
                const [inv, snaps] = await Promise.all([
                    systemBackupApi.getInventory(),
                    systemBackupApi.listSnapshots(),
                ]);
                setInventory(inv);
                setSnapshots(snaps);
                setSelectedScopes((prev) =>
                    prev.length > 0 ? prev : inv.scopes.map((s) => s.key),
                );
            } else {
                setInventory(null);
                setSnapshots([]);
            }
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không thể kiểm tra trạng thái Backup.");
        } finally {
            setStatusLoading(false);
            setInventoryLoading(false);
            setSnapshotsLoading(false);
        }
    }, []);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            if (!active) return;
            await loadAllData(false);
        }
        void initLoad();
        return () => {
            active = false;
        };
    }, [loadAllData]);

    const handleUnlockAdminKey = async () => {
        setStoredAdminBackupKey(adminKeyInput);
        await loadAllData();
        const st = await systemBackupApi.getStatus();
        if (st.admin_key_required && !st.admin_key_valid) {
            message.error("Khóa ADMIN_BACKUP_KEY không đúng.");
        } else {
            message.success("Đã xác thực quyền Quản trị viên cao nhất.");
        }
    };

    const handleLockAdminKey = () => {
        setStoredAdminBackupKey("");
        setAdminKeyInput("");
        void loadAllData();
    };

    const groupedScopes = useMemo(() => {
        const scopes = inventory?.scopes || [];
        const groups: Record<string, { label: string; items: BackupScopeMeta[] }> = {};
        for (const s of scopes) {
            if (!groups[s.group]) {
                groups[s.group] = { label: s.group_label_vi, items: [] };
            }
            groups[s.group].items.push(s);
        }
        return GROUP_ORDER.filter((g) => groups[g]).map((g) => ({
            groupKey: g,
            ...groups[g],
        }));
    }, [inventory]);

    const handleExport = async () => {
        if (selectedScopes.length === 0) {
            message.warning("Vui lòng chọn ít nhất một phạm vi cấu hình.");
            return;
        }
        if (includeSecrets) {
            if (exportPassphrase.trim().length < 8) {
                message.warning("Passphrase bảo vệ bí mật phải có tối thiểu 8 ký tự.");
                return;
            }
            if (exportPassphrase !== exportPassphraseConfirm) {
                message.warning("Passphrase xác nhận chưa khớp.");
                return;
            }
        }
        setExporting(true);
        try {
            const res = await systemBackupApi.exportBackup({
                scopes: selectedScopes,
                include_secrets: includeSecrets,
                passphrase: includeSecrets ? exportPassphrase : "",
                project_ids: selectedProjectIds.length > 0 ? selectedProjectIds : null,
                notes: exportNotes,
            });
            message.success(
                `Đã xuất gói sao lưu thành công${res.sha256 ? ` (SHA-256: ${res.sha256.slice(0, 12)}...)` : ""}.`,
            );
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xuất gói sao lưu thất bại.");
        } finally {
            setExporting(false);
        }
    };

    const handlePreviewRestore = async () => {
        if (!selectedRestoreFile) {
            message.warning("Vui lòng chọn tệp gói sao lưu (.zip) trước.");
            return;
        }
        setPreviewing(true);
        setRestoreResult(null);
        setConfirmApplyChecked(false);
        setReplaceConfirmText("");
        try {
            const res = await systemBackupApi.previewRestore({
                file: selectedRestoreFile,
                scopes: restoreScopes.length > 0 ? restoreScopes : null,
                mode: restoreMode,
                restore_secrets: restoreSecrets,
                passphrase: restorePassphrase,
            });
            setPreviewData(res);
            if (restoreScopes.length === 0 && res.manifest?.scopes) {
                setRestoreScopes(res.manifest.scopes);
            }
            message.success("Đã kiểm tra gói sao lưu và lập bảng xem trước thay đổi.");
        } catch (err) {
            setPreviewData(null);
            message.error(err instanceof Error ? err.message : "Không thể đọc gói sao lưu.");
        } finally {
            setPreviewing(false);
        }
    };

    const handleExecuteRestore = async () => {
        if (!selectedRestoreFile || !previewData || !previewData.can_apply) return;
        if (!confirmApplyChecked) {
            message.warning("Vui lòng tích xác nhận trước khi thực thi khôi phục.");
            return;
        }
        if (restoreMode === "REPLACE_SCOPE" && replaceConfirmText.trim() !== "RESTORE") {
            message.warning("Chế độ REPLACE_SCOPE yêu cầu nhập chính xác chữ RESTORE để xác nhận.");
            return;
        }
        setRestoring(true);
        try {
            const res = await systemBackupApi.executeRestore({
                file: selectedRestoreFile,
                scopes: restoreScopes.length > 0 ? restoreScopes : null,
                mode: restoreMode,
                restore_secrets: restoreSecrets,
                passphrase: restorePassphrase,
                create_snapshot: createPreRestoreSnapshot,
            });
            setRestoreResult(res);
            message.success("Khôi phục cấu hình thành công!");
            await loadAllData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Khôi phục cấu hình thất bại.");
        } finally {
            setRestoring(false);
        }
    };

    const handleCreateManualSnapshot = async () => {
        setCreatingSnap(true);
        try {
            await systemBackupApi.createSnapshot(
                manualSnapNote.trim() || "Bản chụp thủ công từ giao diện quản trị",
            );
            setManualSnapNote("");
            message.success("Đã tạo bản chụp trạng thái hiện tại.");
            await loadAllData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Tạo bản chụp thất bại.");
        } finally {
            setCreatingSnap(false);
        }
    };

    const handleRollback = async (snapshotId: string) => {
        setRollingBackId(snapshotId);
        try {
            await systemBackupApi.rollbackSnapshot(snapshotId);
            message.success(`Đã hoàn tác toàn bộ cấu hình về bản chụp ${snapshotId}.`);
            await loadAllData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Hoàn tác thất bại.");
        } finally {
            setRollingBackId(null);
        }
    };

    const handleDeleteSnapshot = async (snapshotId: string) => {
        try {
            await systemBackupApi.deleteSnapshot(snapshotId);
            message.success(`Đã xóa bản chụp ${snapshotId}.`);
            await loadAllData();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xóa bản chụp thất bại.");
        }
    };

    const scopeLabelByKey = useMemo(() => {
        const map: Record<string, string> = {};
        for (const s of inventory?.scopes || []) {
            map[s.key] = s.label_vi;
        }
        return map;
    }, [inventory]);

    if (statusLoading && !statusInfo) {
        return (
            <div style={{ padding: 48, textAlign: "center" }}>
                <Spin size="large" />
                <div style={{ marginTop: 12 }}>
                    <Text type="secondary">Đang kiểm tra trạng thái Backup &amp; Restore...</Text>
                </div>
            </div>
        );
    }

    return (
        <div style={{ padding: "16px 24px", maxWidth: 1260, margin: "0 auto" }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card size="small">
                    <Row gutter={[16, 12]} align="middle" justify="space-between">
                        <Col xs={24} md={15}>
                            <Space align="center">
                                <CloudSyncOutlined style={{ fontSize: 24, color: "#0000CC" }} />
                                <div>
                                    <Title level={4} style={{ margin: 0 }}>
                                        Sao lưu &amp; Khôi phục Cấu hình Hệ thống (Migration Manager)
                                    </Title>
                                    <Text type="secondary">
                                        Dành cho Quản trị viên cao nhất: chọn lọc phạm vi cấu hình đã kiểm thử để đóng gói và migrate lên Production an toàn.
                                    </Text>
                                </div>
                            </Space>
                        </Col>
                        <Col xs={24} md={9} style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
                            {statusInfo?.admin_key_required ? (
                                isUnlocked ? (
                                    <Space>
                                        <Tag color="green" icon={<UnlockOutlined />}>
                                            Đã mở khóa ADMIN_BACKUP_KEY
                                        </Tag>
                                        <Button size="small" icon={<LockOutlined />} onClick={handleLockAdminKey}>
                                            Khóa phiên
                                        </Button>
                                    </Space>
                                ) : (
                                    <Tag color="red" icon={<LockOutlined />}>
                                        Yêu cầu ADMIN_BACKUP_KEY
                                    </Tag>
                                )
                            ) : (
                                <Tag color="blue" icon={<SafetyCertificateOutlined />}>
                                    Chế độ Local (chưa đặt ADMIN_BACKUP_KEY)
                                </Tag>
                            )}
                            <Button icon={<ReloadOutlined />} onClick={() => void loadAllData()} loading={inventoryLoading}>
                                Làm mới
                            </Button>
                        </Col>
                    </Row>
                </Card>

                {statusInfo?.admin_key_required && !isUnlocked && (
                    <Card
                        size="small"
                        title={<Space><KeyOutlined /><span>Xác thực Quản trị viên Cao nhất</span></Space>}
                    >
                        <Alert
                            type="warning"
                            showIcon
                            style={{ marginBottom: 12 }}
                            message="Môi trường này đã bật bảo vệ ADMIN_BACKUP_KEY"
                            description="Nhập giá trị ADMIN_BACKUP_KEY được cấu hình trên máy chủ để mở khóa chức năng Sao lưu, Khôi phục và Hoàn tác (khóa chỉ lưu tạm trong sessionStorage của tab hiện tại)."
                        />
                        <Space.Compact style={{ width: "100%", maxWidth: 520 }}>
                            <Input.Password
                                placeholder="Nhập ADMIN_BACKUP_KEY..."
                                value={adminKeyInput}
                                onChange={(e) => setAdminKeyInput(e.target.value)}
                                onPressEnter={() => void handleUnlockAdminKey()}
                            />
                            <Button type="primary" icon={<UnlockOutlined />} onClick={() => void handleUnlockAdminKey()}>
                                Mở khóa Quản trị
                            </Button>
                        </Space.Compact>
                    </Card>
                )}

                {isUnlocked && !statusInfo?.admin_key_required && (
                    <Alert
                        type="info"
                        showIcon
                        message="Mẹo bảo mật khi triển khai Production"
                        description="Biến môi trường ADMIN_BACKUP_KEY hiện đang để trống (phù hợp thử nghiệm Local). Khi vận hành Production, hãy thiết lập ADMIN_BACKUP_KEY trong tệp .env để chỉ Quản trị viên cao nhất mới thao tác được màn hình này."
                    />
                )}

                {isUnlocked && inventory && inventory.active_urban_sim_runs.length > 0 && (
                    <Alert
                        type="warning"
                        showIcon
                        message={`Đang có ${inventory.active_urban_sim_runs.length} phiên mô phỏng UrbanSim hoạt động (${inventory.active_urban_sim_runs.join(", ")})`}
                        description="Hệ thống sẽ chặn thao tác Restore/Rollback liên quan tới dữ liệu UrbanSim cho tới khi các phiên chạy này được tạm dừng hoặc hoàn tất."
                    />
                )}

                {isUnlocked && (
                    <Tabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        type="card"
                        items={[
                            {
                                key: "export",
                                label: (
                                    <Space>
                                        <CloudDownloadOutlined />
                                        <span>1. Sao lưu &amp; Xuất gói (Export)</span>
                                    </Space>
                                ),
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        <Card size="small" title="Chọn nhanh Phạm vi &amp; Lọc Dự án">
                                            <Space wrap style={{ marginBottom: 12 }}>
                                                <Button
                                                    size="small"
                                                    onClick={() => {
                                                        setSelectedScopes((inventory?.scopes || []).map((s) => s.key));
                                                    }}
                                                >
                                                    Chọn tất cả ({inventory?.scopes.length || 0})
                                                </Button>
                                                <Button size="small" onClick={() => setSelectedScopes([])}>
                                                    Bỏ chọn tất cả
                                                </Button>
                                                <Button
                                                    size="small"
                                                    type="primary"
                                                    ghost
                                                    onClick={() => {
                                                        setSelectedScopes((inventory?.scopes || []).map((s) => s.key));
                                                        setIncludeSecrets(false);
                                                    }}
                                                >
                                                    Gói chuẩn Migrate Production (Không gồm bí mật)
                                                </Button>
                                                <Button
                                                    size="small"
                                                    type="primary"
                                                    onClick={() => {
                                                        setSelectedScopes((inventory?.scopes || []).map((s) => s.key));
                                                        setIncludeSecrets(true);
                                                    }}
                                                >
                                                    Gói đầy đủ Migrate Production (Kèm bí mật mã hóa)
                                                </Button>
                                            </Space>

                                            <Row gutter={[12, 12]}>
                                                <Col xs={24} md={12}>
                                                    <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                        Lọc theo Dự án UrbanSim (tùy chọn — để trống = tất cả dự án)
                                                    </Text>
                                                    <Select
                                                        mode="multiple"
                                                        allowClear
                                                        style={{ width: "100%" }}
                                                        placeholder="Tất cả dự án mô phỏng"
                                                        value={selectedProjectIds}
                                                        onChange={setSelectedProjectIds}
                                                        options={(inventory?.projects || []).map((p) => ({
                                                            value: p.id,
                                                            label: `${p.name} (${p.slug}) — ${p.zones_count} zones, ${p.personas_count} personas`,
                                                        }))}
                                                    />
                                                </Col>
                                                <Col xs={24} md={12}>
                                                    <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                        Ghi chú bản sao lưu
                                                    </Text>
                                                    <Input
                                                        placeholder="VD: Staging v2.12 đã test pass, chuẩn bị lên Prod"
                                                        value={exportNotes}
                                                        onChange={(e) => setExportNotes(e.target.value)}
                                                        maxLength={300}
                                                    />
                                                </Col>
                                            </Row>
                                        </Card>

                                        <Card
                                            size="small"
                                            title={`Danh mục Phạm vi Cấu hình (${selectedScopes.length}/${inventory?.scopes.length || 0} đã chọn)`}
                                        >
                                            <Checkbox.Group
                                                style={{ width: "100%" }}
                                                value={selectedScopes}
                                                onChange={(vals) => setSelectedScopes(vals as string[])}
                                            >
                                                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                                    {groupedScopes.map((grp) => (
                                                        <div key={grp.groupKey}>
                                                            <Text strong style={{ fontSize: 13, color: "#1F1B18" }}>
                                                                {grp.label}
                                                            </Text>
                                                            <Row gutter={[12, 10]} style={{ marginTop: 8 }}>
                                                                {grp.items.map((sc) => (
                                                                    <Col xs={24} md={12} key={sc.key}>
                                                                        <Card
                                                                            size="small"
                                                                            style={{
                                                                                height: "100%",
                                                                                borderColor: selectedScopes.includes(sc.key)
                                                                                    ? "#0000CC"
                                                                                    : "#EAEAEA",
                                                                                background: selectedScopes.includes(sc.key)
                                                                                    ? "#F8FAFF"
                                                                                    : "#FFFFFF",
                                                                            }}
                                                                        >
                                                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                                                                                <Checkbox value={sc.key}>
                                                                                    <Text strong>{sc.label_vi}</Text>
                                                                                </Checkbox>
                                                                                <Space size={4}>
                                                                                    {sc.includes_secrets_possible && (
                                                                                        <Tag color="gold" style={{ margin: 0 }}>
                                                                                            Có bí mật
                                                                                        </Tag>
                                                                                    )}
                                                                                    <Badge
                                                                                        count={sc.count}
                                                                                        showZero
                                                                                        color={sc.count > 0 ? "#0000CC" : "#999999"}
                                                                                    />
                                                                                </Space>
                                                                            </div>
                                                                            <div style={{ marginTop: 4, paddingLeft: 24 }}>
                                                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                                                    {sc.description_vi}
                                                                                </Text>
                                                                            </div>
                                                                        </Card>
                                                                    </Col>
                                                                ))}
                                                            </Row>
                                                        </div>
                                                    ))}
                                                </Space>
                                            </Checkbox.Group>
                                        </Card>

                                        <Card
                                            size="small"
                                            title={
                                                <Space>
                                                    <LockOutlined />
                                                    <span>
                                                        Xử lý Bí mật (API Keys &amp; Mật khẩu Persona — hiện có{" "}
                                                        {inventory?.secrets_summary.total || 0} bí mật)
                                                    </span>
                                                </Space>
                                            }
                                        >
                                            <Radio.Group
                                                value={includeSecrets}
                                                onChange={(e) => setIncludeSecrets(Boolean(e.target.value))}
                                            >
                                                <Space direction="vertical" size="small">
                                                    <Radio value={false}>
                                                        <Text strong>Chỉ sao lưu cấu hình khung (Không mang theo bí mật)</Text>{" "}
                                                        <Text type="secondary">
                                                            — Khi Restore sang Production ở chế độ MERGE, các API Key &amp; mật khẩu đang có trên Production sẽ được giữ nguyên.
                                                        </Text>
                                                    </Radio>
                                                    <Radio value={true}>
                                                        <Text strong>Mang theo bí mật được mã hóa bằng Passphrase</Text>{" "}
                                                        <Text type="secondary">
                                                            — Tự động giải mã từ Fernet key nguồn, mã hóa bằng PBKDF2-SHA256 và tự tái mã hóa theo Fernet key của Production khi Restore.
                                                        </Text>
                                                    </Radio>
                                                </Space>
                                            </Radio.Group>

                                            {includeSecrets && (
                                                <Row gutter={12} style={{ marginTop: 12, maxWidth: 680 }}>
                                                    <Col xs={24} sm={12}>
                                                        <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                            Passphrase bảo vệ gói (tối thiểu 8 ký tự)
                                                        </Text>
                                                        <Input.Password
                                                            placeholder="Nhập passphrase..."
                                                            value={exportPassphrase}
                                                            onChange={(e) => setExportPassphrase(e.target.value)}
                                                        />
                                                    </Col>
                                                    <Col xs={24} sm={12}>
                                                        <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                            Xác nhận Passphrase
                                                        </Text>
                                                        <Input.Password
                                                            placeholder="Nhập lại passphrase..."
                                                            value={exportPassphraseConfirm}
                                                            onChange={(e) => setExportPassphraseConfirm(e.target.value)}
                                                        />
                                                    </Col>
                                                </Row>
                                            )}

                                            <Divider style={{ margin: "14px 0" }} />
                                            <Button
                                                type="primary"
                                                size="large"
                                                icon={<DownloadOutlined />}
                                                loading={exporting}
                                                disabled={selectedScopes.length === 0}
                                                onClick={() => void handleExport()}
                                            >
                                                Xuất &amp; Tải gói Sao lưu (.zip)
                                            </Button>
                                        </Card>
                                    </Space>
                                ),
                            },
                            {
                                key: "restore",
                                label: (
                                    <Space>
                                        <CloudUploadOutlined />
                                        <span>2. Khôi phục &amp; Xem trước (Restore)</span>
                                    </Space>
                                ),
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        <Card size="small" title="Bước 1: Chọn gói sao lưu (.zip) &amp; Cấu hình Khôi phục">
                                            <Row gutter={[16, 16]}>
                                                <Col xs={24} md={12}>
                                                    <Dragger
                                                        accept=".zip,application/zip"
                                                        maxCount={1}
                                                        fileList={uploadFileList}
                                                        beforeUpload={(file) => {
                                                            setSelectedRestoreFile(file);
                                                            setUploadFileList([
                                                                {
                                                                    uid: file.uid,
                                                                    name: file.name,
                                                                    size: file.size,
                                                                    status: "done",
                                                                },
                                                            ]);
                                                            setPreviewData(null);
                                                            setRestoreResult(null);
                                                            setRestoreScopes([]);
                                                            return false;
                                                        }}
                                                        onRemove={() => {
                                                            setSelectedRestoreFile(null);
                                                            setUploadFileList([]);
                                                            setPreviewData(null);
                                                            setRestoreResult(null);
                                                            setRestoreScopes([]);
                                                        }}
                                                    >
                                                        <p className="ant-upload-drag-icon">
                                                            <InboxOutlined />
                                                        </p>
                                                        <p className="ant-upload-text">
                                                            Kéo thả hoặc bấm để chọn tệp sao lưu <code>.zip</code>
                                                        </p>
                                                        <p className="ant-upload-hint">
                                                            Hệ thống kiểm tra SHA-256 và mô phỏng thay đổi (Dry-Run) trước khi ghi Database.
                                                        </p>
                                                    </Dragger>
                                                </Col>

                                                <Col xs={24} md={12}>
                                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                        <div>
                                                            <Text strong style={{ display: "block", marginBottom: 4 }}>
                                                                Chiến lược ghi dữ liệu (Restore Mode)
                                                            </Text>
                                                            <Radio.Group
                                                                value={restoreMode}
                                                                onChange={(e) => {
                                                                    setRestoreMode(e.target.value);
                                                                    setPreviewData(null);
                                                                }}
                                                            >
                                                                <Space direction="vertical" size={4}>
                                                                    <Radio value="MERGE_UPSERT">
                                                                        <Text strong>MERGE_UPSERT (Khuyến nghị)</Text> — Cập nhật bản ghi trùng mã/slug, thêm mới bản ghi chưa có, không xóa dữ liệu khác.
                                                                    </Radio>
                                                                    <Radio value="REPLACE_SCOPE">
                                                                        <Text strong type="danger">REPLACE_SCOPE</Text> — Xóa toàn bộ dữ liệu hiện tại trong các phạm vi được chọn rồi nạp mới hoàn toàn từ gói.
                                                                    </Radio>
                                                                </Space>
                                                            </Radio.Group>
                                                        </div>

                                                        <Divider style={{ margin: "8px 0" }} />

                                                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                                            <Text strong>Khôi phục bí mật từ gói (nếu gói có chứa)</Text>
                                                            <Switch
                                                                checked={restoreSecrets}
                                                                onChange={(v) => {
                                                                    setRestoreSecrets(v);
                                                                    setPreviewData(null);
                                                                }}
                                                            />
                                                        </div>

                                                        {restoreSecrets && (
                                                            <Input.Password
                                                                placeholder="Nhập Passphrase giải mã bí mật (nếu gói có mã hóa bí mật)"
                                                                value={restorePassphrase}
                                                                onChange={(e) => setRestorePassphrase(e.target.value)}
                                                            />
                                                        )}

                                                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                                            <Text>Tự động tạo Bản chụp Hoàn tác trước khi Restore</Text>
                                                            <Switch
                                                                checked={createPreRestoreSnapshot}
                                                                onChange={setCreatePreRestoreSnapshot}
                                                            />
                                                        </div>

                                                        <Button
                                                            type="primary"
                                                            icon={<SearchOutlined />}
                                                            loading={previewing}
                                                            disabled={!selectedRestoreFile}
                                                            onClick={() => void handlePreviewRestore()}
                                                        >
                                                            Kiểm tra &amp; Xem trước Thay đổi (Dry-Run)
                                                        </Button>
                                                    </Space>
                                                </Col>
                                            </Row>
                                        </Card>

                                        {previewData && (
                                            <Card
                                                size="small"
                                                title="Bước 2: Kết quả Kiểm tra Toàn vẹn &amp; Xem trước Diff (Dry-Run)"
                                            >
                                                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                                    {previewData.blocking_errors.length > 0 && (
                                                        <Alert
                                                            type="error"
                                                            showIcon
                                                            message="Không thể khôi phục do có điều kiện chặn"
                                                            description={previewData.blocking_errors.join(" ")}
                                                        />
                                                    )}

                                                    {previewData.warnings.length > 0 && (
                                                        <Alert
                                                            type="warning"
                                                            showIcon
                                                            message={`Lưu ý (${previewData.warnings.length})`}
                                                            description={
                                                                <ul style={{ margin: 0, paddingLeft: 18 }}>
                                                                    {previewData.warnings.map((w, idx) => (
                                                                        <li key={idx}>{w}</li>
                                                                    ))}
                                                                </ul>
                                                            }
                                                        />
                                                    )}

                                                    <Descriptions size="small" bordered column={{ xs: 1, sm: 2, md: 3 }}>
                                                        <Descriptions.Item label="Ngày tạo gói">
                                                            {dayjs(previewData.manifest.created_at).format("DD/MM/YYYY HH:mm:ss")}
                                                        </Descriptions.Item>
                                                        <Descriptions.Item label="Chế độ Restore">
                                                            <Tag color={previewData.mode === "REPLACE_SCOPE" ? "red" : "blue"}>
                                                                {previewData.mode}
                                                            </Tag>
                                                        </Descriptions.Item>
                                                        <Descriptions.Item label="Bí mật sẽ khôi phục">
                                                            <Tag color={previewData.totals.secrets_to_restore > 0 ? "green" : "default"}>
                                                                {previewData.totals.secrets_to_restore} bí mật
                                                            </Tag>
                                                        </Descriptions.Item>
                                                        <Descriptions.Item label="SHA-256 gói">
                                                            <Text code>{previewData.manifest.package_sha256.slice(0, 20)}...</Text>
                                                        </Descriptions.Item>
                                                        <Descriptions.Item label="Dự án trong gói" span={2}>
                                                            {(previewData.manifest.project_slugs || []).join(", ") || "Không có"}
                                                        </Descriptions.Item>
                                                        {previewData.manifest.notes && (
                                                            <Descriptions.Item label="Ghi chú gói" span={3}>
                                                                {previewData.manifest.notes}
                                                            </Descriptions.Item>
                                                        )}
                                                    </Descriptions>

                                                    <div>
                                                        <Text strong style={{ display: "block", marginBottom: 6 }}>
                                                            Chọn lọc phạm vi muốn áp dụng từ gói (bỏ tick nếu chỉ muốn khôi phục một phần):
                                                        </Text>
                                                        <Checkbox.Group
                                                            value={restoreScopes}
                                                            onChange={(vals) => {
                                                                setRestoreScopes(vals as string[]);
                                                            }}
                                                        >
                                                            <Space wrap>
                                                                {(previewData.manifest.scopes || []).map((sk) => (
                                                                    <Checkbox key={sk} value={sk}>
                                                                        {scopeLabelByKey[sk] || sk}
                                                                    </Checkbox>
                                                                ))}
                                                            </Space>
                                                        </Checkbox.Group>
                                                        <Button
                                                            size="small"
                                                            style={{ marginLeft: 8 }}
                                                            onClick={() => void handlePreviewRestore()}
                                                        >
                                                            Cập nhật bảng Diff theo phạm vi đã chọn
                                                        </Button>
                                                    </div>

                                                    <Table<ScopeDiffItem>
                                                        rowKey="scope"
                                                        size="small"
                                                        pagination={false}
                                                        dataSource={previewData.scope_diffs}
                                                        columns={[
                                                            {
                                                                title: "Phạm vi cấu hình",
                                                                dataIndex: "label_vi",
                                                                key: "label_vi",
                                                                render: (val: string, rec) => (
                                                                    <Space direction="vertical" size={0}>
                                                                        <Text strong>{val}</Text>
                                                                        <Text type="secondary" style={{ fontSize: 11 }}>{rec.scope}</Text>
                                                                    </Space>
                                                                ),
                                                            },
                                                            {
                                                                title: "Thêm mới",
                                                                dataIndex: "create_count",
                                                                width: 100,
                                                                render: (n: number) => <Tag color={n > 0 ? "green" : "default"}>{n}</Tag>,
                                                            },
                                                            {
                                                                title: "Cập nhật",
                                                                dataIndex: "update_count",
                                                                width: 100,
                                                                render: (n: number) => <Tag color={n > 0 ? "blue" : "default"}>{n}</Tag>,
                                                            },
                                                            {
                                                                title: "Xóa",
                                                                dataIndex: "delete_count",
                                                                width: 90,
                                                                render: (n: number) => <Tag color={n > 0 ? "red" : "default"}>{n}</Tag>,
                                                            },
                                                        ]}
                                                        expandable={{
                                                            expandedRowRender: (rec) => (
                                                                <Space direction="vertical" size={4}>
                                                                    {rec.samples.create.length > 0 && (
                                                                        <div>
                                                                            <Tag color="green">Thêm mới</Tag>{" "}
                                                                            <Text>{rec.samples.create.join(", ")}</Text>
                                                                        </div>
                                                                    )}
                                                                    {rec.samples.update.length > 0 && (
                                                                        <div>
                                                                            <Tag color="blue">Cập nhật</Tag>{" "}
                                                                            <Text>{rec.samples.update.join(", ")}</Text>
                                                                        </div>
                                                                    )}
                                                                    {rec.samples.delete.length > 0 && (
                                                                        <div>
                                                                            <Tag color="red">Xóa</Tag>{" "}
                                                                            <Text>{rec.samples.delete.join(", ")}</Text>
                                                                        </div>
                                                                    )}
                                                                </Space>
                                                            ),
                                                        }}
                                                    />

                                                    <Divider style={{ margin: "8px 0" }} />

                                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                        <Checkbox
                                                            checked={confirmApplyChecked}
                                                            onChange={(e) => setConfirmApplyChecked(e.target.checked)}
                                                        >
                                                            Tôi đã kiểm tra bảng thay đổi và xác nhận áp dụng cấu hình lên môi trường hiện tại.
                                                        </Checkbox>

                                                        {restoreMode === "REPLACE_SCOPE" && (
                                                            <div style={{ maxWidth: 360 }}>
                                                                <Text type="danger" strong style={{ display: "block", marginBottom: 4 }}>
                                                                    Nhập chữ RESTORE để xác nhận ghi đè REPLACE_SCOPE:
                                                                </Text>
                                                                <Input
                                                                    placeholder="RESTORE"
                                                                    value={replaceConfirmText}
                                                                    onChange={(e) => setReplaceConfirmText(e.target.value)}
                                                                />
                                                            </div>
                                                        )}

                                                        <Button
                                                            type="primary"
                                                            danger={restoreMode === "REPLACE_SCOPE"}
                                                            size="large"
                                                            icon={<CheckCircleOutlined />}
                                                            loading={restoring}
                                                            disabled={
                                                                !previewData.can_apply ||
                                                                !confirmApplyChecked ||
                                                                (restoreMode === "REPLACE_SCOPE" && replaceConfirmText.trim() !== "RESTORE")
                                                            }
                                                            onClick={() => void handleExecuteRestore()}
                                                        >
                                                            Thực thi Khôi phục Cấu hình
                                                        </Button>
                                                    </Space>
                                                </Space>
                                            </Card>
                                        )}

                                        {restoreResult && restoreResult.success && (
                                            <Card size="small">
                                                <Result
                                                    status="success"
                                                    title="Khôi phục cấu hình hoàn tất!"
                                                    subTitle={`Chế độ ${restoreResult.mode} — Đã áp dụng ${restoreResult.effective_scopes.length} phạm vi và tái mã hóa ${restoreResult.secrets_restored_count} bí mật theo Fernet key của môi trường này.`}
                                                    extra={[
                                                        restoreResult.pre_restore_snapshot ? (
                                                            <Button
                                                                key="snap"
                                                                icon={<HistoryOutlined />}
                                                                onClick={() => setActiveTab("snapshots")}
                                                            >
                                                                Xem Bản chụp Hoàn tác ({restoreResult.pre_restore_snapshot.snapshot_id})
                                                            </Button>
                                                        ) : null,
                                                    ]}
                                                />
                                            </Card>
                                        )}
                                    </Space>
                                ),
                            },
                            {
                                key: "snapshots",
                                label: (
                                    <Space>
                                        <HistoryOutlined />
                                        <span>3. Bản chụp Hoàn tác &amp; Lịch sử ({snapshots.length})</span>
                                    </Space>
                                ),
                                children: (
                                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                                        <Card size="small" title="Tạo Bản chụp Thủ công tại Máy chủ Hiện tại">
                                            <Space.Compact style={{ width: "100%", maxWidth: 640 }}>
                                                <Input
                                                    placeholder="Ghi chú bản chụp (VD: Trước khi nâng cấp cấu hình AI Prod)..."
                                                    value={manualSnapNote}
                                                    onChange={(e) => setManualSnapNote(e.target.value)}
                                                />
                                                <Button
                                                    type="primary"
                                                    loading={creatingSnap}
                                                    onClick={() => void handleCreateManualSnapshot()}
                                                >
                                                    Tạo Bản chụp Ngay
                                                </Button>
                                            </Space.Compact>
                                        </Card>

                                        <Card size="small" title="Danh sách Bản chụp Tự động &amp; Thủ công">
                                            <Table<SnapshotRecord>
                                                rowKey="snapshot_id"
                                                loading={snapshotsLoading}
                                                dataSource={snapshots}
                                                pagination={{ pageSize: 10 }}
                                                columns={[
                                                    {
                                                        title: "Mã Bản chụp",
                                                        dataIndex: "snapshot_id",
                                                        render: (id: string, rec) => (
                                                            <Space direction="vertical" size={0}>
                                                                <Text code>{id}</Text>
                                                                <Tag color={rec.trigger.startsWith("PRE_") ? "orange" : "blue"} style={{ width: "fit-content", marginTop: 4 }}>
                                                                    {rec.trigger}
                                                                </Tag>
                                                            </Space>
                                                        ),
                                                    },
                                                    {
                                                        title: "Thời điểm",
                                                        dataIndex: "created_at",
                                                        width: 170,
                                                        render: (v: string) => dayjs(v).format("DD/MM/YYYY HH:mm:ss"),
                                                    },
                                                    {
                                                        title: "Ghi chú",
                                                        dataIndex: "note",
                                                        render: (v: string) => v || "-",
                                                    },
                                                    {
                                                        title: "Dung lượng",
                                                        dataIndex: "size_bytes",
                                                        width: 110,
                                                        render: (b: number) => formatBytes(b),
                                                    },
                                                    {
                                                        title: "Thao tác",
                                                        key: "actions",
                                                        width: 260,
                                                        render: (_, rec) => (
                                                            <Space size="small">
                                                                <Popconfirm
                                                                    title="Hoàn tác toàn bộ cấu hình về bản chụp này?"
                                                                    description="Hệ thống sẽ tự tạo thêm 1 bản chụp hiện tại trước khi hoàn tác."
                                                                    icon={<ExclamationCircleOutlined style={{ color: "red" }} />}
                                                                    okText="Hoàn tác ngay"
                                                                    cancelText="Hủy"
                                                                    onConfirm={() => void handleRollback(rec.snapshot_id)}
                                                                >
                                                                    <Button
                                                                        size="small"
                                                                        type="primary"
                                                                        ghost
                                                                        icon={<RollbackOutlined />}
                                                                        loading={rollingBackId === rec.snapshot_id}
                                                                        disabled={rec.file_exists === false}
                                                                    >
                                                                        Hoàn tác
                                                                    </Button>
                                                                </Popconfirm>
                                                                <Button
                                                                    size="small"
                                                                    icon={<DownloadOutlined />}
                                                                    disabled={rec.file_exists === false}
                                                                    onClick={() => void systemBackupApi.downloadSnapshot(rec.snapshot_id)}
                                                                >
                                                                    Tải
                                                                </Button>
                                                                <Popconfirm
                                                                    title="Xóa bản chụp này?"
                                                                    onConfirm={() => void handleDeleteSnapshot(rec.snapshot_id)}
                                                                >
                                                                    <Button size="small" danger icon={<DeleteOutlined />} />
                                                                </Popconfirm>
                                                            </Space>
                                                        ),
                                                    },
                                                ]}
                                            />
                                        </Card>
                                    </Space>
                                ),
                            },
                        ]}
                    />
                )}
            </Space>
        </div>
    );
}
