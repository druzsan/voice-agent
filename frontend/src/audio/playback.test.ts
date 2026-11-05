import { describe, expect, it } from 'vitest'

import { decodePcm } from './pcm.ts'
import { ClipPlayer } from './playback.ts'

// Just enough of the Web Audio API to see what's scheduled when
class FakeSource {
  buffer: { duration: number } | null = null
  onended: (() => void) | null = null
  startedAt: number | null = null
  stopped = false
  connect = () => this
  start(when: number) {
    this.startedAt = when
  }
  stop() {
    this.stopped = true
  }
  // The context reached the end of the buffer
  finish() {
    this.onended?.()
  }
}

class FakeContext {
  currentTime = 0
  resumed = 0
  readonly destination = {}
  readonly sources: FakeSource[] = []
  createBuffer(_channels: number, length: number, sampleRate: number) {
    const data = new Float32Array(length)
    return { duration: length / sampleRate, getChannelData: () => data }
  }
  createBufferSource() {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  resume() {
    this.resumed += 1
    return Promise.resolve()
  }
}

function setup() {
  const context = new FakeContext()
  const played: number[] = []
  const player = new ClipPlayer(
    (clip) => {
      played.push(clip)
    },
    () => context as unknown as AudioContext,
  )
  return { context, played, player }
}

// `seconds` of audio at 10 kHz
function piece(clip: number, seconds: number) {
  return { clip, samples: new Int16Array(seconds * 10000), sampleRate: 10000 }
}

describe('ClipPlayer', () => {
  it('waits for enough audio before a sentence starts', () => {
    const { context, player } = setup()

    player.append(piece(1, 0.1))
    player.append(piece(1, 0.1))
    expect(context.sources).toHaveLength(0)
    player.append(piece(1, 0.1))

    // Back to back, slightly ahead of now
    expect(context.sources.map((source) => source.startedAt)).toEqual([
      0.05,
      expect.closeTo(0.15),
      expect.closeTo(0.25),
    ])
  })

  it('plays a short sentence once it is complete', () => {
    const { context, player } = setup()

    player.append(piece(1, 0.1))
    player.end(1)

    expect(context.sources).toHaveLength(1)
  })

  it('plays the sentences one after the other', () => {
    const { context, player } = setup()

    player.append(piece(1, 0.5))
    player.end(1)
    player.append(piece(2, 0.5))
    player.end(2)

    expect(context.sources.map((source) => source.startedAt)).toEqual([0.05, expect.closeTo(0.55)])
  })

  it('reports a sentence once it is complete and has played', () => {
    const { context, played, player } = setup()

    player.append(piece(1, 0.5))
    context.sources[0]?.finish()
    expect(played).toEqual([])
    player.append(piece(1, 0.5))
    player.end(1)
    context.sources[1]?.finish()

    expect(played).toEqual([1])
  })

  it('counts a stopped sentence as heard from 90 % on', () => {
    const { context, played, player } = setup()
    player.append(piece(1, 1))
    player.end(1)
    player.append(piece(2, 1))
    player.end(2)

    context.currentTime = 0.05 + 0.95
    player.stop()

    expect(played).toEqual([1])
    expect(context.sources.every((source) => source.stopped)).toBe(true)
    // Nothing of the dropped reply plays on
    player.append(piece(3, 0.5))
    expect(context.sources[2]?.startedAt).toBe(0.05 + 0.95 + 0.05)
  })

  it('asks the browser to allow sound', () => {
    const { context, player } = setup()

    player.unlock()

    expect(context.resumed).toBe(1)
  })
})

describe('decodePcm', () => {
  it('reads little-endian 16-bit samples', () => {
    // 1, -2, 32767
    const base64 = btoa(String.fromCharCode(0x01, 0x00, 0xfe, 0xff, 0xff, 0x7f))

    expect(Array.from(decodePcm(base64))).toEqual([1, -2, 32767])
  })
})
