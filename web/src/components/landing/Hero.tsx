import { Link } from 'react-router-dom'
import { Icon } from '../ui/Icon'
import { ExampleReport } from './ExampleReport'
import { HeroGraph } from './HeroGraph'

export function Hero() {
  return (
    <section className="hero">
      <div>
        <div className="eyebrow"><span className="status-dot" /> FOR AGENT BUILDERS</div>
        <h1 tabIndex={-1}>Evaluate your<br /><span>harness.</span></h1>
        <p className="hero-copy">Connect your code. Run real tasks.<br />See how your agent performs.</p>
        <div className="hero-buttons">
          <Link className="ui-btn primary" to="/connect"><Icon name="github" /> Continue with GitHub <Icon name="arrow" /></Link>
        </div>
      </div>
      <div className="hero-visual">
        <HeroGraph />
        <ExampleReport />
      </div>
    </section>
  )
}
