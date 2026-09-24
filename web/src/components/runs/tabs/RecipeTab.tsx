import type { RunBundle } from '../../../lib/types'
import { Fact, Facts } from '../../ui/Fact'

/** recipe.json: how the AI decided to package and run this harness. */
export function RecipeTab({ bundle }: { bundle: RunBundle }) {
  const recipe = bundle.recipe
  if (!recipe) return <div className="empty">no recipe.json in this run.</div>
  return (
    <>
      {recipe.summary && <><h2>Summary</h2><div className="text">{recipe.summary}</div></>}
      <Facts>
        <Fact name="api style" value={recipe.api_style} />
        <Fact name="base image" value={recipe.base_image} />
        <Fact name="ad-hoc workdir" value={recipe.workdir || '/work'} />
      </Facts>
      <h2>Run command</h2><pre>{bundle.command || recipe.run_command || ''}</pre>
      {recipe.check_command && <><h2>Check command</h2><pre>{recipe.check_command}</pre></>}
      <h2>Environment</h2>
      <table>
        <thead><tr><th>name</th><th>value</th></tr></thead>
        <tbody>
          {(recipe.env || []).map(e => (
            <tr key={e.name}><td className="mono">{e.name}</td><td className="mono">{e.value}</td></tr>
          ))}
        </tbody>
      </table>
      {recipe.dockerfile && <><h2>Dockerfile</h2><pre>{recipe.dockerfile}</pre></>}
      {recipe.notes && <><h2>Notes</h2><div className="text" style={{ whiteSpace: 'pre-wrap' }}>{recipe.notes}</div></>}
    </>
  )
}
