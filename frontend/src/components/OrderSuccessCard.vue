<script setup lang="ts">
import { computed } from 'vue'
import type { ProductOption, UiOrderField } from '../types/order'

const props = defineProps<{
  orderId?: string | null
  serviceType?: string | null
  selectedProduct?: ProductOption | null
  fields?: UiOrderField[]
  submittedOrder?: {
    order_no?: string | null
    service_type?: string | null
    effective_service_type?: string | null
    product_name?: string | null
    room_number?: string | null
    area?: string | null
    expected_start_time?: string | null
    contacts?: string | null
    phone?: string | null
  } | null
}>()

function valueOf(keys: string[]): string | null {
  const field = props.fields?.find((item) => keys.includes(item.key))
  return field?.value?.trim() || null
}

const orderNoText = computed(() => props.submittedOrder?.order_no || props.orderId || '系统已生成')
const serviceTypeText = computed(() => props.submittedOrder?.effective_service_type || props.submittedOrder?.service_type || props.serviceType || '已识别')
const productNameText = computed(() => props.submittedOrder?.product_name || props.selectedProduct?.name || '已匹配')
const roomText = computed(() => props.submittedOrder?.room_number || props.submittedOrder?.area || valueOf(['area_room', 'room_number', 'roomNumber']) || '已记录')
const contactText = computed(() => props.submittedOrder?.contacts || valueOf(['contacts']) || '已记录')
const phoneText = computed(() => props.submittedOrder?.phone || valueOf(['phone']) || '已记录')
const expectedTimeText = computed(() => props.submittedOrder?.expected_start_time || valueOf(['expected_time', 'expectedStartTime']) || '待服务人员确认')
</script>

<template>
  <section class="relative overflow-hidden rounded-3xl border border-emerald-200 bg-gradient-to-br from-emerald-50 via-white to-cyan-50 p-5 shadow-[0_18px_45px_rgba(16,185,129,0.16)]">
    <div class="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-emerald-300/25 blur-2xl"></div>
    <div class="pointer-events-none absolute -bottom-12 left-8 h-28 w-28 rounded-full bg-cyan-300/20 blur-2xl"></div>

    <div class="relative flex items-start gap-4">
      <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-500 text-white shadow-lg shadow-emerald-500/25">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div class="min-w-0 flex-1">
        <p class="text-[11px] font-bold uppercase tracking-[0.22em] text-emerald-600">Order Submitted</p>
        <h3 class="mt-1 text-xl font-black tracking-tight text-slate-900">下单成功</h3>
        <p class="mt-1 text-[13px] leading-6 text-slate-600">
          订单已经提交到系统，服务人员会根据订单信息跟进处理。
        </p>
      </div>
    </div>

    <div class="relative mt-5 rounded-2xl border border-white/70 bg-white/80 p-4 shadow-sm backdrop-blur">
      <div class="flex items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <span class="text-[11px] font-semibold text-slate-400">订单编号</span>
        <span class="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-bold text-emerald-700">已提交</span>
      </div>
      <p class="mt-3 break-all font-mono text-[15px] font-bold text-slate-800">
        {{ orderNoText }}
      </p>
    </div>

    <div class="relative mt-4 grid grid-cols-2 gap-3">
      <div class="rounded-2xl border border-white/70 bg-white/70 px-3.5 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">服务类型</p>
        <p class="mt-1 truncate text-[13px] font-semibold text-slate-800">{{ serviceTypeText }}</p>
      </div>
      <div class="rounded-2xl border border-white/70 bg-white/70 px-3.5 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">商品</p>
        <p class="mt-1 truncate text-[13px] font-semibold text-slate-800">{{ productNameText }}</p>
      </div>
      <div class="rounded-2xl border border-white/70 bg-white/70 px-3.5 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">位置</p>
        <p class="mt-1 truncate text-[13px] font-semibold text-slate-800">{{ roomText }}</p>
      </div>
      <div class="rounded-2xl border border-white/70 bg-white/70 px-3.5 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">期望时间</p>
        <p class="mt-1 truncate text-[13px] font-semibold text-slate-800">{{ expectedTimeText }}</p>
      </div>
    </div>

    <div class="relative mt-4 flex flex-wrap gap-2 text-[12px] text-slate-600">
      <span class="rounded-full border border-emerald-100 bg-white/70 px-3 py-1.5">联系人：{{ contactText }}</span>
      <span class="rounded-full border border-emerald-100 bg-white/70 px-3 py-1.5">电话：{{ phoneText }}</span>
    </div>
  </section>
</template>
