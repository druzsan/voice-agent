import type { Service, Usage } from '../api/callProtocol.ts'

export const SERVICES: readonly Service[] = ['stt', 'llm', 'tts']

export interface ServiceTotals {
  models: string[]
  calls: number
  inputTokens: number
  outputTokens: number
  audioInS: number
  audioOutS: number
  durationMs: number
  // Of the calls with a known price
  costUsd: number
  // Some calls have no known price, so the cost is at least costUsd
  unpriced: boolean
}

// What the whole dialog consumed, and how long its turns took
export interface DialogStats {
  services: Record<Service, ServiceTotals>
  // Stage timings of each finished turn, in milliseconds
  turns: Record<string, number>[]
}

function emptyTotals(): ServiceTotals {
  return {
    models: [],
    calls: 0,
    inputTokens: 0,
    outputTokens: 0,
    audioInS: 0,
    audioOutS: 0,
    durationMs: 0,
    costUsd: 0,
    unpriced: false,
  }
}

export function emptyStats(): DialogStats {
  return { services: { stt: emptyTotals(), llm: emptyTotals(), tts: emptyTotals() }, turns: [] }
}

export function addUsage(stats: DialogStats, usages: readonly Usage[]): DialogStats {
  if (usages.length === 0) {
    return stats
  }
  const services = { ...stats.services }
  for (const usage of usages) {
    const totals = services[usage.service]
    services[usage.service] = {
      models: totals.models.includes(usage.model) ? totals.models : [...totals.models, usage.model],
      calls: totals.calls + usage.calls,
      inputTokens: totals.inputTokens + usage.input_tokens,
      outputTokens: totals.outputTokens + usage.output_tokens,
      audioInS: totals.audioInS + usage.audio_in_s,
      audioOutS: totals.audioOutS + usage.audio_out_s,
      durationMs: totals.durationMs + usage.duration_ms,
      costUsd: totals.costUsd + (usage.cost_usd ?? 0),
      unpriced: totals.unpriced || usage.cost_usd === null,
    }
  }
  return { ...stats, services }
}

export function addTurn(stats: DialogStats, timings: Record<string, number>): DialogStats {
  return { ...stats, turns: [...stats.turns, timings] }
}

export function totalCost(stats: DialogStats): { costUsd: number; unpriced: boolean } {
  const totals = SERVICES.map((service) => stats.services[service])
  return {
    costUsd: totals.reduce((sum, totals) => sum + totals.costUsd, 0),
    unpriced: totals.some((totals) => totals.unpriced),
  }
}

// Mean and last value of a stage over the turns that have it
export function stageTiming(
  stats: DialogStats,
  stage: string,
): { meanMs: number; lastMs: number; turns: number } | null {
  const values = stats.turns.flatMap((timings) => {
    const value = timings[stage]
    return value === undefined ? [] : [value]
  })
  const last = values.at(-1)
  if (last === undefined) {
    return null
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length
  return { meanMs: Math.round(mean), lastMs: last, turns: values.length }
}

// USD, with enough digits for the fractions of a cent a turn costs
export function formatCost(costUsd: number, unpriced: boolean): string {
  const amount =
    costUsd === 0
      ? '$0'
      : costUsd < 0.0001
        ? '<$0.0001'
        : `$${costUsd.toFixed(costUsd < 0.01 ? 4 : 3)}`
  return unpriced ? `≥ ${amount}` : amount
}
