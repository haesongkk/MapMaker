import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const root=process.argv[2]||'docs/assets/ram-qwen-filter-new-scenes';
const clean=process.argv.includes('--clean');
const only=process.argv.find(a=>a.startsWith('--sample='))?.slice(9);
const suffix=clean?'-clean':'';
const records=JSON.parse(await fs.readFile(`${root}/scene-manifest.json`,'utf8'));
const ledger=JSON.parse(await fs.readFile(`${root}/captures${suffix}.json`,'utf8').catch(()=>'[]'));
const original=clean?JSON.parse(await fs.readFile(`${root}/captures.json`,'utf8').catch(()=>'[]')):[];
const order=['baseline','v1','v2','movable','vision-movable','furniture','vision-furniture'];
for(const [name,versions] of Object.entries(records))for(const version of order){
 if(only&&name!==only)continue;
 if(clean&&!['baseline','vision-furniture'].includes(version))continue;
 const r=versions[version];if(!r)continue;
 const old=ledger.find(c=>c.sample===name&&c.version===version);
 if(old?.render_policy==='locked_camera_v2'&&old.scene_sha256===r.scene_sha256&&!old.errors.length&&(await fs.stat(`${root}/${name}-${version}${suffix}.png`).catch(()=>null)))continue;
 const reference=ledger.find(c=>c.sample===name&&c.version==='baseline')||original.find(c=>c.sample===name&&c.version==='baseline');
 if(version!=='baseline'&&!reference)throw Error('Missing baseline camera');
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:8136/viewer?run=${r.alias}`);
  await page.waitForFunction(empty=>window.scenePreview?.ready&&(empty||window.scenePreview.renderer.info.render.triangles>0),r.objects===0,{timeout:300000});
  await page.evaluate(()=>document.fonts.ready);
  if(clean)await page.evaluate(()=>{if(window.scenePreview.grid)window.scenePreview.grid.visible=false;});
  const state=await page.evaluate(reference=>{
   const v=window.scenePreview;
   v.controls.dispatchEvent({type:'start'});
   if(reference){v.camera.position.fromArray(reference.camera);v.controls.target.fromArray(reference.target);}
   const distance=v.camera.position.distanceTo(v.controls.target);
   v.camera.near=distance/1000;v.camera.far=distance*100;
   const rect=document.querySelector('#viewport').getBoundingClientRect();v.camera.aspect=rect.width/rect.height;
   v.camera.updateProjectionMatrix();v.controls.update();v.renderer.render(v.scene,v.camera);
   return {camera:v.camera.position.toArray(),target:v.controls.target.toArray(),triangles:v.renderer.info.render.triangles};
  },reference??null);
  if(errors.length)throw Error(JSON.stringify(errors));
  if(r.objects===0)await page.locator('#viewport').evaluate(el=>{
   const label=document.createElement('div');label.textContent='유지된 객체 0개';
   label.style.cssText='position:absolute;top:45%;left:35%;color:white;font:24px system-ui';el.appendChild(label);
  });
  await page.locator('#viewport').screenshot({path:`${root}/${name}-${version}${suffix}.png`,timeout:180000});
  const actual=await page.evaluate(()=>({camera:window.scenePreview.camera.position.toArray(),target:window.scenePreview.controls.target.toArray()}));
  if(JSON.stringify(actual.camera)!==JSON.stringify(state.camera)||JSON.stringify(actual.target)!==JSON.stringify(state.target))throw Error('Camera changed during capture');
  if(old)ledger.splice(ledger.indexOf(old),1);
  ledger.push({sample:name,version,scene_sha256:r.scene_sha256,input_sha256:r.input_sha256,...state,errors,render_policy:'locked_camera_v2',grid_hidden:clean,camera_policy:'same camera and target as this image baseline; verified after screenshot'});
  await fs.writeFile(`${root}/captures${suffix}.json`,JSON.stringify(ledger,null,2));console.log('Captured',name,version,state.triangles);
 }finally{await browser.close();}
}
