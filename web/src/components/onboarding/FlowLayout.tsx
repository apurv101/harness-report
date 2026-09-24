import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PreviewNotice } from '../layout/PreviewNotice'
import { Icon } from '../ui/Icon'
import { FlowSteps } from './FlowSteps'

/** Sidebar with the three steps on the left, the current step's card on the right. */
export function FlowLayout({ step, children }: { step: number; children: ReactNode }) {
  return (
    <>
      <PreviewNotice />
      <div className="flow-layout">
        <aside className="flow-sidebar">
          <Link className="back-link" to="/"><Icon name="back" /> Home</Link>
          <h2>Connect your harness.</h2>
          <FlowSteps step={step} />
        </aside>
        <section className="flow-content" aria-label="Harness setup">{children}</section>
      </div>
    </>
  )
}

/** The step's own title block: "STEP n OF 3", the heading, one line of why. */
export function FlowHeading({ step, title, text }: { step: number; title: string; text: string }) {
  return (
    <div className="flow-heading">
      <div className="eyebrow">STEP {step} OF 3</div>
      <h1 tabIndex={-1}>{title}</h1>
      <p>{text}</p>
    </div>
  )
}
