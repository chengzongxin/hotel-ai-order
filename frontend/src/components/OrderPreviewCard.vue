<script setup lang="ts">
import { computed } from 'vue'
import OrderStatusNotices from './OrderStatusNotices.vue'
import type { CoverageNotice, OrderItem, ProductOption, UiOrderField } from '../types/order'

const props = withDefaults(defineProps<{
  variant?: 'chat' | 'sidebar'
  fields: UiOrderField[]
  filledCount: number
  totalFieldCount: number
  orderCompleteness: number
  effectiveServiceTypeDisplay?: string | null
  selectedProduct?: ProductOption | null
  productFeedback?: string | null
  coverageNotice?: CoverageNotice | null
  missingInfoText?: string
  isSubmittingOrder?: boolean
  hasSubmissionFailure?: boolean
  submissionMissingText?: string
  submissionFailureMessage?: string
  isUpdatingOrderInfo?: boolean
  updatingFieldKey?: string | null
  canConfirmOrder?: boolean
  canCancelOrder?: boolean
  orderItems?: OrderItem[]
  canAddOrderItem?: boolean
  canUpdateOrderItem?: boolean
  canRemoveOrderItem?: boolean
}>(), {
  variant: 'chat',
  orderItems: () => [],
})

const emit = defineEmits<{
  updateField: [key: string, value: string]
  confirm: []
  cancel: []
  addItem: []
  updateItem: [itemId: string, updates: { quantity?: number; fault?: string }]
  removeItem: [itemId: string]
}>()

const progressR = 35
const progressCircumference = 2 * Math.PI * progressR
const progressOffset = computed(() => progressCircumference * (1 - props.orderCompleteness / 100))

function displayValue(field: UiOrderField): string {
  if (field.value === null || field.value === undefined || field.value === '') return '待补充'
  return field.value
}

function updateQuantity(item: OrderItem, event: Event) {
  const value = Math.max(1, Number.parseInt((event.target as HTMLInputElement).value, 10) || 1)
  emit('updateItem', item.id, { quantity: value })
}
</script>

