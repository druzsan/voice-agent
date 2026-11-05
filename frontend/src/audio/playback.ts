import type { Audio } from '../api/conversations.ts'

export interface Playing {
  // Resolves when the clip has played to the end, failed, or was stopped
  done: Promise<void>
  stop: () => void
}

// Plays one reply clip
export function playClip(audio: Audio): Playing {
  const element = new window.Audio(`data:${audio.media_type};base64,${audio.wav_base64}`)
  let finish: () => void = () => undefined
  const done = new Promise<void>((resolve) => {
    finish = resolve
  })
  element.onended = finish
  element.onerror = finish
  // Autoplay rules can refuse playback; the text is shown anyway
  element.play().catch(finish)
  return {
    done,
    stop: () => {
      element.pause()
      finish()
    },
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
