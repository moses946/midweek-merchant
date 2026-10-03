import { ArrowRight, ArrowUpRight, Crown, Medal, Target, Trophy, Wallet } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Legend, Sparkline, TooltipCard } from '../components/charts/common'
import { axis, grid } from '../components/charts/theme'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { Badge, Card, CardHeader, Empty, Jersey, Meter, Note, PosTag, Stat, TeamTag } from '../components/ui/primitives'
import { useCeiling, useFixtures, useHindcast, useLeague, useMeta, usePlan, usePlayers } from '../lib/data'
import { runSummary, ticker } from '../lib/fixtures'
import { CHIP_NAMES, fmt, shortDate } from '../lib/format'
import type { Meta, PlanPlayer, Player, TeamPlan } from '../lib/types'
import { DataError } from './Errors'

export default function Overview() {
  const meta = useMeta()
  if (meta.error) return <DataError error={meta.error} />
  if (!meta.data) return <PageSkeleton />
  return <OverviewBody meta={meta.data} />
}

function OverviewBody({ meta }: { meta: Meta }) {
  const plan = usePlan()
  const players = usePlayers()
  const gwRange = `GW${meta.gws[0]}–${meta.gws[meta.gws.length - 1]}`
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title={`Gameweek ${meta.next_gw}`}
        description={
          <>
            Expected points for all {meta.players} players over {gwRange}, an optimised transfer plan, and the odds in
            your mini-league. Deadline {meta.deadline ? shortDate(meta.deadline) : 'TBC'}.
          </>
        }
        actions={
          <Link
            to="/team"
            className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-accent-ink shadow-[0_8px_24px_-8px_rgba(197,240,60,0.5)] transition-transform hover:-translate-y-px"
          >
            Open the planner <ArrowRight size={15} />
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <div className="xl:col-span-8">
          {plan.data ? (
            <MoveHero plan={plan.data} />
          ) : (
            <Card className="h-full">
              <Empty title={plan.isLoading ? 'Loading the plan…' : 'No team configured'}>
                {plan.isLoading
                  ? null
                  : 'Set FPL_TEAM_ID for the scheduled pipeline to see a recommended move for your team here.'}
              </Empty>
            </Card>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:gap-5 xl:col-span-4 xl:grid-cols-1">
          <LeagueTile />
          <CeilingTile />
        </div>
      </div>

      {plan.data && <StateTiles plan={plan.data} />}

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <div className="xl:col-span-5">{players.data && <Captaincy players={players.data} gw={meta.next_gw} />}</div>
        <div className="xl:col-span-7">{players.data && <TopPlayers players={players.data} meta={meta} />}</div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <TrackRecordCard season={meta.season} />
        </div>
        <div className="xl:col-span-5">
          <FixtureRuns meta={meta} />
        </div>
      </div>
    </div>
  )
}

function MoveCard({ p, dir }: { p: PlanPlayer; dir: 'out' | 'in' }) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-card-2 p-3 ring-1 ring-line">
      <Jersey team={p.team} size={40} />
      <div className="min-w-0 flex-1">
        <span className={dir === 'in' ? 'eyebrow !text-accent-text' : 'eyebrow'}>{dir === 'in' ? 'Buy' : 'Sell'}</span>
        <div className="truncate text-[15px] font-semibold text-ink">{p.name}</div>
        <div className="truncate text-[12px] text-ink-2">
          {p.team} · {fmt.price(p.price)}
        </div>
      </div>
      <div className="text-right">
        <div className="num text-[16px] font-semibold text-ink">{p.xpts.toFixed(1)}</div>
        <div className="text-[11px] text-muted">xPts</div>
      </div>
    </div>
  )
}

const MAX_MOVES = 3

