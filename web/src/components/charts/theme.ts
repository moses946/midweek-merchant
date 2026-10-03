// Recharts takes colours as strings; CSS variables keep both themes in one place.
export const axis = {
  stroke: 'var(--axis)',
  tick: { fill: 'var(--muted)', fontSize: 11.5, fontFamily: 'var(--font-sans)' },
  tickLine: false,
  axisLine: { stroke: 'var(--axis)' },
} as const

export const grid = { stroke: 'var(--grid)', strokeDasharray: '0', vertical: false } as const
