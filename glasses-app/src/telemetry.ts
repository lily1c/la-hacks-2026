import { ImuReportPace, type DeviceStatus, type EvenAppBridge } from '@evenrealities/even_hub_sdk'

// Glasses telemetry sent with each location report: IMU samples, button presses and device status.

const MAX_SAMPLES = 60  // ~6 s at 10 Hz; reports go out every 5 s
const MAX_INPUTS = 20
const SOURCES: Record<number, string> = { 1: 'right', 2: 'ring', 3: 'left' }

export type InputType = 'click' | 'double_click' | 'scroll_up' | 'scroll_down' | 'long_press' | 'long_press_release'

export function startTelemetry(bridge: EvenAppBridge) {
  const imu: number[][] = []  // [unix ms, x, y, z]
  const inputs: { type: InputType; source: string; t: number }[] = []
  let device: Record<string, boolean | number> | null = null

  // P100 = report every 100 ms.
  bridge.imuControl(true, ImuReportPace.P100)
    .then((ok) => { if (!ok) console.warn('IMU unavailable') })
    .catch(() => console.warn('IMU unavailable'))

  function setDevice(status?: DeviceStatus | null) {
    if (!status) return
    const next: Record<string, boolean | number> = {}
    if (status.isWearing != null) next.worn = status.isWearing
    if (status.batteryLevel != null) next.battery = status.batteryLevel
    if (status.isCharging != null) next.charging = status.isCharging
    if (status.isInCase != null) next.in_case = status.isInCase
    device = next
  }
  bridge.getDeviceInfo().then((info) => setDevice(info?.status)).catch(() => {})
  bridge.onDeviceStatusChanged(setDevice)

  return {
    imu(x: number, y: number, z: number) {
      imu.push([Date.now(), x, y, z])
      if (imu.length > MAX_SAMPLES) imu.shift()
    },
    input(type: InputType, source?: number) {
      inputs.push({ type, source: SOURCES[source ?? 0] ?? 'unknown', t: Date.now() })
      if (inputs.length > MAX_INPUTS) inputs.shift()
    },
    // Everything gathered since the last report; buffers are emptied.
    collect() {
      const body: Record<string, unknown> = {}
      if (imu.length) body.imu = imu.splice(0)
      if (inputs.length) body.inputs = inputs.splice(0)
      if (device) body.device = device
      return body
    },
  }
}
