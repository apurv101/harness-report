import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from './router/routes'
import { PreviewProvider } from './state/PreviewContext'
import { SessionProvider } from './state/SessionContext'

export function App() {
  return (
    <SessionProvider>
      <PreviewProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </PreviewProvider>
    </SessionProvider>
  )
}
