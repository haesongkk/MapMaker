// A browser client only: the UI, API, models and artifacts all run remotely.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'web', 'package.json'));
const { chromium } = require('@playwright/test');
const config = JSON.parse(fs.readFileSync(path.join(root, 'configs/cloud-deployment.json'), 'utf8'));
const keyFile = path.join(root, '.runtime/runpod-api.key');
const key = fs.existsSync(keyFile)
  ? fs.readFileSync(keyFile, 'utf8').replace(/^\uFEFF/, '').trim()
  : process.env.RUNPOD_API_KEY;
if (!key) throw new Error('Set RUNPOD_API_KEY or configure .runtime/runpod-api.key');
const origin = new URL(config.web_url).origin;
if (!/^https:\/\/[a-z0-9]+\.api\.runpod\.ai$/.test(origin)) {
  throw new Error('Expected a Runpod endpoint HTTPS origin');
}
const browser = await chromium.launch({ channel: 'chrome', headless: false });
const context = await browser.newContext({ acceptDownloads: true });
// Scope the credential to this endpoint. Never send it to third-party requests.
await context.route('**/*', async route => {
  const request = route.request();
  if (new URL(request.url()).origin === origin) {
    await route.continue({ headers: { ...request.headers(), authorization: `Bearer ${key}` } });
  } else {
    await route.continue();
  }
});
const page = await context.newPage();
console.log('Opening remote MapMaker. No local web server is started.');
await page.goto(origin, { timeout: 180000 });
await new Promise(resolve => browser.on('disconnected', resolve));
