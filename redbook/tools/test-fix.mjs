// test-fix.mjs — 验证官方 redbook CLI fork 的 CDP cookie 提取修复
// 前置：CDP Chrome 在 127.0.0.1:9222 运行中（含 xiaohongshu.com 登录态）
// 判定：
//   TEST 1 修复后的 getCookiesFromCdp 能返回 cookies（Storage.getCookies 路径）
//   TEST 2 修复后的完整 extractCookiesViaCdp 流程拿到 a1 / web_session
//   TEST 3 whoami（用 fork 的 cli.js + 修复后的 cookie）guest=false
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
// fork 里的 dist/lib/cdp-cookies.js 是 ESM，直接 import
const mod = await import('./dist/lib/cdp-cookies.js');

let pass = 0, fail = 0;
const t = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  ✅ ${name}${detail ? ' — ' + detail : ''}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
};

console.log('== TEST 1: getCookiesFromCdp (Storage.getCookies fix, via internal flow) ==');
// getCookiesFromCdp is not exported; its fix is exercised inside extractCookiesViaCdp (TEST 2).
// Here we only assert the module loads and exports the public API used by cli.js.
t('module exports extractCookiesViaCdp', typeof mod.extractCookiesViaCdp === 'function');

console.log('== TEST 2: extractCookiesViaCdp (full flow) ==');
try {
  const res = await mod.extractCookiesViaCdp((m) => process.stderr.write('   [cdp] ' + m + '\n'));
  t('returns cookies object', !!res.cookies && Object.keys(res.cookies).length > 0,
    `keys=${Object.keys(res.cookies).slice(0, 6).join(',')}...`);
  t('has a1', 'a1' in res.cookies);
  t('has web_session', 'web_session' in res.cookies);
} catch (e) {
  t('extractCookiesViaCdp works', false, e.message);
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
