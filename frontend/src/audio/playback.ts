export interface Clip {
  clip: number
  wav_base64: string
  duration_ms: number
}

// A clip counts as heard from this share on, even if it's stopped
const HEARD_SHARE = 0.9

// Plays a reply's clips one after the other as they arrive, and reports
// each one the caller has heard, so the backend knows what was said
export class ClipPlayer {
  private readonly onPlayed: (clip: number) => void
  private readonly queue: Clip[] = []
  private current: { clip: Clip; element: HTMLAudioElement } | null = null

  constructor(onPlayed: (clip: number) => void) {
    this.onPlayed = onPlayed
  }

  enqueue(clip: Clip): void {
    this.queue.push(clip)
    if (this.current === null) {
      this.next()
    }
  }

  // Stops at once and drops the queued clips, e.g. when the caller interrupts
  stop(): void {
    this.queue.length = 0
    const current = this.current
    this.current = null
    if (current) {
      const { element, clip } = current
      if (element.duration > 0 && element.currentTime / element.duration >= HEARD_SHARE) {
        this.onPlayed(clip.clip)
      }
      element.pause()
    }
  }

  private next(): void {
    const clip = this.queue.shift()
    if (!clip) {
      this.current = null
      return
    }
    const element = new window.Audio(`data:audio/wav;base64,${clip.wav_base64}`)
    this.current = { clip, element }
    const advance = (played: boolean) => {
      if (this.current?.element !== element) {
        return
      }
      if (played) {
        this.onPlayed(clip.clip)
      }
      this.next()
    }
    element.onended = () => {
      advance(true)
    }
    // Unplayable or refused (autoplay rules): the text is shown anyway, and
    // the backend stops waiting for it after a while
    element.onerror = () => {
      advance(false)
    }
    element.play().catch(() => {
      advance(false)
    })
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
