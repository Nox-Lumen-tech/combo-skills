const http = require('http');
http.get({ host: '127.0.0.1', port: 9222, path: '/json' }, (r) => {
  let d = '';
  r.on('data', (c) => (d += c));
  r.on('end', () => {
    JSON.parse(d).forEach((t) => console.log(t.type, '|', t.url.slice(0, 90), '|', (t.title || '').slice(0, 30)));
  });
});
