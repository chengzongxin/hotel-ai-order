import { computed, nextTick, ref, type Ref } from 'vue'
import type { ChatMessage, ConversationMessagePayload, Role, SessionSummary, ToolCallRecord } from '../types/order'
import { createSessionId } from '../utils/sessionId'

export const SESSION_KEY = 'order_voice_session_id'
export const HISTORY_KEY = 'order_voice_history_sessions'

export function currentTime(): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

export function loadHistorySessions(): SessionSummary[] {
  try {
    const saved = localStorage.getItem(HISTORY_KEY)
    return saved ? JSON.parse(saved) : []
  } catch {
    return []
  }
}

export function mapHistoryRole(role: string): Role | null {
  if (role === 'human' || role === 'user') return 'user'
  if (role === 'ai' || role === 'assistant') return 'assistant'
  return null
}

export function useChatSession(chatBodyRef: Ref<HTMLElement | null>) {
  const sessionId = ref(localStorage.getItem(SESSION_KEY) || createSessionId())
  const messages = ref<ChatMessage[]>([])
  const historySessions = ref<SessionSummary[]>(loadHistorySessions())
  const showHistory = ref(false)

  localStorage.setItem(SESSION_KEY, sessionId.value)

  const shortSessionId = computed(() => sessionId.value.slice(0, 8).toUpperCase())
  const hasUserMessage = computed(() => messages.value.some((m) => m.role === 'user'))
  const hasPendingAssistantMessage = computed(() => messages.value.some((m) => m.role === 'assistant' && !m.content))

  function persistHistory() {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(historySessions.value.slice(0, 10)))
  }

  function appendMessage(role: Role, content: string) {
    // 局域网 HTTP 页面不是安全上下文，不能直接调用 crypto.randomUUID()。
    const id = createSessionId()
    messages.value.push({ id, role, content, time: currentTime(), orderPreview: null })
    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
    return id
  }

  function setMessageContent(id: string, content: string) {
    const message = messages.value.find((item) => item.id === id)
    if (message) message.content = content
    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  }

  function appendMessageContent(id: string, content: string) {
    const message = messages.value.find((item) => item.id === id)
    if (message) message.content += content
    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  }

  function upsertMessageToolCall(id: string, call: ToolCallRecord) {
    const message = messages.value.find((item) => item.id === id)
    if (!message || !call.call_id || !call.name) return

    const status = call.phase === 'start' && !call.status ? 'running' : call.status
    const nextCall = { ...call, status }
    if (!message.toolCalls) message.toolCalls = []

    const existing = message.toolCalls.find((item) => item.call_id === call.call_id)
    if (existing) {
      Object.assign(existing, nextCall)
    } else {
      message.toolCalls.push(nextCall)
    }

    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  }

  function toChatMessage(payload: ConversationMessagePayload): ChatMessage | null {
    const role = mapHistoryRole(payload.role)
    if (!role) return null
    return {
      id: payload.id,
      role,
      content: payload.content,
      time: currentTime(),
      orderPreview: payload.order_preview ?? null,
    }
  }

  function upsertConversationMessages(payloads: ConversationMessagePayload[]) {
    for (const payload of payloads) {
      const incoming = toChatMessage(payload)
      if (!incoming) continue
      const index = messages.value.findIndex((item) => item.id === incoming.id)
      if (index >= 0) {
        const current = messages.value[index]
        messages.value[index] = {
          ...incoming,
          time: current?.time || incoming.time,
          toolCalls: current?.toolCalls,
        }
      } else {
        messages.value.push(incoming)
      }
    }
    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  }

  function replacePendingTurn(
    humanMessageId: string,
    aiMessageId: string,
    payloads: ConversationMessagePayload[],
  ) {
    const pendingAi = messages.value.find((item) => item.id === aiMessageId)
    const insertAt = messages.value.findIndex((item) => item.id === humanMessageId)
    messages.value = messages.value.filter(
      (item) => item.id !== humanMessageId && item.id !== aiMessageId,
    )
    const converted = payloads
      .map(toChatMessage)
      .filter((item): item is ChatMessage => Boolean(item))
    const ai = converted.find((item) => item.role === 'assistant')
    if (ai && pendingAi?.toolCalls) ai.toolCalls = pendingAi.toolCalls
    messages.value.splice(insertAt >= 0 ? insertAt : messages.value.length, 0, ...converted)
    nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  }

  function summarizeCurrentSession(orderInfo: { room_number?: string | null; product?: string | null; fault?: string | null }, canSubmit: boolean) {
    const u = messages.value.find((m) => m.role === 'user')
    if (!u) return
    const title = [orderInfo.room_number, orderInfo.product, orderInfo.fault]
      .filter(Boolean)
      .join(' ') || u.content.slice(0, 16)
    historySessions.value = [
      { id: sessionId.value, title, status: canSubmit ? '待确认' : '信息待补充', time: currentTime() },
      ...historySessions.value.filter((i) => i.id !== sessionId.value),
    ].slice(0, 10)
    persistHistory()
  }

  function resetMessages() {
    messages.value = []
  }

  function setSessionId(nextId: string) {
    sessionId.value = nextId
    localStorage.setItem(SESSION_KEY, nextId)
  }

  return {
    sessionId,
    messages,
    historySessions,
    showHistory,
    shortSessionId,
    hasUserMessage,
    hasPendingAssistantMessage,
    appendMessage,
    setMessageContent,
    appendMessageContent,
    upsertMessageToolCall,
    upsertConversationMessages,
    replacePendingTurn,
    summarizeCurrentSession,
    resetMessages,
    setSessionId,
    persistHistory,
  }
}
