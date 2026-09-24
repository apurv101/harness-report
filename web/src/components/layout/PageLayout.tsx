import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { SiteFooter } from './SiteFooter'
import { SiteHeader } from './SiteHeader'

/**
 * The shell every route renders into.  On navigation it scrolls to the top and moves focus to
 * the new heading, so the page announces itself to a screen reader instead of silently swapping.
 */
export function PageLayout() {
  const { pathname } = useLocation()
  const first = useRef(true)

  useEffect(() => {
    if (first.current) { first.current = false; return }
    window.scrollTo(0, 0)
    const heading = document.querySelector<HTMLElement>('main h1')
    heading?.focus({ preventScroll: true })
  }, [pathname])

  return (
    <>
      <SiteHeader />
      <main>
        <div className="wrap">
          <Outlet />
          <SiteFooter />
        </div>
      </main>
    </>
  )
}
