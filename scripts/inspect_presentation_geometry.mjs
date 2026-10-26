import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const root=process.argv[2]||'docs/assets/ram-qwen-filter-presentation';
const records=JSON.parse(await fs.readFile(`${root}/scene-manifest.json`,'utf8'));
const only=process.argv[3];
for(const [name,vs] of Object.entries(records)){
 if(only&&name!==only)continue;
 const r=vs['vision-furniture'];if(!r)continue;
 if(await fs.stat(`${root}/${name}-geometry-2.png`).catch(()=>null))continue;
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto(`http://127.0.0.1:8136/viewer?run=${r.alias}`);
  await page.waitForFunction(()=>window.scenePreview?.ready&&window.scenePreview.renderer.info.render.triangles>0,{},{timeout:300000});
  await page.evaluate(()=>document.fonts.ready);
  const state=await page.evaluate(()=>{
   const v=window.scenePreview;v.controls.dispatchEvent({type:'start'});
   if(v.grid)v.grid.visible=false;
   return {camera:v.camera.position.toArray(),target:v.controls.target.toArray()};
  });
  for(const [i,angle] of [0,-Math.PI/4,Math.PI/4].entries()){
   await page.evaluate(({state,angle})=>{
    const v=window.scenePreview;const [x,y,z]=state.camera.map((n,i)=>n-state.target[i]);
    v.camera.position.set(state.target[0]+x*Math.cos(angle)-z*Math.sin(angle),state.target[1]+y,state.target[2]+x*Math.sin(angle)+z*Math.cos(angle));
    v.controls.target.fromArray(state.target);v.controls.update();v.renderer.render(v.scene,v.camera);
   },{state,angle});
   await page.locator('#viewport').screenshot({path:`${root}/${name}-geometry-${i}.png`});
  }
  console.log('Geometry angles captured:',name);
 }finally{await browser.close();}
}
