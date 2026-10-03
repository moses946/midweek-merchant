import clsx from 'clsx'
import { Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { kitUrl, teamColors } from '../../lib/teams'

export function Card({
  children,
  className,
  pad = true,
  glow = false,
}: {
  children?: ReactNode
  className?: string
  pad?: boolean
  glow?: boolean
}) {
  return (
    <section className={clsx('card relative overflow-hidden', pad && 'p-5 sm:p-6', className)}>
      {glow && (
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: 'var(--glow)' }} />
      )}
      <div className="relative">{children}</div>
    </section>
  )
}

export function CardHeader({
  title,
  eyebrow,
  hint,
  action,
  className,
}: {
  title: ReactNode
  eyebrow?: ReactNode
  hint?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('mb-4 flex items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {hint && <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{hint}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function Stat({
  label,
  value,
  sub,
  delta,
  icon,
  accent = false,
  className,
}: {
  label: ReactNode
  value: ReactNode
  sub?: ReactNode
  delta?: { value: string; good: boolean | null }
  icon?: ReactNode
  accent?: boolean
  className?: string
}) {
  return (
    <div className={clsx('card relative overflow-hidden p-5', className)}>
      {accent && (
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: 'var(--glow)' }} />
      )}
      <div className="relative">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-medium text-ink-2">{label}</span>
          {icon && <span className="text-muted">{icon}</span>}
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-[28px] leading-none font-semibold tracking-tight text-ink">{value}</span>
          {delta && (
            <span
              className={clsx(
                'rounded-md px-1.5 py-0.5 text-[12px] font-medium',
                delta.good === null
                  ? 'bg-card-2 text-ink-2'
                  : delta.good
                    ? 'bg-good-soft text-good'
                    : 'bg-bad-soft text-bad',
              )}
            >
              {delta.value}
            </span>
          )}
        </div>
        {sub && <div className="mt-2 text-[12.5px] leading-snug text-muted">{sub}</div>}
      </div>
    </div>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: 'neutral' | 'accent' | 'good' | 'bad' | 'warn' | 'solid'
  className?: string
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap',
        tone === 'neutral' && 'bg-card-2 text-ink-2 ring-1 ring-line',
        tone === 'accent' && 'bg-accent-soft text-accent-text ring-1 ring-accent/25',
        tone === 'good' && 'bg-good-soft text-good',
        tone === 'bad' && 'bg-bad-soft text-bad',
        tone === 'warn' && 'bg-warn-soft text-warn',
        tone === 'solid' && 'bg-accent text-accent-ink',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  size = 'md',
  className,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode }[]
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <div
      role="tablist"
      className={clsx('inline-flex max-w-full overflow-x-auto rounded-xl bg-card-2 p-1 ring-1 ring-line', className)}
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'shrink-0 rounded-lg font-medium whitespace-nowrap transition-colors',
            size === 'sm' ? 'px-2.5 py-1 text-[12px]' : 'px-3 py-1.5 text-[13px]',
            o.value === value ? 'bg-card text-ink shadow-card ring-1 ring-line' : 'text-ink-2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />
}

export function Empty({ title, children, icon }: { title: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="grid size-10 place-items-center rounded-full bg-card-2 text-muted ring-1 ring-line">
        {icon ?? <Info size={18} />}
      </div>
      <div className="text-[14px] font-medium text-ink">{title}</div>
      {children && <div className="max-w-md text-[13px] leading-relaxed text-ink-2">{children}</div>}
    </div>
  )
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={clsx('text-[12.5px] leading-relaxed text-muted', className)}>{children}</p>
}

/** The club's kit (official FPL image), falling back to a two-tone shirt drawn in its colours. */
export function Jersey({
  team,
  pos,
  size = 28,
  className,
}: {
  team: string
  pos?: string
  size?: number
  className?: string
}) {
  const src = kitUrl(team, pos === 'GKP')
  const [failed, setFailed] = useState<string | null>(null)
  if (src && failed !== src) {
    const w = Math.round(size * 0.76) // kit images are 220 × 290
    return (
      <img
        src={src}
        alt=""
        aria-hidden
        width={w}
        height={size}
        loading="lazy"
        decoding="async"
        draggable={false}
        onError={() => setFailed(src)}
        className={clsx('shrink-0 object-contain select-none', className)}
        style={{ width: w, height: size }}
      />
    )
  }
  const [body, trim] = teamColors(team)
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={clsx('shrink-0', className)} aria-hidden>
      <path
        d="M11 3.5 6 5.6 1.8 11.4l4.4 3.3 2.1-2.2V29h15.4V12.5l2.1 2.2 4.4-3.3L26 5.6l-5-2.1c-.6 2-2.6 3.3-5 3.3s-4.4-1.3-5-3.3Z"
        fill={body}
        stroke="rgba(0,0,0,0.35)"
        strokeWidth="0.8"
        strokeLinejoin="round"
      />
      <path d="M6 5.6 1.8 11.4l4.4 3.3 2.1-2.2V8.3Z M26 5.6l4.2 5.8-4.4 3.3-2.1-2.2V8.3Z" fill={trim} opacity="0.95" />
      <path d="M11 3.5c.6 2 2.6 3.3 5 3.3s4.4-1.3 5-3.3" fill="none" stroke={trim} strokeWidth="1.4" />
    </svg>
  )
}

export function TeamTag({ team, className }: { team: string; className?: string }) {
  const [body] = teamColors(team)
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-2', className)}>
      <span className="size-2 rounded-full ring-1 ring-black/20" style={{ background: body }} />
      {team}
    </span>
  )
}

export function PosTag({ pos }: { pos: string }) {
  return (
    <span className="inline-flex w-9 justify-center rounded-md bg-card-2 py-0.5 font-mono text-[10.5px] font-medium tracking-wide text-ink-2 ring-1 ring-line">
      {pos}
    </span>
  )
}

/** Horizontal probability/magnitude bar with the value as text beside it (never colour alone). */
export function Meter({
  value,
  max = 1,
  tone = 'accent',
  className,
}: {
  value: number
  max?: number
  tone?: 'accent' | 's2' | 'muted' | 'good' | 'bad'
  className?: string
}) {
  const pct = Math.max(0, Math.min(1, value / (max || 1))) * 100
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-card-3', className)}>
      <div
        className={clsx(
          'h-full rounded-full transition-[width] duration-500',
          tone === 'accent' && 'bg-accent',
          tone === 's2' && 'bg-s2',
          tone === 'muted' && 'bg-muted',
          tone === 'good' && 'bg-good',
          tone === 'bad' && 'bg-bad',
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function Dot({ color }: { color: string }) {
  return <span className="inline-block size-2.5 shrink-0 rounded-full" style={{ background: color }} />
}

export function XpCell({ v }: { v: number | null }) {
  if (v == null) return <span className="text-muted">–</span>
  // Lightness carries magnitude; the number is always printed, so colour is never the only cue.
  const a = Math.max(0, Math.min(1, v / 7))
  return (
    <span
      className="inline-block min-w-[44px] rounded-md px-1.5 py-0.5 text-right font-medium text-ink"
      style={{ background: `color-mix(in oklab, var(--s1) ${Math.round(a * 34)}%, transparent)` }}
    >
      {v.toFixed(1)}
    </span>
  )
}
