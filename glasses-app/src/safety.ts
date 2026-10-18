// Wearer safety state on the glasses: fall check, man-down and SOS.
//
// A hard impact followed by stillness asks "Are you OK?"; no tap within the
// countdown becomes MAN DOWN. A long press raises SOS. A tap clears any of them.

export type SafetyStatus = 'ok' | 'check' | 'man_down' | 'sos'

export interface SafetyOptions {
  fallG: number          // impact above this many g starts a check (taking glasses off peaked at 2.5 g)
  settleMs: number       // wait this long after the impact before judging stillness
  stillSpreadG: number   // |acceleration| spread below this over the last 3 s counts as still
  confirmMs: number      // time to tap "I'm OK" before MAN DOWN
  onChange: (status: SafetyStatus) => void
  now?: () => number
}

export function createSafety(options: SafetyOptions) {
  const now = options.now ?? Date.now
  let status: SafetyStatus = 'ok'
  let impactAt = 0
  let checkUntil = 0
  const recent: [number, number][] = []  // [ms, |acceleration| in g], last 5 s

  function set(next: SafetyStatus) {
    if (next === status) return
    status = next
    options.onChange(status)
  }

  function stillLately(): boolean {
    const window = recent.filter(([t]) => now() - t <= 3000).map(([, m]) => m)
    if (window.length < 10) return false
    const mean = window.reduce((a, b) => a + b, 0) / window.length
    return Math.sqrt(window.reduce((a, m) => a + (m - mean) ** 2, 0) / window.length) < options.stillSpreadG
  }

  return {
    get status() { return status },

    imu(x: number, y: number, z: number) {
      const magnitude = Math.sqrt(x * x + y * y + z * z)
      recent.push([now(), magnitude])
      while (recent.length && now() - recent[0][0] > 5000) recent.shift()
      if (status === 'ok' && !impactAt && magnitude > options.fallG) impactAt = now()
    },

    // Call about once a second.
    tick() {
      if (impactAt && now() - impactAt >= options.settleMs) {
        if (status === 'ok' && stillLately()) {
          checkUntil = now() + options.confirmMs
          set('check')
        }
        impactAt = 0
      }
      if (status === 'check' && now() >= checkUntil) set('man_down')
    },

    sos() { set('sos') },

    // A tap clears a check, man-down or SOS. Returns true if it did.
    tap(): boolean {
      if (status === 'ok') return false
      impactAt = 0
      set('ok')
      return true
    },

    // Top line for the glasses, or '' when all is well.
    line(): string {
      if (status === 'check') return `ARE YOU OK? TAP TO CONFIRM (${Math.max(0, Math.ceil((checkUntil - now()) / 1000))}s)`
      if (status === 'man_down') return 'MAN DOWN SENT - tap if you are OK'
      if (status === 'sos') return 'SOS SENT - tap to cancel'
      return ''
    },
  }
}
