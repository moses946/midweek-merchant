import type { TeamPlan } from './types'

// Optional Python API (src/midweek_merchant/api.py) for planning any team on demand.
export const API_URL: string | null = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || null

export interface PlanRequest {
  team_id: number
  horizon: number
  max_hits: number
  roll: boolean
}

export async function requestPlan(req: PlanRequest, signal?: AbortSignal): Promise<TeamPlan> {
  if (!API_URL) throw new Error('Live planning is not configured')
  const res = await fetch(`${API_URL}/api/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`
    throw new Error(detail)
  }
  return body as TeamPlan
}
