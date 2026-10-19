import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
const root = path.resolve(import.meta.dirname, '..');
const require = createRequire(path.join(root, 'web/package.json'));
const { chromium } = require('@playwright/test');
// The queue permits two hours by default; a one-hour browser deadline can
// abandon a healthy cold-worker run. Validate overrides before any submission.
const generationTimeoutSeconds = Number(process.env.TEST_GENERATION_TIMEOUT_SECONDS ?? 7500);
if (!Number.isSafeInteger(generationTimeoutSeconds) || generationTimeoutSeconds < 60 || generationTimeoutSeconds > 21900) {
  throw Error('TEST_GENERATION_TIMEOUT_SECONDS must be an integer from 60 to 21900');
}
const access = JSON.parse((await fs.readFile(path.join(root, '.runtime/cloud-browser-access.json'), 'utf8')).replace(/^\uFEFF/, ''));
const localOrigin = process.env.TEST_ORIGIN;
if (localOrigin && !/^http:\/\/127\.0\.0\.1:\d+$/.test(localOrigin)) throw Error('TEST_ORIGIN must be loopback');
if (localOrigin) access.origin = localOrigin;
const out = path.join(root, process.env.TEST_OUTPUT || '.runtime/cloud-browser-e2e');
await fs.mkdir(out, { recursive: true });
const report = { started_at: new Date().toISOString(), generation_timeout_seconds: generationTimeoutSeconds, checks: {}, stages: [], errors: [], ranges: [] };
const responseDetails = [];
const save = () => fs.writeFile(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
const check = (name, value) => { report.checks[name] = !!value; if (!value) throw Error(`Check failed: ${name}`); };
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 960 } });
const page = await context.newPage();
page.setDefaultTimeout(180000);
page.on('pageerror', e => report.errors.push(e.message));
page.on('response', r => {
  const pathname = new URL(r.url()).pathname;
  if (!pathname.endsWith('/scene.glb')) return;
  const entry = { pathname, status: r.status(), range: r.request().headers().range ?? null };
  report.ranges.push(entry);
  if (r.status() >= 400) {
    responseDetails.push((async () => {
      let timer;
      try {
        const body = await Promise.race([r.text(), new Promise(resolve => {
          timer = setTimeout(() => resolve('Response body unavailable within 2 seconds'), 2000);
        })]);
        entry.error_body = body.replaceAll(access.access_token, '[REDACTED]').replaceAll(access.access_url, '[PRIVATE URL]').slice(0, 500);
      } catch { entry.error_body = 'Response body unavailable'; }
      finally { clearTimeout(timer); }
    })());
  }
});
try {
  await page.goto(access.origin, { waitUntil: 'domcontentloaded' });
  if (!localOrigin) {
  check('unauthenticated_login_screen', (await page.locator('body').innerText()).includes('private access link'));
  console.log('CHECK unauthenticated_login_screen PASS');
  await page.goto('about:blank');
  await page.goto(access.access_url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.scenePreview, { }, { timeout: 300000 });
  check('fragment_removed', !new URL(page.url()).hash);
  const cookie = (await context.cookies()).find(c => c.name === '__Host-mapmaker');
  check('secure_http_only_session', cookie?.secure && cookie?.httpOnly && cookie?.sameSite === 'Strict');
  console.log('CHECK authenticated_app PASS');
  } else {
    report.browser_path = 'loopback API; backend provenance must be verified separately';
    await page.waitForFunction(() => !!window.scenePreview);
  }
  if (process.env.RESUME_RUN) {
    report.run_id = process.env.RESUME_RUN;
    report.resumed = true;
    await page.goto(`${access.origin}/?run=${report.run_id}`, { waitUntil: 'domcontentloaded' });
  } else {
  const inputPath = path.resolve(root, process.env.TEST_INPUT || 'samples/living_room.jpg');
  const inputHash = createHash('sha256').update(await fs.readFile(inputPath)).digest('hex');
  if (process.env.EXPECT_INPUT_SHA256 && inputHash !== process.env.EXPECT_INPUT_SHA256) throw Error('Input hash differs from frozen evaluation input');
  report.input_sha256 = inputHash;
  await page.locator('#image').setInputFiles(inputPath);
  check('input_preview', await page.locator('#source-preview').isVisible());
  const submitted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/runs' && r.request().method() === 'POST');
  await page.locator('#generate').click();
  const response = await submitted;
  check('upload_accepted', response.status() === 202);
  await page.waitForFunction(() => /^[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get('run') || ''));
  report.run_id = new URL(page.url()).searchParams.get('run');
  }
  console.log('SUBMITTED', report.run_id);
  await save();
  const deadline = Date.now() + generationTimeoutSeconds * 1000;
  while (Date.now() < deadline) {
    const stage = await page.locator('body').getAttribute('data-stage');
    if (stage && report.stages.at(-1) !== stage) { report.stages.push(stage); console.log('STAGE', stage); await page.screenshot({ path: path.join(out, 'progress.png') }); await save(); }
    if (stage === 'failed') throw Error(await page.locator('#status').innerText());
    if (await page.evaluate(() => window.scenePreview?.ready)) break;
    await page.waitForTimeout(2000);
  }
  if (!(await page.evaluate(() => !!window.scenePreview?.ready))) {
    throw Error(`Browser verification timed out after ${generationTimeoutSeconds}s; run ${report.run_id} remains recorded. Check its state before resuming; do not resubmit automatically.`);
  }
  check('scene_ready', true);
  const state = await (await context.request.get(`${access.origin}/api/runs/${report.run_id}`)).json();
  await fs.writeFile(path.join(out, 'state.json'), JSON.stringify(state, null, 2));
  if (process.env.EXPECT_PLACEMENT) check('placement_version', state.metadata.placement.version === Number(process.env.EXPECT_PLACEMENT));
  if (process.env.EXPECT_RELEASE) check('release_hash', state.metadata.deployment.application_sha256 === process.env.EXPECT_RELEASE);
  const objects = state.metadata.objects.filter(o => o.status === 'generated');
  report.object_count = objects.length;
  check('object_list', objects.length > 0 && await page.locator('input[data-object-id]').count() === objects.length);
  check('webgl_render', await page.evaluate(() => window.scenePreview.renderer.info.render.triangles > 0));
  const surfaces = state.metadata.structure?.surfaces || [];
  report.surface_count = surfaces.length;
  if (surfaces.length) {
    const visibility = () => page.evaluate(ids => ids.map(id =>
      window.scenePreview.model.getObjectByName(id)?.visible), surfaces.map(s => s.node));
    check('room_nodes_present', (await visibility()).every(v => v === true));
    await page.locator('#show-room').uncheck();
    check('room_hidden', (await visibility()).every(v => v === false));
    await page.locator('#show-room').check();
    check('room_restored', (await visibility()).every(v => v === true));
    for (const kind of new Set(surfaces.map(s => s.kind))) {
      const target = await page.locator('input[data-surface-kind]').all();
      let selected;
      for (const item of target) {
        if (await item.getAttribute('data-surface-kind') === kind) selected = item;
      }
      check(`surface_control_${kind}`, !!selected);
      await selected.uncheck();
      check(`surface_hide_${kind}`, (await visibility()).every((v, i) => v === (surfaces[i].kind !== kind)));
      await selected.check();
      check(`surface_restore_${kind}`, (await visibility()).every(v => v === true));
    }
    await page.locator('#room-cutaway').click();
    check('room_cutaway', (await visibility()).every((v, i) => v === (surfaces[i].kind === 'floor')));
    await page.locator('#room-cutaway').click();
    check('room_cutaway_restored', (await visibility()).every(v => v === true));
  }
  await page.screenshot({ path: path.join(out, 'scene.png'), fullPage: true });
  for (const obj of objects) {
    const box = page.locator(`input[data-object-id="${obj.id}"]`);
    await box.uncheck();
    check(`hide_${obj.id}`, await page.evaluate(id => !window.scenePreview.model.getObjectByName(id).visible, obj.id));
    await box.check();
    check(`show_${obj.id}`, await page.evaluate(id => window.scenePreview.model.getObjectByName(id).visible, obj.id));
  }
  const cameraBefore = await page.evaluate(() => window.scenePreview.camera.position.toArray());
  await page.locator('#viewport').scrollIntoViewIfNeeded();
  const bounds = await page.locator('#viewport').boundingBox();
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2 + 110, bounds.y + bounds.height / 2 + 40, { steps: 12 }); await page.mouse.up();
  check('orbit', await page.evaluate(before => window.scenePreview.camera.position.toArray().some((v, i) => Math.abs(v - before[i]) > 0.001), cameraBefore));
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadEvent;
  await download.saveAs(path.join(out, 'scene.glb'));
  const bytes = await fs.readFile(path.join(out, 'scene.glb'));
  report.scene_bytes = bytes.length;
  report.scene_sha256 = createHash('sha256').update(bytes).digest('hex');
  check('download_full_sha256_match', report.scene_sha256 === state.metadata.placement.scene_sha256);
  check('download_glb', bytes.toString('ascii', 0, 4) === 'glTF' && bytes.readUInt32LE(8) === bytes.length);
  const remote = await context.request.get(`${access.origin}/runs/${report.run_id}/scene.glb`, { headers: { Range: 'bytes=0-15' } });
  check('download_matches_remote_header', remote.status() === 206 && bytes.subarray(0,16).equals(await remote.body()));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.scenePreview?.ready, {}, { timeout: 300000 });
  check('reload_saved_run', await page.evaluate(id => window.scenePreview.runId === id, report.run_id));
  check('no_page_errors', report.errors.length === 0);
  report.status = 'PASS';
} catch (e) {
  report.status = 'FAIL'; report.failure = String(e.message).replaceAll(access.access_token, '[REDACTED]').replaceAll(access.access_url, '[PRIVATE URL]');
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await Promise.allSettled(responseDetails);
  report.finished_at = new Date().toISOString(); await save(); console.log(JSON.stringify(report)); await browser.close();
}
