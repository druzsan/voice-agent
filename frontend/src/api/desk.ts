// The care desk's read-only view of the customer care system
// (backend/voice_agent/api/desk.py)

export type Topic = 'delivery' | 'charging' | 'connected_services' | 'warranty'
export type TicketStatus = 'open' | 'in_progress' | 'waiting_on_customer' | 'resolved' | 'closed'
export type Priority = 'normal' | 'high' | 'urgent' | 'safety'

export interface Note {
  author: 'carrie' | 'care_agent' | 'system'
  body: string
  created_at: string
}

export interface Ticket {
  number: number
  reference: string
  topic: Topic
  issue_type: string
  status: TicketStatus
  priority: Priority
  summary: string
  details: Record<string, unknown>
  customer_name: string | null
  postal_code: string | null
  vehicle_model: string | null
  order_number: string | null
  mobile_phone: string | null
  verification_status: string
  language: string
  conversation_id: string | null
  created_at: string
  updated_at: string
  notes: Note[]
}

export interface Handover {
  id: number
  conversation_id: string | null
  ticket_number: number | null
  route: string
  priority: Priority
  language: string
  reason: string
  summary: string
  details: Record<string, unknown>
  status: 'transferred' | 'unavailable'
  created_at: string
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, signal ? { signal } : {})
  if (!response.ok) {
    throw new Error(`The server answered with status ${String(response.status)}.`)
  }
  // The backend's response models guarantee the shape
  return (await response.json()) as T
}

export function fetchTickets(signal?: AbortSignal): Promise<Ticket[]> {
  return get<Ticket[]>('/api/desk/tickets', signal)
}

export function fetchHandovers(signal?: AbortSignal): Promise<Handover[]> {
  return get<Handover[]>('/api/desk/handovers', signal)
}
