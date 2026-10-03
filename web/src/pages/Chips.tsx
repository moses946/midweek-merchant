import clsx from 'clsx'
import { CalendarClock, Star, Target } from 'lucide-react'
import { useMemo } from 'react'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { PlanExplorer } from '../components/PlanView'
import { Badge, Card, CardHeader, Empty, Note } from '../components/ui/primitives'
import { useCeiling, useFixtures, useMeta, usePlan } from '../lib/data'
import { CHIP_NAMES, fmt } from '../lib/format'
import { useTheme } from '../lib/hooks'
import { seqColor } from '../lib/scales'
import type { CeilingReport, Chip, ChipReport, FixturesBundle } from '../lib/types'
import { DataError } from './Errors'

const ORDER: Chip[] = ['wildcard', 'freehit', 'bboost', '3xc']

export default function Chips() {
  const meta = useMeta()
  const plan = usePlan()
  const ceil = useCeiling()
  const fx = useFixtures()
  if (meta.error) return <DataError error={meta.error} />
  if (!meta.data || plan.isLoading) return <PageSkeleton />
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Chip strategy"
        description="When to play Wildcard, Free Hit, Bench Boost and Triple Captain. Every chip is tested in every gameweek by re-solving the whole transfer plan with it, so knock-on effects on later weeks are counted."
      />
      {plan.data?.chips ? (
        <ChipMatrix report={plan.data.chips} />
      ) : (
        <Card>
          <Empty title="No chip report yet">The scheduled pipeline evaluates chips for the configured team.</Empty>
        </Card>
      )}
      {ceil.data && <Ceiling report={ceil.data} />}
      {fx.data && <Calendar fx={fx.data} />}
    </div>
  )
}

