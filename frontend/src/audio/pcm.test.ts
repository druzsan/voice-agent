import { describe, expect, it } from 'vitest'

import { Downsampler, Framer } from './pcm.ts'

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

describe('Framer', () => {
  it('hands out full frames and keeps the rest for later', () => {
    const framer = new Framer(4)

    expect(framer.push(new Int16Array([1, 2, 3]))).toEqual([])
    const frames = framer.push(new Int16Array([4, 5, 6, 7, 8, 9, 10]))

    expect(frames.map((frame) => Array.from(frame))).toEqual([
      [1, 2, 3, 4],
      [5, 6, 7, 8],
    ])
    expect(Array.from(framer.push(new Int16Array([11, 12]))[0] ?? [])).toEqual([9, 10, 11, 12])
  })
})
