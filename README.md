# Midweek Merchant

An expected-points forecaster, squad optimiser and mini-league strategist for **Fantasy Premier League
2026/27**.

It ingests FPL, historical and betting-market data and projects every player's expected points (xPts) for
the next eight gameweeks. From those projections it builds the best squad for each gameweek. Given your
team ID, it rebuilds your squad, selling prices, bank, free transfers and remaining chips, then plans
transfers, captaincy and chip timing. Finally it ranks plans by your **chance of winning your mini-league**,
not just by points.

## Quick start

```bash
uv sync                                  # Python 3.11+, installs everything
uv run mm ingest                         # FPL API + vaastav history + football-data odds (~40 s)
uv run mm forecast                       # xPts for the next 8 GWs
uv run mm best-squad                     # best XI per GW + a wildcard draft
uv run mm plan --team-id 1234567         # your transfer/captain plan
uv run mm league --league-id 98765 --team-id 1234567
uv run streamlit run app/streamlit_app.py
```

Your team ID is the number in your FPL points-page URL (`/entry/<ID>/event/...`). Your league ID is the
number in the league URL (`/leagues/<ID>/standings/c`). No FPL login is needed.

## Dashboard

| Page | What it does |
|---|---|
| **Home** | Deadline countdown, data freshness, this week's headline plan, top projections |
| **My team** | Load your team by ID, add transfers already made this week, set horizon/hits/locks/bans/availability overrides, get the plan with a pitch view and alternatives |
| **Projections** | Filterable xPts table per GW, fixture ticker (expected goals / clean-sheet chance), official price-change watch |
| **Best squad** | Best possible squad per GW (Free Hit view) and the best wildcard draft for the horizon |
| **Chips** | Blank/double GW calendar and the value of each chip in each GW: quick single-week values plus exact re-solves including knock-on effects |
| **Mini-league** | Rivals' squads, league effective ownership (shields/swords), candidate plans ranked by P(win league), captaincy and head-to-head odds |
| **Model health** | Backtest accuracy vs baselines, calibration, and live tracking of this season's projections |

## Automation (GitHub Actions)

`.github/workflows/refresh.yml` runs every 6 hours (and on demand). Each run:

1. Refreshes all data.
2. Forecasts expected points.
3. Optimises the best squads.
4. Plans your team and chips, and analyses your league, if configured.
5. Re-runs the backtest weekly.
6. Force-pushes a single-commit **`data` branch** with the results. The repo does not grow, but the point-in-time archive of player news and prices accumulates inside it.

To configure it, go to **Settings → Secrets and variables → Actions**:

