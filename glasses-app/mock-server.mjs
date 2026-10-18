// Fake backend for testing the glasses app without the real drone/LLM pipeline.
//   GET  /latest  -> current summary JSON (cycles through samples every 10s)
//   POST /latest  -> replace the summary with your own JSON (stops cycling)
import http from 'node:http'

const PORT = Number(process.env.PORT ?? 8787)

const samples = [
  {
    priority: 'warning',
    headline: 'Fire spreading NE, 400m ahead',
    instructions: ['Hold position at ridge trail', 'Wind shifting east, 15 km/h', 'Next update in 30s'],
  },
  {
    priority: 'critical',
    headline: 'Fire ahead - move right now',
    instructions: ['Take the down-right path to creek', 'Do NOT go back 50m - spot fire', 'Crew 2 is 200m south of you'],
  },
  {
    priority: 'info',
    headline: 'Area behind you is clear',
    instructions: ['Safe zone: parking lot B', 'Fire front stable for 5 min'],
  },
]

let current = null
let cycling = true
let i = 0

function publish(summary) {
  current = { id: `${Date.now()}`, timestamp: new Date().toISOString(), ...summary }
  console.log(`[${current.priority}] ${current.headline}`)
}

publish(samples[0])
setInterval(() => {
  if (cycling) publish(samples[++i % samples.length])
}, 10000)

http
  .createServer((req, res) => {
    // CORS: the glasses app is served from a different origin than this server.
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
    if (req.method === 'OPTIONS') return res.writeHead(204).end()

    if (req.url !== '/latest') return res.writeHead(404).end()

    if (req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify(current))
    }

    if (req.method === 'POST') {
      let body = ''
      req.on('data', (c) => (body += c))
      req.on('end', () => {
        try {
          cycling = false
          publish(JSON.parse(body))
          res.writeHead(200).end('ok')
        } catch {
          res.writeHead(400).end('invalid JSON')
        }
      })
      return
    }

    res.writeHead(405).end()
  })
  .listen(PORT, () => console.log(`Mock summary server on http://localhost:${PORT}/latest`))
