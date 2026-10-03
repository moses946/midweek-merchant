import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TooltipCard } from '../components/charts/common'
import { axis } from '../components/charts/theme'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { Card, CardHeader, Jersey, Note, Segmented } from '../components/ui/primitives'
import { useFixtures, useMeta } from '../lib/data'
import { runSummary, ticker, type TickerCell } from '../lib/fixtures'
import { useTheme } from '../lib/hooks'
import { rampStops, seqColor } from '../lib/scales'
import { teamColors } from '../lib/teams'
import type { FixturesBundle, Meta } from '../lib/types'
import { DataError } from './Errors'

type Mode = 'attack' | 'defence'

export default function Fixtures() {
  const meta = useMeta()
  const fx = useFixtures()
  if (meta.error || fx.error) return <DataError error={meta.error ?? fx.error} />
  if (!meta.data || !fx.data) return <PageSkeleton />
  return <Body meta={meta.data} fx={fx.data} />
}

function Body({ meta, fx }: { meta: Meta; fx: FixturesBundle }) {
  const [mode, setMode] = useState<Mode>('attack')
  const [run, setRun] = useState(Math.min(4, meta.gws.length))
  const theme = useTheme()
  const grid = useMemo(
    () =>
      ticker(
        fx,
        meta.teams.map((t) => t.short),
        meta.gws,
      ),
    [fx, meta],
  )
  const value = (c: TickerCell) => (mode === 'attack' ? c.xg : c.cs)
  const all = [...grid.values()].flat().filter((c) => c.opps.length)
  const lo = Math.min(...all.map(value))
  const hi = Math.max(...all.map(value))
  const rows = [...grid.entries()]
    .map(([team, cells]) => {
      const s = runSummary(cells, run)
      return { team, cells, score: mode === 'attack' ? s.xg : s.cs }
    })
    .sort((a, b) => b.score - a.score)

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Fixture ticker"
        description="Every club's next eight gameweeks, coloured by what the model expects: goals scored when attacking, clean-sheet chance when defending. Odds from betting markets steer the nearest gameweek."
      />
      <Card pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              value={mode}
              onChange={setMode}
              options={[
                { value: 'attack', label: 'Attack · expected goals' },
                { value: 'defence', label: 'Defence · clean-sheet %' },
              ]}
            />
            <Segmented
              value={run}
              onChange={setRun}
              size="sm"
              options={[2, 4, 6, meta.gws.length]
                .filter((v, i, a) => v <= meta.gws.length && a.indexOf(v) === i)
                .map((v) => ({ value: v, label: `Sort by next ${v}` }))}
            />
          </div>
          <ScaleLegend lo={lo} hi={hi} mode={mode} theme={theme} />
        </div>
        <div className="overflow-x-auto px-3 pb-4 sm:px-4">
          <table className="w-full min-w-[860px] border-separate border-spacing-[3px] text-[12px]">
            <thead>
              <tr className="text-[11.5px] text-muted">
                <th className="w-[120px] px-2 text-left font-medium">Team</th>
                {meta.gws.map((g, k) => (
                  <th key={g} className={clsx('py-1 font-medium', k < run && 'text-ink')}>
                    GW{g}
                  </th>
                ))}
                <th className="w-16 pr-2 text-right font-medium">Next {run}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ team, cells, score }) => (
                <tr key={team}>
                  <td className="px-2">
                    <div className="flex items-center gap-2">
                      <Jersey team={team} size={20} />
                      <span className="font-semibold text-ink">{team}</span>
                    </div>
                  </td>
                  {cells.map((c, k) => {
                    if (!c.opps.length)
                      return (
                        <td
                          key={c.gw}
                          className="h-10 rounded-lg bg-card-2 text-center font-mono text-[10.5px] text-muted ring-1 ring-line"
                        >
                          BLANK
                        </td>
                      )
                    const t = (value(c) - lo) / (hi - lo || 1)
                    const { bg, fg } = seqColor(t, theme)
                    return (
                      <td
                        key={c.gw}
                        className={clsx(
                          'h-10 rounded-lg px-1 text-center transition-opacity',
                          k >= run && 'opacity-55',
                        )}
                        style={{ background: bg, color: fg }}
                        title={`${team} GW${c.gw}: ${c.opps.map((o) => `${o.opp} (${o.home ? 'H' : 'A'})`).join(' + ')} · xG ${c.xg.toFixed(2)} · clean sheet ${(c.cs * 100).toFixed(0)}%`}
                      >
                        <div className="leading-tight font-semibold">
                          {c.opps.map((o) => (o.home ? o.opp : o.opp.toLowerCase())).join(' + ')}
                        </div>
                        <div className="num text-[10.5px] leading-tight opacity-80">
                          {mode === 'attack' ? c.xg.toFixed(2) : `${Math.round(c.cs * 100)}%`}
                        </div>
                      </td>
                    )
                  })}
                  <td className="num pr-2 text-right text-[13px] font-semibold text-ink">
                    {mode === 'attack' ? score.toFixed(1) : score.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Note className="mt-3 px-2">
            Capitals are home games, lower case away. “Next {run}” sums expected goals (attack) or expected clean sheets
            (defence) over the next {run} gameweeks; later gameweeks are dimmed.
          </Note>
        </div>
      </Card>

      <TeamStrength meta={meta} />
    </div>
  )
}

