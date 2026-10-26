import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const version=process.argv.includes('--version')?process.argv[process.argv.indexOf('--version')+1]:process.argv.includes('--vision')?'vision-movable':process.argv.includes('--movable')?'movable':process.argv.includes('--v3')?'v3':process.argv.includes('--v2')?'v2':'v1';
if(!['v1','v2','v3','movable','vision-movable','furniture','vision-furniture'].includes(version))throw Error('Unknown capture version');
const prefix=version==='v1'?'ram-filter':`ram-filter-${version}`;
const port=process.env.REVIEW_PORT||'8134';
const root=`docs/assets/ram-qwen-filter-${version}`;
const records=JSON.parse(await fs.readFile(`${root}/scene-manifest.json`,'utf8'));
const previous=JSON.parse(await fs.readFile('docs/assets/baseline-comparison/captures.json','utf8'));
const prior=[];
for(const earlier of ['v1','v2'].filter(v=>version==='movable'||v<version)){
 const captures=JSON.parse(await fs.readFile(`docs/assets/ram-qwen-filter-${earlier}/captures.json`,'utf8'));
 prior.push(...captures.map(c=>({...c,source_version:earlier})));
}
const ledger=[];
const saved=process.argv.includes('--resume')?JSON.parse(await fs.readFile(`${root}/captures.json`,'utf8').catch(()=> '[]')):[];
for(const [name,record] of Object.entries(records)) {
 const reference=previous.find(x=>x.alias===`baseline-${name}-new`);
 if(!reference||reference.scene_sha256!==record.source_scene_sha256)throw Error(`Unverified baseline: ${name}`);
 const reusable=saved.find(c=>c.sample===name&&c.scene_sha256===record.scene_sha256&&c.source_scene_sha256===record.source_scene_sha256&&!c.errors.length&&JSON.stringify(c.camera)===JSON.stringify(reference.camera)&&JSON.stringify(c.target)===JSON.stringify(reference.target));
 if(reusable&&(await fs.stat(`${root}/${name}-after.png`).catch(()=>null))){
  ledger.push(reusable);await fs.writeFile(`${root}/captures.json`,JSON.stringify(ledger,null,2));console.log(`Verified saved capture ${name}`);continue;
 }
 await fs.copyFile(reference.asset,`${root}/${name}-before.png`);
 const identical=prior.find(c=>c.sample===name&&c.scene_sha256===record.scene_sha256&&c.source_scene_sha256===record.source_scene_sha256);
 if(identical){
  await fs.copyFile(`docs/assets/ram-qwen-filter-${identical.source_version}/${name}-after.png`,`${root}/${name}-after.png`);
  ledger.push({...identical,reused_from:`${identical.source_version}_identical_scene_sha256`});
  await fs.writeFile(`${root}/captures.json`,JSON.stringify(ledger,null,2));
  console.log(`Reused identical scene ${name}`);continue;
 }
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/viewer?run=${prefix}-${name}-after`);
  await page.waitForFunction(empty=>window.scenePreview?.ready&&(empty||window.scenePreview.renderer.info.render.triangles>0),record.objects_after===0,{timeout:300000});
  const state=await page.evaluate(reference=>{
   const v=window.scenePreview;
   v.camera.position.fromArray(reference.camera);v.controls.target.fromArray(reference.target);
   v.camera.near=.0001;v.camera.far=10000;v.camera.updateProjectionMatrix();v.controls.update();
   v.renderer.render(v.scene,v.camera);
   return {camera:v.camera.position.toArray(),target:v.controls.target.toArray(),triangles:v.renderer.info.render.triangles};
  },reference);
  if(errors.length)throw Error(JSON.stringify(errors));
  if(record.objects_after===0){
   if(state.triangles!==0)throw Error('Empty result still contains triangles');
   await page.locator('#viewport').evaluate(view=>{
    const label=document.createElement('div');label.textContent='유지된 객체 0개';
    label.style.cssText='position:absolute;left:50%;top:45%;transform:translate(-50%,-50%);color:#e6edf5;font:24px system-ui;background:#101722dd;padding:16px 24px;border-radius:8px;';
    view.appendChild(label);
   });
  }
  await page.locator('#viewport').screenshot({path:`${root}/${name}-after.png`,timeout:180000});
  ledger.push({sample:name,...state,errors,source_scene_sha256:record.source_scene_sha256,scene_sha256:record.scene_sha256,
               before_capture:reference.asset,camera_policy:'same_camera_and_target_as_verified_baseline'});
  await fs.writeFile(`${root}/captures.json`,JSON.stringify(ledger,null,2));
  console.log(`Captured ${name}`,state.triangles);
 } finally {await browser.close();}
}
