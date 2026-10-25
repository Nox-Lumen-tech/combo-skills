// Read cookie string from tmp file, save into redbook's own cookie file via auth save (stdin not used; spawn with env)
// This avoids passing cookies on the command line.
const { spawnSync } = require('child_process');
const fs = require('fs');

const cookieStr = fs.readFileSync('tmp_redbook_cookie_string.txt', 'utf8').trim();
if (!cookieStr.includes('web_session')) {
  console.error('Cookie string missing web_session, aborting.');
  process.exit(1);
}

// redbook.cmd shim is in cwd; call it via cmd
const r = spawnSync('cmd.exe', ['/c', 'redbook.cmd', 'auth', 'save', '--cookie-string', cookieStr], {
  cwd: 'd:\\rms-server',
  encoding: 'utf8',
});
console.log(r.stdout);
if (r.stderr) console.error(r.stderr.slice(0, 500));
process.exit(r.status || 0);
