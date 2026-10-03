import { Crown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Legend, TooltipCard } from '../components/charts/common'
import { axis, grid } from '../components/charts/theme'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { Pitch } from '../components/Pitch'
import { PlanTimeline } from '../components/PlanView'
import { Card, CardHeader, Note, Segmented, Stat } from '../components/ui/primitives'
import { useBestSquads, usePlan } from '../lib/data'
import { fmt } from '../lib/format'
import type { BestSquads, TeamPlan } from '../lib/types'
import { DataError } from './Errors'

export default function BestXI() {
  const best = useBestSquads()
  const plan = usePlan()
  const [tab, setTab] = useState<'gw' | 'wc'>('gw')
  if (best.error) return <DataError error={best.error} />
  if (!best.data) return <PageSkeleton />
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Best possible squads"
        description={`The optimal 15 within £${best.data.budget.toFixed(1)}m and the three-per-club rule: picked fresh for each gameweek (what a Free Hit would choose), or built now and managed with one free transfer a week (a Wildcard draft).`}
        actions={
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'gw', label: 'Per gameweek' },
              { value: 'wc', label: 'Wildcard draft' },
            ]}
          />
        }
      />
      {tab === 'gw' ? (
        <PerGameweek best={best.data} plan={plan.data} />
      ) : (
        <Wildcard best={best.data} plan={plan.data} />
      )}
    </div>
  )
}

function PerGameweek({ best, plan }: { best: BestSquads; plan?: TeamPlan }) {
  const gws = useMemo(
    () =>
      Object.keys(best.per_gw)
        .map(Number)
        .sort((a, b) => a - b),
    [best],
  )
  const [gw, setGw] = useState(gws[0])
  const wk = best.per_gw[String(gw)]
  const cost = [...wk.lineup, ...wk.bench].reduce((s, p) => s + p.price, 0)
  const planBy = new Map(plan?.weeks.map((w) => [w.gw, w.xpts]))
  const chart = gws.map((g) => ({ gw: `GW${g}`, best: best.per_gw[String(g)].xpts, mine: planBy.get(g) ?? null }))
  return (
    <>
      <Segmented
        value={gw}
        onChange={setGw}
        options={gws.map((g) => ({ value: g, label: `GW${g}` }))}
        className="self-start"
      />
      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <Pitch week={wk} />
        </Card>
        <div className="flex flex-col gap-4 lg:gap-5 xl:col-span-4">
          <div className="grid grid-cols-2 gap-4 lg:gap-5 xl:grid-cols-1">
            <Stat label={`Expected points, GW${gw}`} value={wk.xpts.toFixed(1)} accent sub="Captain counted twice" />
            <Stat label="Squad cost" value={fmt.price(cost)} sub={`£${(best.budget - cost).toFixed(1)}m left over`} />
          </div>
          <Card>
            <CardHeader title="Armband" />
            <div className="flex items-center gap-3">
              <Crown size={18} className="text-accent-text" />
              <div className="flex-1">
                <div className="text-[14px] font-medium text-ink">{wk.captain.name}</div>
                <div className="text-[12px] text-muted">
                  {wk.captain.team} · {wk.captain.fixture}
                </div>
              </div>
              <div className="num text-[15px] font-semibold">{(wk.captain.xpts * 2).toFixed(1)}</div>
            </div>
            <div className="mt-3 flex items-center gap-3 border-t border-line pt-3">
              <span className="grid size-[18px] place-items-center rounded-full bg-ink font-mono text-[10px] font-bold text-bg">
                V
              </span>
              <div className="flex-1 text-[13px] text-ink-2">{wk.vice.name}</div>
              <div className="num text-[13px] text-ink-2">{wk.vice.xpts.toFixed(1)}</div>
            </div>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader
          title="The ceiling each week"
          hint={
            plan
              ? `Best possible XI against ${plan.state.name}'s planned team. The gap is what a Free Hit could add that week, before its cost of not having it later.`
              : 'Expected points of the best possible XI in each gameweek.'
          }
        />
        <div className="h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={4}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="gw" {...axis} />
              <YAxis {...axis} axisLine={false} width={44} />
              <Tooltip
                cursor={{ fill: 'var(--card-2)' }}
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <TooltipCard
                      title={label}
                      rows={payload.map((r) => ({
                        color: String(r.color),
                        name: String(r.name),
                        value: r.value == null ? '–' : Number(r.value).toFixed(1),
                      }))}
                    />
                  ) : null
                }
              />
              <Bar name="Best possible XI" dataKey="best" fill="var(--s1)" radius={[4, 4, 0, 0]} maxBarSize={22} />
              {plan && <Bar name="Your plan" dataKey="mine" fill="var(--s2)" radius={[4, 4, 0, 0]} maxBarSize={22} />}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3">
          <Legend
            items={[
              { label: 'Best possible XI', color: 'var(--s1)' },
              ...(plan ? [{ label: 'Your plan', color: 'var(--s2)' }] : []),
            ]}
          />
        </div>
      </Card>
    </>
  )
}

function Wildcard({ best, plan }: { best: BestSquads; plan?: TeamPlan }) {
  const wc = best.wildcard
  const first = wc.weeks[0]
  const n = wc.weeks.length
  const mine = plan?.weeks.slice(0, n).reduce((s, w) => s + w.xpts, 0)
  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:gap-5">
        <Stat
          label={`Wildcard draft, ${n} gameweeks`}
          value={wc.total_xpts.toFixed(1)}
          accent
          sub="Expected points with one free transfer a week"
        />
        {mine != null && (
          <Stat label="Your current plan" value={mine.toFixed(1)} sub={`Over the same ${n} gameweeks without a chip`} />
        )}
        {mine != null && (
          <Stat
            label="Wildcard gain"
            value={fmt.signed(wc.total_xpts - mine)}
            delta={{ value: 'xPts', good: wc.total_xpts - mine > 0 }}
            sub="Before the value of keeping the chip for later"
          />
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader eyebrow={`GW${first.gw}`} title="Squad to build" />
          <Pitch week={first} />
        </Card>
        <Card className="xl:col-span-5">
          <CardHeader
            title="Then, week by week"
            hint="Transfers the draft plans after the wildcard, solved jointly with the squad."
          />
          <PlanTimeline weeks={wc.weeks} />
          <Note className="mt-4">The Chips page tests every wildcard week against holding it.</Note>
        </Card>
      </div>
    </>
  )
}
