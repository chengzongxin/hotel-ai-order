import type { Ref } from 'vue'
import type { ApiRequestParams } from '../utils/apiParams'
import { buildApiHeaders } from '../utils/apiParams'
import type { ChatMessage, OrderPreview, ProductOption, StreamEvent, ToolCallRecord } from '../types/order'
import { SESSION_KEY, applyOrderPreview, mapHistoryRole, currentTime } from './useChatSession'
import { isSubmittedPreview } from './useOrderPreview'

type ChatApiDeps = {
  sessionId: Ref<string>
  messages: Ref<ChatMessage[]>
  orderPreview: Ref<OrderPreview | null>
  selectedProductCode: Ref<string | null>
  chatBodyRef: Ref<HTMLElement | null>
  errorMessage: Ref<string>
  streamStatus: Ref<string>
  isSending: Ref<boolean>
  isSelectingProduct: Ref<boolean>
  selectingProductCode: Ref<string | null>
  isUpdatingOrderInfo: Ref<boolean>
  updatingFieldKey: Ref<string | null>
  apiParams: Ref<ApiRequestParams>
  appendMessage: (role: 'user' | 'assistant', content: string) => number
  setMessageContent: (id: number, content: string) => void
  appendMessageContent: (id: number, content: string) => void
  setMessageOrderSuccess: (id: number, snapshot: NonNullable<import('../types/order').ChatMessage['orderSuccess']>) => void
  upsertMessageToolCall: (id: number, call: ToolCallRecord) => void
  buildOrderSuccessSnapshot: () => NonNullable<import('../types/order').ChatMessage['orderSuccess']>
  isProductSelected: (item: ProductOption) => boolean
  canConfirmOrder: Ref<boolean>
}

