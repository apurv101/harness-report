import { Link } from 'react-router-dom'
import { EmptyCard } from '../components/ui/EmptyCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function NotFoundPage() {
  useDocumentTitle('Page not found · Harness Report')
  return (
    <section className="runs-view">
      <EmptyCard>
        <h1 tabIndex={-1}>Page not found.</h1>
        <p><Link to="/runs">View evaluations</Link></p>
      </EmptyCard>
    </section>
  )
}
