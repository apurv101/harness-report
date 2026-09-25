import { Route, Routes } from 'react-router-dom'
import { PageLayout } from '../components/layout/PageLayout'
import { CheckPage } from '../pages/CheckPage'
import { EvaluationsPage } from '../pages/EvaluationsPage'
import { HarnessPage } from '../pages/HarnessPage'
import { HarnessesPage } from '../pages/HarnessesPage'
import { ImportPage } from '../pages/ImportPage'
import { LandingPage } from '../pages/LandingPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ResultPage } from '../pages/ResultPage'
import { RunDetailPage } from '../pages/RunDetailPage'
import { RunsPage } from '../pages/RunsPage'
import { SignInPage } from '../pages/SignInPage'
import { TaskPage } from '../pages/TaskPage'
import { TasksetPage } from '../pages/TasksetPage'
import { TasksPage } from '../pages/TasksPage'
import { RedirectWhenSignedIn, RequireRepo, RequireResult, RequireSignedIn } from './guards'

/** Landing, the three-step flow, the recorded runs, and a page per harness, taskset and task — one shell. */
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
        <Route path="/evaluations" element={<RequireSignedIn><EvaluationsPage /></RequireSignedIn>} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/harnesses" element={<HarnessesPage />} />
        <Route path="/harnesses/:name" element={<HarnessPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/:taskset" element={<TasksetPage />} />
        <Route path="/tasks/:taskset/:task" element={<TaskPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
