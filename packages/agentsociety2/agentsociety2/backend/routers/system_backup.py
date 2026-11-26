"""System Backup & Restore HTTP endpoints (/api/v1/system-backup/*)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from agentsociety2.backend.path_security import _configured_workspace_root
from agentsociety2.backend.services.system_backup import (
    BACKUP_SCHEMA_VERSION,
    MAX_BACKUP_ZIP_BYTES,
    create_local_snapshot,
    delete_backup_snapshot,
    execute_restore,
    export_backup_zip,
    get_backup_inventory,
    get_snapshot_file_path,
    list_backup_snapshots,
    preview_restore,
    rollback_from_snapshot,
)

router = APIRouter(prefix="/api/v1/system-backup", tags=["System Backup & Restore"])


def _ws_root() -> Path:
    return Path(_configured_workspace_root()).resolve()


def _configured_admin_backup_key() -> str:
    return os.getenv("ADMIN_BACKUP_KEY", "").strip()


def _is_admin_backup_key_valid(request: Request) -> tuple[bool, bool]:
    """Return (admin_key_required, is_valid)."""
    expected = _configured_admin_backup_key()
    if not expected:
        return False, True
    supplied = (request.headers.get("X-Admin-Backup-Key") or "").strip()
    if not supplied:
        return True, False
    return True, hmac.compare_digest(supplied, expected)


def require_backup_admin(request: Request) -> None:
    """Enforce ADMIN_BACKUP_KEY when configured on Production."""
    required, valid = _is_admin_backup_key_valid(request)
    if required and not valid:
        raise HTTPException(
            status_code=403,
            detail=(
                "Thao tác này chỉ dành cho Quản trị viên cao nhất. "
                "Vui lòng cung cấp đúng khóa ADMIN_BACKUP_KEY trong header X-Admin-Backup-Key."
            ),
        )


def _parse_json_str_list(raw: str | None, default: list[str] | None = None) -> list[str] | None:
    if raw is None or not raw.strip():
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Danh sách JSON không hợp lệ: {exc!s}") from exc
    raise HTTPException(status_code=400, detail="Giá trị danh sách phải là một mảng JSON.")


class ExportBackupRequest(BaseModel):
    """Yêu cầu xuất gói sao lưu cấu hình có chọn lọc phạm vi."""

    scopes: list[str] = Field(..., description="Danh sách mã phạm vi cấu hình cần sao lưu")
    include_secrets: bool = Field(
        False,
        description="Có mang theo bí mật (API Key, mật khẩu Persona, Atlas Key) được mã hóa bằng Passphrase hay không",
    )
    passphrase: str = Field(
        "",
        description="Mật khẩu tối thiểu 8 ký tự dùng để mã hóa gói bí mật khi include_secrets=true",
    )
    project_ids: list[str] | None = Field(
        None,
        description="Lọc theo danh sách ID dự án UrbanSim (để trống = tất cả dự án)",
    )
    notes: str = Field("", max_length=500, description="Ghi chú mô tả bản sao lưu")


class CreateSnapshotRequest(BaseModel):
    """Yêu cầu tạo bản chụp hoàn tác cục bộ."""

    note: str = Field("", max_length=500, description="Ghi chú bản chụp")


@router.get(
    "/status",
    summary="Kiểm tra trạng thái bảo vệ Backup & Restore",
    description="Kiểm tra hệ thống có yêu cầu khóa quản trị ADMIN_BACKUP_KEY hay không và khóa hiện tại có hợp lệ hay không.",
)
async def get_backup_status(request: Request) -> dict[str, Any]:
    required, valid = _is_admin_backup_key_valid(request)
    return {
        "data": {
            "admin_key_required": required,
            "admin_key_valid": valid,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "max_upload_mb": MAX_BACKUP_ZIP_BYTES // (1024 * 1024),
        }
    }


@router.get(
    "/inventory",
    dependencies=[Depends(require_backup_admin)],
    summary="Kiểm kê danh mục phạm vi cấu hình",
    description="Trả về danh sách 11 phạm vi cấu hình cùng số lượng bản ghi, tệp và bí mật hiện có trong hệ thống.",
)
async def get_inventory() -> dict[str, Any]:
    return {"data": get_backup_inventory(_ws_root())}


@router.post(
    "/export",
    dependencies=[Depends(require_backup_admin)],
    summary="Xuất gói sao lưu cấu hình (.zip)",
    description="Đóng gói các phạm vi cấu hình được chọn kèm mã kiểm tra SHA-256 và tùy chọn mã hóa bí mật bằng Passphrase.",
)
async def export_backup(payload: ExportBackupRequest) -> Response:
    zip_bytes, manifest = export_backup_zip(
        _ws_root(),
        scopes=payload.scopes,
        include_secrets=payload.include_secrets,
        passphrase=payload.passphrase,
        project_ids=payload.project_ids,
        notes=payload.notes,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    sha = hashlib.sha256(zip_bytes).hexdigest()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="agentsociety-backup-{stamp}.zip"',
            "X-Backup-Sha256": sha,
            "X-Backup-Scopes-Count": str(len(manifest.get("scopes") or [])),
        },
    )


async def _read_upload_zip(file: UploadFile) -> bytes:
    raw = await file.read(MAX_BACKUP_ZIP_BYTES + 1)
    if len(raw) > MAX_BACKUP_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Gói sao lưu vượt quá giới hạn {MAX_BACKUP_ZIP_BYTES // (1024 * 1024)} MB.",
        )
    return raw


@router.post(
    "/preview",
    dependencies=[Depends(require_backup_admin)],
    summary="Xem trước thay đổi trước khi khôi phục (Dry-Run)",
    description="Kiểm tra tính toàn vẹn gói ZIP, giải mã thử bí mật và tính toán số lượng bản ghi Thêm mới, Cập nhật hoặc Xóa.",
)
async def preview_backup_restore(
    file: UploadFile = File(..., description="Tệp gói sao lưu .zip"),
    scopes_json: str = Form("", description="Danh sách JSON các phạm vi cần khôi phục (trống = tất cả trong gói)"),
    mode: Literal["MERGE_UPSERT", "REPLACE_SCOPE"] = Form("MERGE_UPSERT", description="Chế độ khôi phục"),
    restore_secrets: bool = Form(True, description="Có giải mã và khôi phục bí mật từ gói hay không"),
    passphrase: str = Form("", description="Mật khẩu giải mã gói bí mật"),
    project_slugs_json: str = Form("", description="Danh sách slug dự án UrbanSim cần lọc (trống = tất cả)"),
) -> dict[str, Any]:
    zip_bytes = await _read_upload_zip(file)
    scopes = _parse_json_str_list(scopes_json, default=None)
    project_slugs = _parse_json_str_list(project_slugs_json, default=None)
    result = preview_restore(
        _ws_root(),
        zip_bytes=zip_bytes,
        selected_scopes=scopes,
        mode=mode,
        restore_secrets=restore_secrets,
        passphrase=passphrase,
        project_slugs=project_slugs,
    )
    return {"data": result}


@router.post(
    "/restore",
    dependencies=[Depends(require_backup_admin)],
    summary="Thực thi khôi phục cấu hình lên môi trường hiện tại",
    description="Tạo bản chụp hoàn tác tự động (nếu bật) rồi khôi phục các phạm vi cấu hình đã chọn trong một transaction nguyên tử.",
)
async def execute_backup_restore(
    file: UploadFile = File(..., description="Tệp gói sao lưu .zip"),
    scopes_json: str = Form("", description="Danh sách JSON các phạm vi cần khôi phục (trống = tất cả trong gói)"),
    mode: Literal["MERGE_UPSERT", "REPLACE_SCOPE"] = Form("MERGE_UPSERT", description="Chế độ khôi phục"),
    restore_secrets: bool = Form(True, description="Có giải mã và khôi phục bí mật từ gói hay không"),
    passphrase: str = Form("", description="Mật khẩu giải mã gói bí mật"),
    project_slugs_json: str = Form("", description="Danh sách slug dự án UrbanSim cần lọc (trống = tất cả)"),
    create_snapshot: bool = Form(True, description="Tự động tạo bản chụp hoàn tác trước khi ghi dữ liệu"),
) -> dict[str, Any]:
    zip_bytes = await _read_upload_zip(file)
    scopes = _parse_json_str_list(scopes_json, default=None)
    project_slugs = _parse_json_str_list(project_slugs_json, default=None)
    result = execute_restore(
        _ws_root(),
        zip_bytes=zip_bytes,
        selected_scopes=scopes,
        mode=mode,
        restore_secrets=restore_secrets,
        passphrase=passphrase,
        project_slugs=project_slugs,
        create_pre_restore_snapshot=create_snapshot,
    )
    return {"data": result}


@router.get(
    "/snapshots",
    dependencies=[Depends(require_backup_admin)],
    summary="Danh sách bản chụp hoàn tác cục bộ",
    description="Liệt kê các bản chụp trạng thái trước khi khôi phục để phục vụ kiểm toán và hoàn tác nhanh.",
)
async def list_snapshots() -> dict[str, Any]:
    return {"data": list_backup_snapshots(_ws_root())}


@router.post(
    "/snapshots",
    dependencies=[Depends(require_backup_admin)],
    summary="Tạo bản chụp trạng thái thủ công",
    description="Chụp toàn bộ cấu hình hiện tại (bao gồm khóa bí mật cục bộ) lưu tại máy chủ để sẵn sàng hoàn tác.",
)
async def create_manual_snapshot(payload: CreateSnapshotRequest) -> dict[str, Any]:
    snap = create_local_snapshot(_ws_root(), trigger="MANUAL", note=payload.note)
    return {"data": snap}


@router.get(
    "/snapshots/{snapshot_id}/download",
    dependencies=[Depends(require_backup_admin)],
    summary="Tải xuống tệp bản chụp cục bộ",
    description="Tải về gói ZIP của một bản chụp hoàn tác đã lưu trên máy chủ.",
)
async def download_snapshot(
    snapshot_id: str,
) -> FileResponse:
    fpath = get_snapshot_file_path(_ws_root(), snapshot_id)
    return FileResponse(path=fpath, filename=fpath.name, media_type="application/zip")


@router.post(
    "/snapshots/{snapshot_id}/rollback",
    dependencies=[Depends(require_backup_admin)],
    summary="Hoàn tác cấu hình về bản chụp đã chọn",
    description="Khôi phục nguyên trạng cấu hình và bí mật của môi trường hiện tại về thời điểm tạo bản chụp.",
)
async def rollback_snapshot(
    snapshot_id: str,
) -> dict[str, Any]:
    result = rollback_from_snapshot(_ws_root(), snapshot_id)
    return {"data": result}


@router.delete(
    "/snapshots/{snapshot_id}",
    dependencies=[Depends(require_backup_admin)],
    summary="Xóa bản chụp hoàn tác cũ",
    description="Xóa tệp bản chụp hoàn tác khỏi bộ nhớ cục bộ của máy chủ.",
)
async def remove_snapshot(
    snapshot_id: str,
    confirm: bool = Query(True, description="Xác nhận xóa bản chụp"),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=400, detail="Cần xác nhận xóa bản chụp.")
    return {"data": delete_backup_snapshot(_ws_root(), snapshot_id)}
