import { Icon } from '../ui/Icon'
import { useSession } from '../../state/SessionContext'

const STEPS = [
  ['Sign in', 'Connect with GitHub'],
  ['Import harness', 'Choose your repository'],
  ['Evaluate', 'Run your first task'],
] as const

/** Where you are in the three-step flow.  Step 4 means finished, so all three read complete. */
export function FlowSteps({ step }: { step: number }) {
  const localUsers = useSession()?.local_users
  return (
    <ol className="flow-steps">
      {STEPS.map(([title, detail], i) => {
        const done = step > i + 1
        const current = step === i + 1
        return (
          <li key={title} className={done ? 'complete' : current ? 'current' : ''} aria-current={current ? 'step' : undefined}>
            <span className="flow-step-circle">{done ? <Icon name="check" /> : i + 1}</span>
            <div className="flow-step-text"><strong>{title}</strong><span>{i === 0 && localUsers ? 'Choose a local test user' : detail}</span></div>
          </li>
        )
      })}
    </ol>
  )
}
