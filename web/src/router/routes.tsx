import { Route, Routes } from 'react-router-dom'
import { PageLayout } from '../components/layout/PageLayout'
import { CheckPage } from '../pages/CheckPage'
import { ImportPage } from '../pages/ImportPage'
import { LandingPage } from '../pages/LandingPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ResultPage } from '../pages/ResultPage'
import { RunDetailPage } from '../pages/RunDetailPage'
import { RunsPage } from '../pages/RunsPage'
import { SignInPage } from '../pages/SignInPage'
import { RedirectWhenSignedIn, RequireRepo, RequireResult, RequireSignedIn } from './guards'

/** Landing, the three-step flow, and the recorded runs — one shell around all of them. */
export function AppRoutes() {
  const signIn = <RedirectWhenSignedIn><SignInPage /></RedirectWhenSignedIn>
  return (
    <Routes>
      <Route element={<PageLayout />}>
        <Route path="/" element={<LandingPage />} />
        <Route path="/connect" element={signIn} />
        <Route path="/login" element={signIn} />
        <Route path="/import" element={<RequireSignedIn><ImportPage /></RequireSignedIn>} />
        <Route path="/check" element={<RequireRepo><CheckPage /></RequireRepo>} />
        <Route path="/check/result" element={<RequireResult><ResultPage /></RequireResult>} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
