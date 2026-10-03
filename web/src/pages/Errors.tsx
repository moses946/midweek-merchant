import { AlertTriangle, Compass } from 'lucide-react'
import { Link, useRouteError } from 'react-router'
import { Card, Empty } from '../components/ui/primitives'

export function NotFound() {
  return (
    <Card>
      <Empty title="Page not found" icon={<Compass size={18} />}>
        <Link to="/" className="font-medium text-accent-text underline-offset-4 hover:underline">
          Back to the overview
        </Link>
      </Empty>
    </Card>
  )
}

export function RouteError() {
  const err = useRouteError() as Error | undefined
  return (
    <div className="grid min-h-dvh place-items-center p-6">
      <Card className="max-w-md">
        <Empty title="Something went wrong" icon={<AlertTriangle size={18} />}>
          {err?.message ?? 'Unexpected error.'}{' '}
          <a href={import.meta.env.BASE_URL} className="font-medium text-accent-text">
            Reload
          </a>
        </Empty>
      </Card>
    </div>
  )
}

/** Shown when a data file could not be loaded. */
export function DataError({ error }: { error: unknown }) {
  return (
    <Card>
      <Empty title="Could not load data" icon={<AlertTriangle size={18} />}>
        {error instanceof Error ? error.message : String(error)}. The scheduled pipeline publishes a fresh bundle every
        six hours; try again shortly.
      </Empty>
    </Card>
  )
}
