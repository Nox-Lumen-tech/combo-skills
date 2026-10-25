// Wide viewport: locate red publish button by canvas pixel scan, then click its center
// GUARDED (strict): same rules as post-note.js — this performs the actual publish click.
const http = require('http');
const fs = require('fs');
const { execSync } = require('child_process');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  const isPriv = process.env.RB_POST_PRIVATE === '1' ? '1' : '0';
  execSync('node guard.js check post', { cwd: __dirname, stdio: ['ignore', 'inherit', 'inherit'],
    env: { ...process.env, RB_POST_PRIVATE: isPriv } });
} catch (e) { process.exit(1); }
function guardRecord(result) {
  try { execSync(`node guard.js record post ${result}`, { cwd: __dirname, stdio: 'ignore' }); } catch (e) {}
}

function getJson(p) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: 9222, path: p }, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

async function main() {
  const tabs = await getJson('/json');
  const tab = tabs.find((t) => t.url.includes('publish/publish'));
  if (!tab) { console.error('No publish tab'); process.exit(1); }

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  function send(method, params = {}) {
    return new Promise((resolve) => {
      const id = ++msgId;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });
  }
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  await new Promise((r) => (ws.onopen = r));
  await send('Page.enable');
  await send('Page.bringToFront');

  // ensure wide + scrolled bottom
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  await sleep(2000);
  await send('Runtime.evaluate', { expression: `(() => { const c = document.querySelector('.publish-page'); if (c) { c.scrollTop = c.scrollHeight; c.dispatchEvent(new Event('scroll', { bubbles: true })); } return true; })()`, returnByValue: true });
  await sleep(2000);
  await send('Runtime.evaluate', { expression: `(() => { const c = document.querySelector('.publish-page'); if (c) c.scrollTop = c.scrollHeight; return true; })()`, returnByValue: true });
  await sleep(1500);

  // pixel-scan via screenshot decoded in Node (no page canvas needed)
  // bar is at l=280..ri=960, t=710..b=800; red button per wide screenshot sits right side ~x830-950, y~715-770
  // take clip screenshot of bar and scan locally
  const shot = await send('Page.captureScreenshot', { format: 'png', clip: { x: 600, y: 705, width: 380, height: 95, scale: 1 } });
  const png = Buffer.from(shot.result.data, 'base64');
  fs.writeFileSync('tmp_redbook_bar2.png', png);

  // scan with pure node PNG decode — use browser to decode instead (in page context, small image)
  const scan = await send('Runtime.evaluate', {
    expression: `(async () => {
      const b64 = ${JSON.stringify(shot.result.data)};
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      await new Promise((res) => { img.onload = res; });
      const cv = document.createElement('canvas');
      cv.width = img.width; cv.height = img.height;
      const ctx = cv.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const data = ctx.getImageData(0, 0, cv.width, cv.height).data;
      let minX = 1e9, minY = 1e9, maxX = -1, maxY = -1, count = 0;
      for (let y = 0; y < cv.height; y++) {
        for (let x = 0; x < cv.width; x++) {
          const i = (y * cv.width + x) * 4;
          const R = data[i], G = data[i + 1], B = data[i + 2];
          if (R > 220 && G < 110 && B < 130) { count++; if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; }
        }
      }
      if (!count) return 'no red';
      // bbox is relative to clip origin (600,705)
      return JSON.stringify({ count, bboxAbs: { x1: minX + 600, y1: minY + 705, x2: maxX + 600, y2: maxY + 705 }, center: { x: Math.round((minX + maxX) / 2) + 600, y: Math.round((minY + maxY) / 2) + 705 } });
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  const scanInfo = scan.result && scan.result.result;
  console.error('Red button bbox:', JSON.stringify(scanInfo));

  let center;
  try { center = JSON.parse(scanInfo.value).center; } catch (e) { console.error('parse fail'); process.exit(1); }
  console.error('Clicking center:', center);

  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: center.x, y: center.y });
  await sleep(250);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: center.x, y: center.y, button: 'left', clickCount: 1 });
  await sleep(100);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: center.x, y: center.y, button: 'left', clickCount: 1 });
  console.error('Clicked. Waiting 15s...');
  await sleep(15000);

  const after = await send('Runtime.evaluate', {
    expression: `JSON.stringify({ url: location.href, head: document.body.innerText.slice(0, 150) })`,
    returnByValue: true,
  });
  console.error('After:', after.result.result.value);
  let afterInfo = {};
  try { afterInfo = JSON.parse(after.result.result.value); } catch (e) {}
  if (afterInfo.url && (afterInfo.url.includes('publish/success') || afterInfo.url.includes('published=true'))) {
    guardRecord('ok');
    console.error('GUARD: published successfully, recorded ok');
  } else if (afterInfo.head && /验证|异常|拦截/.test(afterInfo.head)) {
    guardRecord('captcha');
    console.error('GUARD: captcha/risk detected → auto 48h cooldown started');
  } else {
    guardRecord('denied');
    console.error('GUARD: publish outcome unclear → recorded denied (conservative)');
  }

  try {
    const s2 = await send('Page.captureScreenshot', { format: 'jpeg', quality: 60 });
    fs.writeFileSync('tmp_redbook_wide_after.jpg', Buffer.from(s2.result.data, 'base64'));
    console.error('After screenshot saved');
  } catch (e) {}

  ws.close();
  process.exit(0);
}
main().catch((e) => { console.error('Fatal:', e.message); process.exit(1); });
