import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const root='docs/assets/ram-qwen-filter-new-scenes';
const selection=JSON.parse(await fs.readFile(`${root}/selection.json`,'utf8'));
const complete=process.argv.includes('--complete');
if(complete){
 const records=JSON.parse(await fs.readFile(`${root}/scene-manifest.json`,'utf8'));
 const captures=JSON.parse(await fs.readFile(`${root}/captures.json`,'utf8'));
 if(captures.length!==42)throw Error('Expected 42 verified captures');
 for(const item of selection.samples){
  const reference=captures.find(c=>c.sample===item.sample&&c.version==='baseline');
  if(Object.keys(records[item.sample]).length!==7)throw Error('Expected all seven scenes');
  for(const [version,r] of Object.entries(records[item.sample])){
   const c=captures.find(c=>c.sample===item.sample&&c.version===version);
   if(!c||c.errors.length||c.scene_sha256!==r.scene_sha256||c.input_sha256!==item.input_sha256)throw Error('Capture provenance mismatch');
   // OrbitControls recomputes spherical coordinates; allow floating-point roundoff.
   const sameVector=(a,b)=>a.length===b.length&&a.every((x,i)=>Math.abs(x-b[i])<=1e-10);
   if(!sameVector(c.camera,reference.camera)||!sameVector(c.target,reference.target))throw Error('Camera mismatch');
   if(c.render_policy!=='locked_camera_v2')throw Error('Capture camera was not locked');
  }
 }
}
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:2400,height:1200},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html');
 if(await page.locator('section').count()!==11||await page.locator('figure').count()!==77)throw Error('Expected 11 rows and 77 comparison figures');
 for(const item of selection.samples){
  const row=page.locator(`#${item.sample}`);
  await row.scrollIntoViewIfNeeded();
  if(await row.locator('figure').count()!==7)throw Error('Missing version column');
  await row.locator('img').evaluateAll(async ims=>{for(const im of ims)im.loading='eager';await Promise.all(ims.map(im=>im.decode()));});
  const urls=await row.locator('figcaption a').evaluateAll(as=>as.map(a=>a.href));
  if(complete&&urls.length!==7)throw Error('Missing ready viewer');
  for(const url of urls){const response=await page.request.get(url);if(!response.ok())throw Error('Bad viewer URL');}
  await row.screenshot({path:`${root}/comparison-${item.sample}.png`});
 }
 if(errors.length)throw Error(JSON.stringify(errors));
 console.log('11 rows, 77 version slots; original images decoded; all available viewer links verified. Complete:',complete);
}finally{await browser.close();}
