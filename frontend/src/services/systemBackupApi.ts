import { fetchCustom } from "../components/fetch";

const API_BASE = "/api/v1/system-backup";
const ADMIN_KEY_STORAGE = "agentsociety_admin_backup_key";

export function getStoredAdminBackupKey(): string {
    try {
        return sessionStorage.getItem(ADMIN_KEY_STORAGE) || "";
    } catch {
        return "";
    }
}

export function setStoredAdminBackupKey(key: string): void {
    try {
        const clean = key.trim();
        if (clean) {
            sessionStorage.setItem(ADMIN_KEY_STORAGE, clean);
        } else {
            sessionStorage.removeItem(ADMIN_KEY_STORAGE);
        }
    } catch {
        // ignore storage errors
    }
}

export interface BackupStatusResponse {
    admin_key_required: boolean;
    admin_key_valid: boolean;
    schema_version: string;
    max_upload_mb: number;
}

export interface BackupScopeMeta {
    key: string;
    group: string;
    group_label_vi: string;
    label_vi: string;
    label_en: string;
    label_zh: string;
    description_vi: string;
    includes_secrets_possible: boolean;
    depends_on: string[];
    count: number;
    extra?: Record<string, unknown>;
}

export interface BackupProjectSummary {
    id: string;
    slug: string;
    name: string;
    zones_count: number;
    personas_count: number;
    has_zone_map_image: boolean;
}

export interface BackupInventoryResponse {
    schema_version: string;
    scopes: BackupScopeMeta[];
    projects: BackupProjectSummary[];
    secrets_summary: {
        llm_api_keys: number;
        persona_passwords: number;
        atlas_api_keys: number;
        total: number;
    };
    active_urban_sim_runs: string[];
}

export interface ScopeDiffItem {
    scope: string;
    label_vi: string;
    create_count: number;
    update_count: number;
    delete_count: number;
    unchanged_count: number;
    samples: {
        create: string[];
        update: string[];
        delete: string[];
    };
}

export interface RestorePreviewResponse {
    can_apply: boolean;
    blocking_errors: string[];
    mode: "MERGE_UPSERT" | "REPLACE_SCOPE";
    effective_scopes: string[];
    manifest: {
        format: string;
        schema_version: string;
        created_at: string;
        scopes: string[];
        project_slugs: string[];
        includes_secrets: boolean;
        secrets_count: number;
        notes: string;
        package_sha256: string;
    };
    scope_diffs: ScopeDiffItem[];
    totals: {
        create: number;
        update: number;
        delete: number;
        unchanged: number;
        secrets_to_restore: number;
    };
    warnings: string[];
}

export interface SnapshotRecord {
    snapshot_id: string;
    file_name: string;
    trigger: string;
    note: string;
    created_at: string;
    size_bytes: number;
    sha256: string;
    scopes: string[];
    counts: Record<string, number>;
    file_exists?: boolean;
}

export interface RestoreExecuteResponse {
    success: boolean;
    mode: string;
    trigger: string;
    restored_at: string;
    effective_scopes: string[];
    applied_counts: Record<string, { created: number; updated: number; deleted: number }>;
    secrets_restored_count: number;
    pre_restore_snapshot: SnapshotRecord | null;
    warnings: string[];
}

function buildHeaders(extra?: Record<string, string>, isFormData = false): Record<string, string> {
    const headers: Record<string, string> = isFormData
        ? { ...(extra || {}) }
        : { "Content-Type": "application/json", ...(extra || {}) };
    const adminKey = getStoredAdminBackupKey();
    if (adminKey) {
        headers["X-Admin-Backup-Key"] = adminKey;
    }
    return headers;
}

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const resp = await fetchCustom(url, {
        ...options,
        headers: buildHeaders(options.headers as Record<string, string> | undefined, isFormData),
    });
    const text = await resp.text();
    let parsed: Record<string, unknown> = {};
    if (text) {
        try {
            parsed = JSON.parse(text) as Record<string, unknown>;
        } catch {
            parsed = {};
        }
    }
    if (!resp.ok) {
        const detail =
            (typeof parsed.detail === "string" && parsed.detail) ||
            (typeof parsed.error === "string" && parsed.error) ||
            `HTTP ${resp.status}`;
        const err = new Error(detail) as Error & { status?: number };
        err.status = resp.status;
        throw err;
    }
    return (parsed.data ?? parsed) as T;
}

