import { type RefObject, useEffect, useReducer, useRef } from 'react'

import { callUrl, type ClientMessage, parseServerMessage } from '../api/callProtocol.ts'
import type { InputVia } from '../api/conversations.ts'
import { type Microphone, openMicrophone } from '../audio/microphone.ts'
import { ClipPlayer } from '../audio/playback.ts'
import { callReducer, initialCallState } from './callState.ts'

// What a running call holds on to, outside of React state
interface Handles {
  socket: WebSocket | null
  microphone: Microphone | null
  player: ClipPlayer | null
  muted: boolean
}

function send(socket: WebSocket | null, message: ClientMessage) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message))
  }
}

// Stops whatever is in progress: the connection, the microphone, the audio
function release(handles: RefObject<Handles>) {
  const current = handles.current
  const socket = current.socket
  current.socket = null
  if (socket) {
    socket.onmessage = null
    socket.onclose = null
    socket.onopen = null
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close(1000)
    }
  }
  current.microphone?.close()
  current.microphone = null
  current.player?.stop()
  current.player = null
}

function describeMicrophoneError(error: unknown): string {
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return 'The microphone is blocked. You can still type.'
  }
  if (error instanceof Error && error.message) {
    return `${error.message} You can still type.`
  }
  return 'The microphone is not available. You can still type.'
}

// A live phone call with the backend over one WebSocket: the microphone
// streams continuously, the backend notices when the caller stops talking,
// and its answer plays sentence by sentence as it's written
export function useCall() {
  const [state, dispatch] = useReducer(callReducer, initialCallState)
  const handles = useRef<Handles>({ socket: null, microphone: null, player: null, muted: false })

  async function listen(socket: WebSocket) {
    try {
      const microphone = await openMicrophone((frame) => {
        if (!handles.current.muted && socket.readyState === WebSocket.OPEN) {
          socket.send(frame)
        }
      })
      // Hung up while the browser asked for the microphone
      if (handles.current.socket !== socket) {
        microphone.close()
        return
      }
      handles.current.microphone = microphone
      dispatch({ type: 'microphone', available: true })
    } catch (error) {
      if (handles.current.socket === socket) {
        dispatch({ type: 'microphone', available: false, notice: describeMicrophoneError(error) })
      }
    }
  }

  function start() {
    release(handles)
    dispatch({ type: 'dial' })
    const socket = new WebSocket(callUrl())
    const player = new ClipPlayer((clip) => {
      send(socket, { type: 'played', clip })
    })
    handles.current = { socket, microphone: null, player, muted: false }

    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') {
        return
      }
      const message = parseServerMessage(event.data)
      if (message === null) {
        return
      }
      if (message.type === 'audio') {
        player.enqueue(message)
      } else if (message.type === 'interrupted') {
        player.stop()
      }
      dispatch({ type: 'received', message, at: Date.now() })
      if (message.type === 'call_ended') {
        release(handles)
      }
    }
    socket.onclose = () => {
      release(handles)
      dispatch({ type: 'disconnected', at: Date.now() })
    }
    // Asked for at once, so the browser's prompt shows while the call connects
    void listen(socket)
  }

  function type(text: string, via: InputVia) {
    send(handles.current.socket, { type: 'text', text, via })
  }

  function toggleMute() {
    const muted = !handles.current.muted
    handles.current.muted = muted
    send(handles.current.socket, { type: 'mute', muted })
    dispatch({ type: 'muted', muted })
  }

  function hangUp() {
    // Sent before the connection closes, so the call ends as hung up
    send(handles.current.socket, { type: 'hangup' })
    release(handles)
    dispatch({ type: 'hungUp', at: Date.now() })
  }

  useEffect(() => {
    // Closing the page closes the connection, which ends the call
    return () => {
      release(handles)
    }
  }, [])

  return { state, start, type, toggleMute, hangUp }
}
