import http from 'node:http';
import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { networkInterfaces } from 'node:os';
import { configuration, validateSource } from './relay.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const runtime = resolve(root, '.runtime');
const binary = resolve(runtime, 'mediamtx');
const configPath = resolve(runtime, 'mediamtx.yml');
const mediaBind = process.env.MEDIA_BIND || '127.0.0.1';
configuration(null, mediaBind);
await mkdir(runtime, { recursive: true, mode: 0o700 });
let relay, source = null, revision = 0, changing = false, relayError = null;
const lanIPs = Object.values(networkInterfaces()).flat().filter(i => i && i.family === 'IPv4' && !i.internal).map(i => i.address);

async function configure(nextSource) {
  try { await access(binary); } catch { throw new Error('MediaMTX is not installed. Run npm run setup first.'); }
  if (relay) {
    const previous = relay;
    await new Promise(resolveExit => { previous.once('exit', resolveExit); previous.kill('SIGTERM'); });
  }
  await writeFile(configPath, configuration(nextSource, mediaBind), { mode: 0o600 });
  relayError = null;
  const child = spawn(binary, [configPath], { cwd: runtime, stdio: ['ignore', 'pipe', 'pipe'] });
  relay = child;
  // Never log raw relay output: upstream URLs may contain credentials.
  const recordError = () => { relayError = 'Relay reported a source or connection problem. Verify the source URL, credentials, network and codec.'; };
  child.stdout.on('data', recordError);
  child.stderr.on('data', recordError);
  await new Promise((ok, fail) => {
    child.once('spawn', ok);
    child.once('error', fail);
  });
  child.once('exit', () => { if (relay === child) relay = null; });
  source = nextSource;
  revision++;
}

async function status() {
  let path, apiAvailable = false;
  try {
    const response = await fetch('http://127.0.0.1:9997/v3/paths/list', { signal: AbortSignal.timeout(1500) });
    if (response.ok) { apiAvailable = true; path = (await response.json()).items.find(p => p.name === 'firesight'); }
  } catch {}
  return {
    mode: source ? 'pull' : 'publish', configured: Boolean(source), revision,
    relayRunning: Boolean(relay) && apiAvailable, ready: Boolean(path?.ready),
    tracks: path?.tracks || [], bytesReceived: path?.bytesReceived ?? 0,
    readers: path?.readers?.length ?? 0,
    message: path?.ready ? 'Receiving video' : relayError || (source ? 'Connecting to source; waiting for media' : 'Waiting for a publisher'),
    urls: { rtsp: 'rtsp://127.0.0.1:8554/firesight', hls: 'http://127.0.0.1:8888/firesight/index.m3u8', player: 'http://127.0.0.1:8888/firesight/', publish: 'rtmp://127.0.0.1:1935/firesight' },
    lanEnabled: mediaBind === '0.0.0.0', lanIPs
  };
}
function send(res, code, data) { res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)); }
const pages = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'] };
const server = http.createServer(async (req, res) => {
  try {
    // Local administration only; reject cross-origin mutations and DNS rebinding.
    if (!['127.0.0.1:8787', 'localhost:8787'].includes(req.headers.host)) return send(res, 403, { error: 'Local access only' });
    if (req.method === 'POST') {
      if (req.headers.origin && !['http://127.0.0.1:8787', 'http://localhost:8787'].includes(req.headers.origin)) return send(res, 403, { error: 'Origin rejected' });
      if (!req.headers['content-type']?.startsWith('application/json')) return send(res, 415, { error: 'Use application/json' });
      if (!['/api/source', '/api/publisher'].includes(req.url)) return send(res, 404, { error: 'Not found' });
      let body = '';
      for await (const chunk of req) { body += chunk; if (body.length > 8192) return send(res, 413, { error: 'Request too large' }); }
      let data;
      try { data = JSON.parse(body || '{}'); } catch { return send(res, 400, { error: 'Invalid JSON' }); }
      let next;
      try { next = req.url === '/api/source' ? validateSource(data.url) : null; } catch (error) { return send(res, 400, { error: error.message }); }
      if (changing) return send(res, 409, { error: 'Configuration in progress. Try again shortly.' });
      changing = true;
      try { await configure(next); return send(res, 202, { accepted: true, ...await status() }); }
      finally { changing = false; }
    }
    if (req.method === 'GET' && req.url === '/api/status') return send(res, 200, await status());
    if (req.method === 'GET' && pages[req.url]) {
      const [file, type] = pages[req.url];
      res.writeHead(200, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      return res.end(await readFile(resolve(root, 'public', file)));
    }
    send(res, 404, { error: 'Not found' });
  } catch (error) { send(res, 500, { error: error.message }); }
});
server.on('error', error => { console.error(error.message); relay?.kill(); process.exit(1); });
try { await configure(null); } catch (error) { relayError = error.message; console.error(error.message); }
server.listen(8787, '127.0.0.1', () => console.log('FireSight receiver: http://127.0.0.1:8787'));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { relay?.kill('SIGTERM'); server.close(() => process.exit(0)); setTimeout(() => process.exit(0), 2000).unref(); });
