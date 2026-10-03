import { AlertTriangle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { LivePlanner } from '../components/LivePlanner'
import { PlanExplorer, PlanTimeline } from '../components/PlanView'
import {
  Badge,
  Card,
  CardHeader,
  Empty,
  Jersey,
  Note,
  PosTag,
  Segmented,
  Stat,
  XpCell,
} from '../components/ui/primitives'
import { useMeta, usePlan, usePlayers } from '../lib/data'
import { CHIP_NAMES, fmt, POSITIONS } from '../lib/format'
import type { Chip, ChipPlan, Player, TeamPlan } from '../lib/types'
import { DataError } from './Errors'

export default function MyTeam() {
  const meta = useMeta()
  const saved = usePlan()
  const players = usePlayers()
  const [live, setLive] = useState<TeamPlan | null>(null)
  const [withChips, setWithChips] = useState(false)
  const plan = live ?? saved.data
  const chipPlan = live ? null : (plan?.with_chips ?? null)
  const shown = chipPlan && withChips ? chipPlan : plan
  if (meta.error) return <DataError error={meta.error} />
  if (!meta.data || saved.isLoading) return <PageSkeleton />

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title={plan ? plan.state.name : 'My team'}
        description={
          plan ? (
            <>
              Team {plan.state.entry_id}: squad, selling prices, bank, free transfers and chips rebuilt from public FPL
              data, then a {plan.weeks.length}-week transfer plan solved as a mixed-integer program over{' '}
              {meta.data.players} players.
            </>
          ) : (
            'Load a team to see its optimised plan.'
          )
        }
        actions={live ? <Badge tone="accent">Live plan</Badge> : <Badge>Scheduled plan</Badge>}
      />

      <LivePlanner onPlan={setLive} active={Boolean(live)} onReset={() => setLive(null)} />

      {!plan ? (
        <Card>
          <Empty title="No plan yet">The scheduled pipeline writes a plan for the configured team.</Empty>
        </Card>
      ) : (
        <>
          <StateStrip plan={plan} />
          {chipPlan && shown && (
            <ChipToggle plan={plan} chipPlan={chipPlan} value={withChips} onChange={setWithChips} />
          )}
          <PlanExplorer key={withChips ? 'chips' : 'none'} weeks={shown?.weeks ?? plan.weeks} />
          <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
            <Card className="xl:col-span-7">
              <CardHeader
                title="The plan at a glance"
                hint={`Expected points over the horizon: ${(shown ?? plan).total_xpts.toFixed(1)}. Later weeks are discounted, so the plan favours points that are surer and sooner.`}
              />
              <PlanTimeline weeks={shown?.weeks ?? plan.weeks} />
            </Card>
            <Card className="xl:col-span-5">
              <ChipsHeld plan={plan} />
            </Card>
          </div>
          {players.data && <SquadTable plan={plan} players={players.data} gws={meta.data.gws} />}
        </>
      )}
    </div>
  )
}

function ChipToggle({
  plan,
  chipPlan,
  value,
  onChange,
}: {
  plan: TeamPlan
  chipPlan: ChipPlan
  value: boolean
  onChange: (v: boolean) => void
}) {
  const avg = (t: number, n: number) => (n ? t / n : 0).toFixed(1)
  const schedule = Object.entries(chipPlan.schedule)
    .map(([gw, c]) => `${CHIP_NAMES[c]} GW${gw}`)
    .join(', ')
  return (
    <Card>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-[13.5px] font-medium text-ink">
            {avg(plan.total_xpts, plan.weeks.length)} xPts a week without chips,{' '}
            <span className="text-accent">{avg(chipPlan.total_xpts, chipPlan.weeks.length)}</span> with them
          </div>
          <div className="mt-0.5 text-[12.5px] text-muted">
            Best schedule: {schedule}. Every schedule is solved in full, and each chip is charged the value of keeping
            it for later.
          </div>
        </div>
        <Segmented
          className="shrink-0"
          value={value ? 'chips' : 'none'}
          onChange={(v) => onChange(v === 'chips')}
          options={[
            { value: 'none', label: 'Without chips' },
            { value: 'chips', label: 'With best chips' },
          ]}
        />
      </div>
    </Card>
  )
}

function StateStrip({ plan }: { plan: TeamPlan }) {
  const s = plan.state
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:gap-5 xl:grid-cols-5">
      <Stat
        label="Total points"
        value={s.total_points ?? '–'}
        sub={`${s.last_gw_points ?? '–'} in the last gameweek`}
      />
      <Stat label="Overall rank" value={s.overall_rank ? fmt.int(s.overall_rank) : '–'} />
      <Stat label="Squad value" value={`£${(s.squad_value / 10).toFixed(1)}m`} sub="at selling prices" />
      <Stat label="In the bank" value={`£${(s.bank / 10).toFixed(1)}m`} />
      <Stat label="Free transfers" value={s.free_transfers} sub={`for GW${s.next_gw}`} />
    </div>
  )
}

