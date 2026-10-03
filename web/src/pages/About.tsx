import {
  ArrowRight,
  BarChart3,
  Boxes,
  Calculator,
  CloudCog,
  Database,
  Dices,
  GitBranch,
  LineChart,
  Network,
  Server,
  ShieldCheck,
  Target,
  Timer,
  Trophy,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { GithubMark, Logo, PageHeader } from '../components/layout/Shell'
import { Badge, Card, CardHeader } from '../components/ui/primitives'
import { REPO_URL, useHindcast, useMeta, useModel } from '../lib/data'
import { fmt } from '../lib/format'

export default function About() {
  const meta = useMeta()
  const model = useModel()
  const past = useHindcast('2025-26')
  const all = model.data?.backtest?.metrics.filter((r) => r.subset === 'all players') ?? []
  const m = all.find((r) => r.predictor === 'model')
  const ep = all.find((r) => r.predictor.startsWith('FPL ep'))
  const hm = past.data?.summary.find((r) => r.pick === 'Model')
  const he = past.data?.summary.find((r) => r.pick === 'FPL ep')

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="How it works"
        description="Midweek Merchant is an end-to-end Fantasy Premier League decision system: a structural expected-points model, a mixed-integer optimiser, Monte Carlo strategy for mini-leagues and big weeks, and a scheduled pipeline that publishes everything you see here."
        actions={
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-xl bg-card px-3.5 py-2 text-[13px] font-medium text-ink ring-1 ring-line hover:bg-card-2"
          >
            <GithubMark /> View the source
          </a>
        }
      />

      <Card glow>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12 lg:items-center">
          <div className="lg:col-span-5">
            <Logo className="size-12" />
            <h2 className="mt-4 text-[24px] leading-tight font-semibold tracking-tight text-ink">
              Every number is a forecast you can check.
            </h2>
            <p className="mt-3 text-[14px] leading-relaxed text-ink-2">
              Projections are replayed blind against past gameweeks before they are trusted. The model only ever sees
              what was known before each deadline, and a test proves it: delete everything after the deadline and the
              picks do not change.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:col-span-7">
            <Proof
              value={hm && he ? fmt.signed(hm.mean_points - he.mean_points) : '–'}
              label="points a week over FPL's own prediction"
              sub={hm ? `Blind XIs across ${hm.gameweeks} gameweeks of 2025/26` : undefined}
            />
            <Proof
              value={hm?.beats_fpl_ep_pick != null ? fmt.pct(hm.beats_fpl_ep_pick) : '–'}
              label="of gameweeks won head to head"
              sub="Same rules, same pre-deadline information"
            />
            <Proof
              value={m && ep ? `${((1 - m.rmse / ep.rmse) * 100).toFixed(0)}%` : '–'}
              label="lower error than FPL's ep"
              sub={m ? `RMSE ${m.rmse.toFixed(2)} on ${fmt.compact(m.n)} player-gameweeks` : undefined}
            />
            <Proof
              value={meta.data ? String(meta.data.players) : '–'}
              label="players projected"
              sub="Over the next eight gameweeks, refreshed every six hours"
            />
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          eyebrow="Architecture"
          title="From raw data to a decision"
          hint="Python does the data and modelling; the React app is a static front end over a published JSON bundle; a small FastAPI service re-plans any team on demand."
        />
        <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[1fr_auto_1.2fr_auto_1fr_auto_1fr]">
          <Stage
            icon={<Database size={16} />}
            title="Sources"
            items={['FPL API', 'Historical match data and xG', 'Betting odds', 'Point-in-time FPL snapshots']}
          />
          <Arrow />
          <Stage
            icon={<Calculator size={16} />}
            title="Python models"
            accent
            items={[
              'Dixon–Coles team strength',
              'Minutes and availability',
              'Player event rates',
              'Analytic xPts and correlated Monte Carlo',
            ]}
          />
          <Arrow />
          <Stage
            icon={<Boxes size={16} />}
            title="Optimise and strategise"
            items={['MILP transfer planner (HiGHS)', 'Chip timing and 100+ week chaser', 'Mini-league win probability']}
          />
          <Arrow />
          <Stage
            icon={<LineChart size={16} />}
            title="Deliver"
            items={[
              'GitHub Actions every 6 hours',
              'JSON bundle on a data branch',
              'React dashboard',
              'FastAPI live planner',
            ]}
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:gap-5 xl:grid-cols-3">
        <Feature icon={<Network size={18} />} title="Team strength">
          A time-decayed, ridge-regularised Poisson model of goals and xG (Dixon–Coles, with a low-score correction),
          including Championship matches for promoted clubs. Bookmaker odds with the margin removed are blended into the
          nearest fixtures.
        </Feature>
        <Feature icon={<Timer size={18} />} title="Minutes">
          Recency-weighted rates of starting, lasting 60 minutes and coming off the bench. FPL status, chance of
          playing, “expected back” dates and loan rules set availability for each fixture.
        </Feature>
        <Feature icon={<BarChart3 size={18} />} title="Player rates">
          Each player&apos;s share of team xG and xA with empirical-Bayes shrinkage towards price and position priors.
          Defensive contributions use a negative-binomial count model; saves, cards and bonus are modelled too.
        </Feature>
        <Feature icon={<Dices size={18} />} title="Simulation">
          A correlated Monte Carlo draws scorelines and hands goals and assists to the players on the pitch, so
          teammates and opponents move together. Its spread is calibrated by CRPS on blind hindcasts.
        </Feature>
        <Feature icon={<Boxes size={18} />} title="Optimiser">
          A mixed-integer program chooses squad, lineup, captain, bench and transfers at selling prices, banks free
          transfers up to five, and schedules all four chips under the 2026/27 rules (two sets, one chip a week).
        </Feature>
        <Feature icon={<Trophy size={18} />} title="Mini-league strategy">
          Your gap to a rival changes in expectation only through your own points, so ownership matters through
          variance. Every plan is scored against rivals&apos; squads on shared simulations to rank them by chance of
          winning.
        </Feature>
        <Feature icon={<Target size={18} />} title="Chasing a big week">
          A different question from the planner: the best chance of at least one gameweek above a target. Chip schedules
          and same-team stacks are scored on tail probabilities, with the captain picked for upside.
        </Feature>
        <Feature icon={<ShieldCheck size={18} />} title="No leakage">
          Backtests and hindcasts use only point-in-time data. A test deletes every statistic from the target gameweek
          onwards and asserts the predictions and picked XI are unchanged, and fails if a leak is introduced.
        </Feature>
        <Feature icon={<CloudCog size={18} />} title="Automation">
          A GitHub Actions workflow ingests, forecasts, re-plans and re-runs the hindcasts every six hours, then
          publishes a single-commit data branch. This dashboard reads it directly; no database, no servers to babysit.
        </Feature>
      </div>

      <Card>
        <CardHeader eyebrow="Stack" title="Built with" />
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <StackGroup
            icon={<Calculator size={15} />}
            title="Modelling"
            items={['Python 3.11', 'pandas', 'NumPy', 'SciPy', 'HiGHS (MILP)', 'pytest']}
          />
          <StackGroup
            icon={<Server size={15} />}
            title="Services"
            items={['FastAPI', 'Typer CLI', 'GitHub Actions', 'Streamlit (analyst console)']}
          />
          <StackGroup
            icon={<GitBranch size={15} />}
            title="Front end"
            items={['React 19', 'TypeScript', 'Vite', 'Tailwind CSS v4', 'Recharts', 'TanStack Query']}
          />
        </div>
      </Card>
    </div>
  )
}

