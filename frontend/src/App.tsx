import { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, Check, ChevronRight, CircleDot,
  Clock, Code2, Database, ExternalLink, GitCompare, Loader2, LockKeyhole, Pause,
  Play, ShieldCheck, SkipBack, SkipForward, TerminalSquare, X, Gauge,
} from 'lucide-react'
import type { InvariantResult, ModelStatus, RunEvent, RunReport, ScheduleResult, Target, UsageSnapshot } from './types'

const API = import.meta.env.VITE_API_URL ?? ''
const stages = ['load_target', 'inspect', 'investigate', 'execute_experiment', 'observe', 'repair', 'apply_patch', 'verify', 'human_review', 'finalize']

function StatusPill({ status }: { status: string }) {
  const tone = status.includes('VERIFIED') || status === 'APPROVED' ? 'good' : status.includes('ERROR') || status === 'UNRESOLVED' || status === 'HUMAN_REJECTED' ? 'bad' : 'warn'
  return <span className={`status-pill ${tone}`}><CircleDot size={12} />{status.replaceAll('_', ' ')}</span>
}

function Metric({ label, value, accent = false }: { label: string; value: string | number; accent?: boolean }) {
  return <div className={`metric ${accent ? 'accent' : ''}`}><span>{label}</span><strong>{value}</strong></div>
}

