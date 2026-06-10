<script setup lang="ts">
import type { CoverageNotice } from '../types/order'

defineProps<{
  coverageNotice?: CoverageNotice | null
  missingInfoText?: string
  isSubmittingOrder?: boolean
  hasSubmissionFailure?: boolean
  submissionMissingText?: string
}>()
</script>

<template>
  <div
    v-if="coverageNotice"
    class="rounded-xl border px-3.5 py-3"
    :class="coverageNotice.tone === 'warning' ? 'border-amber-100 bg-amber-50' : 'border-emerald-100 bg-emerald-50'"
  >
    <p
      class="text-[12px] font-semibold"
      :class="coverageNotice.tone === 'warning' ? 'text-amber-800' : 'text-emerald-800'"
    >
      {{ coverageNotice.title }}
    </p>
    <p
      class="mt-1 text-[12px] leading-5"
      :class="coverageNotice.tone === 'warning' ? 'text-amber-700/90' : 'text-emerald-700/90'"
    >
      {{ coverageNotice.message }}
    </p>
  </div>

  <div
    v-if="missingInfoText"
    class="rounded-xl border border-red-100 bg-red-50 px-3.5 py-3"
  >
    <p class="text-[12px] font-semibold text-red-700">还缺少必要信息</p>
    <p class="mt-1 text-[12px] leading-5 text-red-600">
      {{ missingInfoText }}
    </p>
  </div>

  <div
    v-if="isSubmittingOrder || hasSubmissionFailure"
    class="rounded-xl border px-3.5 py-3"
    :class="hasSubmissionFailure ? 'border-amber-100 bg-amber-50' : 'border-indigo-100 bg-indigo-50'"
  >
    <p
      class="text-[12px] font-semibold"
      :class="hasSubmissionFailure ? 'text-amber-800' : 'text-indigo-800'"
    >
      {{ hasSubmissionFailure ? '订单暂未提交成功' : '正在提交订单' }}
    </p>
    <p
      class="mt-1 text-[12px] leading-5"
      :class="hasSubmissionFailure ? 'text-amber-700/90' : 'text-indigo-700/80'"
    >
      {{
        hasSubmissionFailure
          ? (submissionMissingText ? `还需补齐：${submissionMissingText}` : '订单参数已生成，请确认接口返回后重试。')
          : '正在调用下单接口，请不要关闭页面。'
      }}
    </p>
  </div>
</template>
