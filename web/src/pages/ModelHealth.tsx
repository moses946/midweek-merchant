import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipCard } from '../components/charts/common'
import { axis, grid } from '../components/charts/theme'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { Card, CardHeader, Empty, Note, Segmented, Stat } from '../components/ui/primitives'
import { useModel } from '../lib/data'
import { fmt } from '../lib/format'
import type { ModelBundle, RankCalibration } from '../lib/types'
import { DataError } from './Errors'

const PRED: Record<string, { label: string; color: string }> = {
  model: { label: 'Model', color: 'var(--s1)' },
  'FPL ep (pre-deadline)': { label: "FPL's ep", color: 'var(--s2)' },
  'form (last 4)': { label: 'Form (last 4)', color: 'var(--s3)' },
}

export default function ModelHealth() {
  const m = useModel()
  if (m.error) return <DataError error={m.error} />
  if (!m.data) return <PageSkeleton />
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Model health"
        description="How good are the projections? A rolling-origin backtest replays last season week by week, letting the model see only data from before each deadline, and compares it with FPL's own pre-deadline prediction and recent form."
      />
      {m.data.backtest ? (
        <Backtest b={m.data.backtest} />
      ) : (
        <Card>
          <Empty title="No backtest yet" />
        </Card>
      )}
      {m.data.backtest?.horizon?.length ? <Horizon b={m.data.backtest} /> : null}
      {m.data.team_strength && <TeamStrength ts={m.data.team_strength} />}
      {m.data.tails && <Tails t={m.data.tails} />}
      <Live live={m.data.live} />
    </div>
  )
}

type BacktestData = NonNullable<ModelBundle['backtest']>

function Backtest({ b }: { b: BacktestData }) {
  const subsets = useMemo(() => [...new Set(b.metrics.map((r) => r.subset))], [b])
  const [subset, setSubset] = useState(subsets[0])
  const rows = b.metrics.filter((r) => r.subset === subset)
  const all = b.metrics.filter((r) => r.subset === subsets[0])
  const model = all.find((r) => r.predictor === 'model')
  const ep = all.find((r) => r.predictor.startsWith('FPL ep'))
  const top = Object.fromEntries(b.top_picks.map((r) => [String(r.predictor), Number(r['mean points of top 10'])]))
  const rmseGain = model && ep ? 1 - model.rmse / ep.rmse : null
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:gap-5 xl:grid-cols-4">
        <Stat
          label="Prediction error (RMSE)"
          value={model?.rmse.toFixed(2) ?? '–'}
          delta={rmseGain != null ? { value: `−${(rmseGain * 100).toFixed(0)}% vs FPL`, good: true } : undefined}
          sub={`FPL's own ep: ${ep?.rmse.toFixed(2)} · ${fmt.int(model?.n)} player-gameweeks`}
          accent
        />
        <Stat
          label="Rank correlation"
          value={model?.spearman_within_pos.toFixed(2) ?? '–'}
          sub={`Within position, vs ${ep?.spearman_within_pos.toFixed(2)} for FPL's ep. Ranking is what picks teams.`}
        />
        <Stat
          label="Bias"
          value={fmt.signed(model?.bias, 2)}
          sub="Average predicted minus actual points: essentially unbiased"
        />
        <Stat
          label="Top-10 picks each week"
          value={top['model']?.toFixed(2) ?? '–'}
          sub={`Average actual points, vs ${top['FPL ep (pre-deadline)']?.toFixed(2)} for FPL's ep and ${top['hindsight best']?.toFixed(1)} in hindsight`}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader
            eyebrow={`${b.season.replace('-', '/')} · ${b.gws.length} gameweeks`}
            title="Accuracy by predictor"
            hint="Lower error is better; higher rank correlation is better. Even a perfect model has an RMSE near 2.7–2.9 for players who play, because FPL points are noisy."
          />
          <Segmented
            value={subset}
            onChange={setSubset}
            size="sm"
            options={subsets.map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))}
            className="mb-5"
          />
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            <MetricBars title="RMSE" rows={rows} k="rmse" lowerBetter />
            <MetricBars title="MAE" rows={rows} k="mae" lowerBetter />
            <MetricBars title="Rank correlation" rows={rows} k="spearman_within_pos" />
          </div>
          <Note className="mt-5">
            FPL&apos;s ep is taken from the same team-news snapshot the model uses, a few days before each deadline, so
            neither side sees late news.
          </Note>
        </Card>
        <Card className="xl:col-span-5">
          <CardHeader
            title="Calibration"
            hint="Players grouped into ten equal bins by predicted points. A calibrated model sits on the diagonal: when it says 3, players score 3 on average."
          />
          <Calibration data={b.calibration} />
        </Card>
      </div>
    </>
  )
}

