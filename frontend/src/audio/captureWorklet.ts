// Runs on the audio rendering thread: passes the microphone on to the page
// as 16 kHz PCM frames of 32 ms
import { Downsampler, Framer } from './pcm.ts'

// Globals of the audio worklet scope, which TypeScript's DOM types lack
declare const sampleRate: number
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}
declare function registerProcessor(name: string, processor: new () => AudioWorkletProcessor): void

class PcmCapture extends AudioWorkletProcessor {
  private readonly downsampler = new Downsampler(sampleRate)
  private readonly framer = new Framer()

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (channel) {
      for (const frame of this.framer.push(this.downsampler.push(channel))) {
        this.port.postMessage(frame, [frame.buffer])
      }
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCapture)