function ScaleLegend({ lo, hi, mode, theme }: { lo: number; hi: number; mode: Mode; theme: 'dark' | 'light' }) {
  const f = (v: number) => (mode === 'attack' ? v.toFixed(1) : `${Math.round(v * 100)}%`)
  return (
    <div className="flex items-center gap-2 text-[11.5px] text-muted">
      <span className="num">{f(lo)}</span>
      <span className="flex h-2.5 w-40 overflow-hidden rounded-full ring-1 ring-line">
        {rampStops(theme).map((c) => (
          <span key={c} className="flex-1" style={{ background: c }} />
        ))}
      </span>
      <span className="num">{f(hi)}</span>
    </div>
  )
}

function niceDomain(vals: number[], step = 0.2): [number, number, number[]] {
  const lo = Math.floor((Math.min(...vals) - 0.04) / step) * step
  const hi = Math.ceil((Math.max(...vals) + 0.04) / step) * step
  const ticks: number[] = []
  for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(Number(v.toFixed(2)))
  return [lo, hi, ticks]
}

type Box = { x0: number; x1: number; y0: number; y1: number }
type LabelPos = { dx: number; dy: number; anchor: 'start' | 'end' | 'middle' }
const CHART_H = 460
const MARGIN = { top: 12, right: 28, bottom: 30, left: 8 }
const Y_AXIS_W = 60
const X_AXIS_H = 30 // Recharts' default
const PLOT = {
  left: MARGIN.left + Y_AXIS_W,
  right: MARGIN.right,
  top: MARGIN.top,
  bottom: MARGIN.bottom + X_AXIS_H,
}

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}
const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

