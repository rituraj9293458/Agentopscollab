export type RunEvent = {
  sequence: number
  timestamp: string
  kind: 'agent' | 'stage' | 'transaction' | 'checkpoint' | 'sql' | 'invariant' | 'repair' | 'verification' | 'error' | 'usage'
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
  lock_waits: Array<{
    waiting_actor: string
    blocking_actors: string[]
    lock_type: string
    lock_mode: string
    relation: string | null
    duration_ms: number
    release_point: string | null
    deadlock: boolean
  }>
  wait_for_edges: Array<{
    waiting_actor: string
    blocking_actor: string
    lock_type: string
    lock_mode: string
  }>
  deadlock_cycle: boolean
}

export type Verification = {
  passed: boolean
  replay_mode: string
  gates: Record<string, boolean>
  schedule_results: ScheduleResult[]
  lock_evidence_results: ScheduleResult[]
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
    proposal?: {
      strategy: string
      diagnosis: string
      assumptions: string[]
      residual_risks: string[]
    }
    verification?: Verification
    failure_reason?: string
  }>
  limitations: string[]
  investigation_model: string
  repair_model: string
  fallback_model: string | null
  fallback_enabled: boolean
  usage: UsageSnapshot
  human_review: { decision: string; comment: string; decided_at?: string } | null
  trace_url: string | null
  stage_timings_ms: Record<string, number>
}

export type UsageSnapshot = {
  total_requests: number
  requests_by_agent: Record<string, number>
  requests_by_model: Record<string, number>
  input_tokens: number
  output_tokens: number
  total_tokens: number
  unknown_token_responses: number
  failed_requests: number
  rate_limit_errors: number
  fallback_invocations: number
  remaining_request_budget: number
  remaining_investigation_budget: number
  remaining_repair_budget: number
  remaining_token_budget: number
  budget_exhausted: boolean
  warnings: string[]
  approximate_cost_usd: number | null
  cost_is_partial: boolean
}

export type ModelStatus = {
  key_configured: boolean
  investigation_model: string
  repair_model: string
  fallback_model: string
  fallback_enabled: boolean
  budgets: Record<string, number>
  langsmith?: { configured: boolean; tracing: boolean; project: string }
}

export type CustomTargetProposal = {
  target_id: string
  status: string
  analysis_mode: string
  execution_ready: boolean
  selected_operation: {
    entrypoint: string
    file: string
    function: string
    line: number
    signals: string[]
    risk: string
  } | null
  operation_candidates: Array<Record<string, unknown>>
  actors: Array<{ id: string; input: Record<string, unknown> }>
  proposed_invariant: {
    name: string
    description: string
    assertion: string
    approved: boolean
  }
  reproduction_schedule: { name: string; description: string; checkpoints: string[] }
  editable_paths: string[]
  protected_paths: string[]
  warnings: string[]
  files: string[]
  execution_blocker: string
}
