// Read-only validation of a completed fresh inference run. Never submits a GPU job.
import { chromium } from '@playwright/test';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
const [run, output, mode = 'after'] = process.argv.slice(2);
if (!['before','after'].includes(mode)) throw new Error('Invalid validation mode');
if (!/^[a-f0-9]{32}$/.test(run)) throw new Error('Invalid run ID');
await mkdir(output,{recursive:true});
const report={run,mode,checks:{},errors:[]};
const assert=(ok,message)=>{if(!ok)throw new Error(message);};
const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.route('**/*',route=>new URL(route.request().url()).origin==='http://127.0.0.1:8082' ? route.continue() : route.abort());
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(`http://127.0.0.1:8082/?run=${run}`);
  await page.waitForFunction(()=>window.scenePreview?.ready,{},{timeout:180000});
  const meta=JSON.parse(await readFile(path.join('runs',run,'scene_metadata.json'),'utf8'));
  const count=meta.objects.filter(o=>o.status==='generated').length;
  assert(await page.locator('.object-row').count()===count,'Object count mismatch');
  report.floor_present=await page.evaluate(()=>!!window.scenePreview.model.getObjectByName('background_floor'));
  report.checks.floor=mode==='before' || report.floor_present;
  assert(report.checks.floor,'Missing floor');
  report.checks.webgl=await page.evaluate(()=>window.scenePreview.renderer.info.render.triangles>0);
  assert(report.checks.webgl,'No rendered triangles');
  await page.locator('#viewport').screenshot({path:path.join(output,'viewer.png')});
  for (const control of await page.locator('.object-row input').all()) {
    const id=await control.getAttribute('data-object-id');
    await control.uncheck();
    assert(await page.evaluate(id=>!window.scenePreview.model.getObjectByName(id).visible,id),'Hide failed');
    await control.check();
    assert(await page.evaluate(id=>window.scenePreview.model.getObjectByName(id).visible,id),'Show failed');
  }
  report.checks.toggle=true;
  const box=await page.locator('canvas').boundingBox();
  const camera=()=>page.evaluate(()=>window.scenePreview.camera.position.toArray());
  const target=()=>page.evaluate(()=>window.scenePreview.controls.target.toArray());
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  let before=await camera();
  await page.mouse.down();await page.mouse.move(box.x+box.width/2+65,box.y+box.height/2+25,{steps:8});await page.mouse.up();
  report.checks.orbit=JSON.stringify(before)!==JSON.stringify(await camera());
  before=await camera();await page.mouse.wheel(0,-200);await page.waitForTimeout(500);
  report.checks.zoom=JSON.stringify(before)!==JSON.stringify(await camera());
  before=await target();await page.mouse.down({button:'right'});await page.mouse.move(box.x+box.width/2-30,box.y+box.height/2+45,{steps:8});await page.mouse.up({button:'right'});
  report.checks.pan=JSON.stringify(before)!==JSON.stringify(await target());
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;
  const file=path.join(output,'download.glb');await download.saveAs(file);
  const hash=b=>createHash('sha256').update(b).digest('hex');
  report.checks.download=hash(await readFile(file))===hash(await readFile(path.join('runs',run,'scene.glb')));
  assert(Object.values(report.checks).every(Boolean)&&!report.errors.length,'Viewer checks failed');
  report.passed=true;
} catch(e){report.passed=false;report.error=e.message;process.exitCode=1;}
finally{await writeFile(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
