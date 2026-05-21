<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

type Role = 'user' | 'assistant'

interface ChatMessage {
  id: number
  role: Role
  content: string
  time: string
}

interface PreOrder {
  roomNumber: string | null
  product: string | null
  fault: string | null
  area: string | null
  urgency: 'low' | 'medium' | 'high' | 'urgent' | null
  matchedProductName: string | null
  matchedProductCode: string | null
  status: string | null
}

interface OrderPreview {
  status?: string | null
  order_info?: {
    room_number?: string | null
    product?: string | null
    fault?: string | null
    area?: string | null
    urgency?: PreOrder['urgency']
  }
  matched_product?: {
    service_product_name?: string | null
    service_product_code?: string | null
  }
}

interface SessionSummary {
  id: string
  title: string
  status: string
  time: string
}

const SESSION_KEY = 'order_voice_session_id'
const HISTORY_KEY = 'order_voice_history_sessions'

const sessionId = ref(localStorage.getItem(SESSION_KEY) || crypto.randomUUID())
const inputText = ref('')
const isListening = ref(false)
const isSending = ref(false)
const errorMessage = ref('')
const showHistory = ref(false)
const chatBodyRef = ref<HTMLElement | null>(null)
const historyRef = ref<HTMLElement | null>(null)

const messages = ref<ChatMessage[]>([])
const preOrder = ref<PreOrder>(createEmptyOrder())
const historySessions = ref<SessionSummary[]>(loadHistorySessions())

localStorage.setItem(SESSION_KEY, sessionId.value)

const shortSessionId = computed(() => sessionId.value.slice(0, 8).toUpperCase())
const hasUserMessage = computed(() => messages.value.some((m) => m.role === 'user'))

const filledCount = computed(() =>
  [preOrder.value.roomNumber, preOrder.value.product, preOrder.value.fault, preOrder.value.area, preOrder.value.urgency].filter(Boolean).length
)
const orderCompleteness = computed(() => Math.round((filledCount.value / 5) * 100))

const canSubmit = computed(() =>
  Boolean(preOrder.value.roomNumber && preOrder.value.product && preOrder.value.fault)
)

const urgencyConfig = computed(() => {
  if (!preOrder.value.urgency) return { label: '—', icon: '·', color: 'text-slate-400', bg: 'bg-slate-50' }
  return {
    low:    { label: '低优先级', icon: '↓', color: 'text-emerald-700', bg: 'bg-emerald-50' },
    medium: { label: '普通',     icon: '→', color: 'text-blue-700',    bg: 'bg-blue-50'    },
    high:   { label: '较急',     icon: '↑', color: 'text-amber-700',   bg: 'bg-amber-50'   },
    urgent: { label: '紧急',     icon: '!', color: 'text-red-700',     bg: 'bg-red-50'     },
  }[preOrder.value.urgency]
})

const orderFields = computed(() => [
  { key: 'roomNumber', icon: '🏠', label: '房间号', value: preOrder.value.roomNumber },
  { key: 'product',   icon: '🔧', label: '商品/设备', value: preOrder.value.product },
  { key: 'fault',     icon: '⚡', label: '问题描述', value: preOrder.value.fault },
  { key: 'area',      icon: '📍', label: '所在区域', value: preOrder.value.area },
])

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

function createEmptyOrder(): PreOrder {
  return {
    roomNumber: null,
    product: null,
    fault: null,
    area: null,
    urgency: null,
    matchedProductName: null,
    matchedProductCode: null,
    status: null,
  }
}

function loadHistorySessions(): SessionSummary[] {
  const fallback: SessionSummary[] = [
    { id: '1208', title: '1208 空调不制冷', status: '待确认', time: '09:42' },
    { id: '0816', title: '0816 水龙头漏水',  status: '已派单', time: '昨天' },
    { id: '0321', title: '0321 门锁打不开',  status: '已完成', time: '周日' },
  ]
  try {
    const saved = localStorage.getItem(HISTORY_KEY)
    return saved ? JSON.parse(saved) : fallback
  } catch { return fallback }
}

function persistHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(historySessions.value.slice(0, 10)))
}

function appendMessage(role: Role, content: string) {
  messages.value.push({ id: Date.now() + Math.floor(Math.random() * 999), role, content, time: currentTime() })
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight, behavior: 'smooth' }))
}

