import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { cancelEval } from '../lib/api'
import type { Evaluation } from '../lib/types'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function EvaluationsPage() {
  useDocumentTitle('Your evaluations · Harness Report')
  const [jobs, setJobs] = useState<Evaluation[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const ac = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const response = await fetch('/api/evals', { signal: ac.signal })
        const data = await response.json()
        if (!response.ok) throw new Error(data.error || 'Could not load evaluations')
        setJobs(data.evals); setError(null)
      } catch (e) { if (!ac.signal.aborted) setError(String(e)) }
      if (!ac.signal.aborted) timer = setTimeout(poll, 1500)
    }
    poll()
    return () => { ac.abort(); clearTimeout(timer) }
  }, [])
  return <div className="wrap" style={{ paddingBlock: 36 }}>
    <h1>Your evaluations</h1>
    <p>Each task has its own environment. Waiting tasks start as worker slots become available.</p>
    <p><Link className="ui-btn primary" to="/import">Queue a task</Link></p>
    {error && <p role="alert">{error}</p>}
    {!jobs.length && <p>No evaluations yet.</p>}
    {jobs.map(job => <div className="flow-card" key={job.id} style={{ padding: 20, marginBlock: 12 }}>
      <strong>{job.repo}</strong> · {job.status} <span className="muted">· {job.task}</span>
      <p className="muted">{job.id}</p>
      {job.error && <p>{job.error}</p>}
      <Link className="text-link" to={`/check?repo=${encodeURIComponent(job.repo)}&eval=${encodeURIComponent(job.id)}`}>View evaluation</Link>
      {(job.status === 'queued' || job.status === 'running') && <button className="ui-btn small" style={{ marginLeft: 16 }}
        onClick={() => cancelEval(job.id).catch(e => setError(String(e)))}>Cancel</button>}
    </div>)}
  </div>
}