export function useChatApi(deps: ChatApiDeps) {
  function currentApiHeaders() {
    return buildApiHeaders(deps.apiParams.value)
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
      const restored = (data.messages || [])
        .map((msg: { role: string; content: string }, index: number) => {
          const role = mapHistoryRole(msg.role)
          if (!role || !msg.content?.trim()) return null
          return { id: Date.now() + index, role, content: msg.content, time: currentTime() }
        })
        .filter(Boolean)

      if (restored.length) {
        deps.messages.value = restored as typeof deps.messages.value
      }

      if (data.order_preview) {
        applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
      }
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
      if (!res.ok) {
        let detail = `更新失败 ${res.status}`
        try {
          const errBody = await res.json()
          detail = typeof errBody.detail === 'string' ? errBody.detail : detail
        } catch { /* ignore */ }
        throw new Error(detail)
      }
      const data = await res.json()
      applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
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
      if (!res.ok) {
        let detail = `选择失败 ${res.status}`
        try {
          const errBody = await res.json()
          detail = typeof errBody.detail === 'string' ? errBody.detail : detail
        } catch { /* ignore */ }
        throw new Error(detail)
      }
      const data = await res.json()
      applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
      if (typeof data.message === 'string' && data.message.trim()) {
        deps.appendMessage('assistant', data.message.trim())
      }
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '选择商品失败'
    } finally {
      deps.isSelectingProduct.value = false
      deps.selectingProductCode.value = null
    }
  }

  async function rejectProducts() {
    if (deps.isSending.value || deps.isSelectingProduct.value) return
    deps.errorMessage.value = ''
    deps.appendMessage('user', '以上都不符合')
    const assistantMessageId = deps.appendMessage('assistant', '')
    deps.isSending.value = true
    deps.streamStatus.value = '正在重新整理需求...'

    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(deps.sessionId.value)}/reject-products`, {
        method: 'POST',
        headers: currentApiHeaders(),
      })
      if (!res.ok) throw await buildResponseError(res, `操作失败 ${res.status}`)

      const data = await res.json()
      applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
      deps.setMessageContent(assistantMessageId, data.answer || '请重新描述需要处理的商品和问题。')
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '操作失败'
      deps.setMessageContent(assistantMessageId, '操作失败，请稍后重试。')
    } finally {
      deps.isSending.value = false
      deps.streamStatus.value = ''
    }
  }

  async function confirmOrder() {
    if (!deps.canConfirmOrder.value || deps.isSending.value) return
    deps.errorMessage.value = ''
    const confirmText = '确认下单'
    deps.appendMessage('user', confirmText)
    const assistantMessageId = deps.appendMessage('assistant', '')
    deps.isSending.value = true
    deps.streamStatus.value = '正在提交订单...'

    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(deps.sessionId.value)}/confirm`, {
        method: 'POST',
        headers: currentApiHeaders(),
      })
      if (!res.ok) throw await buildResponseError(res, `确认下单失败 ${res.status}`)

      const data = await res.json()
      applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
      if (isSubmittedPreview(data.order_preview)) {
        deps.setMessageOrderSuccess(assistantMessageId, deps.buildOrderSuccessSnapshot())
      }
      deps.setMessageContent(assistantMessageId, data.answer || '已处理确认下单请求。')
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '确认下单失败'
      deps.setMessageContent(assistantMessageId, '确认下单失败，请检查信息后重试。')
    } finally {
      deps.isSending.value = false
      deps.streamStatus.value = ''
    }
  }

  async function cancelOrder() {
    if (deps.isSending.value) return
    deps.errorMessage.value = ''
    deps.appendMessage('user', '取消订单')
    const assistantMessageId = deps.appendMessage('assistant', '')
    deps.isSending.value = true
    deps.streamStatus.value = '正在取消订单...'

    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(deps.sessionId.value)}/cancel`, {
        method: 'POST',
        headers: currentApiHeaders(),
      })
      if (!res.ok) throw await buildResponseError(res, `取消订单失败 ${res.status}`)

      const data = await res.json()
      applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
      deps.setMessageContent(assistantMessageId, data.answer || '已取消当前订单。')
    } catch (err) {
      deps.errorMessage.value = err instanceof Error ? err.message : '取消订单失败'
      deps.setMessageContent(assistantMessageId, '取消订单失败，请稍后重试。')
    } finally {
      deps.isSending.value = false
      deps.streamStatus.value = ''
    }
  }

  async function sendFallbackMessage(content: string, assistantMessageId: number) {
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
    applyOrderPreview(deps.orderPreview, deps.chatBodyRef, data.order_preview)
    deps.setMessageContent(assistantMessageId, data.answer || '我已收到，会继续为您处理。')
  }

  async function sendStreamingMessage(content: string, assistantMessageId: number) {
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
    let streamedAnswer = ''

    const handleEvent = (event: StreamEvent) => {
      if (event.type === 'status') {
        deps.streamStatus.value = event.message || '正在处理您的请求...'
        return
      }
      if (event.type === 'preview') {
        applyOrderPreview(deps.orderPreview, deps.chatBodyRef, event.order_preview)
        return
      }
      if (event.type === 'tool_call') {
        if (event.call_id && event.name) {
          deps.upsertMessageToolCall(assistantMessageId, {
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
        const chunk = event.content || ''
        streamedAnswer += chunk
        deps.appendMessageContent(assistantMessageId, chunk)
        return
      }
      if (event.type === 'final') {
        if (event.session_id) {
          deps.sessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY, event.session_id)
        }
        applyOrderPreview(deps.orderPreview, deps.chatBodyRef, event.order_preview)
        if (isSubmittedPreview(event.order_preview)) {
          deps.setMessageOrderSuccess(assistantMessageId, deps.buildOrderSuccessSnapshot())
        }
        deps.setMessageContent(assistantMessageId, streamedAnswer || event.answer || '我已收到，会继续为您处理。')
        return
      }
      if (event.type === 'error') {
        const streamError = new Error(event.message || '智能体处理失败')
        streamError.name = 'StreamEventError'
        throw streamError
      }
    }

    const parseAndHandleEvent = (line: string) => {
      let event: StreamEvent
      try {
        event = JSON.parse(line)
      } catch {
        const streamError = new Error('流式响应格式异常，请稍后重试')
        streamError.name = 'StreamEventError'
        throw streamError
      }
      handleEvent(event)
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        const text = line.trim()
        if (!text) continue
        parseAndHandleEvent(text)
      }
    }

    const lastLine = buffer.trim()
    if (lastLine) parseAndHandleEvent(lastLine)
    if (!deps.messages.value.find((item) => item.id === assistantMessageId)?.content) {
      deps.setMessageContent(assistantMessageId, '我已收到，会继续为您处理。')
    }
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
