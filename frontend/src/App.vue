<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

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
}

interface SessionSummary {
  id: string
  title: string
  status: string
  time: string
}

const SESSION_KEY = 'repair_voice_session_id'
const HISTORY_KEY = 'repair_voice_history_sessions'

const sessionId = ref(localStorage.getItem(SESSION_KEY) || crypto.randomUUID())
const inputText = ref('')
const isListening = ref(false)
const isSending = ref(false)
const errorMessage = ref('')
const chatBodyRef = ref<HTMLElement | null>(null)

const messages = ref<ChatMessage[]>([createWelcomeMessage()])
const preOrder = ref<PreOrder>(createEmptyOrder())
const historySessions = ref<SessionSummary[]>(loadHistorySessions())

localStorage.setItem(SESSION_KEY, sessionId.value)

const shortSessionId = computed(() => sessionId.value.slice(0, 8).toUpperCase())

const orderCompleteness = computed(() => {
  const values = Object.values(preOrder.value)
  const filledCount = values.filter(Boolean).length
  return Math.round((filledCount / values.length) * 100)
})

const canSubmit = computed(() => {
  return Boolean(preOrder.value.roomNumber && preOrder.value.product && preOrder.value.fault)
})

function currentTime() {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date())
}

function createWelcomeMessage(): ChatMessage {
  return {
    id: Date.now(),
    role: 'assistant',
    content: '您好，我是维修下单助手。请告诉我房号、设备和故障情况，我会同步整理成预下单卡片。',
    time: currentTime(),
  }
}

function createEmptyOrder(): PreOrder {
  return {
    roomNumber: null,
    product: null,
    fault: null,
    area: null,
    urgency: null,
  }
}

function loadHistorySessions(): SessionSummary[] {
  const fallback = [
    { id: '1208', title: '1208 空调不制冷', status: '待确认', time: '09:42' },
    { id: '0816', title: '0816 水龙头漏水', status: '已派单', time: '昨天' },
    { id: '0321', title: '0321 门锁打不开', status: '已完成', time: '周日' },
  ]

  try {
    const saved = localStorage.getItem(HISTORY_KEY)
    return saved ? JSON.parse(saved) : fallback
  } catch {
    return fallback
  }
}

function persistHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(historySessions.value.slice(0, 8)))
}

function appendMessage(role: Role, content: string) {
  messages.value.push({
    id: Date.now() + Math.floor(Math.random() * 1000),
    role,
    content,
    time: currentTime(),
  })

  nextTick(() => {
    chatBodyRef.value?.scrollTo({
      top: chatBodyRef.value.scrollHeight,
      behavior: 'smooth',
    })
  })
}

function inferPreOrder(text: string) {
  // 前端只做轻量预览，真实抽取仍应以后端 Agent 为准。
  const roomMatch = text.match(/(\d{3,5}|[A-Z]栋\d{2,5})/)
  if (roomMatch) preOrder.value.roomNumber = roomMatch[1]

  const productWords = ['空调', '电视', '水龙头', '门锁', '洗碗机', '打印机', '马桶', '窗帘']
  const product = productWords.find((word) => text.includes(word))
  if (product) preOrder.value.product = product

  const faultWords = ['不制冷', '漏水', '打不开', '不亮', '卡纸', '堵塞', '不通电', '噪音大']
  const fault = faultWords.find((word) => text.includes(word))
  if (fault) preOrder.value.fault = fault

  const areaWords = ['卫生间', '卧室', '客厅', '走廊', '会议室', '厨房', '大堂']
  const area = areaWords.find((word) => text.includes(word))
  if (area) preOrder.value.area = area

  if (/马上|很急|危险|漏电|严重/.test(text)) {
    preOrder.value.urgency = 'urgent'
  } else if (/尽快|比较急/.test(text)) {
    preOrder.value.urgency = 'high'
  } else if (/不急|有空/.test(text)) {
    preOrder.value.urgency = 'low'
  } else if (!preOrder.value.urgency) {
    preOrder.value.urgency = 'medium'
  }
}

