import { describe, expect, it } from 'vitest'

import { Downsampler, encodeWav } from './pcm.ts'

describe('Downsampler', () => {
  it('turns 48 kHz into 16 kHz by averaging every three samples', () => {
    const downsampler = new Downsampler(48000)

    const pcm = downsampler.push(new Float32Array([0, 0.5, 1, -1, -1, -1]))

    expect(Array.from(pcm)).toEqual([Math.round(0.5 * 32767), -32767])
  })

  it('carries partial samples over to the next chunk', () => {
    const downsampler = new Downsampler(48000)

    expect(downsampler.push(new Float32Array([1, 1])).length).toBe(0)
    expect(Array.from(downsampler.push(new Float32Array([1])))).toEqual([32767])
  })

  it('refuses to upsample', () => {
    expect(() => new Downsampler(8000)).toThrow(RangeError)
  })
})

describe('encodeWav', () => {
  it('writes a 16 kHz mono 16-bit WAV header before the samples', async () => {
    const wav = encodeWav([new Int16Array([1, 2]), new Int16Array([3])])
    const view = new DataView(await wav.arrayBuffer())
    const text = (offset: number) => String.fromCharCode(...new Uint8Array(view.buffer, offset, 4))

    expect(wav.type).toBe('audio/wav')
    expect(view.byteLength).toBe(44 + 6)
    expect([text(0), text(8), text(12), text(36)]).toEqual(['RIFF', 'WAVE', 'fmt ', 'data'])
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getUint32(40, true)).toBe(6)
    expect([44, 46, 48].map((offset) => view.getInt16(offset, true))).toEqual([1, 2, 3])
  })
})
