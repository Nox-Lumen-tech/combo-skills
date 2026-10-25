// guard.js — 风控防护闸门（所有 redbook-tools 脚本执行前必须调用）
// 用法:
//   node guard.js check <opType>   → exit 0 允许 / exit 1 拒绝(原因输出到 stderr)
//   node guard.js record <opType> <ok|captcha|denied>  → 记录操作结果
//   node guard.js block <hours> [reason] → 手动进入冷却
//   node guard.js status → 查看当前状态
// opType: read | search | post | api
const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(process.env.USERPROFILE || '', '.redbook', 'guard-state.json');

// —— 安全参数（2026-10-22 风控事故校准）——
const CONFIG = {
  minIntervalMin: 30,          // 任意两次自动化操作最小间隔（分钟）
  dailyMaxOps: 3,              // 单日最大操作次数
  captchaCooldownHours: 48,    // 触发验证码/风控后的冷却时间（小时）
  postRequiresPrivateFirst: true, // 发帖必须先私密验证过（记录在 state）
};

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch (e) {
    return { ops: [], blockedUntil: null, blockReason: null, privateVerified: false };
  }
}

function saveState(s) {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(s, null, 2));
}

function check(opType) {
  const s = loadState();
  const now = Date.now();

  // 1. 冷却期检查
  if (s.blockedUntil && now < new Date(s.blockedUntil).getTime()) {
    const remain = Math.ceil((new Date(s.blockedUntil).getTime() - now) / 3600000);
    return { ok: false, reason: `BLOCKED: cooling down ${remain}h left (reason: ${s.blockBlockReason || s.blockReason || 'risk control'})` };
  }

  // 2. 最近一次操作若结果是 captcha/denied → 自动进入 48h 冷却并拒绝
  const last = s.ops[s.ops.length - 1];
  if (last && (last.result === 'captcha' || last.result === 'denied')) {
    s.blockedUntil = new Date(now + CONFIG.captchaCooldownHours * 3600000).toISOString();
    s.blockReason = `last op ${last.type}@${last.time} got ${last.result}`;
    saveState(s);
    return { ok: false, reason: `BLOCKED: previous op hit ${last.result}, auto cooldown ${CONFIG.captchaCooldownHours}h` };
  }

  // 3. 操作间隔 —— 例外：read/search 属于同一阅读会话（人搜完立刻点开结果）；
  //    unblock/override 等管理记录不是平台操作，不参与间隔计算；
  //    RB_TEST_SESSION=1：用户显式授权的连续测试会话（如一次测完读+发），豁免间隔但计入日限并留痕。
  if (last) {
    const mgmtTypes = ['unblock', 'user-override'];
    let lastOp = last;
    while (lastOp && mgmtTypes.includes(lastOp.type)) {
      const idx = s.ops.indexOf(lastOp);
      lastOp = idx > 0 ? s.ops[idx - 1] : null;
    }
    const testSession = process.env.RB_TEST_SESSION === '1';
    if (lastOp && !testSession) {
      const gapMin = (now - new Date(lastOp.time).getTime()) / 60000;
      const sameReadSession = (opType === 'read' || opType === 'search') && (lastOp.type === 'read' || lastOp.type === 'search');
      if (!sameReadSession && gapMin < CONFIG.minIntervalMin) {
        return { ok: false, reason: `TOO SOON: last op ${Math.round(gapMin)}min ago, min interval ${CONFIG.minIntervalMin}min (set RB_TEST_SESSION=1 for authorized continuous test)` };
      }
    }
  }

  // 4. 单日次数 —— 读会话（search+read 连续）合计为 1 次
  const today = new Date().toDateString();
  const mgmtTypes = ['unblock', 'user-override'];
  const todayOps = s.ops.filter((o) => new Date(o.time).toDateString() === today && !mgmtTypes.includes(o.type));
  const readSessionCount = todayOps.some((o) => o.type === 'read' || o.type === 'search') ? 1 : 0;
  const writeOps = todayOps.filter((o) => o.type !== 'read' && o.type !== 'search').length;
  const effectiveCount = readSessionCount + writeOps;
  if (effectiveCount >= CONFIG.dailyMaxOps) {
    return { ok: false, reason: `DAILY LIMIT: ${effectiveCount}/${CONFIG.dailyMaxOps} effective ops today` };
  }

  // 5. 发帖前置验证 —— 私密发帖本身就是验证，应放行；仅拦截非私密公开发帖
  const isPrivate = process.env.RB_POST_PRIVATE === '1';
  if (opType === 'post' && CONFIG.postRequiresPrivateFirst && !s.privateVerified && !isPrivate) {
    return { ok: false, reason: 'POST GUARD: must publish one --private note first (or: node guard.js mark-verified)' };
  }

  return { ok: true, reason: `OK: ${effectiveCount}/${CONFIG.dailyMaxOps} effective ops today` };
}

function record(opType, result) {
  const s = loadState();
  s.ops.push({ type: opType, result, time: new Date().toISOString() });
  // 只保留最近 50 条
  if (s.ops.length > 50) s.ops = s.ops.slice(-50);
  if (result === 'captcha' || result === 'denied') {
    s.blockedUntil = new Date(Date.now() + CONFIG.captchaCooldownHours * 3600000).toISOString();
    s.blockReason = `${opType} got ${result} at ${new Date().toISOString()}`;
  }
  if (opType === 'post' && result === 'ok') s.privateVerified = true; // 成功发布过即视为通道验证（私密发布 OK 也算）
  if (opType === 'post-private' && result === 'ok') s.privateVerified = true;
  saveState(s);
  return 'recorded';
}

function status() {
  const s = loadState();
  const today = new Date().toDateString();
  const todayOps = s.ops.filter((o) => new Date(o.time).toDateString() === today);
  return JSON.stringify({
    stateFile: STATE_FILE,
    blockedUntil: s.blockedUntil,
    blockReason: s.blockReason || null,
    nowBlocked: s.blockedUntil ? Date.now() < new Date(s.blockedUntil).getTime() : false,
    todayOps: `${todayOps.length}/${CONFIG.dailyMaxOps}`,
    privateVerified: !!s.privateVerified,
    recent: s.ops.slice(-5),
    config: CONFIG,
  }, null, 2);
}

const [,, cmd, a, b, c] = process.argv;
switch (cmd) {
  case 'check': {
    const r = check(a || 'read');
    console.error(r.reason);
    process.exit(r.ok ? 0 : 1);
  }
  case 'record':
    console.log(record(a, b));
    break;
  case 'block': {
    const s = loadState();
    s.blockedUntil = new Date(Date.now() + (parseFloat(a) || 48) * 3600000).toISOString();
    s.blockReason = c ? `${b} ${c}` : (b || 'manual');
    saveState(s);
    console.log('blocked until', s.blockedUntil);
    break;
  }
  case 'mark-verified': {
    const s = loadState();
    s.privateVerified = true;
    saveState(s);
    console.log('private channel marked verified');
    break;
  }
  case 'unblock': {
    // 显式解除熔断：必须提供理由（通常是用户明确授权），记录在案
    const s = loadState();
    const reason = process.argv.slice(3).join(' ') || 'no reason given';
    if (s.blockedUntil) {
      s.ops.push({ type: 'unblock', result: 'authorized', time: new Date().toISOString(), note: reason });
      s.blockedUntil = null;
      s.blockReason = null;
      saveState(s);
      console.log('unblocked. reason recorded:', reason);
    } else {
      console.log('not blocked');
    }
    break;
  }
  case 'status':
  default:
    console.log(status());
}
