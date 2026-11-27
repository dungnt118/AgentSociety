import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const LIVE_BASE = process.env.E2E_LIVE_BASE_URL || 'http://127.0.0.1:5173';
const EVIDENCE_DIR =
    process.env.EVIDENCE_DIR ||
    'C:/Users/admin/.gemini/antigravity/brain/566323eb-7be7-420e-a631-ef001befa513/workflow-digital-urban-map/evidence';

function ensureEvidenceDir() {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
}

function makePngBuffer(width = 800, height = 500): Buffer {
    const crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
        let c = n;
        for (let k = 0; k < 8; k += 1) {
            c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        }
        crcTable[n] = c >>> 0;
    }
    const crc32 = (buf: Buffer): number => {
        let c = 0xffffffff;
        for (let i = 0; i < buf.length; i += 1) {
            c = crcTable[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
        }
        return (c ^ 0xffffffff) >>> 0;
    };
    const chunk = (tag: string, data: Buffer): Buffer => {
        const tagBuf = Buffer.from(tag, 'ascii');
        const lenBuf = Buffer.alloc(4);
        lenBuf.writeUInt32BE(data.length, 0);
        const crcBuf = Buffer.alloc(4);
        crcBuf.writeUInt32BE(crc32(Buffer.concat([tagBuf, data])), 0);
        return Buffer.concat([lenBuf, tagBuf, data, crcBuf]);
    };
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(width, 0);
    ihdr.writeUInt32BE(height, 4);
    ihdr[8] = 8;
    ihdr[9] = 2;
    const raw = Buffer.from([0, 220, 235, 250, 220, 235, 250, 220, 235, 250]);
    const idat = zlib.deflateSync(raw);
    return Buffer.concat([
        Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
        chunk('IHDR', ihdr),
        chunk('IDAT', idat),
        chunk('IEND', Buffer.alloc(0)),
    ]);
}

async function attachErrorCollectors(page: import('@playwright/test').Page) {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const server5xx: string[] = [];
    page.on('console', (msg) => {
        if (msg.type() === 'error') {
            consoleErrors.push(msg.text());
        }
    });
    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('response', (res) => {
        if (res.status() >= 500) {
            server5xx.push(`${res.status()} ${res.url()}`);
        }
    });
    return { consoleErrors, pageErrors, server5xx };
}

