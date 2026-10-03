import clsx from 'clsx'
import { ArrowDownRight, ArrowRight, ArrowUpRight, Crown, RotateCcw } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { CHIP_NAMES, fmt } from '../lib/format'
import type { PlanWeek } from '../lib/types'
import { Pitch } from './Pitch'
import { Badge, Card, CardHeader, Jersey } from './ui/primitives'

export function WeekTabs({
  weeks,
  value,
  onChange,
  extra,
}: {
  weeks: PlanWeek[]
  value: number
  onChange: (i: number) => void
  extra?: (w: PlanWeek) => ReactNode
}) {
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {weeks.map((w, i) => (
        <button
          key={w.gw}
          onClick={() => onChange(i)}
          className={clsx(
            'flex min-w-[92px] shrink-0 flex-col items-start rounded-2xl px-3.5 py-2.5 text-left ring-1 transition-all',
            i === value ? 'bg-card shadow-card ring-accent/60' : 'bg-card-2/60 ring-line hover:bg-card-2',
          )}
        >
          <span className="flex w-full items-center justify-between gap-2">
            <span className={clsx('font-mono text-[11px]', i === value ? 'text-accent-text' : 'text-muted')}>
              GW{w.gw}
            </span>
            {w.chip && (
              <span className="rounded bg-accent px-1 font-mono text-[9.5px] font-bold text-accent-ink">
                {w.chip === '3xc' ? 'TC' : w.chip === 'bboost' ? 'BB' : w.chip === 'freehit' ? 'FH' : 'WC'}
              </span>
            )}
          </span>
          <span className="num mt-0.5 text-[17px] font-semibold text-ink">{w.xpts.toFixed(1)}</span>
          <span className="text-[11px] text-muted">
            {extra ? extra(w) : `${w.transfers_in.length} transfer${w.transfers_in.length === 1 ? '' : 's'}`}
          </span>
        </button>
      ))}
    </div>
  )
}

function TransferRow({ p, dir }: { p: PlanWeek['transfers_in'][number]; dir: 'out' | 'in' }) {
  return (
    <div className="flex items-center gap-2.5">
      <Jersey team={p.team} pos={p.position} size={30} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-[13px] font-medium text-ink">
          {dir === 'out' ? (
            <ArrowDownRight size={13} className="shrink-0 text-bad" />
          ) : (
            <ArrowUpRight size={13} className="shrink-0 text-good" />
          )}
          <span className="truncate">{p.name}</span>
        </div>
        <div className="truncate text-[11.5px] text-muted">
          {p.team} · £{p.price.toFixed(1)}m
        </div>
      </div>
      <span className="num text-[13px] font-medium text-ink-2">{p.xpts.toFixed(1)}</span>
    </div>
  )
}

export function TransferList({ week }: { week: PlanWeek }) {
  const pairs = week.transfers_out.map((o, i) => [o, week.transfers_in[i]] as const)
  if (week.chip === 'freehit')
    return <p className="text-[13px] text-ink-2">Free Hit: this whole squad is temporary and reverts next week.</p>
  if (week.chip === 'wildcard' && week.transfers_in.length > 3)
    return (
      <p className="text-[13px] text-ink-2">
        Wildcard: {week.transfers_in.length} changes, highlighted on the pitch. Transfers are free this week.
      </p>
    )
  if (!pairs.length)
    return (
      <div className="flex items-center gap-2 text-[13px] text-ink-2">
        <RotateCcw size={15} className="text-muted" /> No transfer: roll it for {Math.min(5, week.free_transfers + 1)}{' '}
        next week.
      </div>
    )
  return (
    <ul className="flex flex-col gap-2">
      {pairs.map(([o, i]) => (
        <li key={o.element} className="flex flex-col gap-2 rounded-xl bg-card-2 p-3 ring-1 ring-line">
          <TransferRow p={o} dir="out" />
          {i && <TransferRow p={i} dir="in" />}
        </li>
      ))}
    </ul>
  )
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 text-[13px]">
      <span className="text-ink-2">{label}</span>
      <span className="num font-medium text-ink">{value}</span>
    </div>
  )
}