function Proof({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="rounded-2xl bg-card-2 p-4 ring-1 ring-line">
      <div className="text-[30px] leading-none font-semibold tracking-tight text-ink">{value}</div>
      <div className="mt-2 text-[13px] font-medium text-ink-2">{label}</div>
      {sub && <div className="mt-1 text-[12px] text-muted">{sub}</div>}
    </div>
  )
}

function Stage({ icon, title, items, accent }: { icon: ReactNode; title: string; items: string[]; accent?: boolean }) {
  return (
    <div
      className={
        accent ? 'rounded-2xl bg-accent-soft p-4 ring-1 ring-accent/40' : 'rounded-2xl bg-card-2 p-4 ring-1 ring-line'
      }
    >
      <div className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
        <span className={accent ? 'text-accent-text' : 'text-muted'}>{icon}</span>
        {title}
      </div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {items.map((i) => (
          <li key={i} className="flex items-start gap-2 text-[12.5px] leading-snug text-ink-2">
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-muted" />
            {i}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Arrow() {
  return (
    <div className="flex items-center justify-center text-muted">
      <ArrowRight size={18} className="rotate-90 lg:rotate-0" />
    </div>
  )
}

function Feature({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card>
      <div className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent-text ring-1 ring-accent/30">
        {icon}
      </div>
      <h3 className="mt-4 text-[15px] font-semibold tracking-tight text-ink">{title}</h3>
      <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{children}</p>
    </Card>
  )
}

function StackGroup({ icon, title, items }: { icon: ReactNode; title: string; items: string[] }) {
  return (
    <div>
      <div className="mb-2.5 flex items-center gap-2 text-[13px] font-medium text-ink">
        <span className="text-muted">{icon}</span>
        {title}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((i) => (
          <Badge key={i}>{i}</Badge>
        ))}
      </div>
    </div>
  )
}
