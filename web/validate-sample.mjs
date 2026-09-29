// Real UI submission and verification. No mocked requests or generated artifacts.
import { chromium } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';

const [source, output, resume = ''] = process.argv.slice(2);
const base = 'http://127.0.0.1:8082';
const report = { source, checks: {}, stages: [], page_errors: [], console_errors: [], network_errors: [] };
await mkdir(output, { recursive: true });
const save = () => writeFile(path.join(output, 'browser.json'), JSON.stringify(report, null, 2));
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
let page;
async function newPage() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await context.newPage();
  p.setDefaultTimeout(120000);
  p.on('pageerror', e => report.page_errors.push(e.message));
  p.on('console', e => { if (e.type() === 'error') report.console_errors.push(e.text()); });
  p.on('requestfailed', r => report.network_errors.push({ url: r.url(), error: r.failure()?.errorText }));
  p.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) report.network_errors.push({ url: r.url(), status: r.status() }); });
  return p;
}
async function ready(p) {
  await p.waitForFunction(() => window.scenePreview?.ready || document.body.dataset.stage === 'failed', { }, { timeout: 180000 });
  assert(await p.evaluate(() => window.scenePreview?.ready), await p.locator('#status').innerText());
  assert(await p.locator('body').getAttribute('data-stage') === 'done', 'Status is not done');
}
try {
  page = await newPage();
  await page.goto(base + (resume ? `/?run=${resume}` : '/'));
  if (resume) {
    assert(/^[a-f0-9]{32}$/.test(resume), 'Invalid resume ID');
    report.run_id = resume;
  } else {
    await page.locator('#image').setInputFiles(source);
    report.submission_uncertain = true;
    await save();
    const responsePromise = page.waitForResponse(r => r.url() === `${base}/api/runs` && r.request().method() === 'POST');
    await page.locator('#generate').click();
    const response = await responsePromise;
    if (response.status() !== 202) {
      report.submission_uncertain = false;
      await page.waitForFunction(() => document.body.dataset.stage === 'failed');
      throw new Error(`Upload HTTP ${response.status()}: ${await page.locator('#status').innerText()}`);
    }
    // Read the application-owned URL, not the inspector's evictable response cache.
    await page.waitForFunction(() => /^[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get('run') || ''));
    report.run_id = new URL(page.url()).searchParams.get('run');
    report.submission_uncertain = false;
    report.checks.browser_upload = true;
  }
  report.url = `${base}/?run=${report.run_id}`;
  await save();
  console.log(`RUN ${report.run_id}`);
  // Backend owns the 60..21600s remote timeout and cancellation. The extra
  // margin allows artifact download; never start another job on uncertain timeout.
  const deadline = Date.now() + 22200 * 1000;
  let last = '';
  while (true) {
    const response = await page.request.get(`${base}/api/runs/${report.run_id}`);
    assert(response.ok(), `Status HTTP ${response.status()}`);
    const state = await response.json();
    if (state.stage !== last) {
      last = state.stage;
      report.stages.push({ stage: last, at: new Date().toISOString(), message: state.message });
      console.log(`STAGE ${last}: ${state.message}`);
      await save();
    }
    assert(state.stage !== 'failed', state.message);
    if (state.stage === 'done') break;
    assert(Date.now() < deadline, 'Infrastructure: backend did not terminate within maximum job timeout; stop batch');
    await page.waitForTimeout(3000);
  }
  await ready(page);
  report.checks.generation_page = true;
  // Restore with no cookies/localStorage from the generation context.
  await page.context().close();
  page = await newPage();
  await page.goto(report.url);
  await ready(page);
  assert(await page.locator('body').getAttribute('data-run-id') === report.run_id, 'Wrong restored run');
  report.checks.fresh_context_restore = true;
  const input = page.locator('#source-preview');
  assert(await input.evaluate(img => img.complete && img.naturalWidth > 0), 'Input preview missing');
  assert((await input.getAttribute('src')) === `/runs/${report.run_id}/input/source_image.png`, 'Wrong input preview URL');
  const count = await page.locator('.object-row').count();
  assert(count > 0, 'No object controls');
  report.object_count = count;
  report.render = await page.evaluate(() => {
    const { renderer, scene, camera, model } = window.scenePreview;
    renderer.render(scene, camera);
    const gl = renderer.getContext();
    const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
    gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let opaque = 0, min = 255, max = 0, meshes = 0;
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i + 3]) {
      opaque++; min = Math.min(min, pixels[i], pixels[i + 1], pixels[i + 2]); max = Math.max(max, pixels[i], pixels[i + 1], pixels[i + 2]);
    }
    model.traverse(o => { if (o.isMesh) meshes++; });
    return { frame: renderer.info.render.frame, triangles: renderer.info.render.triangles, meshes, opaque_pixels: opaque, color_range: max - min, nodes: model.children.map(o => o.name) };
  });
  assert(report.render.frame > 0 && report.render.triangles > 0 && report.render.meshes > 0 && report.render.opaque_pixels > 100 && report.render.color_range > 5, 'Blank/invalid WebGL render');
  report.checks.actual_render = true;
  for (let i = 0; i < count; i++) {
    const control = page.locator('.object-row input').nth(i);
    const id = await control.getAttribute('data-object-id');
    await control.uncheck();
    assert(await page.evaluate(id => window.scenePreview.model.getObjectByName(id).visible === false, id), `Hide failed: ${id}`);
    await control.check();
    assert(await page.evaluate(id => window.scenePreview.model.getObjectByName(id).visible, id), `Show failed: ${id}`);
  }
  report.checks.visibility = true;
  const camera = () => page.evaluate(() => window.scenePreview.camera.position.toArray());
  const initial = await camera();
  const box = await page.locator('canvas').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 65, box.y + box.height / 2 + 20, { steps: 8 });
  await page.mouse.up();
  assert(JSON.stringify(initial) !== JSON.stringify(await camera()), 'Orbit did not move camera');
  report.checks.orbit = true;
  // Restore the existing automatic fit camera for reproducible screenshots.
  await page.evaluate(position => {
    const p = window.scenePreview;
    p.camera.position.fromArray(position); p.controls.update(); p.renderer.render(p.scene, p.camera);
  }, initial);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadPromise;
  const exportPath = path.join(output, 'export.glb');
  await download.saveAs(exportPath);
  const hash = b => createHash('sha256').update(b).digest('hex');
  const run = path.resolve('runs', report.run_id);
  assert(hash(await readFile(exportPath)) === hash(await readFile(path.join(run, 'scene.glb'))), 'Export hash mismatch');
  report.checks.export = true;
  report.viewer_screenshot = path.join(output, 'viewer.png');
  report.full_page_screenshot = path.join(output, 'full_page.png');
  await page.locator('#viewport').screenshot({ path: report.viewer_screenshot });
  await page.screenshot({ path: report.full_page_screenshot, fullPage: true });
  assert(!report.page_errors.length && !report.console_errors.length && !report.network_errors.length, 'Browser console/runtime/network errors; inspect browser.json');
  report.passed = true;
} catch (e) {
  report.passed = false;
  report.error = e.message;
  if (page && !page.isClosed()) {
    const failurePath = path.join(output, 'failure.png');
    await page.screenshot({ path: failurePath, fullPage: true })
      .then(() => { report.failure_screenshot = failurePath; }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  await save();
  await browser.close();
}
