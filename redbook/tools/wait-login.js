// Poll CDP Chrome for xiaohongshu web_session cookie (user logging in manually)
const http = require('http');

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

async function tryOnce() {
  const version = await getJson('/json/version');
  return await new Promise((resolve) => {
    const ws = new WebSocket(version.webSocketDebuggerUrl);
    ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: 'Storage.getCookies' }));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === 1) {
        const all = (msg.result && msg.result.cookies) || [];
        const xhs = all.filter((c) => c.domain.includes('xiaohongshu.com'));
        ws.close();
        resolve(xhs);
      }
    };
    ws.onerror = () => resolve([]);
  });
}

async function main() {
  const deadline = Date.now() + 10 * 60 * 1000; // 10 min
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt++;
    try {
      const xhs = await tryOnce();
      const names = xhs.map((c) => c.name);
      const has = names.includes('web_session');
      if (attempt % 6 === 0 || has) console.error(`[${new Date().toLocaleTimeString()}] attempt=${attempt} xhs_cookies=${xhs.length} web_session=${has}`);
      if (has) {
        const str = xhs.map((c) => `${c.name}=${c.value}`).join('; ');
        require('fs').writeFileSync('tmp_redbook_cookie_string.txt', str, 'utf8');
        console.error('LOGIN DETECTED. Cookie string saved to tmp_redbook_cookie_string.txt');
        process.exit(0);
      }
    } catch (e) { /* chrome not ready yet */ }
    await sleep(5000);
  }
  console.error('Timeout: no web_session within 10 minutes.');
  process.exit(1);
}
main();