function ChipMatrix({ report }: { report: ChipReport }) {
  const theme = useTheme()
  const gws = useMemo(() => [...new Set(report.exact.map((r) => r.gw))].sort((a, b) => a - b), [report])
  const chips = ORDER.filter((c) => report.exact.some((r) => r.chip === c))
  const cell = (c: Chip, g: number) => report.exact.find((r) => r.chip === c && r.gw === g)
  const maxNet = Math.max(...report.exact.map((r) => r.gain - (report.option_values[r.chip] ?? 0)), 1)

  return (
    <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
      <Card className="xl:col-span-8">
        <CardHeader
          eyebrow={`Baseline: ${report.baseline_xpts.toFixed(1)} xPts without a chip`}
          title="Extra expected points from each chip, by gameweek"
          hint="Shaded by the gain beyond the value of keeping the chip for later. A grey cell means holding it is worth more."
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-separate border-spacing-[4px] text-[13px]">
            <thead>
              <tr className="text-[11.5px] text-muted">
                <th className="w-[140px] text-left font-medium">Chip</th>
                {gws.map((g) => (
                  <th key={g} className="font-medium">
                    GW{g}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {chips.map((c) => {
                const rows = report.exact.filter((r) => r.chip === c)
                const best = rows.reduce((a, b) => (b.gain > a.gain ? b : a), rows[0])
                const opt = report.option_values[c] ?? 0
                return (
                  <tr key={c}>
                    <td className="pr-2">
                      <div className="font-medium text-ink">{CHIP_NAMES[c]}</div>
                      <div className="text-[11.5px] text-muted">hold value {opt.toFixed(0)}</div>
                    </td>
                    {gws.map((g) => {
                      const r = cell(c, g)
                      if (!r)
                        return (
                          <td key={g} className="h-14 rounded-xl bg-card-2 text-center text-muted ring-1 ring-line">
                            –
                          </td>
                        )
                      const net = r.gain - opt
                      const { bg, fg } =
                        net > 0
                          ? seqColor(0.15 + (0.85 * net) / maxNet, theme)
                          : { bg: 'var(--card-2)', fg: 'var(--muted)' }
                      const isBest = r === best
                      return (
                        <td
                          key={g}
                          className={clsx('relative h-14 rounded-xl text-center', isBest && 'ring-2 ring-accent')}
                          style={{ background: bg, color: fg }}
                          title={`${CHIP_NAMES[c]} in GW${g}: ${fmt.signed(r.gain)} xPts vs no chip (hold value ${opt})`}
                        >
                          {isBest && <Star size={11} className="absolute top-1.5 right-1.5" fill="currentColor" />}
                          <div className="num text-[14px] font-semibold">{fmt.signed(r.gain)}</div>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Note className="mt-3">
          ★ marks each chip&apos;s best week. Gains include the effect on every later week of the plan.
        </Note>
      </Card>
      <Card className="xl:col-span-4">
        <CardHeader
          title="Verdict"
          hint="Each chip is tested on its own and only one can be played per gameweek: when two peak in the same week, the bigger gain goes first."
        />
        <ul className="flex flex-col gap-3">
          {chips.map((c) => {
            const rows = report.exact.filter((r) => r.chip === c)
            const best = rows.reduce((a, b) => (b.gain > a.gain ? b : a), rows[0])
            const net = best.gain - (report.option_values[c] ?? 0)
            const now = best.gw === gws[0]
            const verdict = net <= 0 ? 'Hold' : now ? `Best now` : `Pencil in GW${best.gw}`
            return (
              <li key={c} className="flex items-center gap-3 rounded-xl bg-card-2 p-3 ring-1 ring-line">
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium text-ink">{CHIP_NAMES[c]}</div>
                  <div className="text-[12px] text-muted">
                    Best GW{best.gw} · {fmt.signed(best.gain)} xPts
                  </div>
                </div>
                <Badge tone={net <= 0 ? 'neutral' : now ? 'solid' : 'accent'}>{verdict}</Badge>
              </li>
            )
          })}
        </ul>
      </Card>
    </div>
  )
}

function Ceiling({ report }: { report: CeilingReport }) {
  const top = report.table.slice(0, 8)
  const max = Math.max(...top.map((r) => r.p_any), 0.001)
  const best = report.table[0]
  const ref = report.table.find((r) => r.plan === report.reference)
  const plan = report.plans[String(best.plan)]
  const gws = report.target_gws
  const weeks = plan?.weeks.filter((w) => w.sim) ?? []
  const cal = report.calibration
  return (
    <>
      <Card glow>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
          <div className="xl:col-span-4">
            <Badge tone="accent">
              <Target size={12} /> Chase a big week
            </Badge>
            <h2 className="mt-3 text-[20px] font-semibold tracking-tight text-ink">
              Best shot at {report.target}+ points in GW{gws[0]}–{gws[gws.length - 1]}
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
              Expected points win seasons; a {report.target}-point week is a tail event. Each chip schedule is solved
              for expected points over eight weeks, then scored on {fmt.int(report.n_sims)} correlated simulations with
              the captain picked for upside.
            </p>
            <div className="mt-5 flex items-end gap-6">
              <div>
                <div className="text-[44px] leading-none font-semibold tracking-tight text-ink">
                  {fmt.pctSmart(best.p_any)}
                </div>
                <div className="mt-1 text-[12px] text-muted">chance with the best plan</div>
              </div>
              {ref && ref.plan !== best.plan && (
                <div>
                  <div className="text-[24px] leading-none font-semibold text-ink-2">{fmt.pctSmart(ref.p_any)}</div>
                  <div className="mt-1 text-[12px] text-muted">best plan for xPts</div>
                </div>
              )}
            </div>
            <p className="mt-4 text-[12.5px] text-ink-2">
              Expected points given up: <b className="num text-ink">{best.cost_vs_best.toFixed(1)}</b> over eight
              gameweeks.
            </p>
          </div>
          <div className="xl:col-span-8">
            <div className="mb-3 flex items-center justify-between text-[11.5px] text-muted">
              <span>Chip schedule</span>
              <span className="flex gap-6">
                <span>xPts cost</span>
                <span className="w-12 text-right">P({report.target}+)</span>
              </span>
            </div>
            <ul className="flex flex-col gap-2.5">
              {top.map((r, i) => (
                <li key={r.plan} className="grid grid-cols-[1fr_auto] items-center gap-4">
                  <div className="min-w-0">
                    <div
                      title={r.label}
                      className={clsx('truncate text-[13px]', i === 0 ? 'font-semibold text-ink' : 'text-ink-2')}
                    >
                      {r.label}
                    </div>
                    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-card-3">
                      <div
                        className={clsx('h-full rounded-full', i === 0 ? 'bg-accent' : 'bg-s2')}
                        style={{ width: `${(r.p_any / max) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <span className="num w-12 text-right text-[12.5px] text-muted">
                      {r.cost_vs_best ? `−${r.cost_vs_best.toFixed(1)}` : '0'}
                    </span>
                    <span className="num w-12 text-right text-[13px] font-semibold text-ink">
                      {fmt.pctSmart(r.p_any)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            {cal && (
              <Note className="mt-5">
                Tail calibration: simulated spread scaled by k = {report.scale} (CRPS fit on {cal.gameweeks} blind
                hindcast gameweeks). With it those weeks expected {cal.fitted.n80_expected.toFixed(1)} scores of 80+
                (observed {cal.fitted.n80_observed}) and {cal.fitted.n100_expected.toFixed(1)} of 100+ (observed{' '}
                {cal.fitted.n100_observed}).
              </Note>
            )}
          </div>
        </div>
      </Card>
      {weeks.length > 0 && (
        <PlanExplorer
          weeks={weeks}
          title={<h3 className="text-[16px] font-semibold tracking-tight text-ink">{plan.label}, week by week</h3>}
          tabExtra={(w) => (w.sim ? `P(${report.target}+) ${fmt.pctSmart(w.sim.p_target)}` : '')}
          extraFacts={(w) =>
            w.sim ? (
              <>
                <div className="flex items-center justify-between py-2 text-[13px]">
                  <span className="text-ink-2">Simulated mean</span>
                  <span className="num font-medium text-ink">{w.sim.mean.toFixed(1)}</span>
                </div>
                <div className="flex items-center justify-between py-2 text-[13px]">
                  <span className="text-ink-2">1-in-10 week</span>
                  <span className="num font-medium text-ink">{w.sim.p90.toFixed(0)}</span>
                </div>
                <div className="flex items-center justify-between py-2 text-[13px]">
                  <span className="text-ink-2">1-in-100 week</span>
                  <span className="num font-medium text-ink">{w.sim.p99.toFixed(0)}</span>
                </div>
              </>
            ) : null
          }
        />
      )}
    </>
  )
}

function Calendar({ fx }: { fx: FixturesBundle }) {
  const special = fx.calendar.filter((c) => c.blank.length || c.double.length)
  return (
    <Card>
      <CardHeader
        eyebrow="Fixture calendar"
        title="Blank and double gameweeks"
        hint="Bench Boost and Triple Captain love doubles; Free Hit rescues blanks."
        action={<CalendarClock size={18} className="text-muted" />}
      />
      {special.length ? (
        <div className="flex flex-wrap gap-2">
          {special.map((c) => (
            <div key={c.gw} className="rounded-xl bg-card-2 px-3 py-2 ring-1 ring-line">
              <div className="font-mono text-[11.5px] text-ink">GW{c.gw}</div>
              {c.double.length > 0 && <div className="text-[12px] text-good">Double: {c.double.join(', ')}</div>}
              {c.blank.length > 0 && <div className="text-[12px] text-bad">Blank: {c.blank.join(', ')}</div>}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-ink-2">No blank or double gameweeks are scheduled yet.</p>
      )}
      <Note className="mt-3">
        {fx.unscheduled
          ? `${fx.unscheduled} fixture${fx.unscheduled === 1 ? ' has' : 's have'} no gameweek yet (postponed or cup-affected); they usually become doubles. `
          : 'Every remaining fixture has a gameweek for now. '}
        Expected this season: blanks around GW30 (League Cup final) and GW33 (FA Cup semi-finals), doubles around GW32
        and GW35–36.
      </Note>
    </Card>
  )
}
