import { Link } from 'react-router-dom'
import { Icon } from '../ui/Icon'

/** The repository this run is about, with a way back to the picker. */
export function SelectedRepo({ repo, change = true }: { repo: string; change?: boolean }) {
  return (
    <div className="selected-repo">
      <Icon name="github" />
      <span>{repo}</span>
      {change && <Link to="/import" className="text-link">Change repository</Link>}
    </div>
  )
}
