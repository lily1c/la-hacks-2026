// Point the app at a backend: writes VITE_SUMMARY_URL to .env.local and sets
// the network whitelist in app.json to match.
//   npm run use-backend -- https://example.trycloudflare.com
//   npm run use-backend -- http://localhost:8787        (back to the local mock)
import { readFileSync, writeFileSync, existsSync } from 'node:fs'

const arg = process.argv[2]
if (!arg) {
  console.error('Usage: npm run use-backend -- <backend URL>')
  process.exit(1)
}

const url = new URL(arg)
if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Use a backend HTTP(S) URL without credentials, query or fragment')
const summaryUrl = url.pathname === '/' ? `${url.origin}/latest` : url.href

const previous = existsSync('.env.local') ? readFileSync('.env.local', 'utf8') : ''
const kept = previous.split('\n').filter(line => !line.startsWith('VITE_SUMMARY_URL=')).join('\n').trim()
writeFileSync('.env.local', `${kept}${kept ? '\n' : ''}VITE_SUMMARY_URL=${summaryUrl}\n`)

const app = JSON.parse(readFileSync('app.json', 'utf8'))
const network = app.permissions.find((p) => p.name === 'network')
network.whitelist = [url.origin]
writeFileSync('app.json', JSON.stringify(app, null, 2) + '\n')

console.log(`Summaries from: ${summaryUrl}`)
console.log(`Whitelist:      ${url.origin}`)
console.log('Now run: npm run pack')
