import type { RunBundle } from '../../../lib/types'
import { LogBlock } from './LogBlock'

/** What the harness printed, and what the proxy logged alongside it. */
export function LogsTab({ bundle }: { bundle: RunBundle }) {
  return (
    <>
      <LogBlock title="stdout.log" text={bundle.stdout} />
      <LogBlock title="stderr.log" text={bundle.stderr} />
      <LogBlock title="proxy.log" text={bundle.proxy} />
    </>
  )
}
