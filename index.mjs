// The Jump Room's server room: one always-on process that runs the online server of every game
// on the hub, the way Render runs one game's server.
//
// Every minute it reads the hub's public catalog (/api/catalog). For each game it looks inside the
// stored zip (only the table of contents at the end, through /api/part like the hub's own player
// does) for a "server/" folder. A game with one gets its server files pulled out, a tiny subset of
// its Dockerfile honoured (COPY, ENV, CMD, WORKDIR) and its CMD started on a loopback port.
//
// Players reach a game's server at   wss://<this host>/<person>/<game>   and this process passes
// the WebSocket straight through to that game's port. /health and /status say what is running.
// A new build uploaded to the hub replaces the running server as soon as nobody is connected.
//
// No dependencies. Needs node >= 20 and a Godot binary on PATH (or GODOT_BIN) for Godot servers.

import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { spawn } from 'node:child_process';

const HUB = (process.env.HUB_URL || 'https://jump-room.netlify.app').replace(/\/+$/, '');
const PORT = Number(process.env.PORT || 10000);
const BIND = process.env.BIND_ADDRESS || '0.0.0.0';
const DATA = process.env.DATA_DIR || path.join(os.tmpdir(), 'jump-room-server-room');
const GODOT_BIN = process.env.GODOT_BIN || 'godot';
const SCAN_MS = Math.max(15e3, Number(process.env.SCAN_SECONDS || 60) * 1000);
const ONLY = (process.env.GAMES || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean); // "alex/rift-rumble" for tests
const FILE_MAX = 64 * 1024 * 1024;        // one server file bigger than this is not a server file
const READY_MS = 120e3;                    // how long a server may take to come up (Godot downloads nothing, so this is generous)
const HOLD_MS = 75e3;                      // how long a player's socket waits for a starting server
const INTERNAL_BASE = Number(process.env.INTERNAL_PORT_BASE || 20000);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const KEY = /^[a-z0-9][a-z0-9-]{0,39}\/[a-z0-9][a-z0-9-]{0,39}$/;

const log = (key, ...a) => console.log(new Date().toISOString().slice(11, 19), key ? `[${key}]` : '[room]', ...a);

// ---------- reading a stored zip through the hub ----------

