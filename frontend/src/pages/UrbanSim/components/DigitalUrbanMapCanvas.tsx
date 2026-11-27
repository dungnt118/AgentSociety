import {
    AimOutlined,
    ApartmentOutlined,
    BgColorsOutlined,
    CheckOutlined,
    CloseOutlined,
    DeleteOutlined,
    DownloadOutlined,
    DragOutlined,
    EditOutlined,
    EnvironmentOutlined,
    FullscreenExitOutlined,
    PlusOutlined,
    PushpinOutlined,
    RobotOutlined,
    SaveOutlined,
    UndoOutlined,
    UserAddOutlined,
    ZoomInOutlined,
    ZoomOutOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Badge,
    Button,
    Card,
    Checkbox,
    Col,
    Drawer,
    Form,
    Grid,
    Input,
    InputNumber,
    Modal,
    Popconfirm,
    Popover,
    Radio,
    Row,
    Segmented,
    Select,
    Space,
    Switch,
    Tag,
    Tooltip,
    Typography,
    message,
} from "antd";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarkdownRichTextEditor } from "../../../components/MarkdownRichTextEditor";
import { MarkdownWithMermaid } from "../../../components/MarkdownWithMermaid";
import {
    AgentStatusRow,
    CheckpointCategory,
    DigitalMapGenerateResponse,
    DigitalMapMeta,
    GeneratedCheckpointDraft,
    GeneratedMapZoneDraft,
    getRunMapImageUrl,
    getZoneMapImageUrl,
    PolygonPoint,
    RecentMovementEvent,
    urbanSimApi,
    UrbanSimCheckpoint,
    UrbanSimPersona,
    UrbanSimZone,
    ZoneTopologyCard,
    ZoneType,
} from "../../../services/urbanSimApi";

const { Text } = Typography;
const { TextArea } = Input;

const QUICK_EMOJIS = [
    "🛡️", "🚗", "🛎️", "🔧", "🏊", "🏋️", "🎠", "🍖", "🧹", "📹",
    "📦", "🏢", "🌳", "💡", "🔥", "🚪", "☕", "🛒", "🚿", "📍",
];

const CHECKPOINT_CATEGORY_OPTIONS: Array<{ value: CheckpointCategory; label: string }> = [
    { value: "security", label: "An ninh / Tuần tra" },
    { value: "facility", label: "Kỹ thuật / Hạ tầng M&E" },
    { value: "amenity", label: "Tiện ích Cư dân" },
    { value: "service", label: "Lễ tân / Dịch vụ / Vệ sinh" },
    { value: "general", label: "Điểm chung khác" },
];

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

const ZONE_COLORS = [
    "#0ea5e9", "#6366f1", "#64748b", "#f59e0b", "#3b82f6",
    "#2563eb", "#8b5cf6", "#10b981", "#14b8a6", "#ec4899",
];

type EditTool = "select" | "draw_polygon" | "point_prompt" | "place_checkpoint";

interface DigitalUrbanMapCanvasProps {
    mode: "edit" | "live";
    projectId: string;
    runId?: string;
    zones: Array<UrbanSimZone | ZoneTopologyCard>;
    checkpoints: UrbanSimCheckpoint[];
    personas?: UrbanSimPersona[];
    digitalMap?: DigitalMapMeta;
    hasZoneMapImage: boolean;
    hasDigitalMap: boolean;
    imgCacheKey?: string;
    agentStatuses?: AgentStatusRow[];
    recentMovements?: RecentMovementEvent[];
    onOpenAgentTimeline?: (agentId: number) => void;
    onRefreshMap?: () => void;
    onEditZoneDetails?: (zone: ZoneTopologyCard) => void;
    onAssignZonePersonas?: (zone: ZoneTopologyCard) => void;
    onDeleteZone?: (zone: ZoneTopologyCard) => void;
}

interface PositionedAgent {
    agent: AgentStatusRow;
    renderX: number;
    renderY: number;
    baseX: number;
    baseY: number;
}

type ResizeCorner = "nw" | "ne" | "se" | "sw";

type DragTarget =
    | { kind: "vertex"; zoneId: string; vertexIdx: number }
    | { kind: "polygon"; zoneId: string; startX: number; startY: number; origPoints: PolygonPoint[] }
    | {
          kind: "resize";
          zoneId: string;
          corner: ResizeCorner;
          anchorX: number;
          anchorY: number;
          origBox: { minX: number; minY: number; maxX: number; maxY: number };
          origPoints: PolygonPoint[];
      }
    | { kind: "checkpoint"; cpId: string }
    | { kind: "pan"; startClientX: number; startClientY: number; origPanX: number; origPanY: number };

interface LayoutSnapshot {
    polygons: Record<string, PolygonPoint[]>;
    checkpoints: Record<string, [number, number]>;
}

function clampPct(v: number, min = 0.5, max = 99.5): number {
    return Math.round(Math.max(min, Math.min(max, v)) * 100) / 100;
}

function formatShortAgentName(fullName: string, agentId: number): string {
    const cleaned = (fullName || "").replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
    if (!cleaned) return `#${agentId}`;
    const words = cleaned.split(" ").filter(Boolean);
    const honorifics = new Set(["ông", "bà", "anh", "chị", "cô", "chú", "ông/bà"]);
    if (words.length >= 3 && honorifics.has(words[0].toLowerCase())) {
        return `${words[0]} ${words[words.length - 1]}`;
    }
    if (cleaned.length <= 15) return cleaned;
    let out = "";
    for (const w of words) {
        const next = out ? `${out} ${w}` : w;
        if (next.length > 14 && out) break;
        out = next;
    }
    return out.length > 15 ? `${out.slice(0, 14)}…` : out;
}

function resolveAgentIconFE(agent: AgentStatusRow): string {
    if (agent.avatar_icon && agent.avatar_icon.trim()) return agent.avatar_icon.trim();
    const rc = (agent.role_code || "").toUpperCase();
    const low = (agent.full_name || "").toLowerCase();
    if (agent.group_type === "RESIDENT") {
        if (low.includes("bà ") || low.includes("chị ") || low.includes("cô ")) return "👩";
        if (low.includes("ông ") || low.includes("anh ") || low.includes("chú ")) return "👨";
        return "🧑";
    }
    if (rc === "BQL_DIRECTOR") return "👔";
    if (rc === "BQL_ASSISTANT") return "📋";
    if (rc === "BQL_RECEPTIONIST") return "🛎️";
    if (rc === "SEC_LEAD") return "🛡️";
    if (rc.includes("SEC")) return "👮";
    if (rc === "ENG_LEAD") return "👷";
    if (rc.includes("ENG") || rc.includes("TECH")) return "🔧";
    if (rc.includes("ACCOUNT")) return "🧮";
    return "🧑‍💼";
}

function computePolygonCenter(pts: PolygonPoint[]): [number, number] {
    if (!pts.length) return [50, 50];
    const sx = pts.reduce((acc, p) => acc + p[0], 0) / pts.length;
    const sy = pts.reduce((acc, p) => acc + p[1], 0) / pts.length;
    return [clampPct(sx), clampPct(sy)];
}

function computePolygonBBox(pts: PolygonPoint[]): { minX: number; minY: number; maxX: number; maxY: number } {
    let minX = 100;
    let minY = 100;
    let maxX = 0;
    let maxY = 0;
    for (const [x, y] of pts) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
    }
    return { minX, minY, maxX, maxY };
}

function pointInPolygonFE(x: number, y: number, poly: PolygonPoint[]): boolean {
    if (!poly || poly.length < 3) return false;
    let inside = false;
    let j = poly.length - 1;
    for (let i = 0; i < poly.length; i += 1) {
        const [xi, yi] = poly[i];
        const [xj, yj] = poly[j];
        const intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
        if (intersect) inside = !inside;
        j = i;
    }
    return inside;
}

function clonePolygonsMap(src: Record<string, PolygonPoint[]>): Record<string, PolygonPoint[]> {
    const out: Record<string, PolygonPoint[]> = {};
    for (const [k, pts] of Object.entries(src)) {
        out[k] = pts.map(([x, y]) => [x, y]);
    }
    return out;
}

function cloneCpCoordsMap(src: Record<string, [number, number]>): Record<string, [number, number]> {
    const out: Record<string, [number, number]> = {};
    for (const [k, [x, y]] of Object.entries(src)) {
        out[k] = [x, y];
    }
    return out;
}

function polygonsEqual(a?: PolygonPoint[], b?: PolygonPoint[] | null): boolean {
    if (!a || !b || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
        if (Math.abs(a[i][0] - Number(b[i][0])) > 0.05 || Math.abs(a[i][1] - Number(b[i][1])) > 0.05) {
            return false;
        }
    }
    return true;
}

function toZoneTopologyCard(z: UrbanSimZone | ZoneTopologyCard): ZoneTopologyCard {
    if ("agents_here" in z) return z;
    return {
        id: z.id,
        zone_key: z.zone_key,
        name: z.name,
        zone_type: z.zone_type,
        description: z.description,
        ambient_signals: z.ambient_signals,
        polygon_points: z.polygon_points ?? null,
        center_x_pct: z.center_x_pct ?? null,
        center_y_pct: z.center_y_pct ?? null,
        fill_color: z.fill_color ?? null,
        persona_count: z.persona_count,
        agents_here: [],
        open_incidents: [],
    };
}

interface ResizeHandleSpec {
    corner: ResizeCorner;
    x: number;
    y: number;
    anchorX: number;
    anchorY: number;
    cursor: string;
}

const CornerResizeHandlesOverlay: React.FC<{
    zoneId: string;
    bbox: { minX: number; minY: number; maxX: number; maxY: number };
    pts: PolygonPoint[];
    onStartResize: (target: DragTarget) => void;
}> = ({ zoneId, bbox, pts, onStartResize }) => {
    const corners: ResizeHandleSpec[] = [
        { corner: "nw", x: bbox.minX, y: bbox.minY, anchorX: bbox.maxX, anchorY: bbox.maxY, cursor: "nwse-resize" },
        { corner: "ne", x: bbox.maxX, y: bbox.minY, anchorX: bbox.minX, anchorY: bbox.maxY, cursor: "nesw-resize" },
        { corner: "se", x: bbox.maxX, y: bbox.maxY, anchorX: bbox.minX, anchorY: bbox.minY, cursor: "nwse-resize" },
        { corner: "sw", x: bbox.minX, y: bbox.maxY, anchorX: bbox.maxX, anchorY: bbox.minY, cursor: "nesw-resize" },
    ];
    return (
        <>
            {corners.map((c) => (
                <div
                    key={`resize-${zoneId}-${c.corner}`}
                    data-testid={`resize-handle-${c.corner}`}
                    onPointerDown={(e) => {
                        if (e.button !== 0) return;
                        e.preventDefault();
                        e.stopPropagation();
                        onStartResize({
                            kind: "resize",
                            zoneId,
                            corner: c.corner,
                            anchorX: c.anchorX,
                            anchorY: c.anchorY,
                            origBox: bbox,
                            origPoints: pts.map((p) => [p[0], p[1]] as PolygonPoint),
                        });
                    }}
                    title="Kéo góc để phóng to / thu nhỏ Khu vực"
                    style={{
                        position: "absolute",
                        left: `${c.x}%`,
                        top: `${c.y}%`,
                        width: 26,
                        height: 26,
                        transform: "translate(-50%, -50%)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        cursor: c.cursor,
                        touchAction: "none",
                        pointerEvents: "auto",
                        zIndex: 21,
                    }}
                >
                    <div
                        style={{
                            width: 10,
                            height: 10,
                            borderRadius: 2,
                            background: "#1d4ed8",
                            border: "2px solid #ffffff",
                            boxShadow: "0 1px 4px rgba(0,0,0,0.35)",
                        }}
                    />
                </div>
            ))}
        </>
    );
};

function computeRadialAgentPositions(
    agents: AgentStatusRow[],
    zoneCenterMap: Map<string, [number, number]>,
    isMobile = false
): PositionedAgent[] {
    const bases = agents.map((ag) => {
        const zc = zoneCenterMap.get(ag.current_zone) || [50, 50];
        const bx = typeof ag.current_x_pct === "number" ? ag.current_x_pct : zc[0];
        const by = typeof ag.current_y_pct === "number" ? ag.current_y_pct : zc[1];
        return { agent: ag, baseX: bx, baseY: by };
    });

    // Deterministic cluster grouping for overlapping agents (dist < 2.4%)
    const used = new Array<boolean>(bases.length).fill(false);
    const result: PositionedAgent[] = new Array(bases.length);

    for (let i = 0; i < bases.length; i += 1) {
        if (used[i]) continue;
        const clusterIndices = [i];
        used[i] = true;
        for (let j = i + 1; j < bases.length; j += 1) {
            if (used[j]) continue;
            const dx = bases[j].baseX - bases[i].baseX;
            const dy = bases[j].baseY - bases[i].baseY;
            if (Math.hypot(dx, dy) < 2.4) {
                clusterIndices.push(j);
                used[j] = true;
            }
        }
        clusterIndices.sort((a, b) => bases[a].agent.agent_id - bases[b].agent.agent_id);
        const atCheckpoint = clusterIndices.some((idx) => Boolean(bases[idx].agent.current_checkpoint_key));
        if (clusterIndices.length === 1) {
            const idx = clusterIndices[0];
            const offX = atCheckpoint ? (isMobile ? 7.5 : 4.2) : 0;
            const offY = atCheckpoint ? (isMobile ? 16.5 : 8.5) : 0;
            result[idx] = {
                agent: bases[idx].agent,
                baseX: bases[idx].baseX,
                baseY: bases[idx].baseY,
                renderX: clampPct(bases[idx].baseX + offX, 4, 96),
                renderY: clampPct(bases[idx].baseY + offY, 5, 95),
            };
        } else {
            const arcAngles = [
                Math.PI * 0.32,
                Math.PI * 0.68,
                Math.PI * 0.16,
                Math.PI * 0.84,
                Math.PI * 0.50,
            ];
            clusterIndices.forEach((idx, posInCluster) => {
                if (!atCheckpoint && posInCluster === 0) {
                    result[idx] = {
                        agent: bases[idx].agent,
                        baseX: bases[idx].baseX,
                        baseY: bases[idx].baseY,
                        renderX: clampPct(bases[idx].baseX, 2, 98),
                        renderY: clampPct(bases[idx].baseY, 2, 98),
                    };
                    return;
                }
                if (atCheckpoint) {
                    const tier = Math.floor(posInCluster / arcAngles.length);
                    const angle = arcAngles[posInCluster % arcAngles.length];
                    const baseRadius = isMobile ? 16.5 : 8.5;
                    const radius = baseRadius + tier * (isMobile ? 7.5 : 4.0);
                    const rx = bases[idx].baseX + Math.cos(angle) * radius;
                    const ry = bases[idx].baseY + Math.sin(angle) * radius;
                    result[idx] = {
                        agent: bases[idx].agent,
                        baseX: bases[idx].baseX,
                        baseY: bases[idx].baseY,
                        renderX: clampPct(rx, 4, 96),
                        renderY: clampPct(ry, 5, 95),
                    };
                    return;
                }
                const ring = Math.floor((posInCluster - 1) / 6) + 1;
                const radius = (isMobile ? 4.5 : 3.2) * ring;
                const angle = posInCluster * 2.3999632; // Golden angle deterministic
                const rx = bases[idx].baseX + Math.cos(angle) * radius;
                const ry = bases[idx].baseY + Math.sin(angle) * radius;
                result[idx] = {
                    agent: bases[idx].agent,
                    baseX: bases[idx].baseX,
                    baseY: bases[idx].baseY,
                    renderX: clampPct(rx, 3, 97),
                    renderY: clampPct(ry, 4, 96),
                };
            });
        }
    }
    return result;
}

