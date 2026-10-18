import { AppLocationAccuracy, type EvenAppBridge, type AppLocation } from '@evenrealities/even_hub_sdk'

// Phone GPS -> backend POST /wearer every few seconds; the reply lists the nearest mapped hazards.

export interface Nearby {
  label: string
  severity: string
  distance_m: number
  compass: string
  approx: boolean
}

const SEND_MS = 5000
// Development only: "lat,lon" used when the SDK gives no fix (the simulator has no GPS).
const TEST_LOCATION = import.meta.env.VITE_TEST_LOCATION as string | undefined

export function startLocationReports(
  bridge: EvenAppBridge,
  wearerUrl: string,
  token: string | undefined,
  onNearby: (nearby: Nearby[]) => void,
) {
  let fix: AppLocation | null = null
  let sending = false

  bridge.onAppLocationChanged((location) => { fix = location })
  bridge.startAppLocationUpdates({ accuracy: AppLocationAccuracy.High, intervalMs: SEND_MS, distanceFilter: 3 })
    .then((ok) => { if (!ok) console.warn('Location updates unavailable; polling instead') })
    .catch(() => console.warn('Location updates unavailable; polling instead'))

  async function currentFix(): Promise<AppLocation | null> {
    if (fix && Date.now() - (fix.timestamp ?? Date.now()) < 30000) return fix
    try {
      const polled = await bridge.getAppLocation({ accuracy: AppLocationAccuracy.High, timeoutMs: 4000 })
      if (polled) return (fix = polled)
    } catch { /* fall through to the test location */ }
    if (TEST_LOCATION) {
      const [latitude, longitude] = TEST_LOCATION.split(',').map(Number)
      if (Number.isFinite(latitude) && Number.isFinite(longitude)) return { latitude, longitude, accuracy: 0 }
    }
    return null
  }

  async function send() {
    if (sending || !token) return
    sending = true
    try {
      const here = await currentFix()
      if (!here) return
      const body: Record<string, number | string> = { lat: here.latitude, lon: here.longitude }
      if (import.meta.env.VITE_DEVICE_ID) body.device_id = import.meta.env.VITE_DEVICE_ID
      if (here.accuracy != null) body.accuracy_m = here.accuracy
      if (here.heading != null && here.heading >= 0) body.heading_deg = here.heading
      if (here.speed != null && here.speed >= 0) body.speed_mps = here.speed
      const response = await fetch(wearerUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(4000),
      })
      if (!response.ok) return console.warn('Location report rejected:', response.status)
      const data = await response.json()
      if (Array.isArray(data.nearby)) onNearby(data.nearby)
    } catch {
      console.warn('Location report unavailable')
    } finally {
      sending = false
    }
  }

  send()
  setInterval(send, SEND_MS)
}

// "Fire front: ~180 m NE", or "" if nothing is mapped near the wearer.
export function hazardLine(nearby: Nearby[]): string {
  const nearest = nearby[0]
  if (!nearest) return ''
  const meters = nearest.distance_m
  const distance = meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`
  return `${nearest.label}: ${nearest.approx ? '~' : ''}${distance} ${nearest.compass}`
}