const metaCache = new Map();   // uploadId -> {bytes, parts, partSize}
async function hubJson(url) {
  const res = await fetch(url, { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}
async function meta(id) {
  if (!metaCache.has(id)) {
    const m = await hubJson(`${HUB}/api/upload/meta?id=${id}`);
    let partSize = m.partSize || null;
    if (!partSize) {
      if (m.parts === 1) partSize = m.bytes;
      else for (const s of [4 << 20, 3 << 20, 8 << 20, 2 << 20, 1 << 20]) if (Math.ceil(m.bytes / s) === m.parts) { partSize = s; break; }
    }
    metaCache.set(id, { bytes: Number(m.bytes), parts: Number(m.parts), partSize: partSize || 3 << 20 });
  }
  return metaCache.get(id);
}
const partCache = new Map();   // "id/n" -> Promise<Buffer>; small, the directory and server files are all we read
async function part(id, n) {
  const k = `${id}/${n}`;
  if (!partCache.has(k)) {
    partCache.set(k, (async () => {
      let last;
      for (let i = 0; i < 5; i++) {
        try {
          const res = await fetch(`${HUB}/api/part?id=${id}&n=${n}`);
          if (!res.ok) throw new Error(`part ${n} -> ${res.status}`);
          return Buffer.from(await res.arrayBuffer());
        } catch (e) { last = e; await sleep(500 * (i + 1)); }
      }
      throw last;
    })().catch((e) => { partCache.delete(k); throw e; }));
    while (partCache.size > 24) partCache.delete(partCache.keys().next().value);
  }
  return partCache.get(k);
}
async function readRange(id, start, end) {
  if (end <= start) return Buffer.alloc(0);
  const { partSize: P } = await meta(id);
  const first = Math.floor(start / P), last = Math.floor((end - 1) / P);
  const bufs = await Promise.all(Array.from({ length: last - first + 1 }, (_, i) => part(id, first + i)));
  const out = Buffer.alloc(end - start);
  let o = 0;
  for (let i = 0; i < bufs.length; i++) {
    const base = (first + i) * P, b = bufs[i];
    const s = Math.max(start, base) - base, e = Math.min(end, base + b.length) - base;
    b.copy(out, o, s, e); o += e - s;
  }
  return out;
}
const dirCache = new Map();    // uploadId -> Promise<Map<name, entry>>
function directory(id) {
  if (dirCache.has(id)) return dirCache.get(id);
  const p = (async () => {
    const { bytes } = await meta(id);
    const tailLen = Math.min(bytes, 65536 + 22 + 20);
    const tail = await readRange(id, bytes - tailLen, bytes);
    let e = -1;
    for (let i = tail.length - 22; i >= 0; i--) if (tail.readUInt32LE(i) === 0x06054b50) { e = i; break; }
    if (e < 0) throw new Error('not a zip file');
    let count = tail.readUInt16LE(e + 10), cdSize = tail.readUInt32LE(e + 12), cdOff = tail.readUInt32LE(e + 16);
    if (count === 0xffff || cdSize === 0xffffffff || cdOff === 0xffffffff) {
      const loc = e - 20;
      if (loc >= 0 && tail.readUInt32LE(loc) === 0x07064b50) {
        const z64Off = Number(tail.readBigUInt64LE(loc + 8));
        const z = await readRange(id, z64Off, z64Off + 56);
        if (z.readUInt32LE(0) !== 0x06064b50) throw new Error('bad zip64 record');
        count = Number(z.readBigUInt64LE(32)); cdSize = Number(z.readBigUInt64LE(40)); cdOff = Number(z.readBigUInt64LE(48));
      }
    }
    const cd = await readRange(id, cdOff, cdOff + cdSize);
    const entries = new Map();
    let p = 0;
    for (let i = 0; i < count && p + 46 <= cd.length; i++) {
      if (cd.readUInt32LE(p) !== 0x02014b50) break;
      const method = cd.readUInt16LE(p + 10);
      let csize = cd.readUInt32LE(p + 20), usize = cd.readUInt32LE(p + 24);
      const nameLen = cd.readUInt16LE(p + 28), extraLen = cd.readUInt16LE(p + 30), commentLen = cd.readUInt16LE(p + 32);
      let offset = cd.readUInt32LE(p + 42);
      const name = cd.subarray(p + 46, p + 46 + nameLen).toString('utf8').replace(/\\/g, '/');
      let x = p + 46 + nameLen;
      const xEnd = x + extraLen;
      while (x + 4 <= xEnd) {
        const hid = cd.readUInt16LE(x), hlen = cd.readUInt16LE(x + 2);
        if (hid === 1) {
          let q = x + 4;
          const end = Math.min(xEnd, x + 4 + hlen);
          if (usize === 0xffffffff && q + 8 <= end) { usize = Number(cd.readBigUInt64LE(q)); q += 8; }
          if (csize === 0xffffffff && q + 8 <= end) { csize = Number(cd.readBigUInt64LE(q)); q += 8; }
          if (offset === 0xffffffff && q + 8 <= end) { offset = Number(cd.readBigUInt64LE(q)); q += 8; }
        }
        x += 4 + hlen;
      }
      if (!name.endsWith('/')) entries.set(name, { method, csize, usize, offset });
      p += 46 + nameLen + extraLen + commentLen;
    }
    return entries;
  })().catch((e) => { dirCache.delete(id); throw e; });
  dirCache.set(id, p);
  return p;
}
async function fileFromZip(id, ent) {
  if (ent.usize > FILE_MAX) throw new Error('file too big for a server file: ' + ent.usize);
  const lh = await readRange(id, ent.offset, ent.offset + 30);
  if (lh.readUInt32LE(0) !== 0x04034b50) throw new Error('bad zip entry header');
  const start = ent.offset + 30 + lh.readUInt16LE(26) + lh.readUInt16LE(28);
  const raw = await readRange(id, start, start + ent.csize);
  if (ent.method === 0) return raw;
  if (ent.method === 8) return zlib.inflateRawSync(raw);
  throw new Error('unsupported zip compression ' + ent.method);
}

// ---------- what counts as a server, and how to start it ----------

const SERVER_DIR = /^server\/(Dockerfile|server\.(gd|mjs|js|py))$/;
function serverEntry(entries) {
  // A Dockerfile under server/ wins; a bare server.gd gets the default recipe below.
  if (entries.has('server/Dockerfile')) return 'server/Dockerfile';
  if (entries.has('server/server.gd')) return null;
  return undefined;
}
function hasServer(entries) { return serverEntry(entries) !== undefined || [...entries.keys()].some((n) => SERVER_DIR.test(n)); }

// The handful of Dockerfile lines a game server needs. Everything else (FROM, RUN, USER, EXPOSE,
// ARG, HEALTHCHECK) is the base image's business and is skipped.
function parseDockerfile(text) {
  const plan = { copies: [], env: {}, cmd: null, workdir: '/app' };
  const lines = text.replace(/\\\r?\n/g, ' ').split(/\r?\n/);
  for (let line of lines) {
    line = line.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^(\w+)\s+(.*)$/s);
    if (!m) continue;
    const op = m[1].toUpperCase(), rest = m[2].trim();
    if (op === 'WORKDIR') plan.workdir = rest;
    else if (op === 'ENV') {
      const pairs = rest.match(/(\w+)=("[^"]*"|'[^']*'|\S+)/g);
      if (pairs) for (const p of pairs) { const [k, v] = [p.slice(0, p.indexOf('=')), p.slice(p.indexOf('=') + 1)]; plan.env[k] = v.replace(/^["']|["']$/g, ''); }
      else { const sp = rest.match(/^(\w+)\s+(.*)$/); if (sp) plan.env[sp[1]] = sp[2]; }
    } else if (op === 'COPY' || op === 'ADD') {
      const args = rest.replace(/--\S+\s*/g, '').match(/"[^"]*"|\S+/g).map((s) => s.replace(/^"|"$/g, ''));
      if (args.length >= 2) plan.copies.push({ from: args.slice(0, -1), to: args[args.length - 1] });
    } else if (op === 'CMD' || op === 'ENTRYPOINT') {
      let cmd = null;
      if (rest.startsWith('[')) { try { cmd = JSON.parse(rest); } catch {} }
      if (!cmd) cmd = rest.match(/"[^"]*"|'[^']*'|\S+/g).map((s) => s.replace(/^["']|["']$/g, ''));
      plan.cmd = op === 'ENTRYPOINT' && plan.cmd ? cmd.concat(plan.cmd) : cmd;
    }
  }
  return plan;
}
// No Dockerfile: a Godot script server laid out like the hub asks for (server/server.gd extends SceneTree).
const DEFAULT_PLAN = {
  copies: [{ from: ['server/'], to: './server/' }, { from: ['scripts/'], to: './scripts/' }],
  env: {}, workdir: '/app',
  cmd: ['godot', '--headless', '--audio-driver', 'Dummy', '--path', '.', '--script', 'res://server/server.gd'],
};

const safeRel = (p) => {
  const n = path.posix.normalize(String(p).replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, ''));
  if (n === '.' ) return '';
  if (n.startsWith('..')) throw new Error('path escapes the server folder: ' + p);
  return n;
};

// Pull the server's files out of the zip into dir, following the plan's COPY lines.
async function materialize(id, entries, plan, dir) {
  await fsp.rm(dir, { recursive: true, force: true });
  await fsp.mkdir(dir, { recursive: true });
  const written = [];
  const put = async (zipName, rel) => {
    const ent = entries.get(zipName);
    if (!ent) return false;
    const out = path.join(dir, rel);
    await fsp.mkdir(path.dirname(out), { recursive: true });
    await fsp.writeFile(out, await fileFromZip(id, ent));
    written.push(rel);
    return true;
  };
  for (const c of plan.copies) {
    const toRaw = c.to.replace(/\\/g, '/');
    const toDir = toRaw.endsWith('/') || c.from.length > 1 || toRaw === '.' || toRaw === './';
    const to = toRaw.startsWith(plan.workdir) ? toRaw.slice(plan.workdir.length) : toRaw;   // "/app/x" -> "x"
    for (const srcRaw of c.from) {
      const src = safeRel(srcRaw);
      if (src === '' || src.endsWith('/') || [...entries.keys()].some((n) => n.startsWith(src + '/'))) {
        // a folder: everything under it
        const prefix = src === '' ? '' : src.replace(/\/$/, '') + '/';
        for (const n of entries.keys()) {
          if (!n.startsWith(prefix)) continue;
          if (/(^|\/)(\.git|\.godot|node_modules)\//.test(n)) continue;
          const ent = entries.get(n);
          if (ent.usize > FILE_MAX || /\.(png|jpe?g|webp|gif|wav|ogg|mp3|mp4|webm|pck|wasm|zip|exe|dll|so|ttf|otf|import)$/i.test(n)) continue; // no art, no builds: a server has none
          const rel = safeRel(path.posix.join(to || '.', toDir ? n.slice(prefix.length) : path.posix.basename(n)));
          await put(n, rel);
        }
      } else {
        const rel = toDir ? safeRel(path.posix.join(to || '.', path.posix.basename(src))) : safeRel(to);
        if (!(await put(src, rel))) {
          // COPY of a glob or something the zip does not have: try a loose match on the basename
          const base = path.posix.basename(src);
          const hit = [...entries.keys()].find((n) => path.posix.basename(n) === base && n.startsWith(path.posix.dirname(src)));
          if (hit) await put(hit, rel); else log(null, 'COPY source not in the zip, skipped:', src);
        }
      }
    }
  }
  // A server that was written for its own container may name its WORKDIR as a literal ("/app").
  // Here it lives somewhere else, so those literals are pointed at the real folder.
  if (plan.workdir && plan.workdir !== '/' && plan.workdir !== '.') {
    const here = dir.replace(/\\/g, '/');
    for (const rel of written) {
      if (!/\.(m?js|cjs|gd|py|sh|cfg|json|toml|ya?ml|txt|godot|template)$/i.test(rel)) continue;
      const file = path.join(dir, rel);
      const st = await fsp.stat(file);
      if (st.size > 1 << 20) continue;
      const text = await fsp.readFile(file, 'utf8');
      const re = new RegExp(`(['"\`])${plan.workdir.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(/|\\1)`, 'g');
      if (re.test(text)) await fsp.writeFile(file, text.replace(re, (_, q, tail) => q + here + (tail === q ? q : '/')));
    }
  }
  return written;
}

// ---------- running servers ----------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const games = new Map();   // key -> game
let nextPort = INTERNAL_BASE;

function newGame(key, person, slug) {
  return { key, person, slug, state: 'idle', uploadId: null, build: 0, title: '', version: '', port: 0, proc: null, dir: '', cmd: null,
    sockets: new Set(), pending: null, failures: 0, since: 0, error: '', lastLog: [] };
}

async function tcpOpen(port) {
  return new Promise((resolve) => {
    const s = net.connect({ host: '127.0.0.1', port });
    const done = (ok) => { s.destroy(); resolve(ok); };
    s.setTimeout(1500, () => done(false));
    s.on('connect', () => done(true));
    s.on('error', () => done(false));
  });
}
async function healthOf(port) {
  // 200 = ready, 503 = still starting, anything else (a plain Godot socket server answers no HTTP) = ready enough
  try {
    const ac = new AbortController(); const t = setTimeout(() => ac.abort(), 2500);
    const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: ac.signal });
    clearTimeout(t);
    return res.status === 503 ? 'starting' : 'ready';
  } catch { return 'ready'; }
}

