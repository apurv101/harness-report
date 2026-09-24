import { Link } from 'react-router-dom'

/** The mark: the node-and-edge graph inside a harness outline.  A run is a graph. */
export function Wordmark() {
  return (
    <Link className="wordmark" to="/" aria-label="Harness Report home">
      <svg className="brand-icon" viewBox="0 0 72 72" aria-hidden="true" focusable="false">
        <g transform="translate(-2 2)">
          <path d="M17 55c2.5-5.3 3.4-10.4 1-15.3A21 21 0 0 1 15 29C15 17.4 23.6 9 35 9s20 8.2 20 19v3.4l4.1 8.1c.6 1.2-.2 2.5-1.5 2.5H54v7a4 4 0 0 1-4 4h-9l-1 5"
                fill="none" stroke="var(--logo-ink, #0c1a2b)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
          <g stroke="var(--logo-accent, #0b5fd1)" strokeWidth="2.7" strokeLinecap="round">
            <path d="m26 28 10 5 8-8M36 33l-9 9m9-9 9 9m-9-9-3-13" />
          </g>
          <g fill="var(--logo-accent, #0b5fd1)">
            <circle cx="26" cy="28" r="4" /><circle cx="33" cy="20" r="4" /><circle cx="44" cy="25" r="4" />
            <circle cx="36" cy="33" r="4.5" /><circle cx="27" cy="42" r="4" /><circle cx="45" cy="42" r="4" />
          </g>
        </g>
      </svg>
      <span>Harness Report</span>
    </Link>
  )
}
