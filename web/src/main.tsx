import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { normalizeLocation } from './router/legacy'
import './styles/index.css'

normalizeLocation()
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
