import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1600,height:1100}});
 await page.goto('http://127.0.0.1:8118/docs/FOUR_WAY_COMPARISON.html');
 // Load every lazy image before checking the final document.
 await page.locator('img').evaluateAll(images=>images.forEach(img=>img.loading='eager'));
 await page.waitForFunction(()=>[...document.images].every(i=>i.complete && i.naturalWidth>0));
 const check=await page.evaluate(()=>({
  cards:document.querySelectorAll('article').length,
  images:document.querySelectorAll('article img').length,
  links:document.querySelectorAll('article a[href*="/viewer?run=four-way-"]').length,
  historical:document.body.innerText.includes('기존 참고'),
  broken:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src),
  mismatch:[...document.querySelectorAll('article')].filter(a=>{
   const alias=new URL(a.querySelector('a[href*="/viewer?"]').href).searchParams.get('run');
   return !a.querySelector('img')?.src.endsWith('/'+alias+'.png');
  }).length
 }));
 if(check.cards!==40||check.images!==40||check.links!==40||check.historical||check.broken.length||check.mismatch)throw Error(JSON.stringify(check));
 await page.screenshot({path:'.runtime/four-way-comparison/document-layout.png'});
 await fs.writeFile('.runtime/four-way-comparison/document-verification.json',JSON.stringify(check,null,2));
 console.log(check);
}finally{await browser.close();}
