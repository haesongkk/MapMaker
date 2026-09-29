// Read-only v3/v4 comparison with identical cameras. Never submits inference.
import { chromium } from '@playwright/test';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
const [before, after, output] = process.argv.slice(2);
if (![before, after].every(id => /^[a-f0-9]{32}$/.test(id)) || !output) throw Error('Usage: beforeRun afterRun output');
const load = async id => JSON.parse(await readFile(path.join('runs', id, 'scene_metadata.json'), 'utf8'));
const metas = await Promise.all([load(before), load(after)]);
if (metas[0].placement.version !== 3 || metas[1].placement.version !== 4) throw Error('Expected v3 -> v4');
const ids = m => m.objects.filter(o => o.status === 'generated').map(o => o.id).sort();
if (JSON.stringify(ids(metas[0])) !== JSON.stringify(ids(metas[1]))) throw Error('Different objects');
for (const obj of metas[0].objects.filter(o => o.status === 'generated')) {
 const next = metas[1].objects.find(o => o.id === obj.id);
 if (next.asset_sha256 !== obj.asset_sha256 || JSON.stringify(next.pose) !== JSON.stringify(obj.pose)) throw Error('Input geometry/pose mismatch');
}
const low = [0,1,2].map(i => Math.min(...metas.map(m => m.assembly.bounds[0][i])));
const high = [0,1,2].map(i => Math.max(...metas.map(m => m.assembly.bounds[1][i])));
const center = low.map((v,i) => (v+high[i])/2);
const distance = Math.max(Math.hypot(...low.map((v,i) => high[i]-v))*1.35, .5);
const views = {front:[-.25,.22,-1], reverse:[.8,.35,1]};
const report = {before,after,sharedCamera:{center,distance,views},runs:[],passed:false};
const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 for(const [index,run] of [before,after].entries()) {
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const result={run,stage:index?'after':'before',checks:{},errors:[],cameras:{}};report.runs.push(result);
  await page.route('**/*',r=>new URL(r.request().url()).origin==='http://127.0.0.1:8082'?r.continue():r.abort());
  page.on('pageerror',e=>result.errors.push(e.message));
  page.on('response',r=>{if(r.status()>=400&&!r.url().endsWith('/favicon.ico'))result.errors.push(`${r.status()} ${r.url()}`)});
  await page.goto(`http://127.0.0.1:8082/?run=${run}`);
  await page.waitForFunction(()=>window.scenePreview?.ready,{},{timeout:180000});
  assert(await page.locator('.object-row').count()===ids(metas[index]).length,'Object count mismatch');
  result.checks.floor=await page.evaluate(()=>!!window.scenePreview.model.getObjectByName('background_floor'));
  for(const [name,direction] of Object.entries(views)) {
   result.cameras[name]=await page.evaluate(({center,distance,direction})=>{
    const p=window.scenePreview;
    p.camera.up.set(0,1,0);p.camera.position.set(...center.map((v,i)=>v+distance*direction[i]));
    p.camera.near=distance/1000;p.camera.far=distance*100;p.camera.updateProjectionMatrix();
    p.controls.target.set(...center);p.controls.update();p.renderer.render(p.scene,p.camera);
    return {position:p.camera.position.toArray(),target:p.controls.target.toArray(),projection:p.camera.projectionMatrix.toArray()};
   },{center,distance,direction});
   await page.locator('#viewport').screenshot({path:path.join(output,`${result.stage}_${name}.png`)});
  }
  result.checks.webgl=await page.evaluate(()=>window.scenePreview.renderer.info.render.triangles>0);
  for(const control of await page.locator('.object-row input').all()) {
   const id=await control.getAttribute('data-object-id');await control.uncheck();
   assert(await page.evaluate(id=>!window.scenePreview.model.getObjectByName(id).visible,id),'Hide failed');await control.check();
   assert(await page.evaluate(id=>window.scenePreview.model.getObjectByName(id).visible,id),'Show failed');
  }
  result.checks.toggle=true;
  const box=await page.locator('canvas').boundingBox();
  const initial=await page.evaluate(()=>window.scenePreview.camera.position.toArray());
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+70,box.y+box.height/2+20,{steps:8});await page.mouse.up();
  result.checks.orbit=JSON.stringify(initial)!==JSON.stringify(await page.evaluate(()=>window.scenePreview.camera.position.toArray()));
  const promise=page.waitForEvent('download');await page.locator('#export').click();const download=await promise;
  const file=path.join(output,`${result.stage}.glb`);await download.saveAs(file);
  const hash=b=>createHash('sha256').update(b).digest('hex');
  result.checks.download=hash(await readFile(file))===hash(await readFile(path.join('runs',run,'scene.glb')));
  assert(Object.values(result.checks).every(Boolean)&&!result.errors.length,'Viewer validation failed');
  await page.close();
 }
 assert(JSON.stringify(report.runs[0].cameras)===JSON.stringify(report.runs[1].cameras),'Cameras differ');
 report.passed=true;
} catch(e) {report.error=e.message;process.exitCode=1;}
finally {await writeFile(path.join(output,'comparison.json'),JSON.stringify(report,null,2));await browser.close();}
