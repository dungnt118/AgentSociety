import {
    CheckCircleOutlined,
    CodeOutlined,
    CopyOutlined,
    ExclamationCircleOutlined,
    FileTextOutlined,
    FormatPainterOutlined,
    QuestionCircleOutlined,
} from "@ant-design/icons";
import {
    Alert,
    Button,
    Descriptions,
    Input,
    Modal,
    Popconfirm,
    Space,
    Tag,
    Tooltip,
    Typography,
    message,
} from "antd";
import React, { useMemo, useState } from "react";

const { Text } = Typography;
const { TextArea } = Input;

const MAX_RUBRIC_BYTES = 64 * 1024;

const MINIMAL_RUBRIC_TEMPLATE = {
    version: "1.0",
    roles: {
        BQL_RECEPTIONIST: {
            role_code: "BQL_RECEPTIONIST",
            label: "Lễ tân Sảnh chính (Tiếp nhận & Điều phối Cư dân)",
            interaction_mode: "write_ops",
            target_url_patterns: [
                "ticket",
                "incident",
                "apartment",
                "quan-ly-cu-dan",
            ],
            expected_min_steps: 3,
            min_actions_for_lostness: 3,
            expected_target_modules_for_m3: 2,
        },
    },
    quiz_questions: [
        {
            id: "q_custom_01",
            topic: "Phân biệt phân hệ Phản ánh & Yêu cầu dịch vụ trên QLTN",
            skill_domain: "NAVIGATION_ARCHITECTURE",
            prompt_stem:
                "Khi cư dân gửi phản ánh từ ứng dụng di động và yêu cầu dịch vụ tại quầy lễ tân, nhân viên cần mở cặp đường dẫn nào trên QLTN?",
            options: {
                OPT_A: "/ext/incidents cho phản ánh ứng dụng và /ext/ticket cho phiếu yêu cầu dịch vụ.",
                OPT_B: "/admin/complaints dùng chung cho cả hai loại.",
                OPT_C: "/billing/invoices trong phân hệ kế toán.",
                OPT_D: "/home/dashboard chỉ để xem báo cáo.",
            },
            correct_choice: "OPT_A",
        },
    ],
};

const MINIMAL_RUBRIC_TEMPLATE_JSON = JSON.stringify(MINIMAL_RUBRIC_TEMPLATE, null, 2);

const RUBRIC_PLACEHOLDER = `Để trống để dùng chuẩn mặc định MulberryLane (7 role_code + fallback BQL_STAFF & 6 câu hỏi QLTN).
Hoặc dán JSON Object (<= 64KB) theo cấu trúc ví dụ sau:
{
  "version": "1.0",
  "roles": {
    "BQL_RECEPTIONIST": {
      "role_code": "BQL_RECEPTIONIST",
      "label": "Lễ tân Sảnh chính",
      "interaction_mode": "write_ops",
      "target_url_patterns": ["ticket", "incident", "apartment"],
      "expected_min_steps": 3,
      "min_actions_for_lostness": 3,
      "expected_target_modules_for_m3": 2
    }
  },
  "quiz_questions": [
    {
      "id": "q_custom_01",
      "topic": "Điều hướng phân hệ tiếp nhận sự cố",
      "skill_domain": "NAVIGATION_ARCHITECTURE",
      "prompt_stem": "Đường dẫn xử lý phản ánh cư dân trên QLTN là gì?",
      "options": {
        "OPT_A": "/ext/incidents",
        "OPT_B": "/ext/car-parkings",
        "OPT_C": "/billing/fee",
        "OPT_D": "/home"
      },
      "correct_choice": "OPT_A"
    }
  ]
}`;

interface RubricValidationSummary {
    status: "default" | "valid" | "error";
    bytes: number;
    rolesCount: number;
    questionsCount: number;
    errorMessage?: string;
}

