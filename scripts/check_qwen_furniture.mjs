import {chromium} from '../web/node_modules/@playwright/test/index.mjs';
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const page=await browser.newPage({viewport:{width:2400,height:1200},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html');
 if(await page.locator('section').count()!==5||await page.locator('figure').count()!==35)throw Error('Unexpected comparison rows or figures');
 for(const name of ['house','office','sample-01','sample-02','sample-04']) {
  const row=page.locator(`#${name}`);
  if(await row.locator('figure').count()!==7)throw Error(`Missing experiment column ${name}`);
  await row.locator('img').evaluateAll(async images=>{await Promise.all(images.map(i=>i.decode()));});
  await row.screenshot({path:`docs/assets/ram-qwen-filter-vision-furniture/comparison-${name}.png`});
  const urls=await row.locator('figcaption a').evaluateAll(as=>as.map(a=>a.href));
  for(const url of urls){const response=await page.request.get(url);if(!response.ok())throw Error(`Bad viewer ${url}`);}
 }
 if(errors.length)throw Error(JSON.stringify(errors));
 console.log('Five rows of seven versions verified; 35 figures total, images decoded, viewer links OK');
} finally {await browser.close();}
