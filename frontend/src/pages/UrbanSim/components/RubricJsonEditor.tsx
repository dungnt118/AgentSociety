import {
    CodeOutlined,
    DeleteOutlined,
    DownloadOutlined,
    EditOutlined,
    FileAddOutlined,
    FormatPainterOutlined,
    PlusOutlined,
    QuestionCircleOutlined,
    RotateLeftOutlined,
    SnippetsOutlined,
    TableOutlined,
    UploadOutlined,
} from "@ant-design/icons";
import {
    Alert,
    AutoComplete,
    Button,
    Col,
    Form,
    Input,
    InputNumber,
    Modal,
    Popconfirm,
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
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
    CompetencyRubricData,
    RubricQuizQuestion,
    RubricRoleRule,
    urbanSimApi,
} from "../../../services/urbanSimApi";

const { Text, Paragraph } = Typography;

const MAX_RUBRIC_BYTES = 64 * 1024;

const FALLBACK_MINIMAL_RUBRIC: CompetencyRubricData = {
    version: "1.0",
    roles: {
        BQL_STAFF: {
            role_code: "BQL_STAFF",
            label: "Nhân sự BQL (Mặc định dự phòng)",
            interaction_mode: "write_ops",
            target_url_patterns: ["/ext/incidents", "/ext/internal-tasks"],
            expected_min_steps: 3,
            min_actions_for_lostness: 3,
            expected_target_modules_for_m3: 2,
        },
    },
    quiz_questions: [],
};

const EMPTY_CUSTOM_RUBRIC: CompetencyRubricData = {
    version: "1.0",
    roles: {},
    quiz_questions: [],
};

const STANDARD_ROLE_SUGGESTIONS: Array<{ role_code: string; role_title: string }> = [
    { role_code: "BQL_DIRECTOR", role_title: "Giám đốc Dự án" },
    { role_code: "BQL_ASSISTANT", role_title: "Trợ lý Dự án" },
    { role_code: "BQL_RECEPTIONIST", role_title: "Lễ tân BQL" },
    { role_code: "BQL_ACCOUNTANT", role_title: "Kế toán Công nợ & Phí dịch vụ" },
    { role_code: "SEC_LEAD", role_title: "Tổ trưởng Bảo vệ" },
    { role_code: "SEC_STAFF", role_title: "Nhân viên Bảo vệ" },
    { role_code: "ENG_LEAD", role_title: "Tổ trưởng Kỹ thuật" },
    { role_code: "ENG_STAFF", role_title: "Nhân viên Kỹ thuật" },
    { role_code: "BQL_STAFF", role_title: "Fallback cho vai trò chưa định nghĩa" },
];

let cachedDefaultRubric: CompetencyRubricData | null = null;

export interface SuggestedRoleItem {
    role_code: string;
    role_title?: string;
}

export interface RubricJsonEditorProps {
    id?: string;
    value?: string | null;
    onChange?: (val: string) => void;
    disabled?: boolean;
    projectSlug?: string;
    suggestedRoles?: SuggestedRoleItem[];
}

interface RoleFormValues {
    role_code: string;
    label: string;
    interaction_mode: "write_ops" | "oversight";
    target_url_patterns: string[];
    expected_min_steps: number;
    min_actions_for_lostness: number;
    expected_target_modules_for_m3: number;
}

interface QuestionFormValues {
    id: string;
    topic: string;
    skill_domain: string;
    prompt_stem: string;
    opt_a: string;
    opt_b: string;
    opt_c: string;
    opt_d: string;
    correct_choice: "OPT_A" | "OPT_B" | "OPT_C" | "OPT_D";
}

function getUtf8ByteLength(text: string): number {
    if (typeof TextEncoder !== "undefined") {
        return new TextEncoder().encode(text).length;
    }
    return text.length * 2;
}

function normalizeRubricData(parsed: Record<string, unknown>): CompetencyRubricData {
    const rolesRaw =
        parsed.roles && typeof parsed.roles === "object" && !Array.isArray(parsed.roles)
            ? (parsed.roles as Record<string, Record<string, unknown>>)
            : {};
    const normalizedRoles: Record<string, RubricRoleRule> = {};
    for (const [key, r] of Object.entries(rolesRaw)) {
        if (!r || typeof r !== "object" || Array.isArray(r)) continue;
        normalizedRoles[key] = {
            role_code: typeof r.role_code === "string" && r.role_code.trim() ? r.role_code : key,
            label: typeof r.label === "string" ? r.label : key,
            interaction_mode: r.interaction_mode === "oversight" ? "oversight" : "write_ops",
            target_url_patterns: Array.isArray(r.target_url_patterns)
                ? r.target_url_patterns.filter((x): x is string => typeof x === "string")
                : [],
            expected_min_steps: Number.isFinite(Number(r.expected_min_steps)) ? Number(r.expected_min_steps) : 3,
            min_actions_for_lostness: Number.isFinite(Number(r.min_actions_for_lostness))
                ? Number(r.min_actions_for_lostness)
                : 3,
            expected_target_modules_for_m3: Number.isFinite(Number(r.expected_target_modules_for_m3))
                ? Number(r.expected_target_modules_for_m3)
                : 2,
        };
    }

    const quizRaw = Array.isArray(parsed.quiz_questions) ? parsed.quiz_questions : [];
    const normalizedQuiz: RubricQuizQuestion[] = [];
    for (const item of quizRaw) {
        if (!item || typeof item !== "object" || Array.isArray(item)) continue;
        const q = item as Record<string, unknown>;
        const opts =
            q.options && typeof q.options === "object" && !Array.isArray(q.options)
                ? (q.options as Record<string, unknown>)
                : {};
        const choice = String(q.correct_choice || "OPT_A");
        const validChoice =
            choice === "OPT_B" || choice === "OPT_C" || choice === "OPT_D" ? choice : "OPT_A";
        normalizedQuiz.push({
            id: String(q.id || ""),
            topic: String(q.topic || ""),
            skill_domain: String(q.skill_domain || ""),
            prompt_stem: String(q.prompt_stem || ""),
            options: {
                OPT_A: String(opts.OPT_A ?? ""),
                OPT_B: String(opts.OPT_B ?? ""),
                OPT_C: String(opts.OPT_C ?? ""),
                OPT_D: String(opts.OPT_D ?? ""),
            },
            correct_choice: validChoice,
        });
    }

    return {
        version: typeof parsed.version === "string" && parsed.version.trim() ? parsed.version : "1.0",
        roles: normalizedRoles,
        quiz_questions: normalizedQuiz,
    };
}

