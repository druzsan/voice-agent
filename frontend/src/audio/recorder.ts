import captureUrl from './captureWorklet.ts?worker&url'
import { encodeWav } from './pcm.ts'

export interface Recording {
  // Stops recording and returns the WAV, ready for the backend
  stop: () => Blob
  // Stops recording and throws the audio away
  cancel: () => void
}

// Records the microphone as 16 kHz PCM until stopped. The browser's echo
// cancellation and noise suppression clean up the signal first.
export async function startRecording(): Promise<Recording> {
  if (typeof navigator.mediaDevices === 'undefined') {
    throw new Error('This browser offers no microphone here (it needs https or localhost).')
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const context = new AudioContext()
  const chunks: Int16Array<ArrayBuffer>[] = []
  let node: AudioWorkletNode | null = null

  const release = () => {
    if (node) {
      node.port.onmessage = null
      node.port.close()
    }
    stream.getTracks().forEach((track) => {
      track.stop()
    })
    void context.close()
  }

  try {
    await context.audioWorklet.addModule(captureUrl)
    // Without outputs the node is still processed, and nothing is played
    node = new AudioWorkletNode(context, 'pcm-capture', { numberOfOutputs: 0 })
    node.port.onmessage = (event: MessageEvent<Int16Array<ArrayBuffer>>) => {
      chunks.push(event.data)
    }
    context.createMediaStreamSource(stream).connect(node)
  } catch (error) {
    release()
    throw error
  }

  return {
    stop: () => {
      release()
      return encodeWav(chunks)
    },
    cancel: release,
  }
}
