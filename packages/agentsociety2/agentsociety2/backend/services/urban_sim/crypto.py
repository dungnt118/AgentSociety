"""Secret encryption (Fernet) and SSRF URL validation for Urban Simulation."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

_KEY_LOCK = threading.Lock()
_DEFAULT_ALLOWED_SCHEMES = {"http", "https"}
_LOCAL_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "backend",
    "gateway",
    "mobility-dashboard",
    "sim-runner",
    "0.0.0.0",
}


def _resolve_workspace_root(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    raw = os.getenv("WORKSPACE_PATH", "").strip() or "/workspace"
    return Path(raw).expanduser().resolve()


def _fernet_key_file(workspace_root: Path | None = None) -> Path:
    root = _resolve_workspace_root(workspace_root)
    return root / ".agentsociety" / ".fernet.key"


def get_or_create_fernet_key(workspace_root: Path | None = None) -> bytes:
    """Return persistent Fernet master key from env or `<workspace>/.agentsociety/.fernet.key`."""
    env_key = os.getenv("URBAN_SIM_FERNET_KEY", "").strip()
    if env_key:
        key_bytes = env_key.encode("utf-8")
        # Validate format early so misconfigured env fails loudly
        Fernet(key_bytes)
        return key_bytes

    key_path = _fernet_key_file(workspace_root)
    with _KEY_LOCK:
        if key_path.is_file():
            data = key_path.read_bytes().strip()
            Fernet(data)
            return data
        key_path.parent.mkdir(parents=True, exist_ok=True)
        generated = Fernet.generate_key()
        try:
            with open(key_path, "xb") as fh:
                fh.write(generated)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
            return generated
        except FileExistsError:
            data = key_path.read_bytes().strip()
            Fernet(data)
            return data


def get_fernet(workspace_root: Path | None = None) -> Fernet:
    return Fernet(get_or_create_fernet_key(workspace_root))


def encrypt_secret(plain: str | None, workspace_root: Path | None = None) -> str:
    value = (plain or "").strip()
    if not value:
        return ""
    return get_fernet(workspace_root).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None, workspace_root: Path | None = None) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    try:
        return get_fernet(workspace_root).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt stored credential (Fernet key mismatch)") from exc


def mask_secret(token: str | None) -> str:
    return "••••••" if (token and str(token).strip()) else ""


def encrypt_vault_blob(payload: dict[str, Any], workspace_root: Path | None = None) -> str:
    serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return get_fernet(workspace_root).encrypt(serialized).decode("ascii")


def decrypt_vault_blob(token: str, workspace_root: Path | None = None) -> dict[str, Any]:
    raw = get_fernet(workspace_root).decrypt(token.encode("ascii")).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Vault payload must be a JSON object")
    return parsed


def _is_disallowed_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    except ValueError:
        return False
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
    )


def validate_external_url(url: str, *, allow_local: bool | None = None) -> str:
    """Validate target URL against SSRF rules (allowing local URLs only when explicitly enabled)."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("URL không được để trống")
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in _DEFAULT_ALLOWED_SCHEMES:
        raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL thiếu hostname hợp lệ")

    local_allowed = (
        allow_local
        if allow_local is not None
        else (os.getenv("URBAN_SIM_ALLOW_LOCAL_URLS", "").strip() == "1")
    )
    if local_allowed:
        return cleaned

    if hostname in _LOCAL_HOSTNAMES or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError(f"Từ chối URL nội bộ/loopback vì lý do bảo mật SSRF: {hostname}")
    if _is_disallowed_ip(hostname):
        raise ValueError(f"Từ chối IP nội bộ/private vì lý do bảo mật SSRF: {hostname}")

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        for info in infos:
            addr = info[4][0]
            if _is_disallowed_ip(addr):
                raise ValueError(
                    f"Hostname '{hostname}' phân giải ra IP nội bộ '{addr}' (chặn SSRF)"
                )
    except OSError:
        # Offline / unit environment where public DNS may not resolve
        pass

    return cleaned
