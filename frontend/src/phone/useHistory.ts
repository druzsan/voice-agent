import { useRef, useState } from 'react'

import {
  type ConversationDetail,
  type ConversationSummary,
  fetchConversation,
  fetchConversations,
} from '../api/conversations.ts'
import { previousCalls } from './history.ts'

// Earlier calls, one at a time like a carousel: `older` steps back in time,
// `newer` forward and finally back to the phone. `index` is null while the
// phone itself shows.
export function useHistory(current: string | null) {
  const [calls, setCalls] = useState<ConversationSummary[]>([])
  const [index, setIndex] = useState<number | null>(null)
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  // Only the latest request may update the view, however fast the clicks
  const request = useRef(0)

  async function show(list: ConversationSummary[], position: number) {
    const call = list[position]
    if (call === undefined) {
      return
    }
    const mine = ++request.current
    setIndex(position)
    setDetail(null)
    setLoading(true)
    setNotice(null)
    try {
      const loaded = await fetchConversation(call.id)
      if (mine === request.current) {
        setDetail(loaded)
      }
    } catch {
      if (mine === request.current) {
        setNotice("Couldn't load this call.")
      }
    } finally {
      if (mine === request.current) {
        setLoading(false)
      }
    }
  }

  async function older() {
    let list = calls
    if (index === null) {
      try {
        // Fresh each time the history opens: the last call may have just ended
        list = previousCalls(await fetchConversations(), current)
      } catch {
        setNotice("Couldn't load the previous calls.")
        return
      }
      setCalls(list)
      if (list.length === 0) {
        setNotice('No previous calls yet.')
        return
      }
    }
    const next = index === null ? 0 : index + 1
    if (next < list.length) {
      await show(list, next)
    }
  }

  function close() {
    request.current++
    setIndex(null)
    setDetail(null)
    setLoading(false)
    setNotice(null)
  }

  function newer() {
    if (index === null) {
      return
    }
    if (index === 0) {
      close()
      return
    }
    void show(calls, index - 1)
  }

  return {
    calls,
    index,
    detail,
    loading,
    notice,
    hasOlder: index === null || index < calls.length - 1,
    older: () => void older(),
    newer,
    close,
  }
}