| Name | Kind | Purpose |
|---|---|---|
| `ODDS_API_KEY` | secret (optional) | [the-odds-api.com](https://the-odds-api.com) free key for fresh pre-deadline odds (about 2 credits per call, gated to 12-hourly and 3-hourly near deadlines) |
| `FPL_TEAM_ID` | variable (optional) | Precompute your plan and chip report |
| `FPL_LEAGUE_ID` | variable (optional) | Precompute your league analysis |

`ci.yml` runs ruff and the tests on pushes and PRs.

**Hosting the dashboard:** deploy `app/streamlit_app.py` from this repo on
[Streamlit Community Cloud](https://streamlit.io/cloud). `requirements.txt` installs the package. With no local
data, the app downloads the latest bundle from the `data` branch. Interactive planning, chips and league analysis
run live in the app. To pre-fill your IDs there, add root-level `FPL_TEAM_ID` / `FPL_LEAGUE_ID` entries to the
app's Streamlit secrets; Streamlit exposes root-level secrets as environment variables.

## How it works

### Expected points: a structural model

- **Team strength**
  - Fits a time-decayed, ridge-regularised Poisson model (Dixon–Coles family, with low-score correction ρ)
    to a blend of goals and xG.
  - Championship matches are included so promoted clubs get ratings.
  - Bookmaker odds (1X2 and over/under, with the margin removed) are converted to goal expectancies. These are
    added to the fit as pseudo-observations and blended into the nearest fixtures.
- **Minutes**
  - Uses recency-weighted rates of starting, lasting 60 minutes and coming off the bench.
  - Runs of three or more zero-minute games are treated as absences, not rotation.
  - FPL status, chance of playing, "Expected back <date>" news and loan restrictions set availability per
    fixture.
  - You can override availability manually in the UI.
- **Player rates**
  - Each player's share of team xG and xA is estimated with empirical-Bayes shrinkage towards price/position
    priors.
  - Defensive contributions (DefCon) use a negative-binomial count model: CBIT ≥ 10 for defenders,
    CBIRT ≥ 12 for midfielders and forwards.
  - Also modelled: goalkeeper saves per unit of xG faced, card rates, and a bonus model fitted on 2026/27 data
    (the bonus points system changed this season).
- **Points**: the 2026/27 scoring rules give analytic xPts per fixture, summed across double gameweeks. The rules
  engine reproduces every line of FPL's official points breakdown in the test data.
- **Simulation**: a correlated Monte Carlo draws scorelines and allocates goals and assists to the players on the
  pitch, so teammates and opponents are properly correlated. The mini-league layer uses it.

### Optimiser (MILP, HiGHS)

- **Decisions**: squad, lineup, captain, bench, transfers (using selling prices) and free-transfer banking from
  1 to 5.
- **Penalties**: hits are capped and penalised.
- **Chips**: all four, under the 2026/27 rules:
  - two sets, split at GW19/20;
  - one chip per gameweek;
  - no consecutive Free Hits.
- **Objective**: expected points with weekly decay, plus bench weights, a terminal value for banked free
  transfers, and an option value for unused chips.
- **Extras**: alternative plans (via no-good cuts) and noisy re-solves for sensitivity.

### Mini-league strategy

- **Why ownership matters**: the expected change in your gap to any rival depends only on your own xPts, so
  ownership matters through *variance*.
- **What it does**: each candidate plan (max-xPts, alternatives, "shield" and "sword" variants) is scored on the
  same simulations as your rivals' predicted lineups. It then reports P(1st after the horizon) and P(win league),
  extending past the horizon using the simulated spread of score *differences*.
- **Advice**: a stance is given based on your gap measured in units of that spread:
  - behind: chase with swords;
  - ahead: cover shields;
  - close: maximise xPts.

### Backtest (2025-26, 35 gameweeks, about 27k player-gameweeks)

The test is rolling-origin: each gameweek is predicted using only earlier data plus the market's *opening* odds.

| Predictor | RMSE (all) | RMSE (played) | Avg points of weekly top-10 picks |
|---|---|---|---|
| **This model** | **2.00** | **2.94** | **5.1** |
| Recent form (last 4) | 2.35 | 3.21 | 3.2 |
| FPL xP (archived; recording time unclear) | 2.45 | 3.94 | 2.4 |

Calibration is close to the diagonal across deciles. Re-run with `uv run mm backtest`. The scheduled job refreshes
it weekly, and the Model health page shows it.

### Verified rule details

- Rules are read live from FPL's `game_config`. Key values: goalkeeper goal 10, DefCon +2, `max_extra_free_transfers` 4, sell-on fee 50%.
- **Free transfers freeze through Wildcard/Free Hit weeks**: they don't accrue. This was checked against
  250 top managers' hit charges (0 mismatches vs 5 for the accrue rule). Re-check it with
  `uv run mm diagnose ft-rule`.

## Configuration

`config.yaml` holds the season, horizon, decay, bench weights, free-transfer values, chip option values and model
settings. Environment variables `FPL_TEAM_ID`, `FPL_LEAGUE_ID`, `ODDS_API_KEY` and `MM_DATA_DIR` override it.

The optional `override.yaml` (git-ignored) holds manual corrections:

```yaml
team:
  pending: [{out: 123, in: 456}]   # transfers already made this week
  free_transfers: 2
  bank: 5                          # tenths of £m
minutes:
  321: {p_start: 0.0}              # e.g. injury news the model has not seen
```

## Data sources

| Source | Use |
|---|---|
| FPL API (`fantasy.premierleague.com/api/`) | Players, fixtures, per-match stats, live points breakdown, entries, picks, transfers, leagues |
| [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League) | Per-match history for 2023-24 to 2025-26 (training, priors, backtest) |
| [football-data.co.uk](https://www.football-data.co.uk) | Results, xG, opening/closing 1X2 and over/under odds (E0 + Championship) |
| [the-odds-api](https://the-odds-api.com) (optional) | Fresh odds for upcoming fixtures |

Requests are throttled and cached. Please keep them that way.

## Limitations and roadmap

- **No historical news in the backtest.** No historical availability/news data exists, so the backtest assumes
  everyone is available. A snapshot archive (`data/raw/snapshots`) now accumulates every run to train a
  LightGBM minutes model later.
- **Projections cover 8 gameweeks.** Chip planning for distant blank/double gameweeks relies on the calendar view
  until those weeks enter the horizon.
- **Rival transfers are not modelled.** Rivals are assumed to keep their squads and play their best XI by our
  projections.
- **Penalty-taker changes** are only captured through each player's historical xG share.

## Development

```bash
uv run pytest          # rules, optimiser property tests, simulation/league tests
uv run ruff check src tests app && uv run ruff format src tests app
uv run mm backtest     # rolling backtest on 2025-26
```
