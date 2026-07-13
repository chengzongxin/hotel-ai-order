<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OrderPreviewCard from './components/OrderPreviewCard.vue'
import OrderStatusNotices from './components/OrderStatusNotices.vue'
import OrderSuccessCard from './components/OrderSuccessCard.vue'
import ProductSelectionCard from './components/ProductSelectionCard.vue'
import ToolCallList from './components/ToolCallList.vue'
import { useChatApi } from './composables/useChatApi'
import { useChatSession, currentTime } from './composables/useChatSession'
import {
  displayOrderFieldValue,
  formatMatchScore,
  useOrderPreview,
} from './composables/useOrderPreview'
import type { OrderPreview } from './types/order'
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

const apiParams = ref<ApiRequestParams>(loadApiParams())
const showApiParams = ref(true)
const showApiParamsMobile = ref(false)
const apiParamsSaved = ref(false)

const inputText = ref('')
const isListening = ref(false)
const isSending = ref(false)
const errorMessage = ref('')
const streamStatus = ref('')
const chatBodyRef = ref<HTMLElement | null>(null)
const historyRef = ref<HTMLElement | null>(null)

const orderPreview = ref<OrderPreview | null>(null)
const isSelectingProduct = ref(false)
const selectingProductCode = ref<string | null>(null)
const isUpdatingOrderInfo = ref(false)
const updatingFieldKey = ref<string | null>(null)

const {
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
  setMessageOrderSuccess,
  upsertMessageToolCall,
  summarizeCurrentSession,
  resetMessages,
  setSessionId,
} = useChatSession(chatBodyRef)

const preview = useOrderPreview(orderPreview, isSending, isUpdatingOrderInfo)
const {
  orderInfo,
  phase,
  submission,
  submittedOrder,
  serviceTypeDisplay,
  effectiveServiceTypeDisplay,
  missingInfo,
  productItems,
  productFeedback,
  selectedProductCode,
  productSelectionRejected,
  selectedProduct,
  isProductSelectionPhase,
  isPreOrderPhase,
  isAwaitingProductSelection,
  showDraftOrderCard,
  submittedOrderId,
  submissionState,
  isSubmittingOrder,
  submissionMissingFields,
  hasSubmissionFailure,
  submissionFailureMessage,
  canSubmit,
  canSelectProduct,
  canRejectProducts,
  hasProductOptions,
  isOrderSubmitted,
  showChatOrderPanel,
  canConfirmOrder,
  canCancelOrder,
  missingInfoText,
  submissionMissingText,
  coverageNotice,
  urgencyConfig,
  orderFields,
  filledCount,
  totalFieldCount,
  orderCompleteness,
  progressCircumference,
  progressOffset,
  isProductSelected,
} = preview

function buildOrderSuccessSnapshot() {
  return {
    orderId: submittedOrderId.value,
    serviceType: effectiveServiceTypeDisplay.value,
    selectedProduct: selectedProduct.value ? { ...selectedProduct.value } : null,
    fields: orderFields.value.map((field) => ({
      ...field,
      options: field.options.map((option) => ({ ...option })),
    })),
    submittedOrder: submittedOrder.value ? { ...submittedOrder.value } : null,
  }
}

const chatApi = useChatApi({
  sessionId,
  messages,
  orderPreview,
  chatBodyRef,
  errorMessage,
  streamStatus,
  isSending,
  isSelectingProduct,
  selectingProductCode,
  isUpdatingOrderInfo,
  updatingFieldKey,
  selectedProductCode,
  apiParams,
  appendMessage,
  setMessageContent,
  appendMessageContent,
  setMessageOrderSuccess,
  upsertMessageToolCall,
  buildOrderSuccessSnapshot,
  isProductSelected,
  canConfirmOrder,
})

const {
  loadSessionHistory,
  updateOrderInfoField,
  selectProduct,
  rejectProducts,
  confirmOrder,
  cancelOrder: requestCancelOrder,
  sendFallbackMessage,
  sendStreamingMessage,
} = chatApi

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

async function switchSession(targetSessionId: string) {
  if (targetSessionId === sessionId.value) {
    showHistory.value = false
    return
  }

  summarizeCurrentSession(orderInfo.value, canSubmit.value)
  setSessionId(targetSessionId)
  inputText.value = ''
  errorMessage.value = ''
  isListening.value = false
  isSending.value = false
  resetMessages()
  resetOrder()
  showHistory.value = false
  await loadSessionHistory(targetSessionId)
  nextTick(() => chatBodyRef.value?.scrollTo({ top: chatBodyRef.value.scrollHeight }))
}

type SuggestionChip = { icon: string; text: string }

