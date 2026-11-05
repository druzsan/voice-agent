// The backend's recording format: 16 kHz mono 16-bit PCM in a WAV file
export const SAMPLE_RATE = 16000

// Turns microphone samples at the device rate into 16 kHz PCM. Each output
// sample averages the input samples it covers, which also removes most
// frequencies the lower rate can't carry.
export class Downsampler {
  private readonly step: number
  private position = 0
  private sum = 0
  private count = 0

  constructor(inputRate: number) {
    if (inputRate < SAMPLE_RATE) {
      throw new RangeError(`Cannot upsample from ${String(inputRate)} Hz`)
    }
    this.step = inputRate / SAMPLE_RATE
  }

  push(samples: Float32Array): Int16Array<ArrayBuffer> {
    const output = new Int16Array(Math.ceil(samples.length / this.step) + 1)
    let filled = 0
    for (const sample of samples) {
      this.sum += sample
      this.count += 1
      this.position += 1
      if (this.position < this.step) {
        continue
      }
      this.position -= this.step
      const value = Math.max(-1, Math.min(1, this.sum / this.count))
      this.sum = 0
      this.count = 0
      output[filled] = Math.round(value * 32767)
      filled += 1
    }
    return output.slice(0, filled)
  }
}

// Little-endian PCM in a WAV container (Int16Array is little-endian on all
// platforms browsers run on)
export function encodeWav(
  chunks: readonly Int16Array<ArrayBuffer>[],
  sampleRate = SAMPLE_RATE,
): Blob {
  const samples = chunks.reduce((total, chunk) => total + chunk.length, 0)
  const header = new DataView(new ArrayBuffer(44))
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      header.setUint8(offset + index, value.charCodeAt(index))
    }
  }
  text(0, 'RIFF')
  header.setUint32(4, 36 + samples * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  header.setUint32(16, 16, true) // fmt chunk size
  header.setUint16(20, 1, true) // PCM
  header.setUint16(22, 1, true) // mono
  header.setUint32(24, sampleRate, true)
  header.setUint32(28, sampleRate * 2, true) // bytes per second
  header.setUint16(32, 2, true) // bytes per frame
  header.setUint16(34, 16, true) // bits per sample
  text(36, 'data')
  header.setUint32(40, samples * 2, true)
  return new Blob([header, ...chunks], { type: 'audio/wav' })
}
