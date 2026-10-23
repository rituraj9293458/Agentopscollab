export type RunEvent = {
  sequence: number
  timestamp: string
  kind: 'agent' | 'stage' | 'transaction' | 'checkpoint' | 'sql' | 'invariant' | 'repair' | 'verification' | 'error'
  stage: string
  actor: string | null
  action: string
  detail: Record<string, unknown>
}

export type InvariantResult = {
  name: string
  passed: boolean
  assertion: string
  evidence: Record<string, unknown>
  explanation: string
}

export type Target = {
  id: string
  name: string
  description: string
  operation: string
  actors: string[]
  invariant: { name: string; description: string; approved: true }
}

export type ScheduleResult = {
  schedule_name: string
  status: string
  exact: boolean
  completed: boolean
  reproduced_failure: boolean
  actor_outcomes: Record<string, string>
  events: RunEvent[]
  invariant: InvariantResult | null
  elapsed_ms: number
  error: string | null
}

export type Verification = {
  passed: boolean
  replay_mode: string
  gates: Record<string, boolean>
  performance?: {
    mean_latency_ms: number
    p95_latency_ms: number
    throughput_per_second: number
    deadlocks: number
  }
}

export type RunReport = {
  run_id: string
  status: string
  target_id: string
  target_name: string
  target_operation: string
  invariant_name: string
  invariant_description: string
  investigation_attempts: Array<{
    number: number
    decision: {
      suspected_source: string
      concurrency_pattern: string
      reasoning_summary: string
      experiment_name: string
      confidence: number
      supporting_evidence: string[]
    }
    result?: ScheduleResult
    failure_reason?: string
  }>
  investigation_artifact: {
    confirmed_vulnerability: boolean
    hypothesized_root_cause: string
    evidence_references: string[]
  } | null
  baseline: ScheduleResult | null
  final_diff: string | null
  attempts: Array<{
    number: number
    proposal?: { strategy: string; diagnosis: string }
    verification?: Verification
    failure_reason?: string
  }>
  limitations: string[]
}
