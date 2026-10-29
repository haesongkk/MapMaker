import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const selection=JSON.parse(await fs.readFile('artifacts/assets/ram-qwen-filter-new-scenes/presentation-selection.json','utf8'));
if(selection.version!=='vision-furniture'||selection.samples.length!==3)throw Error('Final selection must contain three cases of the same method');
for(const item of selection.samples){
 const root=item.asset_root||(item.sample.startsWith('present-')?'artifacts/assets/ram-qwen-filter-presentation':'artifacts/assets/ram-qwen-filter-new-scenes');
 const captures=JSON.parse(await fs.readFile(`${root}/captures-clean.json`,'utf8'));
 const b=captures.find(c=>c.sample===item.sample&&c.version==='baseline');
 const f=captures.find(c=>c.sample===item.sample&&c.version==='vision-furniture');
 if(!b||!f||b.errors.length||f.errors.length||!b.grid_hidden||!f.grid_hidden)throw Error('Missing verified comparison capture');
 if(f.scene_sha256!==item.result.scene_sha256||b.input_sha256!==f.input_sha256)throw Error('Provenance mismatch');
 for(const key of ['camera','target'])if(b[key].some((x,i)=>Math.abs(x-f[key][i])>1e-10))throw Error('Different comparison cameras');
}
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1500,height:1100},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8135/artifacts/RAM_QWEN_FILTER_THREE_WAY.html');
 if(await page.locator('section').count()!==3||await page.locator('figure').count()!==9)throw Error('Expected three representative cases');
 if(await page.locator('#new-dining').count())throw Error('Rejected dining case returned');
 if(await page.locator('figure.final').count()!==3)throw Error('Expected same final method in three cases');
 await page.locator('img').evaluateAll(ims=>Promise.all(ims.map(im=>im.decode())));
 for(const url of await page.locator('a').evaluateAll(as=>as.map(a=>a.href).filter(u=>u.startsWith('http://127.0.0.1')))){
  if(!(await page.request.get(url)).ok())throw Error(`Broken local link: ${url}`);
 }
 await page.screenshot({path:'artifacts/assets/ram-qwen-filter-new-scenes/presentation-selection-preview.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Verified: 3 scenes, 1 final method, 9 images, excluded dining, local links, desktop and mobile layout.');
} finally {await browser.close();}
