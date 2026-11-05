// Runs on the audio rendering thread: passes the microphone on to the page
// as 16 kHz PCM chunks
import { Downsampler } from './pcm.ts'

// Globals of the audio worklet scope, which TypeScript's DOM types lack
declare const sampleRate: number
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}
declare function registerProcessor(name: string, processor: new () => AudioWorkletProcessor): void

class PcmCapture extends AudioWorkletProcessor {
  private readonly downsampler = new Downsampler(sampleRate)

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (channel) {
      const pcm = this.downsampler.push(channel)
      if (pcm.length > 0) {
        this.port.postMessage(pcm, [pcm.buffer])
      }
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCapture)