function ChipsHeld({ plan }: { plan: TeamPlan }) {
  const avail = plan.state.chips_available
  const chips: Chip[] = ['wildcard', 'freehit', 'bboost', '3xc']
  return (
    <>
      <CardHeader
        title="Chips"
        hint="2026/27 gives two of each: one for GW1–19 (expires at the GW19 deadline) and one for GW20–38."
      />
      <ul className="grid grid-cols-2 gap-2">
        {chips.map((c) => {
          const halves = avail[c] ?? []
          return (
            <li key={c} className="rounded-xl bg-card-2 p-3 ring-1 ring-line">
              <div className="text-[13px] font-medium text-ink">{CHIP_NAMES[c]}</div>
              <div className="mt-2 flex gap-1.5">
                {[1, 2].map((h) => (
                  <Badge
                    key={h}
                    tone={halves.includes(h) ? 'accent' : 'neutral'}
                    className={halves.includes(h) ? '' : 'line-through opacity-60'}
                  >
                    {h === 1 ? 'GW1–19' : 'GW20–38'}
                  </Badge>
                ))}
              </div>
            </li>
          )
        })}
      </ul>
      {plan.chips && (
        <Note className="mt-4">
          No-chip plan: {plan.chips.baseline_xpts.toFixed(1)} xPts. See <b>Chips</b> for the gain from playing each chip
          in each gameweek.
        </Note>
      )}
      {plan.state.notes.map((n) => (
        <p key={n} className="mt-3 flex items-start gap-2 text-[12.5px] text-warn">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {n}
        </p>
      ))}
    </>
  )
}

function SquadTable({ plan, players, gws }: { plan: TeamPlan; players: Player[]; gws: number[] }) {
  const byId = useMemo(() => new Map(players.map((p) => [p.id, p])), [players])
  const n = Math.min(6, gws.length)
  const rows = useMemo(
    () =>
      plan.state.squad
        .map((s) => ({ s, p: byId.get(s.element) }))
        .sort(
          (a, b) =>
            POSITIONS.indexOf(a.s.position) - POSITIONS.indexOf(b.s.position) || (b.p?.xp[0] ?? 0) - (a.p?.xp[0] ?? 0),
        ),
    [plan, byId],
  )
  return (
    <Card pad={false}>
      <div className="p-5 pb-0 sm:p-6 sm:pb-0">
        <CardHeader
          title="Current squad"
          hint="Selling price is what FPL pays you back: half of any rise since you bought, rounded down."
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] text-[13px]">
          <thead>
            <tr className="border-y border-line text-left text-[11.5px] text-muted">
              <th className="px-5 py-2 font-medium sm:px-6">Player</th>
              <th className="py-2 font-medium">Pos</th>
              <th className="py-2 font-medium">Next</th>
              {gws.slice(0, n).map((g) => (
                <th key={g} className="py-2 text-right font-medium">
                  GW{g}
                </th>
              ))}
              <th className="py-2 pl-4 text-right font-medium">Bought</th>
              <th className="py-2 text-right font-medium">Sell</th>
              <th className="px-5 py-2 font-medium sm:px-6">News</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, p }) => (
              <tr key={s.element} className="border-b border-line last:border-0 hover:bg-card-2/60">
                <td className="px-5 py-2.5 sm:px-6">
                  <div className="flex items-center gap-2.5">
                    <Jersey team={p?.team ?? ''} pos={s.position} size={30} />
                    <div>
                      <div className="font-medium text-ink">{s.name}</div>
                      <div className="text-[11.5px] text-muted">{p?.team}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <PosTag pos={s.position} />
                </td>
                <td className="text-ink-2">{p?.fx[0] || '–'}</td>
                {gws.slice(0, n).map((g, k) => (
                  <td key={g} className="num text-right">
                    <XpCell v={p?.xp[k] ?? null} />
                  </td>
                ))}
                <td className="num pl-4 text-right text-ink-2">£{(s.purchase_price / 10).toFixed(1)}</td>
                <td className="num text-right font-medium text-ink">£{(s.selling_price / 10).toFixed(1)}</td>
                <td className="max-w-[240px] truncate px-5 text-[12px] sm:px-6">
                  {p && p.status !== 'a' ? (
                    <span className="text-warn" title={p.news}>
                      {p.news || 'Flagged'}
                    </span>
                  ) : (
                    <span className="text-muted">–</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
