import { Hero } from '../components/landing/Hero'
import { SimpleSteps } from '../components/landing/SimpleSteps'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function LandingPage() {
  useDocumentTitle('Harness Report — Evaluate your harness')
  return (
    <>
      <Hero />
      <SimpleSteps />
    </>
  )
}
