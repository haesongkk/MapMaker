import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(path.join(root,'web/package.json'));
const {chromium}=require('@playwright/test');
const dir=path.resolve(process.argv[2]);
const meta=JSON.parse(await fs.readFile(path.join(dir,'scene_metadata.json'),'utf8'));
const bytes=await fs.readFile(path.join(dir,'scene.glb'));meta.scene_bytes=bytes.length;
const rid='00000000000000000000000000000006';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1440,height:960},acceptDownloads:true});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try {
 await page.route('http://fixture.test/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname.startsWith('/api/runs/'))return route.fulfill({json:{stage:'done',message:'Saved artifact validation',metadata:meta}});
  if(url.pathname.endsWith('/scene.glb')){
   const range=route.request().headers().range;
   const [,a,b]=range.match(/bytes=(\d+)-(\d+)/);
   return route.fulfill({status:206,contentType:'model/gltf-binary',body:bytes.subarray(+a,+b+1)});
  }
  if(url.pathname.includes('/input/')) {
   try { return route.fulfill({contentType:'image/png',body:await fs.readFile(path.join(dir,'input/source_image.png'))}); }
   catch { return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#142538"/><text x="160" y="100" text-anchor="middle" fill="white" font-size="18">Synthetic room fixture</text></svg>'}); }
  }
  let file=url.pathname==='/'?'index.html':url.pathname.slice(1);
  if(file.startsWith('vendor/three/'))file='node_modules/three/'+file.slice('vendor/three/'.length);
  const target=path.resolve(root,'web',file);
  if(!target.startsWith(path.join(root,'web')+path.sep))return route.abort();
  const type=file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html';
  return route.fulfill({contentType:type,body:await fs.readFile(target)});
 });
 await page.goto(`http://fixture.test/?run=${rid}`);
 await page.waitForFunction(()=>window.scenePreview?.ready,null,{timeout:120000});
 const framing=[];
 for(const viewport of [{width:1440,height:960},{width:700,height:1100}]){
  await page.setViewportSize(viewport);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const bounds=await page.evaluate(async()=>{
   const THREE=await import('three');
   const {model,camera}=window.scenePreview;
   camera.updateMatrixWorld();
   const box=new THREE.Box3().setFromObject(model),projected=[];
   for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])
    projected.push(new THREE.Vector3(x,y,z).project(camera));
   return {maximum:Math.max(...projected.flatMap(p=>[Math.abs(p.x),Math.abs(p.y)])),
    depthValid:projected.every(p=>p.z>-1&&p.z<1),aspect:camera.aspect};
  });
  if(bounds.maximum>1||!bounds.depthValid)throw Error(`Scene framing clips bounds: ${JSON.stringify(bounds)}`);
  framing.push({viewport,...bounds});
 }
 await page.setViewportSize({width:1440,height:960});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const layout=await page.evaluate(()=>{
  const viewport=document.querySelector('#viewport').getBoundingClientRect();
  const objects=document.querySelector('#objects');
  const download=document.querySelector('#export').getBoundingClientRect();
  return {viewportBottom:viewport.bottom,downloadBottom:download.bottom,height:innerHeight,
   listHeight:objects.clientHeight,listScrollHeight:objects.scrollHeight};
 });
 if(layout.viewportBottom>layout.height+1||layout.downloadBottom>layout.height+1)
  throw Error(`Desktop controls extend beyond screen: ${JSON.stringify(layout)}`);
 const surfaces=meta.structure?.surfaces||[];
 const visible=()=>page.evaluate(ids=>ids.map(id=>window.scenePreview.model.getObjectByName(id).visible),surfaces.map(s=>s.node));
 if(surfaces.length){
  await page.locator('#show-room').uncheck();if((await visible()).some(Boolean))throw Error('Room hide failed');
  await page.locator('#show-room').check();if(!(await visible()).every(Boolean))throw Error('Room show failed');
  await page.locator('#room-cutaway').click();
  if((await visible()).some((v,i)=>v!==(surfaces[i].kind==='floor')))throw Error('Cutaway failed');
  await page.locator('#room-cutaway').click();
  for(const toggle of await page.locator('input[data-surface-kind]').all()){await toggle.uncheck();await toggle.check();}
 }
 for(const toggle of await page.locator('input[data-object-id]').all()){await toggle.uncheck();await toggle.check();}
 const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();
 const download=await downloadPromise;await download.saveAs(path.join(dir,'browser-download.glb'));
 if(!(await fs.readFile(path.join(dir,'browser-download.glb'))).equals(bytes))throw Error('Download differs');
 if(surfaces.length){
  for(const toggle of await page.locator('input[data-object-id]').all())await toggle.uncheck();
  await page.screenshot({path:path.join(dir,'room-surfaces.png'),fullPage:true});
  for(const toggle of await page.locator('input[data-object-id]').all())await toggle.check();
  await page.locator('#show-room').uncheck();
  await page.screenshot({path:path.join(dir,'objects-only.png'),fullPage:true});
  await page.locator('#show-room').check();
 }
 await page.screenshot({path:path.join(dir,'full-scene.png'),fullPage:true});
 if(surfaces.length)await page.locator('#room-cutaway').click();
 await page.screenshot({path:path.join(dir,'browser.png'),fullPage:true});
 if(errors.length)throw Error(errors.join('\n'));
 const triangles=await page.evaluate(()=>window.scenePreview.renderer.info.render.triangles);
 if(!triangles)throw Error('No WebGL triangles');
 const report={passed:true,fixture:'saved local artifact; no GPU inference',surfaces:surfaces.length,objects:meta.objects.filter(o=>o.status==='generated').length,triangles,errors,download_match:true,framing,layout};
 await fs.writeFile(path.join(dir,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}
