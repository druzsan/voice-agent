// The backend's audio format: 16 kHz mono 16-bit PCM
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

// Cuts PCM into frames of a fixed number of samples, like the backend's
// voice detection scores them (512 samples, 32 ms)
export const FRAME_SAMPLES = 512

export class Framer {
  private readonly size: number
  private frame: Int16Array<ArrayBuffer>
  private filled = 0

  constructor(size = FRAME_SAMPLES) {
    this.size = size
    this.frame = new Int16Array(size)
  }

  push(samples: Int16Array): Int16Array<ArrayBuffer>[] {
    const frames: Int16Array<ArrayBuffer>[] = []
    let offset = 0
    while (offset < samples.length) {
      const taken = Math.min(this.size - this.filled, samples.length - offset)
      this.frame.set(samples.subarray(offset, offset + taken), this.filled)
      this.filled += taken
      offset += taken
      if (this.filled === this.size) {
        frames.push(this.frame)
        this.frame = new Int16Array(this.size)
        this.filled = 0
      }
    }
    return frames
  }
}
