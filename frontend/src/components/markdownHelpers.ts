const MERMAID_HEADER_RE =
    /^(?:flowchart|graph|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|erDiagram|gantt|pie|mindmap|timeline|gitGraph|journey|quadrantChart|requirementDiagram|C4Context|C4Container|C4Component|xychart-beta|sankey-beta|block-beta)\b/;

export function formatAtlasText(raw: string): string {
    const trimmed = raw.trim();
    if (!trimmed) return "";
    if (/<!doctype html|<html[\s>]|<head[\s>]|<title>/i.test(trimmed)) {
        const titleMatch = trimmed.match(/<title[^>]*>([^<]+)<\/title>/i);
        const codeMatch = trimmed.match(/HTTP\s*(\d{3})/i);
        const titleText = titleMatch?.[1]?.trim();
        const codeText = codeMatch?.[1];
        if (codeText === "504" || /504\s*Gateway/i.test(titleText || "")) {
            return "Lỗi kết nối máy chủ EvidenceAtlas (HTTP 504 Gateway Time-out — máy chủ phản hồi quá thời gian).";
        }
        if (titleText) {
            return `Lỗi kết nối máy chủ EvidenceAtlas (${codeText ? `HTTP ${codeText}: ` : ""}${titleText}).`;
        }
        const stripped = trimmed
            .replace(/<style[\s\S]*?<\/style>/gi, " ")
            .replace(/<script[\s\S]*?<\/script>/gi, " ")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim();
        return stripped.slice(0, 300);
    }
    return raw;
}

export function isMermaidDiagramCode(fenceLang: string, codeBody: string): boolean {
    const lang = String(fenceLang || "").trim().toLowerCase();
    if (lang === "mermaid") return true;
    if (lang !== "") return false;
    const firstLine =
        String(codeBody || "")
            .split(/\r?\n/)
            .map((l) => l.trim())
            .find((l) => l && !l.startsWith("%%")) || "";
    return MERMAID_HEADER_RE.test(firstLine);
}
