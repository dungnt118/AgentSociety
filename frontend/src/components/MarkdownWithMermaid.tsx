import {
    CheckOutlined,
    CodeOutlined,
    CopyOutlined,
    ExpandOutlined,
    EyeOutlined,
} from "@ant-design/icons";
import { Alert, Button, Grid, Modal, Space, Typography, message } from "antd";
import React, { useEffect, useId, useState } from "react";
import { formatAtlasText, isMermaidDiagramCode } from "./markdownHelpers";

const { Text } = Typography;

let mermaidInitialized = false;
let mermaidRenderQueue: Promise<void> = Promise.resolve();

function cleanupMermaidTempNodes(renderId: string): void {
    if (typeof document === "undefined") return;
    document.getElementById(renderId)?.remove();
    document.getElementById(`d${renderId}`)?.remove();
}

export function MermaidDiagramBlock({ code }: { code: string }) {
    const rawId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;
    const normalizedInput = String(code || "").replace(/\r\n/g, "\n").trim();
    const [renderState, setRenderState] = useState<{
        code: string;
        svg: string;
        error: string | null;
    }>({ code: "", svg: "", error: null });
    const [viewMode, setViewMode] = useState<"chart" | "code">("chart");
    const [copied, setCopied] = useState<boolean>(false);
    const [zoomOpen, setZoomOpen] = useState<boolean>(false);

    const isRendering = Boolean(normalizedInput) && renderState.code !== normalizedInput;
    const svgHtml = renderState.code === normalizedInput ? renderState.svg : "";
    const renderError = renderState.code === normalizedInput ? renderState.error : null;

    useEffect(() => {
        if (!normalizedInput) {
            return;
        }
        let cancelled = false;
        const normalizedCode = normalizedInput.replace(/\\n/g, "<br/>");

        const runTask = async () => {
            const renderId = `mmd_${rawId}_${Math.random().toString(36).slice(2, 7)}`;
            try {
                const mod = await import("mermaid");
                const mermaidApi = mod.default;
                if (!mermaidInitialized) {
                    mermaidApi.initialize({
                        startOnLoad: false,
                        theme: "default",
                        securityLevel: "strict",
                        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
                        flowchart: { useMaxWidth: true, htmlLabels: true },
                    });
                    mermaidInitialized = true;
                }
                const result = await mermaidApi.render(renderId, normalizedCode);
                if (!cancelled) {
                    if (result?.svg) {
                        setRenderState({ code: normalizedInput, svg: result.svg, error: null });
                    } else {
                        setRenderState({
                            code: normalizedInput,
                            svg: "",
                            error: "Thư viện Mermaid không trả về SVG hợp lệ.",
                        });
                    }
                }
            } catch (err: unknown) {
                cleanupMermaidTempNodes(renderId);
                if (!cancelled) {
                    setRenderState({
                        code: normalizedInput,
                        svg: "",
                        error:
                            err instanceof Error ? err.message : "Không thể kết xuất sơ đồ Mermaid.",
                    });
                }
            }
        };

        mermaidRenderQueue = mermaidRenderQueue.then(runTask, runTask);

        return () => {
            cancelled = true;
        };
    }, [normalizedInput, rawId]);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            message.success("Đã sao chép mã Mermaid.");
            window.setTimeout(() => setCopied(false), 1800);
        } catch {
            message.error("Không thể sao chép vào clipboard.");
        }
    };

    return (
        <>
            <div
                data-testid="markdown-mermaid-diagram"
                style={{
                    margin: "8px 0",
                    border: "1px solid #cbd5e1",
                    borderRadius: 8,
                    background: "#ffffff",
                    overflow: "hidden",
                }}
            >
                <div
                    style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        flexWrap: "wrap",
                        gap: 8,
                        padding: "6px 10px",
                        background: "#f8fafc",
                        borderBottom: "1px solid #e2e8f0",
                    }}
                >
                    <Text strong style={{ fontSize: 12, color: "#0f172a" }}>
                        Sơ đồ Mermaid
                    </Text>
                    <Space size={4} wrap>
                        <Button
                            size="small"
                            type={viewMode === "chart" ? "primary" : "default"}
                            icon={<EyeOutlined />}
                            onClick={() => setViewMode("chart")}
                        >
                            Sơ đồ
                        </Button>
                        <Button
                            size="small"
                            type={viewMode === "code" ? "primary" : "default"}
                            icon={<CodeOutlined />}
                            onClick={() => setViewMode("code")}
                        >
                            Mã nguồn
                        </Button>
                        <Button
                            size="small"
                            icon={copied ? <CheckOutlined /> : <CopyOutlined />}
                            onClick={() => void handleCopy()}
                        >
                            {copied ? "Đã chép" : "Sao chép"}
                        </Button>
                        {svgHtml && !renderError && (
                            <Button
                                size="small"
                                icon={<ExpandOutlined />}
                                onClick={() => setZoomOpen(true)}
                            >
                                Phóng to
                            </Button>
                        )}
                    </Space>
                </div>

                {viewMode === "chart" ? (
                    isRendering && !svgHtml && !renderError ? (
                        <div style={{ padding: 16, textAlign: "center", fontSize: 12, color: "#64748b" }}>
                            Đang kết xuất sơ đồ Mermaid...
                        </div>
                    ) : svgHtml && !renderError ? (
                        <div
                            className="urban-mermaid-svg"
                            style={{
                                padding: "12px 14px",
                                overflowX: "auto",
                                textAlign: "center",
                                background: "#ffffff",
                            }}
                            dangerouslySetInnerHTML={{ __html: svgHtml }}
                        />
                    ) : (
                        <div>
                            {renderError && (
                                <Alert
                                    type="warning"
                                    showIcon
                                    banner
                                    message={`Không thể kết xuất sơ đồ Mermaid: ${renderError}`}
                                />
                            )}
                            <pre
                                style={{
                                    margin: 0,
                                    padding: "10px 12px",
                                    background: "#f8fafc",
                                    overflowX: "auto",
                                    fontSize: 12,
                                    lineHeight: 1.5,
                                }}
                            >
                                <code className="language-mermaid">{code}</code>
                            </pre>
                        </div>
                    )
                ) : (
                    <pre
                        style={{
                            margin: 0,
                            padding: "10px 12px",
                            background: "#f8fafc",
                            overflowX: "auto",
                            fontSize: 12,
                            lineHeight: 1.5,
                        }}
                    >
                        <code className="language-mermaid">{code}</code>
                    </pre>
                )}
            </div>

            <Modal
                open={zoomOpen}
                title="Sơ đồ Mermaid (Xem chi tiết)"
                footer={null}
                centered
                destroyOnHidden
                width={isMobile ? "96vw" : "90vw"}
                styles={{ container: { maxWidth: 1200 } }}
                onCancel={() => setZoomOpen(false)}
            >
                {svgHtml && (
                    <div
                        className="urban-mermaid-svg"
                        style={{
                            maxHeight: "78vh",
                            overflow: "auto",
                            textAlign: "center",
                            padding: 12,
                            background: "#ffffff",
                        }}
                        dangerouslySetInnerHTML={{ __html: svgHtml }}
                    />
                )}
            </Modal>
        </>
    );
}

