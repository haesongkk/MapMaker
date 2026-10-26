import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
const browser=await chromium.launch({channel:'chrome',headless:true});
const movable=process.argv.includes('--movable');
const allVersions=process.argv.includes('--v3')||movable;
const expected=allVersions?40:30;
try {
 const page=await browser.newPage({viewport:{width:1600,height:1050},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(allVersions&&!movable?'http://127.0.0.1:8136/docs/RAM_QWEN_FILTER_VERSIONS.html':'http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html');
 await page.locator('#house img').evaluateAll(async images=>{await Promise.all(images.map(i=>i.decode()));});
 const count=await page.locator('section').count();
 if(count!==10||await page.locator('figure').count()!==expected)throw Error('Missing comparison columns');
 await page.locator('#house').screenshot({path:movable?'docs/assets/ram-qwen-filter-movable/comparison-house.png':allVersions?'docs/assets/ram-qwen-filter-v3/four-way-house.png':'docs/assets/ram-qwen-filter-v2/three-way-house.png'});
 const links=await page.locator('figcaption a').evaluateAll(as=>as.map(a=>a.href));
 for(const url of links){const response=await page.request.get(url);if(!response.ok())throw Error(`Bad viewer ${url}`);}
 if(errors.length)throw Error(JSON.stringify(errors));
 console.log(`10 rows, ${expected} comparison images, ${expected} viewer pages verified`);
} finally {await browser.close();}
