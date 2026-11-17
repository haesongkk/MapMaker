import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const names=process.argv.slice(2);
const scenes=names.length?names:['present-office-c','new-office','present-cabinet'];
for(const name of scenes)if(!['present-office-c','new-office','present-cabinet'].includes(name))throw Error('Unknown scene');
const frames=80,size=640;
const server=http.createServer(async(req,res)=>{
  try{
    const relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname).slice(1);
    if(!relative.startsWith('web/')&&!relative.startsWith('.runtime/depth-support-fitted/')){res.writeHead(404).end();return;}
    const file=path.resolve(root,relative);
    if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
    const data=await fs.readFile(file);
    const type=file.endsWith('.js')?'text/javascript':file.endsWith('.html')?'text/html; charset=utf-8':'application/octet-stream';
    res.writeHead(200,{'Content-Type':type});res.end(data);
  }catch{res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
let browser;
try{
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=d3d11']});
  for(const name of scenes){
    const folder=path.join(root,'.runtime','turntable-frames',name);
    await fs.mkdir(folder,{recursive:true});
    const page=await browser.newPage({viewport:{width:size,height:size},deviceScaleFactor:1});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`${origin}/web/result-viewer.html?scene=${name}&capture`,{timeout:180000});
    await page.waitForFunction(()=>window.ready,{},{timeout:180000});
    await page.evaluate(async({frames})=>{
      const T=await import('three');
      const {scene,camera,controls,r}=window.viewer;
      const box=new T.Box3().setFromObject(scene),center=box.getCenter(new T.Vector3());
      const corners=[];
      for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])corners.push(new T.Vector3(x,y,z).sub(center));
      const yaw=Math.atan2(.4,-1),elevation=.34;
      const direction=i=>new T.Vector3(Math.sin(yaw+i*2*Math.PI/frames),elevation,Math.cos(yaw+i*2*Math.PI/frames)).normalize();
      let distance=0;
      for(let i=0;i<frames;i++){
        const dir=direction(i),right=new T.Vector3().crossVectors(new T.Vector3(0,1,0),dir).normalize(),up=new T.Vector3().crossVectors(dir,right).normalize();
        for(const p of corners)distance=Math.max(distance,p.dot(dir)+Math.max(Math.abs(p.dot(up)),Math.abs(p.dot(right))/camera.aspect)/Math.tan(T.MathUtils.degToRad(camera.fov/2)));
      }
      distance*=1.08;controls.target.copy(center);camera.near=Math.max(distance/10000,.00001);camera.far=distance*10;camera.updateProjectionMatrix();
      window.drawTurntable=i=>{camera.position.copy(center).add(direction(i).multiplyScalar(distance));camera.lookAt(center);r.render(scene,camera);};
      window.drawTurntable(0);
    },{frames});
    for(let i=0;i<frames;i++){
      await page.evaluate(i=>window.drawTurntable(i),i);
      const png=await page.evaluate(()=>window.viewer.r.domElement.toDataURL('image/png').split(',')[1]);
      await fs.writeFile(path.join(folder,`${String(i).padStart(3,'0')}.png`),Buffer.from(png,'base64'));
      if(i%20===0)console.log(`${name}: ${i}/${frames}`);
    }
    if(errors.length)throw Error(errors.join('\n'));
    await page.close();
    const output=path.join(root,'artifacts','turntables',`${name}.gif`);
    await fs.mkdir(path.dirname(output),{recursive:true});
    const python=process.platform==='win32'?path.join(root,'.venv','Scripts','python.exe'):path.join(root,'.venv','bin','python');
    const code=`from PIL import Image
from pathlib import Path
import sys
frames=[Image.open(p).convert('RGB') for p in sorted(Path(sys.argv[1]).glob('[0-9][0-9][0-9].png'))]
samples=Image.new('RGB',(160*10,160*8))
for i,im in enumerate(frames):
 thumb=im.resize((160,160));samples.paste(thumb,((i%10)*160,(i//10)*160))
palette=samples.quantize(colors=256)
indexed=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in frames]
indexed[0].save(sys.argv[2],save_all=True,append_images=indexed[1:],duration=80,loop=0,optimize=False,disposal=1)
with Image.open(sys.argv[2]) as gif:
 assert gif.n_frames==80 and gif.info['loop']==0
print(sys.argv[2],Path(sys.argv[2]).stat().st_size)
`;
    const result=spawnSync(python,['-c',code,folder,output],{encoding:'utf8'});
    if(result.status!==0)throw Error(result.stderr);
    console.log(result.stdout.trim());
  }
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
