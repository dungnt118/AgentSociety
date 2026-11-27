"""Playwright-backed real web portal environment for BQL staff (MulberryLane QLTN)."""

from __future__ import annotations

import asyncio
import json
import os
import time
import unicodedata
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

from agentsociety2.backend.services.urban_sim.crypto import validate_external_url
from agentsociety2.contrib.env._urban_events_sink import (
    append_urban_event,
    effective_caller_agent_id,
    make_vault_accessor,
)
from agentsociety2.env import EnvBase, tool
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

logger = get_logger()
_STATE_REL = "state/ENV_STATE.json"
_MAX_POOL_CONTEXTS = 12
_MAX_ACTIVE_BROWSER_OPS = 4

_EXTRACT_DOM_JS = """() => {
  const MAX_ELEMS = 85;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  document.querySelectorAll('[data-as-ref]').forEach((el) => el.removeAttribute('data-as-ref'));
  const candidates = document.querySelectorAll(
    'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="menuitem"], [role="treeitem"], [role="tab"], [role="option"], [role="link"], li.ant-menu-item, div.ant-menu-submenu-title'
  );
  const elements = [];
  let idx = 0;
  for (const el of candidates) {
    if (elements.length >= MAX_ELEMS) break;
    if (!isVisible(el)) continue;
    const tag = el.tagName.toLowerCase();
    if ((tag === 'a' || tag === 'button') && el.closest('li.ant-menu-item, div.ant-menu-submenu-title')) {
      // Keep clickable menu wrapper or inner anchor, avoid unlabeled duplicate wrappers
    }
    const role = el.getAttribute('role') || '';
    const inputType = tag === 'input' ? (el.getAttribute('type') || 'text') : '';
    const aria = norm(el.getAttribute('aria-label'));
    const placeholder = norm(el.getAttribute('placeholder'));
    const nameAttr = norm(el.getAttribute('name'));
    const text = norm(el.innerText || el.textContent || '');
    const titleAttr = norm(el.getAttribute('title'));
    const rawLabel = aria || text || titleAttr || placeholder || nameAttr;
    const isFormField = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (!isFormField && (!rawLabel || rawLabel === tag || (/^\\d+\\+?$/.test(rawLabel) && rawLabel.length <= 3))) {
      continue;
    }
    if (tag === 'li' && el.querySelector('a[href]')) {
      continue;
    }
    const label = (rawLabel || tag).slice(0, 90);
    idx += 1;
    const refId = 'e' + idx;
    el.setAttribute('data-as-ref', refId);
    const disabled = Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true');
    const href = tag === 'a' ? (el.getAttribute('href') || '').slice(0, 80) : '';
    const val = (tag === 'input' || tag === 'textarea' || tag === 'select') ? (inputType === 'password' ? '***' : norm(el.value || '').slice(0, 60)) : '';
    const item = {
      ref_id: refId,
      tag,
      role,
      type: inputType,
      label,
      placeholder: placeholder.slice(0, 60),
      name: nameAttr.slice(0, 40),
      disabled,
      value_preview: val,
    };
    if (href) item.href = href;
    elements.push(item);
  }
  const headings = Array.from(document.querySelectorAll('h1, h2, h3, .ant-breadcrumb, [role="alert"], .ant-message-notice, .toast'))
    .filter(isVisible)
    .map((el) => norm(el.innerText || el.textContent))
    .filter(Boolean)
    .slice(0, 10);
  const mainContainer = document.querySelector('main, [role="main"], .ant-layout-content, [class*="content-body"], #main-content');
  let mainExcerpt = '';
  if (mainContainer && isVisible(mainContainer)) {
    mainExcerpt = norm(mainContainer.innerText || mainContainer.textContent).slice(0, 1200);
  } else if (document.body) {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll('nav, aside, header, .ant-layout-sider, script, style').forEach((n) => n.remove());
    mainExcerpt = norm(clone.innerText || clone.textContent).slice(0, 1200);
  }
  const tableRows = [];
  const rowNodes = document.querySelectorAll('tbody tr, [role="row"]');
  for (const row of rowNodes) {
    if (tableRows.length >= 10) break;
    if (!isVisible(row)) continue;
    if (row.querySelectorAll('th').length > 0 && row.querySelectorAll('td, [role="cell"]').length === 0) continue;
    const rowTxt = norm(row.innerText || row.textContent);
    if (!rowTxt) continue;
    tableRows.push(rowTxt.slice(0, 140));
  }
  const bodyText = norm(document.body ? document.body.innerText : '').slice(0, 1800);
  return {
    url: window.location.href,
    title: norm(document.title),
    headings,
    main_excerpt: mainExcerpt,
    table_rows: tableRows,
    body_excerpt: bodyText,
    elements,
  };
}"""

_CLICK_BY_TEXT_JS = """(targetText) => {
  const norm = (s) => (s || '').normalize('NFC').replace(/\\s+/g, ' ').trim().toLowerCase();
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  document.querySelectorAll('[data-as-click-target]').forEach((el) => el.removeAttribute('data-as-click-target'));
  const want = norm(targetText);
  if (!want) return null;
  const nodes = Array.from(document.querySelectorAll(
    'a, button, .ant-menu-item, .ant-menu-submenu-title, .ant-tabs-tab, [role="menuitem"], [role="tab"], [role="button"], [role="link"]'
  )).filter((el) => {
    if (!isVisible(el)) return false;
    if (el.tagName.toLowerCase() === 'li' && el.querySelector('a, button')) return false;
    return true;
  });
  const labelOf = (el) => norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
  const exactMatches = nodes.filter((el) => labelOf(el) === want);
  let best = null;
  if (exactMatches.length > 0) {
    best = exactMatches.find((el) => el.tagName === 'A' || el.tagName === 'BUTTON') || exactMatches[exactMatches.length - 1];
  } else {
    const partials = nodes.filter((el) => labelOf(el).includes(want));
    partials.sort((a, b) => labelOf(a).length - labelOf(b).length);
    best = partials[0] || null;
  }
  if (best) {
    const innerClickable = best.querySelector('a, button');
    if (innerClickable && isVisible(innerClickable) && labelOf(innerClickable).includes(want)) {
      best = innerClickable;
    }
  }
  if (!best) return null;
  best.setAttribute('data-as-click-target', '1');
  return labelOf(best).slice(0, 120);
}"""