async function sendMessage(text = inputText.value) {
  const content = text.trim()
  if (!content || isSending.value) return

  errorMessage.value = ''
  inputText.value = ''
  inferPreOrder(content)
  appendMessage('user', content)
  isSending.value = true

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId.value,
        message: content,
      }),
    })

    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }

    const data = await response.json()
    if (data.session_id) {
      sessionId.value = data.session_id
      localStorage.setItem(SESSION_KEY, data.session_id)
    }
    appendMessage('assistant', data.answer || '我已收到，会继续为您处理。')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '网络请求失败'
    appendMessage('assistant', '后端暂时不可用，我先帮您保留这条预下单信息。')
  } finally {
    isSending.value = false
  }
}

function toggleListening() {
  if (isListening.value) {
    isListening.value = false
    return
  }

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!Recognition) {
    errorMessage.value = '当前浏览器不支持语音识别，请使用文字输入。'
    return
  }

  const recognition = new Recognition()
  recognition.lang = 'zh-CN'
  recognition.interimResults = false
  recognition.maxAlternatives = 1
  isListening.value = true

  recognition.onresult = (event: SpeechRecognitionEvent) => {
    const transcript = event.results[0]?.[0]?.transcript || ''
    inputText.value = transcript
    sendMessage(transcript)
  }

  recognition.onerror = () => {
    errorMessage.value = '语音识别失败，请再试一次。'
  }

  recognition.onend = () => {
    isListening.value = false
  }

  recognition.start()
}

function resetOrder() {
  preOrder.value = createEmptyOrder()
}

function summarizeCurrentSession() {
  const userMessage = messages.value.find((message) => message.role === 'user')
  if (!userMessage) return

  const title = [
    preOrder.value.roomNumber,
    preOrder.value.product,
    preOrder.value.fault,
  ].filter(Boolean).join(' ') || userMessage.content.slice(0, 18)

  historySessions.value = [
    {
      id: sessionId.value,
      title,
      status: canSubmit.value ? '待确认' : '信息待补充',
      time: currentTime(),
    },
    ...historySessions.value.filter((item) => item.id !== sessionId.value),
  ].slice(0, 8)
  persistHistory()
}

function createNewSession() {
  summarizeCurrentSession()
  sessionId.value = crypto.randomUUID()
  localStorage.setItem(SESSION_KEY, sessionId.value)
  inputText.value = ''
  errorMessage.value = ''
  isListening.value = false
  isSending.value = false
  messages.value = [createWelcomeMessage()]
  resetOrder()

  nextTick(() => {
    chatBodyRef.value?.scrollTo({ top: 0 })
  })
}

function urgencyLabel(urgency: PreOrder['urgency']) {
  const map = {
    low: '低',
    medium: '普通',
    high: '较急',
    urgent: '紧急',
  }
  return urgency ? map[urgency] : '待判断'
}
</script>

