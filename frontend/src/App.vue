<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OrderPreviewCard from './components/OrderPreviewCard.vue'
import OrderStatusNotices from './components/OrderStatusNotices.vue'
import ProductSelectionCard from './components/ProductSelectionCard.vue'
import type {
  ChatMessage,
  CoverageNotice,
  OrderPreview,
  ProductOption,
  Role,
  SessionSummary,
  StreamEvent,
  UiOrderField,
} from './types/order'
import {
  API_PARAM_FIELDS,
  buildApiHeaders,
  loadApiParams,
  resetApiParams,
  saveApiParams,
  type ApiRequestParams,
} from './utils/apiParams'
import { createSessionId } from './utils/sessionId'

marked.setOptions({ breaks: true })

function renderMarkdown(content: string): string {
  return DOMPurify.sanitize(marked.parse(content) as string)
}

const SESSION_KEY = 'order_voice_session_id'
const HISTORY_KEY = 'order_voice_history_sessions'

const apiParams = ref<ApiRequestParams>(loadApiParams())
const showApiParams = ref(true)
const showApiParamsMobile = ref(false)
const apiParamsSaved = ref(false)

const sessionId = ref(localStorage.getItem(SESSION_KEY) || createSessionId())
const inputText = ref('')
const isListening = ref(false)
const isSending = ref(false)
const errorMessage = ref('')
const streamStatus = ref('')
const showHistory = ref(false)
const chatBodyRef = ref<HTMLElement | null>(null)
const historyRef = ref<HTMLElement | null>(null)

const messages = ref<ChatMessage[]>([])
const orderPreview = ref<OrderPreview | null>(null)
const isSelectingProduct = ref(false)
const selectingProductCode = ref<string | null>(null)
const isUpdatingOrderInfo = ref(false)
const updatingFieldKey = ref<string | null>(null)
const historySessions = ref<SessionSummary[]>(loadHistorySessions())

localStorage.setItem(SESSION_KEY, sessionId.value)

const shortSessionId = computed(() => sessionId.value.slice(0, 8).toUpperCase())
const hasUserMessage = computed(() => messages.value.some((m) => m.role === 'user'))
const hasPendingAssistantMessage = computed(() => messages.value.some((m) => m.role === 'assistant' && !m.content))

const filledCount = computed(() => orderFields.value.filter((field) => Boolean(field.value)).length)
const totalFieldCount = computed(() => Math.max(orderFields.value.length, 1))
const orderCompleteness = computed(() => Math.round((filledCount.value / totalFieldCount.value) * 100))

const orderInfo = computed(() => orderPreview.value?.order_info ?? {})
const uiPhase = computed(() => orderPreview.value?.ui_phase ?? null)
const previewStatus = computed(() => orderPreview.value?.status ?? null)
const serviceTypeDisplay = computed(
  () => orderPreview.value?.service_type_display ?? orderPreview.value?.service_type ?? null,
)
const effectiveServiceTypeDisplay = computed(
  () =>
    orderPreview.value?.effective_service_type_display
    ?? orderPreview.value?.effective_service_type
    ?? serviceTypeDisplay.value
    ?? null,
)
const missingInfo = computed(() => orderPreview.value?.missing_info ?? [])
const coverage = computed(() => orderPreview.value?.coverage ?? {})
const productItems = computed(() => orderPreview.value?.products?.items ?? [])
const productFeedback = computed(() => orderPreview.value?.products?.feedback ?? null)
const selectedProductCode = computed(() => orderPreview.value?.products?.selected_code ?? null)
const productSelectionRejected = computed(() => Boolean(orderPreview.value?.products?.selection_rejected))
const selectedProduct = computed(
  () => productItems.value.find(isProductSelected) ?? null,
)
const backendOrderFields = computed(() => orderPreview.value?.order_card?.fields ?? [])
const hasBackendOrderFields = computed(() => backendOrderFields.value.length > 0)
const isProductSelectionPhase = computed(() => uiPhase.value === 'product_selection')
const isPreOrderPhase = computed(() => uiPhase.value === 'pre_order' || previewStatus.value === 'confirming')
const isAwaitingProductSelection = computed(
  () => isProductSelectionPhase.value && hasProductOptions.value && !selectedProductCode.value && !productSelectionRejected.value,
)
const showDraftOrderCard = computed(() => isPreOrderPhase.value && Boolean(selectedProductCode.value) && hasBackendOrderFields.value)
const submittedOrderId = computed(() => extractOrderId(orderPreview.value?.submission?.result))
const isSubmittingOrder = computed(() => isSending.value && previewStatus.value === 'confirming')
const submissionMissingFields = computed(() => orderPreview.value?.submission?.missing_fields ?? [])
const hasSubmissionFailure = computed(
  () =>
    previewStatus.value === 'confirming'
    && Boolean(orderPreview.value?.submission?.payload)
    && !submittedOrderId.value
    && (submissionMissingFields.value.length > 0 || Boolean(orderPreview.value?.submission?.result)),
)

