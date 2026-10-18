// The JSON the backend serves at SUMMARY_URL. See SUMMARY_FORMAT.md.
export type Priority = 'critical' | 'warning' | 'info'

export interface Summary {
  id: string            // changes whenever there is a new summary
  timestamp: string     // ISO 8601, when the summary was generated
  priority: Priority
  headline: string      // one short line, shown first
  instructions: string[] // a few short lines, most important first
  mapUrl?: string       // optional 288×144 image; change the URL to push a new map
}

const PRIORITIES: Priority[] = ['critical', 'warning', 'info']

// Validate untrusted JSON from the network. Returns null if it isn't usable.
export function parseSummary(raw: unknown): Summary | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  if (typeof r.headline !== 'string' || r.headline.trim() === '') return null

  const timestamp = typeof r.timestamp === 'string' ? r.timestamp : new Date().toISOString()
  return {
    id: typeof r.id === 'string' || typeof r.id === 'number' ? String(r.id) : `${timestamp}|${r.headline}`,
    timestamp,
    priority: PRIORITIES.includes(r.priority as Priority) ? (r.priority as Priority) : 'info',
    headline: r.headline.trim(),
    instructions: Array.isArray(r.instructions)
      ? r.instructions.filter((s): s is string => typeof s === 'string' && s.trim() !== '').map((s) => s.trim())
      : [],
    mapUrl: typeof r.map_url === 'string' && r.map_url !== '' ? r.map_url : undefined,
  }
}
