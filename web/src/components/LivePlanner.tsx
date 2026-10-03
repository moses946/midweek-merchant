import clsx from 'clsx'
import { Loader2, RotateCcw, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { API_URL, requestPlan } from '../lib/live'
import type { TeamPlan } from '../lib/types'
import { Card, Segmented } from './ui/primitives'

/** Re-plan any FPL team through the Python API. Hidden when no API is configured. */
export function LivePlanner({
  onPlan,
  onReset,
  active,
}: {
  onPlan: (p: TeamPlan) => void
  onReset: () => void
  active: boolean
}) {
  const [teamId, setTeamId] = useState('')
  const [horizon, setHorizon] = useState(6)
  const [maxHits, setMaxHits] = useState(1)
  const [roll, setRoll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const ctrl = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!busy) return
    const t0 = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 250)
    return () => clearInterval(id)
  }, [busy])
  useEffect(() => () => ctrl.current?.abort(), [])

  if (!API_URL) return null

  async function solve() {
    const id = Number(teamId)
    if (!Number.isInteger(id) || id <= 0) {
      setError('Enter the number from your FPL points page URL: /entry/<ID>/event/…')
      return
    }
    ctrl.current?.abort()
    ctrl.current = new AbortController()
    setBusy(true)
    setError(null)
    try {
      onPlan(await requestPlan({ team_id: id, horizon, max_hits: maxHits, roll }, ctrl.current.signal))
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card glow>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end">
        <div className="xl:w-[300px]">
          <div className="flex items-center gap-2 text-[15px] font-semibold text-ink">
            <Sparkles size={16} className="text-accent-text" /> Plan any FPL team
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
            Rebuilds the squad from public FPL data and solves a fresh plan on the Python API.
          </p>
        </div>
        <form
          className="flex flex-1 flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void solve()
          }}
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-[11.5px] text-muted">Team ID</span>
            <input
              inputMode="numeric"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value.replace(/\D/g, ''))}
              placeholder="e.g. 3649661"
              className="h-10 w-[150px] rounded-xl bg-card-2 px-3 text-[14px] text-ink ring-1 ring-line outline-none placeholder:text-muted focus:ring-accent/60"
            />
          </label>
          <div className="flex flex-col gap-1.5">
            <span className="text-[11.5px] text-muted">Horizon</span>
            <Segmented
              value={horizon}
              onChange={setHorizon}
              options={[4, 6, 8].map((v) => ({ value: v, label: `${v} GWs` }))}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[11.5px] text-muted">Max hits per GW</span>
            <Segmented value={maxHits} onChange={setMaxHits} options={[0, 1, 2].map((v) => ({ value: v, label: v }))} />
          </div>
          <label className="flex h-10 cursor-pointer items-center gap-2 rounded-xl bg-card-2 px-3 text-[13px] text-ink-2 ring-1 ring-line">
            <input
              type="checkbox"
              checked={roll}
              onChange={(e) => setRoll(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            No transfer this week
          </label>
          <button
            type="submit"
            disabled={busy}
            className={clsx(
              'inline-flex h-10 items-center gap-2 rounded-xl bg-accent px-4 text-[13px] font-semibold text-accent-ink transition-opacity',
              busy && 'opacity-80',
            )}
          >
            {busy ? (
              <>
                <Loader2 size={15} className="animate-spin" /> Solving… {elapsed}s
              </>
            ) : (
              'Solve plan'
            )}
          </button>
          {active && (
            <button
              type="button"
              onClick={onReset}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:text-ink"
            >
              <RotateCcw size={14} /> Scheduled plan
            </button>
          )}
        </form>
      </div>
      {error && <p className="mt-3 text-[13px] text-bad">{error}</p>}
      {busy && (
        <p className="mt-3 text-[12.5px] text-muted">
          Reading the squad and transfer history from FPL, then solving a mixed-integer program over the player pool.
          Usually 10–30 seconds.
        </p>
      )}
    </Card>
  )
}