function inferPreOrder(text: string) {
  const roomMatch = text.match(/(\d{3,5}|[A-Z]栋\d{2,5})/)
  if (roomMatch) preOrder.value.roomNumber = roomMatch[1]

  const pw = ['空调', '电视', '水龙头', '门锁', '洗碗机', '打印机', '马桶', '窗帘']
  const p = pw.find((w) => text.includes(w))
  if (p) preOrder.value.product = p

  const fw = ['不制冷', '漏水', '打不开', '不亮', '卡纸', '堵塞', '不通电', '噪音大', '没信号']
  const f = fw.find((w) => text.includes(w))
  if (f) preOrder.value.fault = f

  const aw = ['卫生间', '卧室', '客厅', '走廊', '会议室', '厨房', '大堂']
  const a = aw.find((w) => text.includes(w))
  if (a) preOrder.value.area = a

  if (/马上|很急|危险|漏电|严重/.test(text)) preOrder.value.urgency = 'urgent'
  else if (/尽快|比较急/.test(text)) preOrder.value.urgency = 'high'
  else if (/不急|有空/.test(text)) preOrder.value.urgency = 'low'
  else if (!preOrder.value.urgency) preOrder.value.urgency = 'medium'
}

function applyOrderPreview(preview?: OrderPreview | null) {
  if (!preview) return
  const orderInfo = preview.order_info || {}
  preOrder.value.roomNumber = orderInfo.room_number ?? preOrder.value.roomNumber
  preOrder.value.product = orderInfo.product ?? preOrder.value.product
  preOrder.value.fault = orderInfo.fault ?? preOrder.value.fault
  preOrder.value.area = orderInfo.area ?? preOrder.value.area
  preOrder.value.urgency = orderInfo.urgency ?? preOrder.value.urgency
  preOrder.value.status = preview.status ?? preOrder.value.status
  preOrder.value.matchedProductName = preview.matched_product?.service_product_name ?? preOrder.value.matchedProductName
  preOrder.value.matchedProductCode = preview.matched_product?.service_product_code ?? preOrder.value.matchedProductCode
}