function renderInlineMarkdown(text: string, keyPrefix: string): React.ReactNode[] {
    const tokens = text.split(/(\*\*[^*]+?\*\*|~~[^~]+?~~|\[[^\]]+\]\([^)]+\)|`[^`]+`|\*[^*\n]+?\*)/g);
    return tokens.filter((tok) => tok !== "").map((tok, idx) => {
        const key = `${keyPrefix}-${idx}`;
        if (tok.startsWith("**") && tok.endsWith("**") && tok.length > 4) {
            return <strong key={key}>{renderInlineMarkdown(tok.slice(2, -2), `${key}-b`)}</strong>;
        }
        if (tok.startsWith("~~") && tok.endsWith("~~") && tok.length > 4) {
            return <del key={key}>{renderInlineMarkdown(tok.slice(2, -2), `${key}-del`)}</del>;
        }
        const linkMatch = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (linkMatch) {
            const href = linkMatch[2].trim();
            const safeHref = /^(https?:|mailto:|#|\/)/i.test(href) ? href : undefined;
            if (!safeHref) {
                return <span key={key}>{linkMatch[1]}</span>;
            }
            return (
                <a
                    key={key}
                    href={safeHref}
                    target={safeHref.startsWith("#") ? undefined : "_blank"}
                    rel={safeHref.startsWith("#") ? undefined : "noopener noreferrer"}
                    style={{ color: "#1677ff" }}
                >
                    {linkMatch[1]}
                </a>
            );
        }
        if (tok.startsWith("`") && tok.endsWith("`") && tok.length > 2) {
            return (
                <code
                    key={key}
                    style={{
                        background: "#e2e8f0",
                        padding: "1px 5px",
                        borderRadius: 4,
                        fontSize: "0.9em",
                        fontFamily: "monospace",
                    }}
                >
                    {tok.slice(1, -1)}
                </code>
            );
        }
        if (tok.startsWith("*") && tok.endsWith("*") && tok.length > 2 && !tok.startsWith("**")) {
            return <em key={key}>{tok.slice(1, -1)}</em>;
        }
        return <React.Fragment key={key}>{tok}</React.Fragment>;
    });
}

function parseTableCells(line: string): string[] {
    return line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((c) => c.trim());
}

function isMarkdownTableSeparator(line: string): boolean {
    const trimmed = line.trim();
    return /^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$/.test(trimmed);
}

function matchListItem(line: string): { indent: number; ordered: boolean; index?: number; checked?: boolean; text: string } | null {
    const unordered = line.match(/^(\s*)([-*+])\s+(.+)$/);
    if (unordered) {
        const taskMatch = unordered[3].match(/^\[( |x|X)\]\s+(.*)$/);
        return {
            indent: Math.floor(unordered[1].length / 2),
            ordered: false,
            checked: taskMatch ? taskMatch[1].toLowerCase() === "x" : undefined,
            text: taskMatch ? taskMatch[2] : unordered[3],
        };
    }
    const ordered = line.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (ordered) {
        return {
            indent: Math.floor(ordered[1].length / 2),
            ordered: true,
            index: Number(ordered[2]),
            text: ordered[3],
        };
    }
    return null;
}

function renderListTree(
    items: Array<{ indent: number; ordered: boolean; index?: number; checked?: boolean; text: string }>,
    keyPrefix: string
): React.ReactNode {
    interface ListNode {
        text: string;
        ordered: boolean;
        index?: number;
        checked?: boolean;
        children: ListNode[];
    }
    const roots: ListNode[] = [];
    const stack: Array<{ indent: number; node: ListNode }> = [];

    for (const item of items) {
        const node: ListNode = {
            text: item.text,
            ordered: item.ordered,
            index: item.index,
            checked: item.checked,
            children: [],
        };
        while (stack.length && stack[stack.length - 1].indent >= item.indent) {
            stack.pop();
        }
        if (stack.length === 0) {
            roots.push(node);
        } else {
            stack[stack.length - 1].node.children.push(node);
        }
        stack.push({ indent: item.indent, node });
    }

    const renderNodes = (nodes: ListNode[], prefix: string): React.ReactNode => {
        if (nodes.length === 0) return null;
        const ordered = nodes[0].ordered;
        const ListTag = ordered ? "ol" : "ul";
        return (
            <ListTag
                start={ordered ? nodes[0].index : undefined}
                style={{ margin: "4px 0", paddingLeft: 20 }}
            >
                {nodes.map((n, idx) => (
                    <li
                        key={`${prefix}-${idx}`}
                        style={{
                            marginBottom: 3,
                            lineHeight: 1.55,
                            listStyleType: n.checked !== undefined ? "none" : undefined,
                        }}
                    >
                        {n.checked !== undefined && (
                            <input
                                type="checkbox"
                                checked={n.checked}
                                readOnly
                                aria-label={n.text}
                                style={{ marginRight: 6, verticalAlign: "middle" }}
                            />
                        )}
                        {renderInlineMarkdown(n.text, `${prefix}-${idx}`)}
                        {n.children.length > 0 ? renderNodes(n.children, `${prefix}-${idx}-c`) : null}
                    </li>
                ))}
            </ListTag>
        );
    };

    return renderNodes(roots, keyPrefix);
}

function renderMarkdownBlocks(normalized: string, keyPrefix: string): React.ReactNode[] {
    const lines = normalized.split("\n");
    const blocks: React.ReactNode[] = [];
    let i = 0;

    while (i < lines.length) {
        const rawLine = lines[i];
        const trimmed = rawLine.trim();

        if (!trimmed) {
            i += 1;
            continue;
        }

        // Fenced code blocks (``` / ~~~), including single-line trailing content
        const fenceMatch = /^(`{3,}|~{3,})\s*([^\s`~]*)(.*)$/.exec(trimmed);
        if (fenceMatch) {
            const fenceChar = fenceMatch[1][0];
            const fenceLen = fenceMatch[1].length;
            const fenceLang = (fenceMatch[2] || "").trim();
            const inlineTrailing = (fenceMatch[3] || "").trim();
            const closingRe = new RegExp(`^${fenceChar === "`" ? "`" : "~"}{${fenceLen},}\\s*$`);
            const closingInlineRe = new RegExp(`(${fenceChar === "`" ? "`" : "~"}{${fenceLen},})\\s*$`);
            const startIdx = i;
            const body: string[] = [];

            if (inlineTrailing && closingInlineRe.test(inlineTrailing)) {
                body.push(inlineTrailing.replace(closingInlineRe, "").trim());
                i += 1;
            } else {
                if (inlineTrailing) {
                    body.push(inlineTrailing);
                }
                i += 1;
                while (i < lines.length && !closingRe.test(lines[i].trim())) {
                    body.push(lines[i]);
                    i += 1;
                }
                if (i < lines.length) i += 1;
            }

            const codeBody = body.join("\n").trim();
            if (isMermaidDiagramCode(fenceLang, codeBody)) {
                blocks.push(<MermaidDiagramBlock key={`${keyPrefix}-mmd-${startIdx}`} code={codeBody} />);
            } else {
                blocks.push(
                    <pre
                        key={`${keyPrefix}-pre-${startIdx}`}
                        style={{
                            margin: "6px 0",
                            padding: "10px 12px",
                            background: "#f1f5f9",
                            border: "1px solid #cbd5e1",
                            borderRadius: 6,
                            overflowX: "auto",
                            fontSize: 12,
                            lineHeight: 1.5,
                        }}
                    >
                        <code className={fenceLang ? `language-${fenceLang}` : undefined}>
                            {body.join("\n")}
                        </code>
                    </pre>
                );
            }
            continue;
        }

        if (/^(?:---+|___+|\*\*\*+)$/.test(trimmed)) {
            blocks.push(
                <hr
                    key={`${keyPrefix}-hr-${i}`}
                    style={{ border: "none", borderTop: "1px solid #cbd5e1", margin: "8px 0" }}
                />
            );
            i += 1;
            continue;
        }

        const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
        if (headingMatch) {
            const level = headingMatch[1].length;
            const fontSize = level === 1 ? 18 : level === 2 ? 16 : level === 3 ? 15 : 14;
            blocks.push(
                <div
                    key={`${keyPrefix}-h-${i}`}
                    style={{
                        fontWeight: 700,
                        fontSize,
                        marginTop: 10,
                        marginBottom: 4,
                        color: "#0f172a",
                        borderBottom: level <= 2 ? "1px solid #e2e8f0" : undefined,
                        paddingBottom: level <= 2 ? 3 : undefined,
                    }}
                >
                    {renderInlineMarkdown(headingMatch[2], `${keyPrefix}-h-${i}`)}
                </div>
            );
            i += 1;
            continue;
        }

        if (trimmed.startsWith(">")) {
            const startIdx = i;
            const quoteLines: string[] = [];
            while (i < lines.length && lines[i].trim().startsWith(">")) {
                quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
                i += 1;
            }
            const firstLine = (quoteLines[0] || "").trim();
            const alertMatch = firstLine.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$/i);
            const alertPalette: Record<string, { border: string; bg: string; color: string; label: string }> = {
                NOTE: { border: "#3b82f6", bg: "#eff6ff", color: "#1e40af", label: "Ghi chú" },
                TIP: { border: "#10b981", bg: "#ecfdf5", color: "#065f46", label: "Mẹo" },
                IMPORTANT: { border: "#8b5cf6", bg: "#f5f3ff", color: "#5b21b6", label: "Quan trọng" },
                WARNING: { border: "#f59e0b", bg: "#fffbeb", color: "#92400e", label: "Cảnh báo" },
                CAUTION: { border: "#ef4444", bg: "#fef2f2", color: "#991b1b", label: "Lưu ý" },
            };
            if (alertMatch) {
                const style = alertPalette[alertMatch[1].toUpperCase()] || alertPalette.NOTE;
                const bodyLines = alertMatch[2] ? [alertMatch[2], ...quoteLines.slice(1)] : quoteLines.slice(1);
                blocks.push(
                    <blockquote
                        key={`${keyPrefix}-bq-${startIdx}`}
                        style={{
                            margin: "6px 0",
                            padding: "8px 12px",
                            borderLeft: `4px solid ${style.border}`,
                            background: style.bg,
                            color: style.color,
                            borderRadius: "0 6px 6px 0",
                        }}
                    >
                        <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 4 }}>{style.label}</div>
                        {renderMarkdownBlocks(bodyLines.join("\n"), `${keyPrefix}-bq-${startIdx}`)}
                    </blockquote>
                );
            } else {
                blocks.push(
                    <blockquote
                        key={`${keyPrefix}-bq-${startIdx}`}
                        style={{
                            margin: "6px 0",
                            padding: "6px 12px",
                            borderLeft: "3px solid #94a3b8",
                            background: "#f8fafc",
                            color: "#334155",
                        }}
                    >
                        {renderMarkdownBlocks(quoteLines.join("\n"), `${keyPrefix}-bq-${startIdx}`)}
                    </blockquote>
                );
            }
            continue;
        }

        if (trimmed.includes("|") && i + 1 < lines.length && isMarkdownTableSeparator(lines[i + 1])) {
            const startIdx = i;
            const headers = parseTableCells(trimmed);
            i += 2;
            const rows: string[][] = [];
            while (
                i < lines.length &&
                lines[i].trim().includes("|") &&
                !isMarkdownTableSeparator(lines[i]) &&
                !/^(`{3,}|~{3,})/.test(lines[i].trim())
            ) {
                rows.push(parseTableCells(lines[i]));
                i += 1;
            }
            blocks.push(
                <div key={`${keyPrefix}-tbl-${startIdx}`} style={{ overflowX: "auto", margin: "6px 0" }}>
                    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13, background: "#ffffff" }}>
                        <thead>
                            <tr>
                                {headers.map((h, hIdx) => (
                                    <th
                                        key={`th-${hIdx}`}
                                        style={{
                                            border: "1px solid #cbd5e1",
                                            padding: "5px 8px",
                                            textAlign: "left",
                                            background: "#f1f5f9",
                                            fontWeight: 600,
                                        }}
                                    >
                                        {renderInlineMarkdown(h, `${keyPrefix}-th-${startIdx}-${hIdx}`)}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r, rIdx) => (
                                <tr key={`tr-${rIdx}`}>
                                    {headers.map((_, cIdx) => (
                                        <td
                                            key={`td-${rIdx}-${cIdx}`}
                                            style={{
                                                border: "1px solid #cbd5e1",
                                                padding: "5px 8px",
                                                verticalAlign: "top",
                                            }}
                                        >
                                            {renderInlineMarkdown(
                                                r[cIdx] ?? "",
                                                `${keyPrefix}-td-${startIdx}-${rIdx}-${cIdx}`
                                            )}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            );
            continue;
        }

        const firstListItem = matchListItem(rawLine);
        if (firstListItem) {
            const startIdx = i;
            const listItems: Array<{ indent: number; ordered: boolean; index?: number; checked?: boolean; text: string }> = [];
            while (i < lines.length) {
                const item = matchListItem(lines[i]);
                if (!item) {
                    if (!lines[i].trim()) break;
                    const contTrim = lines[i].trim();
                    if (
                        /^\s{2,}\S/.test(lines[i]) &&
                        !/^(#{1,6})\s/.test(contTrim) &&
                        !contTrim.startsWith(">") &&
                        !/^(`{3,}|~{3,})/.test(contTrim) &&
                        listItems.length > 0
                    ) {
                        listItems[listItems.length - 1].text += ` ${contTrim}`;
                        i += 1;
                        continue;
                    }
                    break;
                }
                listItems.push(item);
                i += 1;
            }
            blocks.push(
                <React.Fragment key={`${keyPrefix}-list-${startIdx}`}>
                    {renderListTree(listItems, `${keyPrefix}-list-${startIdx}`)}
                </React.Fragment>
            );
            continue;
        }

        const paraLines: string[] = [];
        const startIdx = i;
        while (
            i < lines.length &&
            lines[i].trim() !== "" &&
            !/^(`{3,}|~{3,})/.test(lines[i].trim()) &&
            !lines[i].trim().startsWith(">") &&
            !/^(#{1,6})\s+/.test(lines[i].trim()) &&
            !matchListItem(lines[i]) &&
            !/^(?:---+|___+|\*\*\*+)$/.test(lines[i].trim()) &&
            !(lines[i].trim().includes("|") && i + 1 < lines.length && isMarkdownTableSeparator(lines[i + 1]))
        ) {
            paraLines.push(lines[i].trim());
            i += 1;
        }
        blocks.push(
            <div key={`${keyPrefix}-p-${startIdx}`} style={{ marginBottom: 4, lineHeight: 1.55 }}>
                {renderInlineMarkdown(paraLines.join(" "), `${keyPrefix}-p-${startIdx}`)}
            </div>
        );
    }

    return blocks;
}

export function MarkdownWithMermaid({
    content,
    className,
}: {
    content: string;
    className?: string;
}) {
    const normalized = formatAtlasText(content).replace(/\r\n/g, "\n").trim();
    if (!normalized) return null;
    return (
        <div className={className} style={{ color: "#1e293b", wordBreak: "break-word" }}>
            {renderMarkdownBlocks(normalized, "md")}
        </div>
    );
}
