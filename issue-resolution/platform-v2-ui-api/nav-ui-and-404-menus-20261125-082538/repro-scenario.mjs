#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseArgs() {
  const args = process.argv.slice(2);
  let phase = process.env.ISSUE_PHASE || 'before';
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '--phase' && args[i + 1]) {
      phase = args[i + 1];
      i += 1;
    }
  }
  if (!['before', 'after'].includes(phase)) {
    throw new Error(`Invalid --phase: ${phase}`);
  }
  return { phase };
}

function loadEnvFile(envPath) {
  const result = {};
  if (!fs.existsSync(envPath)) return result;
  for (const rawLine of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    result[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return result;
}

const API_ENDPOINTS = [
  '/api/llm-configs',
  '/api/map-configs',
  '/api/agent-configs',
  '/api/agent-templates',
  '/api/agent-profiles',
  '/api/agent-classes?agent_type=citizen',
  '/api/agent-blocks',
  '/api/community/workflow/functions',
  '/api/workflow-configs',
  '/api/experiments',
  '/api/surveys',
];

const PLAYWRIGHT_PY = String.raw`
import base64
import json
import os
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("DOCKER_GATEWAY_URL", "http://gateway:5173")
DESKTOP_ROUTES = ["/maps", "/llms", "/agents", "/workflows", "/console", "/survey", "/urban-sim"]
MOBILE_ROUTES = ["/maps", "/console", "/urban-sim"]

report = {
    "base_url": BASE_URL,
    "nav_geometry": None,
    "desktop": {},
    "mobile": {},
    "screenshots": {},
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # Desktop 1440x900
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="vi-VN")
    page = context.new_page()

    for route in DESKTOP_ROUTES:
        failed_requests = []
        console_errors = []
        page_errors = []

        def on_response(resp, bucket=failed_requests):
            if resp.status >= 400 and "/api/" in resp.url:
                bucket.append({"url": resp.url, "status": resp.status})

        def on_console(msg, bucket=console_errors):
            if msg.type == "error":
                bucket.append(msg.text)

        def on_pageerror(err, bucket=page_errors):
            bucket.append(str(err))

        page.on("response", on_response)
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        page.goto(f"{BASE_URL}{route}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(900)

        toasts = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.ant-message-error, .ant-message-notice-error'))
                .map(el => (el.innerText || '').trim())
                .filter(Boolean);
        }""")

        if route == "/maps":
            geom = page.evaluate("""() => {
                const header = document.querySelector('.ant-layout-header');
                const menu = document.querySelector('.ant-layout-header .ant-menu-horizontal');
                const h = header ? header.getBoundingClientRect() : null;
                const m = menu ? menu.getBoundingClientRect() : null;
                const items = Array.from(document.querySelectorAll('.ant-layout-header .ant-menu-horizontal > li'))
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return { text: (el.innerText || '').trim(), top: r.top, bottom: r.bottom, height: r.height, width: r.width };
                    });
                return {
                    header: h ? { top: h.top, bottom: h.bottom, height: h.height, width: h.width } : null,
                    menu: m ? { top: m.top, bottom: m.bottom, height: m.height, width: m.width } : null,
                    items,
                };
            }""")
            report["nav_geometry"] = geom

        shot_key = route.strip("/") + "-desktop.png"
        if route in ["/maps", "/llms", "/console", "/urban-sim"]:
            raw_png = page.screenshot(full_page=False)
            report["screenshots"][shot_key] = base64.b64encode(raw_png).decode("ascii")

        report["desktop"][route] = {
            "failed_requests": failed_requests,
            "error_toasts": toasts,
            "console_errors": console_errors,
            "page_errors": page_errors,
        }

        page.remove_listener("response", on_response)
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)

    context.close()

    # Mobile 390x844
    m_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="vi-VN")
    m_page = m_context.new_page()
    for route in MOBILE_ROUTES:
        failed_requests = []

        def on_m_resp(resp, bucket=failed_requests):
            if resp.status >= 400 and "/api/" in resp.url:
                bucket.append({"url": resp.url, "status": resp.status})

        m_page.on("response", on_m_resp)
        m_page.goto(f"{BASE_URL}{route}", wait_until="networkidle", timeout=30000)
        m_page.wait_for_timeout(900)
        metrics = m_page.evaluate("""() => ({
            docScrollWidth: document.documentElement.scrollWidth,
            innerWidth: window.innerWidth,
        })""")
        shot_key = route.strip("/") + "-mobile-390.png"
        if route in ["/maps", "/console"]:
            raw_png = m_page.screenshot(full_page=False)
            report["screenshots"][shot_key] = base64.b64encode(raw_png).decode("ascii")
        report["mobile"][route] = {
            "docScrollWidth": metrics["docScrollWidth"],
            "innerWidth": metrics["innerWidth"],
            "overflow": metrics["docScrollWidth"] > 390,
            "failed_requests": failed_requests,
        }
        m_page.remove_listener("response", on_m_resp)

    m_context.close()
    browser.close()

print(json.dumps(report, ensure_ascii=False))
`;

async function main() {
  const { phase } = parseArgs();
  const envVars = loadEnvFile(path.join(__dirname, 'issue.env'));
  const frontendBaseUrl = envVars.FRONTEND_BASE_URL || 'http://127.0.0.1:5173';
  const dockerGatewayUrl = envVars.DOCKER_GATEWAY_URL || 'http://gateway:5173';
  const workspaceRoot = path.resolve(__dirname, '..', '..', '..');
  const composeFile = path.join(workspaceRoot, envVars.DOCKER_COMPOSE_FILE || 'docker-compose.local.yml');

  const phaseDir = path.join(__dirname, 'artifacts', phase);
  const payloadsDir = path.join(phaseDir, 'payloads');
  const logsDir = path.join(phaseDir, 'logs');
  const shotsDir = path.join(phaseDir, 'screenshots');
  fs.mkdirSync(payloadsDir, { recursive: true });
  fs.mkdirSync(logsDir, { recursive: true });
  fs.mkdirSync(shotsDir, { recursive: true });

  // 1. Check all 11 API endpoints from host
  const apiResults = [];
  for (const endpoint of API_ENDPOINTS) {
    const url = `${frontendBaseUrl}${endpoint}`;
    try {
      const resp = await fetch(url);
      const text = await resp.text();
      let parsed = null;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
      const hasDataArray = Boolean(parsed && Array.isArray(parsed.data));
      apiResults.push({
        endpoint,
        status: resp.status,
        hasDataArray,
        count: hasDataArray ? parsed.data.length : null,
        snippet: text.slice(0, 220),
        passed: resp.status === 200 && hasDataArray,
      });
    } catch (err) {
      apiResults.push({
        endpoint,
        status: 0,
        hasDataArray: false,
        count: null,
        snippet: String(err),
        passed: false,
      });
    }
  }
  fs.writeFileSync(
    path.join(payloadsDir, 'api-endpoints-check.json'),
    JSON.stringify(apiResults, null, 2),
    'utf8',
  );

  // 2. Run Playwright browser checks inside backend container against gateway:5173
  const pwRun = spawnSync(
    'docker',
    ['exec', '-i', '-e', `DOCKER_GATEWAY_URL=${dockerGatewayUrl}`, 'agentsociety-backend-1', 'python', '-'],
    {
      input: PLAYWRIGHT_PY,
      encoding: 'utf8',
      maxBuffer: 50 * 1024 * 1024,
    },
  );
  if (pwRun.status !== 0) {
    console.error('Playwright execution failed:', pwRun.stderr);
    process.exit(2);
  }
  const uiReport = JSON.parse(pwRun.stdout);
  for (const [name, b64] of Object.entries(uiReport.screenshots || {})) {
    fs.writeFileSync(path.join(shotsDir, name), Buffer.from(b64, 'base64'));
  }
  delete uiReport.screenshots;
  fs.writeFileSync(
    path.join(payloadsDir, 'ui-nav-audit.json'),
    JSON.stringify(uiReport, null, 2),
    'utf8',
  );

  // 3. Collect Docker container logs
  let logOutput = '';
  try {
    logOutput = execFileSync(
      'docker',
      ['compose', '-f', composeFile, 'logs', 'backend', '--tail', '80'],
      { encoding: 'utf8' },
    );
  } catch (err) {
    logOutput = String(err);
  }
  fs.writeFileSync(path.join(logsDir, 'backend-logs.txt'), logOutput, 'utf8');

  // 4. Evaluate Healthy Oracle assertions
  const failures = [];
  for (const r of apiResults) {
    if (!r.passed) {
      failures.push(`API ${r.endpoint} failed: HTTP ${r.status} (hasDataArray=${r.hasDataArray}) body=${r.snippet}`);
    }
  }

  const geom = uiReport.nav_geometry || {};
  const header = geom.header;
  const menu = geom.menu;
  if (!header || !menu) {
    failures.push('NAV geometry missing header or horizontal menu element');
  } else {
    if (Math.abs(menu.height - header.height) > 1) {
      failures.push(`NAV height mismatch: header=${header.height}, menu=${menu.height}`);
    }
    if (menu.bottom > header.bottom + 1 || menu.top < header.top - 1) {
      failures.push(`NAV vertical overflow: header=[${header.top},${header.bottom}], menu=[${menu.top},${menu.bottom}]`);
    }
  }

  for (const [route, info] of Object.entries(uiReport.desktop || {})) {
    if ((info.failed_requests || []).length > 0) {
      failures.push(`Desktop ${route} HTTP >= 400: ${JSON.stringify(info.failed_requests)}`);
    }
    if ((info.error_toasts || []).length > 0) {
      failures.push(`Desktop ${route} error toast: ${JSON.stringify(info.error_toasts)}`);
    }
    if ((info.page_errors || []).length > 0) {
      failures.push(`Desktop ${route} uncaught page errors: ${JSON.stringify(info.page_errors)}`);
    }
  }

  for (const [route, info] of Object.entries(uiReport.mobile || {})) {
    if (info.overflow) {
      failures.push(`Mobile 390px ${route} horizontal overflow: scrollWidth=${info.docScrollWidth}`);
    }
    if ((info.failed_requests || []).length > 0) {
      failures.push(`Mobile 390px ${route} HTTP >= 400: ${JSON.stringify(info.failed_requests)}`);
    }
  }

  const summary = {
    phase,
    passed: failures.length === 0,
    apiPassedCount: apiResults.filter((x) => x.passed).length,
    apiTotalCount: apiResults.length,
    navHeader: header,
    navMenu: menu,
    failureCount: failures.length,
    failures,
  };
  console.log(JSON.stringify(summary, null, 2));
  process.exit(failures.length === 0 ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
