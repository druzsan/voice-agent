import { describe, expect, it } from 'vitest'

import type { Usage } from '../api/callProtocol.ts'
import { addTurn, addUsage, emptyStats, formatCost, stageTiming, totalCost } from './dialogStats.ts'

function usage(overrides: Partial<Usage>): Usage {
  return {
    service: 'tts',
    model: 'tts-model',
    calls: 1,
    input_tokens: 0,
    output_tokens: 0,
    audio_in_s: 0,
    audio_out_s: 0,
    duration_ms: 0,
    cost_usd: 0,
    ...overrides,
  }
}

describe('dialog stats', () => {
  it('adds up every turn per service', () => {
    let stats = emptyStats()
    stats = addUsage(stats, [
      usage({
        service: 'llm',
        model: 'llm-a',
        input_tokens: 100,
        output_tokens: 20,
        cost_usd: 0.01,
      }),
      usage({ audio_out_s: 2, duration_ms: 900, cost_usd: 0.002 }),
    ])
    stats = addUsage(stats, [
      usage({
        service: 'llm',
        model: 'llm-a',
        input_tokens: 150,
        output_tokens: 30,
        cost_usd: 0.02,
      }),
    ])

    expect(stats.services.llm).toMatchObject({
      models: ['llm-a'],
      calls: 2,
      inputTokens: 250,
      outputTokens: 50,
      unpriced: false,
    })
    expect(stats.services.llm.costUsd).toBeCloseTo(0.03)
    expect(stats.services.tts.audioOutS).toBe(2)
    expect(totalCost(stats).costUsd).toBeCloseTo(0.032)
  })

  it('marks the cost as a lower bound when a price is unknown', () => {
    const stats = addUsage(emptyStats(), [
      usage({ service: 'stt', cost_usd: 0.01 }),
      usage({ service: 'stt', model: 'other', cost_usd: null }),
    ])

    expect(stats.services.stt.models).toEqual(['tts-model', 'other'])
    expect(totalCost(stats)).toEqual({ costUsd: 0.01, unpriced: true })
    expect(formatCost(0.01, true)).toBe('≥ $0.010')
  })

  it('averages a stage over the turns that have it', () => {
    let stats = addTurn(emptyStats(), { first_audio: 1000 })
    stats = addTurn(stats, { stt: 500, first_audio: 3000 })

    expect(stageTiming(stats, 'first_audio')).toEqual({ meanMs: 2000, lastMs: 3000, turns: 2 })
    expect(stageTiming(stats, 'stt')).toEqual({ meanMs: 500, lastMs: 500, turns: 1 })
    expect(stageTiming(stats, 'llm_first_token')).toBeNull()
  })

  it('formats small costs', () => {
    expect(formatCost(0, false)).toBe('$0')
    expect(formatCost(0.00001, false)).toBe('<$0.0001')
    expect(formatCost(0.0123, false)).toBe('$0.012')
    expect(formatCost(0.00456, false)).toBe('$0.0046')
  })
})
