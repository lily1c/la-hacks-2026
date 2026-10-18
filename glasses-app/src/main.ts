import {
  waitForEvenAppBridge,
  TextContainerProperty,
  TextContainerUpgrade,
  ImageContainerProperty,
  ImageRawDataUpdate,
  ImageRawDataUpdateResult,
  CreateStartUpPageContainer,
  RebuildPageContainer,
  OsEventTypeList,
  AudioInputSource,
} from '@evenrealities/even_hub_sdk'
import { parseSummary, type Summary } from './summary'
import { pcmToWav, pcmSeconds } from './voice'
import { startLocationReports, hazardLine, type Nearby } from './location'
import { startTelemetry, type InputType } from './telemetry'
import { createSafety } from './safety'

// Where the backend serves the latest summary. Override with VITE_SUMMARY_URL in .env.local.
const SUMMARY_URL = import.meta.env.VITE_SUMMARY_URL ?? 'http://localhost:8790/latest'
// Voice reports are POSTed to the same backend.
const REPORT_URL = new URL('/report', SUMMARY_URL).href
const POLL_MS = 2000
// After this long without a successful fetch, warn the wearer that the info may be out of date.
const STALE_MS = 15000
const MAX_RECORD_SECONDS = 30

// Container IDs. MAIN is the only one that captures input.
const MAIN_ID = 1
const HEAD_ID = 2
const MAP_ID = 3

// Two layouts on the 576×288 canvas:
//   text: one full-screen text container.
//   map:  headline top-left, 288×144 map top-right (the max image size), instructions along the bottom.
type Layout = 'text' | 'map'
const LIMITS = {
  text: { mainLines: 9, mainChars: 44 },
  map: { headLines: 5, headChars: 24, mainLines: 4, mainChars: 44 },
}

const bridge = await waitForEvenAppBridge()