_LOADING_SPLASH_MAX_BYTES = 18_000

_IGNORED_INFLIGHT_URL_PARTS = (
    "socket.io",
    "/ws",
    "websocket",
    "event-stream",
    "/sse",
    "heartbeat",
    "ping",
    "analytics",
    "telemetry",
    "gtag",
    "sentry",
    "clarity",
    "hotjar",
)

_CHECK_PAGE_READY_JS = """() => {
  const readyState = document.readyState || '';
  const bodyEl = document.body;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const st = window.getComputedStyle(el);
    if (!st || st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const bodyText = norm(bodyEl ? (bodyEl.innerText || bodyEl.textContent) : '');
  const lowBody = bodyText.toLowerCase();
  const hasAppSplash = (
    lowBody.includes('đang tải ứng dụng') ||
    lowBody.includes('loading application')
  );
  // Tầng chuẩn W3C ARIA (độc lập framework UI)
  const hasAriaLoading = Array.from(
    document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')
  ).some(isVisible);

  // Tầng nhận diện spinner/skeleton đa hệ sinh thái (AntD, MUI, Element Plus, Bootstrap, Tailwind...)
  const fullSpin = Array.from(
    document.querySelectorAll('.ant-spin-fullscreen, .ant-spin-blur, .ant-btn-loading, .ant-btn-loading-icon, .el-loading-mask')
  ).some(isVisible);
  const inMainOrButton = (el) => Boolean(
    el.closest('main, table, button, .ant-table, .ant-spin-nested-loading, [role="tabpanel"], [role="main"]')
  );
  const frameworkSpinner = Array.from(
    document.querySelectorAll(
      '.ant-spin-spinning, .MuiCircularProgress-root, .MuiLinearProgress-root, .spinner-border, .spinner-grow, .v-progress-circular, .animate-spin'
    )
  ).some((el) => {
    if (!isVisible(el)) return false;
    if (inMainOrButton(el)) return true;
    const r = el.getBoundingClientRect();
    return r.width >= 200 && r.height >= 150;
  });
  const skeletonLoading = Array.from(
    document.querySelectorAll('.ant-skeleton-active, .MuiSkeleton-root')
  ).some((el) => {
    if (!isVisible(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 120 && r.height >= 20;
  });
  const mainBlockingSpin = fullSpin || frameworkSpinner || skeletonLoading;

  const interactiveCount = Array.from(
    document.querySelectorAll('a[href], button, input:not([type="hidden"]), [role="menuitem"], li.ant-menu-item')
  ).filter(isVisible).length;
  const mainEl = document.querySelector('main, [role="main"], .ant-layout-content, [class*="content-body"], #main-content');
  const mainTextLen = norm(mainEl ? (mainEl.innerText || mainEl.textContent) : '').length;
  const tableRowCount = Array.from(document.querySelectorAll('tbody tr, [role="row"]')).filter(isVisible).length;
  const hasContent = interactiveCount >= 2 || bodyText.length >= 40;
  const docOk = readyState === 'interactive' || readyState === 'complete';
  const ready = docOk && !hasAppSplash && !hasAriaLoading && !mainBlockingSpin && hasContent;
  let reason = 'ok';
  if (!docOk) reason = 'document_loading';
  else if (hasAppSplash) reason = 'app_splash_visible';
  else if (hasAriaLoading) reason = 'aria_busy';
  else if (mainBlockingSpin) reason = 'blocking_spinner';
  else if (!hasContent) reason = 'empty_dom';
  const signature = `${bodyText.length}:${interactiveCount}:${tableRowCount}:${mainTextLen}`;
  return { ready, reason, interactiveCount, bodyLen: bodyText.length, tableRowCount, mainTextLen, signature };
}"""


