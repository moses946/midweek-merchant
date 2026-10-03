# Midweek Merchant dashboard

React 19 + TypeScript front end for the Midweek Merchant pipeline. It is a static site: every page reads the JSON
bundle written by `mm export-web` (see `src/midweek_merchant/web_export.py`), and the optional FastAPI service
(`src/midweek_merchant/api.py`) adds live planning for any team.

```bash
npm ci
npm run data     # export the bundle from ../data/outputs into public/data
npm run dev      # http://localhost:5173
npm run build    # type-check and build into dist/
npm run lint && npm run format:check
```

| Variable        | Default                                                 | Purpose                                                                        |
| --------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `VITE_DATA_URL` | the repository's `data` branch (`/data` in development) | Where to read the bundle; a baked snapshot under `<base>/data` is the fallback |
| `VITE_API_URL`  | unset                                                   | Live-planner API; when unset the "Plan any FPL team" panel is hidden           |
| `VITE_SITE_URL` | GitHub Pages URL                                        | Absolute URL for social previews (`og:image`)                                  |
| `BASE_PATH`     | `/`                                                     | Sub-path the site is served from (`/midweek-merchant/` on GitHub Pages)        |

## Layout

```
src/
  lib/          data loading (TanStack Query), bundle types, formatting, colour scales, team colours
  components/   app shell, UI primitives, pitch view, plan explorer, player drawer, live planner, chart helpers
  pages/        one lazily loaded module per route
  styles.css    design tokens (CSS variables) for the dark and light themes, mapped into Tailwind
```

## Design system

- **Themes.** Dark is the primary theme and light is defined separately, not inverted. Tokens live on `:root` and
  `[data-theme]`, and the choice is remembered in `localStorage`.
- **Type.** Geist for UI text and Geist Mono for labels. Tables and axes use tabular figures; big numbers use
  proportional figures.
- **Accent.** Lime (`#c5f03c`) is reserved for the brand, the primary action and the current selection.
- **Chart series.** Fixed slot order: green, violet, orange, blue, magenta. Each theme has its own steps, and every
  adjacent pair passes the colour-vision-deficiency, lightness-band and 3:1 contrast checks against that theme's
  card surface.
- **Heatmaps.** One hue, light to dark, with the cell text colour chosen by fill lightness. The value is always
  printed in the cell, so colour is never the only cue.
- **Marks.** Thin marks, 4px rounded bar ends, recessive hairline grids, a legend for two or more series, and a
  tooltip on every chart.
