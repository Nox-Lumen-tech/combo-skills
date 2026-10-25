// Poll for creator center login completion (URL leaves /login)
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

async function main() {
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    try {
      const tabs = await getJson('/json');
      const creator = tabs.find((t) => t.url.includes('creator.xiaohongshu.com'));
      if (creator && !creator.url.includes('/login')) {
        console.error('CREATOR LOGGED IN:', creator.url);
        process.exit(0);
      }
    } catch (e) {}
    await sleep(4000);
  }
  console.error('Timeout: creator login not completed in 10 min.');
  process.exit(1);
}
main();