function TeamStrength({ meta }: { meta: Meta }) {
  const data = meta.teams
    .filter((t) => t.xg_for != null && t.xg_against != null)
    .map((t) => ({ team: t.short, name: t.name, x: t.xg_for!, y: t.xg_against! }))
  const avgX = data.reduce((s, d) => s + d.x, 0) / (data.length || 1)
  const avgY = data.reduce((s, d) => s + d.y, 0) / (data.length || 1)
  const [x0, x1, xt] = niceDomain(data.map((d) => d.x))
  const [y0, y1, yt] = niceDomain(data.map((d) => d.y))
  const [ref, width] = useWidth<HTMLDivElement>()
  const labels = useMemo(() => {
    // Map points to pixels with the chart's own geometry, then place each label greedily
    // (right, left, above, below) clear of every dot and of the labels already placed.
    const plotW = Math.max(1, width - PLOT.left - PLOT.right)
    const plotH = Math.max(1, CHART_H - PLOT.top - PLOT.bottom)
    const px = data.map((d) => ({
      team: d.team,
      cx: PLOT.left + ((d.x - x0) / (x1 - x0)) * plotW,
      cy: PLOT.top + ((d.y - y0) / (y1 - y0)) * plotH,
    }))
    const taken: Box[] = px.map(({ cx, cy }) => ({ x0: cx - 8, x1: cx + 8, y0: cy - 8, y1: cy + 8 }))
    const out = new Map<string, LabelPos>()
    for (const { team, cx, cy } of px) {
      const w = team.length * 7.4
      const options: (LabelPos & { box: Box })[] = [
        { dx: 11, dy: 4, anchor: 'start', box: { x0: cx + 10, x1: cx + 12 + w, y0: cy - 6, y1: cy + 6 } },
        { dx: -11, dy: 4, anchor: 'end', box: { x0: cx - 12 - w, x1: cx - 10, y0: cy - 6, y1: cy + 6 } },
        { dx: 0, dy: -12, anchor: 'middle', box: { x0: cx - w / 2, x1: cx + w / 2, y0: cy - 22, y1: cy - 9 } },
        { dx: 0, dy: 20, anchor: 'middle', box: { x0: cx - w / 2, x1: cx + w / 2, y0: cy + 9, y1: cy + 22 } },
      ]
      // Every option sits clear of its own dot, so checking all taken boxes is enough.
      const pick = options.find((o) => !taken.some((b) => overlaps(b, o.box))) ?? options[0]
      taken.push(pick.box)
      out.set(team, { dx: pick.dx, dy: pick.dy, anchor: pick.anchor })
    }
    return out
  }, [data, width, x0, x1, y0, y1])
  return (
    <Card>
      <CardHeader
        eyebrow="Dixon–Coles team model"
        title="Team strength"
        hint="Expected goals for and against per match versus an average opponent, from a time-decayed Poisson model of goals and xG. The conceded axis is flipped, so the best teams sit top right."
      />
      <div ref={ref} style={{ height: CHART_H }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={MARGIN}>
            <CartesianGrid stroke="var(--grid)" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[x0, x1]}
              ticks={xt}
              tickFormatter={(v: number) => v.toFixed(1)}
              {...axis}
              label={{
                value: 'Expected goals scored per match',
                position: 'insideBottom',
                offset: -18,
                fill: 'var(--muted)',
                fontSize: 12,
              }}
            />
            <YAxis
              type="number"
              dataKey="y"
              reversed
              domain={[y0, y1]}
              ticks={yt}
              tickFormatter={(v: number) => v.toFixed(1)}
              {...axis}
              width={Y_AXIS_W}
              label={{
                value: 'Expected goals conceded',
                angle: -90,
                position: 'insideLeft',
                offset: 8,
                fill: 'var(--muted)',
                fontSize: 12,
                style: { textAnchor: 'middle' },
              }}
            />
            <ReferenceLine x={avgX} stroke="var(--axis)" strokeDasharray="4 4" />
            <ReferenceLine y={avgY} stroke="var(--axis)" strokeDasharray="4 4" />
            <Tooltip
              cursor={false}
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <TooltipCard
                    title={payload[0].payload.name}
                    rows={[
                      { name: 'xG for / match', value: payload[0].payload.x.toFixed(2) },
                      { name: 'xG against / match', value: payload[0].payload.y.toFixed(2) },
                    ]}
                  />
                ) : null
              }
            />
            <Scatter
              data={data}
              shape={(props: { cx?: number; cy?: number; payload?: { team: string } }) => {
                const { cx = 0, cy = 0, payload } = props
                const label = payload?.team ?? ''
                const pos = labels.get(label) ?? { dx: 11, dy: 4, anchor: 'start' as const }
                const [body] = teamColors(label)
                return (
                  <g>
                    <circle cx={cx} cy={cy} r={8} fill="var(--card)" />
                    <circle
                      cx={cx}
                      cy={cy}
                      r={6}
                      fill={body}
                      stroke="var(--ink-2)"
                      strokeOpacity={0.35}
                      strokeWidth={1}
                    />
                    <text
                      x={cx + pos.dx}
                      y={cy + pos.dy}
                      textAnchor={pos.anchor}
                      fontSize={11.5}
                      fontWeight={600}
                      fill="var(--ink-2)"
                    >
                      {label}
                    </text>
                  </g>
                )
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <Note className="mt-2">Dashed lines mark the league average.</Note>
    </Card>
  )
}