function validateRubricClient(
    raw?: string | null
): {
    valid: boolean;
    error: string | null;
    bytes: number;
    parsed: CompetencyRubricData | null;
} {
    const trimmed = (raw ?? "").trim();
    if (!trimmed) {
        return { valid: true, error: null, bytes: 0, parsed: null };
    }
    const bytes = getUtf8ByteLength(trimmed);
    if (bytes > MAX_RUBRIC_BYTES) {
        return {
            valid: false,
            error: `Kích thước JSON vượt giới hạn 64 KB (hiện tại ${(bytes / 1024).toFixed(1)} KB).`,
            bytes,
            parsed: null,
        };
    }
    let obj: unknown;
    try {
        obj = JSON.parse(trimmed);
    } catch (exc) {
        return {
            valid: false,
            error: `Lỗi cú pháp JSON: ${exc instanceof Error ? exc.message : String(exc)}`,
            bytes,
            parsed: null,
        };
    }
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
        return { valid: false, error: "Rubric phải là một JSON Object ({ ... }).", bytes, parsed: null };
    }
    const rec = obj as Record<string, unknown>;
    if (rec.roles !== undefined && (typeof rec.roles !== "object" || rec.roles === null || Array.isArray(rec.roles))) {
        return {
            valid: false,
            error: 'Trường "roles" phải là Object ánh xạ role_code -> cấu hình vai trò.',
            bytes,
            parsed: null,
        };
    }
    if (rec.roles && typeof rec.roles === "object") {
        for (const [k, v] of Object.entries(rec.roles as Record<string, unknown>)) {
            if (!v || typeof v !== "object" || Array.isArray(v)) {
                return { valid: false, error: `roles["${k}"] phải là Object.`, bytes, parsed: null };
            }
            const r = v as Record<string, unknown>;
            if (typeof r.role_code !== "string" || !r.role_code.trim()) {
                return { valid: false, error: `roles["${k}"].role_code không được để trống.`, bytes, parsed: null };
            }
            if (typeof r.label !== "string" || !r.label.trim()) {
                return { valid: false, error: `roles["${k}"].label không được để trống.`, bytes, parsed: null };
            }
            if (r.interaction_mode !== "write_ops" && r.interaction_mode !== "oversight") {
                return {
                    valid: false,
                    error: `roles["${k}"].interaction_mode phải là "write_ops" hoặc "oversight".`,
                    bytes,
                    parsed: null,
                };
            }
            if (r.target_url_patterns !== undefined && !Array.isArray(r.target_url_patterns)) {
                return {
                    valid: false,
                    error: `roles["${k}"].target_url_patterns phải là mảng chuỗi [].`,
                    bytes,
                    parsed: null,
                };
            }
        }
    }
    if (rec.quiz_questions !== undefined && !Array.isArray(rec.quiz_questions)) {
        return {
            valid: false,
            error: 'Trường "quiz_questions" phải là mảng [] các câu hỏi.',
            bytes,
            parsed: null,
        };
    }
    if (Array.isArray(rec.quiz_questions)) {
        for (let idx = 0; idx < rec.quiz_questions.length; idx += 1) {
            const q = rec.quiz_questions[idx];
            if (!q || typeof q !== "object" || Array.isArray(q)) {
                return { valid: false, error: `quiz_questions[${idx}] phải là Object.`, bytes, parsed: null };
            }
            const qr = q as Record<string, unknown>;
            if (typeof qr.id !== "string" || !qr.id.trim()) {
                return { valid: false, error: `quiz_questions[${idx}].id không được để trống.`, bytes, parsed: null };
            }
            if (typeof qr.topic !== "string" || !qr.topic.trim()) {
                return { valid: false, error: `quiz_questions[${idx}].topic không được để trống.`, bytes, parsed: null };
            }
            if (typeof qr.skill_domain !== "string" || !qr.skill_domain.trim()) {
                return {
                    valid: false,
                    error: `quiz_questions[${idx}].skill_domain không được để trống.`,
                    bytes,
                    parsed: null,
                };
            }
            if (typeof qr.prompt_stem !== "string" || qr.prompt_stem.trim().length < 10) {
                return {
                    valid: false,
                    error: `quiz_questions[${idx}].prompt_stem phải dài tối thiểu 10 ký tự.`,
                    bytes,
                    parsed: null,
                };
            }
            const opts = qr.options as Record<string, unknown> | undefined;
            if (!opts || typeof opts !== "object" || Array.isArray(opts)) {
                return {
                    valid: false,
                    error: `quiz_questions[${idx}].options phải có đủ OPT_A..OPT_D.`,
                    bytes,
                    parsed: null,
                };
            }
            for (const key of ["OPT_A", "OPT_B", "OPT_C", "OPT_D"]) {
                if (typeof opts[key] !== "string" || !(opts[key] as string).trim()) {
                    return {
                        valid: false,
                        error: `quiz_questions[${idx}].options.${key} không được để trống.`,
                        bytes,
                        parsed: null,
                    };
                }
            }
            if (!["OPT_A", "OPT_B", "OPT_C", "OPT_D"].includes(String(qr.correct_choice ?? ""))) {
                return {
                    valid: false,
                    error: `quiz_questions[${idx}].correct_choice phải thuộc OPT_A..OPT_D.`,
                    bytes,
                    parsed: null,
                };
            }
        }
    }
    return {
        valid: true,
        error: null,
        bytes,
        parsed: normalizeRubricData(rec),
    };
}

