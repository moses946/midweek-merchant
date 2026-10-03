// Copy dist/index.html to dist/<route>/index.html for every route in src/App.tsx, so any
// static host serves deep links (and refreshes) with clean URLs and a 200 status. Also writes
// 404.html for hosts that fall back to it. Skipped for relative-base (embed) builds.
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const dist = join(root, 'dist')
const index = join(dist, 'index.html')
if (readFileSync(index, 'utf8').includes('src="./assets/')) {
  console.log('route-shells: relative base, skipped')
  process.exit(0)
}
const app = readFileSync(join(root, 'src/App.tsx'), 'utf8')
const routes = [...app.matchAll(/path: '([a-z][a-z0-9-]*)'/g)].map((m) => m[1])
if (!routes.length) throw new Error('route-shells: no routes found in src/App.tsx')
for (const r of routes) {
  mkdirSync(join(dist, r), { recursive: true })
  copyFileSync(index, join(dist, r, 'index.html'))
}
copyFileSync(index, join(dist, '404.html'))
console.log(`route-shells: ${routes.join(', ')}`)