<template>
  <main class="grain relative min-h-screen overflow-hidden bg-[#f5efe4] text-[#243022]">
    <div class="absolute left-[-10rem] top-[-12rem] h-[30rem] w-[30rem] rounded-full bg-[#d8ad78]/35 blur-3xl"></div>
    <div class="absolute bottom-[-16rem] right-[-8rem] h-[34rem] w-[34rem] rounded-full bg-[#8bb8a8]/40 blur-3xl"></div>

    <section class="relative z-10 mx-auto grid min-h-screen max-w-7xl gap-5 px-4 py-5 lg:grid-cols-[18rem_minmax(0,1fr)_22rem] xl:px-6">
      <aside class="hidden rounded-[2rem] border border-[#d8cbb8] bg-white/65 p-4 shadow-xl shadow-[#a6815f]/10 backdrop-blur-xl lg:flex lg:flex-col">
        <div class="rounded-[1.5rem] bg-[#263422] p-5 text-[#fffaf0]">
          <p class="text-xs uppercase tracking-[0.32em] text-[#d7b98a]">Hotel Desk</p>
          <h1 class="mt-3 font-display text-3xl font-semibold leading-tight">AI 语音维修下单</h1>
          <p class="mt-3 text-sm leading-6 text-white/70">为客房维修场景快速收集房号、设备、故障和紧急度。</p>
        </div>

        <button
          class="mt-4 rounded-2xl bg-[#c77943] px-4 py-3 text-left font-semibold text-white shadow-lg shadow-[#c77943]/20 transition hover:-translate-y-0.5 hover:bg-[#b96c38]"
          @click="createNewSession"
        >
          + 新建会话
          <span class="mt-1 block text-xs font-normal text-white/70">清空当前对话并生成新的 Session</span>
        </button>

        <div class="mt-6 flex items-center justify-between text-sm">
          <span class="font-semibold text-[#59624f]">历史会话</span>
          <span class="rounded-full bg-[#efe4d3] px-2.5 py-1 text-xs text-[#8a6c4c]">{{ historySessions.length }} 条</span>
        </div>

        <div class="mt-3 space-y-2 overflow-y-auto pr-1">
          <button
            v-for="item in historySessions"
            :key="item.id"
            class="w-full rounded-2xl border border-[#e7dac7] bg-[#fffaf2]/80 p-3 text-left transition hover:border-[#c77943]/50 hover:bg-white"
          >
            <div class="flex items-center justify-between gap-3">
              <p class="truncate font-semibold text-[#283422]">{{ item.title }}</p>
              <span class="shrink-0 text-xs text-[#9a866d]">{{ item.time }}</span>
            </div>
            <p class="mt-1 text-xs text-[#c77943]">{{ item.status }}</p>
          </button>
        </div>
      </aside>

      <div class="flex min-h-[calc(100vh-2.5rem)] flex-col rounded-[2rem] border border-[#d8cbb8] bg-[#fffaf2]/85 p-4 shadow-2xl shadow-[#a6815f]/15 backdrop-blur-xl md:p-5">
        <header class="flex flex-wrap items-center justify-between gap-3 border-b border-[#eadbc7] pb-4">
          <div>
            <p class="text-xs uppercase tracking-[0.35em] text-[#b9854c]">Repair Conversation</p>
            <h2 class="mt-2 font-display text-3xl font-semibold tracking-tight text-[#263422] md:text-4xl">
              当前维修会话
            </h2>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-full border border-[#d7c5ad] bg-white/80 px-4 py-2 text-sm text-[#6f5a43]">
              Session {{ shortSessionId }}
            </span>
            <button
              class="rounded-full bg-[#263422] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#35472d] lg:hidden"
              @click="createNewSession"
            >
              新建会话
            </button>
          </div>
        </header>

        <div ref="chatBodyRef" class="mt-5 flex-1 space-y-4 overflow-y-auto rounded-[1.5rem] bg-[#f8eddd]/70 p-3">
          <article
            v-for="message in messages"
            :key="message.id"
            class="flex"
            :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[84%] rounded-[1.4rem] px-5 py-4 shadow-sm"
              :class="
                message.role === 'user'
                  ? 'bg-[#2f614d] text-white'
                  : 'border border-[#e7d5bd] bg-white text-[#283422]'
              "
            >
              <p class="whitespace-pre-wrap leading-7">{{ message.content }}</p>
              <p class="mt-2 text-right text-xs opacity-60">{{ message.time }}</p>
            </div>
          </article>
        </div>

        <div class="mt-4 rounded-[1.75rem] border border-[#e1d1bc] bg-white/85 p-4 shadow-lg shadow-[#a6815f]/10">
          <div class="mb-4 flex items-center justify-between gap-3">
            <div>
              <p class="text-sm font-semibold text-[#263422]">语音或文字输入</p>
              <p class="text-xs text-[#86745d]">Enter 发送，Shift + Enter 换行</p>
            </div>
            <div class="flex items-end gap-1.5" :class="{ 'opacity-100': isListening, 'opacity-30': !isListening }">
              <span v-for="bar in 5" :key="bar" class="voice-bar h-7 w-1.5 rounded-full bg-[#c77943]"></span>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-[auto_1fr_auto]">
            <button
              class="group relative h-16 w-16 rounded-2xl border border-[#d5b083] bg-[#fbefe0] text-2xl shadow-inner transition hover:scale-105 disabled:cursor-not-allowed disabled:opacity-60"
              :class="{ 'bg-[#c77943] text-white shadow-lg shadow-[#c77943]/25': isListening }"
              :disabled="isSending"
              @click="toggleListening"
            >
              <span class="relative">{{ isListening ? '■' : '🎙' }}</span>
            </button>

            <textarea
              v-model="inputText"
              class="min-h-16 resize-none rounded-2xl border border-[#e0cdb5] bg-[#fffdf8] px-4 py-3 text-base text-[#263422] outline-none transition placeholder:text-[#a7937c] focus:border-[#c77943] focus:ring-4 focus:ring-[#c77943]/10"
              placeholder="例如：1208 房间空调不制冷，比较急"
              @keydown.enter.exact.prevent="sendMessage()"
            ></textarea>

            <button
              class="rounded-2xl bg-[#c77943] px-7 py-3 font-semibold text-white shadow-lg shadow-[#c77943]/20 transition hover:-translate-y-0.5 hover:bg-[#b96c38] disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="isSending || !inputText.trim()"
              @click="sendMessage()"
            >
              {{ isSending ? '发送中' : '发送' }}
            </button>
          </div>

          <p v-if="errorMessage" class="mt-3 rounded-xl bg-[#fff1e7] px-3 py-2 text-sm text-[#b3542e]">{{ errorMessage }}</p>
        </div>
      </div>

      <aside class="grid gap-5">
        <section class="rounded-[2rem] border border-[#d8cbb8] bg-white/80 p-5 shadow-xl shadow-[#a6815f]/10 backdrop-blur-xl">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-xs uppercase tracking-[0.32em] text-[#b9854c]">Draft Order</p>
              <h2 class="mt-2 font-display text-3xl font-semibold text-[#263422]">预下单卡片</h2>
            </div>
            <div class="rounded-full bg-[#263422] px-3 py-1 text-sm text-white">{{ orderCompleteness }}%</div>
          </div>

          <div class="mt-5 h-2 overflow-hidden rounded-full bg-[#eee1cf]">
            <div class="h-full rounded-full bg-[#c77943] transition-all" :style="{ width: `${orderCompleteness}%` }"></div>
          </div>

          <dl class="mt-6 grid gap-3">
            <div class="rounded-2xl bg-[#f6ebdc] p-4">
              <dt class="text-xs text-[#8d7a62]">房号</dt>
              <dd class="mt-1 text-lg font-semibold text-[#263422]">{{ preOrder.roomNumber || '待识别' }}</dd>
            </div>
            <div class="rounded-2xl bg-[#f6ebdc] p-4">
              <dt class="text-xs text-[#8d7a62]">商品/设备</dt>
              <dd class="mt-1 text-lg font-semibold text-[#263422]">{{ preOrder.product || '待识别' }}</dd>
            </div>
            <div class="rounded-2xl bg-[#f6ebdc] p-4">
              <dt class="text-xs text-[#8d7a62]">故障</dt>
              <dd class="mt-1 text-lg font-semibold text-[#263422]">{{ preOrder.fault || '待识别' }}</dd>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div class="rounded-2xl bg-[#f6ebdc] p-4">
                <dt class="text-xs text-[#8d7a62]">区域</dt>
                <dd class="mt-1 font-semibold text-[#263422]">{{ preOrder.area || '待补充' }}</dd>
              </div>
              <div class="rounded-2xl bg-[#f6ebdc] p-4">
                <dt class="text-xs text-[#8d7a62]">紧急度</dt>
                <dd class="mt-1 font-semibold text-[#263422]">{{ urgencyLabel(preOrder.urgency) }}</dd>
              </div>
            </div>
          </dl>

          <div class="mt-6 grid grid-cols-2 gap-3">
            <button
              class="rounded-2xl bg-[#263422] px-4 py-3 font-semibold text-white transition hover:bg-[#35472d] disabled:opacity-40"
              :disabled="!canSubmit"
            >
              确认预下单
            </button>
            <button
              class="rounded-2xl border border-[#d5b083] bg-white px-4 py-3 font-semibold text-[#6f4d2f] transition hover:bg-[#fbefe0]"
              @click="resetOrder"
            >
              清空
            </button>
          </div>
        </section>

        <section class="rounded-[2rem] border border-[#d8cbb8] bg-[#263422] p-5 text-white shadow-xl shadow-[#263422]/15">
          <p class="text-xs uppercase tracking-[0.32em] text-[#d7b98a]">Tips</p>
          <h2 class="mt-2 font-display text-2xl font-semibold">推荐描述格式</h2>
          <div class="mt-4 space-y-3 text-sm leading-6 text-white/75">
            <p class="rounded-2xl bg-white/10 p-3">“1208 房间，卫生间水龙头漏水，比较急。”</p>
            <p class="rounded-2xl bg-white/10 p-3">“B栋 301 门锁打不开，客人在门外。”</p>
          </div>
        </section>
      </aside>
    </section>
  </main>
</template>