const canSubmit = computed(() =>
  previewStatus.value === 'confirming' && missingInfo.value.length === 0
)

const hasProductOptions = computed(() => productItems.value.length > 0)

const isOrderSubmitted = computed(() => previewStatus.value === 'submitted')

const showChatOrderPanel = computed(() => {
  const status = previewStatus.value
  if (status === 'submitted') return true
  if (status === 'cancelled') return false
  if (!status || status === 'idle') return false
  if (productSelectionRejected.value) return false
  return (isProductSelectionPhase.value && productItems.value.length > 0) || showDraftOrderCard.value
})

const canConfirmOrder = computed(
  () => canSubmit.value && Boolean(selectedProductCode.value) && !isSending.value && !isUpdatingOrderInfo.value,
)

const canCancelOrder = computed(() => {
  const status = previewStatus.value
  return (status === 'collecting' || status === 'confirming') && !isSending.value
})

const missingInfoLabels: Record<string, string> = {
  selected_product: '服务商品',
  room_number: '房号',
  product: '商品/设备',
  fault: '故障现象',
  area: '区域',
  expected_start_time: '期待开工时间',
  goods_arrival_status: '货物到场状态',
  contacts: '联系人',
  phone: '联系电话',
  address: '地址',
}

const missingInfoText = computed(() =>
  missingInfo.value
    .map((field) => missingInfoLabels[field] || field)
    .join('、')
)

const submissionMissingText = computed(() =>
  submissionMissingFields.value
    .map((field) => missingInfoLabels[field] || field)
    .join('、')
)

const coverageNotice = computed<CoverageNotice | null>(() => {
  const data = coverage.value
  if (!data.checked || !data.reason) return null
  const tone: CoverageNotice['tone'] = data.covered === false ? 'warning' : 'ok'
  return {
    tone,
    title: data.covered === false ? '维保范围提示' : '维保范围已校验',
    message: data.reason,
  }
})

const urgencyConfig = computed(() => {
  if (!orderInfo.value.urgency) return { label: '—', icon: '·', color: 'text-slate-400', bg: 'bg-slate-50' }
  return {
    low:    { label: '低优先级', icon: '↓', color: 'text-emerald-700', bg: 'bg-emerald-50' },
    medium: { label: '普通',     icon: '→', color: 'text-blue-700',    bg: 'bg-blue-50'    },
    high:   { label: '较急',     icon: '↑', color: 'text-amber-700',   bg: 'bg-amber-50'   },
    urgent: { label: '紧急',     icon: '!', color: 'text-red-700',     bg: 'bg-red-50'     },
  }[orderInfo.value.urgency]
})

function makeReadonlyField(
  key: string,
  icon: string,
  label: string,
  value: string | null | undefined,
): UiOrderField {
  return {
    key,
    icon,
    label,
    value: value ?? null,
    required: false,
    editable: false,
    inputType: 'text',
    options: [],
  }
}

const orderFields = computed<UiOrderField[]>(() => {
  if (hasBackendOrderFields.value) {
    return backendOrderFields.value.map((field) => ({
      key: field.key,
      icon: iconForOrderField(field.key),
      label: field.label,
      value: formatOrderFieldValue(field.value),
      required: Boolean(field.required),
      editable: field.editable !== false,
      inputType: field.input_type || 'text',
      options: field.options || [],
    }))
  }

  const base = [
    makeReadonlyField('serviceType', '📋', '订单类型', serviceTypeDisplay.value),
    makeReadonlyField('product', '🔧', '商品/设备', orderInfo.value.product ?? null),
  ]

  if (serviceTypeDisplay.value?.includes('单次安装')) {
    return [
      ...base,
      makeReadonlyField('expectedStartTime', '🕒', '期待开工时间', orderInfo.value.expected_start_time),
      makeReadonlyField('goodsArrivalStatus', '🚚', '货物是否到场', orderInfo.value.goods_arrival_status),
    ]
  }

  if (serviceTypeDisplay.value?.includes('单次测量')) {
    return [
      ...base,
      makeReadonlyField('expectedStartTime', '🕒', '期待开工时间', orderInfo.value.expected_start_time),
    ]
  }

  if (serviceTypeDisplay.value?.includes('单次维修')) {
    return [
      ...base,
      makeReadonlyField('fault', '⚡', '问题描述', orderInfo.value.fault),
      makeReadonlyField('expectedStartTime', '🕒', '期待开工时间', orderInfo.value.expected_start_time),
    ]
  }

  return [
    ...base,
    makeReadonlyField('fault', '⚡', '问题描述', orderInfo.value.fault),
    makeReadonlyField('area', '📍', '所在区域', orderInfo.value.area),
    makeReadonlyField('roomNumber', '🏠', '房间号', orderInfo.value.room_number),
  ]
})

