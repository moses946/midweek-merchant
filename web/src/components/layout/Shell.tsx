import clsx from 'clsx'
import {
  Activity,
  BookOpen,
  CalendarDays,
  History,
  LayoutDashboard,
  Menu,
  Moon,
  Shirt,
  Sparkles,
  Sun,
  Trophy,
  Users,
  X,
  Zap,
} from 'lucide-react'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { REPO_URL, useMeta } from '../../lib/data'
import { relativeTime } from '../../lib/format'
import { countdownParts, setTheme, useNow, useTheme } from '../../lib/hooks'
import { Skeleton } from '../ui/primitives'

const NAV = [
  {
    group: 'Gameweek',
    items: [
      { to: '/', label: 'Overview', icon: LayoutDashboard },
      { to: '/team', label: 'My team', icon: Shirt },
      { to: '/players', label: 'Players', icon: Users },
      { to: '/fixtures', label: 'Fixtures', icon: CalendarDays },
    ],
  },
  {
    group: 'Strategy',
    items: [
      { to: '/best-xi', label: 'Best XI', icon: Sparkles },
      { to: '/chips', label: 'Chips', icon: Zap },
      { to: '/league', label: 'Mini-league', icon: Trophy },
    ],
  },
  {
    group: 'Model',
    items: [
      { to: '/track-record', label: 'Track record', icon: History },
      { to: '/model', label: 'Model health', icon: Activity },
      { to: '/about', label: 'How it works', icon: BookOpen },
    ],
  },
]

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="var(--accent)" />
      <path d="M15 46V19l8.5 0 8.5 15 8.5-15H49v27h-7.5V31.5L34.6 43h-5.2L22.5 31.5V46z" fill="var(--accent-ink)" />
    </svg>
  )
}

export function GithubMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-3 px-2">
      <Logo className="size-9 shrink-0 drop-shadow-[0_6px_18px_rgba(197,240,60,0.25)]" />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-ink">Midweek Merchant</div>
        <div className="font-mono text-[10.5px] tracking-wider text-muted uppercase">FPL intelligence</div>
      </div>
    </NavLink>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-6">
      {NAV.map((g) => (
        <div key={g.group}>
          <div className="eyebrow mb-2 px-3">{g.group}</div>
          <ul className="flex flex-col gap-0.5">
            {g.items.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    clsx(
                      'group flex items-center gap-3 rounded-xl px-3 py-2 text-[13.5px] font-medium transition-colors',
                      isActive ? 'bg-card-2 text-ink ring-1 ring-line' : 'text-ink-2 hover:bg-card-2/60 hover:text-ink',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        size={17}
                        strokeWidth={isActive ? 2.2 : 1.8}
                        className={isActive ? 'text-accent-text' : 'text-muted group-hover:text-ink-2'}
                      />
                      {label}
                      {isActive && <span className="ml-auto size-1.5 rounded-full bg-accent" />}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function DataFooter() {
  const meta = useMeta()
  return (
    <div className="rounded-2xl bg-card p-3.5 ring-1 ring-line">
      <div className="flex items-center gap-2">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-50" />
          <span className="relative inline-flex size-2 rounded-full bg-accent" />
        </span>
        <span className="text-[12.5px] font-medium text-ink">Live data</span>
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
        {meta.data
          ? `Forecast refreshed ${relativeTime(meta.data.generated_at)}. Pipeline runs every 6 hours.`
          : 'Loading the latest forecast…'}
      </p>
      <a
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        className="mt-3 inline-flex items-center gap-2 text-[12px] font-medium text-ink-2 hover:text-ink"
      >
        <GithubMark size={14} /> Source on GitHub
      </a>
    </div>
  )
}

function Deadline() {
  const meta = useMeta()
  const now = useNow(1000)
  if (!meta.data) return <Skeleton className="h-9 w-48" />
  const c = countdownParts(meta.data.deadline, now)
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-card px-3 py-1.5 ring-1 ring-line">
      <span className="rounded-md bg-accent px-1.5 py-0.5 font-mono text-[11px] font-semibold text-accent-ink">
        GW{meta.data.next_gw}
      </span>
      <span className="text-[12.5px] text-ink-2">
        {c && !c.passed ? (
          <>
            <span className="hidden sm:inline">Deadline in </span>
            <span className="num font-medium text-ink">
              {c.d}d {String(c.h).padStart(2, '0')}h {String(c.m).padStart(2, '0')}m
              <span className="hidden md:inline"> {String(c.s).padStart(2, '0')}s</span>
            </span>
          </>
        ) : (
          'Deadline passed'
        )}
      </span>
    </div>
  )
}

function ThemeToggle() {
  const theme = useTheme()
  return (
    <button
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="grid size-9 place-items-center rounded-xl bg-card text-ink-2 ring-1 ring-line transition-colors hover:text-ink"
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
    >
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}

function currentTitle(pathname: string): string {
  for (const g of NAV) for (const i of g.items) if (i.to === pathname) return i.label
  return 'Overview'
}

export function Shell() {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const title = currentTitle(pathname)
  useEffect(() => {
    document.title = `${title} · Midweek Merchant`
    window.scrollTo({ top: 0 })
  }, [title])

  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[264px] flex-col gap-8 border-r border-line bg-bg-elev px-4 py-6 lg:flex">
        <Brand />
        <div className="flex-1 overflow-y-auto">
          <NavList />
        </div>
        <DataFooter />
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="rise absolute inset-y-0 left-0 flex w-[280px] flex-col gap-8 border-r border-line bg-bg-elev px-4 py-6">
            <div className="flex items-center justify-between">
              <Brand />
              <button onClick={() => setOpen(false)} className="text-ink-2" aria-label="Close menu">
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <NavList onNavigate={() => setOpen(false)} />
            </div>
            <DataFooter />
          </aside>
        </div>
      )}

      <div className="lg:pl-[264px]">
        <header className="sticky top-[env(safe-area-inset-top,0px)] z-20 border-b border-line bg-bg/80 backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              className="grid size-9 place-items-center rounded-xl bg-card text-ink-2 ring-1 ring-line lg:hidden"
              onClick={() => setOpen(true)}
              aria-label="Open menu"
            >
              <Menu size={18} />
            </button>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[15px] font-semibold tracking-tight">{title}</div>
            </div>
            <Deadline />
            <ThemeToggle />
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              aria-label="Source code on GitHub"
              className="hidden size-9 place-items-center rounded-xl bg-card text-ink-2 ring-1 ring-line hover:text-ink sm:grid"
            >
              <GithubMark />
            </a>
          </div>
        </header>
        <main className="mx-auto max-w-[1440px] px-4 pt-6 pb-16 sm:px-6 lg:px-8 lg:pt-8">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-10 w-72" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-80" />
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-3xl">
        <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-ink sm:text-[30px]">{title}</h1>
        {description && <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