/** Week picker + pitch + transfers/summary side panel. */
export function PlanExplorer({
  weeks,
  title,
  extraFacts,
  tabExtra,
}: {
  weeks: PlanWeek[]
  title?: ReactNode
  extraFacts?: (w: PlanWeek) => ReactNode
  tabExtra?: (w: PlanWeek) => ReactNode
}) {
  const [i, setI] = useState(0)
  const w = weeks[Math.min(i, weeks.length - 1)] as PlanWeek | undefined
  const highlight = useMemo(() => new Set((w?.transfers_in ?? []).map((p) => p.element)), [w])
  if (!w) return null
  return (
    <div className="flex flex-col gap-4">
      {title}
      <WeekTabs weeks={weeks} value={i} onChange={setI} extra={tabExtra} />
      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <Pitch week={w} highlight={highlight} />
        </Card>
        <div className="flex flex-col gap-4 lg:gap-5 xl:col-span-4">
          <Card>
            <CardHeader eyebrow={`GW${w.gw}`} title="Transfers" />
            <TransferList week={w} />
          </Card>
          <Card>
            <CardHeader eyebrow={`GW${w.gw}`} title="Week summary" />
            <div className="divide-y divide-line">
              <Fact label="Expected points" value={w.xpts.toFixed(1)} />
              <Fact
                label="Captain"
                value={
                  <span className="inline-flex items-center gap-1.5">
                    <Crown size={13} className="text-accent-text" />
                    {w.captain.name}
                    <span className="text-muted">({(w.captain.xpts * (w.chip === '3xc' ? 3 : 2)).toFixed(1)})</span>
                  </span>
                }
              />
              <Fact label="Vice-captain" value={w.vice.name} />
              <Fact label="Chip" value={w.chip ? <Badge tone="solid">{CHIP_NAMES[w.chip]}</Badge> : 'None'} />
              <Fact label="Free transfers available" value={w.free_transfers} />
              <Fact label="Hits" value={w.hits ? <span className="text-bad">−{4 * w.hits}</span> : '0'} />
              <Fact label="Bank after transfers" value={fmt.price(w.bank)} />
              {extraFacts?.(w)}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

/** Compact table of every week in a plan. */
export function PlanTimeline({ weeks }: { weeks: PlanWeek[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11.5px] text-muted">
            <th className="py-2 pr-3 font-medium">Gameweek</th>
            <th className="py-2 pr-3 font-medium">Moves</th>
            <th className="py-2 pr-3 font-medium">Captain</th>
            <th className="py-2 pr-3 font-medium">Chip</th>
            <th className="py-2 pr-3 text-right font-medium">Hits</th>
            <th className="py-2 text-right font-medium">xPts</th>
          </tr>
        </thead>
        <tbody>
          {weeks.map((w) => (
            <tr key={w.gw} className="border-b border-line last:border-0">
              <td className="py-3 pr-3 font-mono text-[12px] text-ink-2">GW{w.gw}</td>
              <td className="py-3 pr-3 text-ink">
                {w.chip === 'freehit' || (w.chip === 'wildcard' && w.transfers_in.length > 3) ? (
                  <span className="text-ink-2">{w.transfers_in.length} changes</span>
                ) : w.transfers_in.length >= 11 && !w.transfers_out.length ? (
                  <span className="text-ink-2">Build the squad</span>
                ) : w.transfers_out.length ? (
                  w.transfers_out.map((o, k) => (
                    <span key={o.element} className="mr-3 inline-flex items-center gap-1 whitespace-nowrap">
                      <span className="text-ink-2">{o.name}</span>
                      <ArrowRight size={12} className="text-muted" />
                      <span className="font-medium">{w.transfers_in[k]?.name}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-muted">Roll</span>
                )}
              </td>
              <td className="py-3 pr-3 text-ink">{w.captain.name}</td>
              <td className="py-3 pr-3">
                {w.chip ? <Badge tone="solid">{CHIP_NAMES[w.chip]}</Badge> : <span className="text-muted">–</span>}
              </td>
              <td className="num py-3 pr-3 text-right">
                {w.hits ? <span className="text-bad">−{4 * w.hits}</span> : <span className="text-muted">0</span>}
              </td>
              <td className="num py-3 text-right font-semibold text-ink">{w.xpts.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