function SchedulePlayer({ events }: { events: RunEvent[] }) {
  const items = events.filter(event => ['transaction', 'checkpoint', 'sql', 'invariant'].includes(event.kind))
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(900)
  useEffect(() => {
    if (!playing || !items.length) return
    const timer = window.setInterval(() => {
      setIndex(current => {
        if (current >= items.length - 1) { setPlaying(false); return current }
        return current + 1
      })
    }, speed)
    return () => window.clearInterval(timer)
  }, [playing, speed, items.length])
  useEffect(() => { setIndex(0); setPlaying(false) }, [events.length])
  const current = items[index]
  return <article className="panel player-panel">
    <div className="panel-head"><div><span className="kicker">INTERACTIVE REPLAY</span><h2>Schedule event player</h2></div><Activity size={20}/></div>
    <div className="player-controls">
      <button onClick={() => setIndex(0)} disabled={!items.length}><SkipBack size={14}/></button>
      <button onClick={() => setPlaying(value => !value)} disabled={!items.length}>{playing ? <Pause size={14}/> : <Play size={14}/>}</button>
      <button onClick={() => setIndex(value => Math.min(items.length - 1, value + 1))} disabled={!items.length}><SkipForward size={14}/></button>
      <span>Step {items.length ? index + 1 : 0} / {items.length}</span>
      <select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={1500}>0.5×</option><option value={900}>1×</option><option value={400}>2×</option></select>
    </div>
    <input className="player-slider" type="range" min="0" max={Math.max(0, items.length - 1)} value={Math.min(index, Math.max(0, items.length - 1))} onChange={event => setIndex(Number(event.target.value))}/>
    {current ? <div className="player-event"><strong>#{current.sequence} · {current.actor ? `Actor ${current.actor}` : 'System'} · {current.action.replaceAll('_', ' ')}</strong><p>{String(current.detail?.statement ?? current.detail?.explanation ?? current.kind)}</p></div> : <div className="empty-state"><p>Run an investigation to replay its PostgreSQL schedule.</p></div>}
  </article>
}

function meaningfulSelect(result: ScheduleResult | null | undefined) {
  const statements = result?.events
    .filter(event => event.kind === 'sql')
    .map(event => String(event.detail.statement ?? ''))
    .filter(statement => /^SELECT\b/i.test(statement) && !/pg_catalog|information_schema/i.test(statement)) ?? []
  return statements.find(statement => /FOR UPDATE/i.test(statement)) ?? statements.find(statement => /booking|resource/i.test(statement)) ?? statements[0] ?? 'No application SELECT captured'
}

function outcomeSummary(result: ScheduleResult | null | undefined) {
  if (!result) return 'No replay evidence'
  const counts = Object.values(result.actor_outcomes).reduce<Record<string, number>>(
    (all, value) => ({ ...all, [value]: (all[value] ?? 0) + 1 }),
    {},
  )
  return Object.entries(counts).map(([name, count]) => `${count} ${name}`).join(', ')
}

function DatabaseBehaviorComparison({ before, after }: { before: ScheduleResult | null | undefined; after: ScheduleResult | null | undefined }) {
  const rows = [
    ['Read SQL', meaningfulSelect(before), meaningfulSelect(after)],
    ['Actor outcomes', outcomeSummary(before), outcomeSummary(after)],
    ['Invariant', before?.invariant?.passed ? 'Passed' : 'Failed', after?.invariant?.passed ? 'Passed' : 'Failed'],
    ['Schedule result', before?.status ?? 'Unavailable', after?.status ?? 'Unavailable'],
  ]
  return <article className="panel sql-compare-panel">
    <div className="panel-head"><div><span className="kicker">DATABASE BEHAVIOR</span><h2>Before / after SQL comparison</h2></div><Database size={20}/></div>
    <div className="sql-compare-grid sql-compare-head"><span>Evidence</span><strong>Before patch</strong><strong>After patch</strong></div>
    {rows.map(([label, beforeValue, afterValue]) => <div className="sql-compare-grid" key={label}><span>{label}</span><code>{beforeValue}</code><code>{afterValue}</code></div>)}
  </article>
}

function LockWaitVisualization({ result }: { result: ScheduleResult | null | undefined }) {
  const waits = result?.lock_waits ?? []
  return <article className="panel lock-panel">
    <div className="panel-head"><div><span className="kicker">POSTGRESQL LOCK EVIDENCE</span><h2>Lock-wait visualization</h2></div><Clock size={20}/></div>
    {waits.length ? <div className="lock-list">{waits.map((wait, index) => <div className="lock-wait" key={`${wait.waiting_actor}-${index}`}>
      <div className="lock-lane"><strong>Actor {wait.blocking_actors.join(' + ') || 'unknown'}</strong><div className="lock-bar owner">holds {wait.lock_type} lock</div><span>{wait.release_point ?? 'release observed'}</span></div>
      <div className="lock-lane"><strong>Actor {wait.waiting_actor}</strong><div className="lock-bar waiter">waits {wait.duration_ms.toFixed(1)} ms</div><span>acquires after release</span></div>
      <div className="lock-meta"><span>Mode <strong>{wait.lock_mode}</strong></span><span>Relation <strong>{wait.relation ?? 'transaction'}</strong></span><span>Deadlock <strong>{wait.deadlock ? 'detected' : 'none'}</strong></span></div>
    </div>)}</div> : <div className="empty-state"><p>No PostgreSQL lock wait was sampled in this replay. Fast uncontended locks may complete between samples.</p></div>}
  </article>
}

function DeadlockGraph({ result }: { result: ScheduleResult | null | undefined }) {
  const edges = result?.wait_for_edges ?? []
  const actors = [...new Set(edges.flatMap(edge => [edge.waiting_actor, edge.blocking_actor]))]
  return <article className="panel deadlock-panel">
    <div className="panel-head"><div><span className="kicker">WAIT-FOR GRAPH</span><h2>Deadlock analysis</h2></div><Activity size={20}/></div>
    <div className={`cycle-status ${result?.deadlock_cycle ? 'danger' : 'safe'}`}>{result?.deadlock_cycle ? 'DEADLOCK DETECTED' : 'NO WAIT-FOR CYCLE DETECTED'}</div>
    {edges.length ? <div className="wait-graph">
      <div className="graph-nodes">{actors.map(actor => <div className="graph-node" key={actor}>TX {actor}</div>)}</div>
      {edges.map((edge, index) => <div className="graph-edge" key={`${edge.waiting_actor}-${edge.blocking_actor}-${index}`}><strong>TX {edge.waiting_actor}</strong><ArrowRight size={16}/><strong>TX {edge.blocking_actor}</strong><span>{edge.lock_type} · {edge.lock_mode}</span></div>)}
    </div> : <div className="empty-state"><p>No blocking edge was observed. The verified replay completed without a sampled transaction dependency.</p></div>}
  </article>
}

function App() {
  const [runId, setRunId] = useState<string | null>(() => localStorage.getItem('raceproof.runId'))
  const [events, setEvents] = useState<RunEvent[]>([])
  const [report, setReport] = useState<RunReport | null>(null)
  const [status, setStatus] = useState('READY')
  const [health, setHealth] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [targets, setTargets] = useState<Target[]>([])
  const [targetId, setTargetId] = useState('')
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null)
  const [streamVersion, setStreamVersion] = useState(0)
  const [reviewComment, setReviewComment] = useState('')
  const [reviewSubmitting, setReviewSubmitting] = useState(false)

  function resetInterruptedRun(message: string) {
    localStorage.removeItem('raceproof.runId')
    setRunId(null)
    setEvents([])
    setReport(null)
    setStatus('READY')
    setError(message)
  }

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
    const data = await response.json()
    localStorage.setItem('raceproof.runId', data.run_id)
    setRunId(data.run_id)
  }

  async function submitReview(action: 'approve' | 'reject' | 'request_revision') {
    if (!runId) return
    setError(null); setStatus('HUMAN_REVIEW'); setReviewSubmitting(true)
    try {
      const response = await fetch(`${API}/api/runs/${runId}/review`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, comment: reviewComment }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail ?? `Review request failed (${response.status})`)
      }
      setStreamVersion(value => value + 1)
    } catch (error) {
      setStatus('AWAITING_HUMAN_REVIEW')
      throw error
    } finally {
      setReviewSubmitting(false)
    }
  }

  useEffect(() => {
    if (!runId) return
    const source = new EventSource(`${API}/api/runs/${runId}/events`)
    source.onmessage = event => {
      try {
        const item = JSON.parse(event.data) as RunEvent
        if (item && typeof item === 'object') {
          setEvents(previous => previous.some(existing => existing.sequence === item.sequence) ? previous : [...previous, item])
          if (item.kind === 'stage' && item.stage) setStatus(item.stage.toUpperCase())
        }
      } catch (err) {
        console.error('Failed to parse SSE event:', err)
      }
    }
    source.addEventListener('done', async () => {
      source.close()
      try {
        const response = await fetch(`${API}/api/runs/${runId}`)
        if (response.status === 404) {
          resetInterruptedRun(
            'The backend restarted and discarded this in-memory run. Start a new investigation.',
          )
          return
        }
        if (response.ok) {
          const data = await response.json()
          setStatus(data.status ?? 'COMPLETED')
          setReport(data.report ?? null)
          setError(data.error ?? null)
          if (data.status === 'VERIFIED_CANDIDATE' && !data.report?.human_review) {
            localStorage.removeItem('raceproof.runId')
            setRunId(null)
            setError('This completed run was created by the pre-HITL backend. Start a new investigation to use human review.')
          }
        }
      } catch (err) {
        console.error('Failed to fetch completed run report:', err)
      }
    })
    source.onerror = async () => {
      source.close()
      try {
        const response = await fetch(`${API}/api/runs/${runId}`)
        if (response.status === 404) {
          resetInterruptedRun(
            'The backend restarted and discarded this in-memory run. Start a new investigation.',
          )
          return
        }
      } catch {
        // The API may be temporarily unavailable while its process restarts.
      }
      setStatus('READY')
      localStorage.removeItem('raceproof.runId')
      setRunId(null)
      setEvents([])
      setReport(null)
      setError('Event stream disconnected. Start a new investigation.')
    }
    return () => source.close()
  }, [runId, streamVersion])

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
  const verifiedSchedule = verification?.lock_evidence_results?.find(result => result.lock_waits?.length) ?? verification?.schedule_results?.find(result => result.lock_waits?.length) ?? verification?.schedule_results?.[0]
  const investigationEvents = events.filter(event => event.kind === 'agent' && event.actor === 'Investigation Agent')
  const repairEvents = events.filter(event => event.kind === 'agent' && event.actor === 'Repair Agent')
  const liveUsage = [...events].reverse().find(event => event.kind === 'usage')?.detail as UsageSnapshot | undefined
  const usage = report?.usage ?? liveUsage
  const target = targets.find(item => item.id === targetId)
  const actors = target?.actors ?? []
  const evidence = Object.entries(invariant?.evidence ?? {}).slice(0, 3)
  const terminal = ['READY', 'VERIFIED_CANDIDATE', 'MODEL_UNAVAILABLE', 'AWAITING_HUMAN_REVIEW', 'APPROVED', 'HUMAN_REJECTED', 'UNRESOLVED', 'UNCONFIRMED', 'EXECUTION_ERROR', 'UNVERIFIABLE_SCHEDULE', 'BUDGET_EXCEEDED', 'AUTHENTICATION_ERROR', 'RATE_LIMITED', 'QUOTA_EXCEEDED']
  const busy = !terminal.includes(status)

  return <main>
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><LockKeyhole size={18} /></div><div><strong>RaceProof</strong><span>Concurrency lab</span></div></div>
      <div className="connection"><span className={`pulse ${health ? 'online' : ''}`} /> PostgreSQL {health === null ? 'checking' : health ? 'connected' : 'offline'}</div>
      <div className="header-actions"><select value={targetId} onChange={event => setTargetId(event.target.value)} disabled={busy}>{targets.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select><StatusPill status={status} /><button className="run-button" onClick={() => startRun().catch(e => setError(e.message))} disabled={busy || status === 'AWAITING_HUMAN_REVIEW' || health === false || !targetId}>{busy ? <Loader2 size={16} className="spin" /> : <Play size={15} fill="currentColor" />}Run investigation</button></div>
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
                <span>{(event.action ?? '').replaceAll('_', ' ')}</span><small>#{event.sequence}</small>
              </div>)}
              {!transactions.some(event => event.actor === actor) && <div className="lane-empty">Waiting for transaction events</div>}
            </div>
          </div>)}
        </div>
        <div className="schedule-caption"><Activity size={15}/><span>Every interleaving is driven by the selected target's declarative checkpoint schedule.</span></div>
      </article>

      <article className="panel invariant-panel">
        <div className="panel-head"><div><span className="kicker">DETERMINISTIC ORACLE</span><h2>Business invariant</h2></div><ShieldCheck size={20}/></div>
        <code>{invariant?.assertion ?? target?.invariant?.description ?? 'Waiting for the approved target invariant'}</code>
        <div className={`verdict ${invariant ? (invariant.passed ? 'pass' : 'fail') : ''}`}>
          {invariant ? (invariant.passed ? <Check/> : <X/>) : <CircleDot/>}
          <div><span>INVARIANT</span><strong>{invariant ? (invariant.passed ? 'PASSED' : 'FAILED') : 'PENDING'}</strong></div>
        </div>
        <div className="invariant-stats">{evidence.map(([label, value], index) => <Metric key={label} label={(label ?? '').replaceAll('_', ' ')} value={String(value ?? '')} accent={index === 1}/>)}</div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LLM AGENT 1</span><h2>Investigation Agent</h2></div><TerminalSquare size={20}/></div>
        <div className="activity-list">
          {investigationEvents.slice(-6).map(event => <div className="activity-row" key={event.sequence}>
            <span className={`activity-icon ${event.kind}`}><ChevronRight size={13}/></span><div><strong>{(event.action ?? '').replaceAll('_', ' ')}</strong><small>{String(event.detail?.reasoning_summary ?? event.detail?.root_cause ?? event.detail?.schedule ?? (event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''))}</small></div>
          </div>)}
          {investigation?.decision && <div className="agent-summary"><strong>{investigation.decision.concurrency_pattern ?? 'Concurrency Pattern'}</strong><p>{investigation.decision.reasoning_summary ?? ''}</p><small>Experiment: {investigation.decision.experiment_name ?? 'experiment'} · confidence {Math.round((investigation.decision.confidence ?? 0) * 100)}%</small></div>}
          {!investigationEvents.length && !investigation && <div className="empty-state"><Activity size={24}/><p>Waiting for a structured LLM hypothesis.</p></div>}
        </div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LOCAL COST CONTROL</span><h2>Model usage</h2></div><Gauge size={20}/></div>
        <div className="invariant-stats">
          <Metric label="Requests" value={usage?.total_requests ?? 0} accent/>
          <Metric label="Reported tokens" value={usage ? `${usage.total_tokens ?? 0}${usage.unknown_token_responses ? '+' : ''}` : '0'}/>
          <Metric label="Requests left" value={usage?.remaining_request_budget ?? modelStatus?.budgets?.max_model_requests ?? '-'}/>
        </div>
        <div className="agent-summary">
          <strong>Investigation: {report?.investigation_model || modelStatus?.investigation_model || 'loading'}</strong>
          <p>Repair: {report?.repair_model || modelStatus?.repair_model || 'loading'}</p>
          <small>Investigation requests {usage?.requests_by_agent?.investigation ?? 0} · Repair requests {usage?.requests_by_agent?.repair ?? 0} · Fallback {usage?.fallback_invocations ?? 0}</small>
        </div>
        <div className="schedule-caption"><AlertTriangle size={15}/><span>{usage?.unknown_token_responses ? 'Some provider token metadata is unavailable. Token totals are lower bounds.' : usage?.approximate_cost_usd != null ? `Verified configured estimate: $${usage.approximate_cost_usd.toFixed(6)}${usage.cost_is_partial ? ' partial' : ''}` : 'Dollar estimates stay hidden until verified pricing is configured.'}</span></div>
      </article>

      <article className="panel activity-panel">
        <div className="panel-head"><div><span className="kicker">LLM AGENT 2</span><h2>Repair Agent</h2></div><Code2 size={20}/></div>
        <div className="activity-list">
          {repairEvents.slice(-6).map(event => <div className="activity-row" key={event.sequence}>
            <span className={`activity-icon ${event.kind}`}><ChevronRight size={13}/></span><div><strong>{(event.action ?? '').replaceAll('_', ' ')}</strong><small>{String(event.detail?.strategy ?? (event.detail?.passed === true ? 'verification passed' : event.detail?.passed === false ? 'verification failed' : (event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '')))}</small></div>
          </div>)}
          {repairAttempt?.proposal && <div className="agent-summary"><strong>{repairAttempt.proposal.strategy ?? 'Repair Proposal'}</strong><p>{repairAttempt.proposal.diagnosis ?? ''}</p><small>{repairAttempt.failure_reason ?? 'Candidate awaiting deterministic gates'}</small></div>}
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
        {verification?.gates && <div className="gate-grid">{Object.entries(verification.gates).map(([name, passed]) => <div key={name} className={passed ? 'gate pass' : 'gate fail'}>{passed ? <Check size={13}/> : <X size={13}/>}<span>{(name ?? '').replaceAll('_', ' ')}</span></div>)}</div>}
      </article>
    </section>

    <SchedulePlayer events={events}/>

    {report && <div className="evidence-feature-grid">
      <DatabaseBehaviorComparison before={baseline} after={verification?.schedule_results?.[0]}/>
      <LockWaitVisualization result={verifiedSchedule}/>
      <DeadlockGraph result={verifiedSchedule}/>
    </div>}

    {report?.status === 'AWAITING_HUMAN_REVIEW' && <section className="panel review-panel">
      <div className="panel-head"><div><span className="kicker">HUMAN IN THE LOOP</span><h2>Review verified candidate</h2></div><ShieldCheck size={20}/></div>
      <p>Every deterministic gate passed. Review the complete evidence and diff below. The candidate is not approved until you decide.</p>
      <div className="review-summary"><span>Changed candidate</span><strong>{report.attempts.at(-1)?.proposal?.strategy ?? 'Verified repair'}</strong></div>
      <div className="invariant-stats">
        <Metric label="Gates passed" value={verification?.gates ? `${Object.values(verification.gates).filter(Boolean).length}/${Object.keys(verification.gates).length}` : '-'}/>
        <Metric label="Candidate p95" value={verification?.performance ? `${verification.performance.p95_latency_ms.toFixed(1)} ms` : '-'}/>
        <Metric label="Deadlocks" value={verification?.performance?.deadlocks ?? 0}/>
        <Metric label="Model requests" value={usage?.total_requests ?? 0} accent/>
      </div>
      {!!report.attempts.at(-1)?.proposal?.residual_risks?.length && <ul>{report.attempts.at(-1)?.proposal?.residual_risks.map(risk => <li key={risk}>{risk}</li>)}</ul>}
      <textarea value={reviewComment} onChange={event => setReviewComment(event.target.value)} placeholder="Reviewer comment or revision instructions"/>
      <div className="review-actions"><button className="approve" disabled={reviewSubmitting} onClick={() => submitReview('approve').catch(error => setError(error.message))}>{reviewSubmitting ? 'Submitting decision…' : 'Approve'}</button><button disabled={reviewSubmitting} onClick={() => submitReview('request_revision').catch(error => setError(error.message))}>Request revision</button><button className="reject" disabled={reviewSubmitting} onClick={() => submitReview('reject').catch(error => setError(error.message))}>Reject</button></div>
    </section>}

    {(report?.trace_url || report?.stage_timings_ms) && <section className="panel observability-panel">
      <div className="panel-head"><div><span className="kicker">OBSERVABILITY</span><h2>Trace and stage latency</h2></div><Clock size={20}/></div>
      {report.trace_url && <a className="trace-link" href={report.trace_url} target="_blank" rel="noreferrer"><ExternalLink size={14}/>Open trace in LangSmith</a>}
      <div className="timing-grid">{Object.entries(report.stage_timings_ms ?? {}).map(([name, duration]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{duration < 1000 ? `${Math.round(duration)} ms` : `${(duration / 1000).toFixed(2)} s`}</strong></div>)}</div>
    </section>}

    <section className="panel diff-panel">
      <div className="panel-head"><div><span className="kicker">REVIEWABLE ARTIFACT</span><h2>Candidate patch</h2></div><Code2 size={20}/></div>
      <pre>{report?.final_diff ?? 'No verified candidate diff. Live repair requires a configured model API key; failed or unverified patches are never promoted.'}</pre>
    </section>


    <footer><span>RaceProof experimental prototype</span><span>Finite tests establish observed evidence, not formal race freedom.</span>{runId && <span>RUN {runId}</span>}</footer>
  </main>
}

export default App

