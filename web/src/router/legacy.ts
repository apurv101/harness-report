const TABS = ['traj', 'calls', 'verifier', 'logs', 'recipe', 'run', 'files']

/**
 * Keep old links working.  Runs used to live at /<run-id> with the tab in the hash, and the
 * routes before this app were bare hashes (#runs/<id>); the router speaks #/… only.
 */
export function normalizeLocation(): void {
  if (!['/', '/index.html'].includes(location.pathname)) {
    const path = location.pathname.replace(/^\/|\/$/g, '')
    const route = path === 'runs' || path.startsWith('runs/') ? path : `runs/${path}`
    const oldTab = location.hash.slice(1)
    const tab = TABS.includes(oldTab) ? `?tab=${oldTab}` : ''
    history.replaceState({}, '', `/#/${route}${tab}`)
    return
  }
  if (location.hash && !location.hash.startsWith('#/'))
    history.replaceState({}, '', `${location.pathname}#/${location.hash.slice(1)}`)
}