const suggestionPool: SuggestionChip[] = [
  { icon: '❄️', text: '1208 空调不制冷，比较急' },
  { icon: '💧', text: '0316 卫生间水龙头漏水' },
  { icon: '🔑', text: 'B栋 301 门锁打不开' },
  { icon: '📺', text: '0501 房间电视没有信号' },
  { icon: '🚿', text: '816 卫生间花洒出水很小' },
  { icon: '💡', text: '大堂灯闪烁，麻烦安排维修' },
  { icon: '🧺', text: '洗衣房洗衣机需要安装，货已经到了' },
  { icon: '🪟', text: '1506 窗户关不上，有点漏风' },
  { icon: '🚪', text: '公区仓库门合页松动，需要修一下' },
  { icon: '🧊', text: '餐厅冰柜温度降不下来' },
  { icon: '📡', text: '0902 网络连不上，请尽快处理' },
  { icon: '🛁', text: '2301 浴缸下水很慢' },
]
const SUGGESTION_COUNT = 4
const suggestions = ref<SuggestionChip[]>(buildRandomSuggestions())

function buildRandomSuggestions(): SuggestionChip[] {
  return [...suggestionPool].sort(() => Math.random() - 0.5).slice(0, SUGGESTION_COUNT)
}

function refreshSuggestions() {
  suggestions.value = buildRandomSuggestions()
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
    if (err instanceof Error && err.name === 'AuthRequiredError') {
      errorMessage.value = err.message
      setMessageContent(assistantMessageId, err.message)
      isSending.value = false
      streamStatus.value = ''
      return
    }
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

function createNewSession() {
  summarizeCurrentSession(orderInfo.value, canSubmit.value)
  setSessionId(createSessionId())
  inputText.value = ''; errorMessage.value = ''; isListening.value = false; isSending.value = false
  resetMessages(); resetOrder(); refreshSuggestions(); showHistory.value = false
  nextTick(() => chatBodyRef.value?.scrollTo({ top: 0 }))
}

async function cancelOrder() {
  if (!canCancelOrder.value) return
  await requestCancelOrder()
}

function statusStyle(status: string) {
  return {
    '待确认': 'bg-amber-100 text-amber-700',
    '已派单': 'bg-blue-100 text-blue-700',
    '已完成': 'bg-emerald-100 text-emerald-700',
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
                    <OrderSuccessCard
                      v-if="message.variant === 'order_success'"
                      :order-id="message.orderSuccess?.orderId"
                      :service-type="message.orderSuccess?.serviceType"
                      :selected-product="message.orderSuccess?.selectedProduct"
                      :fields="message.orderSuccess?.fields"
                      :submitted-order="message.orderSuccess?.submittedOrder"
                    />
                    <div v-else-if="message.content" class="prose prose-sm" v-html="renderMarkdown(message.content)"></div>
                    <p v-else class="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1.5 text-[12px] text-indigo-600">
                      <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500"></span>
                      {{ streamStatus || '正在处理您的请求...' }}
                    </p>
                    <ToolCallList
                      v-if="message.toolCalls?.length"
                      class="mt-3"
                      :items="message.toolCalls"
                    />
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
                    <OrderStatusNotices
                      v-if="isSubmittingOrder || hasSubmissionFailure"
                      class="mb-3"
                      :is-submitting-order="isSubmittingOrder"
                      :has-submission-failure="hasSubmissionFailure"
                      :submission-missing-text="submissionMissingText"
                      :submission-failure-message="submissionFailureMessage"
                    />

                    <ProductSelectionCard
                      v-if="isProductSelectionPhase && hasProductOptions && !productSelectionRejected"
                      :items="productItems"
                      :feedback="productFeedback"
                      :selected-code="selectedProductCode"
                      :selecting-code="selectingProductCode"
                      :is-awaiting-selection="isAwaitingProductSelection"
                      :is-selecting="isSelectingProduct"
                      :is-submitted="isOrderSubmitted"
                      :can-select="canSelectProduct"
                      :can-reject="canRejectProducts"
                      @select="selectProduct"
                      @reject="rejectProducts"
                    />

                    <OrderPreviewCard
                      v-if="showDraftOrderCard && !isOrderSubmitted"
                      :fields="orderFields"
                      :filled-count="filledCount"
                      :total-field-count="totalFieldCount"
                      :order-completeness="orderCompleteness"
                      :effective-service-type-display="effectiveServiceTypeDisplay"
                      :selected-product="selectedProduct"
                      :product-feedback="productFeedback"
                      :coverage-notice="coverageNotice"
                      :missing-info-text="missingInfoText"
                      :is-updating-order-info="isUpdatingOrderInfo"
                      :updating-field-key="updatingFieldKey"
                      :can-confirm-order="canConfirmOrder"
                      :can-cancel-order="canCancelOrder"
                      :submission-failure-message="submissionFailureMessage"
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
          :product-feedback="productFeedback"
          :coverage-notice="coverageNotice"
          :missing-info-text="missingInfoText"
          :is-submitting-order="isSubmittingOrder"
          :has-submission-failure="hasSubmissionFailure"
          :submission-missing-text="submissionMissingText"
          :submission-failure-message="submissionFailureMessage"
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
