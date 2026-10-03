import clsx from 'clsx'
import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Legend, TooltipCard } from '../components/charts/common'
import { axis, grid } from '../components/charts/theme'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { Pitch } from '../components/Pitch'
import { Badge, Card, CardHeader, Note, Segmented } from '../components/ui/primitives'
import { useHindcast, useMeta } from '../lib/data'
import { fmt, shortDate } from '../lib/format'
import type { Hindcast, HindcastWeek, PickKey } from '../lib/types'
import { DataError } from './Errors'

const SERIES: { key: PickKey | 'avg'; label: string; color: string; dashed?: boolean }[] = [
  { key: 'model', label: 'Model', color: 'var(--s1)' },
  { key: 'fpl_ep', label: "FPL's ep", color: 'var(--s2)' },
  { key: 'form', label: 'Form (last 4)', color: 'var(--s3)' },
  { key: 'avg', label: 'Average manager', color: 'var(--muted)', dashed: true },
]

export default function TrackRecord() {
  const meta = useMeta()
  const seasons = useMemo(
    () =>
      Object.keys(meta.data?.files.hindcast ?? {})
        .sort()
        .reverse(),
    [meta.data],
  )
  const [picked, setSeason] = useState<string | undefined>()
  const season = picked ?? seasons[0]
  const h = useHindcast(season)
  if (meta.error || h.error) return <DataError error={meta.error ?? h.error} />
  if (!meta.data || !season || !h.data) return <PageSkeleton />
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Track record"
        description="The honest test. For each gameweek already played, the model picks its best XI, captain and bench using only what was known before that deadline. Then the real points are revealed, next to FPL's own predictions and recent form picking under the same rules."
        actions={
          seasons.length > 1 ? (
            <Segmented
              value={season}
              onChange={setSeason}
              options={seasons.map((s) => ({ value: s, label: s.replace('-', '/') }))}
            />
          ) : undefined
        }
      />
      <Body h={h.data} />
    </div>
  )
}

function Body({ h }: { h: Hindcast }) {
  const weeks = h.gameweeks
  const hasAvg = weeks.some((w) => w.average_manager != null)
  const series = SERIES.filter((s) => s.key !== 'avg' || hasAvg)
  const data = weeks.map((w) => ({
    gw: `GW${w.gw}`,
    model: w.scores.model ?? null,
    fpl_ep: w.scores.fpl_ep ?? null,
    form: w.scores.form ?? null,
    avg: w.average_manager,
    edge: w.scores.model != null && w.scores.fpl_ep != null ? w.scores.model - w.scores.fpl_ep : null,
  }))
  const byPick = Object.fromEntries(h.summary.map((r) => [r.pick, r]))
  const model = byPick['Model']
  const ep = byPick['FPL ep']
  const form = byPick['Form (last 4)']
  const avg = byPick['Average manager']
  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:gap-5 xl:grid-cols-4">
        <SummaryTile
          label="Model"
          color="var(--s1)"
          value={model?.mean_points}
          sub={`${model?.total_points.toFixed(0)} points in ${model?.gameweeks} GWs`}
          highlight
        />
        <SummaryTile
          label="FPL's own prediction"
          color="var(--s2)"
          value={ep?.mean_points}
          sub={`Model wins ${fmt.pct(model?.beats_fpl_ep_pick)} of gameweeks`}
        />
        <SummaryTile
          label="Recent form"
          color="var(--s3)"
          value={form?.mean_points}
          sub="Best XI by FPL form over the last four gameweeks"
        />
        {avg ? (
          <SummaryTile
            label="Average manager"
            color="var(--muted)"
            value={avg.mean_points}
            sub={`Model beats them in ${fmt.pct(model?.beats_average_manager)} of gameweeks`}
          />
        ) : (
          <SummaryTile
            label="Share of the best possible"
            value={model?.share_of_hindsight != null ? model.share_of_hindsight * 100 : undefined}
            suffix="%"
            sub="Model points / hindsight-optimal XI"
          />
        )}
      </div>

      <Card>
        <CardHeader
          title="Actual points of each blind pick"
          hint="Every pick is a fresh Free-Hit-style squad each week (£100m, three per club). The average manager carries a squad and pays for transfers, so they are a looser comparison."
        />
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="gw" {...axis} interval="preserveStartEnd" minTickGap={16} />
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
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="linear"
                  name={s.label}
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={s.key === 'model' ? 2.5 : 1.75}
                  strokeOpacity={s.key === 'model' ? 1 : 0.85}
                  strokeDasharray={s.dashed ? '4 4' : undefined}
                  dot={
                    s.key === 'model' && weeks.length <= 12
                      ? { r: 3.5, strokeWidth: 2, stroke: 'var(--card)', fill: s.color }
                      : false
                  }
                  activeDot={{ r: 4.5, strokeWidth: 2, stroke: 'var(--card)' }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3">
          <Legend items={series.map((s) => ({ label: s.label, color: s.color, dashed: s.dashed }))} />
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Model minus FPL's prediction, each gameweek"
          hint={`Both pick blind under the same rules from the same pre-deadline information. Bars above zero are gameweeks the model's XI outscored FPL's ep XI; the model averaged ${fmt.signed((model?.mean_points ?? 0) - (ep?.mean_points ?? 0))} points a week.`}
        />
        <div className="h-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="gw" {...axis} interval="preserveStartEnd" minTickGap={16} />
              <YAxis {...axis} axisLine={false} width={44} />
              <ReferenceLine y={0} stroke="var(--axis)" />
              <Tooltip
                cursor={{ fill: 'var(--card-2)' }}
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <TooltipCard
                      title={label}
                      rows={[{ name: 'Model − FPL ep', value: fmt.signed(Number(payload[0].value), 0) }]}
                    />
                  ) : null
                }
              />
              <Bar dataKey="edge" radius={[3, 3, 3, 3]} maxBarSize={18}>
                {data.map((d) => (
                  <Cell key={d.gw} fill={(d.edge ?? 0) >= 0 ? 'var(--good)' : 'var(--bad)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <WeekDetail key={h.season} weeks={weeks} />
    </>
  )
}

function SummaryTile({
  label,
  value,
  sub,
  color,
  highlight,
  suffix = '',
}: {
  label: string
  value: number | undefined
  sub: string
  color?: string
  highlight?: boolean
  suffix?: string
}) {
  return (
    <div className={clsx('card relative overflow-hidden p-5', highlight && 'ring-1 ring-accent/40')}>
      {highlight && (
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: 'var(--glow)' }} />
      )}
      <div className="relative">
        <div className="flex items-center gap-2 text-[13px] font-medium text-ink-2">
          {color && <span className="size-2.5 rounded-full" style={{ background: color }} />}
          {label}
        </div>
        <div className="mt-3 flex items-baseline gap-1.5">
          <span className="text-[30px] leading-none font-semibold tracking-tight text-ink">
            {value == null ? '–' : value.toFixed(1)}
            {suffix}
          </span>
          {!suffix && <span className="text-[12.5px] text-muted">pts / GW</span>}
        </div>
        <div className="mt-2 text-[12.5px] text-muted">{sub}</div>
      </div>
    </div>
  )
}

