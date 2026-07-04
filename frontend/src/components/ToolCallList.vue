<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ToolCallRecord } from '../types/order'

const props = defineProps<{
  items: ToolCallRecord[]
}>()

const expandedIds = ref<string[]>([])

const visibleItems = computed(() => props.items.filter((item) => item.call_id && item.name))

function isExpanded(id: string) {
  return expandedIds.value.includes(id)
}

function toggle(id: string) {
  expandedIds.value = isExpanded(id)
    ? expandedIds.value.filter((item) => item !== id)
    : [...expandedIds.value, id]
}

function titleFor(item: ToolCallRecord) {
  return item.display_name || item.name
}

function kindFor(item: ToolCallRecord) {
  return item.kind === 'interface' ? '接口' : '工具'
}

function statusFor(item: ToolCallRecord) {
  if (item.phase === 'start' || item.status === 'running') return '调用中'
  if (item.status === 'success') return '成功'
  if (item.status === 'fallback') return '兜底'
  if (item.status === 'error' || item.phase === 'error') return '失败'
  return item.status || '完成'
}

function statusClass(item: ToolCallRecord) {
  if (item.phase === 'start' || item.status === 'running') return 'border-sky-200 bg-sky-50 text-sky-700'
  if (item.status === 'success') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (item.status === 'fallback') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (item.status === 'error' || item.phase === 'error') return 'border-rose-200 bg-rose-50 text-rose-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function dotClass(item: ToolCallRecord) {
  if (item.phase === 'start' || item.status === 'running') return 'bg-sky-500 animate-pulse'
  if (item.status === 'success') return 'bg-emerald-500'
  if (item.status === 'fallback') return 'bg-amber-500'
  if (item.status === 'error' || item.phase === 'error') return 'bg-rose-500'
  return 'bg-slate-400'
}

function formatDuration(item: ToolCallRecord) {
  if (typeof item.duration_ms !== 'number') return ''
  if (item.duration_ms >= 1000) return `${(item.duration_ms / 1000).toFixed(2)}s`
  return `${Math.round(item.duration_ms)}ms`
}

function hasPayload(value: unknown) {
  return value !== undefined && value !== null && value !== ''
}

function formatPayload(value: unknown) {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<template>
  <div v-if="visibleItems.length" class="space-y-2">
    <div
      v-for="item in visibleItems"
      :key="item.call_id"
      class="overflow-hidden rounded-lg border border-slate-200 bg-white"
    >
      <button
        class="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-slate-50"
        type="button"
        @click="toggle(item.call_id)"
      >
        <svg
          class="h-3.5 w-3.5 shrink-0 text-slate-400 transition"
          :class="isExpanded(item.call_id) ? 'rotate-90' : ''"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="2"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span class="h-2 w-2 shrink-0 rounded-full" :class="dotClass(item)"></span>
        <span class="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
          {{ kindFor(item) }}
        </span>
        <span class="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-700">
          {{ titleFor(item) }}
        </span>
        <span
          class="shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium"
          :class="statusClass(item)"
        >
          {{ statusFor(item) }}
        </span>
        <span v-if="formatDuration(item)" class="shrink-0 text-[11px] text-slate-400">
          {{ formatDuration(item) }}
        </span>
      </button>

      <div v-if="isExpanded(item.call_id)" class="border-t border-slate-100 bg-slate-50/70 px-3 py-3">
        <div class="grid gap-3">
          <div v-if="item.step || item.name" class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span v-if="item.step">节点：{{ item.step }}</span>
            <span>标识：{{ item.name }}</span>
          </div>
          <p v-if="item.summary" class="text-[12px] leading-5 text-slate-600">
            {{ item.summary }}
          </p>

          <div v-if="item.error" class="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-[12px] leading-5 text-rose-700">
            {{ item.error }}
          </div>

          <div v-if="hasPayload(item.params)">
            <p class="mb-1 text-[11px] font-semibold text-slate-500">调用参数</p>
            <pre class="max-h-64 overflow-auto rounded-md bg-slate-900 px-3 py-2 text-[11px] leading-5 text-slate-100">{{ formatPayload(item.params) }}</pre>
          </div>

          <div v-if="hasPayload(item.result)">
            <p class="mb-1 text-[11px] font-semibold text-slate-500">调用结果</p>
            <pre class="max-h-64 overflow-auto rounded-md bg-slate-900 px-3 py-2 text-[11px] leading-5 text-slate-100">{{ formatPayload(item.result) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