def _norm_vi(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower().strip()


def _normalize_qltn_route(url_or_path: str | None) -> str:
    raw = str(url_or_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path if (parsed.scheme or parsed.netloc) else raw.split("?", 1)[0]).strip()
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


class DemegoWebPortalEnv(EnvBase):
    """Môi trường trình duyệt thật Playwright thao tác trên cổng QLTN (chỉ dành cho nhân sự BQL)."""

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("current_url", "TEXT"),
        ColumnDef("actions_count", "INTEGER"),
        ColumnDef("blocked_actions_count", "INTEGER"),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_web_actions", "INTEGER"),
        ColumnDef("total_blocked_actions", "INTEGER"),
    ]

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        return True

    @classmethod
    def description(cls) -> str:
        return "Môi trường thao tác trình duyệt web thật (Playwright Chromium) trên phần mềm quản lý tòa nhà QLTN cho nhân sự BQL."

    @classmethod
    def skill_dirs(cls) -> list:
        return [Path(__file__).resolve().parent / "urban_sim_skills" / "bql"]

    def __init__(
        self,
        allowed_agent_ids: list[int] | None = None,
        default_portal_url: str = "https://mulberrylane.sandbox.demego.vn",
        secrets_vault_path: str | None = None,
        screenshots_dir: str | None = None,
        events_log_path: str | None = None,
        guardrail_mode: str = "SAFE_WRITE",
        record_prefix: str = "[SIM-BQL]",
        blocked_keywords: list[str] | None = None,
        personas_meta: dict[str, dict[str, str]] | None = None,
    ):
        super().__init__()
        self._allowed_ids: set[int] = {int(x) for x in (allowed_agent_ids or [])}
        self._default_portal_url = str(default_portal_url).strip()
        self._screenshots_dir = Path(screenshots_dir).resolve() if screenshots_dir else None
        if self._screenshots_dir is not None:
            self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._events_log_path = events_log_path
        self._guardrail_mode = str(guardrail_mode or "SAFE_WRITE").upper()
        self._record_prefix = str(record_prefix or "[SIM-BQL]").strip()
        self._blocked_keywords = [_norm_vi(k) for k in (blocked_keywords or []) if str(k).strip()]
        self._personas_meta = {int(k): dict(v) for k, v in (personas_meta or {}).items()}

        # Private vault closure — prevents secret exposure via EnvBase attrs / CodeGenRouter
        self._vault_accessor = make_vault_accessor(secrets_vault_path)

        self._pool_lock = asyncio.Lock()
        self._browser_slots = asyncio.Semaphore(_MAX_ACTIVE_BROWSER_OPS)
        self._agent_locks: dict[int, asyncio.Lock] = {}
        self._playwright = None
        self._browser = None
        self._contexts: OrderedDict[int, tuple[Any, Any]] = OrderedDict()  # aid -> (context, page)
        self._page_inflight: dict[int, dict[str, float]] = {}

        self._last_urls: dict[int, str] = {}
        self._actions_count: dict[int, int] = {}
        self._blocked_count: dict[int, int] = {}
        self._step_counter = 0

    def _agent_lock(self, agent_id: int) -> asyncio.Lock:
        aid = int(agent_id)
        if aid not in self._agent_locks:
            self._agent_locks[aid] = asyncio.Lock()
        return self._agent_locks[aid]

    def _assert_allowed(self, agent_id: int) -> tuple[bool, dict[str, Any]]:
        aid = int(agent_id)
        if aid not in self._allowed_ids:
            return False, {
                "ok": False,
                "error": f"ACCESS_DENIED: Agent {aid} thuộc nhóm Cư dân (không có quyền truy cập phần mềm QLTN BQL).",
            }
        return True, {}

    def _agent_meta(self, agent_id: int) -> tuple[str, str]:
        m = self._personas_meta.get(int(agent_id), {})
        return str(m.get("full_name") or f"BQL-{agent_id}"), str(m.get("role_title") or "")

    def _storage_state_path(self, agent_id: int) -> Path | None:
        if self._workspace_root is None:
            return None
        state_dir = self._workspace_root / "state" / "browser_states"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"agent_{int(agent_id)}.json"

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-notifications"],
        )
        return self._browser

    def _attach_inflight_tracker(self, aid: int, page: Any) -> None:
        """Theo dõi các XHR/Fetch đang chạy trên từng page (loại trừ WS/SSE/analytics)."""
        bucket: dict[str, float] = {}
        self._page_inflight[aid] = bucket

        def _track_req(req: Any) -> None:
            try:
                if getattr(req, "resource_type", "") not in {"xhr", "fetch"}:
                    return
                url_low = str(getattr(req, "url", "") or "").lower()
                if any(part in url_low for part in _IGNORED_INFLIGHT_URL_PARTS):
                    return
                bucket[f"{id(req)}:{url_low[:160]}"] = time.monotonic()
            except Exception:
                pass

        def _drop_req(req: Any) -> None:
            try:
                url_low = str(getattr(req, "url", "") or "").lower()
                bucket.pop(f"{id(req)}:{url_low[:160]}", None)
            except Exception:
                pass

        page.on("request", _track_req)
        page.on("requestfinished", _drop_req)
        page.on("requestfailed", _drop_req)

    def _count_active_inflight(self, aid: int | None) -> int:
        if aid is None:
            return 0
        bucket = self._page_inflight.get(int(aid))
        if not bucket:
            return 0
        now = time.monotonic()
        stale = [k for k, started in bucket.items() if (now - started) > 12.0]
        for k in stale:
            bucket.pop(k, None)
        return len(bucket)

    async def _get_page(self, agent_id: int):
        aid = int(agent_id)
        async with self._pool_lock:
            if aid in self._contexts:
                ctx, page = self._contexts[aid]
                self._contexts.move_to_end(aid)
                return page

            while len(self._contexts) >= _MAX_POOL_CONTEXTS:
                evict_aid = next(
                    (k for k in self._contexts if k != aid and not self._agent_lock(k).locked()),
                    None,
                )
                if evict_aid is None:
                    evict_aid = next((k for k in self._contexts if k != aid), None)
                if evict_aid is None:
                    break
                evict_ctx, evict_page = self._contexts.pop(evict_aid)
                self._page_inflight.pop(evict_aid, None)
                try:
                    self._last_urls[evict_aid] = evict_page.url or self._last_urls.get(evict_aid, "")
                    st_path = self._storage_state_path(evict_aid)
                    if st_path is not None:
                        await evict_ctx.storage_state(path=str(st_path))
                except Exception:
                    logger.debug("Failed saving storage_state on pool eviction for agent %d", evict_aid, exc_info=True)
                try:
                    await evict_ctx.close()
                except Exception:
                    pass

            browser = await self._ensure_browser()
            st_path = self._storage_state_path(aid)
            ctx_kwargs: dict[str, Any] = {
                "viewport": {"width": 1280, "height": 800},
                "locale": "vi-VN",
                "permissions": ["notifications"],
            }
            if st_path is not None and st_path.is_file():
                ctx_kwargs["storage_state"] = str(st_path)
            ctx = await browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()
            page.set_default_timeout(15000)
            self._attach_inflight_tracker(aid, page)
            self._contexts[aid] = (ctx, page)
            return page

    async def _save_context_state(self, agent_id: int, page: Any) -> None:
        aid = int(agent_id)
        try:
            self._last_urls[aid] = page.url or ""
            st_path = self._storage_state_path(aid)
            if st_path is not None and aid in self._contexts:
                ctx, _ = self._contexts[aid]
                await ctx.storage_state(path=str(st_path))
        except Exception:
            logger.debug("Could not persist Playwright storage_state for agent %d", aid, exc_info=True)

    async def _wait_until_page_ready(
        self,
        page: Any,
        *,
        agent_id: int | None = None,
        timeout_ms: int = 4500,
        initial_settle_ms: int = 260,
        require_stable_polls: int = 2,
    ) -> dict[str, Any]:
        """Chờ đa tầng độc lập framework: XHR/Fetch lắng xuống -> W3C ARIA & UI indicator -> DOM ổn định 2 nhịp."""
        t0 = time.monotonic()
        if initial_settle_ms > 0:
            await page.wait_for_timeout(initial_settle_ms)
        deadline = t0 + max(0.3, timeout_ms / 1000.0)
        last_reason = "init"
        last_sig: str | None = None
        stable_streak = 0
        needed_streak = max(1, int(require_stable_polls))
        while True:
            inflight = self._count_active_inflight(agent_id)
            if inflight > 0:
                stable_streak = 0
                last_sig = None
                last_reason = f"inflight_api:{inflight}"
            else:
                try:
                    state = await page.evaluate(_CHECK_PAGE_READY_JS)
                    if isinstance(state, dict) and state.get("ready"):
                        sig = str(state.get("signature") or "")
                        if last_sig is not None and sig == last_sig:
                            stable_streak += 1
                        else:
                            last_sig = sig
                            stable_streak = 1
                            last_reason = "dom_mutating"
                        if stable_streak >= needed_streak:
                            return {
                                "ready": True,
                                "capture_status": "READY",
                                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                                "reason": "ok",
                            }
                    else:
                        stable_streak = 0
                        last_sig = None
                        if isinstance(state, dict):
                            last_reason = str(state.get("reason") or last_reason)
                except Exception as exc:
                    stable_streak = 0
                    last_sig = None
                    last_reason = f"eval_retry:{type(exc).__name__}"
            if time.monotonic() >= deadline:
                return {
                    "ready": False,
                    "capture_status": "LOADING_TIMEOUT",
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    "reason": last_reason,
                }
            await page.wait_for_timeout(150)

    async def _dismiss_hover_overlays(self, page: Any) -> None:
        """Di chuột ra góc trên bên phải ngoài sidebar AntD để tắt hover popover (không dùng (0,0) hay Escape)."""
        try:
            await page.mouse.move(1260, 12)
            await page.wait_for_timeout(180)
        except Exception:
            pass

    async def _capture_screenshot(
        self,
        agent_id: int,
        page: Any,
        action_tag: str,
        *,
        capture_status: str = "READY",
        current_url: str = "",
    ) -> tuple[str | None, int | None]:
        if self._screenshots_dir is None:
            return None, None
        aid = int(agent_id)
        count = self._actions_count.get(aid, 0) + 1
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        safe_tag = "".join(c if c.isalnum() or c in "_-" else "_" for c in action_tag)[:24]
        filename = f"agent_{aid}_s{count}_{safe_tag}_{ts}.jpg"
        target = self._screenshots_dir / filename
        tmp_target = self._screenshots_dir / f".{filename}.tmp"
        try:
            for attempt in range(2):
                try:
                    await page.screenshot(
                        path=str(tmp_target),
                        type="jpeg",
                        quality=70,
                        full_page=False,
                        animations="disabled",
                        timeout=15000,
                    )
                    break
                except Exception:
                    if attempt >= 1:
                        raise
                    await page.wait_for_timeout(250)
            os.replace(tmp_target, target)
            img_bytes = target.read_bytes()
            size_bytes = len(img_bytes)

            cur_url = str(current_url or page.url or "").strip()
            cur_route = _normalize_qltn_route(cur_url)
            meta_path = self._screenshots_dir / f"agent_{aid}_latest.meta.json"
            prev_meta: dict[str, Any] = {}
            if meta_path.is_file():
                try:
                    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        prev_meta = loaded
                except Exception:
                    prev_meta = {}

            latest_copy = self._screenshots_dir / f"agent_{aid}_latest.jpg"
            is_ready_shot = capture_status == "READY" and size_bytes > 0
            if is_ready_shot:
                tmp_latest = self._screenshots_dir / f".agent_{aid}_latest.jpg.tmp"
                tmp_latest.write_bytes(img_bytes)
                os.replace(tmp_latest, latest_copy)
                latest_img_file = filename
                latest_img_url = cur_url
                latest_img_route = cur_route
                latest_img_status = "READY"
            else:
                latest_img_file = prev_meta.get("latest_image_filename") or (
                    latest_copy.name if latest_copy.is_file() else None
                )
                latest_img_url = prev_meta.get("latest_image_url") or ""
                latest_img_route = prev_meta.get("latest_image_route_path") or ""
                latest_img_status = prev_meta.get("latest_image_status") or capture_status

            meta_payload = {
                "agent_id": aid,
                "last_screenshot_filename": filename,
                "last_screenshot_bytes": size_bytes,
                "capture_status": capture_status,
                "current_url": cur_url,
                "current_route_path": cur_route,
                "latest_image_filename": latest_img_file,
                "latest_image_url": latest_img_url,
                "latest_image_route_path": latest_img_route,
                "latest_image_status": latest_img_status,
                "captured_at": datetime.now(UTC).isoformat(),
            }
            atomic_write_text(
                meta_path,
                json.dumps(meta_payload, ensure_ascii=False, indent=2),
            )
            return filename, size_bytes
        except Exception:
            logger.debug("Screenshot capture failed for agent %d", aid, exc_info=True)
            try:
                if tmp_target.exists():
                    tmp_target.unlink()
            except OSError:
                pass
            return None, None

    async def _extract_snapshot(self, page: Any) -> dict[str, Any]:
        snap = await page.evaluate(_EXTRACT_DOM_JS)
        # Bound response text length while keeping main_excerpt, table_rows & refs visible
        raw_str = json.dumps(snap, ensure_ascii=False)
        if len(raw_str) > 8500 and isinstance(snap, dict):
            snap["body_excerpt"] = str(snap.get("body_excerpt") or "")[:500]
            if len(json.dumps(snap, ensure_ascii=False)) > 8500:
                snap["main_excerpt"] = str(snap.get("main_excerpt") or "")[:700]
            if len(json.dumps(snap, ensure_ascii=False)) > 8500:
                snap["elements"] = (snap.get("elements") or [])[:55]
        return snap

    def _emit_web_event(
        self,
        agent_id: int,
        action: str,
        summary: str,
        *,
        url: str = "",
        screenshot_file: str | None = None,
        ok: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        name, role = self._agent_meta(agent_id)
        append_urban_event(
            self._events_log_path,
            stream="WEB",
            agent_id=int(agent_id),
            agent_name=name,
            role_title=role,
            action=action,
            summary=summary,
            sim_time=self.t,
            screenshot_file=screenshot_file,
            ok=ok,
            details={"url": url, **(extra or {})},
        )

    async def to_workspace(self, workspace_path=None) -> None:
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            return
        async with self._pool_lock:
            for aid, (ctx, page) in list(self._contexts.items()):
                try:
                    self._last_urls[aid] = page.url or self._last_urls.get(aid, "")
                    st_path = self._storage_state_path(aid)
                    if st_path is not None:
                        await ctx.storage_state(path=str(st_path))
                except Exception:
                    pass
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "last_urls": {str(k): v for k, v in self._last_urls.items()},
                    "actions_count": {str(k): v for k, v in self._actions_count.items()},
                    "blocked_count": {str(k): v for k, v in self._blocked_count.items()},
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._last_urls = {int(k): str(v) for k, v in (state.get("last_urls") or {}).items()}
        self._actions_count = {int(k): int(v) for k, v in (state.get("actions_count") or {}).items()}
        self._blocked_count = {int(k): int(v) for k, v in (state.get("blocked_count") or {}).items()}
        self._step_counter = int(state.get("step_counter") or 0)
        return True

    async def close(self):
        async with self._pool_lock:
            for _, (ctx, _page) in list(self._contexts.items()):
                try:
                    await ctx.close()
                except Exception:
                    pass
            self._contexts.clear()
            self._page_inflight.clear()
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

    @tool(readonly=True, kind="observe")
    async def observe_web_portal(self, agent_id: int) -> dict[str, Any]:
        """Quan sát màn hình phần mềm QLTN hiện tại của nhân sự BQL (trả URL, tiêu đề và các phần tử [e1..eN])."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return {"agent_id": aid, "software_access_enabled": False}
        async with self._agent_lock(aid), self._browser_slots:
            if aid not in self._contexts and aid not in self._last_urls:
                return {
                    "agent_id": aid,
                    "software_access_enabled": True,
                    "status": "NOT_LOGGED_IN",
                    "portal_url": self._default_portal_url,
                    "hint": "QUAN TRỌNG: Gọi lại ask_env với readonly=False (bắt buộc readonly=False) để chạy login_qltn_portal mở và đăng nhập vào phần mềm QLTN.",
                }
            page = await self._get_page(aid)
            if (not page.url or page.url == "about:blank") and self._last_urls.get(aid):
                target_url = validate_external_url(self._last_urls[aid])
                await page.goto(target_url, wait_until="domcontentloaded")
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=5000, initial_settle_ms=150, require_stable_polls=1
            )
            snap = await self._extract_snapshot(page)
            return {
                "ok": True,
                "agent_id": aid,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    @tool(readonly=False)
    async def login_qltn_portal(self, agent_id: int) -> dict[str, Any]:
        """Mở trang QLTN và tự động đăng nhập bằng tài khoản được cấu hình cho nhân sự BQL."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        vault = self._vault_accessor()
        creds = (vault.get("portal_credentials") or {}).get(str(aid)) or {}
        portal_url = str(creds.get("portal_url") or self._default_portal_url).strip()
        username = str(creds.get("username") or "").strip()
        password = str(creds.get("password") or "")
        if not username or not password:
            return {
                "ok": False,
                "error": f"MISSING_CREDENTIALS: Chưa cấu hình username/password QLTN cho agent_id={aid} trong DB.",
            }

        portal_url = validate_external_url(portal_url)
        async with self._agent_lock(aid), self._browser_slots:
            if aid in self._contexts:
                page = await self._get_page(aid)
                cur_url = str(page.url or "")
                cur_parsed = urlparse(cur_url)
                if (
                    cur_parsed.netloc == urlparse(portal_url).netloc
                    and "/login" not in cur_parsed.path.lower()
                    and cur_url != "about:blank"
                ):
                    snap = await self._extract_snapshot(page)
                    if len(snap.get("elements") or []) >= 2:
                        return {
                            "ok": True,
                            "already_logged_in": True,
                            "url": snap.get("url"),
                            "snapshot": snap,
                            "hint": "Bạn đã đăng nhập sẵn trên QLTN. Hãy gọi click_web_text hoặc click_web_element (readonly=False) để mở chức năng ngay.",
                        }
            page = await self._get_page(aid)
            await page.goto(portal_url, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(
                    "input:visible, [role='menuitem']:visible, nav:visible, main:visible",
                    timeout=15000,
                )
            except Exception:
                pass
            await page.wait_for_timeout(400)

            pwd_loc = page.locator("input[type='password']:visible")
            if await pwd_loc.count() == 0:
                legacy_toggle = page.locator("button:has-text('Mật khẩu cũ có chữ'):visible").first
                if await legacy_toggle.count() > 0:
                    await legacy_toggle.click()
                    try:
                        await page.wait_for_selector("input[type='password']:visible", timeout=5000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(200)
                    pwd_loc = page.locator("input[type='password']:visible")

            if await pwd_loc.count() > 0:
                pre_path = urlparse(page.url or "").path.lower()
                user_loc = page.locator(
                    "input[name*='user' i]:visible, input[name*='email' i]:visible, input[name*='account' i]:visible, input[placeholder*='demego' i]:visible, input[type='email']:visible, input[type='text']:visible"
                ).first
                if await user_loc.count() > 0:
                    await user_loc.fill(username)
                await pwd_loc.first.fill(password)
                await page.wait_for_timeout(200)
                submit_loc = page.locator(
                    "button[type='submit']:visible, button:has-text('Đăng nhập'):visible, button:has-text('Login'):visible"
                ).first
                if await submit_loc.count() > 0 and not await submit_loc.is_disabled():
                    await submit_loc.click()
                else:
                    await pwd_loc.first.press("Enter")

                if "/login" in pre_path:
                    try:
                        await page.wait_for_function(
                            "() => !window.location.pathname.toLowerCase().includes('/login')",
                            timeout=12000,
                        )
                    except Exception:
                        pass

            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=7000, initial_settle_ms=260, require_stable_polls=2
            )
            for dismiss_sel in (
                "button:has-text('Không nhắc lại'):visible",
                "button:has-text('Đóng'):visible",
            ):
                try:
                    btn = page.locator(dismiss_sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        await page.wait_for_timeout(180)
                except Exception:
                    pass
            await self._dismiss_hover_overlays(page)

            still_on_login = (
                "/login" in urlparse(page.url or "").path.lower()
                and await page.locator("input[type='password']:visible, input[aria-label^='OTP Input']:visible").count() > 0
            )
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                "login",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or portal_url),
            )
            extra_meta = {
                "capture_status": readiness["capture_status"],
                "screenshot_bytes": shot_bytes,
                "wait_elapsed_ms": readiness["elapsed_ms"],
            }
            if still_on_login:
                self._emit_web_event(
                    aid,
                    "login_qltn_portal",
                    f"Đăng nhập QLTN thất bại hoặc vẫn ở trang login -> {snap.get('url', portal_url)}",
                    url=str(snap.get("url") or portal_url),
                    screenshot_file=shot,
                    ok=False,
                    extra=extra_meta,
                )
                return {
                    "ok": False,
                    "error": "LOGIN_FAILED_OR_STILL_ON_LOGIN_PAGE",
                    "url": snap.get("url"),
                    "screenshot": shot,
                    "capture_status": readiness["capture_status"],
                    "snapshot": snap,
                }

            self._emit_web_event(
                aid,
                "login_qltn_portal",
                f"Đăng nhập QLTN -> {snap.get('url', portal_url)}",
                url=str(snap.get("url") or portal_url),
                screenshot_file=shot,
                extra=extra_meta,
            )
            return {
                "ok": True,
                "url": snap.get("url"),
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    def _check_click_guardrail(self, aid: int, page: Any, label_text: str) -> dict[str, Any] | None:
        if self._guardrail_mode == "READ_ONLY":
            write_terms = ("lưu", "tạo", "gửi", "xóa", "duyệt", "chốt", "save", "submit", "create", "delete", "approve")
            if any(term in label_text for term in write_terms):
                self._blocked_count[aid] = self._blocked_count.get(aid, 0) + 1
                self._emit_web_event(aid, "guardrail_block", f"READ_ONLY chặn bấm '{label_text}'", url=page.url, ok=False)
                return {"ok": False, "error": f"GUARDRAIL_BLOCKED (READ_ONLY): Bị chặn thao tác ghi '{label_text}'."}
        elif self._guardrail_mode == "SAFE_WRITE":
            for kw in self._blocked_keywords:
                if kw and kw in label_text:
                    self._blocked_count[aid] = self._blocked_count.get(aid, 0) + 1
                    self._emit_web_event(aid, "guardrail_block", f"SAFE_WRITE chặn nút nguy hiểm '{label_text}' (match '{kw}')", url=page.url, ok=False)
                    return {"ok": False, "error": f"GUARDRAIL_BLOCKED (SAFE_WRITE): Cấm bấm nút chứa từ khóa nhạy cảm '{kw}'."}
        return None

    @tool(readonly=False)
    async def click_web_element(self, agent_id: int, ref_id: str) -> dict[str, Any]:
        """Bấm nút, menu hoặc liên kết theo mã ref_id ([e1], [e2]...) trên màn hình QLTN."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        clean_ref = ref_id.strip().lstrip("[").rstrip("]")
        async with self._agent_lock(aid), self._browser_slots:
            page = await self._get_page(aid)
            loc = page.locator(f'[data-as-ref="{clean_ref}"]').first
            if await loc.count() == 0:
                await self._extract_snapshot(page)
                loc = page.locator(f'[data-as-ref="{clean_ref}"]').first
            if await loc.count() == 0:
                self._emit_web_event(
                    aid,
                    "click_web_element",
                    f"Không tìm thấy phần tử [{clean_ref}] trên màn hình",
                    url=str(page.url or ""),
                    ok=False,
                    extra={"error": "ELEMENT_NOT_FOUND", "ref_id": clean_ref},
                )
                return {"ok": False, "error": f"Không tìm thấy phần tử '{clean_ref}' trên màn hình hiện tại."}

            label_text = _norm_vi(
                (await loc.inner_text() or "")
                + " "
                + (await loc.get_attribute("aria-label") or "")
            )
            blocked = self._check_click_guardrail(aid, page, label_text)
            if blocked is not None:
                return blocked

            await loc.click()
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=4500, initial_settle_ms=260, require_stable_polls=2
            )
            await self._dismiss_hover_overlays(page)
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                f"click_{clean_ref}",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or ""),
            )
            self._emit_web_event(
                aid,
                "click_web_element",
                f"Bấm [{clean_ref}] '{label_text[:60]}' -> {snap.get('url', '')}",
                url=str(snap.get("url") or ""),
                screenshot_file=shot,
                extra={
                    "capture_status": readiness["capture_status"],
                    "screenshot_bytes": shot_bytes,
                    "wait_elapsed_ms": readiness["elapsed_ms"],
                },
            )
            return {
                "ok": True,
                "clicked": clean_ref,
                "label": label_text,
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    @tool(readonly=False)
    async def click_web_text(self, agent_id: int, text: str) -> dict[str, Any]:
        """Bấm menu, tab, nút hoặc liên kết trên màn hình QLTN dựa theo nội dung chữ hiển thị (vd: 'Phiếu yêu cầu', 'Phản ánh qua App', 'Công việc thực thi')."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"ok": False, "error": "Tham số text không được để trống."}
        async with self._agent_lock(aid), self._browser_slots:
            page = await self._get_page(aid)
            matched_label = await page.evaluate(_CLICK_BY_TEXT_JS, clean_text)
            if not matched_label:
                snap = await self._extract_snapshot(page)
                self._emit_web_event(
                    aid,
                    "click_web_text",
                    f"Không tìm thấy mục '{clean_text}' trên màn hình -> {snap.get('url', '')}",
                    url=str(snap.get("url") or page.url or ""),
                    ok=False,
                    extra={"error": "TEXT_NOT_FOUND", "target_text": clean_text},
                )
                return {
                    "ok": False,
                    "error": f"Không tìm thấy mục nào khớp '{clean_text}' trên màn hình hiện tại.",
                    "snapshot": snap,
                }

            label_text = _norm_vi(str(matched_label))
            blocked = self._check_click_guardrail(aid, page, label_text)
            if blocked is not None:
                return blocked

            loc = page.locator('[data-as-click-target="1"]').first
            if await loc.count() == 0:
                self._emit_web_event(
                    aid,
                    "click_web_text",
                    f"Phần tử khớp '{clean_text}' vừa biến mất khỏi DOM",
                    url=str(page.url or ""),
                    ok=False,
                    extra={"error": "ELEMENT_DETACHED", "target_text": clean_text},
                )
                return {"ok": False, "error": f"Phần tử khớp '{clean_text}' vừa biến mất khỏi DOM."}
            try:
                await loc.scroll_into_view_if_needed()
            except Exception:
                pass
            await loc.click()
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=4500, initial_settle_ms=260, require_stable_polls=2
            )
            await self._dismiss_hover_overlays(page)
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                "click_text",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or ""),
            )
            self._emit_web_event(
                aid,
                "click_web_text",
                f"Bấm mục '{clean_text}' ('{label_text[:50]}') -> {snap.get('url', '')}",
                url=str(snap.get("url") or ""),
                screenshot_file=shot,
                extra={
                    "capture_status": readiness["capture_status"],
                    "screenshot_bytes": shot_bytes,
                    "wait_elapsed_ms": readiness["elapsed_ms"],
                },
            )
            return {
                "ok": True,
                "clicked_text": clean_text,
                "label": label_text,
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    @tool(readonly=False)
    async def fill_web_input(self, agent_id: int, ref_id: str, value: str) -> dict[str, Any]:
        """Điền nội dung vào ô nhập liệu theo mã ref_id trên màn hình QLTN."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        clean_ref = ref_id.strip().lstrip("[").rstrip("]")
        async with self._agent_lock(aid), self._browser_slots:
            page = await self._get_page(aid)
            loc = page.locator(f'[data-as-ref="{clean_ref}"]').first
            if await loc.count() == 0:
                await self._extract_snapshot(page)
                loc = page.locator(f'[data-as-ref="{clean_ref}"]').first
            if await loc.count() == 0:
                self._emit_web_event(
                    aid,
                    "fill_web_input",
                    f"Không tìm thấy ô nhập [{clean_ref}]",
                    url=str(page.url or ""),
                    ok=False,
                    extra={"error": "ELEMENT_NOT_FOUND", "ref_id": clean_ref},
                )
                return {"ok": False, "error": f"Không tìm thấy ô nhập '{clean_ref}'."}

            input_type = (await loc.get_attribute("type") or "text").lower()
            if input_type == "password":
                return {"ok": False, "error": "Cấm nhập thủ công vào ô mật khẩu qua fill_web_input; hãy dùng login_qltn_portal."}

            meta_hint = _norm_vi(
                (await loc.get_attribute("placeholder") or "")
                + " "
                + (await loc.get_attribute("name") or "")
                + " "
                + (await loc.get_attribute("aria-label") or "")
            )
            final_val = str(value)
            if (
                self._guardrail_mode == "SAFE_WRITE"
                and self._record_prefix
                and self._record_prefix not in final_val
                and len(final_val.strip()) >= 4
                and input_type not in {"email", "tel", "number", "date", "search"}
                and any(k in meta_hint for k in ("tiêu đề", "tên", "mô tả", "nội dung", "ghi chú", "title", "subject", "description", "content", "note"))
            ):
                final_val = f"{self._record_prefix} {final_val.strip()}"

            await loc.fill(final_val)
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=1500, initial_settle_ms=150, require_stable_polls=1
            )
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                f"fill_{clean_ref}",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or ""),
            )
            self._emit_web_event(
                aid,
                "fill_web_input",
                f"Điền [{clean_ref}]: {final_val[:80]}",
                url=str(snap.get("url") or ""),
                screenshot_file=shot,
                extra={
                    "capture_status": readiness["capture_status"],
                    "screenshot_bytes": shot_bytes,
                    "wait_elapsed_ms": readiness["elapsed_ms"],
                },
            )
            return {
                "ok": True,
                "filled": clean_ref,
                "value_used": final_val,
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    @tool(readonly=False)
    async def select_web_option(self, agent_id: int, ref_id: str, option_text: str) -> dict[str, Any]:
        """Chọn giá trị trong ô select/dropdown trên màn hình QLTN."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        clean_ref = ref_id.strip().lstrip("[").rstrip("]")
        async with self._agent_lock(aid), self._browser_slots:
            page = await self._get_page(aid)
            loc = page.locator(f'[data-as-ref="{clean_ref}"]').first
            if await loc.count() == 0:
                self._emit_web_event(
                    aid,
                    "select_web_option",
                    f"Không tìm thấy phần tử [{clean_ref}]",
                    url=str(page.url or ""),
                    ok=False,
                    extra={"error": "ELEMENT_NOT_FOUND", "ref_id": clean_ref},
                )
                return {"ok": False, "error": f"Không tìm thấy phần tử '{clean_ref}'."}
            tag = (await loc.evaluate("el => el.tagName.toLowerCase()") or "").strip()
            if tag == "select":
                await loc.select_option(label=option_text)
            else:
                await loc.click()
                await page.wait_for_timeout(300)
                opt = page.get_by_text(option_text, exact=False).first
                if await opt.count() > 0:
                    await opt.click()
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=1500, initial_settle_ms=150, require_stable_polls=1
            )
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                f"select_{clean_ref}",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or ""),
            )
            self._emit_web_event(
                aid,
                "select_web_option",
                f"Chọn [{clean_ref}] -> '{option_text}'",
                url=str(snap.get("url") or ""),
                screenshot_file=shot,
                extra={
                    "capture_status": readiness["capture_status"],
                    "screenshot_bytes": shot_bytes,
                    "wait_elapsed_ms": readiness["elapsed_ms"],
                },
            )
            return {
                "ok": True,
                "selected": option_text,
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    @tool(readonly=False)
    async def navigate_web_path(self, agent_id: int, path: str) -> dict[str, Any]:
        """Điều hướng trực tiếp tới một route/path thuộc tên miền cổng QLTN đang cấu hình."""
        aid = effective_caller_agent_id(agent_id)
        ok, err = self._assert_allowed(aid)
        if not ok:
            return err
        vault = self._vault_accessor()
        creds = (vault.get("portal_credentials") or {}).get(str(aid)) or {}
        base_url = validate_external_url(str(creds.get("portal_url") or self._default_portal_url))
        target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/")) if not path.startswith("http") else validate_external_url(path)
        if urlparse(target).netloc != urlparse(base_url).netloc:
            return {"ok": False, "error": "CROSS_DOMAIN_BLOCKED: Chỉ được điều hướng trong đúng tên miền cổng QLTN cấu hình."}
        async with self._agent_lock(aid), self._browser_slots:
            page = await self._get_page(aid)
            try:
                await page.goto(target, wait_until="domcontentloaded")
            except Exception as exc:
                self._emit_web_event(
                    aid,
                    "navigate_web_path",
                    f"Chuyển trang thất bại -> {target}",
                    url=target,
                    ok=False,
                    extra={"error": str(exc)[:200]},
                )
                return {"ok": False, "error": f"NAVIGATION_FAILED: {exc}"}
            readiness = await self._wait_until_page_ready(
                page, agent_id=aid, timeout_ms=7000, initial_settle_ms=260, require_stable_polls=2
            )
            await self._dismiss_hover_overlays(page)
            self._actions_count[aid] = self._actions_count.get(aid, 0) + 1
            await self._save_context_state(aid, page)
            snap = await self._extract_snapshot(page)
            shot, shot_bytes = await self._capture_screenshot(
                aid,
                page,
                "navigate",
                capture_status=readiness["capture_status"],
                current_url=str(snap.get("url") or target),
            )
            self._emit_web_event(
                aid,
                "navigate_web_path",
                f"Chuyển trang -> {snap.get('url', target)}",
                url=str(snap.get("url") or target),
                screenshot_file=shot,
                extra={
                    "capture_status": readiness["capture_status"],
                    "screenshot_bytes": shot_bytes,
                    "wait_elapsed_ms": readiness["elapsed_ms"],
                },
            )
            return {
                "ok": True,
                "url": snap.get("url"),
                "screenshot": shot,
                "capture_status": readiness["capture_status"],
                "snapshot": snap,
            }

    async def step(self, tick: int, t: datetime):
        self.t = t
        self._step_counter += 1
        records = [
            {
                "agent_id": aid,
                "current_url": self._last_urls.get(aid, ""),
                "actions_count": self._actions_count.get(aid, 0),
                "blocked_actions_count": self._blocked_count.get(aid, 0),
            }
            for aid in sorted(self._allowed_ids)
        ]
        await self._write_agent_state_batch(self._step_counter, t, records)
        await self._write_env_state(
            self._step_counter,
            t,
            total_web_actions=sum(self._actions_count.values()),
            total_blocked_actions=sum(self._blocked_count.values()),
        )
