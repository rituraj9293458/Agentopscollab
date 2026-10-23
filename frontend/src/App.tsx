import { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, Check, ChevronRight, CircleDot,
  Code2, Database, GitCompare, Loader2, LockKeyhole, Play, ShieldCheck,
  TerminalSquare, X, Gauge,
} from 'lucide-react'
import type { InvariantResult, ModelStatus, RunEvent, RunReport, Target, UsageSnapshot } from './types'

const API = import.meta.env.VITE_API_URL ?? ''
const stages = ['load_target', 'inspect', 'investigate', 'execute_experiment', 'observe', 'repair', 'apply_patch', 'verify', 'finalize']

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
  const [targets, setTargets] = useState<Target[]>([])
  const [targetId, setTargetId] = useState('')
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null)

  useEffect(() => {
    fetch(`${API}/api/health`).then(r => r.json()).then(data => setHealth(data.postgresql)).catch(() => setHealth(false))
    fetch(`${API}/api/model-status`).then(r => r.json()).then(setModelStatus).catch(() => setModelStatus(null))
    fetch(`${API}/api/targets`).then(r => r.json()).then((data: Target[]) => {
      setTargets(data); setTargetId(current => current || data[0]?.id || '')
    }).catch(() => setError('Could not load target applications.'))
  }, [])

  async function startRun() {
    setError(null); setEvents([]); setReport(null); setStatus('QUEUED')
    const response = await fetch(`${API}/api/runs`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_id: targetId }),
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
  const invariant = baseline?.invariant ?? (invariantEvent?.detail as unknown as InvariantResult | undefined)
  const verification = report?.attempts.at(-1)?.verification
  const investigation = report?.investigation_attempts.at(-1)
  const repairAttempt = report?.attempts.at(-1)
  const investigationEvents = events.filter(event => event.kind === 'agent' && event.actor === 'Investigation Agent')
  const repairEvents = events.filter(event => event.kind === 'agent' && event.actor === 'Repair Agent')
  const liveUsage = [...events].reverse().find(event => event.kind === 'usage')?.detail as UsageSnapshot | undefined
  const usage = report?.usage ?? liveUsage
  const target = targets.find(item => item.id === targetId)
  const actors = target?.actors ?? []
  const evidence = Object.entries(invariant?.evidence ?? {}).slice(0, 3)
  const terminal = ['READY', 'MODEL_UNAVAILABLE', 'VERIFIED_CANDIDATE', 'UNRESOLVED', 'UNCONFIRMED', 'EXECUTION_ERROR', 'UNVERIFIABLE_SCHEDULE', 'BUDGET_EXCEEDED', 'AUTHENTICATION_ERROR', 'RATE_LIMITED', 'QUOTA_EXCEEDED']
  const busy = !terminal.includes(status)

  return <main>
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><LockKeyhole size={18} /></div><div><strong>RaceProof</strong><span>Concurrency lab</span></div></div>
      <div className="connection"><span className={`pulse ${health ? 'online' : ''}`} /> PostgreSQL {health === null ? 'checking' : health ? 'connected' : 'offline'}</div>
      <div className="header-actions"><select value={targetId} onChange={event => setTargetId(event.target.value)} disabled={busy}>{targets.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select><StatusPill status={status} /><button className="run-button" onClick={() => startRun().catch(e => setError(e.message))} disabled={busy || health === false || !targetId}>{busy ? <Loader2 size={16} className="spin" /> : <Play size={15} fill="currentColor" />}Run investigation</button></div>
    </header>

    <section className="hero">
      <div><div className="eyebrow">LIVE EXPERIMENT · {target?.name.toUpperCase() ?? 'SELECT A TARGET'}</div><h1>Make the invisible<br/><em>interleaving</em> visible.</h1><p>{target?.description ?? 'Controlled PostgreSQL transactions. Executable business invariants. Model-authored patches behind deterministic gates.'}</p></div>
      <div className="hero-side"><Metric label="Operation" value={target?.operation.split(':').at(-1) ?? '-'}/><Metric label="Actors" value={actors.join(' + ') || '-'}/><Metric label="SQL events" value={sqlCount.toString().padStart(2, '0')} accent/></div>
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
          {actors.map(actor => <div className="lane" key={actor}>
            <div className={`actor actor-${actor.toLowerCase()}`}>{actor}</div>
            <div className="lane-track">
              {transactions.filter(event => event.actor === actor).map(event => <div className={`tx-event ${event.kind}`} key={event.sequence}>
                <span>{event.action.replaceAll('_', ' ')}</span><small>#{event.sequence}</small>
              </div>)}
              {!transactions.some(event => event.actor === actor) && <div className="lane-empty">Waiting for transaction events</div>}
            </div>
          </div>)}
        </div>
        <div className="schedule-caption"><Activity size={15}/><span>Every interleaving is driven by the selected target's declarative checkpoint schedule.</span></div>
      </article>

      <article className="panel invariant-panel">
        <div className="panel-head"><div><span className="kicker">DETERMINISTIC ORACLE</span><h2>Business invariant</h2></div><ShieldCheck size={20}/></div>
        <code>{invariant?.assertion ?? target?.invariant.description ?? 'Waiting for the approved target invariant'}</code>
        <div className={`verdict ${invariant ? (invariant.passed ? 'pass' : 'fail') : ''}`}>
          {invariant ? (invariant.passed ? <Check/> : <X/>) : <CircleDot/>}
          <div><span>INVARIANT</span><strong>{invariant ? (invariant.passed ? 'PASSED' : 'FAILED') : 'PENDING'}</strong></div>
        </div>
        <div className="invariant-stats">{evidence.map(([label, value], index) => <Metric key={label} label={label.replaceAll('_', ' ')} value={String(value)} accent={index === 1}/>)}</div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LLM AGENT 1</span><h2>Investigation Agent</h2></div><TerminalSquare size={20}/></div>
        <div className="activity-list">
          {investigationEvents.slice(-6).map(event => <div className="activity-row" key={event.sequence}>
            <span className={`activity-icon ${event.kind}`}><ChevronRight size={13}/></span><div><strong>{event.action.replaceAll('_', ' ')}</strong><small>{String(event.detail.reasoning_summary ?? event.detail.root_cause ?? event.detail.schedule ?? new Date(event.timestamp).toLocaleTimeString())}</small></div>
          </div>)}
          {investigation && <div className="agent-summary"><strong>{investigation.decision.concurrency_pattern}</strong><p>{investigation.decision.reasoning_summary}</p><small>Experiment: {investigation.decision.experiment_name} · confidence {Math.round(investigation.decision.confidence * 100)}%</small></div>}
          {!investigationEvents.length && !investigation && <div className="empty-state"><Activity size={24}/><p>Waiting for a structured LLM hypothesis.</p></div>}
        </div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LOCAL COST CONTROL</span><h2>Model usage</h2></div><Gauge size={20}/></div>
        <div className="invariant-stats">
          <Metric label="Requests" value={usage?.total_requests ?? 0} accent/>
          <Metric label="Reported tokens" value={usage ? `${usage.total_tokens}${usage.unknown_token_responses ? '+' : ''}` : '0'}/>
          <Metric label="Requests left" value={usage?.remaining_request_budget ?? modelStatus?.budgets.max_model_requests ?? '-'}/>
        </div>
        <div className="agent-summary">
          <strong>Investigation: {report?.investigation_model ?? modelStatus?.investigation_model ?? 'loading'}</strong>
          <p>Repair: {report?.repair_model ?? modelStatus?.repair_model ?? 'loading'}</p>
          <small>Investigation requests {usage?.requests_by_agent.investigation ?? 0} · Repair requests {usage?.requests_by_agent.repair ?? 0} · Fallback {usage?.fallback_invocations ?? 0}</small>
        </div>
        <div className="schedule-caption"><AlertTriangle size={15}/><span>{usage?.unknown_token_responses ? 'Some provider token metadata is unavailable. Token totals are lower bounds.' : usage?.approximate_cost_usd != null ? `Verified configured estimate: $${usage.approximate_cost_usd.toFixed(6)}${usage.cost_is_partial ? ' partial' : ''}` : 'Dollar estimates stay hidden until verified pricing is configured.'}</span></div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LLM AGENT 2</span><h2>Repair Agent</h2></div><Code2 size={20}/></div>
        <div className="activity-list">
          {repairEvents.slice(-6).map(event => <div className="activity-row" key={event.sequence}>
            <span className={`activity-icon ${event.kind}`}><ChevronRight size={13}/></span><div><strong>{event.action.replaceAll('_', ' ')}</strong><small>{String(event.detail.strategy ?? (event.detail.passed === true ? 'verification passed' : event.detail.passed === false ? 'verification failed' : new Date(event.timestamp).toLocaleTimeString()))}</small></div>
          </div>)}
          {repairAttempt?.proposal && <div className="agent-summary"><strong>{repairAttempt.proposal.strategy}</strong><p>{repairAttempt.proposal.diagnosis}</p><small>{repairAttempt.failure_reason ?? 'Candidate awaiting deterministic gates'}</small></div>}
          {!repairEvents.length && !repairAttempt && <div className="empty-state"><Code2 size={24}/><p>Repair starts only after a confirmed invariant violation.</p></div>}
        </div>
      </article>

      <article className="panel evidence-panel">
        <div className="panel-head"><div><span className="kicker">BEFORE / AFTER</span><h2>Verification evidence</h2></div><GitCompare size={20}/></div>
        <div className="comparison">
          <div className="compare-card before"><span>BEFORE</span><strong>{baseline?.invariant ? (baseline.invariant.passed ? 'Invariant passed' : 'Invariant failed') : 'Awaiting baseline'}</strong><small>{baseline?.invariant ? `${baseline.schedule_name} on PostgreSQL` : 'No evidence yet'}</small></div>
          <ArrowRight size={20}/>
          <div className={`compare-card after ${verification?.passed ? 'verified' : ''}`}><span>AFTER</span><strong>{verification?.passed ? 'All declared gates passed' : 'Not verified'}</strong><small>{verification ? `${verification.replay_mode} replay` : 'Candidate required'}</small></div>
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

