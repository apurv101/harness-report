import type { RunBundle } from '../../../lib/types'
import { LogBlock } from './LogBlock'

/** What the harness printed, and what the proxy logged alongside it. */
export function LogsTab({ bundle }: { bundle: RunBundle }) {
  const cut = (name: string) => bundle.truncated?.includes(name) ?? false
  return (
    <>
      {(['stdout.log', 'stderr.log', 'proxy.log'] as const).map(name => (
        <LogBlock key={name} title={name} run={bundle.run} cut={cut(name)}
                  text={name === 'stdout.log' ? bundle.stdout : name === 'stderr.log' ? bundle.stderr : bundle.proxy} />
      ))}
    </>
  )
}