test.describe('Digital Urban Map Human-Like UAT Suite (Live Docker)', () => {
    test.setTimeout(360_000);

    test('L2-UAT-01..07: Full Human-Like UAT with Desktop 1440x900, Mobile 390x844 & Evidence Pack', async ({
        page,
        request,
    }) => {
        ensureEvidenceDir();
        const { consoleErrors, pageErrors, server5xx } = await attachErrorCollectors(page);
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.addInitScript(() => localStorage.setItem('i18nextLng', 'vi'));

        const resultsSummary: Record<string, unknown> = {
            base_url: LIVE_BASE,
            started_at: new Date().toISOString(),
        };

        // ─── L2-UAT-01: /maps Guard + Deep-link to /urban-sim?projectId=...&focus=map ───
        await page.goto(`${LIVE_BASE}/maps`, { waitUntil: 'networkidle' });
        await expect(page.getByText('Phân biệt Bản đồ Giao thông (.pb) và Bản đồ Số Khu đô thị')).toBeVisible();
        const openDigitalBtn = page.getByRole('button', { name: /Mở Bản đồ Số/i }).first();
        await expect(openDigitalBtn).toBeVisible();
        await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat01-maps-guard.png'), fullPage: true });

        // Negative API check: /maps upload .png returns 415
        const pngBuf = makePngBuffer(800, 500);
        const badUploadRes = await request.post(`${LIVE_BASE}/api/map-configs/-/upload`, {
            multipart: {
                file: {
                    name: 'floorplan.png',
                    mimeType: 'image/png',
                    buffer: pngBuf,
                },
            },
        });
        expect(badUploadRes.status()).toBe(415);

        await openDigitalBtn.click();
        await expect(page).toHaveURL(/\/urban-sim\?.*projectId=.*focus=map/);
        await expect(page.getByTestId('digital-urban-map-canvas')).toBeVisible();
        await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat01-urban-sim-deeplink.png'), fullPage: false });
        resultsSummary.uat01 = 'PASS';

        // ─── Fetch Default LLM Config for real AI Map Generation & Pilot Run ───
        const llmCfgRes = await (await request.get(`${LIVE_BASE}/api/llm-configs`)).json();
        const defaultLlmId: string | undefined = llmCfgRes?.data?.[0]?.id;

        // ─── Create a fresh test project for clean L2-UAT-02..07 (leaves MulberryLane untouched!) ───
        const tempSlug = `uat-map-${Date.now()}`;
        const createProjRes = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects`, {
            data: {
                slug: tempSlug,
                name: `UAT Bản đồ Số (${tempSlug})`,
                description: 'Dự án kiểm thử E2E Human-Like UAT',
                seed_mulberrylane_template: false,
                num_steps: 2,
                tick_seconds: 900,
                max_react_turns: 4,
                pilot_mode: true,
                enable_sociological_debrief: false,
                llm_config_id: defaultLlmId || null,
            },
        });
        expect(createProjRes.ok()).toBeTruthy();
        const tempProj = (await createProjRes.json()).project;
        const tempProjId: string = tempProj.id;
        let activeRunId: string | null = null;

        try {
            // Open temp project via deep-link
            await page.goto(`${LIVE_BASE}/urban-sim?projectId=${encodeURIComponent(tempProjId)}&focus=map`, {
                waitUntil: 'networkidle',
            });
            await expect(page.getByText('Chưa có dữ liệu Bản đồ Số')).toBeVisible();
            await expect(page.getByRole('button', { name: /AI Sinh Chốt/i })).toBeDisabled();

            // Backend dynamic 409 check on empty project
            const cp409 = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`, {
                data: { name: 'Chốt bị chặn', x_pct: 50, y_pct: 50, icon_emoji: '🛡️' },
            });
            expect(cp409.status()).toBe(409);
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat04-checkpoint-gated.png'), fullPage: false });

            // ─── L2-UAT-02: AI Digital Map (No image -> with 2D image MERGE) + F5 + DB verify ───
            await page.getByRole('button', { name: /AI Tạo Bản đồ Số/i }).click();
            const mapDialog = page.getByRole('dialog');
            await mapDialog.locator('textarea').fill(
                'Khu đô thị mới gồm 3 khu vực rõ ràng: Cổng An ninh phía Nam, Sảnh Lễ tân ở giữa và Khu Bể bơi Thể thao phía Bắc.'
            );
            await mapDialog.getByRole('button', { name: /Phân tích & Sinh Bản đồ Số/i }).click();
            await expect(mapDialog.getByText(/Đã sinh .* Khu vực Polygon/i)).toBeVisible({ timeout: 90_000 });
            await mapDialog.getByRole('button', { name: /Áp dụng \(\d+ Khu vực\)/i }).click();
            await expect(page.getByRole('button', { name: /AI Sinh Chốt/i })).toBeEnabled();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat02-ai-map-no-image.png'), fullPage: false });

            // Upload 2D image & run AI generate (Vision or transparent fallback) in MERGE
            const uploadImgRes = await request.post(
                `${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/zones/map-image`,
                {
                    multipart: {
                        file: {
                            name: 'uat-floorplan.png',
                            mimeType: 'image/png',
                            buffer: pngBuf,
                        },
                    },
                }
            );
            expect(uploadImgRes.ok()).toBeTruthy();
            await page.reload({ waitUntil: 'networkidle' });
            await page.getByRole('button', { name: /AI Tạo Bản đồ Số/i }).click();
            const mapDialog2 = page.getByRole('dialog');
            await mapDialog2.locator('textarea').fill(
                'Giữ bố cục hiện tại và bổ sung Khu Vườn dạo BBQ phía Đông Bắc.'
            );
            await mapDialog2.getByRole('button', { name: /Phân tích & Sinh Bản đồ Số/i }).click();
            await expect(mapDialog2.getByText(/Đã sinh .* Khu vực Polygon/i)).toBeVisible({ timeout: 90_000 });
            await mapDialog2.getByRole('button', { name: /Áp dụng \(\d+ Khu vực\)/i }).click();
            await page.reload({ waitUntil: 'networkidle' });
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat02-ai-map-with-image.png'), fullPage: false });

            const zonesAfterUat02 = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/zones`)).json()).items;
            expect(zonesAfterUat02.length).toBeGreaterThanOrEqual(3);
            resultsSummary.uat02 = { status: 'PASS', zones_count: zonesAfterUat02.length };

            // ─── L2-UAT-03: Unsaved Form Protection + Draw Polygon + Drag Vertex + Point-Center AI + F5 ───
            const nameField = page.getByPlaceholder(/MulberryLane/i).first();
            const sentinelText = `UAT Bản đồ Số SENTINEL_${Date.now()}`;
            await nameField.fill(sentinelText);

            const canvas = page.getByTestId('digital-urban-map-canvas');
            await canvas.scrollIntoViewIfNeeded();
            const box = await canvas.boundingBox();
            expect(box).not.toBeNull();
            const bx = box!;

            await page.getByText('Vẽ Polygon', { exact: true }).click();
            await canvas.click({ position: { x: bx.width * 0.15, y: bx.height * 0.15 } });
            await canvas.click({ position: { x: bx.width * 0.35, y: bx.height * 0.15 } });
            await canvas.click({ position: { x: bx.width * 0.35, y: bx.height * 0.35 } });
            await canvas.click({ position: { x: bx.width * 0.15, y: bx.height * 0.35 } });
            await page.getByRole('button', { name: /Hoàn tất hình/i }).click();
            const drawDlg = page.getByRole('dialog');
            await drawDlg.getByPlaceholder('vd: KHU_THE_THAO').fill('UAT_DRAWN_ZONE');
            await drawDlg.getByPlaceholder('vd: Khu Thể thao & Bể bơi').fill('Khu Tự Vẽ UAT');
            await drawDlg.getByRole('button', { name: /Lưu thành Khu vực/i }).click();
            await expect(drawDlg).toBeHidden();

            // Verify unsaved Project Form content is STILL intact (QA-FND-07)!
            await expect(nameField).toHaveValue(sentinelText);

            // Switch to Select/Drag mode, select UAT_DRAWN_ZONE, drag vertex #0, drag whole polygon, resize SE corner, then Undo (Hoàn tác) -> Auto-save verifies cleanly
            await page.getByText('Chọn / Kéo', { exact: true }).click();
            await canvas.scrollIntoViewIfNeeded();
            const drawnPoly = page.getByTestId('zone-polygon-UAT_DRAWN_ZONE');
            await drawnPoly.click({ force: true });

            // 1) Drag vertex #0 + verify auto-save
            const v0 = page.getByTestId('vertex-handle-0');
            await expect(v0).toBeVisible();
            await v0.scrollIntoViewIfNeeded();
            const v0Box = (await v0.boundingBox())!;
            await page.mouse.move(v0Box.x + v0Box.width / 2, v0Box.y + v0Box.height / 2);
            await page.mouse.down();
            await page.mouse.move(v0Box.x + 24, v0Box.y + 18, { steps: 6 });
            await page.mouse.up();
            await expect(page.getByText('Đã tự động lưu')).toBeVisible({ timeout: 15_000 });
            await expect(nameField).toHaveValue(sentinelText);

            // 2) Drag whole polygon & verify Zone Label moves synchronously
            const labelLoc = page.getByTestId('zone-label-UAT_DRAWN_ZONE');
            const labelBefore = (await labelLoc.boundingBox())!;
            const polyBoxBefore = (await drawnPoly.boundingBox())!;
            await page.mouse.move(polyBoxBefore.x + polyBoxBefore.width / 2, polyBoxBefore.y + polyBoxBefore.height / 2);
            await page.mouse.down();
            await page.mouse.move(polyBoxBefore.x + polyBoxBefore.width / 2 + 45, polyBoxBefore.y + polyBoxBefore.height / 2 + 30, { steps: 8 });
            await page.mouse.up();
            await expect(page.getByText('Đã tự động lưu')).toBeVisible({ timeout: 15_000 });
            const labelAfterDrag = (await labelLoc.boundingBox())!;
            expect(labelAfterDrag.x).toBeGreaterThan(labelBefore.x + 15);

            // 3) Resize SE corner + Undo (Hoàn tác) back to pre-resize geometry
            const polyBoxPreResize = (await drawnPoly.boundingBox())!;
            const seHandle = page.getByTestId('resize-handle-se');
            await expect(seHandle).toBeVisible();
            const seBox = (await seHandle.boundingBox())!;
            await page.mouse.move(seBox.x + seBox.width / 2, seBox.y + seBox.height / 2);
            await page.mouse.down();
            await page.mouse.move(seBox.x + 36, seBox.y + 30, { steps: 6 });
            await page.mouse.up();
            await expect(page.getByText('Đã tự động lưu')).toBeVisible({ timeout: 15_000 });
            const polyBoxResized = (await drawnPoly.boundingBox())!;
            expect(polyBoxResized.width).toBeGreaterThan(polyBoxPreResize.width + 10);

            await page.getByTestId('canvas-undo-btn').click();
            await expect(page.getByText('Đã tự động lưu')).toBeVisible({ timeout: 15_000 });
            const polyBoxAfterUndo = (await drawnPoly.boundingBox())!;
            expect(Math.abs(polyBoxAfterUndo.width - polyBoxPreResize.width)).toBeLessThan(8);
            await expect(nameField).toHaveValue(sentinelText);

            // Point-Center + AI
            await page.getByText('Điểm tâm + AI', { exact: true }).click();
            await canvas.scrollIntoViewIfNeeded();
            const bxPt = (await canvas.boundingBox())!;
            await canvas.click({ position: { x: bxPt.width * 0.72, y: bxPt.height * 0.72 } });
            const ptDlg = page.getByRole('dialog');
            await ptDlg.locator('textarea').fill('Khu tiện ích sân vườn và đường dạo nội bộ');
            await ptDlg.getByRole('button', { name: /AI Sinh Polygon/i }).click();
            await expect(ptDlg.getByText(/Kết quả dự kiến:/i)).toBeVisible({ timeout: 90_000 });
            await ptDlg.getByRole('button', { name: /Lưu thành Khu vực thật/i }).click();
            await expect(ptDlg).toBeHidden();
            await expect(nameField).toHaveValue(sentinelText);

            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat03-polygon-and-anti-lost-update.png'), fullPage: false });
            await page.reload({ waitUntil: 'networkidle' });
            const zonesAfterUat03 = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/zones`)).json()).items;
            const drawnZone = zonesAfterUat03.find((z: { zone_key: string }) => z.zone_key === 'UAT_DRAWN_ZONE');
            expect(drawnZone).toBeTruthy();
            expect(drawnZone.polygon_points.length).toBeGreaterThanOrEqual(4);
            resultsSummary.uat03 = { status: 'PASS', drawn_zone: drawnZone };

            // ─── L2-UAT-04: Manual Checkpoint + AI Batch Checkpoints + F5 + DB Check ───
            await page.getByText('Đặt Chốt', { exact: true }).click();
            const canvas2 = page.getByTestId('digital-urban-map-canvas');
            await canvas2.scrollIntoViewIfNeeded();
            const bx2 = (await canvas2.boundingBox())!;
            await canvas2.click({ position: { x: bx2.width * 0.25, y: bx2.height * 0.25 } });
            const cpDlg = page.getByRole('dialog');
            await cpDlg.getByPlaceholder('vd: Cổng An ninh Chính').fill('Chốt Kiểm tra Tự vẽ');
            await cpDlg.getByRole('button', { name: /Tạo chốt/i }).click();
            await expect(cpDlg).toBeHidden();

            await page.getByRole('button', { name: /AI Sinh Chốt/i }).click();
            const aiCpDlg = page.getByRole('dialog');
            await aiCpDlg.locator('textarea').fill('Tạo chốt tuần tra cổng an ninh, phòng gym và bể bơi ngoài trời');
            await aiCpDlg.getByRole('button', { name: /AI Sinh Chốt$/i }).click();
            await expect(aiCpDlg.getByRole('button', { name: /Lưu \d+ Chốt đã chọn/i })).toBeEnabled({ timeout: 90_000 });
            await aiCpDlg.getByRole('button', { name: /Lưu \d+ Chốt đã chọn/i }).click();
            await expect(aiCpDlg).toBeHidden();

            await page.reload({ waitUntil: 'networkidle' });
            const cpsAfterUat04 = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`)).json()).items;
            expect(cpsAfterUat04.length).toBeGreaterThanOrEqual(2);
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat04-checkpoints-saved.png'), fullPage: false });
            resultsSummary.uat04 = { status: 'PASS', checkpoints_count: cpsAfterUat04.length };

            // ─── L2-UAT-08: Drag Checkpoint Pin + Floating Bar Gắn người + Terminology Unification ───
            await page.getByText('Chọn / Kéo', { exact: true }).click();
            const firstCp = cpsAfterUat04[0];
            const firstPin = page.getByTestId(`checkpoint-pin-${firstCp.checkpoint_key}`);
            await firstPin.scrollIntoViewIfNeeded();
            const pinBox = (await firstPin.boundingBox())!;
            await page.mouse.move(pinBox.x + pinBox.width / 2, pinBox.y + pinBox.height / 2);
            await page.mouse.down();
            await page.mouse.move(pinBox.x + 48, pinBox.y + 26, { steps: 6 });
            await page.mouse.up();
            await expect(page.getByText('Đã tự động lưu')).toBeVisible({ timeout: 15_000 });
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat08-canvas-drag-resize-undo.png'), fullPage: false });

            // Verify dragged checkpoint persisted in DB after F5
            await page.reload({ waitUntil: 'networkidle' });
            const cpsAfterDrag = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`)).json()).items;
            const movedCpObj = cpsAfterDrag.find((c: { id: string }) => c.id === firstCp.id);
            expect(Math.abs(movedCpObj.x_pct - firstCp.x_pct) + Math.abs(movedCpObj.y_pct - firstCp.y_pct)).toBeGreaterThan(0.5);

            // Seed Persona #10 (inactive during Pilot run) to test Floating Bar "Gắn người" & Profile Traits
            const otherZoneKey = zonesAfterUat03.find((z: { zone_key: string }) => z.zone_key !== 'UAT_DRAWN_ZONE')?.zone_key || 'UAT_DRAWN_ZONE';
            const p10Res = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/personas`, {
                data: {
                    agent_id: 10,
                    full_name: 'Kỹ sư Gắn Khu vực UAT',
                    role_code: 'BQL_TECH',
                    role_title: 'Kỹ sư M&E',
                    department: 'Kỹ thuật',
                    group_type: 'BQL',
                    software_access_enabled: false,
                    is_pilot_member: false,
                    is_active: false,
                    home_zone: otherZoneKey,
                    domain_knowledge_prompt: 'Kiểm tra kỹ thuật khu đô thị.',
                },
            });
            expect(p10Res.ok()).toBeTruthy();
            const p10Id: string = (await p10Res.json()).persona.id;
            await page.reload({ waitUntil: 'networkidle' });

            // Click unobstructed interior of Polygon -> Floating Bar -> Gắn người -> F5 -> DB verify
            const targetPoly3 = page.getByTestId('zone-polygon-UAT_DRAWN_ZONE');
            await targetPoly3.scrollIntoViewIfNeeded();
            const pb3 = (await targetPoly3.boundingBox())!;
            await targetPoly3.click({ position: { x: Math.min(24, pb3.width * 0.25), y: Math.max(18, pb3.height - 22) } });
            const floatBar = page.getByTestId('canvas-zone-floating-bar');
            await expect(floatBar).toBeVisible();
            await floatBar.getByRole('button', { name: /Gắn người/i }).click();
            const assignDlg = page.getByRole('dialog');
            await assignDlg.locator('.ant-select').first().click();
            await page.locator('.ant-select-item-option-content', { hasText: 'Kỹ sư Gắn Khu vực UAT' }).first().click();
            await page.keyboard.press('Escape');
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat08-floating-assign-persona.png'), fullPage: false });
            await assignDlg.getByRole('button', { name: /Lưu gắn người/i }).click();
            await expect(assignDlg).toBeHidden();

            await page.reload({ waitUntil: 'networkidle' });
            const personasAfterAssign = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/personas`)).json()).items;
            const p10Updated = personasAfterAssign.find((p: { id: string }) => p.id === p10Id);
            expect(p10Updated.home_zone).toBe('UAT_DRAWN_ZONE');

            // Verify unified Vietnamese "Khu vực" terminology (zero legacy Zone strings in UI)
            await expect(page.getByText(/Quản lý Khu vực \(\d+\)/i)).toBeVisible();
            const bodyTxt = await page.locator('body').innerText();
            for (const banned of ['Lưới Thẻ Zone', 'Ngoài Zone', 'Chưa thuộc Zone', 'Sửa chi tiết Zone', 'Lưu thành Zone']) {
                expect(bodyTxt).not.toContain(banned);
            }
            resultsSummary.uat08 = { status: 'PASS', assigned_home_zone: p10Updated.home_zone };

            // ─── L2-UAT-09: Top-Level "Kỹ năng Agent" (/skills) Menu & Persona Skills/Profile Traits ───
            await expect(page.getByRole('menuitem', { name: /Kỹ năng Agent/i })).toBeVisible();
            await expect(page.locator('a[href="/agents"], a[href="/profiles"], a[href="/agent-templates"]')).toHaveCount(0);
            await page.getByRole('menuitem', { name: /Kỹ năng Agent/i }).click();
            await expect(page).toHaveURL(/\/skills/);
            await expect(page.getByText(/Ma trận Nhân sự & Cư dân/i).first()).toBeVisible();

            await page.goto(`${LIVE_BASE}/urban-sim/${tempProjId}/personas`, { waitUntil: 'networkidle' });
            const targetRow = page.locator('tr', { hasText: 'Kỹ sư Gắn Khu vực UAT' });
            await targetRow.getByRole('button', { name: /Sửa/i }).click();
            const drawer = page.getByRole('dialog').filter({ hasText: 'Cấu hình Persona' });
            await expect(drawer).toBeVisible();
            await drawer.getByPlaceholder('vd: 34').fill('35');
            await drawer.getByPlaceholder('vd: Kỹ sư phần mềm').fill('Kỹ sư QA Cao cấp');
            await drawer.getByPlaceholder(/Sáng 07:00/i).fill('Tuần tra lúc 08:00');
            await drawer.getByPlaceholder('vd: 👮').fill('🕵️');
            // Select default activated skill
            const skillSelect = drawer.locator('.ant-form-item', { hasText: 'Kỹ năng kích hoạt mặc định cho nhân vật' }).locator('.ant-select').first();
            await skillSelect.click();
            await page.locator('.ant-select-item-option-content', { hasText: 'daily-guidance' }).first().click();
            await page.keyboard.press('Escape');
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat09-skills-and-persona-traits.png'), fullPage: false });
            await drawer.getByRole('button', { name: /Lưu thay đổi/i }).click();
            await expect(drawer).toBeHidden();

            await page.reload({ waitUntil: 'networkidle' });
            const personasAfterSkills = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/personas`)).json()).items;
            const p10Traits = personasAfterSkills.find((p: { id: string }) => p.id === p10Id);
            expect(p10Traits.default_activated_skill_ids).toContain('built-in@daily-guidance');
            expect(p10Traits.profile_traits?.occupation).toBe('Kỹ sư QA Cao cấp');
            expect(p10Traits.avatar_icon).toBe('🕵️');
            resultsSummary.uat09 = {
                status: 'PASS',
                skills: p10Traits.default_activated_skill_ids,
                occupation: p10Traits.profile_traits?.occupation,
                avatar_icon: p10Traits.avatar_icon,
            };

            // ─── L2-UAT-07: System Backup & Restore (REPLACE_SCOPE) preserving Digital Map + Checkpoints ───
            const exportRes = await request.post(`${LIVE_BASE}/api/v1/system-backup/export`, {
                data: {
                    scopes: ['urban_sim_projects', 'urban_sim_zones'],
                    include_secrets: false,
                    project_ids: [tempProjId],
                },
            });
            expect(exportRes.ok()).toBeTruthy();
            const zipBuffer = Buffer.from(await exportRes.body());
            await request.delete(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints/${cpsAfterUat04[0].id}`);
            const afterDelCount = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`)).json()).items.length;
            expect(afterDelCount).toBe(cpsAfterUat04.length - 1);

            const restoreRes = await request.post(`${LIVE_BASE}/api/v1/system-backup/restore`, {
                multipart: {
                    file: { name: 'uat-backup.zip', mimeType: 'application/zip', buffer: zipBuffer },
                    selected_scopes_json: JSON.stringify(['urban_sim_zones']),
                    mode: 'REPLACE_SCOPE',
                    restore_secrets: 'false',
                    create_pre_restore_snapshot: 'false',
                },
            });
            expect(restoreRes.ok()).toBeTruthy();
            const restoredCps = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`)).json()).items;
            expect(restoredCps.length).toBe(cpsAfterUat04.length);
            await page.goto(`${LIVE_BASE}/system-backup`, { waitUntil: 'networkidle' });
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat07-backup-restore.png'), fullPage: false });
            resultsSummary.uat07 = { status: 'PASS', restored_checkpoints_count: restoredCps.length };

            // Mobile 390px Edit check
            await page.setViewportSize({ width: 390, height: 844 });
            await page.goto(`${LIVE_BASE}/urban-sim?projectId=${encodeURIComponent(tempProjId)}&focus=map`, {
                waitUntil: 'networkidle',
            });
            const editOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= 390);
            expect(editOverflow).toBeTruthy();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat06-mobile-390px-edit.png'), fullPage: false });

            // ─── L2-UAT-05 & L2-UAT-06: Real Fresh Pilot Run, Movement T0->T1->T2, Snapshot Isolation, Mobile Drawer & P95 ───
            await page.setViewportSize({ width: 1440, height: 900 });

            // Ensure standard CP_GATE_MAIN & CP_POOL checkpoints exist on tempProjId
            const currentCps = (await (await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`)).json()).items as Array<{
                checkpoint_key: string;
            }>;
            if (!currentCps.some((c) => c.checkpoint_key === 'CP_GATE_MAIN')) {
                const mkGate = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`, {
                    data: {
                        checkpoint_key: 'CP_GATE_MAIN',
                        name: 'Chốt Trực Cổng Chính',
                        x_pct: 20,
                        y_pct: 82,
                        icon_emoji: '🛡️',
                        category: 'security',
                        description_md: '### Chốt Trực Cổng Chính\n- Kiểm soát an ninh ra vào 24/7\n- Bàn giao ca trực và tuần tra định kỳ',
                    },
                });
                expect(mkGate.ok()).toBeTruthy();
            }
            if (!currentCps.some((c) => c.checkpoint_key === 'CP_POOL')) {
                const mkPool = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`, {
                    data: {
                        checkpoint_key: 'CP_POOL',
                        name: 'Khu Bể bơi Ngoài trời',
                        x_pct: 75,
                        y_pct: 28,
                        icon_emoji: '🏊',
                        category: 'amenity',
                        description_md: '### Khu Bể bơi Ngoài trời\n- Tiện ích thư giãn của cư dân\n- Kiểm tra an toàn mặt nước',
                    },
                });
                expect(mkPool.ok()).toBeTruthy();
            }

            // Seed 2 lightweight Pilot personas on tempProjId
            const homeZoneKey = zonesAfterUat03[0]?.zone_key || 'UAT_DRAWN_ZONE';
            const p1Res = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/personas`, {
                data: {
                    agent_id: 1,
                    full_name: 'NV An ninh UAT',
                    role_code: 'BQL_SECURITY',
                    role_title: 'Nhân viên An ninh',
                    department: 'An ninh',
                    group_type: 'BQL',
                    software_access_enabled: false,
                    is_pilot_member: true,
                    is_active: true,
                    home_zone: homeZoneKey,
                    domain_knowledge_prompt:
                        "Bạn là Nhân viên An ninh đang tuần tra khu đô thị. Ngay bước đầu tiên HÃY GỌI công cụ `move_to_checkpoint` tới `'CP_GATE_MAIN'` với `activity='Tuần tra cổng chính'`, sau đó tiếp tục di chuyển tới `'CP_POOL'`.",
                    initial_tasks: ['Tuần tra chốt CP_GATE_MAIN và CP_POOL'],
                },
            });
            expect(p1Res.ok()).toBeTruthy();

            const p2Res = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/personas`, {
                data: {
                    agent_id: 2,
                    full_name: 'Cư dân UAT',
                    role_code: 'RESIDENT_OWNER',
                    role_title: 'Cư dân Chủ hộ',
                    department: 'Cư dân',
                    group_type: 'RESIDENT',
                    software_access_enabled: false,
                    is_pilot_member: true,
                    is_active: true,
                    home_zone: homeZoneKey,
                    domain_knowledge_prompt:
                        "Bạn là Cư dân đi dạo buổi chiều trong khuôn viên. Ngay bước đầu tiên HÃY GỌI công cụ `move_to_checkpoint` tới `'CP_POOL'` với `activity='Đi dạo quanh bể bơi'`.",
                    initial_tasks: ['Đi dạo khu vực CP_POOL'],
                },
            });
            expect(p2Res.ok()).toBeTruthy();

            // Start real Pilot Run!
            const startRes = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/start`);
            expect(startRes.ok()).toBeTruthy();
            const startedRun = (await startRes.json()).run;
            const runId: string = startedRun.id;
            activeRunId = runId;

            await page.goto(`${LIVE_BASE}/urban-sim/${tempProjId}/runs/${runId}/monitor`, {
                waitUntil: 'networkidle',
            });
            const clockEl = page.getByTestId('continuous-sim-clock');
            await expect(clockEl).toBeVisible();
            const clockT1 = (await clockEl.innerText()).trim();
            expect(clockT1).toMatch(/^\d{2}:\d{2}:\d{2}$/);
            await expect(page.getByText(/Chạy liên tục ·/i)).toBeVisible();
            await page.waitForTimeout(2300);
            const clockT2 = (await clockEl.innerText()).trim();
            expect(clockT2).toMatch(/^\d{2}:\d{2}:\d{2}$/);
            expect(clockT2).not.toBe(clockT1);

            const liveCanvas = page.getByTestId('digital-urban-map-canvas');
            await expect(liveCanvas).toBeVisible();
            await liveCanvas.scrollIntoViewIfNeeded();
            await expect(page.getByTestId('live-agent-icon-1')).toBeVisible();
            await expect(page.getByTestId('live-agent-name-1')).toBeVisible();
            await expect(page.getByTestId('live-agent-icon-2')).toBeVisible();
            await expect(page.getByTestId('live-agent-name-2')).toBeVisible();
            const icon1Text = (await page.getByTestId('live-agent-icon-1').innerText()).trim();
            expect(icon1Text.length).toBeGreaterThan(0);
            expect(/^\d+$/.test(icon1Text)).toBeFalsy();

            // Toggle 'Tên Agent' switch off -> name badge hidden, then back on -> name badge visible
            const toggleNames = page.getByTestId('live-toggle-agent-names');
            await toggleNames.click();
            await expect(page.getByTestId('live-agent-name-1')).toBeHidden();
            await toggleNames.click();
            await expect(page.getByTestId('live-agent-name-1')).toBeVisible();

            await clockEl.scrollIntoViewIfNeeded();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat10-icon-names-continuous-clock.png'), fullPage: false });
            await liveCanvas.scrollIntoViewIfNeeded();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat05-live-T0.png'), fullPage: false });

            // Poll live /state until genuine movement is emitted (max 120s)
            let movementObserved = false;
            let liveStateData: Record<string, unknown> | null = null;
            const deadline = Date.now() + 120_000;
            while (Date.now() < deadline) {
                const stRes = await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`);
                expect(stRes.ok()).toBeTruthy();
                const st = await stRes.json();
                liveStateData = st;
                const recentMoves = Array.isArray(st.recent_movements) ? st.recent_movements : [];
                const movedAgent = Array.isArray(st.agent_statuses)
                    ? st.agent_statuses.some((a: { current_checkpoint_key?: string | null }) => Boolean(a.current_checkpoint_key))
                    : false;
                if (recentMoves.length > 0 || movedAgent) {
                    movementObserved = true;
                    break;
                }
                if (st.run?.status === 'FAILED') {
                    throw new Error(`Real Pilot Run FAILED before movement: ${JSON.stringify(st.run)}`);
                }
                if (st.run?.status === 'COMPLETED' && !movementObserved) {
                    throw new Error('Real Pilot Run COMPLETED without any move_to_checkpoint / move_to_zone event!');
                }
                await page.waitForTimeout(2500);
            }
            expect(movementObserved).toBeTruthy();

            // Wait 3.5s for RunMonitorPage polling overlay, scroll canvas cleanly, then capture T1
            await page.waitForTimeout(3500);
            await liveCanvas.scrollIntoViewIfNeeded();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat05-live-T1.png'), fullPage: false });

            // Click checkpoint pin on Live canvas -> Popover Markdown (normal click, proving zero agent overlap!)
            const cpGatePin = page.getByTestId('checkpoint-pin-CP_GATE_MAIN');
            await cpGatePin.scrollIntoViewIfNeeded();
            await cpGatePin.click();
            await expect(page.locator('.ant-popover').getByText(/Chốt Trực Cổng Chính/i).first()).toBeVisible();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat05-live-T1-checkpoint-md.png'), fullPage: false });
            await page.keyboard.press('Escape');

            // Wait 5s for further live progression, capture T2
            await page.waitForTimeout(5000);
            await liveCanvas.scrollIntoViewIfNeeded();
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat05-live-T2.png'), fullPage: false });

            // Click a Live agent marker -> opens PersonaTimelineDrawer
            const firstMarker = page.locator('[data-testid^="live-agent-marker-"]').first();
            await expect(firstMarker).toBeVisible();
            await firstMarker.scrollIntoViewIfNeeded();
            await firstMarker.click();
            await expect(page.getByText(/Hành trình & Tư duy/i)).toBeVisible();
            await page.waitForTimeout(450);
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat05-live-T2-timeline.png'), fullPage: false });
            await page.keyboard.press('Escape');

            // Persist real snapshot + events sample into EVIDENCE_DIR
            const eventsSample = await (
                await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/events?limit=50`)
            ).json();
            const stateBeforeMutation = await (
                await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`)
            ).json();
            fs.writeFileSync(
                path.join(EVIDENCE_DIR, 'run-snapshot-and-events-sample.json'),
                JSON.stringify({ run_id: runId, state: stateBeforeMutation, events: eventsSample }, null, 2),
                'utf-8'
            );

            // Pause run if still running so cleanup is safe
            if (['STARTING', 'RUNNING'].includes(stateBeforeMutation?.run?.status)) {
                await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/pause`);
                for (let w = 0; w < 15; w += 1) {
                    const chk = await (
                        await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`)
                    ).json();
                    if (!['STARTING', 'RUNNING'].includes(chk?.run?.status)) break;
                    await page.waitForTimeout(1500);
                }
            }
            activeRunId = null;

            // Verify Snapshot Isolation (INV-07): mutate project zones/checkpoints -> Run state must NOT change!
            const zonesBefore = JSON.stringify(stateBeforeMutation.zones.map((z: { polygon_points?: unknown }) => z.polygon_points));
            const mkMutatedCp = await request.post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/checkpoints`, {
                data: {
                    checkpoint_key: 'CP_MUTATED_AFTER_RUN',
                    name: 'Chốt Thêm Sau Run',
                    x_pct: 50,
                    y_pct: 50,
                    icon_emoji: '🚨',
                },
            });
            expect(mkMutatedCp.ok()).toBeTruthy();
            const zoneToMutate = zonesAfterUat03[0];
            await request.patch(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/zones/${zoneToMutate.id}`, {
                data: {
                    polygon_points: [
                        [10, 10],
                        [90, 10],
                        [90, 90],
                        [10, 90],
                    ],
                },
            });
            const stateAfterMutation = await (
                await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`)
            ).json();
            const hasMutatedCpInRun = (stateAfterMutation.checkpoints || []).some(
                (c: { checkpoint_key: string }) => c.checkpoint_key === 'CP_MUTATED_AFTER_RUN'
            );
            expect(hasMutatedCpInRun).toBe(false);
            const zonesAfter = JSON.stringify(stateAfterMutation.zones.map((z: { polygon_points?: unknown }) => z.polygon_points));
            expect(zonesAfter).toBe(zonesBefore);

            // P95 benchmark on Live Run /state endpoint (25 calls)
            const latencies: number[] = [];
            for (let i = 0; i < 25; i += 1) {
                const t0 = performance.now();
                const r = await request.get(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`);
                expect(r.ok()).toBeTruthy();
                latencies.push(performance.now() - t0);
            }
            latencies.sort((a, b) => a - b);
            const p50Ms = latencies[Math.floor(latencies.length * 0.5)];
            const p95Ms = latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * 0.95))];
            const maxMs = latencies[latencies.length - 1];
            expect(p95Ms).toBeLessThanOrEqual(150);
            fs.writeFileSync(
                path.join(EVIDENCE_DIR, 'l2-perf-p95.json'),
                JSON.stringify(
                    {
                        endpoint: `/api/v1/urban-sim/projects/${tempProjId}/runs/${runId}/state`,
                        samples: latencies.length,
                        p50_ms: Number(p50Ms.toFixed(2)),
                        p95_ms: Number(p95Ms.toFixed(2)),
                        max_ms: Number(maxMs.toFixed(2)),
                        threshold_ms: 150,
                        passed: p95Ms <= 150,
                    },
                    null,
                    2
                ),
                'utf-8'
            );

            // Mobile 390x844 Live Monitor + Bottom Drawer check
            await page.setViewportSize({ width: 390, height: 844 });
            await page.reload({ waitUntil: 'networkidle' });
            const liveOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= 390);
            expect(liveOverflow).toBeTruthy();
            const cpPoolPin = page.getByTestId('checkpoint-pin-CP_POOL');
            await cpPoolPin.scrollIntoViewIfNeeded();
            await cpPoolPin.click();
            await expect(page.locator('.ant-drawer-bottom')).toBeVisible();
            await page.waitForTimeout(450);
            await page.screenshot({ path: path.join(EVIDENCE_DIR, 'uat06-mobile-390px-live.png'), fullPage: false });

            resultsSummary.uat05_06 = {
                status: 'PASS',
                run_id: runId,
                run_status: stateAfterMutation?.run?.status || liveStateData?.run,
                movement_observed: movementObserved,
                recent_movements_count: (stateBeforeMutation?.recent_movements || []).length,
                snapshot_isolation: 'PASS',
                p50_state_ms: Number(p50Ms.toFixed(2)),
                p95_state_ms: Number(p95Ms.toFixed(2)),
            };
            resultsSummary.console_errors = consoleErrors;
            resultsSummary.page_errors = pageErrors;
            resultsSummary.server_5xx = server5xx;

            fs.writeFileSync(
                path.join(EVIDENCE_DIR, 'uat-playwright-summary.json'),
                JSON.stringify(resultsSummary, null, 2),
                'utf-8'
            );

            expect(consoleErrors).toEqual([]);
            expect(pageErrors).toEqual([]);
            expect(server5xx).toEqual([]);
        } finally {
            if (activeRunId) {
                await request
                    .post(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}/runs/${activeRunId}/pause`)
                    .catch(() => {});
            }
            await request.delete(`${LIVE_BASE}/api/v1/urban-sim/projects/${tempProjId}`).catch(() => {});
        }
    });
});
