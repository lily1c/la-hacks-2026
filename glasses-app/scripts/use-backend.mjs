// Point the app at a backend: writes VITE_SUMMARY_URL to .env.local and sets
// the network whitelist in app.json to match.
//   npm run use-backend -- https://example.trycloudflare.com
//   npm run use-backend -- http://localhost:8787        (back to the local mock)
import { readFileSync, writeFileSync } from 'node:fs'

const arg = process.argv[2]
if (!arg) {
  console.error('Usage: npm run use-backend -- <backend URL>')
  process.exit(1)
}

const url = new URL(arg)
const summaryUrl = url.pathname === '/' ? `${url.origin}/latest` : url.href

writeFileSync('.env.local', `VITE_SUMMARY_URL=${summaryUrl}\n`)

const app = JSON.parse(readFileSync('app.json', 'utf8'))
const network = app.permissions.find((p) => p.name === 'network')
network.whitelist = [url.origin]
writeFileSync('app.json', JSON.stringify(app, null, 2) + '\n')

console.log(`Summaries from: ${summaryUrl}`)
console.log(`Whitelist:      ${url.origin}`)
console.log('Now run: npm run pack')
