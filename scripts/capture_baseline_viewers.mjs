// Capture new baseline using each historical capture's camera and target.
import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
const v2=process.argv.includes('--qwen-v2');
const qwen=process.argv.includes('--qwen')||v2;
const prefix=v2?'qwen-v2-':qwen?'qwen-':'baseline-';
const root=`docs/assets/${v2?'qwen-baseline-v2-comparison':qwen?'qwen-baseline-comparison':'baseline-comparison'}`;
const mapping=JSON.parse(await fs.readFile(`${root}/viewers.json`,'utf8'));
const previous=JSON.parse(await fs.readFile('docs/assets/four-way-comparison/captures.json','utf8'));
let ledger=[];
try {ledger=JSON.parse(await fs.readFile(`${root}/captures.json`,'utf8'));} catch (error) {if(error.code!=='ENOENT')throw error;}
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 for(const [alias,folder] of Object.entries(mapping)) {
  const sceneHash=crypto.createHash('sha256').update(await fs.readFile(`${folder}/scene.glb`)).digest('hex');
  if(ledger.some(c=>c.alias===alias&&c.scene_sha256===sceneHash))continue;
  ledger=ledger.filter(c=>c.alias!==alias);
  const name=alias.slice(prefix.length,-'-new'.length);
  const reference=previous.find(x=>x.alias===`four-way-${name}-1`);
  if(!reference)throw Error(`Missing historical camera: ${name}`);
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:8118/viewer?run=${alias}`);
  await page.waitForFunction(()=>window.scenePreview?.ready && window.scenePreview.renderer.info.render.triangles>0,null,{timeout:300000});
  await page.evaluate(reference=>{
   const v=window.scenePreview;v.camera.position.fromArray(reference.camera);
   v.controls.target.fromArray(reference.target);v.controls.update();
   v.renderer.render(v.scene,v.camera);
  },reference);
  const state=await page.evaluate(()=>{const v=window.scenePreview;return {run:v.runId,camera:v.camera.position.toArray(),target:v.controls.target.toArray(),triangles:v.renderer.info.render.triangles}});
  const expected=crypto.createHash('sha256').update(alias).digest('hex').slice(0,32);
  if(state.run!==expected||errors.length)throw Error(JSON.stringify({alias,state,errors}));
  const asset=`${root}/${alias}.png`;
  await page.locator('#viewport').screenshot({path:asset,timeout:180000});
  ledger.push({alias,folder,asset,...state,errors,camera_policy:'historical_camera_and_target',reference:reference.alias,scene_sha256:crypto.createHash('sha256').update(await fs.readFile(`${folder}/scene.glb`)).digest('hex')});
  await fs.writeFile(`${root}/captures.json`,JSON.stringify(ledger,null,2));
  console.log(`Captured ${alias}`);await page.close();
 }
} finally {await browser.close();}
