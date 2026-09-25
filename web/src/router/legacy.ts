const TABS = ['traj', 'calls', 'verifier', 'logs', 'recipe', 'run', 'files']
const ROUTES = ['connect', 'login', 'import', 'check', 'runs', 'harnesses', 'tasks']

/**
 * Keep old links working.  The app used hash routes (#/runs/<id>, and before that #runs/<id>), and before that
 * runs lived at /<run-id> with the tab in the hash.  Every one of those becomes a real path, which is what a
 * crawler, an agent reading the .md twin, and a shared link all need.
 */
export function normalizeLocation(): void {
  const hash = location.hash.replace(/^#\/?/, '')
  if (hash && ['/', '/index.html'].includes(location.pathname)) {
    const [path, query] = hash.split('?')
    const route = ROUTES.includes(path.split('/')[0]) ? path : TABS.includes(path) ? '' : path
    history.replaceState({}, '', `/${route}${query ? `?${query}` : ''}`)
    return
  }
  const path = location.pathname.replace(/^\/|\/$/g, '')
  if (path && path !== 'index.html' && !ROUTES.includes(path.split('/')[0])) {
    const tab = TABS.includes(hash) ? `?tab=${hash}` : ''
    history.replaceState({}, '', `/runs/${path}${tab}`)
  }
}
