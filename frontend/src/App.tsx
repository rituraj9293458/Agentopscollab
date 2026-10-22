import { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, Check, ChevronRight, CircleDot,
  Code2, Database, GitCompare, Loader2, LockKeyhole, Play, ShieldCheck,
  TerminalSquare, X,
} from 'lucide-react'
import type { RunEvent, RunReport } from './types'

const API = import.meta.env.VITE_API_URL ?? ''
const stages = ['inspect', 'hypothesize', 'schedule', 'repair', 'verify', 'finalize']

function StatusPill({ status }: { status: string }) {
  const tone = status.includes('VERIFIED') ? 'good' : status.includes('ERROR') || status === 'UNRESOLVED' ? 'bad' : 'warn'
  return <span className={`status-pill ${tone}`}><CircleDot size={12} />{status.replaceAll('_', ' ')}</span>
}

function Metric({ label, value, accent = false }: { label: string; value: string | number; accent?: boolean }) {
  return <div className={`metric ${accent ? 'accent' : ''}`}><span>{label}</span><strong>{value}</strong></div>
}

function App() {
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [report, setReport] = useState<RunReport | null>(null)
  const [status, setStatus] = useState('READY')
  const [health, setHealth] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API}/api/health`).then(r => r.json()).then(data => setHealth(data.postgresql)).catch(() => setHealth(false))
  }, [])

  async function startRun() {
    setError(null); setEvents([]); setReport(null); setStatus('QUEUED')
    const response = await fetch(`${API}/api/runs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: 'inventory_oversell' }),
    })
    if (!response.ok) throw new Error(await response.text())
    const data = await response.json(); setRunId(data.run_id)
  }

  useEffect(() => {
    if (!runId) return
    const source = new EventSource(`${API}/api/runs/${runId}/events`)
    source.onmessage = event => {
      const item = JSON.parse(event.data) as RunEvent
      setEvents(previous => previous.some(existing => existing.sequence === item.sequence) ? previous : [...previous, item])
      if (item.kind === 'stage') setStatus(item.stage.toUpperCase())
    }
    source.addEventListener('done', async () => {
      source.close()
      const response = await fetch(`${API}/api/runs/${runId}`)
      const data = await response.json()
      setStatus(data.status); setReport(data.report); setError(data.error)
    })
    source.onerror = () => { source.close(); setError('Event stream disconnected.') }
    return () => source.close()
  }, [runId])

  const currentStage = useMemo(() => {
    const stageEvents = events.filter(event => event.kind === 'stage')
    return stageEvents.at(-1)?.stage ?? ''
  }, [events])
  const visitedStages = useMemo(
    () => new Set(events.filter(event => event.kind === 'stage').map(event => event.stage)),
    [events],
  )
  const transactions = events.filter(event => ['transaction', 'checkpoint'].includes(event.kind))
  const sqlCount = events.filter(event => event.kind === 'sql').length
  const baseline = report?.baseline
  const invariantEvent = [...events].reverse().find(event => event.kind === 'invariant')
  const liveInvariant = invariantEvent?.detail as unknown as RunReport['baseline'] extends infer _ ? Record<string, unknown> : never
  const invariant = baseline?.invariant ?? (liveInvariant as unknown as { passed: boolean; initial_stock: number; successful_orders: number; final_stock: number } | undefined)
  const verification = report?.attempts.at(-1)?.verification
  const busy = !['READY', 'MODEL_UNAVAILABLE', 'VERIFIED_CANDIDATE', 'UNRESOLVED', 'EXECUTION_ERROR'].includes(status)

  return <main>
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><LockKeyhole size={18} /></div><div><strong>RaceProof</strong><span>Concurrency lab</span></div></div>
      <div className="connection"><span className={`pulse ${health ? 'online' : ''}`} /> PostgreSQL {health === null ? 'checking' : health ? 'connected' : 'offline'}</div>
      <div className="header-actions"><StatusPill status={status} /><button className="run-button" onClick={() => startRun().catch(e => setError(e.message))} disabled={busy || health === false}>{busy ? <Loader2 size={16} className="spin" /> : <Play size={15} fill="currentColor" />}Run investigation</button></div>
    </header>

    <section className="hero">
      <div><div className="eyebrow">LIVE EXPERIMENT · INVENTORY OVERSALE</div><h1>Make the invisible<br/><em>interleaving</em> visible.</h1><p>Controlled PostgreSQL transactions. Executable business invariants. Model-authored patches behind deterministic gates.</p></div>
      <div className="hero-side"><Metric label="Initial stock" value="01"/><Metric label="Actors" value="A + B"/><Metric label="SQL events" value={sqlCount.toString().padStart(2, '0')} accent/></div>
    </section>

    {error && <div className="error-banner"><AlertTriangle size={17}/><span>{error}</span></div>}

    <section className="stage-rail">
      {stages.map((stage, index) => {
        const current = stages.indexOf(currentStage); const done = visitedStages.has(stage) && current !== index
        return <div className={`stage ${current === index ? 'active' : ''} ${done ? 'done' : ''}`} key={stage}>
          <div className="stage-dot">{done ? <Check size={12}/> : index + 1}</div><span>{stage}</span>{index < stages.length - 1 && <div className="stage-line"/>}
        </div>
      })}
    </section>

    <section className="workspace-grid">
      <article className="panel transaction-panel">
        <div className="panel-head"><div><span className="kicker">CONTROLLED SCHEDULE</span><h2>Transaction timeline</h2></div><Database size={20}/></div>
        <div className="lanes">
          {['A', 'B'].map(actor => <div className="lane" key={actor}>
            <div className={`actor actor-${actor.toLowerCase()}`}>{actor}</div>
            <div className="lane-track">
              {transactions.filter(event => event.actor === actor).map(event => <div className={`tx-event ${event.kind}`} key={event.sequence}>
                <span>{event.action.replaceAll('_', ' ')}</span><small>#{event.sequence}</small>
              </div>)}
              {!transactions.some(event => event.actor === actor) && <div className="lane-empty">Waiting for transaction events</div>}
            </div>
          </div>)}
        </div>
        <div className="schedule-caption"><Activity size={15}/><span>The scheduler waits for both reads, commits A, then releases B with its stale value.</span></div>
      </article>

      <article className="panel invariant-panel">
        <div className="panel-head"><div><span className="kicker">DETERMINISTIC ORACLE</span><h2>Business invariant</h2></div><ShieldCheck size={20}/></div>
        <code>orders ≤ initial_stock<br/>stock = initial_stock − orders</code>
        <div className={`verdict ${invariant ? (invariant.passed ? 'pass' : 'fail') : ''}`}>
          {invariant ? (invariant.passed ? <Check/> : <X/>) : <CircleDot/>}
          <div><span>INVARIANT</span><strong>{invariant ? (invariant.passed ? 'PASSED' : 'FAILED') : 'PENDING'}</strong></div>
        </div>
        <div className="invariant-stats"><Metric label="Stock" value={invariant?.initial_stock ?? '-'}/><ArrowRight size={16}/><Metric label="Orders" value={invariant?.successful_orders ?? '-'} accent/><Metric label="Final" value={invariant?.final_stock ?? '-'}/></div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LANGGRAPH STATE</span><h2>Agent activity</h2></div><TerminalSquare size={20}/></div>
        <div className="activity-list">
          {events.filter(event => event.kind === 'stage' || event.kind === 'error').slice(-9).map(event => <div className="activity-row" key={event.sequence}>
            <span className={`activity-icon ${event.kind}`}><ChevronRight size={13}/></span><div><strong>{event.action}</strong><small>{new Date(event.timestamp).toLocaleTimeString()}</small></div>
          </div>)}
          {!events.length && <div className="empty-state"><Activity size={24}/><p>Start an investigation to stream real graph transitions.</p></div>}
        </div>
      </article>

      <article className="panel evidence-panel">
        <div className="panel-head"><div><span className="kicker">BEFORE / AFTER</span><h2>Verification evidence</h2></div><GitCompare size={20}/></div>
        <div className="comparison">
          <div className="compare-card before"><span>BEFORE</span><strong>{baseline?.invariant?.successful_orders ?? '-'} orders / 1 item</strong><small>{baseline?.invariant ? 'Reproduced under exact schedule' : 'Awaiting baseline'}</small></div>
          <ArrowRight size={20}/>
          <div className={`compare-card after ${verification?.passed ? 'verified' : ''}`}><span>AFTER</span><strong>{verification?.passed ? '1 accepted · 1 rejected' : 'Not verified'}</strong><small>{verification ? `${verification.replay_mode} replay` : 'Candidate required'}</small></div>
        </div>
        {verification && <div className="gate-grid">{Object.entries(verification.gates).map(([name, passed]) => <div key={name} className={passed ? 'gate pass' : 'gate fail'}>{passed ? <Check size={13}/> : <X size={13}/>}<span>{name.replaceAll('_', ' ')}</span></div>)}</div>}
      </article>
    </section>

    <section className="panel diff-panel">
      <div className="panel-head"><div><span className="kicker">REVIEWABLE ARTIFACT</span><h2>Candidate patch</h2></div><Code2 size={20}/></div>
      <pre>{report?.final_diff ?? 'No verified candidate diff. Live repair requires a configured model API key; failed or unverified patches are never promoted.'}</pre>
    </section>

    <footer><span>RaceProof experimental prototype</span><span>Finite tests establish observed evidence, not formal race freedom.</span>{runId && <span>RUN {runId}</span>}</footer>
  </main>
}

export default App

