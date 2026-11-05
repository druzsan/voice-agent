import { type RefObject, useEffect, useReducer, useRef } from 'react'

import {
  ApiError,
  type Audio,
  endConversation,
  type InputVia,
  sendRecording,
  sendText,
  startConversation,
  type TurnResponse,
} from '../api/conversations.ts'
import { playClip, type Playing } from '../audio/playback.ts'
import { type Recording, startRecording } from '../audio/recorder.ts'
import { callReducer, initialCallState } from './callState.ts'

type Send = (conversationId: string, signal: AbortSignal) => Promise<TurnResponse>

// What a running call holds on to, outside of React state
interface Handles {
  conversationId: string | null
  request: AbortController | null
  recording: Recording | null
  recordingTimer: number | null
  playing: Playing | null
}

// Stops whatever is in progress: the request, the microphone, the audio
function release(handles: RefObject<Handles>) {
  const current = handles.current
  current.request?.abort()
  current.request = null
  if (current.recordingTimer !== null) {
    window.clearTimeout(current.recordingTimer)
    current.recordingTimer = null
  }
  current.recording?.cancel()
  current.recording = null
  current.playing?.stop()
  current.playing = null
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return 'The microphone is blocked. You can still type.'
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return 'Something went wrong. Please try again.'
}

// A phone call with the backend: dial, talk or type turn by turn, hang up
export function useCall(maxRecordingS: number) {
  const [state, dispatch] = useReducer(callReducer, initialCallState)
  const handles = useRef<Handles>({
    conversationId: null,
    request: null,
    recording: null,
    recordingTimer: null,
    playing: null,
  })

  async function play(audio: Audio | null) {
    if (audio) {
      const playing = playClip(audio)
      handles.current.playing = playing
      await playing.done
      handles.current.playing = null
    }
    dispatch({ type: 'played' })
  }

  async function start() {
    const controller = new AbortController()
    handles.current.request = controller
    dispatch({ type: 'start' })
    try {
      const started = await startConversation(controller.signal)
      handles.current.conversationId = started.conversation.id
      dispatch({
        type: 'started',
        conversationId: started.conversation.id,
        greeting: started.greeting,
        at: Date.now(),
      })
      await play(started.audio)
    } catch (error) {
      if (!controller.signal.aborted) {
        dispatch({ type: 'startFailed', notice: `Couldn't start the call. ${describe(error)}` })
      }
    }
  }

  async function turn(send: Send) {
    const conversationId = handles.current.conversationId
    if (conversationId === null) {
      return
    }
    const controller = new AbortController()
    handles.current.request = controller
    dispatch({ type: 'sending' })
    try {
      const answer = await send(conversationId, controller.signal)
      dispatch({ type: 'answered', user: answer.user_message, assistant: answer.assistant_message })
      await play(answer.audio)
    } catch (error) {
      if (!controller.signal.aborted) {
        dispatch({ type: 'failed', notice: describe(error) })
      }
    }
  }

  function stopTalking() {
    const current = handles.current
    if (current.recordingTimer !== null) {
      window.clearTimeout(current.recordingTimer)
      current.recordingTimer = null
    }
    const recording = current.recording
    if (recording === null) {
      return
    }
    current.recording = null
    const wav = recording.stop()
    void turn((conversationId, signal) => sendRecording(conversationId, wav, signal))
  }

  async function talk() {
    try {
      const recording = await startRecording()
      // Hung up while the browser asked for the microphone
      if (handles.current.conversationId === null) {
        recording.cancel()
        return
      }
      handles.current.recording = recording
      dispatch({ type: 'recording' })
      // Stop shortly before the backend's limit, so the recording is accepted
      handles.current.recordingTimer = window.setTimeout(
        stopTalking,
        Math.max(1, maxRecordingS - 0.5) * 1000,
      )
    } catch (error) {
      dispatch({ type: 'failed', notice: describe(error) })
    }
  }

  function type(text: string, via: InputVia) {
    void turn((conversationId, signal) => sendText(conversationId, text, via, signal))
  }

  function hangUp() {
    release(handles)
    const conversationId = handles.current.conversationId
    handles.current.conversationId = null
    if (conversationId !== null) {
      // The backend waits for a running turn before it ends the call
      endConversation(conversationId, 'hangup').catch(() => undefined)
    }
    dispatch({ type: 'hungUp', at: Date.now() })
  }

  useEffect(() => {
    // Closing the page ends the call too, as far as the browser still lets us
    const onPageHide = () => {
      const conversationId = handles.current.conversationId
      if (conversationId !== null) {
        navigator.sendBeacon(
          `/api/conversations/${conversationId}/end`,
          new Blob([JSON.stringify({ reason: 'page_closed' })], { type: 'application/json' }),
        )
      }
    }
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      // Free the microphone and stop the audio when the view goes away
      release(handles)
    }
  }, [])

  return {
    state,
    start: () => void start(),
    talk: () => void talk(),
    stopTalking,
    type,
    hangUp,
  }
}