<template>
  <div :class="variant === 'sidebar' ? 'flex flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm' : 'space-y-3'">
    <div
      v-if="variant === 'sidebar'"
      class="flex items-center gap-4 border-b border-slate-100 px-5 py-4"
    >
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
        <p class="mt-1 text-xs text-slate-500">必填项 <span class="font-semibold text-slate-700">{{ filledCount }}</span> / {{ totalFieldCount }} 已完成</p>
        <p v-if="effectiveServiceTypeDisplay" class="mt-1 truncate text-xs text-slate-500">
          服务类型：<span class="font-semibold text-indigo-600">{{ effectiveServiceTypeDisplay }}</span>
        </p>
      </div>
    </div>

    <div v-else class="rounded-xl border border-slate-200 bg-slate-50/60 px-3.5 py-3">
      <p class="text-[13px] font-semibold text-slate-800">预下单卡片</p>
      <p v-if="missingInfoText" class="mt-1 text-[11px] text-amber-700">
        还需补充必填信息：{{ missingInfoText }}。
      </p>
      <p v-else-if="canConfirmOrder" class="mt-1 text-[11px] text-emerald-700">
        必填信息已完整，可以确认下单；其他未填写项为可选信息。
      </p>
      <p v-else class="mt-1 text-[11px] text-slate-500">
        必填项已完成 {{ filledCount }} / {{ totalFieldCount }}，请检查订单信息。
      </p>
      <p v-if="effectiveServiceTypeDisplay" class="mt-1 text-[11px] text-slate-600">
        服务类型：<span class="font-semibold text-indigo-600">{{ effectiveServiceTypeDisplay }}</span>
      </p>
      <p v-if="selectedProduct?.name" class="mt-1 text-[11px] text-indigo-600">
        商品：{{ selectedProduct.name }}
      </p>
    </div>

    <div :class="variant === 'sidebar' ? 'flex-1 overflow-y-auto p-3.5 space-y-2' : 'space-y-3'">
      <OrderStatusNotices
        :product-feedback="productFeedback"
        :coverage-notice="coverageNotice"
        :missing-info-text="missingInfoText"
        :is-submitting-order="isSubmittingOrder"
        :has-submission-failure="hasSubmissionFailure"
        :submission-missing-text="submissionMissingText"
        :submission-failure-message="submissionFailureMessage"
      />

      <section v-if="orderItems.length" class="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3.5">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div>
            <p class="text-[10px] font-semibold uppercase tracking-wide text-indigo-400">商品明细</p>
            <p class="mt-0.5 text-xs text-slate-500">共 {{ orderItems.length }} 种商品</p>
          </div>
          <button v-if="canAddOrderItem" type="button" class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700" @click="emit('addItem')">+ 新增商品</button>
        </div>
        <div class="space-y-2">
          <div v-for="item in orderItems" :key="item.id" class="rounded-xl border border-white bg-white px-3 py-2.5 shadow-sm">
            <div class="flex items-start gap-3">
              <div class="min-w-0 flex-1">
                <p class="truncate text-[13px] font-semibold text-slate-800">{{ item.name }}</p>
                <p class="mt-0.5 truncate text-[11px] text-slate-400">{{ item.code }}<span v-if="item.price"> · ¥{{ item.price }}/{{ item.unit || '件' }}</span></p>
              </div>
              <label class="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                数量
                <input type="number" min="1" step="1" class="w-16 rounded-lg border border-slate-200 px-2 py-1.5 text-center text-xs outline-none focus:border-indigo-300" :value="item.quantity" :disabled="!canUpdateOrderItem" @change="updateQuantity(item, $event)" />
              </label>
              <button v-if="canRemoveOrderItem && item.can_remove !== false" type="button" class="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50" @click="emit('removeItem', item.id)">删除</button>
            </div>
            <div class="mt-2 grid gap-2">
              <label class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                故障/服务说明
                <input class="mt-1 w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-normal normal-case text-slate-700 outline-none focus:border-indigo-300" :value="item.fault || ''" :disabled="!canUpdateOrderItem" @change="emit('updateItem', item.id, { fault: ($event.target as HTMLInputElement).value })" />
              </label>
            </div>
            <p v-if="item.errors?.length" class="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-700">
              该商品仍需补充：{{ item.errors.join('、') }}
            </p>
          </div>
        </div>
      </section>

      <div
        v-for="field in fields"
        :key="field.key"
        class="rounded-xl border px-3.5 py-3 transition"
        :class="[
          field.value ? 'border-emerald-100 bg-emerald-50/50' : 'border-slate-100 bg-white',
          variant === 'sidebar' ? 'group flex items-center gap-3 transition-all duration-300' : '',
        ]"
      >
        <span v-if="variant === 'sidebar'" class="shrink-0 text-[15px] leading-none">{{ field.icon }}</span>
        <label class="block min-w-0 flex-1">
          <span class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {{ field.label }}<span v-if="field.required" class="ml-0.5 text-red-400">*</span>
          </span>
          <select
            v-if="field.editable && field.inputType === 'select'"
            class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-800 outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
            :value="field.value || ''"
            :disabled="isUpdatingOrderInfo"
            @change="emit('updateField', field.key, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">请选择</option>
            <option v-for="option in field.options" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <textarea
            v-else-if="field.editable && field.inputType === 'textarea'"
            class="mt-1 w-full resize-none rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-800 outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
            rows="2"
            :value="field.value || ''"
            :disabled="isUpdatingOrderInfo"
            @change="emit('updateField', field.key, ($event.target as HTMLTextAreaElement).value)"
          ></textarea>
          <input
            v-else-if="field.editable && field.inputType === 'number'"
            class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-800 outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            :value="field.value || ''"
            :disabled="isUpdatingOrderInfo"
            @change="emit('updateField', field.key, ($event.target as HTMLInputElement).value)"
          />
          <input
            v-else-if="field.editable"
            class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-800 outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
            type="text"
            :value="field.value || ''"
            :disabled="isUpdatingOrderInfo"
            @change="emit('updateField', field.key, ($event.target as HTMLInputElement).value)"
          />
          <span v-else class="mt-1 block truncate text-[13px] font-medium text-slate-800">
            {{ displayValue(field) }}
          </span>
          <p v-if="field.hint" class="mt-1 text-[11px] leading-4 text-slate-500">
            {{ field.hint }}
          </p>
        </label>
        <p v-if="updatingFieldKey === field.key" class="mt-1 text-[10px] text-indigo-500">正在保存...</p>
      </div>

      <div
        v-if="variant === 'sidebar' && !orderItems.length"
        class="flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-all duration-300"
        :class="selectedProduct?.code ? 'border-indigo-100 bg-indigo-50/60' : 'border-slate-100 bg-slate-50/60'"
      >
        <span class="shrink-0 text-[15px] leading-none">📦</span>
        <div class="min-w-0 flex-1">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">当前选中商品</p>
          <p class="mt-0.5 truncate text-[13px] font-medium" :class="selectedProduct?.name ? 'text-slate-800' : 'text-slate-300'">
            {{ selectedProduct?.name || '待匹配' }}
          </p>
          <p v-if="selectedProduct?.code" class="mt-0.5 truncate text-[11px] text-slate-400">{{ selectedProduct.code }}</p>
        </div>
      </div>

      <div v-if="variant === 'sidebar'" class="mt-1 rounded-xl border border-indigo-100 bg-indigo-50/60 px-3.5 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-indigo-400">示例语句</p>
        <ul class="mt-1.5 space-y-1 text-[12px] leading-5 text-indigo-700/70">
          <li>"1208 房卫生间水龙头漏水，比较急。"</li>
          <li>"大堂空调噪音很大，麻烦来看一下。"</li>
          <li>"帮我安装洗衣机，明天上午，货已经到了。"</li>
        </ul>
      </div>
    </div>

    <div
      class="flex flex-col gap-2 sm:flex-row"
      :class="variant === 'sidebar' ? 'space-y-0 border-t border-slate-100 p-3.5 sm:flex-col' : 'mt-1'"
    >
      <button
        type="button"
        class="flex-1 rounded-xl bg-indigo-600 py-2.5 text-[13px] font-semibold text-white shadow-sm shadow-indigo-600/20 transition hover:bg-indigo-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!canConfirmOrder"
        @click="emit('confirm')"
      >确认下单</button>
      <button
        type="button"
        class="flex-1 rounded-xl border border-slate-200 bg-white py-2.5 text-[13px] font-medium text-slate-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!canCancelOrder"
        @click="emit('cancel')"
      >取消订单</button>
    </div>
  </div>
</template>
