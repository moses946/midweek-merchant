import type { FixturesBundle } from './types'

export interface TickerCell {
  team: string
  gw: number
  opps: { opp: string; home: boolean }[]
  xg: number // expected goals scored (sum over the gameweek's fixtures)
  xga: number // expected goals conceded
  cs: number // clean-sheet probability (product over fixtures)
}

/** Team × gameweek matrix from the fixture lambdas; blanks have no fixtures. */
export function ticker(bundle: FixturesBundle, teams: string[], gws: number[]): Map<string, TickerCell[]> {
  const out = new Map<string, TickerCell[]>()
  for (const t of teams) {
    out.set(
      t,
      gws.map((gw) => ({ team: t, gw, opps: [], xg: 0, xga: 0, cs: 1 })),
    )
  }
  const idx = new Map(gws.map((g, i) => [g, i]))
  for (const f of bundle.fixtures) {
    const i = idx.get(f.gw)
    if (i === undefined) continue
    for (const [team, opp, lf, la, home] of [
      [f.home, f.away, f.lh, f.la, true],
      [f.away, f.home, f.la, f.lh, false],
    ] as const) {
      const cell = out.get(team)?.[i]
      if (!cell) continue
      cell.opps.push({ opp, home })
      cell.xg += lf
      cell.xga += la
      cell.cs *= Math.exp(-la)
    }
  }
  for (const cells of out.values()) for (const c of cells) if (!c.opps.length) c.cs = 0
  return out
}

/** Average over the first `n` gameweeks of a team's run. */
export function runSummary(cells: TickerCell[], n: number) {
  const run = cells.slice(0, n)
  const games = run.reduce((s, c) => s + c.opps.length, 0)
  return {
    xg: run.reduce((s, c) => s + c.xg, 0),
    cs: run.reduce((s, c) => s + c.cs * c.opps.length, 0),
    games,
  }
}
