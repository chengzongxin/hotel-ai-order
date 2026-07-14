import type { Ref } from 'vue'
import type { ApiRequestParams } from '../utils/apiParams'
import { buildApiHeaders } from '../utils/apiParams'
import type {
  ChatMessage,
  ConversationMessagePayload,
  ProductOption,
  StreamEvent,
  ToolCallRecord,
} from '../types/order'
import { SESSION_KEY } from './useChatSession'

type ChatApiDeps = {
  sessionId: Ref<string>
  messages: Ref<ChatMessage[]>
  selectedProductCode: Ref<string | null>
  errorMessage: Ref<string>
  streamStatus: Ref<string>
  isSending: Ref<boolean>
  isSelectingProduct: Ref<boolean>
  selectingProductCode: Ref<string | null>
  isUpdatingOrderInfo: Ref<boolean>
  updatingFieldKey: Ref<string | null>
  apiParams: Ref<ApiRequestParams>
  appendMessage: (role: 'user' | 'assistant', content: string) => string
  setMessageContent: (id: string, content: string) => void
  appendMessageContent: (id: string, content: string) => void
  upsertMessageToolCall: (id: string, call: ToolCallRecord) => void
  upsertConversationMessages: (messages: ConversationMessagePayload[]) => void
  replacePendingTurn: (
    humanMessageId: string,
    aiMessageId: string,
    messages: ConversationMessagePayload[],
  ) => void
  isProductSelected: (item: ProductOption) => boolean
  canConfirmOrder: Ref<boolean>
}