async function downloadBlob(url: string, options: RequestInit, fallbackName: string): Promise<{ sha256: string }> {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const resp = await fetchCustom(url, {
        ...options,
        headers: buildHeaders(options.headers as Record<string, string> | undefined, isFormData),
    });
    if (!resp.ok) {
        const txt = await resp.text();
        let msg = `HTTP ${resp.status}`;
        try {
            const j = JSON.parse(txt) as Record<string, unknown>;
            if (typeof j.detail === "string") msg = j.detail;
        } catch {
            // ignore
        }
        throw new Error(msg);
    }
    const sha256 = resp.headers.get("X-Backup-Sha256") || "";
    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const filename = match?.[1] || fallbackName;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    try {
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
    } finally {
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
    }
    return { sha256 };
}

export const systemBackupApi = {
    getStatus: (): Promise<BackupStatusResponse> =>
        requestJson<BackupStatusResponse>(`${API_BASE}/status`),

    getInventory: (): Promise<BackupInventoryResponse> =>
        requestJson<BackupInventoryResponse>(`${API_BASE}/inventory`),

    exportBackup: (payload: {
        scopes: string[];
        include_secrets: boolean;
        passphrase: string;
        project_ids?: string[] | null;
        notes?: string;
    }): Promise<{ sha256: string }> =>
        downloadBlob(
            `${API_BASE}/export`,
            { method: "POST", body: JSON.stringify(payload) },
            "agentsociety-backup.zip",
        ),

    previewRestore: (params: {
        file: File;
        scopes?: string[] | null;
        mode: "MERGE_UPSERT" | "REPLACE_SCOPE";
        restore_secrets: boolean;
        passphrase: string;
        project_slugs?: string[] | null;
    }): Promise<RestorePreviewResponse> => {
        const form = new FormData();
        form.append("file", params.file);
        if (params.scopes && params.scopes.length > 0) {
            form.append("scopes_json", JSON.stringify(params.scopes));
        }
        form.append("mode", params.mode);
        form.append("restore_secrets", String(params.restore_secrets));
        form.append("passphrase", params.passphrase || "");
        if (params.project_slugs && params.project_slugs.length > 0) {
            form.append("project_slugs_json", JSON.stringify(params.project_slugs));
        }
        return requestJson<RestorePreviewResponse>(`${API_BASE}/preview`, {
            method: "POST",
            body: form,
        });
    },

    executeRestore: (params: {
        file: File;
        scopes?: string[] | null;
        mode: "MERGE_UPSERT" | "REPLACE_SCOPE";
        restore_secrets: boolean;
        passphrase: string;
        project_slugs?: string[] | null;
        create_snapshot: boolean;
    }): Promise<RestoreExecuteResponse> => {
        const form = new FormData();
        form.append("file", params.file);
        if (params.scopes && params.scopes.length > 0) {
            form.append("scopes_json", JSON.stringify(params.scopes));
        }
        form.append("mode", params.mode);
        form.append("restore_secrets", String(params.restore_secrets));
        form.append("passphrase", params.passphrase || "");
        if (params.project_slugs && params.project_slugs.length > 0) {
            form.append("project_slugs_json", JSON.stringify(params.project_slugs));
        }
        form.append("create_snapshot", String(params.create_snapshot));
        return requestJson<RestoreExecuteResponse>(`${API_BASE}/restore`, {
            method: "POST",
            body: form,
        });
    },

    listSnapshots: (): Promise<SnapshotRecord[]> =>
        requestJson<SnapshotRecord[]>(`${API_BASE}/snapshots`),

    createSnapshot: (note: string): Promise<SnapshotRecord> =>
        requestJson<SnapshotRecord>(`${API_BASE}/snapshots`, {
            method: "POST",
            body: JSON.stringify({ note }),
        }),

    downloadSnapshot: (snapshotId: string): Promise<{ sha256: string }> =>
        downloadBlob(
            `${API_BASE}/snapshots/${encodeURIComponent(snapshotId)}/download`,
            { method: "GET" },
            `${snapshotId}.zip`,
        ),

    rollbackSnapshot: (snapshotId: string): Promise<RestoreExecuteResponse> =>
        requestJson<RestoreExecuteResponse>(
            `${API_BASE}/snapshots/${encodeURIComponent(snapshotId)}/rollback`,
            { method: "POST", body: JSON.stringify({}) },
        ),

    deleteSnapshot: (snapshotId: string): Promise<{ deleted: string }> =>
        requestJson<{ deleted: string }>(
            `${API_BASE}/snapshots/${encodeURIComponent(snapshotId)}?confirm=true`,
            { method: "DELETE" },
        ),
};