function WeekDetail({ weeks }: { weeks: HindcastWeek[] }) {
  const [gw, setGw] = useState(weeks[weeks.length - 1].gw)
  const w = weeks.find((x) => x.gw === gw) ?? weeks[weeks.length - 1]
  const model = w.picks.model
  const hind = w.picks.hindsight
  return (
    <Card>
      <CardHeader
        title="One gameweek in detail"
        hint="Each card shows the pre-deadline prediction and what actually happened. Points include the captain (vice if the captain did not play) and automatic substitutions."
      />
      <div className="-mx-1 mb-5 flex gap-1.5 overflow-x-auto px-1 pb-1">
        {weeks.map((x) => {
          const diff = (x.scores.model ?? 0) - (x.scores.fpl_ep ?? x.scores.model ?? 0)
          return (
            <button
              key={x.gw}
              onClick={() => setGw(x.gw)}
              className={clsx(
                'flex min-w-[52px] shrink-0 flex-col items-center rounded-xl px-2 py-1.5 ring-1 transition-colors',
                x.gw === gw ? 'bg-card ring-accent/60' : 'bg-card-2/60 ring-line hover:bg-card-2',
              )}
            >
              <span className={clsx('font-mono text-[10.5px]', x.gw === gw ? 'text-accent-text' : 'text-muted')}>
                GW{x.gw}
              </span>
              <span className="num text-[13px] font-semibold text-ink">{x.scores.model ?? '–'}</span>
              <span className={clsx('mt-0.5 h-1 w-5 rounded-full', diff >= 0 ? 'bg-good' : 'bg-bad')} />
            </button>
          )
        })}
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-2">
        <Badge>Deadline {shortDate(w.deadline)}</Badge>
        <Badge tone={w.snapshot_used ? 'good' : 'warn'}>
          {w.snapshot_used ? 'Team news snapshot used' : 'No news snapshot: all assumed fit'}
        </Badge>
        {(['model', 'fpl_ep', 'form', 'hindsight'] as PickKey[]).map((k) =>
          w.scores[k] != null ? (
            <Badge key={k} tone={k === 'model' ? 'accent' : 'neutral'}>
              {k === 'model' ? 'Model' : k === 'fpl_ep' ? "FPL's ep" : k === 'form' ? 'Form' : 'Hindsight'}:{' '}
              {w.scores[k]}
            </Badge>
          ) : null,
        )}
        {w.average_manager != null && <Badge>Average manager: {w.average_manager}</Badge>}
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {model && (
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="text-[14px] font-semibold text-ink">Model&apos;s pick, made before the deadline</h3>
              <span className="num text-[13px] text-ink-2">
                predicted {model.predicted?.toFixed(1)} → <b className="text-ink">{w.scores.model}</b>
              </span>
            </div>
            <Pitch week={model} mode="actual" compact />
          </div>
        )}
        {hind && (
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <h3 className="text-[14px] font-semibold text-ink">Best XI possible in hindsight</h3>
              <span className="num text-[13px] text-ink-2">
                <b className="text-ink">{w.scores.hindsight}</b> points
              </span>
            </div>
            <Pitch week={hind} mode="actual" compact />
          </div>
        )}
      </div>
      <Note className="mt-4">“DNP” marks a starter who did not play; the first eligible bench player came on.</Note>
    </Card>
  )
}