export function useChatApi(deps: ChatApiDeps) {
  function currentApiHeaders() {
    return buildApiHeaders(deps.apiParams.value)
  }

  function responseMessages(data: unknown): ConversationMessagePayload[] {
    if (!data || typeof data !== 'object') return []
    const messages = (data as { conversation_messages?: unknown }).conversation_messages
    return Array.isArray(messages) ? messages as ConversationMessagePayload[] : []
  }

  async function buildResponseError(res: Response, fallback: string) {
    let message = fallback
    try {
      const body = await res.json()
      if (typeof body.detail === 'string' && body.detail.trim()) {
        message = body.detail.trim()
      }
    } catch { /* ignore */ }
    const err = new Error(message)
    if (res.status === 401) err.name = 'AuthRequiredError'
    return err
  }

  async function loadSessionHistory(targetSessionId = deps.sessionId.value) {
    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(targetSessionId)}/history`, {
        headers: currentApiHeaders(),
      })
      if (!res.ok) return

      const data = await res.json()
      deps.messages.value = []
      deps.upsertConversationMessages(responseMessages(data))
    } catch {
      // 新会话或后端不可用时保持空白页
    }
  }

  async function updateOrderInfoField(key: string, value: string | null) {
    if (!deps.selectedProductCode.value || deps.isUpdatingOrderInfo.value) return
    deps.isUpdatingOrderInfo.value = true
    deps.updatingFieldKey.value = key
    deps.errorMessage.value = ''

    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(deps.sessionId.value)}/order-info`, {
        method: 'PATCH',
        headers: currentApiHeaders(),
        body: JSON.stringify({ updates: { [key]: value ?? '' } }),
      })
      if (!res.ok) throw await buildResponseError(res, `更新失败 ${res.status}`)
      deps.upsertConversationMessages(responseMessages(await res.json()))
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '更新下单信息失败'
    } finally {
      deps.isUpdatingOrderInfo.value = false
      deps.updatingFieldKey.value = null
    }
  }

  async function selectProduct(item: ProductOption) {
    const code = item.code?.trim()
    if (!code || deps.isSelectingProduct.value || deps.isSending.value || deps.isProductSelected(item)) return

    deps.isSelectingProduct.value = true
    deps.selectingProductCode.value = code
    deps.errorMessage.value = ''

    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(deps.sessionId.value)}/select-product`, {
        method: 'POST',
        headers: currentApiHeaders(),
        body: JSON.stringify({ product_code: code }),
      })
      if (!res.ok) throw await buildResponseError(res, `选择失败 ${res.status}`)
      deps.upsertConversationMessages(responseMessages(await res.json()))
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '选择商品失败'
    } finally {
      deps.isSelectingProduct.value = false
      deps.selectingProductCode.value = null
    }
  }

  async function runDeterministicTurn(
    path: string,
    humanContent: string,
    pendingStatus: string,
    fallbackError: string,
  ) {
    deps.errorMessage.value = ''
    const humanMessageId = deps.appendMessage('user', humanContent)
    const aiMessageId = deps.appendMessage('assistant', '')
    deps.isSending.value = true
    deps.streamStatus.value = pendingStatus

    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: currentApiHeaders(),
      })
      if (!res.ok) throw await buildResponseError(res, `${fallbackError} ${res.status}`)
      deps.replacePendingTurn(
        humanMessageId,
        aiMessageId,
        responseMessages(await res.json()),
      )
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : fallbackError
      deps.setMessageContent(aiMessageId, `${fallbackError}，请稍后重试。`)
    } finally {
      deps.isSending.value = false
      deps.streamStatus.value = ''
    }
  }

  async function rejectProducts() {
    if (deps.isSending.value || deps.isSelectingProduct.value) return
    await runDeterministicTurn(
      `/api/chat/${encodeURIComponent(deps.sessionId.value)}/reject-products`,
      '以上都不符合',
      '正在重新整理需求...',
      '操作失败',
    )
  }

  async function confirmOrder() {
    if (!deps.canConfirmOrder.value || deps.isSending.value) return
    await runDeterministicTurn(
      `/api/chat/${encodeURIComponent(deps.sessionId.value)}/confirm`,
      '确认下单',
      '正在提交订单...',
      '确认下单失败',
    )
  }

  async function cancelOrder() {
    if (deps.isSending.value) return
    await runDeterministicTurn(
      `/api/chat/${encodeURIComponent(deps.sessionId.value)}/cancel`,
      '取消订单',
      '正在取消订单...',
      '取消订单失败',
    )
  }

  async function sendFallbackMessage(
    content: string,
    humanMessageId: string,
    aiMessageId: string,
  ) {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: currentApiHeaders(),
      body: JSON.stringify({ session_id: deps.sessionId.value, message: content }),
    })
    if (!res.ok) throw await buildResponseError(res, `请求失败 ${res.status}`)
    const data = await res.json()
    if (data.session_id) {
      deps.sessionId.value = data.session_id
      localStorage.setItem(SESSION_KEY, data.session_id)
    }
    deps.replacePendingTurn(humanMessageId, aiMessageId, responseMessages(data))
  }

  async function sendStreamingMessage(
    content: string,
    humanMessageId: string,
    aiMessageId: string,
  ) {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: currentApiHeaders(),
      body: JSON.stringify({ session_id: deps.sessionId.value, message: content }),
    })
    if (!res.ok) throw await buildResponseError(res, `请求失败 ${res.status}`)
    if (!res.body) throw new Error(`请求失败 ${res.status}`)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const handleEvent = (event: StreamEvent) => {
      if (event.type === 'status') {
        deps.streamStatus.value = event.message || '正在处理您的请求...'
        return
      }
      if (event.type === 'tool_call') {
        if (event.call_id && event.name) {
          deps.upsertMessageToolCall(aiMessageId, {
            call_id: event.call_id,
            phase: event.phase,
            kind: event.kind,
            name: event.name,
            display_name: event.display_name,
            step: event.step,
            status: event.status,
            params: event.params,
            result: event.result,
            error: event.error,
            duration_ms: event.duration_ms,
            summary: event.summary,
          })
        }
        return
      }
      if (event.type === 'token') {
        deps.appendMessageContent(aiMessageId, event.content || '')
        return
      }
      if (event.type === 'final') {
        if (event.session_id) {
          deps.sessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY, event.session_id)
        }
        deps.replacePendingTurn(
          humanMessageId,
          aiMessageId,
          event.conversation_messages || [],
        )
        return
      }
      if (event.type === 'error') {
        const streamError = new Error(event.message || '智能体处理失败')
        streamError.name = 'StreamEventError'
        throw streamError
      }
    }

    const parseAndHandleEvent = (line: string) => {
      try {
        handleEvent(JSON.parse(line) as StreamEvent)
      } catch (error) {
        if (error instanceof Error && error.name === 'StreamEventError') throw error
        const streamError = new Error('流式响应格式异常，请稍后重试')
        streamError.name = 'StreamEventError'
        throw streamError
      }
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        const text = line.trim()
        if (text) parseAndHandleEvent(text)
      }
    }

    const lastLine = buffer.trim()
    if (lastLine) parseAndHandleEvent(lastLine)
  }

  return {
    loadSessionHistory,
    updateOrderInfoField,
    selectProduct,
    rejectProducts,
    confirmOrder,
    cancelOrder,
    sendFallbackMessage,
    sendStreamingMessage,
  }
}
