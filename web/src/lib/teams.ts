// Club colours for the fallback shirt icon (primary body, secondary sleeves/trim).
const COLORS: Record<string, [string, string]> = {
  ARS: ['#e2231a', '#ffffff'],
  AVL: ['#7a1e45', '#95bfe5'],
  BOU: ['#d71920', '#111111'],
  BRE: ['#e30613', '#ffffff'],
  BHA: ['#0057b8', '#ffffff'],
  BUR: ['#6c1d45', '#99d6ea'],
  CHE: ['#034694', '#ffffff'],
  COV: ['#6cabdd', '#ffffff'],
  CRY: ['#1b458f', '#c4122e'],
  EVE: ['#003399', '#ffffff'],
  FUL: ['#f4f4f4', '#111111'],
  HUL: ['#f5a12d', '#111111'],
  IPS: ['#3a64a3', '#ffffff'],
  LEE: ['#f4f4f4', '#1d428a'],
  LEI: ['#003090', '#fdbe11'],
  LIV: ['#c8102e', '#f6eb61'],
  MCI: ['#6cabdd', '#ffffff'],
  MUN: ['#da291c', '#111111'],
  NEW: ['#241f20', '#f4f4f4'],
  NFO: ['#dd0000', '#ffffff'],
  SOU: ['#d71920', '#ffffff'],
  SUN: ['#eb172b', '#ffffff'],
  TOT: ['#f4f4f4', '#132257'],
  WHU: ['#7a263a', '#1bb1e7'],
  WOL: ['#fdb913', '#231f20'],
}

// Hindcast picks carry full club names; map them to the same codes.
const ALIASES: Record<string, string> = {
  Arsenal: 'ARS',
  'Aston Villa': 'AVL',
  Bournemouth: 'BOU',
  Brentford: 'BRE',
  Brighton: 'BHA',
  Burnley: 'BUR',
  Chelsea: 'CHE',
  Coventry: 'COV',
  'Crystal Palace': 'CRY',
  Everton: 'EVE',
  Fulham: 'FUL',
  Hull: 'HUL',
  Ipswich: 'IPS',
  Leeds: 'LEE',
  Leicester: 'LEI',
  Liverpool: 'LIV',
  'Man City': 'MCI',
  'Man United': 'MUN',
  'Man Utd': 'MUN',
  Newcastle: 'NEW',
  "Nott'm Forest": 'NFO',
  Southampton: 'SOU',
  Sunderland: 'SUN',
  Tottenham: 'TOT',
  Spurs: 'TOT',
  'West Ham': 'WHU',
  Wolves: 'WOL',
}

export function teamCode(team: string): string {
  return ALIASES[team] ?? team
}

export function teamColors(team: string): [string, string] {
  return COLORS[teamCode(team)] ?? ['#5d6670', '#c9ced3']
}

// FPL team codes (stable across seasons) locate the official kit images. The bundle's
// meta.json supplies codes for the current season, covering newly promoted clubs.
const CODES: Record<string, number> = {
  ARS: 3,
  AVL: 7,
  BOU: 91,
  BRE: 94,
  BHA: 36,
  BUR: 90,
  CHE: 8,
  COV: 9,
  CRY: 31,
  EVE: 11,
  FUL: 54,
  HUL: 88,
  IPS: 40,
  LEE: 2,
  LEI: 13,
  LIV: 14,
  MCI: 43,
  MUN: 1,
  NEW: 4,
  NFO: 17,
  SOU: 20,
  SUN: 56,
  TOT: 6,
  WHU: 21,
  WOL: 39,
}

export function registerTeams(rows: { short: string; name: string; code?: number | null }[]) {
  for (const r of rows) {
    if (r.code) CODES[r.short] = r.code
    ALIASES[r.name] ??= r.short
  }
}

const KITS_URL = (
  import.meta.env.VITE_KITS_URL ?? 'https://fantasy.premierleague.com/dist/img/shirts/standard'
).replace(/\/$/, '')

/** Official FPL kit image for a club (goalkeepers wear the `_1` kit), or null when unknown. */
export function kitUrl(team: string, goalkeeper = false): string | null {
  const code = CODES[teamCode(team)]
  return code ? `${KITS_URL}/shirt_${code}${goalkeeper ? '_1' : ''}-110.webp` : null
}