const MOVEMENT_BADGE_META: Record<string, { label: string; color: string }> = {
    patrolling: { label: "Tuần tra", color: "#fa8c16" },
    working: { label: "Kiểm tra", color: "#1677ff" },
    leisure: { label: "Tiện ích", color: "#13c2c2" },
    moving: { label: "Di chuyển", color: "#722ed1" },
    idle: { label: "Tại chỗ", color: "#8c8c8c" },
};

export const DigitalUrbanMapCanvas: React.FC<DigitalUrbanMapCanvasProps> = ({
    mode,
    projectId,
    runId,
    zones,
    checkpoints,
    digitalMap,
    hasZoneMapImage,
    hasDigitalMap,
    imgCacheKey,
    personas = [],
    agentStatuses = [],
    recentMovements = [],
    onOpenAgentTimeline,
    onRefreshMap,
    onEditZoneDetails,
    onAssignZonePersonas,
    onDeleteZone,
}) => {
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;
    const innerBoxRef = useRef<HTMLDivElement | null>(null);
    const dragRef = useRef<DragTarget | null>(null);
    const didMoveRef = useRef<boolean>(false);
    const pendingSnapshotRef = useRef<LayoutSnapshot | null>(null);

    // Draft overrides during pointer drag & undo/auto-save tracking
    const [draftPolygons, setDraftPolygons] = useState<Record<string, PolygonPoint[]>>({});
    const [draftCpCoords, setDraftCpCoords] = useState<Record<string, [number, number]>>({});
    const [isDragging, setIsDragging] = useState(false);
    const [savingLayout, setSavingLayout] = useState(false);
    const [autoSaveStatus, setAutoSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [undoStack, setUndoStack] = useState<LayoutSnapshot[]>([]);
    const [savedPolys, setSavedPolys] = useState<Record<string, PolygonPoint[]>>({});
    const [savedCps, setSavedCps] = useState<Record<string, [number, number]>>({});

    // Canvas viewport & controls
    const [zoom, setZoom] = useState<number>(1);
    const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
    const [editTool, setEditTool] = useState<EditTool>("select");
    const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
    const [selectedCpId, setSelectedCpId] = useState<string | null>(null);
    const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);

    // Polygon drawing state
    const [drawingPts, setDrawingPts] = useState<PolygonPoint[]>([]);
    const [drawZoneModalOpen, setDrawZoneModalOpen] = useState(false);
    const [creatingDrawnZone, setCreatingDrawnZone] = useState(false);
    const [drawZoneForm] = Form.useForm();

    // Point-Center + Prompt state
    const [pointModalOpen, setPointModalOpen] = useState(false);
    const [clickedPoint, setClickedPoint] = useState<PolygonPoint>([50, 50]);
    const [pointPromptText, setPointPromptText] = useState("");
    const [pointGenLoading, setPointGenLoading] = useState(false);
    const [pointDraft, setPointDraft] = useState<GeneratedMapZoneDraft | null>(null);
    const [pointFallbackInfo, setPointFallbackInfo] = useState<string | null>(null);

    // AI Full Digital Map modal & preview
    const [aiMapModalOpen, setAiMapModalOpen] = useState(false);
    const [aiMapPrompt, setAiMapPrompt] = useState("");
    const [aiMapUseImage, setAiMapUseImage] = useState(true);
    const [aiMapApplyMode, setAiMapApplyMode] = useState<"MERGE" | "REPLACE">("MERGE");
    const [aiMapGenerating, setAiMapGenerating] = useState(false);
    const [aiMapApplying, setAiMapApplying] = useState(false);
    const [aiMapDraft, setAiMapDraft] = useState<DigitalMapGenerateResponse | null>(null);

    // Checkpoint Manual Create/Edit Modal
    const [cpModalOpen, setCpModalOpen] = useState(false);
    const [editingCp, setEditingCp] = useState<UrbanSimCheckpoint | null>(null);
    const [savingCp, setSavingCp] = useState(false);
    const [cpForm] = Form.useForm();

    // AI Checkpoints Generate Modal & Preview
    const [aiCpModalOpen, setAiCpModalOpen] = useState(false);
    const [aiCpPrompt, setAiCpPrompt] = useState("");
    const [aiCpGenerating, setAiCpGenerating] = useState(false);
    const [aiCpApplying, setAiCpApplying] = useState(false);
    const [aiCpDrafts, setAiCpDrafts] = useState<Array<GeneratedCheckpointDraft & { selected: boolean }>>([]);
    const [aiCpFallbackInfo, setAiCpFallbackInfo] = useState<string | null>(null);

    // Live Mode filters & inspection
    const [liveGroupFilter, setLiveGroupFilter] = useState<"ALL" | "BQL" | "RESIDENT">("ALL");
    const [liveSelectedAgentId, setLiveSelectedAgentId] = useState<number | "ALL">("ALL");
    const [showTrails, setShowTrails] = useState(true);
    const [showCheckpoints, setShowCheckpoints] = useState(true);
    const [showZoneLabels, setShowZoneLabels] = useState(true);
    const [showAgentNames, setShowAgentNames] = useState(true);
    const [liveMobileCp, setLiveMobileCp] = useState<UrbanSimCheckpoint | null>(null);
    const [liveMobileZone, setLiveMobileZone] = useState<ZoneTopologyCard | null>(null);
    const [liveDesktopCpId, setLiveDesktopCpId] = useState<string | null>(null);

    const localPolygons = useMemo(() => {
        const out: Record<string, PolygonPoint[]> = {};
        for (const z of zones) {
            if (!z.id) continue;
            if (draftPolygons[z.id]) {
                out[z.id] = draftPolygons[z.id];
            } else if (Array.isArray(z.polygon_points) && z.polygon_points.length >= 3) {
                out[z.id] = z.polygon_points.map((pt) => [Number(pt[0]), Number(pt[1])]);
            }
        }
        return out;
    }, [zones, draftPolygons]);

    const localCpCoords = useMemo(() => {
        const out: Record<string, [number, number]> = {};
        for (const cp of checkpoints) {
            out[cp.id] = draftCpCoords[cp.id] || [Number(cp.x_pct), Number(cp.y_pct)];
        }
        return out;
    }, [checkpoints, draftCpCoords]);

    const dirtyZoneIds = useMemo(
        () =>
            new Set(
                Object.keys(draftPolygons).filter((zid) => {
                    const z = zones.find((item) => item.id === zid);
                    if (!z) return false;
                    const draft = draftPolygons[zid];
                    if (polygonsEqual(draft, z.polygon_points)) return false;
                    if (savedPolys[zid] && polygonsEqual(draft, savedPolys[zid])) {
                        return false;
                    }
                    return true;
                })
            ),
        [draftPolygons, zones, savedPolys]
    );
    const dirtyCpIds = useMemo(
        () =>
            new Set(
                Object.keys(draftCpCoords).filter((cid) => {
                    const cp = checkpoints.find((item) => item.id === cid);
                    if (!cp) return false;
                    const [dx, dy] = draftCpCoords[cid];
                    if (Math.abs(dx - cp.x_pct) <= 0.05 && Math.abs(dy - cp.y_pct) <= 0.05) return false;
                    const saved = savedCps[cid];
                    if (saved && Math.abs(dx - saved[0]) <= 0.05 && Math.abs(dy - saved[1]) <= 0.05) {
                        return false;
                    }
                    return true;
                })
            ),
        [draftCpCoords, checkpoints, savedCps]
    );

    const localPolygonsRef = useRef<Record<string, PolygonPoint[]>>(localPolygons);
    const localCpCoordsRef = useRef<Record<string, [number, number]>>(localCpCoords);
    useEffect(() => {
        localPolygonsRef.current = localPolygons;
        localCpCoordsRef.current = localCpCoords;
    }, [localPolygons, localCpCoords]);

    const aspectRatio = useMemo(() => {
        const raw = Number(digitalMap?.map_aspect_ratio || 1.6);
        return Number.isFinite(raw) && raw > 0.3 && raw < 4.0 ? raw : 1.6;
    }, [digitalMap?.map_aspect_ratio]);

    const resolvedImageUrl = useMemo(() => {
        if (mode === "live" && runId) {
            if (!digitalMap?.has_map_image && !hasZoneMapImage) return null;
            if (digitalMap?.image_url) return digitalMap.image_url;
            return getRunMapImageUrl(
                projectId,
                runId,
                String(digitalMap?.map_image_version ?? imgCacheKey ?? "1")
            );
        }
        if (!hasZoneMapImage) return null;
        return getZoneMapImageUrl(
            projectId,
            String(digitalMap?.map_image_version ?? imgCacheKey ?? "1")
        );
    }, [mode, runId, projectId, digitalMap, hasZoneMapImage, imgCacheKey]);

    const imgError = Boolean(resolvedImageUrl && failedImageUrl === resolvedImageUrl);

    const clientPointToPct = useCallback((clientX: number, clientY: number): PolygonPoint => {
        const el = innerBoxRef.current;
        if (!el) return [50, 50];
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return [50, 50];
        const xp = ((clientX - rect.left) / rect.width) * 100;
        const yp = ((clientY - rect.top) / rect.height) * 100;
        return [clampPct(xp), clampPct(yp)];
    }, []);

    const persistLayoutChanges = useCallback(
        async (zoneIds: string[], cpIds: string[], toastSuccess?: string) => {
            if (zoneIds.length === 0 && cpIds.length === 0) return;
            setSavingLayout(true);
            setAutoSaveStatus("saving");
            try {
                if (zoneIds.length > 0) {
                    const nextSavedPolys: Record<string, PolygonPoint[]> = {};
                    const payload = zoneIds.map((zid) => {
                        const pts = localPolygonsRef.current[zid] || [];
                        const [cx, cy] = computePolygonCenter(pts);
                        nextSavedPolys[zid] = pts.map(([x, y]) => [x, y]);
                        return {
                            id: zid,
                            polygon_points: pts.length >= 3 ? pts : null,
                            center_x_pct: cx,
                            center_y_pct: cy,
                        };
                    });
                    await urbanSimApi.saveZonesLayout(projectId, payload);
                    setSavedPolys((prev) => ({ ...prev, ...nextSavedPolys }));
                }
                if (cpIds.length > 0) {
                    const nextSavedCps: Record<string, [number, number]> = {};
                    const cpPayload = cpIds.map((cpId) => {
                        const coords = localCpCoordsRef.current[cpId] || [50, 50];
                        nextSavedCps[cpId] = [coords[0], coords[1]];
                        return { id: cpId, x_pct: coords[0], y_pct: coords[1] };
                    });
                    await urbanSimApi.saveCheckpointsLayout(projectId, cpPayload);
                    setSavedCps((prev) => ({ ...prev, ...nextSavedCps }));
                }
                setAutoSaveStatus("saved");
                if (toastSuccess) {
                    message.success(toastSuccess);
                }
                onRefreshMap?.();
            } catch (err) {
                setAutoSaveStatus("error");
                message.error(err instanceof Error ? err.message : "Tự động lưu bố cục thất bại");
            } finally {
                setSavingLayout(false);
            }
        },
        [projectId, onRefreshMap]
    );

    const startDrag = useCallback(
        (target: DragTarget) => {
            if (target.kind !== "pan") {
                pendingSnapshotRef.current = {
                    polygons: clonePolygonsMap(localPolygons),
                    checkpoints: cloneCpCoordsMap(localCpCoords),
                };
            } else {
                pendingSnapshotRef.current = null;
            }
            didMoveRef.current = false;
            dragRef.current = target;
            setIsDragging(true);
        },
        [localPolygons, localCpCoords]
    );

    // Global window pointer listeners during active drag (works reliably across SVG/HTML & Playwright)
    useEffect(() => {
        if (!isDragging) return;

        const handleWinMove = (e: PointerEvent) => {
            const drag = dragRef.current;
            if (!drag) return;
            if (drag.kind === "pan") {
                const dx = e.clientX - drag.startClientX;
                const dy = e.clientY - drag.startClientY;
                if (Math.hypot(dx, dy) > 3) didMoveRef.current = true;
                setPan({ x: drag.origPanX + dx, y: drag.origPanY + dy });
                return;
            }
            const [xp, yp] = clientPointToPct(e.clientX, e.clientY);
            didMoveRef.current = true;

            if (drag.kind === "vertex") {
                const cur = localPolygonsRef.current[drag.zoneId];
                if (!cur) return;
                const updated = cur.map((pt, idx) =>
                    idx === drag.vertexIdx ? ([xp, yp] as PolygonPoint) : pt
                );
                localPolygonsRef.current = { ...localPolygonsRef.current, [drag.zoneId]: updated };
                setDraftPolygons((prev) => ({ ...prev, [drag.zoneId]: updated }));
            } else if (drag.kind === "polygon") {
                const { minX, minY, maxX, maxY } = computePolygonBBox(drag.origPoints);
                const rawDx = xp - drag.startX;
                const rawDy = yp - drag.startY;
                const dx = Math.max(0.5 - minX, Math.min(99.5 - maxX, rawDx));
                const dy = Math.max(0.5 - minY, Math.min(99.5 - maxY, rawDy));
                const shifted = drag.origPoints.map(
                    ([px, py]) => [clampPct(px + dx), clampPct(py + dy)] as PolygonPoint
                );
                localPolygonsRef.current = { ...localPolygonsRef.current, [drag.zoneId]: shifted };
                setDraftPolygons((prev) => ({ ...prev, [drag.zoneId]: shifted }));
            } else if (drag.kind === "resize") {
                const { corner, anchorX, anchorY, origBox, origPoints, zoneId } = drag;
                const minSpan = 4.0;
                const newX =
                    corner === "nw" || corner === "sw"
                        ? Math.min(anchorX - minSpan, Math.max(0.5, xp))
                        : Math.max(anchorX + minSpan, Math.min(99.5, xp));
                const newY =
                    corner === "nw" || corner === "ne"
                        ? Math.min(anchorY - minSpan, Math.max(0.5, yp))
                        : Math.max(anchorY + minSpan, Math.min(99.5, yp));
                const origW = origBox.maxX - origBox.minX;
                const origH = origBox.maxY - origBox.minY;
                const newW = Math.abs(anchorX - newX);
                const newH = Math.abs(anchorY - newY);
                const scaleX = origW > 0.5 ? newW / origW : 1;
                const scaleY = origH > 0.5 ? newH / origH : 1;
                const scaled = origPoints.map(([ox, oy]) => {
                    const nx = origW > 0.5 ? anchorX + (ox - anchorX) * scaleX : ox;
                    const ny = origH > 0.5 ? anchorY + (oy - anchorY) * scaleY : oy;
                    return [clampPct(nx), clampPct(ny)] as PolygonPoint;
                });
                localPolygonsRef.current = { ...localPolygonsRef.current, [zoneId]: scaled };
                setDraftPolygons((prev) => ({ ...prev, [zoneId]: scaled }));
            } else if (drag.kind === "checkpoint") {
                const coords: [number, number] = [xp, yp];
                localCpCoordsRef.current = { ...localCpCoordsRef.current, [drag.cpId]: coords };
                setDraftCpCoords((prev) => ({ ...prev, [drag.cpId]: coords }));
            }
        };

        const finishDrag = () => {
            const drag = dragRef.current;
            dragRef.current = null;
            setIsDragging(false);
            if (!drag || drag.kind === "pan") return;
            const moved = didMoveRef.current;
            if (moved) {
                window.setTimeout(() => {
                    didMoveRef.current = false;
                }, 80);
                if (pendingSnapshotRef.current) {
                    const snap = pendingSnapshotRef.current;
                    setUndoStack((prev) => [...prev.slice(-14), snap]);
                }
                if (drag.kind === "checkpoint") {
                    void persistLayoutChanges([], [drag.cpId]);
                } else {
                    void persistLayoutChanges([drag.zoneId], []);
                }
            }
            pendingSnapshotRef.current = null;
        };

        window.addEventListener("pointermove", handleWinMove);
        window.addEventListener("pointerup", finishDrag);
        window.addEventListener("pointercancel", finishDrag);
        return () => {
            window.removeEventListener("pointermove", handleWinMove);
            window.removeEventListener("pointerup", finishDrag);
            window.removeEventListener("pointercancel", finishDrag);
        };
    }, [isDragging, clientPointToPct, persistLayoutChanges]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        const prevSnap = undoStack[undoStack.length - 1];
        setUndoStack((s) => s.slice(0, -1));

        const changedZoneIds: string[] = [];
        const changedCpIds: string[] = [];
        const nextPolys: Record<string, PolygonPoint[]> = {};
        for (const z of zones) {
            if (!z.id) continue;
            const targetPoly = prevSnap.polygons[z.id];
            const curPoly = localPolygonsRef.current[z.id];
            if (targetPoly && !polygonsEqual(targetPoly, curPoly)) {
                nextPolys[z.id] = targetPoly;
                localPolygonsRef.current[z.id] = targetPoly;
                changedZoneIds.push(z.id);
            }
        }
        const nextCps: Record<string, [number, number]> = {};
        for (const cp of checkpoints) {
            const targetCoord = prevSnap.checkpoints[cp.id];
            const curCoord = localCpCoordsRef.current[cp.id];
            if (
                targetCoord &&
                (!curCoord ||
                    Math.abs(targetCoord[0] - curCoord[0]) > 0.05 ||
                    Math.abs(targetCoord[1] - curCoord[1]) > 0.05)
            ) {
                nextCps[cp.id] = targetCoord;
                localCpCoordsRef.current[cp.id] = targetCoord;
                changedCpIds.push(cp.id);
            }
        }
        if (Object.keys(nextPolys).length > 0) {
            setDraftPolygons((prev) => ({ ...prev, ...nextPolys }));
        }
        if (Object.keys(nextCps).length > 0) {
            setDraftCpCoords((prev) => ({ ...prev, ...nextCps }));
        }
        void persistLayoutChanges(changedZoneIds, changedCpIds, "Đã hoàn tác và lưu bố cục.");
    }, [undoStack, zones, checkpoints, persistLayoutChanges]);

    useEffect(() => {
        if (mode !== "edit") return;
        const onKeyDown = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
                const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
                if (tag === "input" || tag === "textarea" || (e.target as HTMLElement | null)?.isContentEditable) {
                    return;
                }
                if (undoStack.length > 0) {
                    e.preventDefault();
                    handleUndo();
                }
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [mode, undoStack.length, handleUndo]);

    const handleCanvasClick = (e: React.MouseEvent<HTMLDivElement>) => {
        if (didMoveRef.current) {
            didMoveRef.current = false;
            return;
        }
        if (mode !== "edit") return;
        const [xp, yp] = clientPointToPct(e.clientX, e.clientY);

        if (editTool === "draw_polygon") {
            setDrawingPts((prev) => [...prev, [xp, yp]]);
            return;
        }
        if (editTool === "point_prompt") {
            setClickedPoint([xp, yp]);
            setPointDraft(null);
            setPointFallbackInfo(null);
            setPointPromptText("");
            setPointModalOpen(true);
            return;
        }
        if (editTool === "place_checkpoint") {
            if (!hasDigitalMap) {
                message.warning("Cần có Bản đồ Số (Ảnh 2D hoặc ít nhất 1 Polygon Khu vực) trước khi đặt Chốt.");
                return;
            }
            openCpModal(null, xp, yp);
            return;
        }
    };

    const openCpModal = (cp: UrbanSimCheckpoint | null, defaultX = 50, defaultY = 50) => {
        setEditingCp(cp);
        if (cp) {
            const coords = localCpCoords[cp.id] || [cp.x_pct, cp.y_pct];
            cpForm.setFieldsValue({
                checkpoint_key: cp.checkpoint_key,
                name: cp.name,
                x_pct: coords[0],
                y_pct: coords[1],
                icon_emoji: cp.icon_emoji || "📍",
                category: cp.category || "general",
                sort_order: cp.sort_order ?? 1,
                description_md: cp.description_md || "",
            });
        } else {
            cpForm.setFieldsValue({
                checkpoint_key: "",
                name: "",
                x_pct: defaultX,
                y_pct: defaultY,
                icon_emoji: "🛡️",
                category: "security",
                sort_order: checkpoints.length + 1,
                description_md: "### Quy trình / Ghi chú tại chốt\n- Kiểm tra thực địa và ghi nhận trạng thái.",
            });
        }
        setCpModalOpen(true);
    };

    const handleSaveLayout = async () => {
        const zIds = Array.from(dirtyZoneIds);
        const cIds = Array.from(dirtyCpIds);
        if (zIds.length === 0 && cIds.length === 0) return;
        await persistLayoutChanges(zIds, cIds, "Đã lưu bố cục Bản đồ Số & Chốt vào Database.");
    };

    const handleFinishDrawnPolygon = () => {
        if (drawingPts.length < 3) {
            message.warning("Vui lòng chấm tối thiểu 3 đỉnh để tạo Polygon Khu vực.");
            return;
        }
        drawZoneForm.setFieldsValue({
            zone_key: "",
            name: "",
            zone_type: "TOWER",
            fill_color: ZONE_COLORS[zones.length % ZONE_COLORS.length],
            description: "",
            ambient_signals: "",
        });
        setDrawZoneModalOpen(true);
    };

    const handleSaveDrawnZone = async (values: {
        zone_key: string;
        name: string;
        zone_type: ZoneType;
        fill_color?: string;
        description?: string;
        ambient_signals?: string;
    }) => {
        setCreatingDrawnZone(true);
        try {
            const [cx, cy] = computePolygonCenter(drawingPts);
            await urbanSimApi.createZone(projectId, {
                zone_key: values.zone_key,
                name: values.name,
                zone_type: values.zone_type,
                description: values.description || "",
                ambient_signals: values.ambient_signals || "",
                sort_order: zones.length + 1,
                polygon_points: drawingPts,
                center_x_pct: cx,
                center_y_pct: cy,
                fill_color: values.fill_color || "#0ea5e9",
            });
            message.success(`Đã tạo Khu vực Polygon "${values.name}".`);
            setDrawZoneModalOpen(false);
            setDrawingPts([]);
            setEditTool("select");
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không tạo được Khu vực Polygon");
        } finally {
            setCreatingDrawnZone(false);
        }
    };

    const handleGenerateFromPoint = async () => {
        if (pointPromptText.trim().length < 5) {
            message.warning("Vui lòng nhập mô tả khu vực (tối thiểu 5 ký tự).");
            return;
        }
        setPointGenLoading(true);
        setPointFallbackInfo(null);
        try {
            const res = await urbanSimApi.generateZoneFromPoint(projectId, {
                center_x_pct: clickedPoint[0],
                center_y_pct: clickedPoint[1],
                prompt: pointPromptText.trim(),
            });
            setPointDraft(res.zone);
            if (!res.used_vision && res.fallback_reason) {
                setPointFallbackInfo(res.fallback_reason);
            }
        } catch (err) {
            message.error(err instanceof Error ? err.message : "AI sinh Polygon thất bại");
        } finally {
            setPointGenLoading(false);
        }
    };

    const handleConfirmPointDraft = async () => {
        if (!pointDraft) return;
        setPointGenLoading(true);
        try {
            await urbanSimApi.createZone(projectId, {
                zone_key: pointDraft.zone_key,
                name: pointDraft.name,
                zone_type: pointDraft.zone_type,
                description: pointDraft.description,
                ambient_signals: pointDraft.ambient_signals,
                fill_color: pointDraft.fill_color,
                polygon_points: pointDraft.polygon_points,
                center_x_pct: pointDraft.center_x_pct,
                center_y_pct: pointDraft.center_y_pct,
                sort_order: zones.length + 1,
            });
            message.success(`Đã lưu Khu vực "${pointDraft.name}" từ điểm tâm.`);
            setPointDraft(null);
            setPointModalOpen(false);
            setEditTool("select");
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu khu vực thất bại");
        } finally {
            setPointGenLoading(false);
        }
    };

    const handleGenerateAiMap = async () => {
        if (aiMapPrompt.trim().length < 5) {
            message.warning("Vui lòng nhập prompt mô tả khuôn viên (tối thiểu 5 ký tự).");
            return;
        }
        setAiMapGenerating(true);
        try {
            const res = await urbanSimApi.generateDigitalMap(projectId, {
                map_prompt: aiMapPrompt.trim(),
                use_image: aiMapUseImage && hasZoneMapImage,
                max_zones: 14,
            });
            setAiMapDraft(res);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "AI tạo Bản đồ Số thất bại");
        } finally {
            setAiMapGenerating(false);
        }
    };

    const handleApplyAiMap = async () => {
        if (!aiMapDraft) return;
        setAiMapApplying(true);
        try {
            await urbanSimApi.applyDigitalMap(projectId, {
                mode: aiMapApplyMode,
                map_prompt: aiMapDraft.map_prompt,
                aspect_ratio: aiMapDraft.aspect_ratio,
                zones: aiMapDraft.zones,
            });
            message.success(
                `Đã áp dụng ${aiMapDraft.zones.length} Khu vực Polygon (${aiMapApplyMode === "MERGE" ? "Gộp an toàn" : "Thay thế"}).`
            );
            setAiMapDraft(null);
            setAiMapModalOpen(false);
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Áp dụng Bản đồ Số thất bại");
        } finally {
            setAiMapApplying(false);
        }
    };

    const handleSaveCheckpoint = async (values: {
        checkpoint_key?: string;
        name: string;
        x_pct: number;
        y_pct: number;
        icon_emoji: string;
        category: CheckpointCategory;
        sort_order?: number;
        description_md?: string;
    }) => {
        setSavingCp(true);
        try {
            if (editingCp) {
                await urbanSimApi.updateCheckpoint(projectId, editingCp.id, {
                    checkpoint_key: values.checkpoint_key || undefined,
                    name: values.name,
                    x_pct: Number(values.x_pct),
                    y_pct: Number(values.y_pct),
                    icon_emoji: values.icon_emoji || "📍",
                    category: values.category,
                    sort_order: Number(values.sort_order ?? 1),
                    description_md: values.description_md || "",
                });
                message.success(`Đã cập nhật chốt "${values.name}".`);
            } else {
                await urbanSimApi.createCheckpoint(projectId, {
                    checkpoint_key: values.checkpoint_key || undefined,
                    name: values.name,
                    x_pct: Number(values.x_pct),
                    y_pct: Number(values.y_pct),
                    icon_emoji: values.icon_emoji || "📍",
                    category: values.category,
                    sort_order: Number(values.sort_order ?? checkpoints.length + 1),
                    description_md: values.description_md || "",
                });
                message.success(`Đã thêm chốt "${values.name}".`);
            }
            setCpModalOpen(false);
            setEditTool("select");
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu chốt thất bại");
        } finally {
            setSavingCp(false);
        }
    };

    const handleDeleteCheckpoint = async (cpId: string) => {
        try {
            await urbanSimApi.deleteCheckpoint(projectId, cpId);
            message.success("Đã xóa chốt.");
            setSelectedCpId(null);
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Xóa chốt thất bại");
        }
    };

    const handleGenerateAiCheckpoints = async () => {
        if (aiCpPrompt.trim().length < 5) {
            message.warning("Vui lòng nhập mô tả các chốt cần tạo (tối thiểu 5 ký tự).");
            return;
        }
        setAiCpGenerating(true);
        setAiCpFallbackInfo(null);
        try {
            const res = await urbanSimApi.generateCheckpoints(projectId, {
                prompt: aiCpPrompt.trim(),
                max_checkpoints: 20,
            });
            setAiCpDrafts(res.checkpoints.map((c) => ({ ...c, selected: true })));
            if (!res.used_vision && res.fallback_reason) {
                setAiCpFallbackInfo(res.fallback_reason);
            }
        } catch (err) {
            message.error(err instanceof Error ? err.message : "AI sinh Chốt thất bại");
        } finally {
            setAiCpGenerating(false);
        }
    };

    const handleApplyAiCheckpoints = async () => {
        const picked = aiCpDrafts.filter((c) => c.selected);
        if (picked.length === 0) {
            message.warning("Hãy chọn ít nhất 1 chốt để lưu.");
            return;
        }
        setAiCpApplying(true);
        try {
            await urbanSimApi.applyCheckpointsBatch(
                projectId,
                picked.map((c, idx) => ({
                    checkpoint_key: c.checkpoint_key,
                    name: c.name,
                    x_pct: c.x_pct,
                    y_pct: c.y_pct,
                    icon_emoji: c.icon_emoji,
                    description_md: c.description_md,
                    category: c.category,
                    sort_order: checkpoints.length + idx + 1,
                }))
            );
            message.success(`Đã lưu ${picked.length} Chốt/Pin vào Bản đồ Số.`);
            setAiCpDrafts([]);
            setAiCpModalOpen(false);
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Lưu hàng loạt Chốt thất bại");
        } finally {
            setAiCpApplying(false);
        }
    };

    const handleExportGeoJson = async () => {
        try {
            const geo = await urbanSimApi.exportDigitalMapGeoJson(projectId);
            const blob = new Blob([JSON.stringify(geo, null, 2)], { type: "application/geo+json;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `digital-map-${projectId}.geojson`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không xuất được GeoJSON");
        }
    };

    const handleDeleteVertex = (zoneId: string, vertexIdx: number) => {
        const cur = localPolygons[zoneId];
        if (!cur || cur.length <= 3) {
            message.warning("Polygon phải giữ tối thiểu 3 đỉnh.");
            return;
        }
        setUndoStack((prev) => [
            ...prev.slice(-14),
            {
                polygons: clonePolygonsMap(localPolygonsRef.current),
                checkpoints: cloneCpCoordsMap(localCpCoordsRef.current),
            },
        ]);
        const next = cur.filter((_, idx) => idx !== vertexIdx);
        localPolygonsRef.current = { ...localPolygonsRef.current, [zoneId]: next };
        setDraftPolygons((prev) => ({ ...prev, [zoneId]: next }));
        void persistLayoutChanges([zoneId], []);
    };

    const handleInsertMidpoint = (zoneId: string, edgeIdx: number) => {
        const cur = localPolygons[zoneId];
        if (!cur || cur.length >= 32) {
            message.warning("Polygon đã đạt tối đa 32 đỉnh.");
            return;
        }
        setUndoStack((prev) => [
            ...prev.slice(-14),
            {
                polygons: clonePolygonsMap(localPolygonsRef.current),
                checkpoints: cloneCpCoordsMap(localCpCoordsRef.current),
            },
        ]);
        const p1 = cur[edgeIdx];
        const p2 = cur[(edgeIdx + 1) % cur.length];
        const mid: PolygonPoint = [clampPct((p1[0] + p2[0]) / 2), clampPct((p1[1] + p2[1]) / 2)];
        const next = [...cur.slice(0, edgeIdx + 1), mid, ...cur.slice(edgeIdx + 1)];
        localPolygonsRef.current = { ...localPolygonsRef.current, [zoneId]: next };
        setDraftPolygons((prev) => ({ ...prev, [zoneId]: next }));
        void persistLayoutChanges([zoneId], []);
    };

    const handleQuickPlaceUnplacedZone = async (z: UrbanSimZone | ZoneTopologyCard, idxHint: number) => {
        if (!z.id) return;
        const col = idxHint % 4;
        const row = Math.floor(idxHint / 4) % 3;
        const x1 = clampPct(10 + col * 21);
        const y1 = clampPct(12 + row * 24);
        const x2 = clampPct(x1 + 17);
        const y2 = clampPct(y1 + 16);
        const poly: PolygonPoint[] = [
            [x1, y1],
            [x2, y1],
            [x2, y2],
            [x1, y2],
        ];
        const [cx, cy] = computePolygonCenter(poly);
        try {
            await urbanSimApi.saveZonesLayout(projectId, [
                {
                    id: z.id,
                    polygon_points: poly,
                    center_x_pct: cx,
                    center_y_pct: cy,
                },
            ]);
            setSavedPolys((prev) => ({ ...prev, [z.id!]: poly }));
            localPolygonsRef.current = { ...localPolygonsRef.current, [z.id]: poly };
            setDraftPolygons((prev) => ({ ...prev, [z.id!]: poly }));
            setSelectedZoneId(z.id);
            setSelectedCpId(null);
            message.success(`Đã đặt Polygon cho Khu vực "${z.name}". Hãy kéo chỉnh vị trí và kích thước.`);
            onRefreshMap?.();
        } catch (err) {
            message.error(err instanceof Error ? err.message : "Không đặt được Polygon");
        }
    };

    const selectedZonePts = useMemo(
        () => (selectedZoneId && localPolygons[selectedZoneId]?.length >= 3 ? localPolygons[selectedZoneId] : null),
        [selectedZoneId, localPolygons]
    );

    const selectedZoneBBox = useMemo(
        () => (selectedZonePts ? computePolygonBBox(selectedZonePts) : null),
        [selectedZonePts]
    );

    // Computed geometry maps for rendering (prioritize live localPolygons centroid so labels follow drag!)
    const zoneCenterMap = useMemo(() => {
        const m = new Map<string, [number, number]>();
        zones.forEach((z, idx) => {
            const poly = z.id && localPolygons[z.id] ? localPolygons[z.id] : z.polygon_points;
            if (Array.isArray(poly) && poly.length >= 3) {
                m.set(z.zone_key, computePolygonCenter(poly));
            } else if (typeof z.center_x_pct === "number" && typeof z.center_y_pct === "number") {
                m.set(z.zone_key, [z.center_x_pct, z.center_y_pct]);
            } else {
                const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(1, zones.length))));
                const ri = Math.floor(idx / cols);
                const ci = idx % cols;
                m.set(z.zone_key, [
                    clampPct(14 + (ci + 0.5) * (72 / cols)),
                    clampPct(16 + (ri + 0.5) * (68 / Math.max(1, Math.ceil(zones.length / cols)))),
                ]);
            }
        });
        return m;
    }, [zones, localPolygons]);

    const personaCountByZone = useMemo(() => {
        const counts = new Map<string, number>();
        if (personas && personas.length > 0) {
            for (const p of personas) {
                counts.set(p.home_zone, (counts.get(p.home_zone) || 0) + 1);
            }
        } else {
            for (const z of zones) {
                if (typeof z.persona_count === "number") {
                    counts.set(z.zone_key, z.persona_count);
                }
            }
        }
        return counts;
    }, [personas, zones]);

    const liveCheckpointZoneKey = useCallback(
        (cp: UrbanSimCheckpoint): string | null => {
            const coords = localCpCoords[cp.id];
            if (!coords) return cp.zone_key || null;
            for (const z of zones) {
                const poly = z.id && localPolygons[z.id] ? localPolygons[z.id] : z.polygon_points;
                if (Array.isArray(poly) && poly.length >= 3 && pointInPolygonFE(coords[0], coords[1], poly)) {
                    return z.zone_key;
                }
            }
            return isDragging ? null : cp.zone_key || null;
        },
        [localCpCoords, zones, localPolygons, isDragging]
    );

    const unplacedZones = useMemo(
        () => zones.filter((z) => z.id && (!localPolygons[z.id] || localPolygons[z.id].length < 3)),
        [zones, localPolygons]
    );

    const filteredLiveAgents = useMemo(() => {
        if (mode !== "live") return [];
        return agentStatuses.filter((ag) => {
            if (liveGroupFilter !== "ALL" && ag.group_type !== liveGroupFilter) return false;
            if (liveSelectedAgentId !== "ALL" && ag.agent_id !== liveSelectedAgentId) return false;
            return true;
        });
    }, [mode, agentStatuses, liveGroupFilter, liveSelectedAgentId]);

    const positionedAgents = useMemo(
        () => computeRadialAgentPositions(filteredLiveAgents, zoneCenterMap, isMobile),
        [filteredLiveAgents, zoneCenterMap, isMobile]
    );

    const hasUnsavedLayout = dirtyZoneIds.size > 0 || dirtyCpIds.size > 0;
    const selectedZoneObj = zones.find((z) => z.id === selectedZoneId) || null;
    const selectedCpObj = checkpoints.find((c) => c.id === selectedCpId) || null;

    return (
        <Space direction="vertical" size="small" style={{ width: "100%" }}>
            {mode === "edit" ? (
                <Card size="small" bodyStyle={{ padding: "8px 12px" }}>
                    <Space wrap size={[6, 6]} style={{ width: "100%", justifyContent: "space-between" }}>
                        <Space wrap size={[6, 6]}>
                            <Segmented
                                size="small"
                                value={editTool}
                                onChange={(val) => {
                                    setEditTool(val as EditTool);
                                    if (val !== "draw_polygon") setDrawingPts([]);
                                }}
                                options={[
                                    { label: <Space size={4}><DragOutlined />Chọn / Kéo</Space>, value: "select" },
                                    { label: <Space size={4}><EditOutlined />Vẽ Polygon</Space>, value: "draw_polygon" },
                                    { label: <Space size={4}><AimOutlined />Điểm tâm + AI</Space>, value: "point_prompt" },
                                    {
                                        label: (
                                            <Tooltip
                                                title={
                                                    hasDigitalMap
                                                        ? "Click lên bản đồ để đặt Chốt/Pin mới"
                                                        : "Cần có Bản đồ Số (Ảnh 2D hoặc ít nhất 1 Polygon Khu vực) trước khi đặt Chốt"
                                                }
                                            >
                                                <Space size={4} style={{ opacity: hasDigitalMap ? 1 : 0.5 }}>
                                                    <PushpinOutlined />Đặt Chốt
                                                </Space>
                                            </Tooltip>
                                        ),
                                        value: "place_checkpoint",
                                        disabled: !hasDigitalMap,
                                    },
                                ]}
                            />
                            <Button
                                size="small"
                                icon={<RobotOutlined />}
                                onClick={() => {
                                    setAiMapPrompt(digitalMap?.map_prompt || "");
                                    setAiMapDraft(null);
                                    setAiMapModalOpen(true);
                                }}
                            >
                                AI Tạo Bản đồ Số
                            </Button>
                            <Tooltip
                                title={
                                    hasDigitalMap
                                        ? "Sinh nhiều Chốt tuần tra / tiện ích từ Prompt"
                                        : "Cần tạo Bản đồ Số (Ảnh 2D hoặc Polygon Khu vực) trước"
                                }
                            >
                                <Button
                                    size="small"
                                    icon={<PushpinOutlined />}
                                    disabled={!hasDigitalMap}
                                    onClick={() => {
                                        setAiCpDrafts([]);
                                        setAiCpFallbackInfo(null);
                                        setAiCpModalOpen(true);
                                    }}
                                >
                                    AI Sinh Chốt
                                </Button>
                            </Tooltip>
                        </Space>
                        <Space wrap size={[6, 6]}>
                            {drawingPts.length > 0 && (
                                <>
                                    <Tag color="processing">Đang vẽ: {drawingPts.length} đỉnh</Tag>
                                    <Button
                                        size="small"
                                        type="primary"
                                        icon={<CheckOutlined />}
                                        disabled={drawingPts.length < 3}
                                        onClick={handleFinishDrawnPolygon}
                                    >
                                        Hoàn tất hình
                                    </Button>
                                    <Button
                                        size="small"
                                        icon={<CloseOutlined />}
                                        onClick={() => setDrawingPts([])}
                                    >
                                        Hủy vẽ
                                    </Button>
                                </>
                            )}
                            {undoStack.length > 0 && (
                                <Tooltip title="Hoàn tác thao tác vừa kéo/chỉnh (Ctrl+Z)">
                                    <Button
                                        size="small"
                                        data-testid="canvas-undo-btn"
                                        icon={<UndoOutlined />}
                                        disabled={savingLayout}
                                        onClick={handleUndo}
                                    >
                                        Hoàn tác ({undoStack.length})
                                    </Button>
                                </Tooltip>
                            )}
                            {autoSaveStatus === "saving" && (
                                <Tag color="processing" style={{ marginInlineEnd: 0 }}>Đang tự động lưu...</Tag>
                            )}
                            {autoSaveStatus === "saved" && !hasUnsavedLayout && (
                                <Tag color="success" style={{ marginInlineEnd: 0 }}>Đã tự động lưu</Tag>
                            )}
                            {hasUnsavedLayout && (
                                <Button
                                    size="small"
                                    type="primary"
                                    icon={<SaveOutlined />}
                                    loading={savingLayout}
                                    onClick={() => void handleSaveLayout()}
                                >
                                    Lưu bố cục ({dirtyZoneIds.size + dirtyCpIds.size})
                                </Button>
                            )}
                            <Button size="small" icon={<DownloadOutlined />} onClick={() => void handleExportGeoJson()}>
                                GeoJSON
                            </Button>
                        </Space>
                    </Space>
                    {unplacedZones.length > 0 && (
                        <div
                            style={{
                                marginTop: 8,
                                paddingTop: 8,
                                borderTop: "1px dashed #e2e8f0",
                                display: "flex",
                                alignItems: "center",
                                flexWrap: "wrap",
                                gap: 6,
                            }}
                        >
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                Khu vực chưa có Polygon trên bản đồ ({unplacedZones.length}):
                            </Text>
                            {unplacedZones.map((uz, uIdx) => (
                                <Button
                                    key={uz.id || uz.zone_key}
                                    size="small"
                                    type="dashed"
                                    icon={<PlusOutlined />}
                                    onClick={() => void handleQuickPlaceUnplacedZone(uz, uIdx)}
                                >
                                    Đặt hình: {uz.name}
                                </Button>
                            ))}
                        </div>
                    )}
                </Card>
            ) : (
                <Card size="small" bodyStyle={{ padding: "8px 12px" }}>
                    <Space wrap size={[8, 8]} style={{ width: "100%", justifyContent: "space-between" }}>
                        <Space wrap size={[8, 6]}>
                            <Segmented
                                size="small"
                                value={liveGroupFilter}
                                onChange={(v) => setLiveGroupFilter(v as "ALL" | "BQL" | "RESIDENT")}
                                options={[
                                    { label: `Tất cả (${agentStatuses.length})`, value: "ALL" },
                                    { label: "Ban Quản lý", value: "BQL" },
                                    { label: "Cư dân", value: "RESIDENT" },
                                ]}
                            />
                            <Select
                                size="small"
                                style={{ width: isMobile ? "100%" : 210 }}
                                value={liveSelectedAgentId}
                                onChange={(val) => setLiveSelectedAgentId(val)}
                                options={[
                                    { value: "ALL", label: "Hiện tất cả Persona" },
                                    ...agentStatuses.map((a) => ({
                                        value: a.agent_id,
                                        label: `#${a.agent_id} ${a.full_name}`,
                                    })),
                                ]}
                            />
                        </Space>
                        <Space wrap size={[10, 6]}>
                            <Space size={4}>
                                <Switch size="small" checked={showTrails} onChange={setShowTrails} />
                                <Text style={{ fontSize: 12 }}>Quỹ đạo</Text>
                            </Space>
                            <Space size={4}>
                                <Switch size="small" checked={showCheckpoints} onChange={setShowCheckpoints} />
                                <Text style={{ fontSize: 12 }}>Chốt ({checkpoints.length})</Text>
                            </Space>
                            <Space size={4}>
                                <Switch size="small" checked={showZoneLabels} onChange={setShowZoneLabels} />
                                <Text style={{ fontSize: 12 }}>Nhãn Khu vực</Text>
                            </Space>
                            <Space size={4}>
                                <Switch
                                    size="small"
                                    data-testid="live-toggle-agent-names"
                                    checked={showAgentNames}
                                    onChange={setShowAgentNames}
                                />
                                <Text style={{ fontSize: 12 }}>Tên Agent</Text>
                            </Space>
                        </Space>
                    </Space>
                </Card>
            )}

            {!hasDigitalMap && mode === "edit" && (
                <Alert
                    type="info"
                    showIcon
                    message="Chưa có dữ liệu Bản đồ Số"
                    description="Hãy tải Ảnh mặt bằng 2D (tùy chọn), vẽ Polygon Khu vực hoặc bấm 'AI Tạo Bản đồ Số' để mở khóa tính năng đặt/sinh Chốt & Pin địa điểm."
                />
            )}

            {aiMapDraft && (
                <Alert
                    type={aiMapDraft.used_vision ? "success" : "warning"}
                    showIcon
                    message={
                        <Space wrap>
                            <span>
                                Bản nháp AI: {aiMapDraft.zones.length} Khu vực Polygon (
                                {aiMapDraft.used_vision ? "Vision + Prompt" : "Text-only Fallback"})
                            </span>
                            <Button
                                size="small"
                                type="primary"
                                loading={aiMapApplying}
                                onClick={() => void handleApplyAiMap()}
                            >
                                Áp dụng ({aiMapApplyMode === "MERGE" ? "Gộp an toàn" : "Thay thế"})
                            </Button>
                            <Button size="small" onClick={() => setAiMapDraft(null)}>Bỏ nháp</Button>
                        </Space>
                    }
                    description={aiMapDraft.fallback_reason || "Đường viền nét đứt màu tím trên bản đồ là vị trí dự kiến. Bấm Áp dụng để lưu vào Database."}
                />
            )}

            {/* Outer Viewport with Zoom/Pan controls */}
            <div
                style={{
                    position: "relative",
                    width: "100%",
                    maxWidth: "100%",
                    overflow: "hidden",
                    borderRadius: 10,
                    border: "1px solid #d9d9d9",
                    background: "#eef2f6",
                }}
            >
                <div
                    style={{
                        position: "absolute",
                        top: 8,
                        right: 8,
                        zIndex: 25,
                        display: "flex",
                        gap: 4,
                        background: "rgba(255,255,255,0.92)",
                        padding: 4,
                        borderRadius: 8,
                        boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
                    }}
                >
                    <Button
                        size="small"
                        icon={<ZoomOutOutlined />}
                        aria-label="Thu nhỏ bản đồ"
                        onClick={() => setZoom((z) => Math.max(0.6, Math.round((z - 0.2) * 10) / 10))}
                    />
                    <Text style={{ fontSize: 12, alignSelf: "center", minWidth: 38, textAlign: "center" }}>
                        {Math.round(zoom * 100)}%
                    </Text>
                    <Button
                        size="small"
                        icon={<ZoomInOutlined />}
                        aria-label="Phóng to bản đồ"
                        onClick={() => setZoom((z) => Math.min(3.0, Math.round((z + 0.2) * 10) / 10))}
                    />
                    <Button
                        size="small"
                        icon={<FullscreenExitOutlined />}
                        aria-label="Đưa về góc nhìn mặc định"
                        onClick={() => {
                            setZoom(1);
                            setPan({ x: 0, y: 0 });
                        }}
                    />
                </div>

                <div
                    style={{
                        width: "100%",
                        display: "flex",
                        justifyContent: "center",
                        alignItems: "center",
                        padding: isMobile ? 4 : 10,
                    }}
                >
                    {/* Coaxial Aspect-Locked Box: <img> + <svg viewBox="0 0 100 100"> + HTML Overlay share exact 0..100 coordinates */}
                    <div
                        ref={innerBoxRef}
                        data-testid="digital-urban-map-canvas"
                        onClick={handleCanvasClick}
                        onPointerDown={(e) => {
                            if (e.button === 1 || (zoom > 1 && e.target === innerBoxRef.current)) {
                                e.preventDefault();
                                startDrag({
                                    kind: "pan",
                                    startClientX: e.clientX,
                                    startClientY: e.clientY,
                                    origPanX: pan.x,
                                    origPanY: pan.y,
                                });
                            } else if (mode === "edit" && editTool === "select" && e.target === innerBoxRef.current) {
                                setSelectedZoneId(null);
                                setSelectedCpId(null);
                            }
                        }}
                        style={{
                            position: "relative",
                            width: "100%",
                            maxWidth: 980,
                            aspectRatio: String(aspectRatio),
                            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                            transformOrigin: "center center",
                            borderRadius: 8,
                            overflow: "hidden",
                            background: "#ffffff",
                            border: "1px solid #cbd5e1",
                            userSelect: "none",
                            touchAction: isDragging
                                ? "none"
                                : editTool === "select" && zoom === 1
                                  ? "pan-y"
                                  : "none",
                            cursor:
                                editTool === "draw_polygon" || editTool === "point_prompt" || editTool === "place_checkpoint"
                                    ? "crosshair"
                                    : "default",
                        }}
                    >
                        {/* Layer 1: Optional 2D Image OR Blueprint Grid */}
                        {resolvedImageUrl && !imgError ? (
                            <img
                                src={resolvedImageUrl}
                                alt="Bản đồ Số Khu đô thị"
                                onError={() => setFailedImageUrl(resolvedImageUrl)}
                                style={{
                                    position: "absolute",
                                    inset: 0,
                                    width: "100%",
                                    height: "100%",
                                    display: "block",
                                    pointerEvents: "none",
                                }}
                            />
                        ) : null}

                        {/* Layer 2: SVG ViewBox [0..100] x [0..100] */}
                        <svg
                            viewBox="0 0 100 100"
                            preserveAspectRatio="none"
                            style={{
                                position: "absolute",
                                inset: 0,
                                width: "100%",
                                height: "100%",
                                overflow: "visible",
                            }}
                        >
                            <defs>
                                <pattern id="urbanGrid10" width="10" height="10" patternUnits="userSpaceOnUse">
                                    <path
                                        d="M 10 0 L 0 0 0 10"
                                        fill="none"
                                        stroke={resolvedImageUrl && !imgError ? "rgba(15,23,42,0.08)" : "rgba(148,163,184,0.28)"}
                                        strokeWidth="0.2"
                                    />
                                </pattern>
                                <style>{`
                                    @keyframes urbanPulseRed {
                                        0%, 100% { stroke-opacity: 0.95; stroke-width: 0.7; }
                                        50% { stroke-opacity: 0.35; stroke-width: 1.3; }
                                    }
                                    .urban-poly-incident {
                                        animation: urbanPulseRed 1.4s ease-in-out infinite;
                                    }
                                `}</style>
                            </defs>

                            <rect x="0" y="0" width="100" height="100" fill="url(#urbanGrid10)" style={{ pointerEvents: "none" }} />

                            {/* Existing Zone Polygons */}
                            {zones.map((z, idx) => {
                                const pts =
                                    z.id && localPolygons[z.id]
                                        ? localPolygons[z.id]
                                        : z.polygon_points || null;
                                if (!pts || pts.length < 3) return null;
                                const pointsAttr = pts.map((p) => `${p[0]},${p[1]}`).join(" ");
                                const color = z.fill_color || ZONE_COLORS[idx % ZONE_COLORS.length];
                                const isSelected = mode === "edit" && selectedZoneId === z.id;
                                const openInc = "open_incidents" in z ? z.open_incidents.length : 0;
                                const hasInc = mode === "live" && openInc > 0;
                                return (
                                    <polygon
                                        key={z.id || z.zone_key}
                                        data-testid={`zone-polygon-${z.zone_key}`}
                                        points={pointsAttr}
                                        fill={color}
                                        fillOpacity={hasInc ? 0.3 : isSelected ? 0.32 : resolvedImageUrl && !imgError ? 0.18 : 0.22}
                                        stroke={hasInc ? "#ff4d4f" : isSelected ? "#1d4ed8" : color}
                                        strokeWidth={isSelected ? 0.75 : 0.45}
                                        className={hasInc ? "urban-poly-incident" : undefined}
                                        style={{
                                            cursor: mode === "edit" && editTool === "select" ? "move" : "pointer",
                                            touchAction: mode === "edit" && editTool === "select" ? "none" : "auto",
                                        }}
                                        onClick={(e) => {
                                            if (didMoveRef.current) {
                                                didMoveRef.current = false;
                                                return;
                                            }
                                            if (mode === "edit" && editTool === "select" && z.id) {
                                                e.stopPropagation();
                                                setSelectedZoneId(z.id);
                                                setSelectedCpId(null);
                                            } else if (mode === "live" && isMobile && "agents_here" in z) {
                                                e.stopPropagation();
                                                setLiveMobileZone(z);
                                            }
                                        }}
                                        onDoubleClick={(e) => {
                                            if (mode === "edit" && onEditZoneDetails) {
                                                e.stopPropagation();
                                                onEditZoneDetails(toZoneTopologyCard(z));
                                            }
                                        }}
                                        onPointerDown={(e) => {
                                            if (mode !== "edit" || editTool !== "select" || !z.id || e.button !== 0) return;
                                            e.preventDefault();
                                            e.stopPropagation();
                                            const [sx, sy] = clientPointToPct(e.clientX, e.clientY);
                                            setSelectedZoneId(z.id);
                                            setSelectedCpId(null);
                                            startDrag({
                                                kind: "polygon",
                                                zoneId: z.id,
                                                startX: sx,
                                                startY: sy,
                                                origPoints: pts.map((p) => [p[0], p[1]] as PolygonPoint),
                                            });
                                        }}
                                    />
                                );
                            })}

                            {/* Selected Polygon Bounding Box Guide in Edit Mode */}
                            {mode === "edit" && editTool === "select" && selectedZoneBBox && (
                                <rect
                                    x={selectedZoneBBox.minX}
                                    y={selectedZoneBBox.minY}
                                    width={Math.max(0.5, selectedZoneBBox.maxX - selectedZoneBBox.minX)}
                                    height={Math.max(0.5, selectedZoneBBox.maxY - selectedZoneBBox.minY)}
                                    fill="none"
                                    stroke="#1d4ed8"
                                    strokeWidth={0.35}
                                    strokeDasharray="1.0,0.8"
                                    style={{ pointerEvents: "none" }}
                                />
                            )}

                            {/* AI Full Map Draft Preview Polygons */}
                            {aiMapDraft?.zones.map((dz) => (
                                <polygon
                                    key={`draft-${dz.zone_key}`}
                                    points={dz.polygon_points.map((p) => `${p[0]},${p[1]}`).join(" ")}
                                    fill={dz.fill_color || "#722ed1"}
                                    fillOpacity={0.22}
                                    stroke="#722ed1"
                                    strokeWidth={0.6}
                                    strokeDasharray="1.5,1.0"
                                    style={{ pointerEvents: "none" }}
                                />
                            ))}

                            {/* In-progress Drawing Polygon */}
                            {drawingPts.length >= 2 && (
                                <polyline
                                    points={drawingPts.map((p) => `${p[0]},${p[1]}`).join(" ")}
                                    fill={drawingPts.length >= 3 ? "rgba(22, 119, 255, 0.18)" : "none"}
                                    stroke="#1677ff"
                                    strokeWidth={0.65}
                                    strokeDasharray="1.2,0.8"
                                    style={{ pointerEvents: "none" }}
                                />
                            )}
                            {drawingPts.map((pt, i) => (
                                <circle
                                    key={`draw-pt-${i}`}
                                    cx={pt[0]}
                                    cy={pt[1]}
                                    r={1.1}
                                    fill="#1677ff"
                                    stroke="#ffffff"
                                    strokeWidth={0.35}
                                    style={{ pointerEvents: "none" }}
                                />
                            ))}

                            {/* Live Movement Trails (<=12 pts/agent) */}
                            {mode === "live" &&
                                showTrails &&
                                positionedAgents.map(({ agent }) => {
                                    const trail = agent.recent_trail || [];
                                    if (trail.length < 2) return null;
                                    const ptsStr = trail.map((t) => `${t.x_pct},${t.y_pct}`).join(" ");
                                    const strokeCol = agent.group_type === "BQL" ? "#1677ff" : "#722ed1";
                                    return (
                                        <g key={`trail-${agent.agent_id}`} style={{ pointerEvents: "none" }}>
                                            <polyline
                                                points={ptsStr}
                                                fill="none"
                                                stroke={strokeCol}
                                                strokeWidth={0.5}
                                                strokeOpacity={0.55}
                                                strokeDasharray="1.3,0.9"
                                            />
                                        </g>
                                    );
                                })}
                        </svg>

                        {/* Layer 3: HTML Overlay — Edit Handles, Corner Resize, Zone Labels, Floating Actions, Checkpoints & Live Avatars */}
                        <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
                            {/* Zone Labels */}
                            {showZoneLabels &&
                                zones.map((z) => {
                                    const center = zoneCenterMap.get(z.zone_key) || [50, 50];
                                    const polyPts = z.id && localPolygons[z.id] ? localPolygons[z.id] : z.polygon_points;
                                    const hasLiveBox = mode === "live" && Array.isArray(polyPts) && polyPts.length >= 3;
                                    const liveBox = hasLiveBox ? computePolygonBBox(polyPts as PolygonPoint[]) : null;
                                    const labelLeft = liveBox ? clampPct(liveBox.minX + 1.2, 1, 88) : center[0];
                                    const labelTop = liveBox ? clampPct(liveBox.minY + 1.5, 1, 90) : center[1];
                                    const openCnt = "open_incidents" in z ? z.open_incidents.length : 0;
                                    const pCount = personaCountByZone.get(z.zone_key) || 0;
                                    return (
                                        <div
                                            key={`zlabel-${z.zone_key}`}
                                            data-testid={`zone-label-${z.zone_key}`}
                                            style={{
                                                position: "absolute",
                                                left: `${labelLeft}%`,
                                                top: `${labelTop}%`,
                                                transform: liveBox ? "none" : "translate(-50%, -50%)",
                                                background: "rgba(255,255,255,0.9)",
                                                border: openCnt > 0 ? "1px solid #ff4d4f" : "1px solid rgba(148,163,184,0.6)",
                                                borderRadius: 6,
                                                padding: "1px 6px",
                                                fontSize: isMobile ? 10 : 11,
                                                fontWeight: 600,
                                                color: "#0f172a",
                                                whiteSpace: "nowrap",
                                                maxWidth: 170,
                                                overflow: "hidden",
                                                textOverflow: "ellipsis",
                                                boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                                                pointerEvents: "none",
                                            }}
                                        >
                                            {z.name}
                                            {mode === "edit" && pCount > 0 ? ` · 👤${pCount}` : ""}
                                            {openCnt > 0 ? ` (${openCnt})` : ""}
                                        </div>
                                    );
                                })}

                            {/* Selected Polygon 4 Corner Bounding-Box Resize Handles */}
                            {mode === "edit" &&
                                editTool === "select" &&
                                selectedZoneId &&
                                selectedZoneBBox &&
                                selectedZonePts && (
                                    <CornerResizeHandlesOverlay
                                        zoneId={selectedZoneId}
                                        bbox={selectedZoneBBox}
                                        pts={selectedZonePts}
                                        onStartResize={startDrag}
                                    />
                                )}

                            {/* Selected Polygon Vertex & Midpoint Drag Handles in Edit Mode */}
                            {mode === "edit" &&
                                editTool === "select" &&
                                selectedZoneId &&
                                localPolygons[selectedZoneId]?.map((pt, vIdx, arr) => {
                                    const nextPt = arr[(vIdx + 1) % arr.length];
                                    const midX = (pt[0] + nextPt[0]) / 2;
                                    const midY = (pt[1] + nextPt[1]) / 2;
                                    return (
                                        <React.Fragment key={`handle-${selectedZoneId}-${vIdx}`}>
                                            {/* Vertex handle (>=32px hitbox, touch-action: none) */}
                                            <div
                                                data-testid={`vertex-handle-${vIdx}`}
                                                onPointerDown={(e) => {
                                                    if (e.button !== 0) return;
                                                    e.preventDefault();
                                                    e.stopPropagation();
                                                    startDrag({
                                                        kind: "vertex",
                                                        zoneId: selectedZoneId,
                                                        vertexIdx: vIdx,
                                                    });
                                                }}
                                                onContextMenu={(e) => {
                                                    e.preventDefault();
                                                    e.stopPropagation();
                                                    handleDeleteVertex(selectedZoneId, vIdx);
                                                }}
                                                title={`Đỉnh #${vIdx + 1} (kéo để sửa; chuột phải xóa đỉnh)`}
                                                style={{
                                                    position: "absolute",
                                                    left: `${pt[0]}%`,
                                                    top: `${pt[1]}%`,
                                                    width: 32,
                                                    height: 32,
                                                    transform: "translate(-50%, -50%)",
                                                    display: "flex",
                                                    alignItems: "center",
                                                    justifyContent: "center",
                                                    cursor: "grab",
                                                    touchAction: "none",
                                                    pointerEvents: "auto",
                                                    zIndex: 18,
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        width: 12,
                                                        height: 12,
                                                        borderRadius: "50%",
                                                        background: "#1677ff",
                                                        border: "2px solid #ffffff",
                                                        boxShadow: "0 1px 4px rgba(0,0,0,0.35)",
                                                    }}
                                                />
                                            </div>
                                            {/* Midpoint insert handle */}
                                            <div
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleInsertMidpoint(selectedZoneId, vIdx);
                                                }}
                                                title="Bấm để thêm đỉnh mới giữa cạnh này"
                                                style={{
                                                    position: "absolute",
                                                    left: `${midX}%`,
                                                    top: `${midY}%`,
                                                    width: 24,
                                                    height: 24,
                                                    transform: "translate(-50%, -50%)",
                                                    display: "flex",
                                                    alignItems: "center",
                                                    justifyContent: "center",
                                                    cursor: "copy",
                                                    pointerEvents: "auto",
                                                    zIndex: 16,
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        width: 8,
                                                        height: 8,
                                                        borderRadius: "50%",
                                                        background: "#ffffff",
                                                        border: "1.5px solid #1677ff",
                                                    }}
                                                />
                                            </div>
                                        </React.Fragment>
                                    );
                                })}

                            {/* Checkpoints / Pins */}
                            {(mode === "edit" || showCheckpoints) &&
                                checkpoints.map((cp) => {
                                    const coords = localCpCoords[cp.id] || [cp.x_pct, cp.y_pct];
                                    const agentsCount = cp.agents_here?.length || 0;
                                    const isCpSel = mode === "edit" && selectedCpId === cp.id;
                                    const cpZoneKey = liveCheckpointZoneKey(cp);

                                    const pinButton = (
                                        <div
                                            data-testid={`checkpoint-pin-${cp.checkpoint_key}`}
                                            draggable={false}
                                            onPointerDown={(e) => {
                                                if (mode !== "edit" || editTool !== "select" || e.button !== 0) return;
                                                e.preventDefault();
                                                e.stopPropagation();
                                                setSelectedCpId(cp.id);
                                                setSelectedZoneId(null);
                                                startDrag({ kind: "checkpoint", cpId: cp.id });
                                            }}
                                            onClick={(e) => {
                                                if (didMoveRef.current) {
                                                    didMoveRef.current = false;
                                                    return;
                                                }
                                                if (mode === "edit") {
                                                    e.stopPropagation();
                                                    setSelectedCpId(cp.id);
                                                    setSelectedZoneId(null);
                                                } else if (isMobile) {
                                                    e.stopPropagation();
                                                    setLiveMobileCp(cp);
                                                } else {
                                                    e.stopPropagation();
                                                    setLiveDesktopCpId((prev) => (prev === cp.id ? null : cp.id));
                                                }
                                            }}
                                            onDoubleClick={(e) => {
                                                if (mode === "edit") {
                                                    e.stopPropagation();
                                                    openCpModal(cp);
                                                }
                                            }}
                                            style={{
                                                position: "absolute",
                                                left: `${coords[0]}%`,
                                                top: `${coords[1]}%`,
                                                minWidth: 32,
                                                minHeight: 32,
                                                transform: "translate(-50%, -50%)",
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                cursor: mode === "edit" ? "grab" : "pointer",
                                                touchAction: mode === "edit" ? "none" : "auto",
                                                pointerEvents: "auto",
                                                zIndex: isCpSel ? 22 : 14,
                                            }}
                                        >
                                            <Badge count={agentsCount > 0 ? agentsCount : 0} size="small" offset={[-2, 2]}>
                                                <div
                                                    style={{
                                                        display: "inline-flex",
                                                        alignItems: "center",
                                                        gap: 3,
                                                        padding: "2px 6px",
                                                        borderRadius: 14,
                                                        background: isCpSel ? "#fff7e6" : "rgba(255,255,255,0.96)",
                                                        border: isCpSel ? "2px solid #fa8c16" : "1.5px solid #475569",
                                                        boxShadow: "0 2px 6px rgba(0,0,0,0.16)",
                                                        fontSize: isMobile ? 11 : 12,
                                                        fontWeight: 600,
                                                        color: "#0f172a",
                                                    }}
                                                >
                                                    <span>{cp.icon_emoji || "📍"}</span>
                                                    {!isMobile && (
                                                        <span style={{ maxWidth: 96, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                            {cp.name}
                                                        </span>
                                                    )}
                                                </div>
                                            </Badge>
                                        </div>
                                    );

                                    if (mode === "live" && !isMobile) {
                                        return (
                                            <Popover
                                                key={cp.id}
                                                open={liveDesktopCpId === cp.id}
                                                onOpenChange={(vis) => {
                                                    if (!vis) {
                                                        setLiveDesktopCpId((prev) => (prev === cp.id ? null : prev));
                                                    }
                                                }}
                                                trigger="click"
                                                title={
                                                    <Space>
                                                        <span>{cp.icon_emoji || "📍"}</span>
                                                        <span>{cp.name}</span>
                                                        <Tag>{cp.checkpoint_key}</Tag>
                                                    </Space>
                                                }
                                                content={
                                                    <div style={{ width: 340, maxHeight: 300, overflowY: "auto" }}>
                                                        <Space wrap size={4} style={{ marginBottom: 8 }}>
                                                            <Tag color="blue">{cpZoneKey || "Ngoài Khu vực"}</Tag>
                                                            <Tag>({coords[0].toFixed(1)}%, {coords[1].toFixed(1)}%)</Tag>
                                                        </Space>
                                                        {cp.description_md ? (
                                                            <MarkdownWithMermaid content={cp.description_md} />
                                                        ) : (
                                                            <Text type="secondary">Chưa có mô tả chi tiết cho chốt này.</Text>
                                                        )}
                                                        {cp.agents_here && cp.agents_here.length > 0 && (
                                                            <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed #e2e8f0" }}>
                                                                <Text strong style={{ fontSize: 12 }}>Đang có mặt ({cp.agents_here.length}):</Text>
                                                                <div style={{ marginTop: 4 }}>
                                                                    {cp.agents_here.map((a) => (
                                                                        <Tag
                                                                            key={a.agent_id}
                                                                            color={a.group_type === "BQL" ? "blue" : "purple"}
                                                                            style={{ cursor: "pointer", marginBottom: 4 }}
                                                                            onClick={() => onOpenAgentTimeline?.(a.agent_id)}
                                                                        >
                                                                            #{a.agent_id} {a.full_name}
                                                                        </Tag>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                }
                                            >
                                                {pinButton}
                                            </Popover>
                                        );
                                    }
                                    return <React.Fragment key={cp.id}>{pinButton}</React.Fragment>;
                                })}

                            {/* AI Checkpoints Preview Pins */}
                            {mode === "edit" &&
                                aiCpDrafts
                                    .filter((c) => c.selected)
                                    .map((cp) => (
                                        <div
                                            key={`draft-cp-${cp.checkpoint_key}`}
                                            style={{
                                                position: "absolute",
                                                left: `${cp.x_pct}%`,
                                                top: `${cp.y_pct}%`,
                                                transform: "translate(-50%, -50%)",
                                                padding: "2px 6px",
                                                borderRadius: 12,
                                                background: "#f9f0ff",
                                                border: "1.5px dashed #722ed1",
                                                fontSize: 11,
                                                fontWeight: 600,
                                                pointerEvents: "none",
                                                zIndex: 21,
                                            }}
                                        >
                                            {cp.icon_emoji} {cp.name}
                                        </div>
                                    ))}

                            {/* Live Persona Icon Avatars with Top Agent Name & Smooth CSS Transition */}
                            {mode === "live" &&
                                positionedAgents.map(({ agent, renderX, renderY }) => {
                                    const mv = MOVEMENT_BADGE_META[agent.movement_status || "idle"] || MOVEMENT_BADGE_META.moving;
                                    const isBql = agent.group_type === "BQL";
                                    const hasInc = (agent.incidents_open_count || 0) > 0;
                                    const iconEmoji = resolveAgentIconFE(agent);
                                    const shortName = formatShortAgentName(agent.full_name, agent.agent_id);
                                    return (
                                        <Tooltip
                                            key={`agent-live-${agent.agent_id}`}
                                            title={
                                                <div>
                                                    <div><strong>{iconEmoji} #{agent.agent_id} {agent.full_name}</strong> ({agent.role_title})</div>
                                                    <div>Vị trí: {agent.current_checkpoint_name || agent.current_zone} ({renderX.toFixed(1)}%, {renderY.toFixed(1)}%)</div>
                                                    {agent.current_activity && <div>Hoạt động: {agent.current_activity}</div>}
                                                    <div style={{ color: "#91caff" }}>Bấm để mở Timeline chi tiết</div>
                                                </div>
                                            }
                                        >
                                            <div
                                                data-testid={`live-agent-marker-${agent.agent_id}`}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onOpenAgentTimeline?.(agent.agent_id);
                                                }}
                                                style={{
                                                    position: "absolute",
                                                    left: `${renderX}%`,
                                                    top: `${renderY}%`,
                                                    transform: "translate(-50%, -50%)",
                                                    transition:
                                                        "left 900ms cubic-bezier(0.22, 1, 0.36, 1), top 900ms cubic-bezier(0.22, 1, 0.36, 1)",
                                                    pointerEvents: "auto",
                                                    cursor: "pointer",
                                                    display: "flex",
                                                    flexDirection: "column",
                                                    alignItems: "center",
                                                    zIndex: 20,
                                                    minWidth: 32,
                                                    minHeight: 32,
                                                }}
                                            >
                                                {showAgentNames && (
                                                    <span
                                                        data-testid={`live-agent-name-${agent.agent_id}`}
                                                        style={{
                                                            marginBottom: 2,
                                                            padding: "1px 5px",
                                                            borderRadius: 6,
                                                            background: isBql ? "rgba(22, 119, 255, 0.92)" : "rgba(114, 46, 209, 0.92)",
                                                            color: "#ffffff",
                                                            fontSize: isMobile ? 8.5 : 9.5,
                                                            fontWeight: 600,
                                                            lineHeight: 1.25,
                                                            maxWidth: isMobile ? 74 : 96,
                                                            whiteSpace: "nowrap",
                                                            overflow: "hidden",
                                                            textOverflow: "ellipsis",
                                                            boxShadow: "0 1px 4px rgba(15,23,42,0.28)",
                                                            pointerEvents: "none",
                                                        }}
                                                    >
                                                        {shortName}
                                                    </span>
                                                )}
                                                <div
                                                    data-testid={`live-agent-icon-${agent.agent_id}`}
                                                    style={{
                                                        position: "relative",
                                                        width: isMobile ? 28 : 32,
                                                        height: isMobile ? 28 : 32,
                                                        borderRadius: "50%",
                                                        background: isBql ? "#eff6ff" : "#faf5ff",
                                                        border: hasInc ? "2.5px solid #ff4d4f" : `2.5px solid ${mv.color}`,
                                                        fontSize: isMobile ? 16 : 18,
                                                        display: "flex",
                                                        alignItems: "center",
                                                        justifyContent: "center",
                                                        boxShadow: "0 2px 8px rgba(0,0,0,0.28)",
                                                    }}
                                                >
                                                    <span aria-hidden="true">{iconEmoji}</span>
                                                    <span
                                                        style={{
                                                            position: "absolute",
                                                            right: -4,
                                                            bottom: -3,
                                                            minWidth: 14,
                                                            height: 14,
                                                            padding: "0 2px",
                                                            borderRadius: 7,
                                                            background: isBql ? "#1677ff" : "#722ed1",
                                                            color: "#ffffff",
                                                            fontSize: 8.5,
                                                            fontWeight: 700,
                                                            display: "flex",
                                                            alignItems: "center",
                                                            justifyContent: "center",
                                                            border: "1px solid #ffffff",
                                                        }}
                                                    >
                                                        {agent.agent_id}
                                                    </span>
                                                </div>
                                                {agent.current_activity && !isMobile && (
                                                    <span
                                                        style={{
                                                            marginTop: 2,
                                                            padding: "0 4px",
                                                            borderRadius: 4,
                                                            background: "rgba(15,23,42,0.82)",
                                                            color: "#ffffff",
                                                            fontSize: 9,
                                                            maxWidth: 96,
                                                            whiteSpace: "nowrap",
                                                            overflow: "hidden",
                                                            textOverflow: "ellipsis",
                                                            pointerEvents: "none",
                                                        }}
                                                    >
                                                        {agent.current_activity}
                                                    </span>
                                                )}
                                            </div>
                                        </Tooltip>
                                    );
                                })}

                            {/* Floating Quick-Action Bar right above Selected Zone in Edit Mode */}
                            {mode === "edit" &&
                                editTool === "select" &&
                                !isDragging &&
                                selectedZoneObj &&
                                selectedZoneObj.id &&
                                localPolygons[selectedZoneObj.id]?.length >= 3 && (() => {
                                    const box = computePolygonBBox(localPolygons[selectedZoneObj.id]);
                                    const barX = clampPct((box.minX + box.maxX) / 2, 18, 82);
                                    const placeAbove = box.minY > 14;
                                    const barY = placeAbove ? Math.max(2, box.minY - 2) : Math.min(92, box.maxY + 2);
                                    const card = toZoneTopologyCard(selectedZoneObj);
                                    return (
                                        <div
                                            data-testid="canvas-zone-floating-bar"
                                            onPointerDown={(e) => e.stopPropagation()}
                                            onClick={(e) => e.stopPropagation()}
                                            style={{
                                                position: "absolute",
                                                left: `${barX}%`,
                                                top: `${barY}%`,
                                                transform: placeAbove ? "translate(-50%, -100%)" : "translate(-50%, 0)",
                                                background: "#ffffff",
                                                border: "1px solid #cbd5e1",
                                                borderRadius: 8,
                                                padding: "4px 6px",
                                                boxShadow: "0 4px 12px rgba(15,23,42,0.16)",
                                                display: "flex",
                                                alignItems: "center",
                                                gap: 4,
                                                pointerEvents: "auto",
                                                whiteSpace: "nowrap",
                                                zIndex: 40,
                                            }}
                                        >
                                            {onEditZoneDetails && (
                                                <Button
                                                    size="small"
                                                    type="text"
                                                    icon={<EditOutlined />}
                                                    onClick={() => onEditZoneDetails(card)}
                                                >
                                                    Sửa
                                                </Button>
                                            )}
                                            {onAssignZonePersonas && (
                                                <Button
                                                    size="small"
                                                    type="text"
                                                    icon={<UserAddOutlined />}
                                                    onClick={() => onAssignZonePersonas(card)}
                                                >
                                                    Gắn người
                                                </Button>
                                            )}
                                            <Popover
                                                trigger="click"
                                                title="Chọn màu Khu vực"
                                                content={
                                                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", maxWidth: 168 }}>
                                                        {ZONE_COLORS.map((hex) => (
                                                            <button
                                                                key={hex}
                                                                type="button"
                                                                aria-label={`Đổi màu ${hex}`}
                                                                onClick={() => {
                                                                    void urbanSimApi
                                                                        .updateZone(projectId, selectedZoneObj.id!, { fill_color: hex })
                                                                        .then(() => {
                                                                            message.success("Đã đổi màu Khu vực.");
                                                                            onRefreshMap?.();
                                                                        })
                                                                        .catch((err) =>
                                                                            message.error(
                                                                                err instanceof Error ? err.message : "Đổi màu thất bại"
                                                                            )
                                                                        );
                                                                }}
                                                                style={{
                                                                    width: 22,
                                                                    height: 22,
                                                                    borderRadius: "50%",
                                                                    background: hex,
                                                                    border:
                                                                        selectedZoneObj.fill_color === hex
                                                                            ? "2px solid #0f172a"
                                                                            : "1px solid #cbd5e1",
                                                                    cursor: "pointer",
                                                                }}
                                                            />
                                                        ))}
                                                    </div>
                                                }
                                            >
                                                <Button size="small" type="text" icon={<BgColorsOutlined />}>
                                                    Màu
                                                </Button>
                                            </Popover>
                                            {onDeleteZone && (
                                                <Button
                                                    size="small"
                                                    type="text"
                                                    danger
                                                    icon={<DeleteOutlined />}
                                                    onClick={() => onDeleteZone(card)}
                                                >
                                                    Xóa
                                                </Button>
                                            )}
                                        </div>
                                    );
                                })()}

                            {/* Floating Quick-Action Bar right above Selected Checkpoint */}
                            {mode === "edit" &&
                                editTool === "select" &&
                                !isDragging &&
                                selectedCpObj && (() => {
                                    const coords = localCpCoords[selectedCpObj.id] || [selectedCpObj.x_pct, selectedCpObj.y_pct];
                                    const placeAbove = coords[1] > 15;
                                    const barY = placeAbove ? Math.max(2, coords[1] - 4.5) : Math.min(92, coords[1] + 4.5);
                                    return (
                                        <div
                                            data-testid="canvas-cp-floating-bar"
                                            onPointerDown={(e) => e.stopPropagation()}
                                            onClick={(e) => e.stopPropagation()}
                                            style={{
                                                position: "absolute",
                                                left: `${clampPct(coords[0], 16, 84)}%`,
                                                top: `${barY}%`,
                                                transform: placeAbove ? "translate(-50%, -100%)" : "translate(-50%, 0)",
                                                background: "#ffffff",
                                                border: "1px solid #cbd5e1",
                                                borderRadius: 8,
                                                padding: "4px 6px",
                                                boxShadow: "0 4px 12px rgba(15,23,42,0.16)",
                                                display: "flex",
                                                alignItems: "center",
                                                gap: 4,
                                                pointerEvents: "auto",
                                                whiteSpace: "nowrap",
                                                zIndex: 40,
                                            }}
                                        >
                                            <Button
                                                size="small"
                                                type="text"
                                                icon={<EditOutlined />}
                                                onClick={() => openCpModal(selectedCpObj)}
                                            >
                                                Sửa chốt
                                            </Button>
                                            <Popconfirm
                                                title={`Xóa chốt "${selectedCpObj.name}"?`}
                                                okText="Xóa"
                                                cancelText="Hủy"
                                                onConfirm={() => void handleDeleteCheckpoint(selectedCpObj.id)}
                                            >
                                                <Button size="small" type="text" danger icon={<DeleteOutlined />}>
                                                    Xóa
                                                </Button>
                                            </Popconfirm>
                                        </div>
                                    );
                                })()}
                        </div>
                    </div>
                </div>
            </div>

            {/* Selected Khu vực / Checkpoint Property Bar in Edit Mode */}
            {mode === "edit" && selectedZoneObj && selectedZoneObj.id && (
                <Card size="small" bodyStyle={{ padding: "8px 12px" }}>
                    <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                        <Space wrap>
                            <EnvironmentOutlined />
                            <Text strong>{selectedZoneObj.name}</Text>
                            <Tag>{selectedZoneObj.zone_key}</Tag>
                            <Tag color="blue">{(localPolygons[selectedZoneObj.id] || []).length} đỉnh</Tag>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                Kéo hình để di chuyển · Kéo 4 góc xanh đậm để phóng/thu · Kéo đỉnh để nắn · Double-click để sửa (Tự động lưu)
                            </Text>
                        </Space>
                        <Space wrap>
                            {onAssignZonePersonas && (
                                <Button
                                    size="small"
                                    icon={<UserAddOutlined />}
                                    onClick={() => onAssignZonePersonas(toZoneTopologyCard(selectedZoneObj))}
                                >
                                    Gắn Nhân sự &amp; Cư dân
                                </Button>
                            )}
                            {onEditZoneDetails && (
                                <Button
                                    size="small"
                                    icon={<EditOutlined />}
                                    onClick={() => onEditZoneDetails(toZoneTopologyCard(selectedZoneObj))}
                                >
                                    Sửa chi tiết Khu vực
                                </Button>
                            )}
                            <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                disabled={(localPolygons[selectedZoneObj.id] || []).length <= 3}
                                onClick={() => {
                                    const pts = localPolygons[selectedZoneObj.id!] || [];
                                    if (pts.length > 3) {
                                        handleDeleteVertex(selectedZoneObj.id!, pts.length - 1);
                                    }
                                }}
                            >
                                Xóa đỉnh cuối
                            </Button>
                        </Space>
                    </Space>
                </Card>
            )}

            {mode === "edit" && selectedCpObj && (
                <Card size="small" bodyStyle={{ padding: "8px 12px" }}>
                    <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                        <Space wrap>
                            <span>{selectedCpObj.icon_emoji}</span>
                            <Text strong>{selectedCpObj.name}</Text>
                            <Tag>{selectedCpObj.checkpoint_key}</Tag>
                            <Tag color="blue">{liveCheckpointZoneKey(selectedCpObj) || "Ngoài Khu vực"}</Tag>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                Tọa độ: {(localCpCoords[selectedCpObj.id]?.[0] ?? selectedCpObj.x_pct).toFixed(1)}%,{" "}
                                {(localCpCoords[selectedCpObj.id]?.[1] ?? selectedCpObj.y_pct).toFixed(1)}%
                            </Text>
                        </Space>
                        <Space wrap>
                            <Button size="small" icon={<EditOutlined />} onClick={() => openCpModal(selectedCpObj)}>
                                Sửa Chốt &amp; Markdown
                            </Button>
                            <Popconfirm
                                title={`Xóa chốt "${selectedCpObj.name}"?`}
                                okText="Xóa"
                                cancelText="Hủy"
                                onConfirm={() => void handleDeleteCheckpoint(selectedCpObj.id)}
                            >
                                <Button size="small" danger icon={<DeleteOutlined />}>Xóa chốt</Button>
                            </Popconfirm>
                        </Space>
                    </Space>
                </Card>
            )}

            {/* Live Recent Movement Ticker */}
            {mode === "live" && recentMovements.length > 0 && (
                <Card size="small" title={`Nhật ký Di chuyển Trực quan gần nhất (${recentMovements.length})`}>
                    <div style={{ maxHeight: 150, overflowY: "auto" }}>
                        {recentMovements.slice(0, 10).map((mv) => (
                            <div
                                key={`mv-${mv.seq}`}
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    padding: "3px 0",
                                    borderBottom: "1px dashed #f0f0f0",
                                    fontSize: 12,
                                }}
                            >
                                <Space size={6} wrap>
                                    <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>#{mv.agent_id}</Tag>
                                    <Text>{mv.summary}</Text>
                                </Space>
                                <Button
                                    type="link"
                                    size="small"
                                    style={{ padding: 0 }}
                                    onClick={() => onOpenAgentTimeline?.(mv.agent_id)}
                                >
                                    Timeline
                                </Button>
                            </div>
                        ))}
                    </div>
                </Card>
            )}

            {/* Modal 1: Name Newly Drawn Polygon Zone */}
            <Modal
                title="Lưu Khu vực Polygon vừa vẽ"
                open={drawZoneModalOpen}
                destroyOnHidden
                onCancel={() => setDrawZoneModalOpen(false)}
                onOk={() => drawZoneForm.submit()}
                confirmLoading={creatingDrawnZone}
                okText="Lưu thành Khu vực"
                cancelText="Hủy"
            >
                <Form form={drawZoneForm} layout="vertical" onFinish={(vals) => void handleSaveDrawnZone(vals)}>
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Form.Item name="zone_key" label="Mã khu vực" rules={[{ required: true }]}>
                                <Input placeholder="vd: KHU_THE_THAO" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="name" label="Tên khu vực" rules={[{ required: true }]}>
                                <Input placeholder="vd: Khu Thể thao & Bể bơi" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={16}>
                            <Form.Item name="zone_type" label="Loại khu vực" rules={[{ required: true }]}>
                                <Select options={ZONE_TYPE_OPTIONS} />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item name="fill_color" label="Màu Polygon">
                                <Input type="color" />
                            </Form.Item>
                        </Col>
                    </Row>
                    <Form.Item name="description" label="Mô tả khu vực">
                        <TextArea rows={2} maxLength={240} />
                    </Form.Item>
                    <Form.Item name="ambient_signals" label="Tín hiệu động (ambient_signals)">
                        <TextArea rows={3} maxLength={2000} />
                    </Form.Item>
                </Form>
            </Modal>

            {/* Modal 2: Point-Center + Prompt AI Polygon */}
            <Modal
                title={`Sinh Polygon Khu vực từ Điểm tâm (${clickedPoint[0].toFixed(1)}%, ${clickedPoint[1].toFixed(1)}%)`}
                open={pointModalOpen}
                destroyOnHidden
                width={640}
                onCancel={() => setPointModalOpen(false)}
                footer={[
                    <Button key="cancel" onClick={() => setPointModalOpen(false)}>Đóng</Button>,
                    <Button
                        key="gen"
                        icon={<RobotOutlined />}
                        loading={pointGenLoading}
                        onClick={() => void handleGenerateFromPoint()}
                    >
                        {pointDraft ? "Sinh lại" : "AI Sinh Polygon"}
                    </Button>,
                    <Button
                        key="save"
                        type="primary"
                        disabled={!pointDraft}
                        loading={pointGenLoading}
                        onClick={() => void handleConfirmPointDraft()}
                    >
                        Lưu thành Khu vực thật
                    </Button>,
                ]}
            >
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <Text type="secondary">
                        Nhập mô tả khu vực quanh điểm bạn vừa chấm trên bản đồ. AI sẽ tự tạo đa giác và thông số ngữ cảnh.
                    </Text>
                    <TextArea
                        rows={3}
                        value={pointPromptText}
                        onChange={(e) => setPointPromptText(e.target.value)}
                        placeholder="vd: Khu bể bơi ngoài trời và sân chơi trẻ em ở phía Tây khuôn viên..."
                    />
                    {pointFallbackInfo && <Alert type="warning" showIcon message={pointFallbackInfo} />}
                    {pointDraft && (
                        <Card size="small" title={`Kết quả dự kiến: ${pointDraft.name} (${pointDraft.zone_key})`}>
                            <Space wrap>
                                <Tag color="blue">{pointDraft.zone_type}</Tag>
                                <Tag>{pointDraft.polygon_points.length} đỉnh Polygon</Tag>
                                <Tag>Tâm: ({pointDraft.center_x_pct}%, {pointDraft.center_y_pct}%)</Tag>
                            </Space>
                            <div style={{ marginTop: 6 }}>{pointDraft.description}</div>
                        </Card>
                    )}
                </Space>
            </Modal>

            {/* Modal 3: AI Generate Full Digital Map */}
            <Modal
                title="AI Tạo Bản đồ Số Khu đô thị (Polygon + Ảnh 2D tùy chọn)"
                open={aiMapModalOpen}
                destroyOnHidden
                width={760}
                onCancel={() => setAiMapModalOpen(false)}
                footer={[
                    <Button key="close" onClick={() => setAiMapModalOpen(false)}>Đóng</Button>,
                    <Button
                        key="gen"
                        icon={<RobotOutlined />}
                        loading={aiMapGenerating}
                        onClick={() => void handleGenerateAiMap()}
                    >
                        Phân tích &amp; Sinh Bản đồ Số
                    </Button>,
                    <Button
                        key="apply"
                        type="primary"
                        disabled={!aiMapDraft}
                        loading={aiMapApplying}
                        onClick={() => void handleApplyAiMap()}
                    >
                        Áp dụng ({aiMapDraft?.zones.length || 0} Khu vực)
                    </Button>,
                ]}
            >
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <TextArea
                        rows={4}
                        value={aiMapPrompt}
                        onChange={(e) => setAiMapPrompt(e.target.value)}
                        placeholder="Mô tả tổng quan bố cục các tháp, sảnh lễ tân, hầm xe, khu kỹ thuật, bể bơi, công viên..."
                    />
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Checkbox
                                checked={aiMapUseImage && hasZoneMapImage}
                                disabled={!hasZoneMapImage}
                                onChange={(e) => setAiMapUseImage(e.target.checked)}
                            >
                                Đọc kèm ảnh mặt bằng 2D đã tải lên ({hasZoneMapImage ? "Có ảnh" : "Chưa có ảnh"})
                            </Checkbox>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Radio.Group
                                value={aiMapApplyMode}
                                onChange={(e) => setAiMapApplyMode(e.target.value)}
                            >
                                <Radio value="MERGE">Gộp &amp; giữ Persona (Khuyên dùng)</Radio>
                                <Radio value="REPLACE">Thay thế toàn bộ</Radio>
                            </Radio.Group>
                        </Col>
                    </Row>
                    {aiMapDraft && (
                        <Alert
                            type={aiMapDraft.used_vision ? "success" : "warning"}
                            showIcon
                            message={`Đã sinh ${aiMapDraft.zones.length} Khu vực Polygon (Chế độ: ${aiMapDraft.used_vision ? "Multimodal Vision" : "Text-only Fallback"})`}
                            description={aiMapDraft.fallback_reason || aiMapDraft.zones.map((z) => z.name).join(" · ")}
                        />
                    )}
                </Space>
            </Modal>

            {/* Modal 4: Create / Edit Checkpoint (Name, Coords, Emoji, MarkdownRichTextEditor) */}
            <Modal
                title={editingCp ? `Chỉnh sửa Chốt: ${editingCp.name}` : "Thêm Chốt / Pin Địa điểm mới"}
                open={cpModalOpen}
                destroyOnHidden
                width={isMobile ? "96vw" : 760}
                onCancel={() => setCpModalOpen(false)}
                onOk={() => cpForm.submit()}
                confirmLoading={savingCp}
                okText={editingCp ? "Lưu chốt" : "Tạo chốt"}
                cancelText="Hủy"
            >
                <Form form={cpForm} layout="vertical" onFinish={(vals) => void handleSaveCheckpoint(vals)}>
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Form.Item name="name" label="Tên chốt / địa điểm" rules={[{ required: true, message: "Nhập tên chốt" }]}>
                                <Input placeholder="vd: Cổng An ninh Chính" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="checkpoint_key" label="Mã chốt (tự chuẩn hóa nếu bỏ trống)">
                                <Input placeholder="vd: CP_GATE_MAIN" />
                            </Form.Item>
                        </Col>
                        <Col xs={12} sm={6}>
                            <Form.Item name="x_pct" label="Tọa độ X (%)" rules={[{ required: true }]}>
                                <InputNumber min={0.5} max={99.5} step={0.5} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                        <Col xs={12} sm={6}>
                            <Form.Item name="y_pct" label="Tọa độ Y (%)" rules={[{ required: true }]}>
                                <InputNumber min={0.5} max={99.5} step={0.5} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item name="category" label="Nhóm chức năng">
                                <Select options={CHECKPOINT_CATEGORY_OPTIONS} />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={24}>
                            <Form.Item name="icon_emoji" label="Icon Emoji">
                                <Input style={{ width: 120 }} />
                            </Form.Item>
                            <Space wrap size={4} style={{ marginTop: -8, marginBottom: 12 }}>
                                {QUICK_EMOJIS.map((em) => (
                                    <Button
                                        key={em}
                                        size="small"
                                        onClick={() => cpForm.setFieldValue("icon_emoji", em)}
                                    >
                                        {em}
                                    </Button>
                                ))}
                            </Space>
                        </Col>
                        <Col xs={24} sm={24}>
                            <Form.Item name="description_md" label="Mô tả nghiệp vụ / quy chuẩn tại chốt (Markdown)">
                                <MarkdownRichTextEditor
                                    minRows={5}
                                    maxRows={12}
                                    defaultMode="split"
                                    modalTitle="Soạn thảo Mô tả Chốt / Địa điểm (Markdown RichText)"
                                />
                            </Form.Item>
                        </Col>
                    </Row>
                </Form>
            </Modal>

            {/* Modal 5: AI Batch Generate Checkpoints */}
            <Modal
                title="AI Sinh Danh sách Chốt / Pin từ Prompt Mô tả"
                open={aiCpModalOpen}
                destroyOnHidden
                width={isMobile ? "96vw" : 780}
                onCancel={() => setAiCpModalOpen(false)}
                footer={[
                    <Button key="close" onClick={() => setAiCpModalOpen(false)}>Đóng</Button>,
                    <Button
                        key="gen"
                        icon={<RobotOutlined />}
                        loading={aiCpGenerating}
                        onClick={() => void handleGenerateAiCheckpoints()}
                    >
                        {aiCpDrafts.length > 0 ? "Sinh lại" : "AI Sinh Chốt"}
                    </Button>,
                    <Button
                        key="apply"
                        type="primary"
                        disabled={aiCpDrafts.filter((c) => c.selected).length === 0}
                        loading={aiCpApplying}
                        onClick={() => void handleApplyAiCheckpoints()}
                    >
                        Lưu {aiCpDrafts.filter((c) => c.selected).length} Chốt đã chọn
                    </Button>,
                ]}
            >
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <TextArea
                        rows={3}
                        value={aiCpPrompt}
                        onChange={(e) => setAiCpPrompt(e.target.value)}
                        placeholder="vd: Tạo các chốt tuần tra an ninh (cổng chính, hầm B1), kiểm tra kỹ thuật/vệ sinh và các tiện ích cư dân (bể bơi, gym, sân chơi trẻ em, vườn BBQ)..."
                    />
                    {aiCpFallbackInfo && <Alert type="warning" showIcon message={aiCpFallbackInfo} />}
                    {aiCpDrafts.length > 0 && (
                        <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid #f0f0f0", borderRadius: 6, padding: 8 }}>
                            {aiCpDrafts.map((cp, idx) => (
                                <div
                                    key={cp.checkpoint_key}
                                    style={{
                                        display: "flex",
                                        alignItems: "flex-start",
                                        gap: 8,
                                        padding: "6px 4px",
                                        borderBottom: "1px dashed #f0f0f0",
                                    }}
                                >
                                    <Checkbox
                                        checked={cp.selected}
                                        onChange={(e) =>
                                            setAiCpDrafts((prev) =>
                                                prev.map((item, i) =>
                                                    i === idx ? { ...item, selected: e.target.checked } : item
                                                )
                                            )
                                        }
                                    />
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <Space wrap size={4}>
                                            <span>{cp.icon_emoji}</span>
                                            <Text strong>{cp.name}</Text>
                                            <Tag>{cp.checkpoint_key}</Tag>
                                            <Tag color="blue">{cp.zone_key || "Tự do"}</Tag>
                                            <Text type="secondary" style={{ fontSize: 11 }}>
                                                ({cp.x_pct}%, {cp.y_pct}%)
                                            </Text>
                                        </Space>
                                        {cp.description_md && (
                                            <Text type="secondary" style={{ fontSize: 12, display: "block" }}>
                                                {cp.description_md.slice(0, 140)}
                                            </Text>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </Space>
            </Modal>

            {/* Mobile (<768px) Bottom Drawers for Live Checkpoint & Zone Inspection */}
            <Drawer
                placement="bottom"
                height="62vh"
                open={Boolean(liveMobileCp)}
                onClose={() => setLiveMobileCp(null)}
                title={
                    liveMobileCp && (
                        <Space>
                            <span>{liveMobileCp.icon_emoji}</span>
                            <span>{liveMobileCp.name}</span>
                        </Space>
                    )
                }
            >
                {liveMobileCp && (
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                        <Space wrap>
                            <Tag>{liveMobileCp.checkpoint_key}</Tag>
                            <Tag color="blue">{liveMobileCp.zone_key || "Ngoài Khu vực"}</Tag>
                            <Tag>({liveMobileCp.x_pct}%, {liveMobileCp.y_pct}%)</Tag>
                        </Space>
                        <MarkdownWithMermaid content={liveMobileCp.description_md || "Chưa có mô tả chi tiết."} />
                        {liveMobileCp.agents_here && liveMobileCp.agents_here.length > 0 && (
                            <div>
                                <Text strong>Tác nhân đang tại chốt:</Text>
                                <div style={{ marginTop: 6 }}>
                                    {liveMobileCp.agents_here.map((a) => (
                                        <Tag
                                            key={a.agent_id}
                                            color={a.group_type === "BQL" ? "blue" : "purple"}
                                            style={{ marginBottom: 4, cursor: "pointer" }}
                                            onClick={() => {
                                                setLiveMobileCp(null);
                                                onOpenAgentTimeline?.(a.agent_id);
                                            }}
                                        >
                                            #{a.agent_id} {a.full_name}
                                        </Tag>
                                    ))}
                                </div>
                            </div>
                        )}
                    </Space>
                )}
            </Drawer>

            <Drawer
                placement="bottom"
                height="50vh"
                open={Boolean(liveMobileZone)}
                onClose={() => setLiveMobileZone(null)}
                title={
                    liveMobileZone && (
                        <Space>
                            <ApartmentOutlined />
                            <span>{liveMobileZone.name}</span>
                        </Space>
                    )
                }
            >
                {liveMobileZone && (
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                        <Tag>{liveMobileZone.zone_key}</Tag>
                        <Text>{liveMobileZone.description}</Text>
                        <Text strong>Tác nhân đang hiện diện ({liveMobileZone.agents_here.length}):</Text>
                        <Space wrap>
                            {liveMobileZone.agents_here.map((ag) => (
                                <Tag
                                    key={ag.agent_id}
                                    color={ag.group_type === "BQL" ? "blue" : "purple"}
                                    style={{ cursor: "pointer" }}
                                    onClick={() => {
                                        setLiveMobileZone(null);
                                        onOpenAgentTimeline?.(ag.agent_id);
                                    }}
                                >
                                    #{ag.agent_id} {ag.full_name}
                                </Tag>
                            ))}
                        </Space>
                    </Space>
                )}
            </Drawer>
        </Space>
    );
};
export default DigitalUrbanMapCanvas;
