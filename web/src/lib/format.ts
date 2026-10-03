import type { Chip, Position } from './types'

export const CHIP_NAMES: Record<Chip, string> = {
  wildcard: 'Wildcard',
  freehit: 'Free Hit',
  bboost: 'Bench Boost',
  '3xc': 'Triple Captain',
}

export const CHIP_SHORT: Record<Chip, string> = { wildcard: 'WC', freehit: 'FH', bboost: 'BB', '3xc': 'TC' }

export const POSITIONS: Position[] = ['GKP', 'DEF', 'MID', 'FWD']

export const fmt = {
  pts: (v: number | null | undefined, d = 1) => (v == null ? '–' : v.toFixed(d)),
  price: (v: number | null | undefined) => (v == null ? '–' : `£${v.toFixed(1)}m`),
  pct: (v: number | null | undefined, d = 0) => (v == null ? '–' : `${(v * 100).toFixed(d)}%`),
  pctSmart: (v: number | null | undefined) => {
    if (v == null) return '–'
    const p = v * 100
    if (p > 0 && p < 1) return `${p.toFixed(1)}%`
    return `${p.toFixed(0)}%`
  },
  signed: (v: number | null | undefined, d = 1) =>
    v == null ? '–' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v).toFixed(d)}`,
  int: (v: number | null | undefined) => (v == null ? '–' : Math.round(v).toLocaleString('en-GB')),
  compact: (v: number | null | undefined) =>
    v == null ? '–' : Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 }).format(v),
  ordinal: (n: number) => {
    const s = ['th', 'st', 'nd', 'rd']
    const v = n % 100
    return n + (s[(v - 20) % 10] || s[v] || s[0])
  },
}

export function relativeTime(iso: string, now = Date.now()): string {
  const diff = (now - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`
  return `${Math.floor(diff / 86400)} d ago`
}

export function shortDate(iso: string): string {
  return (
    new Date(iso).toLocaleString('en-GB', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'UTC',
    }) + ' UTC'
  )
}

/** Split "TOT(H)" / "LEE(A)" / "ARS(H)+CHE(A)" into opponents with venue. */
export function parseFixture(s: string): { opp: string; home: boolean }[] {
  if (!s || s === '—') return []
  return s.split(/\s*\+\s*|,\s*/).flatMap((part) => {
    const m = part.match(/^([A-Za-z' ]+)\((H|A)\)$/)
    return m ? [{ opp: m[1], home: m[2] === 'H' }] : []
  })
}
