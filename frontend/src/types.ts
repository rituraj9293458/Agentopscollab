export type RunEvent = {
  sequence: number
  timestamp: string
  kind: 'stage' | 'transaction' | 'checkpoint' | 'sql' | 'invariant' | 'repair' | 'verification' | 'error'
  stage: string
  actor: string | null
  action: string
  detail: Record<string, unknown>
}

export type InvariantResult = {
  passed: boolean
  initial_stock: number
  successful_orders: number
  final_stock: number
  explanation: string
}

export type ScheduleResult = {
  schedule_name: string
  exact: boolean
  completed: boolean
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
  target_operation: string
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

