// Extract xiaohongshu.com cookies from Chrome via CDP Storage.getCookies (Chrome 155+ compatible)
const http = require('http');

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: 9222, path }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });
}

async function main() {
  const version = await getJson('/json/version');
  const wsUrl = version.webSocketDebuggerUrl;
  const ws = new WebSocket(wsUrl);
  const id = 1;
  ws.onopen = () => {
    ws.send(JSON.stringify({ id, method: 'Storage.getCookies' }));
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id === id) {
      if (msg.error) {
        console.error('CDP error:', msg.error);
        process.exit(1);
      }
      const all = msg.result.cookies || [];
      const xhs = all.filter((c) => /xiaohongshu\.com$/.test(c.domain.replace(/^\./, '')) || c.domain.includes('xiaohongshu.com'));
      const names = new Set(xhs.map((c) => c.name));
      const need = ['a1', 'web_session'];
      const missing = need.filter((n) => !names.has(n));
      console.error(`Total cookies: ${all.length}, xiaohongshu cookies: ${xhs.length}, missing required: ${missing.join(',') || 'none'}`);
      // Output cookie string (only to stdout, for piping)
      const str = xhs.map((c) => `${c.name}=${c.value}`).join('; ');
      require('fs').writeFileSync('tmp_redbook_cookie_string.txt', str, 'utf8');
      console.error('Cookie string written to tmp_redbook_cookie_string.txt (not printed to avoid leaking)');
      ws.close();
      process.exit(0);
    }
  };
  ws.onerror = (e) => { console.error('WS error:', e.message); process.exit(1); };
}
main();