async function start(g, info, entries) {
  const id = info.uploadId;
  g.state = 'starting'; g.error = ''; g.since = Date.now(); g.uploadId = id; g.build = info.build; g.title = info.title; g.version = info.version;
  const dockerfile = serverEntry(entries);
  let plan = DEFAULT_PLAN;
  if (dockerfile) plan = parseDockerfile((await fileFromZip(id, entries.get(dockerfile))).toString('utf8'));
  if (!plan.cmd) plan = { ...plan, cmd: DEFAULT_PLAN.cmd };
  g.dir = path.join(DATA, g.person, g.slug, id);
  const files = await materialize(id, entries, plan, g.dir);
  if (!files.length) throw new Error('the server folder had no files this room could run');
  g.port = nextPort++;
  const cmd = plan.cmd.map((a) => (a === 'godot' || a === 'godot4' ? GODOT_BIN : a));
  g.cmd = cmd.join(' ');
  const env = { ...process.env, ...plan.env, PORT: String(g.port), BIND_ADDRESS: '127.0.0.1', HOST: '127.0.0.1', GODOT_BIN, JUMP_ROOM_HUB: HUB, JUMP_ROOM_GAME: g.key };
  log(g.key, `build ${g.build}: ${files.length} files, starting on :${g.port} ->`, g.cmd);
  const proc = spawn(cmd[0], cmd.slice(1), { cwd: g.dir, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  g.proc = proc;
  const tail = (data) => {
    for (const line of data.toString().split(/\r?\n/)) {
      if (!line.trim()) continue;
      log(g.key, line.slice(0, 300));
      g.lastLog.push(line.slice(0, 300)); if (g.lastLog.length > 30) g.lastLog.shift();
    }
  };
  proc.stdout.on('data', tail); proc.stderr.on('data', tail);
  proc.on('exit', (code, signal) => {
    if (g.proc !== proc) return;
    g.proc = null;
    const wanted = g.state === 'stopping';
    g.state = 'idle';
    for (const s of g.sockets) s.destroy();
    g.sockets.clear();
    log(g.key, `server exited (${signal || code})${wanted ? '' : ', will restart'}`);
    if (!wanted) { g.failures++; g.error = `exited with ${signal || code}`; scheduleScan(Math.min(60e3, 5e3 * g.failures)); }
  });
  const until = Date.now() + READY_MS;
  while (Date.now() < until) {
    if (g.proc !== proc) throw new Error('server stopped while starting');
    if (await tcpOpen(g.port)) {
      const h = await healthOf(g.port);
      if (h === 'ready') { g.state = 'running'; g.failures = 0; g.since = Date.now(); log(g.key, `ready at /${g.key}`); return; }
    }
    await sleep(1000);
  }
  throw new Error('server did not come up in time');
}
function stop(g) {
  const proc = g.proc;
  if (!proc) { g.state = 'idle'; return; }
  g.state = 'stopping';
  log(g.key, 'stopping');
  proc.kill('SIGTERM');
  setTimeout(() => { if (g.proc === proc) proc.kill('SIGKILL'); }, 4000).unref();
}

// ---------- the scan: catalog -> which games have servers -> start/replace them ----------

let scanning = false, scanTimer = null;
function scheduleScan(ms) { clearTimeout(scanTimer); scanTimer = setTimeout(() => scan().catch((e) => log(null, 'scan failed:', e.message)), ms); scanTimer.unref(); }

async function scan() {
  if (scanning) return;
  scanning = true;
  try {
    const cat = await hubJson(`${HUB}/api/catalog`);
    const seen = new Set();
    for (const person of cat.people || []) {
      for (const g of person.games || []) {
        const key = `${person.id}/${g.id}`;
        if (!KEY.test(key) || !UUID.test(g.uploadId || '')) continue;
        if (ONLY.length && !ONLY.includes(key)) continue;
        const info = { uploadId: g.uploadId, build: g.build, title: g.title, version: g.version || `${g.uploadId}:${g.build}` };
        let game = games.get(key);
        if (game && game.uploadId === info.uploadId && game.state !== 'idle') { seen.add(key); continue; }   // nothing new
        let entries;
        try { entries = await directory(info.uploadId); }
        catch (e) { log(key, 'could not read the zip:', e.message); continue; }
        if (!hasServer(entries)) { if (game) { seen.add(key); game.pending = null; } continue; }
        seen.add(key);
        if (!game) { game = newGame(key, person.id, g.id); games.set(key, game); }
        if (game.state === 'starting' || game.state === 'stopping') continue;
        if (game.state === 'running' && game.uploadId !== info.uploadId) {
          if (game.sockets.size) { if (!game.pending) log(key, `build ${info.build} is waiting for ${game.sockets.size} player(s) to finish`); game.pending = { info, entries }; continue; }
          stop(game);
          await sleep(500);
        }
        if (game.failures >= 8) { if (!game.error.includes('gave up')) { game.error += ' (gave up; a new upload will try again)'; log(key, game.error); } if (game.uploadId === info.uploadId) continue; game.failures = 0; }
        try { await start(game, info, entries); }
        catch (e) { game.failures++; game.error = e.message; game.state = 'idle'; if (game.proc) stop(game); log(key, 'could not start:', e.message); }
      }
    }
    // Games taken off the hub: stop their servers.
    for (const [key, game] of games) if (!seen.has(key) && !(ONLY.length && !ONLY.includes(key))) { if (game.proc) stop(game); games.delete(key); log(key, 'no longer on the hub'); }
    // A waiting build whose players have left.
    for (const game of games.values()) {
      if (game.pending && game.state === 'running' && !game.sockets.size) {
        const { info, entries } = game.pending; game.pending = null;
        stop(game); await sleep(500);
        try { await start(game, info, entries); } catch (e) { game.failures++; game.error = e.message; game.state = 'idle'; log(game.key, 'could not start:', e.message); }
      }
    }
  } finally {
    scanning = false;
    scheduleScan(SCAN_MS);
  }
}

// ---------- the front door ----------

const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, OPTIONS', 'access-control-allow-headers': 'content-type', 'access-control-max-age': '86400' };
const publicGame = (g) => ({ key: g.key, person: g.person, game: g.slug, title: g.title, build: g.build, version: g.version, state: g.state,
  players: g.sockets.size, url: `/${g.key}`, since: g.since ? new Date(g.since).toISOString() : null, error: g.error || null, waiting: g.pending ? g.pending.info.build : null });
const status = () => ({ status: 'ok', room: 'jump-room-server-room', hub: HUB, uptime: Math.round(process.uptime()), games: [...games.values()].map(publicGame) });
function findGame(pathname) {
  const m = pathname.match(/^\/([a-z0-9][a-z0-9-]{0,39})\/([a-z0-9][a-z0-9-]{0,39})(\/.*)?$/);
  if (!m) return null;
  return { key: `${m[1]}/${m[2]}`, rest: m[3] || '/' };
}

const server = http.createServer({ maxHeaderSize: 16384, headersTimeout: 15000, requestTimeout: 15000 }, (req, res) => {
  const url = new URL(req.url, 'http://x');
  const send = (code, data) => { res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...CORS }); res.end(JSON.stringify(data)); };
  if (req.method === 'OPTIONS') { res.writeHead(204, CORS); res.end(); return; }
  if (!['GET', 'HEAD'].includes(req.method)) { send(405, { error: 'GET only' }); return; }
  if (url.pathname === '/' || url.pathname === '/health' || url.pathname === '/status') { send(200, status()); return; }
  const f = findGame(url.pathname);
  if (f) {
    const g = games.get(f.key);
    if (g) { send(200, publicGame(g)); return; }
    send(404, { error: 'No server for ' + f.key + ' on this room (yet).', scanning, games: [...games.keys()] });
    return;
  }
  send(404, { error: 'Not found' });
});
server.maxConnections = 400;

