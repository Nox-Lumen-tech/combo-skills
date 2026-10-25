// Read a XHS note's content via CDP Chrome (real browser session with login)
// Usage: node read-note.js [noteUrl]
// GUARDED: run through risk-control guard
const http = require('http');
const fs = require('fs');
const { execSync } = require('child_process');

try {
  execSync('node guard.js check read', { cwd: __dirname, stdio: ['ignore', 'inherit', 'inherit'] });
} catch (e) { process.exit(1); }
const GUARD_DONE = () => { try { execSync('node guard.js record read ok', { cwd: __dirname, stdio: 'ignore' }); } catch (e) {} };

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
  const url = process.argv[2] || fs.readFileSync('tmp_redbook_note_url.txt', 'utf8').trim();
  console.error('Reading:', url.slice(0, 80));

  // open a NEW tab for the note (keep search tab intact)
  const tab = await new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: 9222, path: '/json/new?' + encodeURIComponent(url), method: 'PUT' }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => resolve(JSON.parse(data)));
    });
    req.on('error', reject);
    req.end();
  });
  await sleep(8000);

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

  const evalRes = await send('Runtime.evaluate', {
    expression: `(() => {
      const title = (document.querySelector('#detail-title') || {}).textContent
        || (document.querySelector('.title')) && document.querySelector('.title').textContent
        || document.title;
      const desc = (document.querySelector('#detail-desc') || {}).textContent
        || (document.querySelector('.desc')) && document.querySelector('.desc').textContent
        || '';
      const author = (document.querySelector('.username') || {}).textContent || '';
      const date = (document.querySelector('.date') || {}).textContent || '';
      const likes = Array.from(document.querySelectorAll('.engage-bar .count, .like-wrapper .count')).map(e => e.textContent.trim()).join('/');
      const comments = Array.from(document.querySelectorAll('.comment-item')).slice(0, 5).map(ci => {
        const u = (ci.querySelector('.author .name, .name') || {}).textContent || '';
        const c = (ci.querySelector('.content') || {}).textContent || '';
        return u + ': ' + c.trim().slice(0, 100);
      });
      return JSON.stringify({ ok: !!title, title: title.trim(), author: author.trim(), date: date.trim(), likes, desc: desc.trim().slice(0, 500), comments });
    })()`,
    returnByValue: true,
  });
  let info = {};
  try { info = JSON.parse(evalRes.result.result.value); } catch (e) { console.error('Parse error'); }
  console.error(JSON.stringify(info, null, 2));
  if (info.ok) {
    fs.writeFileSync('tmp_redbook_note_content.json', JSON.stringify(info, null, 2), 'utf8');
    console.error('Saved to tmp_redbook_note_content.json');
    GUARD_DONE();
  }

  // close tab
  await getJson('/json/close/' + tab.id).catch(() => {});
  ws.close();
  process.exit(info.ok ? 0 : 1);
}
main().catch((e) => { console.error('Fatal:', e.message); process.exit(1); });
