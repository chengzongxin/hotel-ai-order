<script setup lang="ts">
import type { ProductOption } from '../types/order'

const props = defineProps<{
  items: ProductOption[]
  feedback?: string | null
  selectingCode?: string | null
  isAwaitingSelection?: boolean
  isSelecting?: boolean
  isSubmitted?: boolean
  canSelect?: boolean
  canReject?: boolean
}>()

const emit = defineEmits<{
  select: [item: ProductOption]
  reject: []
}>()

</script>

<template>
  <div class="space-y-2">
    <div v-if="isAwaitingSelection" class="mb-2">
      <p class="text-[13px] font-semibold text-slate-800">请选择要下单的服务商品</p>
      <p class="mt-1 text-[11px] text-slate-400">点击商品卡片即可选择。</p>
      <p v-if="feedback" class="mt-2 rounded-lg bg-indigo-50 px-3 py-2 text-[12px] leading-5 text-indigo-700">
        {{ feedback }}
      </p>
    </div>

    <div class="space-y-2">
      <div
        v-for="item in items"
        :key="`chat-${item.code}`"
        class="relative w-full rounded border p-3 text-left transition-all duration-200"
        :class="[
          'border-slate-200 bg-white',
          canSelect && !isSelecting ? 'cursor-pointer hover:border-indigo-200 hover:shadow-sm' : '',
          isSubmitted ? 'opacity-95' : '',
        ]"
        :role="canSelect ? 'button' : undefined"
        @click="canSelect && !isSelecting && emit('select', item)"
      >
        <div class="flex items-start justify-between gap-2">
          <p class="line-clamp-2 text-[13px] font-semibold leading-5 text-slate-800">{{ item.name }}</p>
          <span
            v-if="item.service_type"
            class="shrink-0 rounded bg-amber-400 px-2 py-0.5 text-[10px] font-semibold text-white"
          >{{ item.service_type }}</span>
        </div>
        <p class="mt-1 line-clamp-1 text-[12px] leading-5 text-slate-500">
          {{ item.fault_phenomenon || item.repair_category || item.code }}
        </p>

        <div class="mt-2">
          <span
            v-if="!isSubmitted && selectingCode === item.code"
            class="inline-flex items-center gap-1.5 text-[11px] text-indigo-600"
          >
            <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>
            选择中…
          </span>
          <span v-else-if="!isSubmitted" class="text-[11px] font-medium text-indigo-500">点击选择</span>
        </div>
      </div>

      <button
        v-if="isAwaitingSelection"
        type="button"
        class="w-full rounded border border-indigo-300 bg-white px-3 py-2.5 text-center text-[12px] font-medium text-indigo-600 transition hover:border-indigo-400 hover:bg-indigo-50"
        :disabled="!canReject"
        @click="emit('reject')"
      >
        以上都不符合
      </button>
    </div>
  </div>
</template>