const progressR = 32
const progressCircumference = computed(() => +(2 * Math.PI * progressR).toFixed(2))
const progressOffset = computed(() =>
  +(progressCircumference.value - (orderCompleteness.value / 100) * progressCircumference.value).toFixed(2)
)

const suggestions = [
  { icon: '❄️', text: '1208 空调不制冷，比较急' },
  { icon: '💧', text: '0316 卫生间水龙头漏水' },
  { icon: '🔑', text: 'B栋 301 门锁打不开' },
  { icon: '📺', text: '0501 房间电视没有信号' },
]

function currentTime() {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function loadHistorySessions(): SessionSummary[] {
  try {
    const saved = localStorage.getItem(HISTORY_KEY)
    return saved ? JSON.parse(saved) : []
  } catch { return [] }
}

function persistHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(historySessions.value.slice(0, 10)))
}

function mapHistoryRole(role: string): Role | null {
  if (role === 'human' || role === 'user') return 'user'
  if (role === 'ai' || role === 'assistant') return 'assistant'
  return null
}

function currentApiHeaders() {
  return buildApiHeaders(apiParams.value)
}

function persistApiParams() {
  saveApiParams(apiParams.value)
  apiParamsSaved.value = true
  window.setTimeout(() => { apiParamsSaved.value = false }, 2000)
}

function restoreDefaultApiParams() {
  apiParams.value = resetApiParams()
  apiParamsSaved.value = true
  window.setTimeout(() => { apiParamsSaved.value = false }, 2000)
}

async function loadSessionHistory(targetSessionId = sessionId.value) {
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
      .filter(Boolean) as ChatMessage[]

    if (restored.length) {
      messages.value = restored
      nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight }))
    }

    if (data.order_preview) applyOrderPreview(data.order_preview)
  } catch {
    // 新会话或后端不可用时保持空白页
  }
}

async function switchSession(targetSessionId: string) {
  if (targetSessionId === sessionId.value) {
    showHistory.value = false
    return
  }

  summarizeCurrentSession()
  sessionId.value = targetSessionId
  localStorage.setItem(SESSION_KEY, targetSessionId)
  inputText.value = ''
  errorMessage.value = ''
  isListening.value = false
  isSending.value = false
  messages.value = []
  resetOrder()
  showHistory.value = false
  await loadSessionHistory(targetSessionId)
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight }))
}

function appendMessage(role: Role, content: string) {
  const id = Date.now() + Math.floor(Math.random() * 999)
  messages.value.push({ id, role, content, time: currentTime() })
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
  return id
}

function setMessageContent(id: number, content: string) {
  const message = messages.value.find((item) => item.id === id)
  if (message) message.content = content
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
}

function appendMessageContent(id: number, content: string) {
  const message = messages.value.find((item) => item.id === id)
  if (message) message.content += content
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
}

function applyOrderPreview(preview?: OrderPreview | null) {
  if (!preview) {
    orderPreview.value = null
    return
  }
  orderPreview.value = preview
  nextTick(() => {
    chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' })
  })
}

function isProductSelected(item: ProductOption): boolean {
  const activeCode = selectedProductCode.value
  return Boolean(item.is_selected || (item.code && item.code === activeCode))
}