async function sendMessage(text = inputText.value) {
  const content = text.trim()
  if (!content || isSending.value) return

  errorMessage.value = ''
  inputText.value = ''
  const ta = document.querySelector<HTMLTextAreaElement>('textarea')
  if (ta) ta.style.height = 'auto'

  inferPreOrder(content)
  appendMessage('user', content)
  isSending.value = true

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value, message: content }),
    })
    if (!res.ok) throw new Error(`请求失败 ${res.status}`)
    const data = await res.json()
    if (data.session_id) { sessionId.value = data.session_id; localStorage.setItem(SESSION_KEY, data.session_id) }
    applyOrderPreview(data.order_preview)
    appendMessage('assistant', data.answer || '我已收到，会继续为您处理。')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '网络请求失败'
    appendMessage('assistant', '后端暂时不可用，已帮您保留预下单信息。')
  } finally {
    isSending.value = false
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

function resetOrder() { preOrder.value = createEmptyOrder() }

function summarizeCurrentSession() {
  const u = messages.value.find((m) => m.role === 'user')
  if (!u) return
  const title = [preOrder.value.roomNumber, preOrder.value.product, preOrder.value.fault].filter(Boolean).join(' ') || u.content.slice(0, 16)
  historySessions.value = [
    { id: sessionId.value, title, status: canSubmit.value ? '待确认' : '信息待补充', time: currentTime() },
    ...historySessions.value.filter((i) => i.id !== sessionId.value),
  ].slice(0, 10)
  persistHistory()
}

function createNewSession() {
  summarizeCurrentSession()
  sessionId.value = crypto.randomUUID()
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

onMounted(() => document.addEventListener('mousedown', closeHistoryOnOutside))
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

      <!-- Session badge -->
      <div class="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
        <span class="text-[11px] font-medium text-slate-500">会话 #{{ shortSessionId }}</span>
      </div>

      <div class="ml-auto flex items-center gap-2">
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
                    <p class="text-[15px] leading-7 text-slate-700 whitespace-pre-wrap">{{ message.content }}</p>
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
              <div v-if="isSending" class="flex items-start gap-3.5">
                <div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-[12px] font-bold text-white shadow-sm shadow-indigo-600/20">H</div>
                <div class="flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-slate-100 bg-slate-50 px-4 py-3.5">
                  <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce"></span>
                  <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style="animation-delay:150ms"></span>
                  <span class="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style="animation-delay:300ms"></span>
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
                placeholder="描述房间号、商品和问题…"
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
      <div class="hidden w-[272px] shrink-0 flex-col gap-3 lg:flex">

        <!-- Order Card -->
        <div class="flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">

          <!-- Card header with circular progress -->
          <div class="flex items-center gap-4 border-b border-slate-100 px-5 py-4">
            <!-- Circular progress ring -->
            <div class="relative h-[72px] w-[72px] shrink-0">
              <svg class="-rotate-90" width="72" height="72" viewBox="0 0 80 80">
                <circle cx="40" cy="40" :r="progressR" fill="none" stroke="#e2e8f0" stroke-width="5"/>
                <circle
                  cx="40" cy="40" :r="progressR" fill="none"
                  :stroke="orderCompleteness === 100 ? '#10b981' : '#6366f1'"
                  stroke-width="5" stroke-linecap="round"
                  :stroke-dasharray="progressCircumference"
                  :stroke-dashoffset="progressOffset"
                  class="transition-all duration-500"
                />
              </svg>
              <div class="absolute inset-0 flex flex-col items-center justify-center">
                <span class="text-lg font-bold leading-none text-slate-800">{{ orderCompleteness }}<span class="text-xs font-normal">%</span></span>
              </div>
            </div>

            <div class="min-w-0 flex-1">
              <p class="text-[10px] font-semibold uppercase tracking-widest text-slate-400">Draft Order</p>
              <h2 class="mt-0.5 text-sm font-semibold text-slate-800">预下单卡片</h2>
              <p class="mt-1 text-xs text-slate-500">已填写 <span class="font-semibold text-slate-700">{{ filledCount }}</span> / 5 项</p>
            </div>
          </div>

          <!-- Fields -->
          <div class="flex-1 overflow-y-auto p-3.5 space-y-2">
            <div
              v-for="field in orderFields"
              :key="field.key"
              class="group flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-all duration-300"
              :class="field.value ? 'border-emerald-100 bg-emerald-50/50' : 'border-slate-100 bg-slate-50/60'"
            >
              <span class="shrink-0 text-[15px] leading-none">{{ field.icon }}</span>
              <div class="min-w-0 flex-1">
                <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{{ field.label }}</p>
                <p class="mt-0.5 truncate text-[13px] font-medium" :class="field.value ? 'text-slate-800' : 'text-slate-300'">
                  {{ field.value || '待识别' }}
                </p>
              </div>
              <div
                class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-all duration-300"
                :class="field.value ? 'bg-emerald-500' : 'bg-slate-200'"
              >
                <svg class="h-3 w-3 text-white" :class="field.value ? 'opacity-100' : 'opacity-0'" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
                </svg>
              </div>
            </div>

            <!-- Urgency field -->
            <div
              class="flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-all duration-300"
              :class="preOrder.urgency ? urgencyConfig.bg + ' border-transparent' : 'border-slate-100 bg-slate-50/60'"
            >
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/80 text-[13px] font-bold shadow-sm" :class="urgencyConfig.color">
                {{ urgencyConfig.icon }}
              </span>
              <div class="min-w-0 flex-1">
                <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">紧急程度</p>
                <p class="mt-0.5 text-[13px] font-medium" :class="preOrder.urgency ? urgencyConfig.color : 'text-slate-300'">
                  {{ urgencyConfig.label }}
                </p>
              </div>
            </div>

            <!-- Matched product -->
            <div
              class="flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-all duration-300"
              :class="preOrder.matchedProductCode ? 'border-indigo-100 bg-indigo-50/60' : 'border-slate-100 bg-slate-50/60'"
            >
              <span class="shrink-0 text-[15px] leading-none">📦</span>
              <div class="min-w-0 flex-1">
                <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">匹配商品</p>
                <p class="mt-0.5 truncate text-[13px] font-medium" :class="preOrder.matchedProductName ? 'text-slate-800' : 'text-slate-300'">
                  {{ preOrder.matchedProductName || '待匹配' }}
                </p>
                <p v-if="preOrder.matchedProductCode" class="mt-0.5 truncate text-[11px] text-slate-400">{{ preOrder.matchedProductCode }}</p>
              </div>
            </div>

            <!-- Tip -->
            <div class="mt-1 rounded-xl border border-indigo-100 bg-indigo-50/60 px-3.5 py-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-indigo-400">示例格式</p>
              <p class="mt-1.5 text-[12px] leading-5 text-indigo-700/70">"1208 房，卫生间水龙头漏水，比较急。"</p>
            </div>
          </div>

          <!-- Action buttons -->
          <div class="space-y-2 border-t border-slate-100 p-3.5">
            <button
              class="w-full rounded-xl bg-indigo-600 py-2.5 text-[13px] font-semibold text-white shadow-sm shadow-indigo-600/20 transition hover:bg-indigo-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30"
              :disabled="!canSubmit"
            >确认预下单</button>
            <button
              class="w-full rounded-xl border border-slate-200 py-2.5 text-[13px] font-medium text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
              @click="resetOrder"
            >清空卡片</button>
          </div>
        </div>

        <!-- Session info mini card -->
        <div class="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
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
  </div>
</template>