function validateRubricClient(raw: string): RubricValidationSummary {
    const trimmed = raw.trim();
    if (!trimmed) {
        return { status: "default", bytes: 0, rolesCount: 0, questionsCount: 0 };
    }
    const bytes = new TextEncoder().encode(trimmed).length;
    if (bytes > MAX_RUBRIC_BYTES) {
        return {
            status: "error",
            bytes,
            rolesCount: 0,
            questionsCount: 0,
            errorMessage: `Dung lượng JSON (${(bytes / 1024).toFixed(1)} KB) vượt quá giới hạn tối đa 64 KB.`,
        };
    }

    let parsed: unknown;
    try {
        parsed = JSON.parse(trimmed);
    } catch (err) {
        return {
            status: "error",
            bytes,
            rolesCount: 0,
            questionsCount: 0,
            errorMessage: `Lỗi cú pháp JSON: ${err instanceof Error ? err.message : "Không hợp lệ"}`,
        };
    }

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return {
            status: "error",
            bytes,
            rolesCount: 0,
            questionsCount: 0,
            errorMessage: "Root JSON phải là một Object { ... }.",
        };
    }

    const obj = parsed as Record<string, unknown>;
    const roles = obj.roles;
    if (roles !== undefined && (!roles || typeof roles !== "object" || Array.isArray(roles))) {
        return {
            status: "error",
            bytes,
            rolesCount: 0,
            questionsCount: 0,
            errorMessage: "Trường 'roles' phải là một Object ánh xạ theo role_code (vd: { \"BQL_RECEPTIONIST\": { ... } }).",
        };
    }

    const rolesObj = (roles && typeof roles === "object" ? roles : {}) as Record<string, unknown>;
    for (const [key, rule] of Object.entries(rolesObj)) {
        if (!rule || typeof rule !== "object" || Array.isArray(rule)) {
            return {
                status: "error",
                bytes,
                rolesCount: 0,
                questionsCount: 0,
                errorMessage: `roles["${key}"] phải là một Object.`,
            };
        }
        const r = rule as Record<string, unknown>;
        if (typeof r.role_code !== "string" || !r.role_code.trim()) {
            return {
                status: "error",
                bytes,
                rolesCount: 0,
                questionsCount: 0,
                errorMessage: `roles["${key}"] thiếu chuỗi 'role_code'.`,
            };
        }
        if (typeof r.label !== "string" || !r.label.trim()) {
            return {
                status: "error",
                bytes,
                rolesCount: 0,
                questionsCount: 0,
                errorMessage: `roles["${key}"] thiếu chuỗi 'label'.`,
            };
        }
        if (
            r.interaction_mode !== undefined &&
            r.interaction_mode !== "write_ops" &&
            r.interaction_mode !== "oversight"
        ) {
            return {
                status: "error",
                bytes,
                rolesCount: 0,
                questionsCount: 0,
                errorMessage: `roles["${key}"].interaction_mode chỉ nhận "write_ops" hoặc "oversight".`,
            };
        }
        if (r.target_url_patterns !== undefined && !Array.isArray(r.target_url_patterns)) {
            return {
                status: "error",
                bytes,
                rolesCount: 0,
                questionsCount: 0,
                errorMessage: `roles["${key}"].target_url_patterns phải là mảng chuỗi (vd: ["ticket", "incident"]).`,
            };
        }
    }

    const questions = obj.quiz_questions;
    if (questions !== undefined && !Array.isArray(questions)) {
        return {
            status: "error",
            bytes,
            rolesCount: Object.keys(rolesObj).length,
            questionsCount: 0,
            errorMessage: "Trường 'quiz_questions' phải là một mảng Array [ ... ].",
        };
    }

    const qList = Array.isArray(questions) ? questions : [];
    for (let idx = 0; idx < qList.length; idx += 1) {
        const q = qList[idx];
        if (!q || typeof q !== "object" || Array.isArray(q)) {
            return {
                status: "error",
                bytes,
                rolesCount: Object.keys(rolesObj).length,
                questionsCount: qList.length,
                errorMessage: `quiz_questions[${idx}] phải là một Object.`,
            };
        }
        const qi = q as Record<string, unknown>;
        for (const reqKey of ["id", "topic", "skill_domain", "prompt_stem"] as const) {
            if (typeof qi[reqKey] !== "string" || !String(qi[reqKey]).trim()) {
                return {
                    status: "error",
                    bytes,
                    rolesCount: Object.keys(rolesObj).length,
                    questionsCount: qList.length,
                    errorMessage: `quiz_questions[${idx}] thiếu chuỗi '${reqKey}'.`,
                };
            }
        }
        if (String(qi.prompt_stem).trim().length < 10) {
            return {
                status: "error",
                bytes,
                rolesCount: Object.keys(rolesObj).length,
                questionsCount: qList.length,
                errorMessage: `quiz_questions[${idx}].prompt_stem phải có ít nhất 10 ký tự.`,
            };
        }
        if (!qi.options || typeof qi.options !== "object" || Array.isArray(qi.options)) {
            return {
                status: "error",
                bytes,
                rolesCount: Object.keys(rolesObj).length,
                questionsCount: qList.length,
                errorMessage: `quiz_questions[${idx}].options phải là Object chứa OPT_A..OPT_D.`,
            };
        }
        const opts = qi.options as Record<string, unknown>;
        for (const optKey of ["OPT_A", "OPT_B", "OPT_C", "OPT_D"] as const) {
            if (typeof opts[optKey] !== "string" || !String(opts[optKey]).trim()) {
                return {
                    status: "error",
                    bytes,
                    rolesCount: Object.keys(rolesObj).length,
                    questionsCount: qList.length,
                    errorMessage: `quiz_questions[${idx}].options thiếu phương án "${optKey}".`,
                };
            }
        }
        if (!["OPT_A", "OPT_B", "OPT_C", "OPT_D"].includes(String(qi.correct_choice || ""))) {
            return {
                status: "error",
                bytes,
                rolesCount: Object.keys(rolesObj).length,
                questionsCount: qList.length,
                errorMessage: `quiz_questions[${idx}].correct_choice phải là một trong: OPT_A, OPT_B, OPT_C, OPT_D.`,
            };
        }
    }

    return {
        status: "valid",
        bytes,
        rolesCount: Object.keys(rolesObj).length,
        questionsCount: qList.length,
    };
}

