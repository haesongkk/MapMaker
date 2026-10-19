// Capture the actual saved GLB in the report's viewer; no inference is run.
import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
const mapping=JSON.parse(await fs.readFile('.runtime/four-way-comparison/viewers.json','utf8'));
const out='docs/assets/four-way-comparison';
const ledger=[];
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 for(const [alias,folder] of Object.entries(mapping)){
  const run=crypto.createHash('sha256').update(alias).digest('hex').slice(0,32);
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:8118/viewer?run=${alias}`);
  await page.waitForFunction(()=>window.scenePreview?.ready && window.scenePreview.renderer.info.render.triangles>0,null,{timeout:180000});
  const state=await page.evaluate(()=>{const v=window.scenePreview;return {run:v.runId,camera:v.camera.position.toArray(),target:v.controls.target.toArray(),triangles:v.renderer.info.render.triangles}});
  if(state.run!==run || errors.length)throw Error(JSON.stringify({alias,state,errors}));
  const asset=`${out}/${alias}.png`;
  await page.locator('#viewport').screenshot({path:asset});
  ledger.push({alias,folder,asset,...state,errors,scene_sha256:crypto.createHash('sha256').update(await fs.readFile(`${folder}/scene.glb`)).digest('hex')});
  await fs.writeFile('.runtime/four-way-comparison/viewer-captures.json',JSON.stringify(ledger,null,2));
  console.log(`Captured ${ledger.length}/40 ${alias}`);await page.close();
 }
}finally{await browser.close();}
