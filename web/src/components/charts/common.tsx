import type { ReactNode } from 'react'

interface TipRow {
  color?: string
  name: ReactNode
  value: ReactNode
}

export function TooltipCard({ title, rows, footer }: { title?: ReactNode; rows: TipRow[]; footer?: ReactNode }) {
  return (
    <div className="min-w-[160px] rounded-xl bg-card px-3 py-2.5 text-[12.5px] shadow-xl ring-1 ring-line-strong">
      {title && <div className="mb-1.5 font-medium text-ink">{title}</div>}
      <div className="flex flex-col gap-1">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2">
            {r.color && <span className="size-2.5 shrink-0 rounded-full" style={{ background: r.color }} />}
            <span className="text-ink-2">{r.name}</span>
            <span className="num ml-auto pl-4 font-medium text-ink">{r.value}</span>
          </div>
        ))}
      </div>
      {footer && <div className="mt-1.5 border-t border-line pt-1.5 text-[11.5px] text-muted">{footer}</div>}
    </div>
  )
}

/** Small dependency-free sparkline: thin line, end dot, optional baseline. */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  color = 'var(--s1)',
  baseline,
}: {
  values: (number | null)[]
  width?: number
  height?: number
  color?: string
  baseline?: number
}) {
  const v = values.map((x) => x ?? 0)
  if (!v.length) return null
  const lo = Math.min(...v, baseline ?? Infinity)
  const hi = Math.max(...v, baseline ?? -Infinity)
  const span = hi - lo || 1
  const pad = 3
  const x = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(1, v.length - 1)
  const y = (val: number) => height - pad - ((val - lo) / span) * (height - 2 * pad)
  const d = v.map((val, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join('')
  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      {baseline != null && (
        <line x1={pad} x2={width - pad} y1={y(baseline)} y2={y(baseline)} stroke="var(--grid)" strokeWidth={1} />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
      <circle
        cx={x(v.length - 1)}
        cy={y(v[v.length - 1])}
        r={2.75}
        fill={color}
        stroke="var(--card)"
        strokeWidth={1.5}
      />
    </svg>
  )
}

export function Legend({ items }: { items: { label: ReactNode; color: string; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
          <svg width="16" height="8" aria-hidden>
            <line
              x1="1"
              x2="15"
              y1="4"
              y2="4"
              stroke={it.color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeDasharray={it.dashed ? '3 3' : undefined}
            />
          </svg>
          {it.label}
        </span>
      ))}
    </div>
  )
}
