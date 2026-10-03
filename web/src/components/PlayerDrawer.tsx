import { X } from 'lucide-react'
import { useEffect } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt } from '../lib/format'
import type { Meta, Player } from '../lib/types'
import { TooltipCard } from './charts/common'
import { axis, grid } from './charts/theme'
import { Badge, Jersey, PosTag } from './ui/primitives'

const PARTS: { key: keyof Player['next']['breakdown']; label: string }[] = [
  { key: 'app', label: 'Appearance' },
  { key: 'goals', label: 'Goals' },
  { key: 'assists', label: 'Assists' },
  { key: 'cs', label: 'Clean sheet' },
  { key: 'saves', label: 'Saves' },
  { key: 'dc', label: 'Defensive contributions' },
  { key: 'bonus', label: 'Bonus' },
  { key: 'gc', label: 'Goals conceded' },
  { key: 'cards', label: 'Cards' },
]

export function PlayerDrawer({ player, meta, onClose }: { player: Player | null; meta: Meta; onClose: () => void }) {
  useEffect(() => {
    if (!player) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [player, onClose])
  if (!player) return null
  const p = player
  const data = meta.gws.map((g, k) => ({ gw: `GW${g}`, xp: p.xp[k] ?? 0, fx: p.fx[k] || 'blank', xmins: p.xmins[k] }))
  const parts = PARTS.map((x) => ({ ...x, v: p.next.breakdown[x.key] ?? 0 })).filter((x) => Math.abs(x.v) >= 0.01)
  const maxAbs = Math.max(...parts.map((x) => Math.abs(x.v)), 0.5)
  const total8 = p.xp.reduce<number>((s, v) => s + (v ?? 0), 0)

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={p.full}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <aside className="rise absolute inset-y-0 right-0 flex w-full max-w-[520px] flex-col overflow-y-auto border-l border-line bg-bg-elev">
        <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-line bg-bg-elev/90 p-5 backdrop-blur-xl">
          <Jersey team={p.team} pos={p.pos} size={64} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-[20px] font-semibold tracking-tight text-ink">{p.name}</h2>
              <PosTag pos={p.pos} />
            </div>
            <div className="truncate text-[13px] text-ink-2">
              {p.full} · {meta.teams.find((t) => t.short === p.team)?.name ?? p.team}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge>{fmt.price(p.price)}</Badge>
              <Badge>{p.own ?? '–'}% owned</Badge>
              <Badge>{p.pts} pts this season</Badge>
              {p.status !== 'a' && <Badge tone="warn">{p.chance ?? 0}% to play</Badge>}
            </div>
          </div>
          <button
            onClick={onClose}
            className="grid size-9 place-items-center rounded-xl text-ink-2 ring-1 ring-line hover:text-ink"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-col gap-6 p-5">
          {p.news && <div className="rounded-xl bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn">{p.news}</div>}

          <div className="grid grid-cols-3 gap-2">
            <Kpi label={`GW${meta.gws[0]} xPts`} value={fmt.pts(p.xp[0], 2)} />
            <Kpi label={`${meta.gws.length}-GW total`} value={total8.toFixed(1)} />
            <Kpi label="FPL's own ep" value={fmt.pts(p.ep)} />
            <Kpi label="Chance to start" value={fmt.pct(p.next.p_start)} />
            <Kpi label="Expected goals" value={fmt.pts(p.next.xg, 2)} />
            <Kpi label="Expected assists" value={fmt.pts(p.next.xa, 2)} />
          </div>

          <section>
            <h3 className="mb-1 text-[14px] font-semibold text-ink">Expected points by gameweek</h3>
            <p className="mb-3 text-[12.5px] text-muted">Double gameweeks sum both fixtures; blanks score zero.</p>
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ top: 16, right: 4, left: -20, bottom: 0 }}>
                  <CartesianGrid {...grid} />
                  <XAxis
                    dataKey="gw"
                    {...axis}
                    interval={0}
                    height={36}
                    tick={({ x, y, payload, index }) => (
                      <g transform={`translate(${x},${y})`}>
                        <text dy={12} textAnchor="middle" fill="var(--muted)" fontSize={11}>
                          {payload.value}
                        </text>
                        <text dy={26} textAnchor="middle" fill="var(--ink-2)" fontSize={10}>
                          {data[index]?.fx}
                        </text>
                      </g>
                    )}
                  />
                  <YAxis {...axis} axisLine={false} width={40} />
                  <Tooltip
                    cursor={{ fill: 'var(--card-2)' }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <TooltipCard
                          title={`${payload[0].payload.gw} · ${payload[0].payload.fx}`}
                          rows={[
                            { name: 'Expected points', value: Number(payload[0].value).toFixed(2) },
                            { name: 'Expected minutes', value: fmt.int(payload[0].payload.xmins) },
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey="xp" fill="var(--s1)" radius={[4, 4, 0, 0]} maxBarSize={24} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section>
            <h3 className="mb-1 text-[14px] font-semibold text-ink">Where the GW{meta.gws[0]} points come from</h3>
            <p className="mb-3 text-[12.5px] text-muted">
              Each event rate times its FPL points value, weighted by the chance of playing 60+ minutes.
            </p>
            <ul className="flex flex-col gap-2">
              {parts.map((x) => (
                <li key={x.key} className="grid grid-cols-[150px_1fr_52px] items-center gap-3 text-[13px]">
                  <span className="text-ink-2">{x.label}</span>
                  <span className="relative h-2 rounded-full bg-card-3">
                    <span
                      className={
                        x.v >= 0
                          ? 'absolute inset-y-0 left-0 rounded-full bg-s1'
                          : 'absolute inset-y-0 left-0 rounded-full bg-bad'
                      }
                      style={{ width: `${(Math.abs(x.v) / maxAbs) * 100}%` }}
                    />
                  </span>
                  <span className="num text-right font-medium text-ink">{fmt.signed(x.v, 2)}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center justify-between border-t border-line pt-3 text-[13px]">
              <span className="text-ink-2">Total</span>
              <span className="num font-semibold text-ink">{fmt.pts(p.xp[0], 2)}</span>
            </div>
          </section>

          {(p.pcp ?? 0) !== 0 && (
            <section className="rounded-xl bg-card p-4 ring-1 ring-line">
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-ink-2">Price change progress</span>
                <span className="num font-medium text-ink">{fmt.signed(p.pcp, 0)}%</span>
              </div>
              <div className="mt-2 text-[12px] text-muted">
                {fmt.compact(p.tin)} transfers in and {fmt.compact(p.tout)} out this gameweek.
              </div>
            </section>
          )}
        </div>
      </aside>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-card px-3 py-2.5 ring-1 ring-line">
      <div className="truncate text-[11.5px] text-muted">{label}</div>
      <div className="num mt-0.5 text-[17px] font-semibold text-ink">{value}</div>
    </div>
  )
}
