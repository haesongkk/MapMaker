import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const page=await browser.newPage({viewport:{width:2200,height:1200},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html');
 if(await page.locator('section').count()!==10||await page.locator('figure').count()!==45)throw Error('Missing comparison figures');
 for(const name of ['house','office','sample-01','sample-02','sample-04']) {
  const row=page.locator(`#${name}`);
  if(await row.locator('figure').count()!==5)throw Error(`Missing vision column ${name}`);
  await row.locator('img').evaluateAll(async images=>{await Promise.all(images.map(i=>i.decode()));});
  await row.screenshot({path:`docs/assets/ram-qwen-filter-vision-movable/comparison-${name}.png`});
  const url=await row.locator('figcaption a').last().getAttribute('href');
  const response=await page.request.get(url);if(!response.ok())throw Error(`Bad viewer ${name}`);
 }
 if(errors.length)throw Error(JSON.stringify(errors));
 console.log('Five new vision columns and all 40 existing figures verified');
} finally {await browser.close();}
