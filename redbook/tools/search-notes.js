// Navigate XHS tab to search results, grab note URLs (tab-level WS, correct context)
// GUARDED: run through risk-control guard (interval/daily-limit/captcha-cooldown)
const http = require('http');
const { execSync } = require('child_process');

try {
  execSync('node guard.js check search', { cwd: __dirname, stdio: ['ignore', 'inherit', 'inherit'] });
} catch (e) { process.exit(1); }
const GUARD_DONE = () => { try { execSync('node guard.js record search ok', { cwd: __dirname, stdio: 'ignore' }); } catch (e) {} };

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: 9222, path }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const tabs = await getJson('/json');
  const xhs = tabs.find((t) => t.url && t.url.includes('xiaohongshu.com'));
  if (!xhs) { console.error('No XHS tab'); process.exit(1); }
  console.error('Using tab:', xhs.id, xhs.url.slice(0, 60));

  const ws = new WebSocket(xhs.webSocketDebuggerUrl);
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
  await send('Page.navigate', { url: 'https://www.xiaohongshu.com/search_result?keyword=Cursor' });
  await sleep(9000);

  const evalRes = await send('Runtime.evaluate', {
    expression: `(() => {
      const hrefs = Array.from(document.querySelectorAll('a')).map(a => a.href)
        .filter(h => h.includes('/explore/') || h.includes('/search_result/'));
      const title = document.title;
      return JSON.stringify({ title, count: hrefs.length, hrefs: hrefs.slice(0, 8) });
    })()`,
    returnByValue: true,
  });
  let info = {};
  try { info = JSON.parse(evalRes.result.result.value); } catch (e) { console.error('Parse failed:', evalRes.result && evalRes.result.result && evalRes.result.result.description); }
  console.error('Page title:', info.title);
  console.error('URL count:', info.count);
  console.error('URLs:', JSON.stringify(info.hrefs, null, 1));
  if (info.hrefs && info.hrefs.length) {
    require('fs').writeFileSync('tmp_redbook_note_url.txt', info.hrefs[0], 'utf8');
    console.error('Saved to tmp_redbook_note_url.txt');
    GUARD_DONE();
  }
  ws.close();
  process.exit(0);
}
main().catch((e) => { console.error('Fatal:', e.message); process.exit(1); });
