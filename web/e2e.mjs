import { chromium } from "@playwright/test";
import { writeFile, readFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = process.argv[2] || path.join(root, "samples/living_room.jpg");
const reportPath = path.join(root, ".runtime/web-e2e.json");
const report = { source, stages: [], pageErrors: [], checks: {} };
const save = () => writeFile(reportPath, JSON.stringify(report, null, 2));
await mkdir(path.dirname(reportPath), { recursive: true });
const browser = await chromium.launch({
  headless: true,
  args: [
    "--no-sandbox",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
page.setDefaultTimeout(120000);
page.setDefaultNavigationTimeout(180000);
page.on("pageerror", (e) => report.pageErrors.push(e.message));
try {
  const resume = process.env.RESUME_RUN;
  await page.goto(`http://127.0.0.1:8082/${resume ? `?run=${resume}` : ""}`);
  if (resume) {
    report.run_id = resume;
    report.resumed = true;
    report.checks.restore = (await page.locator("body").getAttribute("data-run-id")) === resume;
  } else {
    await page.locator("#image").setInputFiles(source);
    const responsePromise = page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    );
    await page.locator("#generate").click();
    const response = await responsePromise;
    if (response.status() !== 202)
      throw new Error(`Upload returned ${response.status()}`);
    await page.waitForFunction(() => document.body.dataset.runId);
    report.run_id = await page.locator("body").getAttribute("data-run-id");
    report.checks.upload = true;
    report.checks.generate = true;
  }
  await save();
  console.log("RUN", report.run_id);
  await page.screenshot({
    path: path.join(root, ".runtime/web-generating.png"),
    fullPage: true,
  });
  const deadline = Date.now() + 90 * 60 * 1000;
  while (Date.now() < deadline) {
    const stage = await page.locator("body").getAttribute("data-stage");
    if (stage && !report.stages.includes(stage)) {
      report.stages.push(stage);
      await save();
      console.log("STAGE", stage);
    }
    if (stage === "failed")
      throw new Error(await page.locator("#status").innerText());
    if (await page.evaluate(() => window.scenePreview?.ready)) break;
    await page.waitForTimeout(1500);
  }
  if (!(await page.evaluate(() => window.scenePreview?.ready)))
    throw new Error("Generation timeout");
  const run = path.join(root, "runs", report.run_id);
  const meta = JSON.parse(
    await readFile(path.join(run, "scene_metadata.json"), "utf8"),
  );
  const count = meta.objects.filter((o) => o.status === "generated").length;
  if ((await page.locator(".object-row").count()) !== count || count === 0)
    throw new Error("Object list mismatch");
  report.checks.status = report.resumed
    ? report.stages.length > 0
    : ["analyzing", "segmenting", "reconstructing", "done"].every((s) =>
        report.stages.includes(s),
      );
  report.checks.preview = true;
  report.checks.object_list = true;
  report.object_count = count;
  await page.screenshot({
    path: path.join(run, "previews/web_preview.png"),
    fullPage: true,
  });
  report.toggled_ids = [];
  for (let index = 0; index < count; index++) {
    const check = page.locator(".object-row input").nth(index),
      id = await check.getAttribute("data-object-id");
    await check.uncheck();
    if (
      await page.evaluate(
        (id) => window.scenePreview.model.getObjectByName(id).visible,
        id,
      )
    )
      throw new Error(`Toggle off failed: ${id}`);
    if (index === 0)
      await page.screenshot({
        path: path.join(run, "previews/web_hidden.png"),
        fullPage: true,
      });
    await check.check();
    if (
      !(await page.evaluate(
        (id) => window.scenePreview.model.getObjectByName(id).visible,
        id,
      ))
    )
      throw new Error(`Toggle on failed: ${id}`);
    report.toggled_ids.push(id);
  }
  report.checks.toggle = report.toggled_ids.length === count;
  const position = () =>
    page.evaluate(() => window.scenePreview.camera.position.toArray());
  const box = await page.locator("canvas").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const before = await position();
  await page.mouse.down();
  await page.mouse.move(
    box.x + box.width / 2 + 80,
    box.y + box.height / 2 + 30,
    { steps: 8 },
  );
  await page.mouse.up();
  report.checks.orbit =
    JSON.stringify(before) !== JSON.stringify(await position());
  const preZoom = await position();
  await page.mouse.wheel(0, -250);
  await page.waitForTimeout(500);
  report.checks.zoom =
    JSON.stringify(preZoom) !== JSON.stringify(await position());
  const prePan = await page.evaluate(() =>
    window.scenePreview.controls.target.toArray(),
  );
  await page.mouse.down({ button: "right" });
  await page.mouse.move(
    box.x + box.width / 2 - 50,
    box.y + box.height / 2 + 20,
    { steps: 8 },
  );
  await page.mouse.up({ button: "right" });
  report.checks.pan =
    JSON.stringify(prePan) !==
    JSON.stringify(
      await page.evaluate(() => window.scenePreview.controls.target.toArray()),
    );
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export").click();
  const download = await downloadPromise;
  const downloadDir = path.join(root, ".runtime/web-downloads");
  await mkdir(downloadDir, { recursive: true });
  const exported = path.join(downloadDir, report.run_id + ".glb");
  await download.saveAs(exported);
  const hash = (b) => createHash("sha256").update(b).digest("hex");
  report.checks.export =
    hash(await readFile(exported)) ===
    hash(await readFile(path.join(run, "scene.glb")));
  report.node_names = await page.evaluate(() =>
    window.scenePreview.model.children.map((o) => o.name),
  );
  if (report.pageErrors.length || Object.values(report.checks).some((v) => !v))
    throw new Error("One or more browser checks failed");
  report.passed = true;
  await save();
  await writeFile(
    path.join(run, "logs/web_validation.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  report.passed = false;
  report.error = error.stack;
  await save();
  throw error;
} finally {
  await browser.close();
}
