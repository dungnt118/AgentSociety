import {
    BoldOutlined,
    BranchesOutlined,
    CheckSquareOutlined,
    CodeOutlined,
    EditOutlined,
    ExpandOutlined,
    EyeOutlined,
    InfoCircleOutlined,
    ItalicOutlined,
    LinkOutlined,
    MinusOutlined,
    OrderedListOutlined,
    SplitCellsOutlined,
    StrikethroughOutlined,
    TableOutlined,
    UnorderedListOutlined,
} from "@ant-design/icons";
import {
    Button,
    Divider,
    Grid,
    Input,
    Modal,
    Segmented,
    Space,
    Tooltip,
    Typography,
} from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import React, { useMemo, useRef, useState } from "react";
import { MarkdownWithMermaid } from "./MarkdownWithMermaid";

const { Text } = Typography;
const { TextArea } = Input;

export type MarkdownEditorMode = "edit" | "split" | "preview";

export interface MarkdownRichTextEditorProps {
    id?: string;
    value?: string;
    onChange?: (value: string) => void;
    placeholder?: string;
    minRows?: number;
    maxRows?: number;
    defaultMode?: MarkdownEditorMode;
    disabled?: boolean;
    allowFullscreen?: boolean;
}

function getTextareaElement(ref: React.RefObject<TextAreaRef | null>): HTMLTextAreaElement | null {
    return ref.current?.resizableTextArea?.textArea ?? null;
}

const DEFAULT_MARKDOWN_PLACEHOLDER = `Ví dụ mô tả kịch bản (hỗ trợ Markdown RichText):

## Mục tiêu kịch bản
Mô phỏng vận hành khu đô thị [MulberryLane](https://mulberrylane.sandbox.demego.vn) với 11 nhân sự BQL và 10 cư dân.

### Phạm vi kiểm thử
- **Lễ tân & Kỹ thuật:** Tiếp nhận phản ánh \`/ext/incidents\` và điều phối xử lý trên \`/ext/internal-tasks\`.
- **Cổng CSKH:** Nhân sự tra cứu hướng dẫn thao tác qua **EvidenceAtlas** khi gặp vướng mắc.`;

