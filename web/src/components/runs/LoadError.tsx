import { EmptyCard } from '../ui/EmptyCard'

/** The run API is the one thing these views cannot do without; say so, and offer another go. */
export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <EmptyCard>
      <h1 tabIndex={-1}>Unable to load results.</h1>
      <p>{message}</p>
      <button className="ui-btn" onClick={onRetry}>Try again</button>
    </EmptyCard>
  )
}
