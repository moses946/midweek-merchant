import { useEffect, useState, useSyncExternalStore } from 'react'

type Theme = 'dark' | 'light'

function readTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

const listeners = new Set<() => void>()

export function setTheme(t: Theme) {
  document.documentElement.dataset.theme = t
  try {
    localStorage.setItem('mm-theme', t)
  } catch {
    /* storage blocked: the toggle still works for this visit */
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'dark' ? '#07090b' : '#f3f4f0')
  listeners.forEach((l) => l())
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    readTheme,
    () => 'dark',
  )
}

/** Re-render every `ms` milliseconds (for countdowns). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

export function countdownParts(target: string | null, now: number) {
  if (!target) return null
  let s = Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000))
  const d = Math.floor(s / 86400)
  s -= d * 86400
  const h = Math.floor(s / 3600)
  s -= h * 3600
  const m = Math.floor(s / 60)
  return { d, h, m, s: s - m * 60, passed: new Date(target).getTime() <= now }
}