export const RubricJsonEditor: React.FC<RubricJsonEditorProps> = ({
    id,
    value,
    onChange,
    disabled,
    projectSlug,
    suggestedRoles = [],
}) => {
    const [mode, setMode] = useState<"visual" | "json">("visual");
    const [guideOpen, setGuideOpen] = useState(false);
    const [defaultRubric, setDefaultRubric] = useState<CompetencyRubricData>(
        cachedDefaultRubric || FALLBACK_MINIMAL_RUBRIC
    );
    const [loadingDefault, setLoadingDefault] = useState<boolean>(!cachedDefaultRubric);

    // Role CRUD Modal state
    const [roleModalOpen, setRoleModalOpen] = useState(false);
    const [editingRoleKey, setEditingRoleKey] = useState<string | null>(null);
    const [roleForm] = Form.useForm<RoleFormValues>();

    // Question CRUD Modal state
    const [questionModalOpen, setQuestionModalOpen] = useState(false);
    const [editingQuestionIdx, setEditingQuestionIdx] = useState<number | null>(null);
    const [questionForm] = Form.useForm<QuestionFormValues>();

    const fileInputRef = useRef<HTMLInputElement | null>(null);

    useEffect(() => {
        if (cachedDefaultRubric) return;
        let active = true;
        urbanSimApi
            .getDefaultRubric()
            .then((data) => {
                if (!active || !data) return;
                cachedDefaultRubric = data;
                setDefaultRubric(data);
            })
            .catch(() => {
                // Giữ fallback tối thiểu nếu backend chưa phản hồi
            })
            .finally(() => {
                if (active) setLoadingDefault(false);
            });
        return () => {
            active = false;
        };
    }, []);

    const rawText = value ?? "";
    const isEmpty = !rawText.trim();
    const validation = useMemo(() => validateRubricClient(rawText), [rawText]);
    const effectiveMode: "visual" | "json" = !isEmpty && !validation.valid ? "json" : mode;

    const defaultRoleCount = Object.keys(defaultRubric.roles).length;
    const defaultQuizCount = defaultRubric.quiz_questions.length;

    const effectiveRubric: CompetencyRubricData = useMemo(() => {
        if (isEmpty) return defaultRubric;
        if (validation.valid && validation.parsed) return validation.parsed;
        return EMPTY_CUSTOM_RUBRIC;
    }, [isEmpty, validation.valid, validation.parsed, defaultRubric]);

    const commitRubric = (next: CompetencyRubricData) => {
        const serialized = JSON.stringify(next, null, 2);
        const bytes = getUtf8ByteLength(serialized);
        if (bytes > MAX_RUBRIC_BYTES) {
            message.error(
                `Không thể lưu vì kích thước vượt 64 KB (${(bytes / 1024).toFixed(1)} KB). Vui lòng rút gọn bớt mẫu URL hoặc câu hỏi.`
            );
            return false;
        }
        onChange?.(serialized);
        return true;
    };

    const handleModeChange = (nextMode: string | number) => {
        const target = nextMode === "json" ? "json" : "visual";
        if (target === "visual" && !isEmpty && !validation.valid) {
            message.error(
                validation.error || "Mã nguồn JSON đang có lỗi. Vui lòng sửa hợp lệ trước khi chuyển sang Trực quan."
            );
            return;
        }
        setMode(target);
    };

    const handleLoadDefaultTemplate = () => {
        if (commitRubric(defaultRubric)) {
            message.success(
                `Đã nạp chuẩn mặc định MulberryLane (${defaultRoleCount} vai trò & ${defaultQuizCount} câu hỏi) để tùy chỉnh.`
            );
        }
    };

    const handleCreateEmptyCustom = () => {
        if (commitRubric(EMPTY_CUSTOM_RUBRIC)) {
            message.info("Đã tạo khung Rubric trống cho hệ thống mới. Bạn có thể thêm vai trò và câu hỏi ngay bên dưới.");
        }
    };

    const handleResetToDefault = () => {
        onChange?.("");
        message.info("Đã khôi phục về mặc định MulberryLane (DB lưu trống).");
    };

    const handleFormatJson = () => {
        if (!validation.valid || !validation.parsed) {
            message.error("JSON chưa hợp lệ nên chưa thể định dạng.");
            return;
        }
        onChange?.(JSON.stringify(validation.parsed, null, 2));
    };

    const handleExportJson = () => {
        const dataToExport = !isEmpty && validation.valid && validation.parsed ? validation.parsed : defaultRubric;
        const formatted = JSON.stringify(dataToExport, null, 2);
        const blob = new Blob([formatted], { type: "application/json;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const safeSlug = (projectSlug || "project").replace(/[^a-zA-Z0-9_-]/g, "_");
        const a = document.createElement("a");
        a.href = url;
        a.download = `rubric-${safeSlug}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        message.success(`Đã xuất tệp rubric-${safeSlug}.json`);
    };

    const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        if (file.size > MAX_RUBRIC_BYTES) {
            message.error(`Tệp vượt quá giới hạn 64 KB (${(file.size / 1024).toFixed(1)} KB).`);
            return;
        }
        try {
            const text = await file.text();
            const check = validateRubricClient(text);
            if (!check.valid || !check.parsed) {
                message.error(check.error || "Tệp JSON không đúng cấu trúc Rubric.");
                return;
            }
            const normalizedText = JSON.stringify(check.parsed, null, 2);
            onChange?.(normalizedText);
            message.success(
                `Đã import thành công "${file.name}" (${Object.keys(check.parsed.roles).length} vai trò, ${check.parsed.quiz_questions.length} câu hỏi).`
            );
        } catch (err) {
            message.error(`Không đọc được tệp JSON: ${err instanceof Error ? err.message : String(err)}`);
        }
    };

    // --- Role Modal handlers ---
    const openCreateRoleModal = () => {
        setEditingRoleKey(null);
        roleForm.setFieldsValue({
            role_code: "",
            label: "",
            interaction_mode: "write_ops",
            target_url_patterns: [],
            expected_min_steps: 3,
            min_actions_for_lostness: 3,
            expected_target_modules_for_m3: 2,
        });
        setRoleModalOpen(true);
    };

    const openEditRoleModal = (key: string, rule: RubricRoleRule) => {
        setEditingRoleKey(key);
        roleForm.setFieldsValue({
            role_code: rule.role_code || key,
            label: rule.label,
            interaction_mode: rule.interaction_mode,
            target_url_patterns: rule.target_url_patterns || [],
            expected_min_steps: rule.expected_min_steps ?? 3,
            min_actions_for_lostness: rule.min_actions_for_lostness ?? 3,
            expected_target_modules_for_m3: rule.expected_target_modules_for_m3 ?? 2,
        });
        setRoleModalOpen(true);
    };

    const handleSaveRole = (values: RoleFormValues) => {
        const cleanCode = values.role_code.trim();
        const nextRoles = { ...(validation.parsed?.roles || {}) };
        if (editingRoleKey && editingRoleKey !== cleanCode) {
            delete nextRoles[editingRoleKey];
        }
        nextRoles[cleanCode] = {
            role_code: cleanCode,
            label: values.label.trim(),
            interaction_mode: values.interaction_mode,
            target_url_patterns: (values.target_url_patterns || []).map((s) => s.trim()).filter(Boolean),
            expected_min_steps: Number(values.expected_min_steps) || 3,
            min_actions_for_lostness: Number(values.min_actions_for_lostness) || 3,
            expected_target_modules_for_m3: Number(values.expected_target_modules_for_m3) || 2,
        };
        const nextRubric: CompetencyRubricData = {
            version: validation.parsed?.version || "1.0",
            roles: nextRoles,
            quiz_questions: validation.parsed?.quiz_questions || [],
        };
        if (commitRubric(nextRubric)) {
            setRoleModalOpen(false);
            message.success(editingRoleKey ? `Đã cập nhật vai trò ${cleanCode}` : `Đã thêm vai trò ${cleanCode}`);
        }
    };

    const handleDeleteRole = (key: string) => {
        const nextRoles = { ...(validation.parsed?.roles || {}) };
        delete nextRoles[key];
        const nextRubric: CompetencyRubricData = {
            version: validation.parsed?.version || "1.0",
            roles: nextRoles,
            quiz_questions: validation.parsed?.quiz_questions || [],
        };
        if (commitRubric(nextRubric)) {
            message.info(`Đã xóa vai trò ${key}`);
        }
    };

    // --- Question Modal handlers ---
    const openCreateQuestionModal = () => {
        const existingCount = (validation.parsed?.quiz_questions || []).length;
        setEditingQuestionIdx(null);
        questionForm.setFieldsValue({
            id: `q_custom_${String(existingCount + 1).padStart(2, "0")}`,
            topic: "",
            skill_domain: "NAVIGATION_ARCHITECTURE",
            prompt_stem: "",
            opt_a: "",
            opt_b: "",
            opt_c: "",
            opt_d: "",
            correct_choice: "OPT_A",
        });
        setQuestionModalOpen(true);
    };

    const openEditQuestionModal = (idx: number, q: RubricQuizQuestion) => {
        setEditingQuestionIdx(idx);
        questionForm.setFieldsValue({
            id: q.id,
            topic: q.topic,
            skill_domain: q.skill_domain,
            prompt_stem: q.prompt_stem,
            opt_a: q.options?.OPT_A || "",
            opt_b: q.options?.OPT_B || "",
            opt_c: q.options?.OPT_C || "",
            opt_d: q.options?.OPT_D || "",
            correct_choice: q.correct_choice || "OPT_A",
        });
        setQuestionModalOpen(true);
    };

    const handleSaveQuestion = (values: QuestionFormValues) => {
        const nextList = [...(validation.parsed?.quiz_questions || [])];
        const cleanItem: RubricQuizQuestion = {
            id: values.id.trim(),
            topic: values.topic.trim(),
            skill_domain: values.skill_domain.trim(),
            prompt_stem: values.prompt_stem.trim(),
            options: {
                OPT_A: values.opt_a.trim(),
                OPT_B: values.opt_b.trim(),
                OPT_C: values.opt_c.trim(),
                OPT_D: values.opt_d.trim(),
            },
            correct_choice: values.correct_choice,
        };
        if (editingQuestionIdx !== null && editingQuestionIdx >= 0 && editingQuestionIdx < nextList.length) {
            nextList[editingQuestionIdx] = cleanItem;
        } else {
            nextList.push(cleanItem);
        }
        const nextRubric: CompetencyRubricData = {
            version: validation.parsed?.version || "1.0",
            roles: validation.parsed?.roles || {},
            quiz_questions: nextList,
        };
        if (commitRubric(nextRubric)) {
            setQuestionModalOpen(false);
            message.success(
                editingQuestionIdx !== null ? `Đã cập nhật câu hỏi ${cleanItem.id}` : `Đã thêm câu hỏi ${cleanItem.id}`
            );
        }
    };

    const handleDeleteQuestion = (idx: number) => {
        const currentList = validation.parsed?.quiz_questions || [];
        const removed = currentList[idx];
        const nextList = currentList.filter((_, i) => i !== idx);
        const nextRubric: CompetencyRubricData = {
            version: validation.parsed?.version || "1.0",
            roles: validation.parsed?.roles || {},
            quiz_questions: nextList,
        };
        if (commitRubric(nextRubric)) {
            message.info(`Đã xóa câu hỏi ${removed?.id || `#${idx + 1}`}`);
        }
    };

    const roleCodeOptions = useMemo(() => {
        const map = new Map<string, string>();
        for (const item of suggestedRoles) {
            if (item.role_code && !map.has(item.role_code)) {
                map.set(item.role_code, item.role_title || "");
            }
        }
        for (const item of STANDARD_ROLE_SUGGESTIONS) {
            if (!map.has(item.role_code)) {
                map.set(item.role_code, item.role_title);
            }
        }
        return Array.from(map.entries()).map(([code, title]) => ({
            value: code,
            label: title ? `${code} — ${title}` : code,
        }));
    }, [suggestedRoles]);

    const roleRows = useMemo(
        () =>
            Object.entries(effectiveRubric.roles).map(([key, rule]) => ({
                key,
                ...rule,
            })),
        [effectiveRubric.roles]
    );

    const roleColumns = (readOnly: boolean): ColumnsType<RubricRoleRule & { key: string }> => {
        const cols: ColumnsType<RubricRoleRule & { key: string }> = [
            {
                title: "Mã vai trò",
                dataIndex: "role_code",
                width: 150,
                render: (code: string) => <Tag color="geekblue">{code}</Tag>,
            },
            {
                title: "Tên hiển thị",
                dataIndex: "label",
                width: 220,
                render: (text: string) => <Text strong>{text}</Text>,
            },
            {
                title: "Chế độ",
                dataIndex: "interaction_mode",
                width: 130,
                render: (m: string) =>
                    m === "oversight" ? (
                        <Tag color="purple">oversight (Giám sát)</Tag>
                    ) : (
                        <Tag color="cyan">write_ops (Thao tác)</Tag>
                    ),
            },
            {
                title: "Mẫu URL phân hệ mục tiêu",
                dataIndex: "target_url_patterns",
                render: (patterns: string[]) =>
                    patterns && patterns.length > 0 ? (
                        <Space size={[4, 4]} wrap>
                            {patterns.slice(0, 6).map((p) => (
                                <Tag key={p}>{p}</Tag>
                            ))}
                            {patterns.length > 6 && (
                                <Tooltip title={patterns.slice(6).join(", ")}>
                                    <Tag color="default">+{patterns.length - 6}</Tag>
                                </Tooltip>
                            )}
                        </Space>
                    ) : (
                        <Text type="secondary">Chưa gán</Text>
                    ),
            },
            {
                title: "Ngưỡng M3 / Lostness",
                key: "thresholds",
                width: 170,
                render: (_, rec) => (
                    <Space size={4} wrap>
                        <Tag>Min bước: {rec.expected_min_steps}</Tag>
                        <Tag>Lostness: {rec.min_actions_for_lostness}</Tag>
                        <Tag>M3 mod: {rec.expected_target_modules_for_m3}</Tag>
                    </Space>
                ),
            },
        ];
        if (!readOnly) {
            cols.push({
                title: "Thao tác",
                key: "actions",
                width: 110,
                fixed: "right",
                render: (_, rec) => (
                    <Space size={4}>
                        <Button
                            size="small"
                            icon={<EditOutlined />}
                            disabled={disabled}
                            onClick={() => openEditRoleModal(rec.key, rec)}
                            aria-label={`Sửa vai trò ${rec.role_code}`}
                        />
                        <Popconfirm
                            title={`Xóa vai trò ${rec.role_code}?`}
                            okText="Xóa"
                            cancelText="Hủy"
                            onConfirm={() => handleDeleteRole(rec.key)}
                        >
                            <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                disabled={disabled}
                                aria-label={`Xóa vai trò ${rec.role_code}`}
                            />
                        </Popconfirm>
                    </Space>
                ),
            });
        }
        return cols;
    };

    const questionColumns = (readOnly: boolean): ColumnsType<RubricQuizQuestion & { _idx: number }> => {
        const cols: ColumnsType<RubricQuizQuestion & { _idx: number }> = [
            {
                title: "Mã câu hỏi",
                dataIndex: "id",
                width: 120,
                render: (qid: string) => <Tag color="blue">{qid}</Tag>,
            },
            {
                title: "Chủ đề & Lĩnh vực",
                key: "topic",
                width: 210,
                render: (_, rec) => (
                    <Space direction="vertical" size={2}>
                        <Text strong>{rec.topic}</Text>
                        <Tag color="default">{rec.skill_domain}</Tag>
                    </Space>
                ),
            },
            {
                title: "Nội dung câu hỏi & đáp án",
                key: "prompt",
                render: (_, rec) => (
                    <Space direction="vertical" size={2}>
                        <Text>{rec.prompt_stem}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                            A: {rec.options?.OPT_A} | B: {rec.options?.OPT_B} | C: {rec.options?.OPT_C} | D:{" "}
                            {rec.options?.OPT_D}
                        </Text>
                    </Space>
                ),
            },
            {
                title: "Đáp án đúng",
                dataIndex: "correct_choice",
                width: 110,
                render: (choice: string) => <Tag color="success">{choice}</Tag>,
            },
        ];
        if (!readOnly) {
            cols.push({
                title: "Thao tác",
                key: "actions",
                width: 110,
                fixed: "right",
                render: (_, rec) => (
                    <Space size={4}>
                        <Button
                            size="small"
                            icon={<EditOutlined />}
                            disabled={disabled}
                            onClick={() => openEditQuestionModal(rec._idx, rec)}
                            aria-label={`Sửa câu hỏi ${rec.id}`}
                        />
                        <Popconfirm
                            title={`Xóa câu hỏi ${rec.id}?`}
                            okText="Xóa"
                            cancelText="Hủy"
                            onConfirm={() => handleDeleteQuestion(rec._idx)}
                        >
                            <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                disabled={disabled}
                                aria-label={`Xóa câu hỏi ${rec.id}`}
                            />
                        </Popconfirm>
                    </Space>
                ),
            });
        }
        return cols;
    };

    const customRoleCount = validation.parsed ? Object.keys(validation.parsed.roles).length : 0;
    const customQuizCount = validation.parsed ? validation.parsed.quiz_questions.length : 0;
    const sizeKb = (validation.bytes / 1024).toFixed(1);

    const statusBadge = isEmpty ? (
        <Tag color="blue">
            Chuẩn mặc định MulberryLane ({defaultRoleCount} vai trò · {defaultQuizCount} câu)
        </Tag>
    ) : validation.valid ? (
        <Tag color="success">
            Đang tùy chỉnh ({customRoleCount} vai trò · {customQuizCount} câu · {sizeKb} / 64 KB)
        </Tag>
    ) : (
        <Tag color="error">Lỗi cấu trúc JSON ({sizeKb} KB)</Tag>
    );

    return (
        <div
            id={id}
            style={{
                border: "1px solid #d9d9d9",
                borderRadius: 8,
                padding: 12,
                background: "#fafafa",
            }}
        >
            {/* Hidden file input cho Import JSON */}
            <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                style={{ display: "none" }}
                onChange={handleImportFile}
                data-testid="rubric-import-file-input"
            />

            {/* Thanh điều khiển chính */}
            <div
                style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 8,
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 10,
                }}
            >
                <Space size={8} wrap>
                    {statusBadge}
                    <Segmented
                        size="small"
                        value={effectiveMode}
                        disabled={disabled}
                        onChange={handleModeChange}
                        options={[
                            { label: "Cấu hình trực quan", value: "visual", icon: <TableOutlined /> },
                            { label: "Mã nguồn JSON", value: "json", icon: <CodeOutlined /> },
                        ]}
                    />
                </Space>

                <Space size={6} wrap>
                    <Button
                        size="small"
                        icon={<SnippetsOutlined />}
                        onClick={handleLoadDefaultTemplate}
                        disabled={disabled || loadingDefault}
                    >
                        Nạp chuẩn mặc định
                    </Button>
                    <Button
                        size="small"
                        icon={<UploadOutlined />}
                        onClick={() => fileInputRef.current?.click()}
                        disabled={disabled}
                    >
                        Import JSON
                    </Button>
                    <Button size="small" icon={<DownloadOutlined />} onClick={handleExportJson} disabled={loadingDefault}>
                        Export JSON
                    </Button>
                    {!isEmpty && (
                        <Popconfirm
                            title="Khôi phục về chuẩn mặc định MulberryLane?"
                            description="Cấu hình tùy chỉnh hiện tại trong khung soạn sẽ bị xóa (chưa lưu DB cho tới khi bấm Lưu cấu hình)."
                            okText="Khôi phục"
                            cancelText="Hủy"
                            onConfirm={handleResetToDefault}
                        >
                            <Button size="small" icon={<RotateLeftOutlined />} disabled={disabled}>
                                Về mặc định
                            </Button>
                        </Popconfirm>
                    )}
                    {effectiveMode === "json" && (
                        <Button
                            size="small"
                            icon={<FormatPainterOutlined />}
                            onClick={handleFormatJson}
                            disabled={disabled || isEmpty || !validation.valid}
                        >
                            Format
                        </Button>
                    )}
                    <Button size="small" icon={<QuestionCircleOutlined />} onClick={() => setGuideOpen(true)}>
                        Xem cấu trúc
                    </Button>
                </Space>
            </div>

            {/* Chế độ Cấu hình Trực quan */}
            {effectiveMode === "visual" ? (
                <Spin spinning={loadingDefault}>
                    {isEmpty ? (
                        <Space direction="vertical" size={10} style={{ width: "100%" }}>
                            <Alert
                                type="info"
                                showIcon
                                message="Đang áp dụng chuẩn mặc định MulberryLane / QLTN v2 từ Backend"
                                description={
                                    <Space direction="vertical" size={8} style={{ width: "100%" }}>
                                        <div>
                                            Hệ thống tự động áp dụng{" "}
                                            <strong>{defaultRoleCount} quy tắc vai trò BQL</strong> và{" "}
                                            <strong>{defaultQuizCount} câu hỏi Pre/Post Quiz</strong> mặc định khi
                                            trường này để trống. Các bảng bên dưới chỉ mang tính xem trước.
                                        </div>
                                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxWidth: "100%" }}>
                                            <Button
                                                type="primary"
                                                size="small"
                                                icon={<EditOutlined />}
                                                disabled={disabled}
                                                onClick={handleLoadDefaultTemplate}
                                                style={{
                                                    whiteSpace: "normal",
                                                    height: "auto",
                                                    paddingBlock: 4,
                                                    maxWidth: "100%",
                                                    textAlign: "left",
                                                }}
                                            >
                                                Tùy chỉnh từ chuẩn MulberryLane
                                            </Button>
                                            <Button
                                                size="small"
                                                icon={<FileAddOutlined />}
                                                disabled={disabled}
                                                onClick={handleCreateEmptyCustom}
                                                style={{
                                                    whiteSpace: "normal",
                                                    height: "auto",
                                                    paddingBlock: 4,
                                                    maxWidth: "100%",
                                                    textAlign: "left",
                                                }}
                                            >
                                                Tạo Rubric trống (Hệ thống khác)
                                            </Button>
                                        </div>
                                    </Space>
                                }
                            />
                            <Tabs
                                size="small"
                                defaultActiveKey="roles"
                                items={[
                                    {
                                        key: "roles",
                                        label: `Quy tắc Vai trò mặc định (${roleRows.length})`,
                                        children: (
                                            <Table
                                                size="small"
                                                rowKey="key"
                                                dataSource={roleRows}
                                                columns={roleColumns(true)}
                                                pagination={false}
                                                scroll={{ x: 860 }}
                                            />
                                        ),
                                    },
                                    {
                                        key: "quiz",
                                        label: `Bộ câu hỏi Pre/Post Quiz mặc định (${effectiveRubric.quiz_questions.length})`,
                                        children: (
                                            <Table
                                                size="small"
                                                rowKey={(r) => `${r.id}-${r._idx}`}
                                                dataSource={effectiveRubric.quiz_questions.map((q, _idx) => ({
                                                    ...q,
                                                    _idx,
                                                }))}
                                                columns={questionColumns(true)}
                                                pagination={false}
                                                scroll={{ x: 860 }}
                                            />
                                        ),
                                    },
                                ]}
                            />
                        </Space>
                    ) : (
                        <Tabs
                            size="small"
                            defaultActiveKey="roles"
                            items={[
                                {
                                    key: "roles",
                                    label: `Quy tắc Vai trò (${roleRows.length})`,
                                    children: (
                                        <Space direction="vertical" size={8} style={{ width: "100%" }}>
                                            <div
                                                style={{
                                                    display: "flex",
                                                    flexWrap: "wrap",
                                                    gap: 8,
                                                    alignItems: "center",
                                                    justifyContent: "space-between",
                                                }}
                                            >
                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                    Vai trò trùng <code>role_code</code> sẽ ghi đè chuẩn MulberryLane;
                                                    vai trò mới sẽ được bổ sung vào hệ thống chấm điểm năng lực (M3 &amp;
                                                    Lostness).
                                                </Text>
                                                <Button
                                                    type="primary"
                                                    size="small"
                                                    icon={<PlusOutlined />}
                                                    disabled={disabled}
                                                    onClick={openCreateRoleModal}
                                                >
                                                    Thêm vai trò
                                                </Button>
                                            </div>
                                            <Table
                                                size="small"
                                                rowKey="key"
                                                dataSource={roleRows}
                                                columns={roleColumns(false)}
                                                pagination={false}
                                                scroll={{ x: 860 }}
                                                locale={{
                                                    emptyText:
                                                        "Chưa có vai trò tùy biến nào. Bấm 'Thêm vai trò' hoặc 'Nạp chuẩn mặc định'.",
                                                }}
                                            />
                                        </Space>
                                    ),
                                },
                                {
                                    key: "quiz",
                                    label: `Bộ câu hỏi Pre/Post Quiz (${effectiveRubric.quiz_questions.length})`,
                                    children: (
                                        <Space direction="vertical" size={8} style={{ width: "100%" }}>
                                            <div
                                                style={{
                                                    display: "flex",
                                                    flexWrap: "wrap",
                                                    gap: 8,
                                                    alignItems: "center",
                                                    justifyContent: "space-between",
                                                }}
                                            >
                                                <Text type="secondary" style={{ fontSize: 12 }}>
                                                    Nếu danh sách có từ 1 câu trở lên, hệ thống dùng toàn bộ bộ câu hỏi
                                                    này thay cho bộ mặc định 6 câu; nếu để trống (0 câu), tự fallback về
                                                    6 câu mặc định.
                                                </Text>
                                                <Button
                                                    type="primary"
                                                    size="small"
                                                    icon={<PlusOutlined />}
                                                    disabled={disabled}
                                                    onClick={openCreateQuestionModal}
                                                >
                                                    Thêm câu hỏi
                                                </Button>
                                            </div>
                                            <Table
                                                size="small"
                                                rowKey={(r) => `${r.id}-${r._idx}`}
                                                dataSource={effectiveRubric.quiz_questions.map((q, _idx) => ({
                                                    ...q,
                                                    _idx,
                                                }))}
                                                columns={questionColumns(false)}
                                                pagination={false}
                                                scroll={{ x: 860 }}
                                                locale={{
                                                    emptyText:
                                                        "Chưa có câu hỏi tùy biến (sẽ fallback về 6 câu chuẩn QLTN v2 khi đánh giá).",
                                                }}
                                            />
                                        </Space>
                                    ),
                                },
                            ]}
                        />
                    )}
                </Spin>
            ) : (
                /* Chế độ Mã nguồn JSON */
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    <Input.TextArea
                        value={rawText}
                        onChange={(e) => onChange?.(e.target.value)}
                        disabled={disabled}
                        autoSize={{ minRows: 10, maxRows: 22 }}
                        placeholder={
                            'Để trống để dùng chuẩn mặc định MulberryLane (khuyên dùng).\nHoặc chuyển sang tab "Cấu hình trực quan" để chỉnh sửa bằng giao diện Form/Bảng.'
                        }
                        style={{
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                            fontSize: 12,
                            lineHeight: 1.5,
                            background: "#ffffff",
                        }}
                    />
                    {!isEmpty && !validation.valid && (
                        <Alert type="error" showIcon message="JSON Rubric chưa hợp lệ" description={validation.error} />
                    )}
                    {!isEmpty && validation.valid && (
                        <Alert
                            type="success"
                            showIcon
                            message={`JSON Rubric hợp lệ (${customRoleCount} vai trò, ${customQuizCount} câu hỏi, ${sizeKb} KB). Bạn có thể chuyển sang tab "Cấu hình trực quan" để chỉnh sửa bằng bảng.`}
                        />
                    )}
                </Space>
            )}

            {/* Modal Thêm / Sửa Vai trò */}
            <Modal
                title={editingRoleKey ? `Chỉnh sửa quy tắc vai trò: ${editingRoleKey}` : "Thêm quy tắc vai trò mới"}
                open={roleModalOpen}
                onCancel={() => setRoleModalOpen(false)}
                onOk={() => roleForm.submit()}
                okText={editingRoleKey ? "Cập nhật vai trò" : "Thêm vai trò"}
                cancelText="Hủy"
                width={640}
                destroyOnHidden
            >
                <Form form={roleForm} layout="vertical" onFinish={handleSaveRole}>
                    <Row gutter={12}>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="role_code"
                                label="Mã vai trò (role_code)"
                                rules={[
                                    { required: true, message: "Vui lòng nhập mã vai trò" },
                                    { max: 64, message: "Tối đa 64 ký tự" },
                                ]}
                                extra="Chọn gợi ý từ Persona BQL hoặc gõ mã mới."
                            >
                                <AutoComplete
                                    options={roleCodeOptions}
                                    placeholder="VD: BQL_DIRECTOR"
                                    filterOption={(inputValue, option) =>
                                        (option?.label?.toString() || "")
                                            .toUpperCase()
                                            .includes(inputValue.toUpperCase())
                                    }
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="interaction_mode"
                                label="Chế độ tương tác phần mềm"
                                rules={[{ required: true }]}
                            >
                                <Select
                                    options={[
                                        { value: "write_ops", label: "write_ops — Tạo/sửa nghiệp vụ" },
                                        { value: "oversight", label: "oversight — Giám sát & tra cứu" },
                                    ]}
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24}>
                            <Form.Item
                                name="label"
                                label="Tên hiển thị (label)"
                                rules={[
                                    { required: true, message: "Vui lòng nhập tên hiển thị" },
                                    { max: 160, message: "Tối đa 160 ký tự" },
                                ]}
                            >
                                <Input placeholder="VD: Giám đốc Dự án (Giám sát & Phê duyệt)" />
                            </Form.Item>
                        </Col>
                        <Col xs={24}>
                            <Form.Item
                                name="target_url_patterns"
                                label="Mẫu URL phân hệ mục tiêu (target_url_patterns)"
                                extra="Gõ từ khóa/đoạn đường dẫn (vd: /ext/incidents, ticket, fee) rồi nhấn Enter hoặc dấu phẩy."
                            >
                                <Select
                                    mode="tags"
                                    tokenSeparators={[","]}
                                    placeholder="Nhập đoạn URL mục tiêu rồi Enter..."
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="expected_min_steps"
                                label="Số bước tối thiểu"
                                rules={[{ required: true, message: "Nhập số từ 1–20" }]}
                            >
                                <InputNumber min={1} max={20} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="min_actions_for_lostness"
                                label="Ngưỡng tính Lostness"
                                rules={[{ required: true, message: "Nhập số từ 1–20" }]}
                            >
                                <InputNumber min={1} max={20} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="expected_target_modules_for_m3"
                                label="Số phân hệ đạt M3"
                                rules={[{ required: true, message: "Nhập số từ 1–10" }]}
                            >
                                <InputNumber min={1} max={10} style={{ width: "100%" }} />
                            </Form.Item>
                        </Col>
                    </Row>
                </Form>
            </Modal>

            {/* Modal Thêm / Sửa Câu hỏi Pre/Post Quiz */}
            <Modal
                title={editingQuestionIdx !== null ? "Chỉnh sửa câu hỏi Pre/Post Quiz" : "Thêm câu hỏi Pre/Post Quiz"}
                open={questionModalOpen}
                onCancel={() => setQuestionModalOpen(false)}
                onOk={() => questionForm.submit()}
                okText={editingQuestionIdx !== null ? "Cập nhật câu hỏi" : "Thêm câu hỏi"}
                cancelText="Hủy"
                width={680}
                destroyOnHidden
            >
                <Form form={questionForm} layout="vertical" onFinish={handleSaveQuestion}>
                    <Row gutter={12}>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="id"
                                label="Mã câu hỏi (id)"
                                rules={[
                                    { required: true, message: "Nhập mã câu hỏi" },
                                    { max: 64, message: "Tối đa 64 ký tự" },
                                ]}
                            >
                                <Input placeholder="VD: q_custom_01" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="topic"
                                label="Chủ đề (topic)"
                                rules={[
                                    { required: true, message: "Nhập chủ đề" },
                                    { max: 120, message: "Tối đa 120 ký tự" },
                                ]}
                            >
                                <Input placeholder="VD: Tiếp nhận sự cố" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={8}>
                            <Form.Item
                                name="skill_domain"
                                label="Lĩnh vực (skill_domain)"
                                rules={[
                                    { required: true, message: "Nhập lĩnh vực" },
                                    { max: 80, message: "Tối đa 80 ký tự" },
                                ]}
                            >
                                <Input placeholder="VD: NAVIGATION_ARCHITECTURE" />
                            </Form.Item>
                        </Col>
                        <Col xs={24}>
                            <Form.Item
                                name="prompt_stem"
                                label="Nội dung câu hỏi (prompt_stem)"
                                rules={[
                                    { required: true, message: "Nhập nội dung câu hỏi" },
                                    { min: 10, message: "Tối thiểu 10 ký tự (chuẩn Backend Schema)" },
                                    { max: 1200, message: "Tối đa 1200 ký tự" },
                                ]}
                            >
                                <Input.TextArea
                                    rows={3}
                                    placeholder="Nhập nội dung câu hỏi kiểm tra năng lực (tối thiểu 10 ký tự)..."
                                />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="opt_a"
                                label="Đáp án A (OPT_A)"
                                rules={[{ required: true, whitespace: true, message: "Không được để trống" }]}
                            >
                                <Input placeholder="Phương án A" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="opt_b"
                                label="Đáp án B (OPT_B)"
                                rules={[{ required: true, whitespace: true, message: "Không được để trống" }]}
                            >
                                <Input placeholder="Phương án B" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="opt_c"
                                label="Đáp án C (OPT_C)"
                                rules={[{ required: true, whitespace: true, message: "Không được để trống" }]}
                            >
                                <Input placeholder="Phương án C" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="opt_d"
                                label="Đáp án D (OPT_D)"
                                rules={[{ required: true, whitespace: true, message: "Không được để trống" }]}
                            >
                                <Input placeholder="Phương án D" />
                            </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                            <Form.Item
                                name="correct_choice"
                                label="Đáp án đúng (correct_choice)"
                                rules={[{ required: true }]}
                            >
                                <Select
                                    options={[
                                        { value: "OPT_A", label: "OPT_A" },
                                        { value: "OPT_B", label: "OPT_B" },
                                        { value: "OPT_C", label: "OPT_C" },
                                        { value: "OPT_D", label: "OPT_D" },
                                    ]}
                                />
                            </Form.Item>
                        </Col>
                    </Row>
                </Form>
            </Modal>

            {/* Modal Hướng dẫn Cấu trúc Schema Rubric */}
            <Modal
                title="Hướng dẫn cấu trúc Rubric Phân hệ & Bộ câu hỏi"
                open={guideOpen}
                onCancel={() => setGuideOpen(false)}
                footer={[
                    <Button key="close" type="primary" onClick={() => setGuideOpen(false)}>
                        Đã hiểu
                    </Button>,
                ]}
                width={760}
            >
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Alert
                        type="info"
                        showIcon
                        message="Cơ chế hoạt động & Kế thừa Mặc định (Single Source of Truth)"
                        description={
                            <ul style={{ margin: 0, paddingLeft: 18 }}>
                                <li>
                                    <strong>Để trống (Khuyên dùng cho MulberryLane):</strong> Hệ thống nạp toàn bộ{" "}
                                    {defaultRoleCount} vai trò BQL và {defaultQuizCount} câu hỏi chuẩn QLTN v2 từ{" "}
                                    <code>DEFAULT_MULBERRYLANE_RUBRIC</code> ở Backend.
                                </li>
                                <li>
                                    <strong>Khi tùy chỉnh một phần (Override):</strong> Các <code>role_code</code> khai
                                    báo sẽ ghi đè vai trò cùng tên hoặc bổ sung vai trò mới; vai trò khác vẫn giữ chuẩn
                                    mặc định. Nếu <code>quiz_questions</code> có ít nhất 1 câu, nó sẽ thay thế bộ 6 câu
                                    mặc định.
                                </li>
                                <li>
                                    <strong>Import / Export JSON:</strong> Hỗ trợ chia sẻ nhanh tệp <code>.json</code>{" "}
                                    (&le; 64 KB) giữa các dự án hoặc chuyển đổi qua lại tức thì với chế độ{" "}
                                    <em>Cấu hình trực quan</em>.
                                </li>
                            </ul>
                        }
                    />
                    <div>
                        <Text strong>1. Khối roles (Quy chuẩn đánh giá từng vai trò BQL):</Text>
                        <ul style={{ marginTop: 4, marginBottom: 8, paddingLeft: 20 }}>
                            <li>
                                <code>role_code</code>: Mã vai trò (vd <code>BQL_DIRECTOR</code>,{" "}
                                <code>BQL_RECEPTIONIST</code>, <code>BQL_STAFF</code>).
                            </li>
                            <li>
                                <code>interaction_mode</code>: <code>&quot;write_ops&quot;</code> (thực thi thao tác)
                                hoặc <code>&quot;oversight&quot;</code> (giám sát, phê duyệt).
                            </li>
                            <li>
                                <code>target_url_patterns</code>: Mảng đường dẫn/từ khóa URL phân hệ mục tiêu trên phần
                                mềm cần đạt.
                            </li>
                            <li>
                                <code>expected_min_steps</code> (1–20), <code>min_actions_for_lostness</code> (1–20),{" "}
                                <code>expected_target_modules_for_m3</code> (1–10).
                            </li>
                        </ul>
                    </div>
                    <div>
                        <Text strong>2. Khối quiz_questions (Bộ câu hỏi Pre/Post Quiz — Marx-Cummings):</Text>
                        <Paragraph style={{ marginTop: 4, marginBottom: 0 }}>
                            Gồm <code>id</code>, <code>topic</code>, <code>skill_domain</code>, <code>prompt_stem</code>{" "}
                            (&ge; 10 ký tự), <code>options</code> (đủ 4 khóa <code>OPT_A</code>, <code>OPT_B</code>,{" "}
                            <code>OPT_C</code>, <code>OPT_D</code>) và <code>correct_choice</code> (
                            <code>OPT_A..OPT_D</code>).
                        </Paragraph>
                    </div>
                </Space>
            </Modal>
        </div>
    );
};