function MoveHero({ plan }: { plan: TeamPlan }) {
  const wk = plan.weeks[0]
  const moves = wk.transfers_out.map((o, i) => [o, wk.transfers_in[i]] as const)
  const gain = moves.reduce((s, [o, i]) => s + (i?.xpts ?? 0) - o.xpts, 0)
  const weeks = plan.weeks.map((w) => ({ gw: `GW${w.gw}`, xpts: w.xpts, chip: w.chip, hits: w.hits }))
  return (
    <Card glow className="h-full">
      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">Recommended move</Badge>
            <span className="text-[12.5px] text-muted">
              for <span className="font-medium text-ink-2">{plan.state.name}</span>
            </span>
          </div>
          <div className="mt-5 flex items-end gap-3">
            <div className="text-[56px] leading-none font-semibold tracking-tight text-ink">{wk.xpts.toFixed(1)}</div>
            <div className="pb-1.5 text-[13px] leading-snug text-ink-2">
              expected points
              <br />
              in GW{wk.gw}
            </div>
          </div>
          <div className="mt-6 flex flex-col gap-2">
            {moves.length ? (
              moves.slice(0, MAX_MOVES).map(([o, i]) => (
                <div key={o.element} className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
                  <MoveCard p={o} dir="out" />
                  <ArrowRight size={18} className="mx-auto shrink-0 rotate-90 text-muted sm:rotate-0" />
                  {i && <MoveCard p={i} dir="in" />}
                </div>
              ))
            ) : (
              <div className="rounded-2xl bg-card-2 p-4 text-[13.5px] text-ink-2 ring-1 ring-line">
                Roll the free transfer: no move beats banking it this week.
              </div>
            )}
          </div>
          {moves.length > MAX_MOVES && (
            <Link to="/team" className="mt-2 text-[12.5px] font-medium text-accent-text hover:underline">
              and {moves.length - MAX_MOVES} more on the planner
            </Link>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-ink-2">
            {moves.length > 0 && (
              <span>
                <span className="num font-semibold text-good">{fmt.signed(gain)}</span> xPts this week
              </span>
            )}
            <span className="inline-flex items-center gap-1.5">
              <Crown size={14} className="text-accent-text" /> Captain{' '}
              <span className="font-medium text-ink">{wk.captain.name}</span>
            </span>
            <span>
              Vice <span className="font-medium text-ink">{wk.vice.name}</span>
            </span>
            {wk.hits > 0 && <Badge tone="bad">−{4 * wk.hits} hit</Badge>}
            {wk.chip && <Badge tone="solid">{CHIP_NAMES[wk.chip]}</Badge>}
          </div>
        </div>
        <div className="flex w-full flex-col lg:w-[260px]">
          <div className="eyebrow">Plan horizon</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[22px] font-semibold tracking-tight">{plan.total_xpts.toFixed(0)}</span>
            <span className="text-[12.5px] text-muted">xPts over {plan.weeks.length} gameweeks</span>
          </div>
          <div className="mt-3 h-[150px] lg:h-auto lg:min-h-[150px] lg:flex-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weeks} margin={{ top: 18, right: 0, left: 0, bottom: 0 }} barCategoryGap="24%">
                <XAxis dataKey="gw" {...axis} axisLine={false} />
                <YAxis hide domain={[0, 'dataMax + 8']} />
                <Tooltip
                  cursor={{ fill: 'var(--card-2)' }}
                  content={({ active, payload }) =>
                    active && payload?.length ? (
                      <TooltipCard
                        title={String(payload[0].payload.gw)}
                        rows={[{ name: 'Expected points', value: Number(payload[0].value).toFixed(1) }]}
                        footer={
                          payload[0].payload.chip
                            ? CHIP_NAMES[payload[0].payload.chip as keyof typeof CHIP_NAMES]
                            : undefined
                        }
                      />
                    ) : null
                  }
                />
                <Bar
                  dataKey="xpts"
                  fill="var(--s1)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                  label={{
                    position: 'top',
                    fill: 'var(--ink-2)',
                    fontSize: 11,
                    formatter: (v: unknown) => Number(v).toFixed(0),
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Link
            to="/team"
            className="mt-3 inline-flex items-center gap-1 self-start text-[12.5px] font-medium text-accent-text hover:underline"
          >
            Week-by-week plan <ArrowUpRight size={14} />
          </Link>
        </div>
      </div>
    </Card>
  )
}

function LeagueTile() {
  const league = useLeague()
  const me = league.data?.standings.find((s) => s.is_me)
  const rank = league.data ? league.data.standings.findIndex((s) => s.is_me) + 1 : 0
  const best = league.data?.plans[league.data.best_plan]
  return (
    <Stat
      label="Chance of winning the league"
      icon={<Trophy size={16} />}
      value={me ? fmt.pctSmart(best?.p_first_season ?? me.p_win_league) : '–'}
      sub={
        league.data && me ? (
          <>
            {fmt.ordinal(rank)} of {league.data.standings.length} in {league.data.league.name}. Simulated with every
            rival&apos;s squad.{' '}
            <Link to="/league" className="font-medium text-accent-text hover:underline">
              Strategy
            </Link>
          </>
        ) : (
          'Mini-league analysis appears after the next scheduled run.'
        )
      }
    />
  )
}

function CeilingTile() {
  const ceil = useCeiling()
  const best = ceil.data?.table[0]
  const gws = ceil.data?.target_gws ?? []
  return (
    <Stat
      label={`Chance of a ${ceil.data?.target ?? 100}+ point week`}
      icon={<Target size={16} />}
      value={best ? fmt.pctSmart(best.p_any) : '–'}
      sub={
        best ? (
          <>
            Best chip schedule for GW{gws[0]}–{gws[gws.length - 1]}: {best.label}.{' '}
            <Link to="/chips" className="font-medium text-accent-text hover:underline">
              Chips
            </Link>
          </>
        ) : (
          'Ceiling plans appear after the next scheduled run.'
        )
      }
    />
  )
}

function StateTiles({ plan }: { plan: TeamPlan }) {
  const s = plan.state
  const chipsLeft = Object.values(s.chips_available).reduce((n, h) => n + (h?.length ?? 0), 0)
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 lg:gap-5">
      <Stat
        label="Overall rank"
        icon={<Medal size={16} />}
        value={s.overall_rank ? fmt.compact(s.overall_rank) : '–'}
        sub={`${s.total_points ?? '–'} points so far · ${s.last_gw_points ?? '–'} last GW`}
      />
      <Stat
        label="Squad value"
        icon={<Wallet size={16} />}
        value={`£${(s.squad_value / 10).toFixed(1)}m`}
        sub={`£${(s.bank / 10).toFixed(1)}m in the bank`}
      />
      <Stat
        label="Free transfers"
        value={s.free_transfers}
        sub={`Plan uses ${plan.weeks.reduce((n, w) => n + w.transfers_in.length, 0)} transfers over ${plan.weeks.length} GWs`}
      />
      <Stat label="Chips in hand" value={chipsLeft} sub="Two of each per season: one per half" />
    </div>
  )
}

function Captaincy({ players, gw }: { players: Player[]; gw: number }) {
  const top = players.slice(0, 8)
  const max = top[0]?.xp[0] ?? 1
  return (
    <Card className="h-full">
      <CardHeader
        eyebrow={`GW${gw}`}
        title="Captaincy shortlist"
        hint="Highest expected points this gameweek; the armband doubles them."
      />
      <ul className="flex flex-col gap-1">
        {top.map((p, i) => (
          <li key={p.id} className="flex items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-card-2">
            <span className="num w-4 text-[12px] text-muted">{i + 1}</span>
            <Jersey team={p.team} size={30} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-[14px] font-medium text-ink">{p.name}</span>
                {p.status !== 'a' && <Badge tone="warn">{p.chance ?? 0}%</Badge>}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <Meter value={p.xp[0] ?? 0} max={max} />
              </div>
            </div>
            <div className="w-[88px] text-right">
              <div className="num text-[15px] font-semibold text-ink">{fmt.pts(p.xp[0], 2)}</div>
              <div className="truncate text-[11.5px] text-muted">{p.fx[0]}</div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function TopPlayers({ players, meta }: { players: Player[]; meta: Meta }) {
  const n = Math.min(4, meta.gws.length)
  const rows = useMemo(
    () =>
      players
        .map((p) => ({ p, sum: p.xp.slice(0, n).reduce<number>((s, v) => s + (v ?? 0), 0) }))
        .sort((a, b) => b.sum - a.sum)
        .slice(0, 8),
    [players, n],
  )
  return (
    <Card className="h-full" pad={false}>
      <div className="p-5 pb-0 sm:p-6 sm:pb-0">
        <CardHeader
          eyebrow={`GW${meta.gws[0]}–${meta.gws[n - 1]}`}
          title="Best over the next four"
          hint="Total expected points with the per-gameweek trend across the full horizon."
          action={
            <Link
              to="/players"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent-text hover:underline"
            >
              All players <ArrowUpRight size={14} />
            </Link>
          }
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-[13px]">
          <thead>
            <tr className="border-y border-line text-left text-[11.5px] text-muted">
              <th className="px-5 py-2 font-medium sm:px-6">Player</th>
              <th className="py-2 font-medium">Pos</th>
              <th className="py-2 text-right font-medium">Price</th>
              <th className="py-2 pl-6 font-medium">Trend</th>
              <th className="px-5 py-2 text-right font-medium sm:px-6">xPts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ p, sum }) => (
              <tr key={p.id} className="border-b border-line last:border-0 hover:bg-card-2/60">
                <td className="px-5 py-2.5 sm:px-6">
                  <div className="flex items-center gap-2.5">
                    <Jersey team={p.team} size={24} />
                    <div className="min-w-0">
                      <div className="truncate font-medium text-ink">{p.name}</div>
                      <TeamTag team={p.team} className="!text-[11px]" />
                    </div>
                  </div>
                </td>
                <td>
                  <PosTag pos={p.pos} />
                </td>
                <td className="num text-right text-ink-2">{fmt.price(p.price)}</td>
                <td className="pl-6">
                  <Sparkline values={p.xp} />
                </td>
                <td className="num px-5 text-right text-[14px] font-semibold text-ink sm:px-6">{sum.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function TrackRecordCard({ season }: { season: string }) {
  const h = useHindcast(season)
  const data = useMemo(
    () =>
      (h.data?.gameweeks ?? []).map((g) => ({
        gw: `GW${g.gw}`,
        model: g.scores.model ?? null,
        fpl: g.scores.fpl_ep ?? null,
        avg: g.average_manager,
      })),
    [h.data],
  )
  const model = h.data?.summary.find((r) => r.pick === 'Model')
  return (
    <Card className="h-full">
      <CardHeader
        eyebrow="Picked blind, scored on reality"
        title="Track record this season"
        hint="Before each deadline the model picks its XI using only what was known then; the real points come later."
        action={
          <Link
            to="/track-record"
            className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent-text hover:underline"
          >
            Details <ArrowUpRight size={14} />
          </Link>
        }
      />
      {model && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          <MiniStat label="Avg points / GW" value={model.mean_points.toFixed(1)} />
          <MiniStat label="Beats avg manager" value={fmt.pct(model.beats_average_manager)} />
          <MiniStat label="Beats FPL's own pick" value={fmt.pct(model.beats_fpl_ep_pick)} />
        </div>
      )}
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
            <CartesianGrid {...grid} />
            <XAxis dataKey="gw" {...axis} />
            <YAxis {...axis} axisLine={false} width={44} />
            <Tooltip
              cursor={{ stroke: 'var(--axis)' }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <TooltipCard
                    title={label}
                    rows={payload.map((r) => ({
                      color: String(r.color),
                      name: String(r.name),
                      value: r.value == null ? '–' : Number(r.value).toFixed(0),
                    }))}
                  />
                ) : null
              }
            />
            <Line
              type="linear"
              name="Model"
              dataKey="model"
              stroke="var(--s1)"
              strokeWidth={2.25}
              dot={{ r: 3.5, strokeWidth: 2, stroke: 'var(--card)', fill: 'var(--s1)' }}
            />
            <Line type="linear" name="FPL's pick" dataKey="fpl" stroke="var(--s2)" strokeWidth={2} dot={false} />
            <Line
              type="linear"
              name="Average manager"
              dataKey="avg"
              stroke="var(--muted)"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3">
        <Legend
          items={[
            { label: 'Model', color: 'var(--s1)' },
            { label: "FPL's pick", color: 'var(--s2)' },
            { label: 'Average manager', color: 'var(--muted)', dashed: true },
          ]}
        />
      </div>
    </Card>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-card-2 px-3 py-2.5 ring-1 ring-line">
      <div className="text-[11.5px] text-muted">{label}</div>
      <div className="mt-0.5 text-[18px] font-semibold tracking-tight text-ink">{value}</div>
    </div>
  )
}

function FixtureRuns({ meta }: { meta: Meta }) {
  const fx = useFixtures()
  const n = Math.min(4, meta.gws.length)
  const rows = useMemo(() => {
    if (!fx.data) return []
    const t = ticker(
      fx.data,
      meta.teams.map((x) => x.short),
      meta.gws,
    )
    return [...t.entries()]
      .map(([team, cells]) => ({ team, ...runSummary(cells, n), cells: cells.slice(0, n) }))
      .sort((a, b) => b.xg - a.xg)
  }, [fx.data, meta, n])
  const top = rows.slice(0, 6)
  const max = top[0]?.xg ?? 1
  return (
    <Card className="h-full">
      <CardHeader
        eyebrow={`GW${meta.gws[0]}–${meta.gws[n - 1]}`}
        title="Best attacking runs"
        hint="Expected goals over the next four gameweeks from the team-strength model and betting markets."
        action={
          <Link
            to="/fixtures"
            className="inline-flex items-center gap-1 text-[12.5px] font-medium text-accent-text hover:underline"
          >
            Ticker <ArrowUpRight size={14} />
          </Link>
        }
      />
      <ul className="flex flex-col gap-3">
        {top.map((r) => (
          <li key={r.team} className="flex items-center gap-3">
            <Jersey team={r.team} size={26} />
            <div className="w-10 text-[13px] font-semibold text-ink">{r.team}</div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Meter value={r.xg} max={max} tone="s2" />
              <div className="flex gap-1.5 overflow-hidden">
                {r.cells.map((c) => (
                  <span key={c.gw} className="truncate font-mono text-[10.5px] text-muted">
                    {c.opps.map((o) => (o.home ? o.opp : o.opp.toLowerCase())).join('+') || 'blank'}
                  </span>
                ))}
              </div>
            </div>
            <div className="num w-12 text-right text-[14px] font-semibold text-ink">{r.xg.toFixed(1)}</div>
          </li>
        ))}
      </ul>
      <Note className="mt-4">Opponents in capitals are home games, lower case away.</Note>
    </Card>
  )
}
