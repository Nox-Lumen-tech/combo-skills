// Post image note via creator center (CDP browser channel)
// Usage: node post-note.js <title> <body> <imagePath> [--private] [--publish]
// GUARDED (strict): post is the highest-risk op — requires private-verified channel,
// 30min interval, daily limit, 48h captcha cooldown. Records result (captcha/denied → auto 48h block).
const http = require('http');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const GUARD_STATE = path.join(process.env.USERPROFILE || '', '.redbook', 'guard-state.json');
function guardFail(reason) {
  console.error('GUARD BLOCKED:', reason);
  process.exit(1);
}
// pre-check（私密发帖通过 RB_POST_PRIVATE=1 告知 guard：私密本身即通道验证，可放行）
try {
  const isPriv = process.argv.includes('--private') ? '1' : '0';
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
  const title = process.argv[2];
  const body = process.argv[3];
  const imagePath = process.argv[4];
  const doPublish = process.argv.includes('--publish');
  const doPrivate = process.argv.includes('--private');
  if (!title || !body || !imagePath) { console.error('Usage: node tmp_redbook_post_browser.js <title> <body> <imagePath> [--private] [--publish]'); process.exit(1); }

  // Reuse existing publish tab or open new one
  const tabs = await getJson('/json');
  let tab = tabs.find((t) => t.url.includes('publish/publish'));
  if (!tab) {
    tab = await new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port: 9222, path: '/json/new?https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image', method: 'PUT' }, (res) => {
        let d = '';
        res.on('data', (c) => (d += c));
        res.on('end', () => resolve(JSON.parse(d)));
      });
      req.on('error', reject);
      req.end();
    });
    await sleep(9000);
  }

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
  await send('DOM.enable');

  // Step 1: ensure 上传图文 tab active (click the leaf-node tab item)
  await send('Runtime.evaluate', {
    expression: `(() => {
      const els = Array.from(document.querySelectorAll('*')).filter(e => e.children.length === 0 && (e.textContent || '').trim() === '上传图文');
      if (els.length) els[els.length - 1].click();
      return true;
    })()`,
    returnByValue: true,
  });
  await sleep(3000);

  // Step 2: upload image — inject File via DataTransfer (no DOM domain needed)
  const imgB64 = require('fs').readFileSync(imagePath).toString('base64');
  const injectRes = await send('Runtime.evaluate', {
    expression: `(async () => {
      const b64 = ${JSON.stringify(imgB64)};
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const file = new File([bytes], 'image.png', { type: 'image/png' });
      const dt = new DataTransfer();
      dt.items.add(file);
      const input = document.querySelector('input.upload-input');
      if (!input) return 'no input';
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return 'file injected: ' + input.files.length;
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  console.error('Inject:', JSON.stringify(injectRes.result && injectRes.result.result));
  if (!injectRes.result || !injectRes.result.result || !String(injectRes.result.result.value).includes('file injected')) {
    console.error('File injection failed');
    process.exit(1);
  }
  console.error('Waiting for upload to complete...');
  await sleep(9000);

  // Step 3: fill title and body
  const fill = await send('Runtime.evaluate', {
    expression: `(() => {
      function fire(el) { el.dispatchEvent(new Event('input', { bubbles: true })); }
      const titleEl = document.querySelector('#title-textarea') || document.querySelector('input[placeholder*="标题"], textarea[placeholder*="标题"]');
      const bodyEl = document.querySelector('#post-textarea') || document.querySelector('.ql-editor') || document.querySelector('div[contenteditable=true]');
      let titleOk = false, bodyOk = false;
      if (titleEl) {
        if (titleEl.tagName === 'TEXTAREA' || titleEl.tagName === 'INPUT') {
          Object.getOwnPropertyDescriptor(window[titleEl.tagName === 'TEXTAREA' ? 'HTMLTextAreaElement' : 'HTMLInputElement'].prototype, 'value').set.call(titleEl, ${JSON.stringify(title)});
          fire(titleEl); titleOk = true;
        } else { titleEl.innerText = ${JSON.stringify(title)}; fire(titleEl); titleOk = true; }
      }
      if (bodyEl) {
        if (bodyEl.tagName === 'TEXTAREA') {
          Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(bodyEl, ${JSON.stringify(body)});
          fire(bodyEl); bodyOk = true;
        } else { bodyEl.innerText = ${JSON.stringify(body)}; bodyEl.dispatchEvent(new InputEvent('input', { bubbles: true })); bodyOk = true; }
      }
      return JSON.stringify({ titleOk, bodyOk, titleVal: titleEl ? (titleEl.value || titleEl.innerText || '').slice(0, 20) : null, bodyVal: bodyEl ? (bodyEl.value || bodyEl.innerText || '').slice(0, 20) : null });
    })()`,
    returnByValue: true,
  });
  console.error('Fill:', fill.result.result.value);
  await sleep(2000);

  // Step 4: set private if requested (仅自己可见)
  if (doPrivate) {
    const priv = await send('Runtime.evaluate', {
      expression: `(() => {
        const radios = Array.from(document.querySelectorAll('*')).filter(e => e.children.length === 0 && (e.textContent || '').includes('仅自己可见'));
        if (radios.length) { radios[radios.length - 1].click(); return 'private set'; }
        return 'private option not found';
      })()`,
      returnByValue: true,
    });
    console.error('Private:', priv.result.result.value);
    await sleep(1500);
  }

  // Step 5: verify state
  const verify = await send('Runtime.evaluate', {
    expression: `(() => {
      const imgs = document.querySelectorAll('.img-container img, .upload-preview img, img');
      const titleEl = document.querySelector('#title-textarea, input[placeholder*="标题"], textarea[placeholder*="标题"]');
      const bodyEl = document.querySelector('#post-textarea, .ql-editor, div[contenteditable=true]');
      const publishBtn = Array.from(document.querySelectorAll('button')).find(b => (b.textContent || '').trim() === '发布');
      return JSON.stringify({
        previewImgs: imgs.length,
        title: titleEl ? (titleEl.value || titleEl.innerText || '').slice(0, 30) : null,
        body: bodyEl ? (bodyEl.value || bodyEl.innerText || '').slice(0, 30) : null,
        publishBtnFound: !!publishBtn
      });
    })()`,
    returnByValue: true,
  });
  console.error('Verify:', verify.result.result.value);

  // Step 6: publish or dry-run
  if (doPublish) {
    // ensure scrolled to bottom so publish button is in view
    await send('Runtime.evaluate', {
      expression: `(() => { const c = document.querySelector('.publish-page'); if (c) c.scrollTop = c.scrollHeight; return true; })()`,
      returnByValue: true,
    });
    await sleep(1500);
    const pub = await send('Runtime.evaluate', {
      expression: `(() => {
        // publish is a span.has-tips inside a button at bottom bar
        const spans = Array.from(document.querySelectorAll('span')).filter(s => (s.textContent || '').trim() === '发布' && s.closest('.publish-page'));
        if (!spans.length) return 'no publish span';
        const btn = spans[spans.length - 1].closest('button') || spans[spans.length - 1];
        btn.click();
        return 'publish clicked';
      })()`,
      returnByValue: true,
    });
    console.error('Publish:', pub.result.result.value);
    await sleep(10000);
    const after = await send('Runtime.evaluate', {
      expression: `JSON.stringify({ url: location.href, body: document.body.innerText.slice(0, 300) })`,
      returnByValue: true,
    });
    console.error('After:', after.result.result.value);
    // success → publish/success URL means published; anything else with captcha text → record captcha
    let afterInfo = {};
    try { afterInfo = JSON.parse(after.result.result.value); } catch (e) {}
    if (afterInfo.url && (afterInfo.url.includes('publish/success') || afterInfo.url.includes('published=true'))) {
      guardRecord('ok');
      console.error('GUARD: published successfully, recorded ok');
    } else if (afterInfo.body && /验证|异常|拦截/.test(afterInfo.body)) {
      guardRecord('captcha');
      console.error('GUARD: captcha/risk detected → auto 48h cooldown started');
    } else {
      guardRecord('denied');
      console.error('GUARD: publish outcome unclear → recorded denied (conservative)');
    }
  } else {
    console.error('DRY RUN OK — check Chrome window, publish manually or rerun with --publish');
  }

  ws.close();
  process.exit(0);
}
main().catch((e) => { console.error('Fatal:', e.message); process.exit(1); });
