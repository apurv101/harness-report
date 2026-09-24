/** The logo's constellation, blown up as wallpaper behind the example report. */
export function HeroGraph() {
  return (
    <svg className="hero-graph" viewBox="0 0 72 72" aria-hidden="true" focusable="false">
      <g stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path pathLength="1" d="m26 28 10 5 8-8" />
        <path pathLength="1" d="M36 33l-9 9" />
        <path pathLength="1" d="m36 33 9 9" />
        <path pathLength="1" d="m36 33-3-13" />
      </g>
      <g fill="currentColor">
        <circle cx="26" cy="28" r="2.6" /><circle cx="33" cy="20" r="2.6" /><circle cx="44" cy="25" r="2.6" />
        <circle cx="36" cy="33" r="3.2" /><circle cx="27" cy="42" r="2.6" /><circle cx="45" cy="42" r="2.6" />
      </g>
    </svg>
  )
}
