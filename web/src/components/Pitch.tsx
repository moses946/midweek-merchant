import clsx from 'clsx'
import type { PlanPlayer, PlanWeek, Position } from '../lib/types'
import { Jersey } from './ui/primitives'

const ROWS: Position[] = ['GKP', 'DEF', 'MID', 'FWD']

function PitchLines() {
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 size-full"
      viewBox="0 0 100 140"
      preserveAspectRatio="none"
      fill="none"
      stroke="var(--pitch-line)"
      strokeWidth="0.45"
      vectorEffect="non-scaling-stroke"
    >
      <rect x="3" y="3" width="94" height="134" rx="1.5" />
      <line x1="3" y1="70" x2="97" y2="70" />
      <circle cx="50" cy="70" r="11" />
      <circle cx="50" cy="70" r="0.8" fill="var(--pitch-line)" />
      <rect x="24" y="3" width="52" height="21" />
      <rect x="38" y="3" width="24" height="8" />
      <path d="M41 24a10 10 0 0 0 18 0" />
      <rect x="24" y="116" width="52" height="21" />
      <rect x="38" y="129" width="24" height="8" />
      <path d="M41 116a10 10 0 0 1 18 0" />
    </svg>
  )
}

function Armband({ label }: { label: string }) {
  return (
    <span
      className={clsx(
        'absolute -top-1 -right-2 grid h-[18px] min-w-[18px] place-items-center rounded-full px-1 font-mono text-[10px] font-bold ring-2 ring-[var(--pitch-a)]',
        label === 'V' ? 'bg-ink text-bg' : 'bg-accent text-accent-ink',
      )}
    >
      {label}
    </span>
  )
}

function PlayerToken({
  p,
  badge,
  isNew,
  mode,
}: {
  p: PlanPlayer
  badge?: string
  isNew?: boolean
  mode: 'xpts' | 'actual'
}) {
  const dnp = mode === 'actual' && p.minutes === 0
  return (
    <div className="group flex w-[76px] flex-col items-center sm:w-[92px]">
      <div className="relative">
        {isNew && (
          <span className="absolute -top-1 -left-3 rounded-full bg-accent px-1.5 py-px font-mono text-[9px] font-bold text-accent-ink ring-2 ring-[var(--pitch-a)]">
            IN
          </span>
        )}
        <Jersey
          team={p.team}
          pos={p.position}
          size={54}
          className="drop-shadow-[0_6px_10px_rgba(0,0,0,0.35)] transition-transform group-hover:-translate-y-0.5"
        />
        {badge && <Armband label={badge} />}
      </div>
      <div
        className={clsx(
          'mt-1.5 w-full truncate rounded-md px-1.5 py-[3px] text-center text-[11.5px] font-semibold',
          isNew ? 'bg-accent text-accent-ink' : 'bg-ink text-bg',
        )}
        title={`${p.name} · ${p.team} · £${p.price.toFixed(1)}m`}
      >
        {p.name}
      </div>
      <div className="mt-0.5 w-full truncate rounded-md bg-card/90 px-1 py-[2px] text-center text-[10.5px] text-ink-2 ring-1 ring-line backdrop-blur">
        {mode === 'actual' ? (
          <span className="num">
            {p.xpts.toFixed(1)} → <b className={dnp ? 'text-muted' : 'text-ink'}>{dnp ? 'DNP' : p.actual}</b>
          </span>
        ) : (
          <span className="num">
            <b className="font-semibold text-ink">{p.xpts.toFixed(1)}</b> · {p.fixture}
          </span>
        )}
      </div>
    </div>
  )
}

export function Pitch({
  week,
  highlight,
  mode = 'xpts',
  compact = false,
}: {
  week: PlanWeek
  highlight?: Set<number>
  mode?: 'xpts' | 'actual'
  compact?: boolean
}) {
  const cap = week.captain?.element
  const vice = week.vice?.element
  const triple = week.chip === '3xc'
  const badge = (e: number) => (e === cap ? (triple ? 'TC' : 'C') : e === vice ? 'V' : undefined)
  const bench = week.bench ?? []
  return (
    <div>
      <div
        className={clsx(
          'pitch relative overflow-hidden rounded-2xl ring-1 ring-line',
          compact ? 'px-1 py-4' : 'px-2 py-6 sm:py-8',
        )}
      >
        <PitchLines />
        <div className={clsx('relative flex flex-col', compact ? 'gap-4' : 'gap-6 sm:gap-8')}>
          {ROWS.map((pos) => {
            const players = week.lineup.filter((p) => p.position === pos)
            if (!players.length) return null
            return (
              <div key={pos} className="flex justify-center gap-1 sm:gap-3">
                {players.map((p) => (
                  <PlayerToken
                    key={p.element}
                    p={p}
                    badge={badge(p.element)}
                    isNew={highlight?.has(p.element)}
                    mode={mode}
                  />
                ))}
              </div>
            )
          })}
        </div>
      </div>
      <div className="mt-3 rounded-2xl bg-card-2 px-3 py-3 ring-1 ring-line">
        <div className="eyebrow mb-2 px-1">
          {week.chip === 'bboost' ? 'Bench (Bench Boost: all 15 score)' : 'Bench, in order'}
        </div>
        <div className="flex justify-around gap-1">
          {bench.map((p) => (
            <PlayerToken key={p.element} p={p} isNew={highlight?.has(p.element)} mode={mode} />
          ))}
        </div>
      </div>
    </div>
  )
}
