import clsx from 'clsx'
import { ArrowDown, ArrowUp, Download, Search, TrendingDown, TrendingUp } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { PageHeader, PageSkeleton } from '../components/layout/Shell'
import { PlayerDrawer } from '../components/PlayerDrawer'
import { Badge, Card, CardHeader, Jersey, Note, PosTag, Segmented, XpCell } from '../components/ui/primitives'
import { useMeta, usePlayers } from '../lib/data'
import { fmt, POSITIONS } from '../lib/format'
import type { Meta, Player, Position } from '../lib/types'
import { DataError } from './Errors'

type SortKey = 'total' | 'per_m' | 'price' | 'own' | 'start' | `gw${number}` | 'name'

export default function Players() {
  const meta = useMeta()
  const players = usePlayers()
  if (meta.error || players.error) return <DataError error={meta.error ?? players.error} />
  if (!meta.data || !players.data) return <PageSkeleton />
  return <Explorer meta={meta.data} players={players.data} />
}

function Explorer({ meta, players }: { meta: Meta; players: Player[] }) {
  const [q, setQ] = useState('')
  const [pos, setPos] = useState<Position | 'ALL'>('ALL')
  const [team, setTeam] = useState('ALL')
  const [maxPrice, setMaxPrice] = useState(16)
  const [win, setWin] = useState(Math.min(6, meta.gws.length))
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'total', desc: true })
  const [limit, setLimit] = useState(40)
  const [open, setOpen] = useState<Player | null>(null)
  const query = useDeferredValue(q)

  const gws = meta.gws.slice(0, win)
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const out = players
      .filter(
        (p) =>
          (pos === 'ALL' || p.pos === pos) &&
          (team === 'ALL' || p.team === team) &&
          p.price <= maxPrice &&
          (!needle || p.name.toLowerCase().includes(needle) || p.full.toLowerCase().includes(needle)),
      )
      .map((p) => {
        const total = p.xp.slice(0, win).reduce<number>((s, v) => s + (v ?? 0), 0)
        return { p, total, per_m: total / p.price }
      })
    const val = (r: (typeof out)[number]): number | string => {
      const k = sort.key
      if (k === 'total') return r.total
      if (k === 'per_m') return r.per_m
      if (k === 'price') return r.p.price
      if (k === 'own') return r.p.own ?? 0
      if (k === 'start') return r.p.next.p_start ?? 0
      if (k === 'name') return r.p.name
      return r.p.xp[Number(k.slice(2))] ?? -1
    }
    out.sort((a, b) => {
      const x = val(a)
      const y = val(b)
      const c = typeof x === 'string' ? x.localeCompare(String(y)) : x - (y as number)
      return sort.desc ? -c : c
    })
    return out
  }, [players, pos, team, maxPrice, query, win, sort])

  const teams = useMemo(() => [...new Set(players.map((p) => p.team))].sort(), [players])

  function header(key: SortKey, label: string, align: 'left' | 'right' = 'right') {
    const active = sort.key === key
    return (
      <th className={clsx('py-2 font-medium whitespace-nowrap', align === 'right' ? 'text-right' : 'text-left')}>
        <button
          onClick={() => setSort({ key, desc: active ? !sort.desc : key !== 'name' })}
          className={clsx('inline-flex items-center gap-1 hover:text-ink', active && 'text-ink')}
        >
          {label}
          {active && (sort.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
        </button>
      </th>
    )
  }

  function downloadCsv() {
    const head = [
      'player',
      'team',
      'position',
      'price',
      ...gws.map((g) => `xpts_gw${g}`),
      'total',
      'xpts_per_m',
      'owned_pct',
    ]
    const lines = rows.map(({ p, total, per_m }) =>
      [
        p.name,
        p.team,
        p.pos,
        p.price,
        ...gws.map((_, k) => p.xp[k] ?? ''),
        total.toFixed(2),
        per_m.toFixed(3),
        p.own ?? '',
      ]
        .map((v) => (typeof v === 'string' && v.includes(',') ? `"${v}"` : v))
        .join(','),
    )
    const blob = new Blob([[head.join(','), ...lines].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `midweek-merchant-projections-gw${meta.next_gw}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        title="Player projections"
        description={`Expected FPL points for every player in every gameweek of the horizon, built up from minutes, goals, assists, clean sheets, saves, defensive contributions and bonus. Click a player for the breakdown.`}
        actions={
          !import.meta.env.VITE_EMBED && (
            <button
              onClick={downloadCsv}
              className="inline-flex items-center gap-2 rounded-xl bg-card px-3.5 py-2 text-[13px] font-medium text-ink ring-1 ring-line hover:bg-card-2"
            >
              <Download size={15} /> CSV
            </button>
          )
        }
      />

      <Card className="!p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative min-w-[200px] flex-1">
            <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search players"
              className="h-10 w-full rounded-xl bg-card-2 pr-3 pl-9 text-[14px] text-ink ring-1 ring-line outline-none placeholder:text-muted focus:ring-accent/60"
            />
          </label>
          <Segmented
            value={pos}
            onChange={setPos}
            options={[{ value: 'ALL' as const, label: 'All' }, ...POSITIONS.map((p) => ({ value: p, label: p }))]}
          />
          <select
            value={team}
            onChange={(e) => setTeam(e.target.value)}
            className="h-10 rounded-xl bg-card-2 px-3 text-[13px] text-ink ring-1 ring-line outline-none"
            aria-label="Team"
          >
            <option value="ALL">All teams</option>
            {teams.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <label className="flex h-10 items-center gap-3 rounded-xl bg-card-2 px-3 ring-1 ring-line">
            <span className="text-[12px] whitespace-nowrap text-muted">Max £{maxPrice.toFixed(1)}m</span>
            <input
              type="range"
              min={4}
              max={16}
              step={0.5}
              value={maxPrice}
              onChange={(e) => setMaxPrice(Number(e.target.value))}
              className="w-28 accent-[var(--accent)]"
            />
          </label>
          <Segmented
            value={win}
            onChange={setWin}
            options={[1, 3, 6, meta.gws.length]
              .filter((v, i, a) => v <= meta.gws.length && a.indexOf(v) === i)
              .map((v) => ({ value: v, label: v === 1 ? `GW${meta.gws[0]}` : `${v} GWs` }))}
          />
        </div>
      </Card>

      <Card pad={false}>
        <div className="flex items-center justify-between px-5 pt-4 text-[12.5px] text-muted sm:px-6">
          <span>
            {rows.length} players · totals over GW{gws[0]}
            {gws.length > 1 ? `–${gws[gws.length - 1]}` : ''}
          </span>
          <span className="hidden sm:inline">Cell shade = expected points; the value is always printed.</span>
        </div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[980px] text-[13px]">
            <thead className="text-[11.5px] text-muted">
              <tr className="border-y border-line">
                <th className="px-5 py-2 text-left font-medium sm:px-6">
                  <button
                    onClick={() => setSort({ key: 'name', desc: sort.key === 'name' ? !sort.desc : false })}
                    className="hover:text-ink"
                  >
                    Player
                  </button>
                </th>
                <th className="py-2 text-left font-medium">Pos</th>
                {header('price', 'Price')}
                {header('own', 'Owned')}
                {gws.map((g, k) => (
                  <th key={g} className="py-2 text-right font-medium">
                    <button
                      onClick={() => setSort({ key: `gw${k}`, desc: sort.key === `gw${k}` ? !sort.desc : true })}
                      className={clsx('hover:text-ink', sort.key === `gw${k}` && 'text-ink')}
                    >
                      GW{g}
                    </button>
                  </th>
                ))}
                {header('total', 'Total')}
                {header('per_m', 'Per £m')}
                <th className="w-8 px-5 py-2 sm:px-6" />
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, limit).map(({ p, total, per_m }) => (
                <tr
                  key={p.id}
                  onClick={() => setOpen(p)}
                  className="cursor-pointer border-b border-line transition-colors last:border-0 hover:bg-card-2/70"
                >
                  <td className="px-5 py-2 sm:px-6">
                    <div className="flex items-center gap-2.5">
                      <Jersey team={p.team} pos={p.pos} size={30} />
                      <div className="min-w-0">
                        <div className="truncate font-medium text-ink">{p.name}</div>
                        <div className="text-[11.5px] text-muted">
                          {p.team} · {p.fx[0] || 'blank'}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <PosTag pos={p.pos} />
                  </td>
                  <td className="num text-right text-ink-2">{fmt.price(p.price)}</td>
                  <td className="num text-right text-ink-2">{p.own == null ? '–' : `${p.own.toFixed(1)}%`}</td>
                  {gws.map((g, k) => (
                    <td key={g} className="num py-1.5 pl-1 text-right">
                      <XpCell v={p.xp[k]} />
                    </td>
                  ))}
                  <td className="num pl-3 text-right text-[14px] font-semibold text-ink">{total.toFixed(1)}</td>
                  <td className="num text-right text-ink-2">{per_m.toFixed(2)}</td>
                  <td className="px-5 sm:px-6">
                    {p.status !== 'a' && (
                      <span title={p.news} className="inline-block size-2 rounded-full bg-warn" aria-label={p.news} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > limit && (
          <div className="border-t border-line p-3 text-center">
            <button
              onClick={() => setLimit((l) => l + 60)}
              className="text-[13px] font-medium text-accent-text hover:underline"
            >
              Show more ({rows.length - limit} left)
            </button>
          </div>
        )}
      </Card>

      <PriceWatch players={players} onOpen={setOpen} />
      <PlayerDrawer player={open} meta={meta} onClose={() => setOpen(null)} />
    </div>
  )
}

function PriceList({ list, up, onOpen }: { list: Player[]; up: boolean; onOpen: (p: Player) => void }) {
  return list.length ? (
    <ul className="flex flex-col gap-1">
      {list.map((p) => (
        <li key={p.id}>
          <button
            onClick={() => onOpen(p)}
            className="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-left hover:bg-card-2"
          >
            <Jersey team={p.team} pos={p.pos} size={26} />
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{p.name}</span>
            <span className="num text-[12px] text-muted">{fmt.price(p.price)}</span>
            <span className="w-28">
              <span className="block h-1.5 overflow-hidden rounded-full bg-card-3">
                <span
                  className={clsx('block h-full rounded-full', up ? 'bg-good' : 'bg-bad')}
                  style={{ width: `${Math.min(100, Math.abs(p.pcp ?? 0))}%` }}
                />
              </span>
            </span>
            <span className="num w-11 text-right text-[12px] font-medium text-ink">
              {Math.abs(p.pcp ?? 0).toFixed(0)}%
            </span>
          </button>
        </li>
      ))}
    </ul>
  ) : (
    <p className="px-2 text-[13px] text-muted">Nobody close right now.</p>
  )
}

function PriceWatch({ players, onOpen }: { players: Player[]; onOpen: (p: Player) => void }) {
  const risers = players
    .filter((p) => (p.pcp ?? 0) >= 50)
    .sort((a, b) => (b.pcp ?? 0) - (a.pcp ?? 0))
    .slice(0, 8)
  const fallers = players
    .filter((p) => (p.pcp ?? 0) <= -50)
    .sort((a, b) => (a.pcp ?? 0) - (b.pcp ?? 0))
    .slice(0, 8)
  return (
    <Card>
      <CardHeader
        eyebrow="FPL price predictor"
        title="Price change watch"
        hint="Progress towards the next price change. At 100% a player is expected to change at the next overnight update: buy risers before then, sell fallers you plan to drop."
      />
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center gap-2 px-2 text-[13px] font-medium text-ink">
            <TrendingUp size={15} className="text-good" /> Rising <Badge tone="good">{risers.length}</Badge>
          </div>
          <PriceList list={risers} up onOpen={onOpen} />
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2 px-2 text-[13px] font-medium text-ink">
            <TrendingDown size={15} className="text-bad" /> Falling <Badge tone="bad">{fallers.length}</Badge>
          </div>
          <PriceList list={fallers} up={false} onOpen={onOpen} />
        </div>
      </div>
      <Note className="mt-4">Shown from 50% progress.</Note>
    </Card>
  )
}
