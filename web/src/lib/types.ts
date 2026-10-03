// Shapes of the JSON bundle written by `mm export-web` (src/midweek_merchant/web_export.py).

export type Position = 'GKP' | 'DEF' | 'MID' | 'FWD'
export type Chip = 'wildcard' | 'freehit' | 'bboost' | '3xc'

export interface EventRow {
  gw: number
  deadline: string
  finished: boolean
  average: number | null
  highest: number | null
}

export interface TeamRow {
  name: string
  short: string
  code?: number | null
  attack: number | null
  defence: number | null
  xg_for: number | null
  xg_against: number | null
}

export interface Meta {
  version: number
  season: string
  generated_at: string
  exported_at: string
  next_gw: number
  deadline: string | null
  gws: number[]
  team_id: number | null
  league_id: number | null
  players: number
  events: EventRow[]
  teams: TeamRow[]
  files: {
    players: string
    fixtures: string
    best_squads?: string
    plan?: string
    ceiling?: string
    league?: string
    hindcast: Record<string, string>
    model: string
  }
}

export interface Player {
  id: number
  name: string
  full: string
  pos: Position
  team: string
  price: number
  status: string
  news: string
  chance: number | null
  own: number | null
  form: number | null
  pts: number
  ep: number | null
  pcp: number | null
  pcn: number | null
  tin: number
  tout: number
  xp: (number | null)[]
  fx: string[]
  xmins: (number | null)[]
  next: {
    p_start: number | null
    xg: number | null
    xa: number | null
    cs: number | null
    breakdown: Record<'app' | 'goals' | 'assists' | 'cs' | 'gc' | 'saves' | 'dc' | 'bonus' | 'cards', number | null>
  }
}

export interface Fixture {
  gw: number
  home: string
  away: string
  lh: number
  la: number
  kickoff: string | null
  market: boolean
}

export interface FixturesBundle {
  fixtures: Fixture[]
  calendar: { gw: number; blank: string[]; double: string[] }[]
  unscheduled: number
}

export interface PlanPlayer {
  element: number
  name: string
  team: string
  position: Position
  price: number
  xpts: number
  fixture: string
  // hindcast cards only
  actual?: number
  minutes?: number
}

export interface PlanWeek {
  gw: number
  chip: Chip | null
  xpts: number
  hits: number
  free_transfers: number
  bank: number
  transfers_in: PlanPlayer[]
  transfers_out: PlanPlayer[]
  lineup: PlanPlayer[]
  bench: PlanPlayer[]
  captain: PlanPlayer
  vice: PlanPlayer
  sim?: { mean: number; p_target: number; p90: number; p99: number }
  score?: { points: number; captain: string; captain_points: number; captain_played: boolean }
  predicted?: number
}

export interface SquadEntry {
  element: number
  name: string
  position: Position
  team: string
  purchase_price: number
  now_cost: number
  selling_price: number
}

export interface TeamState {
  entry_id: number
  name: string
  next_gw: number
  squad: SquadEntry[]
  bank: number
  free_transfers: number
  chips_available: Partial<Record<Chip, number[]>>
  chips_used: { event: number; name: string }[]
  total_points: number | null
  overall_rank: number | null
  last_gw_points: number | null
  notes: string[]
  squad_value: number
}

export interface ChipReport {
  baseline_xpts: number
  quick: { gw: number; bboost: number | null; '3xc': number | null; freehit: number | null; planned_xpts: number }[]
  exact: { chip: Chip; gw: number; total_xpts: number; gain: number; status: string }[]
  option_values: Record<Chip, number>
  chips_available: Partial<Record<Chip, number[]>>
}

export interface TeamPlan {
  state: TeamState
  status: string
  objective?: number
  total_xpts: number
  weeks: PlanWeek[]
  chips?: ChipReport
}

export interface BestSquads {
  per_gw: Record<string, PlanWeek>
  wildcard: { total_xpts: number; weeks: PlanWeek[] }
  budget: number
}

export interface CeilingRow {
  plan: number
  label: string
  p_any: number
  p_any_raw: number
  e_best_week: number
  p90_best_week: number
  p99_best_week: number
  e_total: number
  xpts_horizon: number
  chips_kept_value: number
  cost_vs_best: number
  [k: `p_gw${number}`]: number
}

