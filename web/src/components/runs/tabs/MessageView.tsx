import { observation, type Turn } from '../../../lib/conversation'
import { Clipped } from '../../ui/Clipped'

/** One turn of the conversation: who spoke, what they said, what they ran, what came back. */
export function MessageView({ turn }: { turn: Turn }) {
  const role = turn.role === 'tool' ? 'tool' : turn.role
  const label = turn.final
    ? <>assistant<br /><span className="muted">(reply)</span></>
    : role === 'tool' ? 'observation' : role
  const empty = !turn.error && !turn.text && !turn.calls?.length && !turn.results?.length

  return (
    <div className={`msg ${role}`}>
      <div className="role">{label}</div>
      <div className="body">
        {turn.error && <div className="err">proxy error: {turn.error}</div>}
        {turn.text && <div className="text"><Clipped text={turn.text} limit={role === 'system' ? 900 : 4000} /></div>}
        {turn.calls?.map((call, i) => (
          <pre className="cmd" key={i}><span className="muted">{call.name} $</span> {call.pretty}</pre>
        ))}
        {turn.results?.map((result, i) => <Observation key={i} text={result.text} isError={result.is_error} />)}
        {empty && <span className="muted">(empty)</span>}
      </div>
    </div>
  )
}

/** Tool results are often JSON wrapping the real output; unwrap it and keep the rest as a head. */
function Observation({ text, isError }: { text: string; isError?: boolean }) {
  const { head, text: body } = observation(text)
  return (
    <pre className={isError ? 'obs err' : 'obs'}>
      {head && <><span className="muted">{head}</span>{'\n'}</>}
      <Clipped text={body} limit={2500} newline />
    </pre>
  )
}