export interface RubricJsonEditorProps {
    id?: string;
    value?: string | null;
    onChange?: (value: string) => void;
    disabled?: boolean;
}

export const RubricJsonEditor: React.FC<RubricJsonEditorProps> = ({
    id,
    value,
    onChange,
    disabled = false,
}) => {
    const [guideOpen, setGuideOpen] = useState(false);
    const textValue = typeof value === "string" ? value : "";
    const validation = useMemo(() => validateRubricClient(textValue), [textValue]);

    const handleInsertTemplate = () => {
        onChange?.(MINIMAL_RUBRIC_TEMPLATE_JSON);
        message.success("Đã chèn mẫu JSON Rubric & Câu hỏi mẫu. Hãy chỉnh sửa theo dự án của bạn.");
    };

    const handleFormatJson = () => {
        const trimmed = textValue.trim();
        if (!trimmed) return;
        try {
            const parsed = JSON.parse(trimmed);
            onChange?.(JSON.stringify(parsed, null, 2));
            message.success("Đã định dạng lại JSON.");
        } catch {
            message.error("JSON chưa đúng cú pháp nên chưa thể tự định dạng.");
        }
    };

    const handleCopyTemplate = async () => {
        try {
            await navigator.clipboard.writeText(MINIMAL_RUBRIC_TEMPLATE_JSON);
            message.success("Đã sao chép mẫu JSON Rubric.");
        } catch {
            message.error("Không thể sao chép vào clipboard.");
        }
    };

    return (
        <div>
            <div
                style={{
                    border: `1px solid ${validation.status === "error" ? "#ff4d4f" : "#d9d9d9"}`,
                    borderRadius: 8,
                    overflow: "hidden",
                    background: "#ffffff",
                }}
            >
                <div
                    style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        flexWrap: "wrap",
                        gap: 6,
                        padding: "6px 10px",
                        background: "#f8fafc",
                        borderBottom: "1px solid #e2e8f0",
                    }}
                >
                    <Space size={6} wrap>
                        {validation.status === "default" && (
                            <Tag color="blue" style={{ margin: 0 }}>
                                Đang dùng chuẩn mặc định MulberryLane (7 vai trò + 6 câu)
                            </Tag>
                        )}
                        {validation.status === "valid" && (
                            <Tag color="green" icon={<CheckCircleOutlined />} style={{ margin: 0 }}>
                                JSON hợp lệ · {validation.rolesCount} role · {validation.questionsCount} câu hỏi (
                                {(validation.bytes / 1024).toFixed(1)} / 64 KB)
                            </Tag>
                        )}
                        {validation.status === "error" && (
                            <Tag color="red" icon={<ExclamationCircleOutlined />} style={{ margin: 0 }}>
                                JSON chưa hợp lệ
                            </Tag>
                        )}
                    </Space>

                    <Space size={4} wrap>
                        {textValue.trim() ? (
                            <Popconfirm
                                title="Ghi đè nội dung hiện tại bằng mẫu JSON chuẩn?"
                                okText="Chèn mẫu"
                                cancelText="Hủy"
                                onConfirm={handleInsertTemplate}
                            >
                                <Button size="small" icon={<FileTextOutlined />} disabled={disabled}>
                                    Chèn mẫu JSON
                                </Button>
                            </Popconfirm>
                        ) : (
                            <Button
                                size="small"
                                icon={<FileTextOutlined />}
                                disabled={disabled}
                                onClick={handleInsertTemplate}
                            >
                                Chèn mẫu JSON
                            </Button>
                        )}
                        <Tooltip title="Tự căn lề đẹp (Prettify JSON)">
                            <Button
                                size="small"
                                icon={<FormatPainterOutlined />}
                                disabled={disabled || !textValue.trim()}
                                onClick={handleFormatJson}
                            >
                                Format
                            </Button>
                        </Tooltip>
                        <Button
                            size="small"
                            type="link"
                            icon={<QuestionCircleOutlined />}
                            style={{ paddingInline: 4 }}
                            onClick={() => setGuideOpen(true)}
                        >
                            Xem cấu trúc
                        </Button>
                    </Space>
                </div>

                <TextArea
                    id={id}
                    value={textValue}
                    disabled={disabled}
                    onChange={(e) => onChange?.(e.target.value)}
                    placeholder={RUBRIC_PLACEHOLDER}
                    autoSize={{ minRows: 5, maxRows: 14 }}
                    variant="borderless"
                    style={{
                        padding: "10px 12px",
                        fontFamily:
                            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
                        fontSize: 12.5,
                        lineHeight: 1.55,
                        color: "#0f172a",
                    }}
                />
            </div>

            {validation.status === "error" && validation.errorMessage && (
                <Alert
                    type="error"
                    showIcon
                    style={{ marginTop: 6 }}
                    message={validation.errorMessage}
                />
            )}

            <Modal
                open={guideOpen}
                title={
                    <Space>
                        <CodeOutlined />
                        <span>Hướng dẫn cấu trúc JSON Rubric &amp; Bộ câu hỏi tùy biến</span>
                    </Space>
                }
                width={780}
                centered
                onCancel={() => setGuideOpen(false)}
                footer={[
                    <Button key="copy" icon={<CopyOutlined />} onClick={() => void handleCopyTemplate()}>
                        Sao chép mẫu JSON
                    </Button>,
                    <Button
                        key="apply"
                        type="primary"
                        onClick={() => {
                            handleInsertTemplate();
                            setGuideOpen(false);
                        }}
                    >
                        Áp dụng mẫu vào ô nhập
                    </Button>,
                    <Button key="close" onClick={() => setGuideOpen(false)}>
                        Đóng
                    </Button>,
                ]}
            >
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <Alert
                        type="info"
                        showIcon
                        message="Cơ chế ghép thông minh (Partial Override)"
                        description={
                            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                                <li>
                                    <strong>Để trống hoàn toàn:</strong> dùng toàn bộ 7 vai trò chuẩn MulberryLane
                                    (<code>BQL_DIRECTOR</code>, <code>BQL_ASSISTANT</code>,{" "}
                                    <code>BQL_RECEPTIONIST</code>, <code>SEC_LEAD</code>, <code>SEC_STAFF</code>,{" "}
                                    <code>ENG_LEAD</code>, <code>ENG_STAFF</code> + fallback <code>BQL_STAFF</code>) và 6
                                    câu hỏi mặc định.
                                </li>
                                <li>
                                    <strong>Chỉ khai báo <code>roles</code>:</strong> hệ thống giữ nguyên 6 câu hỏi mặc định
                                    và chỉ ghi đè/bổ sung các <code>role_code</code> bạn khai báo.
                                </li>
                                <li>
                                    <strong>Khai báo <code>quiz_questions</code> (khác rỗng):</strong> thay thế toàn bộ
                                    ngân hàng câu hỏi Pre/Post Quiz bằng danh sách câu hỏi bạn cung cấp.
                                </li>
                            </ul>
                        }
                    />

                    <div>
                        <Text strong>1. Bảng ý nghĩa các trường trong <code>roles[&lt;role_code&gt;]</code></Text>
                        <Descriptions bordered size="small" column={1} style={{ marginTop: 6 }}>
                            <Descriptions.Item label={<code>role_code</code>}>
                                Mã vai trò khớp với cột <em>Mã vai trò</em> trong Ma trận 21 Persona (vd:{" "}
                                <code>BQL_RECEPTIONIST</code>, <code>ENG_STAFF</code>).
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>label</code>}>
                                Tên mô tả vai trò hiển thị trên báo cáo đánh giá năng lực.
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>interaction_mode</code>}>
                                <code>"write_ops"</code> (vai trò thực thi tạo/sửa phiếu) hoặc{" "}
                                <code>"oversight"</code> (vai trò giám sát, xem báo cáo).
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>target_url_patterns</code>}>
                                Mảng các từ khóa phân hệ URL mục tiêu trên QLTN mà vai trò này cần mở (vd:{" "}
                                <code>["ticket", "incident", "apartment"]</code>) dùng để đo tỷ lệ lạc đường (Lostness).
                            </Descriptions.Item>
                            <Descriptions.Item label={<><code>expected_min_steps</code> / <code>min_actions_for_lostness</code> / <code>expected_target_modules_for_m3</code></>}>
                                Số bước tối thiểu (1–20), ngưỡng hành động đo Lostness (1–20) và số phân hệ đạt chuẩn
                                Miller M3 (1–10; mặc định lần lượt là <code>3, 3, 2</code>).
                            </Descriptions.Item>
                        </Descriptions>
                    </div>

                    <div>
                        <Text strong>2. Bảng ý nghĩa các trường trong <code>quiz_questions[]</code></Text>
                        <Descriptions bordered size="small" column={1} style={{ marginTop: 6 }}>
                            <Descriptions.Item label={<><code>id</code> / <code>topic</code> / <code>skill_domain</code></>}>
                                Mã định danh duy nhất (vd: <code>"q_custom_01"</code>), chủ đề câu hỏi và nhóm năng lực
                                (vd: <code>"NAVIGATION_ARCHITECTURE"</code>, <code>"WORKFLOW_HANDOFF"</code>,{" "}
                                <code>"SAFETY_COMPLIANCE"</code>).
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>prompt_stem</code>}>
                                Nội dung câu hỏi tình huống (10–1200 ký tự).
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>options</code>}>
                                Object gồm 4 phương án <code>OPT_A</code>, <code>OPT_B</code>, <code>OPT_C</code>,{" "}
                                <code>OPT_D</code>. Hệ thống tự động gắn thêm lựa chọn thứ 5 là <code>CHUA_BIET</code>{" "}
                                khi chạy khảo sát.
                            </Descriptions.Item>
                            <Descriptions.Item label={<code>correct_choice</code>}>
                                Đáp án đúng: chỉ nhận một trong <code>"OPT_A"</code>, <code>"OPT_B"</code>,{" "}
                                <code>"OPT_C"</code>, <code>"OPT_D"</code>.
                            </Descriptions.Item>
                        </Descriptions>
                    </div>

                    <div>
                        <Text strong>3. Mẫu JSON chuẩn hoàn chỉnh</Text>
                        <pre
                            style={{
                                marginTop: 6,
                                padding: "10px 12px",
                                background: "#f8fafc",
                                border: "1px solid #cbd5e1",
                                borderRadius: 6,
                                maxHeight: 260,
                                overflow: "auto",
                                fontSize: 12,
                                lineHeight: 1.5,
                            }}
                        >
                            <code>{MINIMAL_RUBRIC_TEMPLATE_JSON}</code>
                        </pre>
                    </div>
                </Space>
            </Modal>
        </div>
    );
};

export default RubricJsonEditor;