export interface CeilingReport {
  target: number
  target_gws: number[]
  horizon_gws: number[]
  n_sims: number
  table: CeilingRow[]
  best: number
  reference: number
  plans: Record<string, { label: string; total_xpts: number; weeks: PlanWeek[] }>
  scale: number
  calibration?: {
    scale: number
    gameweeks: number
    seasons: string[]
    fitted: { n80_expected: number; n80_observed: number; n100_expected: number; n100_observed: number }
  }
}

export interface LeagueReport {
  league: { id: number; name: string }
  gws: number[]
  me: string
  advice: string
  z: number
  standings: {
    manager: string
    now: number
    projected: number
    p_lead_after_horizon: number
    p_win_league: number
    is_me: boolean
  }[]
  eo: {
    element: number
    name: string
    team: string
    position: Position
    xpts: number
    league_eo: number
    my_mult: number
    net_exposure: number
    role: string
  }[]
  plans: {
    option: number
    type: string
    this_week: string
    hits: number
    captain: string
    chip: string
    xpts_horizon: number
    mean_rank_horizon: number
    p_first_horizon: number
    p_first_season: number
  }[]
  captains: {
    captain: string
    my_gw_xpts: number
    league_eo: number
    p_beat_rival_avg: number
    p_top_score_gw: number
    p_lead_after_gw: number
  }[]
  head_to_head: {
    rival: string
    gap_now: number
    p_outscore_this_gw: number
    exp_margin_this_gw: number
    captain: string
  }[]
  plan_weeks: PlanWeek[][] // one list of weeks per candidate plan
  best_plan: number
  rival_chips: {
    manager: string
    chips_left: Partial<Record<Chip, number[]>>
    bank: number
    free_transfers: number
  }[]
}

export type PickKey = 'model' | 'fpl_ep' | 'form' | 'hindsight'

export interface HindcastSummaryRow {
  pick: string
  gameweeks: number
  mean_points: number
  total_points: number
  mean_captain_points: number
  beats_average_manager: number | null
  beats_fpl_ep_pick: number | null
  share_of_hindsight: number | null
}

export interface HindcastWeek {
  season: string
  gw: number
  deadline: string
  snapshot_used: boolean
  average_manager: number | null
  highest_manager: number | null
  picks: Partial<Record<PickKey, PlanWeek>>
  scores: Partial<Record<PickKey, number>>
}

export interface Hindcast {
  season: string
  generated_at: string
  gameweeks: HindcastWeek[]
  summary: HindcastSummaryRow[]
}

export interface ModelBundle {
  backtest: {
    season: string
    generated_at: string
    gws: number[]
    metrics: {
      subset: string
      predictor: string
      n: number
      rmse: number
      mae: number
      bias: number
      spearman_within_pos: number
    }[]
    calibration: { predicted: number; actual: number; n: number }[]
    top_picks: Record<string, number | string>[]
    top_calibration?: RankCalibration[]
    horizon?: {
      ahead: number
      n: number
      rmse: number
      bias: number
      spearman_within_pos: number
      top120_predicted: number
      top120_actual: number
    }[]
    horizon_top_calibration?: RankCalibration[]
  } | null
  team_strength?: {
    generated_at: string
    seasons: string[]
    best: Record<string, number>
    best_scores: { deviance: number; msle_vs_market: number; sd: number; sd_market: number }
    current: Record<string, number>
    current_scores: { deviance: number; msle_vs_market: number; sd: number; sd_market: number } | null
    baseline: Record<string, number>
    baseline_scores: { deviance: number; msle_vs_market: number; sd: number; sd_market: number } | null
    deviance_market: number
  } | null
  tails: {
    scale: number
    gameweeks: number
    seasons: string[]
    crps_by_scale: Record<string, number>
    raw: TailStats
    fitted: TailStats
  } | null
  live: { gw: number; players: number; rmse: number; mae: number; predicted: number; actual: number }[]
}

export interface RankCalibration {
  ranks: string
  predicted: number
  actual: number
  n: number
}

export interface TailStats {
  gameweeks: number
  actual_mean: number
  sim_mean: number
  sim_sd: number
  realised_sd: number
  n80_expected: number
  n80_observed: number
  n100_expected: number
  n100_observed: number
}