function MetricBars({
  title,
  rows,
  k,
  lowerBetter,
}: {
  title: string
  rows: BacktestData['metrics']
  k: 'rmse' | 'mae' | 'spearman_within_pos'
  lowerBetter?: boolean
}) {
  const max = Math.max(...rows.map((r) => r[k]))
  const best = lowerBetter ? Math.min(...rows.map((r) => r[k])) : max
  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-ink">{title}</span>
        <span className="text-[11px] text-muted">{lowerBetter ? 'lower is better' : 'higher is better'}</span>
      </div>
      <ul className="flex flex-col gap-3">
        {rows.map((r) => {
          const p = PRED[r.predictor] ?? { label: r.predictor, color: 'var(--muted)' }
          return (
            <li key={r.predictor}>
              <div className="mb-1 flex items-center justify-between text-[12px]">
                <span className="flex items-center gap-1.5 text-ink-2">
                  <span className="size-2 rounded-full" style={{ background: p.color }} />
                  {p.label}
                </span>
                <span className={r[k] === best ? 'num font-semibold text-ink' : 'num text-ink-2'}>
                  {r[k].toFixed(3)}
                </span>
              </div>
              <div className="h-2 rounded-full bg-card-3">
                <div className="h-full rounded-full" style={{ width: `${(r[k] / max) * 100}%`, background: p.color }} />
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Calibration({ data }: { data: BacktestData['calibration'] }) {
  const hi = Math.ceil(Math.max(...data.map((d) => Math.max(d.predicted, d.actual))) + 0.2)
  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 12, left: -8, bottom: 16 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, hi]}
            tickCount={hi + 1}
            {...axis}
            label={{
              value: 'Predicted points (bin average)',
              position: 'insideBottom',
              offset: -10,
              fill: 'var(--muted)',
              fontSize: 12,
            }}
          />
          <YAxis type="number" dataKey="actual" domain={[0, hi]} tickCount={hi + 1} {...axis} width={40} />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: hi, y: hi },
            ]}
            stroke="var(--axis)"
            strokeDasharray="4 4"
          />
          <Tooltip
            cursor={false}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <TooltipCard
                  rows={[
                    { name: 'Predicted', value: Number(payload[0].payload.predicted).toFixed(2) },
                    { name: 'Actual', value: Number(payload[0].payload.actual).toFixed(2) },
                    { name: 'Player-gameweeks', value: fmt.int(payload[0].payload.n) },
                  ]}
                />
              ) : null
            }
          />
          <Scatter
            data={data}
            fill="var(--s1)"
            line={{ stroke: 'var(--s1)', strokeWidth: 2 }}
            shape={(p: { cx?: number; cy?: number }) => (
              <circle cx={p.cx} cy={p.cy} r={5} fill="var(--s1)" stroke="var(--card)" strokeWidth={2} />
            )}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function Tails({ t }: { t: NonNullable<ModelBundle['tails']> }) {
  const data = Object.entries(t.crps_by_scale)
    .map(([k, v]) => ({ k: Number(k), crps: v }))
    .sort((a, b) => a.k - b.k)
  const best = data.reduce((a, b) => (b.crps < a.crps ? b : a), data[0])
  const lo = Math.floor(Math.min(...data.map((d) => d.crps)) * 10) / 10
  const hi = Math.ceil(Math.max(...data.map((d) => d.crps)) * 10) / 10
  const yTicks = Array.from({ length: Math.round((hi - lo) / 0.1) + 1 }, (_, i) => Number((lo + i * 0.1).toFixed(1)))
  return (
    <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
      <Card className="xl:col-span-7">
        <CardHeader
          eyebrow={`${t.gameweeks} blind gameweeks · ${t.seasons.join(', ')}`}
          title="Tail calibration of the simulator"
          hint="Chasing a 100-point week needs the spread of outcomes right, not just the mean. The simulator's spread is scaled by k, chosen to minimise CRPS (a proper score for whole distributions) on blind hindcast XIs."
        />
        <div className="h-[240px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 16, left: -8, bottom: 16 }}>
              <CartesianGrid {...grid} />
              <XAxis
                dataKey="k"
                type="number"
                domain={['dataMin', 'dataMax']}
                {...axis}
                tickFormatter={(v: number) => v.toFixed(1)}
                label={{
                  value: 'Spread scale k',
                  position: 'insideBottom',
                  offset: -10,
                  fill: 'var(--muted)',
                  fontSize: 12,
                }}
              />
              <YAxis
                {...axis}
                axisLine={false}
                width={48}
                domain={[lo, hi]}
                ticks={yTicks}
                tickFormatter={(v: number) => v.toFixed(1)}
              />
              <Tooltip
                cursor={{ stroke: 'var(--axis)' }}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <TooltipCard
                      title={`k = ${Number(payload[0].payload.k).toFixed(2)}`}
                      rows={[{ name: 'CRPS', value: Number(payload[0].value).toFixed(3) }]}
                    />
                  ) : null
                }
              />
              <Line type="monotone" dataKey="crps" stroke="var(--s2)" strokeWidth={2} dot={false} />
              <ReferenceDot
                x={best.k}
                y={best.crps}
                r={5}
                fill="var(--accent)"
                stroke="var(--card)"
                strokeWidth={2}
                label={{ value: `k = ${best.k}`, position: 'top', fill: 'var(--ink)', fontSize: 12 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card className="xl:col-span-5">
        <CardHeader
          title="Big weeks: expected vs observed"
          hint="Across the same blind gameweeks, before and after scaling."
        />
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-[11.5px] text-muted">
              <th className="py-2 font-medium" />
              <th className="py-2 text-right font-medium">Raw</th>
              <th className="py-2 text-right font-medium">Calibrated</th>
              <th className="py-2 text-right font-medium">Observed</th>
            </tr>
          </thead>
          <tbody>
            {[
              {
                label: 'Scores of 80+',
                raw: t.raw.n80_expected,
                fit: t.fitted.n80_expected,
                obs: t.fitted.n80_observed,
              },
              {
                label: 'Scores of 100+',
                raw: t.raw.n100_expected,
                fit: t.fitted.n100_expected,
                obs: t.fitted.n100_observed,
              },
              { label: 'Spread (SD)', raw: t.raw.sim_sd, fit: t.fitted.sim_sd, obs: t.fitted.realised_sd },
              { label: 'Mean points', raw: t.raw.sim_mean, fit: t.fitted.sim_mean, obs: t.fitted.actual_mean },
            ].map((r) => (
              <tr key={r.label} className="border-b border-line last:border-0">
                <td className="py-3 text-ink-2">{r.label}</td>
                <td className="num py-3 text-right text-muted">{r.raw.toFixed(1)}</td>
                <td className="num py-3 text-right font-medium text-ink">{r.fit.toFixed(1)}</td>
                <td className="num py-3 text-right text-ink">{Number.isInteger(r.obs) ? r.obs : r.obs.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function Live({ live }: { live: ModelBundle['live'] }) {
  return (
    <Card>
      <CardHeader
        title="This season, live"
        hint="Projections are archived before every deadline by the scheduled pipeline; once a gameweek has been played its accuracy appears here."
      />
      {live.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-[13px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] text-muted">
                <th className="py-2 font-medium">Gameweek</th>
                <th className="py-2 text-right font-medium">Players</th>
                <th className="py-2 text-right font-medium">RMSE</th>
                <th className="py-2 text-right font-medium">MAE</th>
                <th className="py-2 text-right font-medium">Predicted total</th>
                <th className="py-2 text-right font-medium">Actual total</th>
              </tr>
            </thead>
            <tbody>
              {live.map((r) => (
                <tr key={r.gw} className="border-b border-line last:border-0">
                  <td className="py-2.5 font-mono text-[12px] text-ink-2">GW{r.gw}</td>
                  <td className="num text-right text-ink-2">{r.players}</td>
                  <td className="num text-right text-ink">{r.rmse.toFixed(2)}</td>
                  <td className="num text-right text-ink">{r.mae.toFixed(2)}</td>
                  <td className="num text-right text-ink-2">{r.predicted.toFixed(0)}</td>
                  <td className="num text-right text-ink">{r.actual.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="Waiting for the first archived gameweek to be played">
          The archive started this season; the first pre-deadline projections are scored after that gameweek finishes.
        </Empty>
      )}
    </Card>
  )
}

function RankTable({ rows, caption }: { rows: RankCalibration[]; caption: string }) {
  return (
    <div>
      <div className="mb-2 text-[12.5px] font-medium text-ink-2">{caption}</div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11.5px] text-muted">
            <th className="py-2 font-medium">Prediction rank</th>
            <th className="py-2 text-right font-medium">Predicted</th>
            <th className="py-2 text-right font-medium">Actual</th>
            <th className="py-2 text-right font-medium">Ratio</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ranks} className="border-b border-line last:border-0">
              <td className="py-2.5 font-mono text-[12px] text-ink-2">{r.ranks}</td>
              <td className="num py-2.5 text-right text-ink-2">{r.predicted.toFixed(2)}</td>
              <td className="num py-2.5 text-right text-ink">{r.actual.toFixed(2)}</td>
              <td className="num py-2.5 text-right font-medium text-ink">{(r.actual / r.predicted).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Horizon({ b }: { b: BacktestData }) {
  const rows = b.horizon ?? []
  return (
    <Card>
      <CardHeader
        eyebrow={`${b.season.replace('-', '/')} · forecast from each gameweek without odds`}
        title="Accuracy as the planner uses it"
        hint="The live forecast rarely has odds for the weeks it plans: football-data lists only the next round, a few days ahead. This replays forecasts made at past deadlines with no odds at all, one to six gameweeks ahead, and scores them on what happened."
      />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[460px] text-[13px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] text-muted">
                <th className="py-2 font-medium">Weeks ahead</th>
                <th className="py-2 text-right font-medium">RMSE</th>
                <th className="py-2 text-right font-medium">Bias</th>
                <th className="py-2 text-right font-medium">Rank corr.</th>
                <th className="py-2 text-right font-medium">Top 120: predicted → actual</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ahead} className="border-b border-line last:border-0">
                  <td className="py-2.5 font-mono text-[12px] text-ink-2">
                    {r.ahead === 0 ? 'next GW' : `+${r.ahead}`}
                  </td>
                  <td className="num py-2.5 text-right text-ink">{r.rmse.toFixed(3)}</td>
                  <td className="num py-2.5 text-right text-ink-2">{fmt.signed(r.bias, 3)}</td>
                  <td className="num py-2.5 text-right text-ink">{r.spearman_within_pos.toFixed(3)}</td>
                  <td className="num py-2.5 text-right text-ink-2">
                    {r.top120_predicted.toFixed(2)} →{' '}
                    <span className="font-medium text-ink">{r.top120_actual.toFixed(2)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-2">
          {b.top_calibration?.length ? <RankTable rows={b.top_calibration} caption="Next gameweek, with odds" /> : null}
          {b.horizon_top_calibration?.length ? (
            <RankTable rows={b.horizon_top_calibration} caption="One to six weeks ahead, no odds" />
          ) : null}
        </div>
      </div>
      <Note className="mt-4">
        Ranks are each gameweek&apos;s ordering by predicted points: ranks 1–120 are the players a manager actually
        picks from. A ratio above 1 means those players outscored their projections.
      </Note>
    </Card>
  )
}

function TeamStrength({ ts }: { ts: NonNullable<ModelBundle['team_strength']> }) {
  const rows = [
    ts.baseline_scores && { label: 'Before tuning (goals and xG only, slow decay)', s: ts.baseline_scores },
    ts.current_scores && { label: 'Now (also learns from past matches’ odds)', s: ts.current_scores },
  ].filter(Boolean) as { label: string; s: { deviance: number; sd: number; sd_market: number } }[]
  return (
    <Card>
      <CardHeader
        eyebrow={`Point-in-time, ${ts.seasons.join(' and ')}, six weeks ahead`}
        title="Team strength against the betting market"
        hint="Each fixture's expected goals scored on the goals that followed (Poisson deviance, lower is better), next to the market's own opening odds for the same fixtures."
      />
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11.5px] text-muted">
            <th className="py-2 font-medium">Team-strength model</th>
            <th className="py-2 text-right font-medium">Deviance</th>
            <th className="py-2 text-right font-medium">Spread of λ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-line">
              <td className="py-2.5 text-ink-2">{r.label}</td>
              <td className="num py-2.5 text-right font-medium text-ink">{r.s.deviance.toFixed(4)}</td>
              <td className="num py-2.5 text-right text-ink-2">{r.s.sd.toFixed(2)}</td>
            </tr>
          ))}
          <tr>
            <td className="py-2.5 text-ink-2">Bookmakers&apos; opening odds</td>
            <td className="num py-2.5 text-right font-medium text-ink">{ts.deviance_market.toFixed(4)}</td>
            <td className="num py-2.5 text-right text-ink-2">{rows[0]?.s.sd_market.toFixed(2) ?? '–'}</td>
          </tr>
        </tbody>
      </table>
      <Note className="mt-3">
        The market spreads teams further apart than the model; the extra spread reflects information the model does not
        have (transfers, injuries, tactics), so stretching the model to match it makes its forecasts worse.
      </Note>
    </Card>
  )
}