let summary: Summary | null = null
let lastOkAt = 0
let layout: Layout = 'text'
let shown: Record<number, string> = {}
let lastDisplayedId = 'startup'
let lastSdkRefresh = 0
let fetching = false
const DISPLAY_URL = new URL('/g2/display', SUMMARY_URL).href
const REPORT_TOKEN = import.meta.env.VITE_G2_REPORT_TOKEN
async function reportDisplay(alertId: string, text: string, state: 'sdk_accepted' | 'failed' | 'cleared') {
  if (!REPORT_TOKEN) return
  try {
    const response = await fetch(DISPLAY_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${REPORT_TOKEN}` },
      body: JSON.stringify({ alert_id: alertId, rendered_text: text, status: state }),
      signal: AbortSignal.timeout(3000),
    })
    if (!response.ok) console.warn('Display report rejected:', response.status)
  } catch { console.warn('Display report unavailable') }
}
// From each location report: nearest mapped hazards, a GPS-built alert, and a real map around the wearer.
let nearby: Nearby[] = []
let nearbyAt = 0
let gpsSummary: Summary | null = null
let gpsMapUrl: string | null = null
const telemetry = startTelemetry(bridge)
// Fall check, man-down and SOS. Status changes are reported straight away.
const safety = createSafety({
  fallG: Number(import.meta.env.VITE_FALL_G ?? 3),
  settleMs: 5000,
  stillSpreadG: 0.05,
  confirmMs: 20000,
  onChange: (next) => { telemetry.setStatus(next); reports.sendNow(); refresh() },
})
let hazardIndex = 0
const reports = startLocationReports(bridge, new URL('/wearer', SUMMARY_URL).href, REPORT_TOKEN, telemetry.collect, (reply) => {
  nearby = reply.nearby
  nearbyAt = Date.now()
  gpsSummary = reply.situation ? parseSummary(reply.situation) : null
  gpsMapUrl = reply.map_url ?? null
})
const gpsFresh = () => Date.now() - nearbyAt < 20000
// Drone-frame alerts win; otherwise show the alert built from GPS.
function activeSummary(): Summary | null { return summary ?? (gpsFresh() ? gpsSummary : null) }
// The real GPS map wins over the placeholder frame map.
function activeMapUrl(): string | null { return (gpsFresh() && gpsMapUrl) || activeSummary()?.mapUrl || null }
let mapShown: string | null = null
let mapBusy = false

// Voice report state.
let recording = false
let recordStartedAt = 0
let chunks: Uint8Array[] = []
let status = '' // transient line like "Report sent", shown at the top
let statusTimer: ReturnType<typeof setTimeout> | undefined

function setStatus(text: string, clearAfterMs?: number) {
  status = text
  clearTimeout(statusTimer)
  if (clearAfterMs) statusTimer = setTimeout(() => setStatus(''), clearAfterMs)
  refresh()
}

function clip(line: string, max: number): string {
  return line.length > max ? line.slice(0, max - 1) + '…' : line
}

// Greedy word wrap for the narrow headline column.
function wrap(text: string, max: number): string[] {
  const lines: string[] = []
  let line = ''
  for (const word of text.split(/\s+/)) {
    if (line && (line + ' ' + word).length > max) {
      lines.push(line)
      line = word
    } else {
      line = line ? line + ' ' + word : word
    }
  }
  if (line) lines.push(line)
  return lines
}

function topLines(): string[] {
  const lines: string[] = []
  const alarm = safety.line()
  if (alarm) lines.push(alarm)
  if (recording) {
    const secs = Math.floor((Date.now() - recordStartedAt) / 1000)
    lines.push(`● REC 0:${String(secs).padStart(2, '0')}`)
  } else if (status) {
    lines.push(status)
  }

  const age = lastOkAt ? Date.now() - lastOkAt : Infinity
  if (age > STALE_MS) {
    // Round to 5s so we don't redraw the glasses every second.
    lines.push(lastOkAt ? `NO SIGNAL - last update ${Math.floor(age / 5000) * 5}s ago` : 'Connecting to command...')
  } else if (!activeSummary()) {
    lines.push('Waiting for first update...')
  }
  return lines
}

function headerLine(s: Summary): string {
  const time = new Date(s.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const tag = s.priority === 'critical' ? '!! CRITICAL' : s.priority === 'warning' ? '! WARNING' : 'INFO'
  return `${tag}   ${time}`
}

// Text for each container in the current layout.
function render(): Record<number, string> {
  const top = topLines()
  const current = activeSummary()
  // The GPS alert already leads with the nearest hazard; add it as a line only above drone alerts.
  const hazard = summary && gpsFresh() ? hazardLine(nearby) : ''
  const steps = [...(hazard ? [`>> ${hazard}`] : []), ...(current ? current.instructions.map((s) => `- ${s}`) : [])]

  if (layout === 'text') {
    const { mainLines, mainChars } = LIMITS.text
    const lines = current ? [...top, headerLine(current), current.headline.toUpperCase(), '', ...steps] : [...top, ...steps]
    return { [MAIN_ID]: lines.slice(0, mainLines).map((l) => clip(l, mainChars)).join('\n') }
  }

  const { headLines, headChars, mainLines, mainChars } = LIMITS.map
  const head = [
    ...top.flatMap((l) => wrap(l, headChars)),
    ...(current ? [headerLine(current), ...wrap(current.headline.toUpperCase(), headChars)] : []),
  ]
  return {
    [HEAD_ID]: head.slice(0, headLines).map((l) => clip(l, headChars)).join('\n'),
    [MAIN_ID]: steps.slice(0, mainLines).map((l) => clip(l, mainChars)).join('\n') || ' ',
  }
}

function textContainer(id: number, name: string, x: number, y: number, w: number, h: number, content: string) {
  return new TextContainerProperty({
    xPosition: x,
    yPosition: y,
    width: w,
    height: h,
    borderWidth: 0,
    borderColor: 5,
    paddingLength: 4,
    containerID: id,
    containerName: name,
    content,
    isEventCapture: id === MAIN_ID ? 1 : 0,
  })
}

function page(content: Record<number, string>) {
  if (layout === 'text') {
    return { containerTotalNum: 1, textObject: [textContainer(MAIN_ID, 'main', 0, 0, 576, 288, content[MAIN_ID])] }
  }
  return {
    containerTotalNum: 3,
    textObject: [
      textContainer(HEAD_ID, 'head', 0, 0, 288, 144, content[HEAD_ID]),
      textContainer(MAIN_ID, 'main', 0, 144, 576, 144, content[MAIN_ID]),
    ],
    imageObject: [
      new ImageContainerProperty({ xPosition: 288, yPosition: 0, width: 288, height: 144, containerID: MAP_ID, containerName: 'map' }),
    ],
  }
}

const NAMES: Record<number, string> = { [MAIN_ID]: 'main', [HEAD_ID]: 'head' }

shown = render()
const result = await bridge.createStartUpPageContainer(new CreateStartUpPageContainer(page(shown)))
if (result !== 0) {
  // The startup page can only be created once per session. After a Vite
  // reload it already exists, so rebuild it instead.
  const rebuilt = await bridge.rebuildPageContainer(new RebuildPageContainer(page(shown)))
  if (!rebuilt) console.error('createStartUpPageContainer failed:', result)
}
// The IMU (like the microphone) needs the startup page to exist first.
telemetry.enableImu()

let refreshing = false

// Push changes to the glasses: rebuild if the layout changed, otherwise only update text that changed.
async function refresh() {
  if (refreshing) return
  refreshing = true
  if (summary && (!Number.isFinite(Date.parse(summary.timestamp)) || Date.now() - Date.parse(summary.timestamp) > STALE_MS)) summary = null
  const captured = activeSummary()
  const alertId = captured?.id ?? lastDisplayedId
  const previousLayout = layout
  let text = ''
  try {
    const wanted: Layout = activeMapUrl() ? 'map' : 'text'
    layout = wanted
    const next = render()
    text = (wanted === 'map' ? [next[HEAD_ID], next[MAIN_ID]] : [next[MAIN_ID]]).join('\n')
    const heartbeat = Date.now() - lastSdkRefresh > 5000
    let updated = false
    if (wanted !== previousLayout) {
      const ok = await bridge.rebuildPageContainer(new RebuildPageContainer(page(next)))
      if (!ok) throw new Error('G2 rebuild rejected')
      shown = next
      mapShown = null
      updated = true
    } else {
      for (const [id, content] of Object.entries(next)) {
        if (!heartbeat && shown[+id] === content) continue
        const ok = await bridge.textContainerUpgrade(new TextContainerUpgrade({containerID: +id, containerName: NAMES[+id], content}))
        if (!ok) throw new Error('G2 text update rejected')
        shown[+id] = content
        updated = true
      }
    }
    if (updated) {
      lastSdkRefresh = Date.now()
      lastDisplayedId = alertId
      await reportDisplay(alertId, text, captured ? 'sdk_accepted' : 'cleared')
    }
  } catch (error) {
    layout = previousLayout
    shown = {} // Retry all containers rather than suppressing a failed update.
    console.warn('Glasses update failed:', error)
    await reportDisplay(alertId, text, 'failed')
  } finally { refreshing = false }
  pushMap()
}

// Send the map image only when its URL changes. Images are slow over Bluetooth, so never overlap sends.
async function pushMap() {
  const mapUrl = activeMapUrl()
  if (layout !== 'map' || !mapUrl || mapBusy) return
  const url = new URL(mapUrl, SUMMARY_URL).href
  if (url === mapShown) return

  mapBusy = true
  try {
    const res = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(5000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const bytes = new Uint8Array(await res.arrayBuffer())
    const r = await bridge.updateImageRawData(new ImageRawDataUpdate({ containerID: MAP_ID, containerName: 'map', imageData: bytes }))
    if (r === ImageRawDataUpdateResult.success) mapShown = url
    else console.warn('Map update failed:', r)
  } catch (err) {
    console.warn('Map fetch error:', err)
  } finally {
    mapBusy = false
  }
}

async function fetchLatest() {
  if (fetching) return
  fetching = true
  try {
    const res = await fetch(SUMMARY_URL, { cache: 'no-store', signal: AbortSignal.timeout(3000) })
    if (res.status === 204) {
      summary = null
      lastOkAt = Date.now()
    } else if (res.ok) {
      const next = parseSummary(await res.json())
      lastOkAt = Date.now()
      if (next && Date.now() - Date.parse(next.timestamp) <= STALE_MS && Date.parse(next.timestamp) <= Date.now() + 5000) summary = next
      else summary = null

    } else {
      console.warn('Summary fetch failed:', res.status)
    }
  } catch (err) {
    console.warn('Summary fetch error:', err)
  } finally { fetching = false }
  await refresh()
}

async function pollLoop() {
  await fetchLatest()
  setTimeout(pollLoop, POLL_MS)
}

pollLoop()
// Keeps the "NO SIGNAL" age and recording timer current.
setInterval(() => {
  safety.tick()
  if (recording && Date.now() - recordStartedAt > MAX_RECORD_SECONDS * 1000) stopRecording()
  refresh()
}, 1000)

async function startRecording() {
  if (recording) return
  chunks = []
  recording = true
  recordStartedAt = Date.now()
  refresh()
  const ok = await bridge.audioControl(true, AudioInputSource.Glasses)
  if (!ok) {
    recording = false
    setStatus('Mic unavailable', 4000)
  }
}

async function stopRecording() {
  if (!recording) return
  recording = false
  await bridge.audioControl(false)

  if (pcmSeconds(chunks) < 0.5) {
    setStatus('Too short - hold to record', 3000)
    return
  }

  setStatus('Sending report...')
  try {
    const res = await fetch(REPORT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav' },
      body: pcmToWav(chunks),
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    setStatus('Report sent', 4000)
  } catch (err) {
    console.warn('Report upload failed:', err)
    setStatus('Report FAILED - hold to retry', 6000)
  }
  chunks = []
}

bridge.onEvenHubEvent((event) => {
  if (event.audioEvent) {
    if (recording) chunks.push(event.audioEvent.audioPcm)
    return
  }

  const sys = event.sysEvent
  if (sys?.eventType === OsEventTypeList.IMU_DATA_REPORT) {
    if (sys.imuData) {
      const { x = 0, y = 0, z = 0 } = sys.imuData
      telemetry.imu(x, y, z)
      safety.imu(x, y, z)
    }
    return
  }

  // Taps arrive as sysEvent (source-aware) or textEvent depending on host version.
  const input = event.textEvent ?? event.sysEvent
  if (!input) return
  const INPUTS: Partial<Record<number, InputType>> = {
    [OsEventTypeList.CLICK_EVENT]: 'click', [OsEventTypeList.DOUBLE_CLICK_EVENT]: 'double_click',
    [OsEventTypeList.SCROLL_TOP_EVENT]: 'scroll_up', [OsEventTypeList.SCROLL_BOTTOM_EVENT]: 'scroll_down',
    [OsEventTypeList.LONG_PRESS_EVENT]: 'long_press', [OsEventTypeList.LONG_PRESS_RELEASE_EVENT]: 'long_press_release',
  }
  const pressed = INPUTS[input.eventType ?? OsEventTypeList.CLICK_EVENT]
  if (pressed) telemetry.input(pressed, sys?.eventSource)

  switch (input.eventType) {
    case OsEventTypeList.CLICK_EVENT:
    case undefined: // SDK normalizes 0 to undefined in some cases
      if (recording) break
      if (safety.tap()) {
        setStatus('OK sent to command', 3000)
      } else {
        // Acknowledge the alert on screen, and fetch immediately.
        const current = activeSummary()
        if (current) {
          telemetry.ack(current.id)
          reports.sendNow()
          setStatus('Acknowledged', 3000)
        }
        fetchLatest()
      }
      break

    case OsEventTypeList.SCROLL_TOP_EVENT:
    case OsEventTypeList.SCROLL_BOTTOM_EVENT:
      // Step through nearby mapped hazards.
      if (nearby.length) {
        hazardIndex = (hazardIndex + (input.eventType === OsEventTypeList.SCROLL_TOP_EVENT ? nearby.length - 1 : 1)) % nearby.length
        setStatus(`${hazardIndex + 1}/${nearby.length} ${hazardLine([nearby[hazardIndex]])}`, 5000)
      }
      break

    case OsEventTypeList.LONG_PRESS_EVENT:
      // Hold for SOS, or to record a voice report when voice reports are enabled.
      if (import.meta.env.VITE_ENABLE_VOICE_REPORTS === 'true') startRecording()
      else safety.sos()
      break

    case OsEventTypeList.LONG_PRESS_RELEASE_EVENT:
      stopRecording()
      break

    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      // Mode 1 shows the system exit-confirmation dialog (required on the root page).
      if (recording) stopRecording()
      bridge.shutDownPageContainer(1)
      break
  }
})
