// Fake backend for testing the glasses app without the real drone/LLM pipeline.
//   GET  /latest   -> current summary JSON (cycles through samples every 10s)
//   POST /latest   -> replace the summary with your own JSON (stops cycling)
//   GET  /map.png  -> generated 288×144 greyscale fire map (?fire=<radius>)
//   POST /report   -> voice report (audio/wav), saved to ./reports/
import http from 'node:http'
import { mkdirSync, writeFileSync } from 'node:fs'
import { deflateSync } from 'node:zlib'

const PORT = Number(process.env.PORT ?? 8787)

const samples = [
  {
    priority: 'warning',
    headline: 'Fire spreading NE, 400m ahead',
    instructions: ['Hold position at ridge trail', 'Wind shifting east, 15 km/h', 'Next update in 30s'],
    fire: 30,
  },
  {
    priority: 'critical',
    headline: 'Fire ahead - move right now',
    instructions: ['Take the down-right path to creek', 'Do NOT go back 50m - spot fire', 'Crew 2 is 200m south of you'],
    fire: 48,
  },
  {
    priority: 'info',
    headline: 'Area behind you is clear',
    instructions: ['Safe zone: parking lot B', 'Fire front stable for 5 min'],
    fire: 40,
  },
]

let current = null
let cycling = true
let i = 0

function publish({ fire, ...summary }) {
  const id = `${Date.now()}`
  current = {
    id,
    timestamp: new Date().toISOString(),
    ...(fire ? { map_url: `/map.png?fire=${fire}&v=${id}` } : {}),
    ...summary,
  }
  console.log(`[${current.priority}] ${current.headline}`)
}

publish(samples[0])
setInterval(() => {
  if (cycling) publish(samples[++i % samples.length])
}, 10000)

// --- Map rendering: 8-bit greyscale, 0 = off (transparent on the glasses), 255 = brightest ---

const W = 288
const H = 144

function drawMap(fireRadius) {
  const px = new Uint8Array(W * H)
  const set = (x, y, v) => {
    x = Math.round(x)
    y = Math.round(y)
    if (x >= 0 && x < W && y >= 0 && y < H) px[y * W + x] = Math.max(px[y * W + x], v)
  }

  // Border so the map area is visible.
  for (let x = 0; x < W; x++) set(x, 0, 90), set(x, H - 1, 90)
  for (let y = 0; y < H; y++) set(0, y, 90), set(W - 1, y, 90)

  // Fire: irregular blob in the upper right, brighter at the core.
  const fx = 200, fy = 45
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const a = Math.atan2(y - fy, x - fx)
      const edge = fireRadius * (1 + 0.12 * Math.sin(a * 3 + 0.5) + 0.07 * Math.sin(a * 7 + 1))
      const d = Math.hypot(x - fx, y - fy)
      if (d < edge) set(x, y, (x + y) % 3 === 0 ? 255 : d < edge * 0.6 ? 200 : 140)
    }
  }

  // You: ring with a filled centre.
  const ux = 110, uy = 70
  for (let a = 0; a < Math.PI * 2; a += 0.05) set(ux + 8 * Math.cos(a), uy + 8 * Math.sin(a), 255)
  for (let y = -3; y <= 3; y++) for (let x = -3; x <= 3; x++) if (x * x + y * y <= 9) set(ux + x, uy + y, 255)

  // Escape route: dashed line down-left to the safe zone.
  const sx = 30, sy = 125
  const steps = 120
  for (let s = 0; s <= steps; s++) {
    if (Math.floor(s / 6) % 2) continue
    const t = s / steps
    for (let w = -1; w <= 1; w++) set(ux + (sx - ux) * t + w, uy + (sy - uy) * t, 220)
  }

  // Safe zone: hollow square.
  for (let d = -7; d <= 7; d++) {
    for (let w = 0; w < 2; w++) {
      set(sx + d, sy - 7 + w, 255), set(sx + d, sy + 7 - w, 255)
      set(sx - 7 + w, sy + d, 255), set(sx + 7 - w, sy + d, 255)
    }
  }

  // North arrow, top left.
  for (let y = 0; y < 14; y++) for (let x = -Math.floor(y / 2); x <= Math.floor(y / 2); x++) set(18 + x, 8 + y, 200)

  return encodePng(px, W, H)
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

function crc32(buf) {
  let c = 0xffffffff
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([len, body, crc])
}

function encodePng(px, w, h) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 0 // greyscale
  const raw = Buffer.alloc((w + 1) * h)
  for (let y = 0; y < h; y++) {
    raw[y * (w + 1)] = 0 // no filter
    Buffer.from(px.buffer, y * w, w).copy(raw, y * (w + 1) + 1)
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

// --- HTTP ---

function readBody(req) {
  return new Promise((resolve) => {
    const parts = []
    req.on('data', (c) => parts.push(c))
    req.on('end', () => resolve(Buffer.concat(parts)))
  })
}

http
  .createServer(async (req, res) => {
    // CORS: the glasses app is served from a different origin than this server.
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
    if (req.method === 'OPTIONS') return res.writeHead(204).end()

    const url = new URL(req.url, 'http://localhost')

    if (url.pathname === '/latest' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify(current))
    }

    if (url.pathname === '/latest' && req.method === 'POST') {
      try {
        cycling = false
        publish(JSON.parse(await readBody(req)))
        return res.writeHead(200).end('ok')
      } catch {
        return res.writeHead(400).end('invalid JSON')
      }
    }

    if (url.pathname === '/map.png' && req.method === 'GET') {
      const fire = Math.min(80, Math.max(5, Number(url.searchParams.get('fire')) || 35))
      res.writeHead(200, { 'Content-Type': 'image/png' })
      return res.end(drawMap(fire))
    }

    if (url.pathname === '/report' && req.method === 'POST') {
      const audio = await readBody(req)
      mkdirSync('reports', { recursive: true })
      const file = `reports/report-${new Date().toISOString().replace(/[:.]/g, '-')}.wav`
      writeFileSync(file, audio)
      const seconds = Math.max(0, audio.length - 44) / 32000
      console.log(`Voice report: ${seconds.toFixed(1)}s -> ${file}`)
      res.writeHead(200, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify({ ok: true, seconds }))
    }

    res.writeHead(404).end()
  })
  .listen(PORT, () => console.log(`Mock backend on http://localhost:${PORT} (GET /latest, GET /map.png, POST /report)`))