server.on('upgrade', async (req, socket, head) => {
  const refuse = (code, text) => { try { socket.end(`HTTP/1.1 ${code} ${text}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch {} };
  const url = new URL(req.url, 'http://x');
  const f = findGame(url.pathname);
  if (!f || req.method !== 'GET' || String(req.headers.upgrade || '').toLowerCase() !== 'websocket') { refuse(404, 'Not Found'); return; }
  let g = games.get(f.key);
  if (!g) { scheduleScan(0); refuse(404, 'No Such Game Server'); return; }
  socket.pause();
  socket.setTimeout(0);
  socket.setNoDelay(true);
  // A server that is waking or starting: hold the player's socket for a bit instead of bouncing it.
  const until = Date.now() + HOLD_MS;
  while (g.state !== 'running' && Date.now() < until && !socket.destroyed) { if (g.state === 'idle') scheduleScan(0); await sleep(1000); g = games.get(f.key) || g; }
  if (socket.destroyed) return;
  if (g.state !== 'running') { refuse(503, 'Game Server Starting'); return; }
  const upstream = net.connect({ host: '127.0.0.1', port: g.port });
  g.sockets.add(socket);
  const cleanup = () => { g.sockets.delete(socket); socket.destroy(); upstream.destroy(); };
  socket.on('error', cleanup); socket.on('close', cleanup);
  upstream.on('error', cleanup); upstream.on('close', cleanup);
  upstream.on('connect', () => {
    let header = `GET ${f.rest}${url.search} HTTP/${req.httpVersion}\r\n`;
    for (let i = 0; i < req.rawHeaders.length; i += 2) header += `${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}\r\n`;
    upstream.write(header + '\r\n');
    if (head.length) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
    socket.resume();
  });
});
server.on('clientError', (_e, socket) => { try { socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'); } catch {} });

function shutdown() {
  log(null, 'shutting down');
  server.close();
  for (const g of games.values()) { for (const s of g.sockets) s.destroy(); if (g.proc) stop(g); }
  setTimeout(() => process.exit(0), 4500).unref();
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

fs.mkdirSync(DATA, { recursive: true });
server.listen(PORT, BIND, () => {
  log(null, `listening on ${BIND}:${PORT}, hub ${HUB}, godot ${GODOT_BIN}, files in ${DATA}${ONLY.length ? ', only ' + ONLY.join(' ') : ''}`);
  scan().catch((e) => log(null, 'first scan failed:', e.message));
});
