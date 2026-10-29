import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

const root=path.resolve(process.argv[2]);
const phase=process.argv[3]||'floor';
const origin=process.argv[4]||'http://127.0.0.1:8142';
const state=JSON.parse(await fs.readFile(path.join(root,'state.json'),'utf8'));
const bundle=state.original_matrices?{objects:state.objects.map((o,i)=>({object_id:o.id,id:`O${String(i+1).padStart(3,'0')}`}))}:JSON.parse(await fs.readFile(path.join(root,'image-inputs','inputs.json'),'utf8'));
const floor=phase==='floor'||process.argv[5]==='inspect'?JSON.parse(await fs.readFile(path.join(root,'floor-report.json'),'utf8')):null;
const cameraPath=path.join(root,'comparison-camera.json');
const reference=await fs.readFile(cameraPath,'utf8').then(JSON.parse).catch(error=>{if(error.code==='ENOENT'&&['upright','floor-aligned'].includes(phase))return null;throw error;});
const relative=path.relative(process.cwd(),root).split(path.sep).map(encodeURIComponent).join('/');
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 const page=await browser.newPage({viewport:{width:1000,height:800}});
 await page.goto(origin);
 await page.setContent(`<style>body{margin:0}</style><script type="importmap">{"imports":{"three":"${origin}/web/node_modules/three/build/three.module.js","three/addons/":"${origin}/web/node_modules/three/examples/jsm/"}}</script>`);
 await page.evaluate(async({url,objects,phase,reference})=>{
  const THREE=await import('three');
  const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
  const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
  renderer.setSize(1000,800);renderer.setPixelRatio(1);renderer.setClearColor(0x182333);document.body.appendChild(renderer.domElement);
  const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xffffff,0x898989,2.5));
  const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(3,6,4);scene.add(light);
  const gltf=await new GLTFLoader().loadAsync(url);scene.add(gltf.scene);
  const box=new THREE.Box3().setFromObject(gltf.scene);const center=box.getCenter(new THREE.Vector3());
  const size=box.getSize(new THREE.Vector3());const radius=reference?.radius||size.length();
  if(reference)center.fromArray(reference.center);
  window.cameraReference={radius,center:center.toArray()};
  const camera=new THREE.PerspectiveCamera(40,1000/800,Math.max(radius/1000,.00001),radius*100);
  camera.position.copy(center).add(new THREE.Vector3(-.35,.20,1).normalize().multiplyScalar(radius*1.65));
  camera.lookAt(center);
  const grid=new THREE.GridHelper(radius*1.5,20,0x7e9aba,0x405067);grid.position.set(center.x,0,center.z);scene.add(grid);
  const label=document.createElement('div');Object.assign(label.style,{position:'absolute',top:'12px',left:'16px',color:'white',font:'20px sans-serif'});document.body.appendChild(label);
  const originals=[];gltf.scene.traverse(n=>{if(n.isMesh)originals.push([n,n.material]);});
  function highlight(id){
    for(const [n,m] of originals){
      if(n.material!==m)n.material.dispose();n.material=m;
      if(id){let p=n,selected=false;while(p){if(p.name===id)selected=true;p=p.parent;}
        n.material=new THREE.MeshBasicMaterial({color:selected?0xffb52e:0x626a76,side:THREE.DoubleSide,transparent:!selected,opacity:selected?1:.25,depthWrite:selected});
      }
    }
  }
  window.capture={draw:(id,text,angle=0)=>{highlight(id);label.textContent=text;
    const offset=new THREE.Vector3(-.35,.20,1).normalize().multiplyScalar(radius*1.65);offset.applyAxisAngle(new THREE.Vector3(0,1,0),angle);
    camera.position.copy(center).add(offset);camera.lookAt(center);renderer.render(scene,camera);},triangles:()=>renderer.info.render.triangles};
  window.capture.draw(null,phase);
 },{url:`${origin}/${relative}/${phase}.glb`,objects:state.objects,phase,reference});
 if(['upright','floor-aligned'].includes(phase))await fs.writeFile(cameraPath,JSON.stringify(await page.evaluate(()=>window.cameraReference)));
 await fs.mkdir(path.join(root,'renders'),{recursive:true});
 for(const [i,angle] of [0,-Math.PI/4,Math.PI/4,Math.PI].entries()){
  await page.evaluate(({phase,angle})=>window.capture.draw(null,phase,angle),{phase,angle});
  await page.screenshot({path:path.join(root,'renders',`${phase}-${i}.png`)});
 }
 if(floor){
  for(const oid of floor.candidates){
   const label=bundle.objects.find(o=>o.object_id===oid).id;
   await page.evaluate(({oid,label})=>window.capture.draw(oid,'Highlighted instance: '+label),{oid,label});
   await page.screenshot({path:path.join(root,'renders',`${phase}-${label}.png`)});
  }
 }
 console.log(JSON.stringify({phase,triangles:await page.evaluate(()=>window.capture.triangles()),candidates:floor?.candidates.length||0}));
} finally {await browser.close();}
