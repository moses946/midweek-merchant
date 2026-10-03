import clsx from 'clsx'
import { Crown, Flag } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import {
  Badge,
  Card,
  CardHeader,
  Empty,
  Jersey,
  Meter,
  Note,
  PosTag,
  Segmented,
  Stat,
} from '../components/ui/primitives'
import { useLeague, useMeta } from '../lib/data'
import { CHIP_SHORT, fmt } from '../lib/format'
import type { Chip, LeagueReport } from '../lib/types'
import { DataError } from './Errors'

export default function League() {
  const meta = useMeta()
  const league = useLeague()
  if (meta.error || league.error) return <DataError error={meta.error ?? league.error} />
  if (!meta.data || league.isLoading) return <PageSkeleton />
  if (!league.data)
    return (
      <Card>
        <Empty title="No mini-league analysis yet">Set a league ID for the scheduled pipeline to analyse it.</Empty>
      </Card>
    )
  return <Body rep={league.data} />
}

function Body({ rep }: { rep: LeagueReport }) {
  const meIdx = rep.standings.findIndex((s) => s.is_me)
  const me = rep.standings[meIdx]
  const leader = rep.standings[0]
  const best = rep.plans[rep.best_plan]
  const stance = rep.z <= -0.75 ? 'Chasing' : rep.z >= 0.75 ? 'Protecting a lead' : 'Close race'
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title={rep.league.name}
        description={`Win the league, not just the gameweek. Rivals' squads are read from FPL and every candidate plan is scored against them on the same correlated simulations over GW${rep.gws[0]}–${rep.gws[rep.gws.length - 1]}, so shared players cancel out and differentials show their true risk and reward.`}
      />

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card glow className="xl:col-span-6">
          <Badge tone="accent">
            <Flag size={12} /> {stance}
          </Badge>
          <div className="mt-4 flex items-end gap-4">
            <div className="text-[52px] leading-none font-semibold tracking-tight text-ink">
              {fmt.pctSmart(best?.p_first_season)}
            </div>
            <div className="pb-1 text-[13px] leading-snug text-ink-2">
              chance to win the league
              <br />
              with the recommended plan
            </div>
          </div>
          <p className="mt-5 text-[13.5px] leading-relaxed text-ink-2">{rep.advice}</p>
          <ZGauge z={rep.z} />
        </Card>
        <div className="grid grid-cols-2 gap-4 lg:gap-5 xl:col-span-6">
          <Stat label="Position" value={fmt.ordinal(meIdx + 1)} sub={`of ${rep.standings.length} managers`} />
          <Stat
            label="Gap to the leader"
            value={me === leader ? 'Leading' : `${leader.now - me.now}`}
            sub={me === leader ? `${me.now - rep.standings[1].now} points clear` : `points behind ${leader.manager}`}
          />
          <Stat
            label="Projected finish"
            value={fmt.int(me.projected)}
            sub={`points by GW${rep.gws[rep.gws.length - 1]}, simulated`}
          />
          <Stat
            label="Recommended"
            value={best ? best.type.charAt(0).toUpperCase() + best.type.slice(1) : '–'}
            sub={best ? `${best.this_week} · captain ${best.captain}` : undefined}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:gap-5 xl:grid-cols-12">
        <Card pad={false} className="xl:col-span-7">
          <div className="p-5 pb-0 sm:p-6 sm:pb-0">
            <CardHeader
              title="Standings and title odds"
              hint="Win probability counts the chips each manager still holds."
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead>
                <tr className="border-y border-line text-left text-[11.5px] text-muted">
                  <th className="w-12 py-2 pl-5 font-medium sm:pl-6">#</th>
                  <th className="py-2 font-medium">Manager</th>
                  <th className="py-2 text-right font-medium">Points</th>
                  <th className="py-2 text-right font-medium">Projected</th>
                  <th className="w-[34%] px-5 py-2 font-medium sm:px-6">Win the league</th>
                </tr>
              </thead>
              <tbody>
                {rep.standings.map((s, i) => (
                  <tr
                    key={s.manager}
                    className={clsx('border-b border-line last:border-0', s.is_me && 'bg-accent-soft')}
                  >
                    <td className="num py-2.5 pr-2 pl-5 text-muted sm:pl-6">{i + 1}</td>
                    <td className="py-2.5">
                      <span className={clsx('font-medium', s.is_me ? 'text-accent-text' : 'text-ink')}>
                        {s.manager}
                      </span>
                      {s.is_me && <span className="ml-2 text-[11px] text-muted">you</span>}
                    </td>
                    <td className="num text-right text-ink">{s.now}</td>
                    <td className="num text-right text-ink-2">{s.projected.toFixed(0)}</td>
                    <td className="px-5 sm:px-6">
                      <div className="flex items-center gap-3">
                        <Meter
                          value={s.p_win_league}
                          max={Math.max(...rep.standings.map((x) => x.p_win_league))}
                          tone={s.is_me ? 'accent' : 's2'}
                        />
                        <span className="num w-12 text-right font-medium text-ink">{fmt.pctSmart(s.p_win_league)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card className="xl:col-span-5">
          <CardHeader
            title="Your options, by chance of winning"
            hint="Differences under about one percentage point are simulation noise; then prefer the higher-xPts option."
          />
          <ul className="flex flex-col gap-2">
            {[...rep.plans]
              .sort((a, b) => b.p_first_season - a.p_first_season)
              .map((p) => {
                const isBest = p === best
                return (
                  <li
                    key={p.option}
                    className={clsx(
                      'rounded-xl p-3 ring-1',
                      isBest ? 'bg-accent-soft ring-accent/40' : 'bg-card-2 ring-line',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13.5px] font-medium text-ink">{p.type}</span>
                      {isBest && <Badge tone="solid">Recommended</Badge>}
                      {p.chip && <Badge>{p.chip}</Badge>}
                      <span className="num ml-auto text-[14px] font-semibold text-ink">
                        {fmt.pctSmart(p.p_first_season)}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-ink-2">
                      <span>{p.this_week}</span>
                      <span className="text-muted">·</span>
                      <span>
                        <Crown size={11} className="mr-1 inline text-accent-text" />
                        {p.captain}
                      </span>
                      <span className="text-muted">·</span>
                      <span className="num">{p.xpts_horizon.toFixed(1)} xPts</span>
                      {p.hits > 0 && <span className="text-bad">−{4 * p.hits}</span>}
                    </div>
                  </li>
                )
              })}
          </ul>
        </Card>
      </div>

      <Detail rep={rep} />
    </div>
  )
}

function ZGauge({ z }: { z: number }) {
  const clamp = Math.max(-2.5, Math.min(2.5, z))
  const pos = ((clamp + 2.5) / 5) * 100
  return (
    <div className="mt-6">
      <div className="relative h-2 rounded-full bg-linear-to-r from-bad/50 via-card-3 to-good/50">
        <div
          className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink"
          style={{ left: `${pos}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between text-[11.5px] text-muted">
        <span>Chasing</span>
        <span>Close race</span>
        <span>Protecting</span>
      </div>
      <Note className="mt-2">
        Gap to the leader in units of the spread of outcomes: z = {z >= 0 ? '+' : ''}
        {z.toFixed(2)}. Chasers need variance; leaders want to cover.
      </Note>
    </div>
  )
}

function Detail({ rep }: { rep: LeagueReport }) {
  const [tab, setTab] = useState<'eo' | 'cap' | 'h2h' | 'chips'>('eo')
  return (
    <Card>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">Under the hood</h2>
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: 'eo', label: 'Ownership' },
            { value: 'cap', label: 'Captaincy' },
            { value: 'h2h', label: 'Head to head' },
            { value: 'chips', label: "Rivals' chips" },
          ]}
        />
      </div>
      {tab === 'eo' && <Ownership rep={rep} />}
      {tab === 'cap' && <Captaincy rep={rep} />}
      {tab === 'h2h' && <HeadToHead rep={rep} />}
      {tab === 'chips' && <RivalChips rep={rep} />}
    </Card>
  )
}

function Ownership({ rep }: { rep: LeagueReport }) {
  const rows = useMemo(
    () => [...rep.eo].sort((a, b) => Math.abs(b.net_exposure) - Math.abs(a.net_exposure)).slice(0, 18),
    [rep],
  )
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.net_exposure)), 1)
  return (
    <>
      <p className="mb-4 text-[13px] text-ink-2">
        Effective ownership counts each rival starter once and their captain twice. Net exposure above zero means you
        gain ground when that player scores; below zero, you lose it.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-[11.5px] text-muted">
              <th className="py-2 font-medium">Player</th>
              <th className="py-2 font-medium">Pos</th>
              <th className="py-2 text-right font-medium">xPts</th>
              <th className="py-2 text-right font-medium">League EO</th>
              <th className="py-2 text-right font-medium">You</th>
              <th className="w-[36%] py-2 pl-6 font-medium">Net exposure</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.element} className="border-b border-line last:border-0">
                <td className="py-2">
                  <div className="flex items-center gap-2">
                    <Jersey team={r.team} size={22} />
                    <span className="font-medium text-ink">{r.name}</span>
                    <span className="text-[11.5px] text-muted">{r.team}</span>
                  </div>
                </td>
                <td>
                  <PosTag pos={r.position} />
                </td>
                <td className="num text-right text-ink-2">{r.xpts.toFixed(1)}</td>
                <td className="num text-right text-ink-2">{r.league_eo.toFixed(0)}%</td>
                <td className="num text-right text-ink">{r.my_mult ? `×${r.my_mult}` : '–'}</td>
                <td className="pl-6">
                  <div className="flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded-full bg-card-3">
                      <div className="bg-axis absolute inset-y-0 left-1/2 w-px" style={{ background: 'var(--axis)' }} />
                      <div
                        className={clsx('absolute inset-y-0 rounded-full', r.net_exposure >= 0 ? 'bg-good' : 'bg-bad')}
                        style={
                          r.net_exposure >= 0
                            ? { left: '50%', width: `${(r.net_exposure / maxAbs) * 50}%` }
                            : { right: '50%', width: `${(-r.net_exposure / maxAbs) * 50}%` }
                        }
                      />
                    </div>
                    <span className="num w-12 text-right font-medium text-ink">{fmt.signed(r.net_exposure, 0)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Captaincy({ rep }: { rep: LeagueReport }) {
  return (
    <>
      <p className="mb-4 text-[13px] text-ink-2">
        Each candidate armband scored on the same simulations: the chance you beat the typical rival this gameweek, post
        the top score in the league, or lead it afterwards.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-[11.5px] text-muted">
              <th className="py-2 font-medium">Captain</th>
              <th className="py-2 text-right font-medium">Your GW xPts</th>
              <th className="py-2 text-right font-medium">League EO</th>
              <th className="py-2 pl-6 font-medium">Beat a rival</th>
              <th className="py-2 pl-6 font-medium">Top league score</th>
            </tr>
          </thead>
          <tbody>
            {rep.captains.map((c, i) => (
              <tr key={c.captain} className="border-b border-line last:border-0">
                <td className="py-2.5 font-medium text-ink">
                  {i === 0 && <Crown size={13} className="mr-1.5 inline text-accent-text" />}
                  {c.captain}
                </td>
                <td className="num text-right text-ink-2">{c.my_gw_xpts.toFixed(1)}</td>
                <td className="num text-right text-ink-2">{c.league_eo.toFixed(0)}%</td>
                <td className="pl-6">
                  <ProbCell v={c.p_beat_rival_avg} />
                </td>
                <td className="pl-6">
                  <ProbCell v={c.p_top_score_gw} tone="s2" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function HeadToHead({ rep }: { rep: LeagueReport }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {rep.head_to_head.map((h) => (
        <div key={h.rival} className="rounded-xl bg-card-2 p-4 ring-1 ring-line">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[14px] font-medium text-ink">{h.rival}</div>
              <div className="text-[12px] text-muted">
                {h.gap_now === 0
                  ? 'Level on points'
                  : h.gap_now > 0
                    ? `You lead by ${h.gap_now}`
                    : `${-h.gap_now} points ahead of you`}{' '}
                · captain {h.captain}
              </div>
            </div>
            <div className="text-right">
              <div className="num text-[16px] font-semibold text-ink">{fmt.pct(h.p_outscore_this_gw)}</div>
              <div className="text-[11px] text-muted">to outscore this GW</div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Meter value={h.p_outscore_this_gw} tone={h.p_outscore_this_gw >= 0.5 ? 'good' : 'bad'} />
            <span className="num w-14 text-right text-[12px] text-ink-2">{fmt.signed(h.exp_margin_this_gw)} pts</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function RivalChips({ rep }: { rep: LeagueReport }) {
  const chips: Chip[] = ['wildcard', 'freehit', 'bboost', '3xc']
  return (
    <>
      <p className="mb-4 text-[13px] text-ink-2">
        Rivals with chips in hand can swing a gameweek. Plan cover before likely Bench Boost and Triple Captain weeks.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {rep.rival_chips.map((r) => (
          <div key={r.manager} className="rounded-xl bg-card-2 p-3.5 ring-1 ring-line">
            <div className="flex items-center justify-between">
              <span className="text-[13.5px] font-medium text-ink">{r.manager}</span>
              <span className="num text-[12px] text-muted">
                £{r.bank.toFixed(1)}m · {r.free_transfers} FT
              </span>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {chips.map((c) => {
                const n = r.chips_left[c]?.length ?? 0
                return (
                  <Badge key={c} tone={n ? 'accent' : 'neutral'} className={n ? '' : 'opacity-50'}>
                    {CHIP_SHORT[c]} ×{n}
                  </Badge>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

function ProbCell({ v, tone = 'accent' }: { v: number; tone?: 'accent' | 's2' }) {
  return (
    <div className="flex items-center gap-2">
      <Meter value={v} tone={tone} />
      <span className="num w-11 text-right font-medium text-ink">{fmt.pct(v)}</span>
    </div>
  )
}
