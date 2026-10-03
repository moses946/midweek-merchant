import { useQuery } from '@tanstack/react-query'
import { registerTeams } from './teams'
import type {
  BestSquads,
  CeilingReport,
  FixturesBundle,
  Hindcast,
  LeagueReport,
  Meta,
  ModelBundle,
  Player,
  TeamPlan,
} from './types'

// The scheduled pipeline publishes the bundle to the repository's `data` branch every six
// hours. The site build also bakes in a snapshot under <base>/data, used when the live bundle
// is unreachable; in development `npm run data` writes that snapshot locally.
const LOCAL_URL = `${import.meta.env.BASE_URL}data`
const LIVE_URL: string = (
  import.meta.env.VITE_DATA_URL ??
  (import.meta.env.DEV ? LOCAL_URL : 'https://raw.githubusercontent.com/moses946/midweek-merchant/data/web')
).replace(/\/$/, '')

export const REPO_URL = 'https://github.com/moses946/midweek-merchant'

async function fetchJSON<T>(base: string, name: string): Promise<T> {
  const res = await fetch(`${base}/${name}`)
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`)
  return (await res.json()) as T
}

// meta.json decides the source; every other file is read from the same one so they match.
let source: Promise<string> | null = null

function resolveSource(): Promise<{ base: string; meta: Meta }> {
  const attempt = async () => {
    try {
      return { base: LIVE_URL, meta: await fetchJSON<Meta>(LIVE_URL, 'meta.json') }
    } catch (err) {
      if (LIVE_URL === LOCAL_URL) throw err
      return { base: LOCAL_URL, meta: await fetchJSON<Meta>(LOCAL_URL, 'meta.json') }
    }
  }
  const p = attempt().then((r) => {
    registerTeams(r.meta.teams)
    return r
  })
  source = p.then((r) => r.base)
  p.catch(() => (source = null))
  return p
}

async function getJSON<T>(name: string): Promise<T> {
  return fetchJSON<T>(await (source ?? resolveSource().then((r) => r.base)), name)
}

const opts = { staleTime: 5 * 60_000, retry: 1 } as const

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: async () => (await resolveSource()).meta, ...opts })
}

/** Load a file listed in meta.files once meta is available. */
function useFile<T>(key: string, file: string | undefined) {
  return useQuery({
    queryKey: ['file', key, file],
    queryFn: () => getJSON<T>(file!),
    enabled: Boolean(file),
    ...opts,
  })
}

export function usePlayers() {
  const meta = useMeta()
  return useFile<Player[]>('players', meta.data?.files.players)
}

export function useFixtures() {
  const meta = useMeta()
  return useFile<FixturesBundle>('fixtures', meta.data?.files.fixtures)
}

export function usePlan() {
  const meta = useMeta()
  return useFile<TeamPlan>('plan', meta.data?.files.plan)
}

export function useCeiling() {
  const meta = useMeta()
  return useFile<CeilingReport>('ceiling', meta.data?.files.ceiling)
}

export function useLeague() {
  const meta = useMeta()
  return useFile<LeagueReport>('league', meta.data?.files.league)
}

export function useBestSquads() {
  const meta = useMeta()
  return useFile<BestSquads>('best', meta.data?.files.best_squads)
}

export function useModel() {
  const meta = useMeta()
  return useFile<ModelBundle>('model', meta.data?.files.model)
}

export function useHindcast(season: string | undefined) {
  const meta = useMeta()
  return useFile<Hindcast>('hindcast', season ? meta.data?.files.hindcast[season] : undefined)
}
