// A piece of a spoken sentence (clip): mono 16-bit PCM
export interface AudioPiece {
  clip: number
  samples: Int16Array
  sampleRate: number
}

interface Clip {
  id: number
  // Audio held back until enough has arrived to play without a gap
  waiting: AudioBuffer[]
  waitingSeconds: number
  sources: Set<AudioBufferSourceNode>
  // Context time of its first sample and after its last one
  start: number | null
  end: number
  // The server sent all of its audio
  complete: boolean
  reported: boolean
}

// A clip counts as heard from this share on, even if it's stopped
const HEARD_SHARE = 0.9
// Pieces are scheduled slightly ahead, so they join without a click
const LEAD_SECONDS = 0.05
// A sentence's first piece is short and the next follows a moment later,
// so its playback waits for this much audio, or for the whole sentence
const START_SECONDS = 0.3

// Plays a reply's sentences one after the other while their audio still
// arrives, and reports each one the caller has heard, so the backend knows
// what was said
export class ClipPlayer {
  private readonly onPlayed: (clip: number) => void
  private readonly createContext: () => AudioContext | null
  private context: AudioContext | null = null
  private clips: Clip[] = []
  // Context time at which the next piece starts
  private cursor = 0

  constructor(
    onPlayed: (clip: number) => void,
    // None where the browser has no Web Audio: the text is shown anyway
    createContext: () => AudioContext | null = () =>
      typeof AudioContext === 'undefined' ? null : new AudioContext(),
  ) {
    this.onPlayed = onPlayed
    this.createContext = createContext
  }

  // Browsers allow sound only after a user gesture: call this from one
  unlock(): void {
    void this.ensureContext()?.resume()
  }

  append({ clip: id, samples, sampleRate }: AudioPiece): void {
    const context = this.ensureContext()
    if (!context || samples.length === 0) {
      return
    }
    const clip = this.clip(id)
    const buffer = context.createBuffer(1, samples.length, sampleRate)
    const channel = buffer.getChannelData(0)
    for (let index = 0; index < samples.length; index += 1) {
      channel[index] = (samples[index] ?? 0) / 32768
    }
    if (clip.start === null) {
      clip.waiting.push(buffer)
      clip.waitingSeconds += buffer.duration
      if (clip.waitingSeconds >= START_SECONDS) {
        this.release(context, clip)
      }
    } else {
      this.schedule(context, clip, buffer)
    }
  }

  // The clip's last piece has arrived
  end(id: number): void {
    const clip = this.clip(id)
    clip.complete = true
    if (this.context) {
      this.release(this.context, clip)
    }
    this.reportIfPlayed(clip)
  }

  // Stops at once and drops the queued audio, e.g. when the caller interrupts
  stop(): void {
    const now = this.context?.currentTime ?? 0
    for (const clip of this.clips) {
      if (
        clip.complete &&
        clip.start !== null &&
        now - clip.start >= HEARD_SHARE * (clip.end - clip.start)
      ) {
        this.report(clip)
      }
      for (const source of clip.sources) {
        source.onended = null
        source.stop()
      }
    }
    this.clips = []
    this.cursor = 0
  }

  private ensureContext(): AudioContext | null {
    this.context ??= this.createContext()
    return this.context
  }

  private clip(id: number): Clip {
    let clip = this.clips.find((candidate) => candidate.id === id)
    if (!clip) {
      clip = {
        id,
        waiting: [],
        waitingSeconds: 0,
        sources: new Set(),
        start: null,
        end: 0,
        complete: false,
        reported: false,
      }
      this.clips.push(clip)
    }
    return clip
  }

  private release(context: AudioContext, clip: Clip): void {
    const waiting = clip.waiting
    clip.waiting = []
    clip.waitingSeconds = 0
    for (const buffer of waiting) {
      this.schedule(context, clip, buffer)
    }
  }

  private schedule(context: AudioContext, clip: Clip, buffer: AudioBuffer): void {
    const start = Math.max(this.cursor, context.currentTime + LEAD_SECONDS)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.onended = () => {
      clip.sources.delete(source)
      this.reportIfPlayed(clip)
    }
    source.start(start)
    clip.sources.add(source)
    clip.start ??= start
    clip.end = start + buffer.duration
    this.cursor = clip.end
  }

  private reportIfPlayed(clip: Clip): void {
    if (clip.complete && clip.sources.size === 0 && clip.waiting.length === 0) {
      this.report(clip)
      this.clips = this.clips.filter((candidate) => candidate !== clip)
    }
  }

  private report(clip: Clip): void {
    if (!clip.reported) {
      clip.reported = true
      this.onPlayed(clip.id)
    }
  }
}

let tones: AudioContext | null = null

// The two-tone sound of a phone key (DTMF)
const DTMF: Record<string, readonly [number, number]> = {
  '1': [697, 1209],
  '2': [697, 1336],
  '3': [697, 1477],
  '4': [770, 1209],
  '5': [770, 1336],
  '6': [770, 1477],
  '7': [852, 1209],
  '8': [852, 1336],
  '9': [852, 1477],
  '*': [941, 1209],
  '0': [941, 1336],
  '#': [941, 1477],
}

export function playKeyTone(key: string): void {
  const frequencies = DTMF[key]
  if (!frequencies || typeof AudioContext === 'undefined') {
    return
  }
  tones ??= new AudioContext()
  const context = tones
  const gain = context.createGain()
  gain.gain.value = 0.08
  gain.connect(context.destination)
  const end = context.currentTime + 0.12
  for (const frequency of frequencies) {
    const oscillator = context.createOscillator()
    oscillator.frequency.value = frequency
    oscillator.connect(gain)
    oscillator.start()
    oscillator.stop(end)
  }
}
