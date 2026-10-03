import { lazy } from 'react'
import { createBrowserRouter, createMemoryRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { Shell } from './components/layout/Shell'
import { NotFound, RouteError } from './pages/Errors'

const Overview = lazy(() => import('./pages/Overview'))
const MyTeam = lazy(() => import('./pages/MyTeam'))
const Players = lazy(() => import('./pages/Players'))
const Fixtures = lazy(() => import('./pages/Fixtures'))
const BestXI = lazy(() => import('./pages/BestXI'))
const Chips = lazy(() => import('./pages/Chips'))
const League = lazy(() => import('./pages/League'))
const TrackRecord = lazy(() => import('./pages/TrackRecord'))
const ModelHealth = lazy(() => import('./pages/ModelHealth'))
const About = lazy(() => import('./pages/About'))

const routes = [
  {
    path: '/',
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'team', element: <MyTeam /> },
      { path: 'players', element: <Players /> },
      { path: 'fixtures', element: <Fixtures /> },
      { path: 'best-xi', element: <BestXI /> },
      { path: 'chips', element: <Chips /> },
      { path: 'league', element: <League /> },
      { path: 'track-record', element: <TrackRecord /> },
      { path: 'model', element: <ModelHealth /> },
      { path: 'about', element: <About /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]

// VITE_EMBED builds run inside frames that do not allow URL routing (e.g. a hosted preview).
const router = import.meta.env.VITE_EMBED
  ? createMemoryRouter(routes)
  : createBrowserRouter(routes, { basename: import.meta.env.BASE_URL.replace(/\/$/, '') || '/' })

export function App() {
  return <RouterProvider router={router} />
}
