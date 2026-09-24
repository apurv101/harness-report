/** owner/repo, the only repository name shape we accept. */
export const REPO_NAME = /^[a-z\d](?:[a-z\d-]{0,38})\/[a-z\d_.-]+$/i

/**
 * owner/repo out of a pasted GitHub URL, or null when it is not one.  Deliberately strict:
 * https only, github.com only, no port, credentials, query, or fragment.
 */
export function parseRepoURL(value: string): string | null {
  let match: RegExpMatchArray | null = null
  try {
    const url = new URL(value.trim())
    if (url.protocol === 'https:' && url.hostname === 'github.com' && !url.port && !url.username && !url.password && !url.search && !url.hash)
      match = url.pathname.match(/^\/([a-z\d](?:[a-z\d-]{0,38}))\/([a-z\d_.-]+?)\/?$/i)
  } catch { /* not a URL at all */ }
  if (!match) return null
  const repo = match[2].replace(/\.git$/, '')
  if (['', '.', '..'].includes(repo)) return null
  return `${match[1]}/${repo}`
}
