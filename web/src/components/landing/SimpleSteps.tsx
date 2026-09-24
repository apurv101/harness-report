const STEPS = [
  ['01', 'Connect your repository'],
  ['02', 'Run an evaluation'],
  ['03', 'Explore your results'],
] as const

export function SimpleSteps() {
  return (
    <div className="simple-steps" aria-label="How it works">
      {STEPS.map(([n, text]) => <span key={n}><b>{n}</b> {text}</span>)}
    </div>
  )
}
