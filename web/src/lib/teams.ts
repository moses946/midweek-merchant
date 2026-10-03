// Club colours for the generic shirt icon (primary body, secondary sleeves/trim).
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