export const MarkdownRichTextEditor: React.FC<MarkdownRichTextEditorProps> = ({
    id,
    value = "",
    onChange,
    placeholder = DEFAULT_MARKDOWN_PLACEHOLDER,
    minRows = 6,
    maxRows = 16,
    defaultMode = "split",
    disabled = false,
    allowFullscreen = true,
}) => {
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;
    const [viewMode, setViewMode] = useState<MarkdownEditorMode>(defaultMode);
    const [fullscreenOpen, setFullscreenOpen] = useState(false);

    const inlineTextareaRef = useRef<TextAreaRef | null>(null);
    const modalTextareaRef = useRef<TextAreaRef | null>(null);

    const normalizedValue = typeof value === "string" ? value : "";
    const effectiveMode: MarkdownEditorMode =
        isMobile && viewMode === "split" ? "edit" : viewMode;

    const stats = useMemo(() => {
        const lines = normalizedValue ? normalizedValue.split(/\r?\n/).length : 0;
        const chars = normalizedValue.length;
        return { lines, chars };
    }, [normalizedValue]);

    const emitChange = (
        nextText: string,
        nextSelStart?: number,
        nextSelEnd?: number,
        isFullscreen = false
    ) => {
        onChange?.(nextText);
        if (nextSelStart !== undefined && nextSelEnd !== undefined) {
            const targetRef = isFullscreen ? modalTextareaRef : inlineTextareaRef;
            window.requestAnimationFrame(() => {
                const el = getTextareaElement(targetRef);
                if (!el) return;
                el.focus();
                el.setSelectionRange(nextSelStart, nextSelEnd);
            });
        }
    };

    const getSelection = (isFullscreen: boolean) => {
        const targetRef = isFullscreen ? modalTextareaRef : inlineTextareaRef;
        const el = getTextareaElement(targetRef);
        const start = el?.selectionStart ?? normalizedValue.length;
        const end = el?.selectionEnd ?? normalizedValue.length;
        return { start, end };
    };

    const applyWrap = (
        prefix: string,
        suffix: string,
        fallbackText: string,
        isFullscreen: boolean
    ) => {
        if (disabled) return;
        const { start, end } = getSelection(isFullscreen);
        const selected = normalizedValue.slice(start, end);
        const inner = selected || fallbackText;
        const nextText =
            normalizedValue.slice(0, start) +
            prefix +
            inner +
            suffix +
            normalizedValue.slice(end);
        const selStart = start + prefix.length;
        const selEnd = selStart + inner.length;
        emitChange(nextText, selStart, selEnd, isFullscreen);
    };

    const applyLinePrefix = (
        prefix: string,
        fallbackLine: string,
        isFullscreen: boolean
    ) => {
        if (disabled) return;
        const { start, end } = getSelection(isFullscreen);
        if (!normalizedValue) {
            const snippet = `${prefix}${fallbackLine}`;
            emitChange(snippet, prefix.length, snippet.length, isFullscreen);
            return;
        }
        const lineStart = normalizedValue.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
        const rawLineEnd = normalizedValue.indexOf("\n", end);
        const lineEnd = rawLineEnd === -1 ? normalizedValue.length : rawLineEnd;

        const block = normalizedValue.slice(lineStart, lineEnd);
        const lines = block.split("\n");
        const isOrdered = prefix === "1. ";

        const allPrefixed = isOrdered
            ? lines.every((l) => /^\d+\.\s+/.test(l))
            : lines.every((l) => l.startsWith(prefix));

        const updatedLines = lines.map((line, idx) => {
            if (allPrefixed) {
                return isOrdered ? line.replace(/^\d+\.\s+/, "") : line.slice(prefix.length);
            }
            const linePrefix = isOrdered ? `${idx + 1}. ` : prefix;
            return line ? `${linePrefix}${line}` : `${linePrefix}${fallbackLine}`;
        });

        const replaced = updatedLines.join("\n");
        const nextText =
            normalizedValue.slice(0, lineStart) +
            replaced +
            normalizedValue.slice(lineEnd);
        emitChange(nextText, lineStart, lineStart + replaced.length, isFullscreen);
    };

    const applyHeading = (level: 2 | 3, isFullscreen: boolean) => {
        if (disabled) return;
        const prefix = `${"#".repeat(level)} `;
        const { start, end } = getSelection(isFullscreen);
        const lineStart = normalizedValue.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
        const rawLineEnd = normalizedValue.indexOf("\n", end);
        const lineEnd = rawLineEnd === -1 ? normalizedValue.length : rawLineEnd;
        const line = normalizedValue.slice(lineStart, lineEnd);

        const cleaned = line.replace(/^#{1,6}\s+/, "");
        const nextLine = line.startsWith(prefix)
            ? cleaned
            : `${prefix}${cleaned || `Tiêu đề ${level}`}`;

        const nextText =
            normalizedValue.slice(0, lineStart) +
            nextLine +
            normalizedValue.slice(lineEnd);
        emitChange(nextText, lineStart, lineStart + nextLine.length, isFullscreen);
    };

    const insertBlock = (snippet: string, isFullscreen: boolean) => {
        if (disabled) return;
        const { start, end } = getSelection(isFullscreen);
        const before = normalizedValue.slice(0, start);
        const after = normalizedValue.slice(end);
        const needLeadingNewline = before.length > 0 && !before.endsWith("\n");
        const needTrailingNewline = after.length > 0 && !after.startsWith("\n");
        const prefix = needLeadingNewline ? (before.endsWith("\n\n") ? "" : "\n\n") : "";
        const suffix = needTrailingNewline ? "\n\n" : "";
        const nextText = before + prefix + snippet + suffix + after;
        const cursorPos = before.length + prefix.length + snippet.length;
        emitChange(nextText, cursorPos, cursorPos, isFullscreen);
    };

    const handleKeyDown = (
        e: React.KeyboardEvent<HTMLTextAreaElement>,
        isFullscreen: boolean
    ) => {
        if (disabled) return;
        if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
        const key = e.key.toLowerCase();
        if (key === "b") {
            e.preventDefault();
            applyWrap("**", "**", "chữ in đậm", isFullscreen);
        } else if (key === "i") {
            e.preventDefault();
            applyWrap("*", "*", "chữ in nghiêng", isFullscreen);
        } else if (key === "k") {
            e.preventDefault();
            applyWrap("[", "](https://)", "liên kết", isFullscreen);
        }
    };

    const renderToolbar = (isFullscreen: boolean) => (
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
            <Space size={2} wrap>
                <Tooltip title="Tiêu đề H2">
                    <Button
                        size="small"
                        type="text"
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyHeading(2, isFullscreen)}
                        style={{ fontWeight: 700, paddingInline: 6 }}
                    >
                        H2
                    </Button>
                </Tooltip>
                <Tooltip title="Tiêu đề H3">
                    <Button
                        size="small"
                        type="text"
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyHeading(3, isFullscreen)}
                        style={{ fontWeight: 700, paddingInline: 6 }}
                    >
                        H3
                    </Button>
                </Tooltip>
                <Divider type="vertical" />
                <Tooltip title="In đậm (Ctrl+B)">
                    <Button
                        size="small"
                        type="text"
                        icon={<BoldOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyWrap("**", "**", "chữ in đậm", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="In nghiêng (Ctrl+I)">
                    <Button
                        size="small"
                        type="text"
                        icon={<ItalicOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyWrap("*", "*", "chữ in nghiêng", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Gạch ngang">
                    <Button
                        size="small"
                        type="text"
                        icon={<StrikethroughOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyWrap("~~", "~~", "nội dung gạch ngang", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Mã nội tuyến (`code`)">
                    <Button
                        size="small"
                        type="text"
                        icon={<CodeOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyWrap("`", "`", "mã_lệnh", isFullscreen)}
                    />
                </Tooltip>
                <Divider type="vertical" />
                <Tooltip title="Danh sách gạch đầu dòng">
                    <Button
                        size="small"
                        type="text"
                        icon={<UnorderedListOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyLinePrefix("- ", "Mục danh sách", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Danh sách đánh số">
                    <Button
                        size="small"
                        type="text"
                        icon={<OrderedListOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyLinePrefix("1. ", "Bước thực hiện", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Checklist công việc">
                    <Button
                        size="small"
                        type="text"
                        icon={<CheckSquareOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyLinePrefix("- [ ] ", "Đầu việc cần kiểm tra", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Trích dẫn">
                    <Button
                        size="small"
                        type="text"
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyLinePrefix("> ", "Nội dung trích dẫn", isFullscreen)}
                        style={{ fontWeight: 700, paddingInline: 6 }}
                    >
                        ”
                    </Button>
                </Tooltip>
                <Tooltip title="Hộp ghi chú nổi bật">
                    <Button
                        size="small"
                        type="text"
                        icon={<InfoCircleOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() =>
                            insertBlock("> [!NOTE]\n> Ghi chú bối cảnh quan trọng của kịch bản.", isFullscreen)
                        }
                    />
                </Tooltip>
                <Divider type="vertical" />
                <Tooltip title="Chèn liên kết (Ctrl+K)">
                    <Button
                        size="small"
                        type="text"
                        icon={<LinkOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => applyWrap("[", "](https://)", "tên liên kết", isFullscreen)}
                    />
                </Tooltip>
                <Tooltip title="Chèn bảng Markdown">
                    <Button
                        size="small"
                        type="text"
                        icon={<TableOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() =>
                            insertBlock(
                                "| Vai trò | Nhiệm vụ chính | Ghi chú |\n| --- | --- | --- |\n| Lễ tân | Tiếp nhận sự vụ | Dùng QLTN + Atlas |",
                                isFullscreen
                            )
                        }
                    />
                </Tooltip>
                <Tooltip title="Chèn sơ đồ luồng Mermaid">
                    <Button
                        size="small"
                        type="text"
                        icon={<BranchesOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() =>
                            insertBlock(
                                "```mermaid\nflowchart LR\n    A[Cư dân báo sự vụ] --> B[Lễ tân tiếp nhận]\n    B --> C[Xử lý trên QLTN]\n```",
                                isFullscreen
                            )
                        }
                    />
                </Tooltip>
                <Tooltip title="Chèn đường kẻ ngang">
                    <Button
                        size="small"
                        type="text"
                        icon={<MinusOutlined />}
                        disabled={disabled || effectiveMode === "preview"}
                        onClick={() => insertBlock("---", isFullscreen)}
                    />
                </Tooltip>
            </Space>

            <Space size={6} wrap>
                <Segmented
                    size="small"
                    value={effectiveMode}
                    onChange={(val) => setViewMode(val as MarkdownEditorMode)}
                    options={
                        isMobile
                            ? [
                                  { label: "Soạn thảo", value: "edit", icon: <EditOutlined /> },
                                  { label: "Xem trước", value: "preview", icon: <EyeOutlined /> },
                              ]
                            : [
                                  { label: "Soạn thảo", value: "edit", icon: <EditOutlined /> },
                                  { label: "Song song", value: "split", icon: <SplitCellsOutlined /> },
                                  { label: "Xem trước", value: "preview", icon: <EyeOutlined /> },
                              ]
                    }
                />
                {allowFullscreen && !isFullscreen && (
                    <Tooltip title="Mở rộng toàn màn hình để soạn thảo thoải mái">
                        <Button
                            size="small"
                            icon={<ExpandOutlined />}
                            onClick={() => setFullscreenOpen(true)}
                        >
                            Mở rộng
                        </Button>
                    </Tooltip>
                )}
            </Space>
        </div>
    );

    const renderBody = (isFullscreen: boolean) => {
        const showEditor = effectiveMode === "edit" || effectiveMode === "split";
        const showPreview = effectiveMode === "preview" || effectiveMode === "split";
        const isSplit = effectiveMode === "split";

        const editorMinHeight = isFullscreen ? 420 : Math.max(132, minRows * 22);
        const editorMaxHeight = isFullscreen ? "66vh" : undefined;

        return (
            <div
                style={{
                    display: "grid",
                    gridTemplateColumns: isSplit ? "minmax(0, 1fr) minmax(0, 1fr)" : "minmax(0, 1fr)",
                    background: "#ffffff",
                }}
            >
                {showEditor && (
                    <div
                        style={{
                            borderRight: isSplit ? "1px solid #e2e8f0" : undefined,
                            display: "flex",
                            flexDirection: "column",
                        }}
                    >
                        <TextArea
                            ref={isFullscreen ? modalTextareaRef : inlineTextareaRef}
                            id={isFullscreen ? undefined : id}
                            value={normalizedValue}
                            disabled={disabled}
                            placeholder={placeholder}
                            onChange={(e) => onChange?.(e.target.value)}
                            onKeyDown={(e) => handleKeyDown(e, isFullscreen)}
                            autoSize={
                                isFullscreen
                                    ? { minRows: 16, maxRows: 26 }
                                    : { minRows, maxRows }
                            }
                            variant="borderless"
                            style={{
                                padding: "10px 12px",
                                fontFamily:
                                    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
                                fontSize: 13,
                                lineHeight: 1.6,
                                minHeight: editorMinHeight,
                                maxHeight: editorMaxHeight,
                                resize: "vertical",
                                color: "#0f172a",
                            }}
                        />
                    </div>
                )}

                {showPreview && (
                    <div
                        style={{
                            padding: "10px 14px",
                            minHeight: editorMinHeight,
                            maxHeight: isFullscreen ? "66vh" : Math.max(320, maxRows * 24),
                            overflowY: "auto",
                            background: isSplit ? "#fcfdff" : "#ffffff",
                            color: "#1e293b",
                            fontSize: 13.5,
                        }}
                    >
                        {normalizedValue.trim() ? (
                            <MarkdownWithMermaid content={normalizedValue} />
                        ) : (
                            <Text type="secondary" style={{ fontStyle: "italic", fontSize: 13 }}>
                                Chưa có nội dung mô tả kịch bản để xem trước.
                            </Text>
                        )}
                    </div>
                )}
            </div>
        );
    };

    const renderFooter = () => (
        <div
            style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 8,
                padding: "4px 10px",
                background: "#f8fafc",
                borderTop: "1px solid #e2e8f0",
                fontSize: 11.5,
                color: "#64748b",
            }}
        >
            <span>
                Hỗ trợ Markdown RichText: <code>**đậm**</code>, <code>*nghiêng*</code>,{" "}
                <code># Tiêu đề</code>, danh sách, bảng, liên kết &amp; khối <code>```mermaid</code>
            </span>
            <span>
                {stats.lines} dòng · {stats.chars.toLocaleString()} ký tự
            </span>
        </div>
    );

    return (
        <>
            <div
                style={{
                    border: "1px solid #d9d9d9",
                    borderRadius: 8,
                    overflow: "hidden",
                    background: "#ffffff",
                }}
            >
                {renderToolbar(false)}
                {renderBody(false)}
                {renderFooter()}
            </div>

            {allowFullscreen && (
                <Modal
                    open={fullscreenOpen}
                    title="Soạn thảo Mô tả Kịch bản (Markdown RichText)"
                    footer={[
                        <Button key="close" type="primary" onClick={() => setFullscreenOpen(false)}>
                            Xong
                        </Button>,
                    ]}
                    centered
                    destroyOnHidden
                    width={isMobile ? "96vw" : "90vw"}
                    styles={{ container: { maxWidth: 1240 } }}
                    onCancel={() => setFullscreenOpen(false)}
                >
                    <div
                        style={{
                            border: "1px solid #d9d9d9",
                            borderRadius: 8,
                            overflow: "hidden",
                            background: "#ffffff",
                        }}
                    >
                        {renderToolbar(true)}
                        {renderBody(true)}
                        {renderFooter()}
                    </div>
                </Modal>
            )}
        </>
    );
};

export default MarkdownRichTextEditor;
