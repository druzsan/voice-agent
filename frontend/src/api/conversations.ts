// The backend's REST API (backend/voice_agent/api/). Calls themselves run
// over the WebSocket in callProtocol.ts.

export type Role = 'user' | 'assistant'
export type Source = 'voice' | 'keyboard' | 'keypad' | 'llm' | 'template'
export type InputVia = 'keyboard' | 'keypad'
export type EndReason = 'hangup' | 'page_closed' | 'disconnect' | 'timeout' | 'error'

export interface Status {
  database: 'ok' | 'error'
  llm: { provider: string; model: string | null; configured: boolean }
  // fallback_model: push-to-talk, and live calls when live recognition fails
  stt: { provider: string; model: string; fallback_model: string | null; max_recording_s: number }
  tts: { provider: string; model: string; speed: number | null }
}

export async function fetchStatus(signal?: AbortSignal): Promise<Status> {
  const response = await fetch('/api/status', signal ? { signal } : {})
  if (!response.ok) {
    throw new Error(`The server answered with status ${String(response.status)}.`)
  }
  // The backend's response model guarantees the shape
  return (await response.json()) as Status
}
