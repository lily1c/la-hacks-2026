import {
  waitForEvenAppBridge,
  TextContainerProperty,
  TextContainerUpgrade,
  CreateStartUpPageContainer,
  RebuildPageContainer,
  OsEventTypeList,
} from '@evenrealities/even_hub_sdk'
import { parseSummary, type Summary } from './summary'

// Where the backend serves the latest summary. Override with VITE_SUMMARY_URL in .env.local.
const SUMMARY_URL = import.meta.env.VITE_SUMMARY_URL ?? 'http://localhost:8787/latest'
const POLL_MS = 2000
// After this long without a successful fetch, warn the wearer that the info may be out of date.
const STALE_MS = 15000
// Rough fit for the 576×288 canvas.
const MAX_LINES = 9
const MAX_LINE_CHARS = 44

const bridge = await waitForEvenAppBridge()

let summary: Summary | null = null
let lastOkAt = 0
let shown = ''

function clip(line: string): string {
  return line.length > MAX_LINE_CHARS ? line.slice(0, MAX_LINE_CHARS - 1) + '…' : line
}

function render(): string {
  const lines: string[] = []
  const age = lastOkAt ? Date.now() - lastOkAt : Infinity

  if (age > STALE_MS) {
    // Round to 5s so we don't redraw the glasses every second.
    lines.push(lastOkAt ? `NO SIGNAL - last update ${Math.floor(age / 5000) * 5}s ago` : 'Connecting to command...')
  }

  if (summary) {
    const time = new Date(summary.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const tag = summary.priority === 'critical' ? '!! CRITICAL' : summary.priority === 'warning' ? '! WARNING' : 'INFO'
    lines.push(`${tag}   ${time}`, summary.headline.toUpperCase(), '')
    for (const step of summary.instructions) lines.push(`- ${step}`)
  } else if (lastOkAt) {
    lines.push('Waiting for first update...')
  }

  return lines.slice(0, MAX_LINES).map(clip).join('\n')
}

const mainText = new TextContainerProperty({
  xPosition: 0,
  yPosition: 0,
  width: 576,
  height: 288,
  borderWidth: 0,
  borderColor: 5,
  paddingLength: 4,
  containerID: 1,
  containerName: 'main',
  content: (shown = render()),
  isEventCapture: 1,
})

const result = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({ containerTotalNum: 1, textObject: [mainText] }),
)
if (result !== 0) {
  // The startup page can only be created once per session. After a Vite
  // reload it already exists, so rebuild it instead.
  const rebuilt = await bridge.rebuildPageContainer(
    new RebuildPageContainer({ containerTotalNum: 1, textObject: [mainText] }),
  )
  if (!rebuilt) console.error('createStartUpPageContainer failed:', result)
}

// Only send to the glasses when the text actually changed.
function refresh() {
  const next = render()
  if (next === shown) return
  shown = next
  bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID: 1, containerName: 'main', content: next }))
}

async function fetchLatest() {
  try {
    const res = await fetch(SUMMARY_URL, { cache: 'no-store', signal: AbortSignal.timeout(3000) })
    if (res.status === 204) {
      lastOkAt = Date.now() // backend is up, nothing published yet
    } else if (res.ok) {
      const next = parseSummary(await res.json())
      lastOkAt = Date.now()
      if (next) summary = next
      else console.warn('Ignoring malformed summary')
    } else {
      console.warn('Summary fetch failed:', res.status)
    }
  } catch (err) {
    console.warn('Summary fetch error:', err)
  }
  refresh()
}

async function pollLoop() {
  await fetchLatest()
  setTimeout(pollLoop, POLL_MS)
}

pollLoop()
// Keeps the "NO SIGNAL" age current even while fetches hang.
setInterval(refresh, 1000)

bridge.onEvenHubEvent((event) => {
  // Taps arrive as sysEvent (source-aware) or textEvent depending on host version.
  const input = event.textEvent ?? event.sysEvent
  if (!input) return

  switch (input.eventType) {
    case OsEventTypeList.CLICK_EVENT:
    case undefined: // SDK normalizes 0 to undefined in some cases
      // Tap to fetch immediately instead of waiting for the next poll.
      fetchLatest()
      break

    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      // Mode 1 shows the system exit-confirmation dialog (required on the root page).
      bridge.shutDownPageContainer(1)
      break
  }
})