function extractOrderId(result?: Record<string, unknown>): string | null {
  if (!result) return null
  const candidates = [result.parent_order_no, result.order_id, result.order_no]
  for (const value of candidates) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

function formatMatchScore(score?: number | null): string {
  if (score == null) return ''
  return `${Math.round(score * 100)}%`
}

function iconForOrderField(key: string): string {
  const icons: Record<string, string> = {
    area_room: '📍',
    urgency: '!',
    remark: '✎',
    contacts: '👤',
    phone: '☎',
    total_fee: '¥',
    expected_time: '🕒',
    goods_arrival_status: '🚚',
  }
  return icons[key] || '•'
}

function formatOrderFieldValue(value: unknown): string | null {
  if (value == null || value === '') return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function displayOrderFieldValue(field: { value?: string | null; options?: Array<{ label: string; value: string }> }): string {
  const value = field.value ?? ''
  const option = field.options?.find((item) => item.value === value)
  return option?.label || value || '待识别'
}

async function updateOrderInfoField(key: string, value: string | null) {
  if (!selectedProductCode.value || isUpdatingOrderInfo.value) return
  isUpdatingOrderInfo.value = true
  updatingFieldKey.value = key
  errorMessage.value = ''

  try {
    const res = await fetch(`/api/chat/${encodeURIComponent(sessionId.value)}/order-info`, {
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
    applyOrderPreview(data.order_preview)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '更新下单信息失败'
  } finally {
    isUpdatingOrderInfo.value = false
    updatingFieldKey.value = null
  }
}

async function selectProduct(item: ProductOption) {
  const code = item.code?.trim()
  if (!code || isSelectingProduct.value || isSending.value || isProductSelected(item)) return

  isSelectingProduct.value = true
  selectingProductCode.value = code
  errorMessage.value = ''

  try {
    const res = await fetch(`/api/chat/${encodeURIComponent(sessionId.value)}/select-product`, {
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
    applyOrderPreview(data.order_preview)
    if (typeof data.message === 'string' && data.message.trim()) {
      appendMessage('assistant', data.message.trim())
    }
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '选择商品失败'
  } finally {
    isSelectingProduct.value = false
    selectingProductCode.value = null
  }
}

async function confirmOrder() {
  if (!canConfirmOrder.value || isSending.value) return
  errorMessage.value = ''
  appendMessage('user', '确认下单')
  const assistantMessageId = appendMessage('assistant', '')
  isSending.value = true
  streamStatus.value = '正在提交订单...'

  try {
    const res = await fetch(`/api/chat/${encodeURIComponent(sessionId.value)}/confirm`, {
      method: 'POST',
      headers: currentApiHeaders(),
    })
    if (!res.ok) {
      let detail = `确认失败 ${res.status}`
      try {
        const errBody = await res.json()
        detail = typeof errBody.detail === 'string' ? errBody.detail : detail
      } catch { /* ignore */ }
      throw new Error(detail)
    }
    const data = await res.json()
    applyOrderPreview(data.order_preview)
    setMessageContent(assistantMessageId, data.answer || '已处理确认下单请求。')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '确认下单失败'
    setMessageContent(assistantMessageId, '确认下单失败，请检查信息后重试。')
  } finally {
    isSending.value = false
    streamStatus.value = ''
  }
}

function cancelOrder() {
  if (!canCancelOrder.value) return
  sendMessage('取消，不用了')
}

async function sendMessage(text = inputText.value) {
  const content = text.trim()
  if (!content || isSending.value) return

  errorMessage.value = ''
  inputText.value = ''
  const ta = document.querySelector<HTMLTextAreaElement>('textarea')
  if (ta) ta.style.height = 'auto'

  appendMessage('user', content)
  const assistantMessageId = appendMessage('assistant', '')
  streamStatus.value = '正在连接智能体...'
  isSending.value = true

  try {
    await sendStreamingMessage(content, assistantMessageId)
  } catch (err) {
    if (err instanceof Error && err.name === 'StreamEventError') {
      errorMessage.value = err.message
      setMessageContent(assistantMessageId, '智能体处理失败，请稍后重试。')
      isSending.value = false
      streamStatus.value = ''
      return
    }
    try {
      await sendFallbackMessage(content, assistantMessageId)
    } catch {
      errorMessage.value = err instanceof Error ? err.message : '网络请求失败'
      setMessageContent(assistantMessageId, '后端暂时不可用，已帮您保留预下单信息。')
    }
  } finally {
    isSending.value = false
    streamStatus.value = ''
  }
}

async function sendFallbackMessage(content: string, assistantMessageId: number) {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: currentApiHeaders(),
      body: JSON.stringify({ session_id: sessionId.value, message: content }),
    })
    if (!res.ok) throw new Error(`请求失败 ${res.status}`)
    const data = await res.json()
    if (data.session_id) { sessionId.value = data.session_id; localStorage.setItem(SESSION_KEY, data.session_id) }
    applyOrderPreview(data.order_preview)
    setMessageContent(assistantMessageId, data.answer || '我已收到，会继续为您处理。')
}

async function sendStreamingMessage(content: string, assistantMessageId: number) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: currentApiHeaders(),
    body: JSON.stringify({ session_id: sessionId.value, message: content }),
  })
  if (!res.ok || !res.body) throw new Error(`请求失败 ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let streamedAnswer = ''

  const handleEvent = (event: StreamEvent) => {
    if (event.type === 'session' && event.session_id) {
      sessionId.value = event.session_id
      localStorage.setItem(SESSION_KEY, event.session_id)
      return
    }
    if (event.type === 'status') {
      streamStatus.value = event.message || '正在处理您的请求...'
      return
    }
    if (event.type === 'preview') {
      applyOrderPreview(event.order_preview)
      return
    }
    if (event.type === 'token') {
      const chunk = event.content || ''
      streamedAnswer += chunk
      appendMessageContent(assistantMessageId, chunk)
      return
    }
    if (event.type === 'final') {
      if (event.session_id) {
        sessionId.value = event.session_id
        localStorage.setItem(SESSION_KEY, event.session_id)
      }
      applyOrderPreview(event.order_preview)
      setMessageContent(assistantMessageId, streamedAnswer || event.answer || '我已收到，会继续为您处理。')
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
      handleEvent(JSON.parse(line))
    } catch {
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
      if (!text) continue
      parseAndHandleEvent(text)
    }
  }

  const lastLine = buffer.trim()
  if (lastLine) parseAndHandleEvent(lastLine)
  if (!messages.value.find((item) => item.id === assistantMessageId)?.content) {
    setMessageContent(assistantMessageId, '我已收到，会继续为您处理。')
  }
}

function toggleListening() {
  if (isListening.value) { isListening.value = false; return }
  const R = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!R) { errorMessage.value = '当前浏览器不支持语音识别'; return }
  const r = new R()
  r.lang = 'zh-CN'; r.interimResults = false; r.maxAlternatives = 1
  isListening.value = true
  r.onresult = (e: SpeechRecognitionEvent) => { const t = e.results[0]?.[0]?.transcript || ''; inputText.value = t; sendMessage(t) }
  r.onerror = () => { errorMessage.value = '语音识别失败，请重试' }
  r.onend = () => { isListening.value = false }
  r.start()
}

function resetOrder() {
  orderPreview.value = null
}

function summarizeCurrentSession() {
  const u = messages.value.find((m) => m.role === 'user')
  if (!u) return
  const title = [orderInfo.value.room_number, orderInfo.value.product, orderInfo.value.fault]
    .filter(Boolean)
    .join(' ') || u.content.slice(0, 16)
  historySessions.value = [
    { id: sessionId.value, title, status: canSubmit.value ? '待确认' : '信息待补充', time: currentTime() },
    ...historySessions.value.filter((i) => i.id !== sessionId.value),
  ].slice(0, 10)
  persistHistory()
}

function createNewSession() {
  summarizeCurrentSession()
  sessionId.value = createSessionId()
  localStorage.setItem(SESSION_KEY, sessionId.value)
  inputText.value = ''; errorMessage.value = ''; isListening.value = false; isSending.value = false
  messages.value = []; resetOrder(); showHistory.value = false
  nextTick(() => chatBodyRef.value?.scrollTo({ top: 0 }))
}

function statusStyle(status: string) {
  return {
    '待确认':    'bg-amber-100 text-amber-700',
    '已派单':    'bg-blue-100 text-blue-700',
    '已完成':    'bg-emerald-100 text-emerald-700',
    '信息待补充': 'bg-slate-100 text-slate-600',
  }[status] ?? 'bg-slate-100 text-slate-500'
}

function autoGrow(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

function closeHistoryOnOutside(e: MouseEvent) {
  if (historyRef.value && !historyRef.value.contains(e.target as Node)) showHistory.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', closeHistoryOnOutside)
  loadSessionHistory()
})
onUnmounted(() => document.removeEventListener('mousedown', closeHistoryOnOutside))
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-slate-100 font-sans antialiased">

    <!-- ══════════════ HEADER ══════════════ -->
    <header class="flex h-14 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-5 shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
      <!-- Brand -->
      <div class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-sm shadow-indigo-600/30">H</div>
        <div class="leading-none">
          <p class="text-[13px] font-semibold text-slate-800">AI 下单助手</p>
          <p class="text-[10px] text-slate-400">Hotel Desk</p>
        </div>
      </div>

      <!-- Separator -->
      <div class="h-6 w-px bg-slate-200"></div>

      <!-- Nav tabs -->
      <nav class="flex items-center gap-1">
        <RouterLink
          to="/"
          class="rounded-lg px-3 py-1.5 text-[12px] font-medium transition"
          active-class="bg-indigo-50 text-indigo-700"
          :class="$route.path === '/' ? '' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'"
        >下单对话</RouterLink>
        <RouterLink
          to="/products"
          class="rounded-lg px-3 py-1.5 text-[12px] font-medium transition"
          active-class="bg-indigo-50 text-indigo-700"
          :class="$route.path === '/products' ? '' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'"
        >商品库</RouterLink>
      </nav>

      <!-- Separator -->
      <div class="h-6 w-px bg-slate-200"></div>

      <!-- Session badge -->
      <div class="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
        <span class="text-[11px] font-medium text-slate-500">会话 #{{ shortSessionId }}</span>
      </div>

      <div class="ml-auto flex items-center gap-2">
        <button
          class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 lg:hidden"
          @click="showApiParamsMobile = true"
        >
          接口参数
        </button>

        <!-- History dropdown -->
        <div ref="historyRef" class="relative">
          <button
            class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
            @click="showHistory = !showHistory"
          >
            <svg class="h-3.5 w-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            历史记录
          </button>

          <!-- History dropdown panel -->
          <div
            v-if="showHistory"
            class="absolute right-0 top-full z-50 mt-2 w-72 rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-200/80"
          >
            <div class="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <p class="text-sm font-semibold text-slate-700">历史会话</p>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">{{ historySessions.length }} 条</span>
            </div>
            <div class="max-h-72 overflow-y-auto p-2">
              <button
                v-for="item in historySessions"
                :key="item.id"
                class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-slate-50"
                @click="switchSession(item.id)"
              >
                <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-xs font-bold text-indigo-600">
                  {{ item.title.slice(0, 2) }}
                </div>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[13px] font-medium text-slate-700">{{ item.title }}</p>
                  <p class="text-[11px] text-slate-400">{{ item.time }}</p>
                </div>
                <span class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium" :class="statusStyle(item.status)">{{ item.status }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- New session -->
        <button
          class="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-sm shadow-indigo-600/25 transition hover:bg-indigo-700 active:scale-95"
          @click="createNewSession"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
          </svg>
          新建对话
        </button>
      </div>
    </header>

    <!-- ══════════════ MAIN CONTENT ══════════════ -->
    <main class="flex flex-1 gap-4 overflow-hidden p-4">

      <!-- ── Chat Panel ── -->
      <div class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">

        <!-- Messages -->
        <div ref="chatBodyRef" class="flex-1 overflow-y-auto">
          <div class="mx-auto max-w-[640px] px-6 py-8">

            <!-- Welcome / empty state -->
            <div v-if="!hasUserMessage">
              <div class="mb-8 flex items-start gap-4">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-base font-bold text-white shadow-md shadow-indigo-600/25">H</div>
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">下单助手</p>
                  <p class="mt-1 text-[15px] leading-7 text-slate-700">您好！我是酒店 AI 下单助手。请告诉我房间号、商品和问题，我会帮您快速整理下单信息。</p>
                </div>
              </div>

              <!-- Suggestion cards grid -->
              <div class="grid grid-cols-2 gap-3">
                <button
                  v-for="chip in suggestions"
                  :key="chip.text"
                  class="group flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-3.5 text-left transition hover:border-indigo-200 hover:bg-indigo-50/50"
                  @click="sendMessage(chip.text)"
                >
                  <span class="text-xl leading-none">{{ chip.icon }}</span>
                  <p class="text-[13px] leading-5 text-slate-600 group-hover:text-indigo-700">{{ chip.text }}</p>
                </button>
              </div>
            </div>

            <!-- Message list -->
            <div class="space-y-7">
              <template v-for="message in messages" :key="message.id">

                <!-- AI message -->
                <div v-if="message.role === 'assistant'" class="flex items-start gap-3.5">
                  <div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-[12px] font-bold text-white shadow-sm shadow-indigo-600/20">H</div>
                  <div class="min-w-0 flex-1">
                    <p class="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">下单助手</p>
                    <div v-if="message.content" class="prose prose-sm" v-html="renderMarkdown(message.content)"></div>
                    <p v-else class="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1.5 text-[12px] text-indigo-600">
                      <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500"></span>
                      {{ streamStatus || '正在处理您的请求...' }}
                    </p>
                    <p class="mt-2 text-[11px] text-slate-400">{{ message.time }}</p>
                  </div>
                </div>

                <!-- User message -->
                <div v-else class="flex justify-end">
                  <div class="max-w-[80%]">
                    <div class="rounded-2xl rounded-tr-md bg-indigo-600 px-4 py-3 shadow-sm shadow-indigo-600/15">
                      <p class="text-[15px] leading-7 text-white whitespace-pre-wrap">{{ message.content }}</p>
                    </div>
                    <p class="mt-1.5 pr-1 text-right text-[11px] text-slate-400">{{ message.time }}</p>
                  </div>
                </div>
              </template>

              <!-- Typing indicator -->
              <div v-if="isSending && !hasPendingAssistantMessage" class="flex items-start gap-3.5">
                <div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-[12px] font-bold text-white shadow-sm shadow-indigo-600/20">H</div>
                <div class="flex items-center gap-3 rounded-2xl rounded-tl-md border border-slate-100 bg-slate-50 px-4 py-3.5">
                  <div class="flex items-center gap-1.5">
                    <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce"></span>
                    <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style="animation-delay:150ms"></span>
                    <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style="animation-delay:300ms"></span>
                  </div>
                  <span class="text-[12px] text-slate-500">{{ streamStatus || '正在处理您的请求...' }}</span>
                </div>
              </div>

              <!-- In-chat order panel: product cards + confirm/cancel -->
              <div v-if="showChatOrderPanel" class="flex items-start gap-3.5">
                <div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-[12px] font-bold text-white shadow-sm shadow-indigo-600/20">H</div>
                <div class="min-w-0 flex-1">
                  <div class="overflow-hidden rounded-2xl border border-indigo-100 bg-white px-4 py-4 shadow-sm shadow-indigo-100/60">
                    <!-- Submitted success -->
                    <div
                      v-if="isOrderSubmitted"
                      class="mb-3 rounded-xl border border-emerald-100 bg-emerald-50 px-3.5 py-3"
                    >
                      <p class="text-[13px] font-semibold text-emerald-800">订单已提交</p>
                      <p v-if="submittedOrderId" class="mt-1 font-mono text-[12px] text-emerald-700">
                        单号：{{ submittedOrderId }}
                      </p>
                      <p v-if="selectedProduct?.name" class="mt-1 text-[12px] text-emerald-700/90">
                        商品：{{ selectedProduct.name }}
                      </p>
                    </div>

                    <OrderStatusNotices
                      v-if="isSubmittingOrder || hasSubmissionFailure"
                      class="mb-3"
                      :is-submitting-order="isSubmittingOrder"
                      :has-submission-failure="hasSubmissionFailure"
                      :submission-missing-text="submissionMissingText"
                    />

                    <ProductSelectionCard
                      v-if="isProductSelectionPhase && hasProductOptions && !productSelectionRejected"
                      :items="productItems"
                      :feedback="productFeedback"
                      :selected-code="selectedProductCode"
                      :selecting-code="selectingProductCode"
                      :is-awaiting-selection="isAwaitingProductSelection"
                      :is-selecting="isSelectingProduct"
                      :is-sending="isSending"
                      :is-submitted="isOrderSubmitted"
                      @select="selectProduct"
                      @reject="sendMessage('0')"
                    />

                    <OrderPreviewCard
                      v-if="showDraftOrderCard && !isOrderSubmitted"
                      :fields="orderFields"
                      :filled-count="filledCount"
                      :total-field-count="totalFieldCount"
                      :order-completeness="orderCompleteness"
                      :effective-service-type-display="effectiveServiceTypeDisplay"
                      :selected-product="selectedProduct"
                      :coverage-notice="coverageNotice"
                      :missing-info-text="missingInfoText"
                      :is-updating-order-info="isUpdatingOrderInfo"
                      :updating-field-key="updatingFieldKey"
                      :can-confirm-order="canConfirmOrder"
                      :can-cancel-order="canCancelOrder"
                      @update-field="updateOrderInfoField"
                      @confirm="confirmOrder"
                      @cancel="cancelOrder"
                    />
                  </div>
                  <p class="mt-2 text-[11px] text-slate-400">{{ currentTime() }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Input area -->
        <div class="shrink-0 border-t border-slate-100/80 bg-white px-5 py-4">
          <!-- Error -->
          <div v-if="errorMessage" class="mb-3 flex items-center gap-2 rounded-xl border border-red-100 bg-red-50 px-4 py-2.5 text-[12px] text-red-600">
            <svg class="h-3.5 w-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
            <span class="flex-1">{{ errorMessage }}</span>
            <button class="opacity-50 hover:opacity-100" @click="errorMessage = ''">✕</button>
          </div>

          <!-- Input box -->
          <div class="mx-auto max-w-[640px]">
            <div class="flex items-end gap-2 rounded-2xl bg-slate-100 px-4 py-3 transition-all duration-200 focus-within:bg-slate-50 focus-within:shadow-[0_0_0_2px_rgba(99,102,241,0.15)]">
              <textarea
                v-model="inputText"
                class="flex-1 resize-none border-none bg-transparent text-[15px] leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-50"
                style="min-height:24px; max-height:160px; overflow-y:auto;"
                rows="1"
                placeholder="描述商品和故障，例如：1208 房空调不制冷…"
                :disabled="isSending"
                @keydown.enter.exact.prevent="sendMessage()"
                @input="autoGrow"
              ></textarea>

              <div class="flex shrink-0 items-center gap-1 pb-0.5">
                <!-- Voice button -->
                <button
                  class="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
                  :class="isListening ? 'bg-red-500 !text-white hover:!bg-red-600' : ''"
                  :disabled="isSending"
                  :title="isListening ? '停止录音' : '语音输入'"
                  @click="toggleListening"
                >
                  <span v-if="isListening" class="flex h-3 w-3 items-center justify-center">
                    <span class="absolute inline-flex h-3 w-3 animate-ping rounded-full bg-red-300 opacity-75"></span>
                    <span class="relative h-2 w-2 rounded-full bg-white"></span>
                  </span>
                  <svg v-else class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/>
                  </svg>
                </button>

                <!-- Send button -->
                <button
                  class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm transition hover:bg-indigo-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
                  :disabled="!inputText.trim() || isSending"
                  @click="sendMessage()"
                >
                  <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18"/>
                  </svg>
                </button>
              </div>
            </div>
            <p class="mt-2 text-center text-[11px] text-slate-400">Enter 发送 · Shift+Enter 换行</p>
          </div>
        </div>
      </div>

      <!-- ── Right Panel ── -->
      <div class="hidden w-[300px] shrink-0 flex-col gap-3 overflow-y-auto lg:flex">

        <OrderPreviewCard
          v-if="showDraftOrderCard"
          variant="sidebar"
          :fields="orderFields"
          :filled-count="filledCount"
          :total-field-count="totalFieldCount"
          :order-completeness="orderCompleteness"
          :effective-service-type-display="effectiveServiceTypeDisplay"
          :selected-product="selectedProduct"
          :coverage-notice="coverageNotice"
          :missing-info-text="missingInfoText"
          :is-submitting-order="isSubmittingOrder"
          :has-submission-failure="hasSubmissionFailure"
          :submission-missing-text="submissionMissingText"
          :is-updating-order-info="isUpdatingOrderInfo"
          :updating-field-key="updatingFieldKey"
          :can-confirm-order="canConfirmOrder"
          :can-cancel-order="canCancelOrder"
          @update-field="updateOrderInfoField"
          @confirm="confirmOrder"
          @cancel="cancelOrder"
          @reset="resetOrder"
        />

        <!-- API params card -->
        <div class="shrink-0 rounded-2xl border border-slate-200 bg-white shadow-sm">
          <button
            class="flex w-full items-center justify-between px-4 py-3 text-left"
            @click="showApiParams = !showApiParams"
          >
            <div>
              <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Request Params</p>
              <p class="mt-0.5 text-sm font-semibold text-slate-800">接口参数</p>
              <p class="mt-1 text-[11px] text-slate-500">
                {{ apiParams.userId }} · 租户 {{ apiParams.tenantId }}
              </p>
            </div>
            <svg
              class="h-4 w-4 text-slate-400 transition"
              :class="showApiParams ? 'rotate-180' : ''"
              fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>

          <div v-if="showApiParams" class="border-t border-slate-100 px-4 py-3.5">
            <div class="mb-3 rounded-xl border border-amber-100 bg-amber-50/80 px-3 py-2 text-[11px] leading-5 text-amber-800">
              这些参数会作为请求 Header 发送给后端，修改后请点击「保存参数」。
            </div>

            <div class="max-h-[360px] space-y-2.5 overflow-y-auto pr-0.5">
              <label
                v-for="field in API_PARAM_FIELDS"
                :key="field.key"
                class="block"
              >
                <span class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{{ field.label }}</span>
                <input
                  v-model="apiParams[field.key]"
                  type="text"
                  :placeholder="field.placeholder"
                  class="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] text-slate-800 outline-none transition focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </label>
            </div>

            <div class="mt-3 flex gap-2">
              <button
                class="flex-1 rounded-xl bg-indigo-600 py-2 text-[12px] font-semibold text-white transition hover:bg-indigo-700"
                @click="persistApiParams"
              >保存参数</button>
              <button
                class="rounded-xl border border-slate-200 px-3 py-2 text-[12px] font-medium text-slate-600 transition hover:bg-slate-50"
                @click="restoreDefaultApiParams"
              >恢复默认</button>
            </div>
            <p v-if="apiParamsSaved" class="mt-2 text-center text-[11px] font-medium text-emerald-600">已保存，后续请求将使用新参数</p>
            <p class="mt-2 break-all text-[10px] leading-4 text-slate-400">
              当前 Token：{{ apiParams.accessToken || '未填写' }}
            </p>
          </div>
        </div>

        <!-- Session info mini card -->
        <div class="shrink-0 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div class="flex items-center justify-between">
            <p class="text-[11px] font-semibold text-slate-400">当前会话</p>
            <span class="flex items-center gap-1 text-[11px] text-emerald-600">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
              进行中
            </span>
          </div>
          <p class="mt-1 font-mono text-xs font-medium text-slate-600">{{ shortSessionId }}</p>
        </div>
      </div>
    </main>

    <!-- Mobile API params drawer -->
    <div
      v-if="showApiParamsMobile"
      class="fixed inset-0 z-[60] flex items-end bg-slate-900/40 lg:hidden"
      @click.self="showApiParamsMobile = false"
    >
      <div class="max-h-[85vh] w-full overflow-y-auto rounded-t-3xl border border-slate-200 bg-white p-5 shadow-2xl">
        <div class="mb-4 flex items-center justify-between">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Request Params</p>
            <h3 class="text-base font-semibold text-slate-800">接口参数</h3>
          </div>
          <button class="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100" @click="showApiParamsMobile = false">✕</button>
        </div>
        <div class="space-y-2.5">
          <label v-for="field in API_PARAM_FIELDS" :key="`mobile-${field.key}`" class="block">
            <span class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{{ field.label }}</span>
            <input
              v-model="apiParams[field.key]"
              type="text"
              :placeholder="field.placeholder"
              class="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-[13px] text-slate-800 outline-none focus:border-indigo-300 focus:bg-white"
            />
          </label>
        </div>
        <div class="mt-4 flex gap-2">
          <button
            class="flex-1 rounded-xl bg-indigo-600 py-3 text-[13px] font-semibold text-white"
            @click="persistApiParams(); showApiParamsMobile = false"
          >保存参数</button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-3 text-[13px] font-medium text-slate-600"
            @click="restoreDefaultApiParams"
          >恢复默认</button>
        </div>
      </div>
    </div>
  </div>
</template>
