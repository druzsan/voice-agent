import captureUrl from './captureWorklet.ts?worker&url'

export interface Microphone {
  // Releases the microphone
  close: () => void
}

// Streams the microphone as 16 kHz PCM frames of 32 ms until closed. The
// browser's echo cancellation and noise suppression clean up the signal
// first; echo cancellation also keeps the assistant's own voice out of the
// microphone as far as the browser manages (headphones work best).
export async function openMicrophone(
  onFrame: (pcm: Int16Array<ArrayBuffer>) => void,
): Promise<Microphone> {
  if (typeof navigator.mediaDevices === 'undefined') {
    throw new Error('This browser offers no microphone here (it needs https or localhost).')
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const context = new AudioContext()
  let node: AudioWorkletNode | null = null

  const close = () => {
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
      onFrame(event.data)
    }
    context.createMediaStreamSource(stream).connect(node)
    // A context created without a click on the page starts suspended
    await context.resume()
  } catch (error) {
    close()
    throw error
  }
  return { close }
}
