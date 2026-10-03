// Sequential single-hue ramps (low -> high) for heatmap cells, one per theme, with the
// cell text colour picked by the fill's lightness so labels always clear contrast.
const RAMP = {
  dark: ['#141a17', '#18261b', '#1d351f', '#264a22', '#356425', '#4f8326', '#77a92a', '#a9d43c'],
  light: ['#f0f4ea', '#dceac9', '#c4dda4', '#a6cb78', '#82b44f', '#5f972c', '#437a16', '#2f5e0b'],
}
const DARK_TEXT_FROM = { dark: 6, light: 99 } // dark mode: bright cells take dark text
const LIGHT_TEXT_FROM = { dark: -1, light: 4 } // light mode: deep cells take white text

export function seqColor(t: number, theme: 'dark' | 'light'): { bg: string; fg: string } {
  const ramp = RAMP[theme]
  const i = Math.max(0, Math.min(ramp.length - 1, Math.round(t * (ramp.length - 1))))
  let fg = theme === 'dark' ? '#eef2ef' : '#0b0e0c'
  if (theme === 'dark' && i >= DARK_TEXT_FROM.dark) fg = '#0b0f05'
  if (theme === 'light' && i >= LIGHT_TEXT_FROM.light) fg = '#ffffff'
  return { bg: ramp[i], fg }
}

export function rampStops(theme: 'dark' | 'light'): string[] {
  return RAMP[theme]
}
