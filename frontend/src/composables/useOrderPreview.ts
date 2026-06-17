import { computed, type ComputedRef, type Ref } from 'vue'
import type { CoverageNotice, OrderPreview, ProductOption, UiOrderField } from '../types/order'

const MISSING_INFO_LABELS: Record<string, string> = {
  selected_product: '服务商品',
  room_number: '房号',
  product: '商品/设备',
  fault: '故障现象',
  area: '区域',
  second_area: '二级区域',
  expected_start_time: '期待开工时间',
  goods_arrival_status: '货物到场状态',
  contacts: '联系人',
  phone: '联系电话',
  address: '地址',
}

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
    hint: null,
  }
}

export function iconForOrderField(key: string): string {
  const icons: Record<string, string> = {
    area_room: '📍',
    second_area: '⌖',
    urgency: '!',
    remark: '✎',
    contacts: '👤',
    phone: '☎',
    total_fee: '¥',
    expected_time: '🕒',
    goods_arrival_status: '🚚',
    product_quantity: '×',
  }
  return icons[key] || '•'
}

export function formatOrderFieldValue(value: unknown): string | null {
  if (value == null || value === '') return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

export function formatMatchScore(score?: number | null): string {
  if (score == null) return ''
  return `${Math.round(score * 100)}%`
}

export function isSubmittedPreview(preview?: OrderPreview | null): boolean {
  return preview?.phase === 'submitted' || preview?.submission?.state === 'succeeded'
}

export function useOrderPreview(
  orderPreview: Ref<OrderPreview | null>,
  isSending: Ref<boolean>,
  isUpdatingOrderInfo: Ref<boolean>,
) {
  const orderInfo = computed(() => orderPreview.value?.order_info ?? {})
  const phase = computed(() => orderPreview.value?.phase ?? null)
  const submission = computed(() => orderPreview.value?.submission ?? {})
  const submittedOrder = computed(() => orderPreview.value?.submitted_order ?? null)
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
  const backendOrderFields = computed(() => orderPreview.value?.order_card?.fields ?? [])
  const hasBackendOrderFields = computed(() => backendOrderFields.value.length > 0)
  const isProductSelectionPhase = computed(() => phase.value === 'product_selection')
  const isPreOrderPhase = computed(() => phase.value === 'pre_order')
  const hasProductOptions = computed(() => productItems.value.length > 0)

  const isProductSelected = (item: ProductOption): boolean => {
    const activeCode = selectedProductCode.value
    return Boolean(item.is_selected || (item.code && item.code === activeCode))
  }

  const selectedProduct = computed(
    () => productItems.value.find(isProductSelected) ?? null,
  )

  const isAwaitingProductSelection = computed(
    () => isProductSelectionPhase.value && hasProductOptions.value && !selectedProductCode.value && !productSelectionRejected.value,
  )
  const showDraftOrderCard = computed(
    () => isPreOrderPhase.value && Boolean(selectedProductCode.value) && hasBackendOrderFields.value,
  )
  const submittedOrderId = computed(() => submittedOrder.value?.order_no || submission.value.order_no || null)
  const submissionState = computed(() => submission.value.state ?? 'not_attempted')
  const isSubmittingOrder = computed(() => submissionState.value === 'submitting' || (isSending.value && isPreOrderPhase.value))
  const submissionMissingFields = computed(() => submission.value.missing_fields ?? [])
  const hasSubmissionFailure = computed(() => submissionState.value === 'failed' || submissionState.value === 'disabled')
  const submissionFailureMessage = computed(() => submission.value.failure_message || '')

  const canSubmit = computed(() =>
    isPreOrderPhase.value && missingInfo.value.length === 0 && submissionState.value !== 'succeeded',
  )

  const isOrderSubmitted = computed(() => phase.value === 'submitted' || submissionState.value === 'succeeded')

  const showChatOrderPanel = computed(() => {
    if (phase.value === 'submitted') return false
    if (phase.value === 'cancelled') return false
    if (!phase.value || phase.value === 'idle') return false
    if (productSelectionRejected.value) return false
    return (isProductSelectionPhase.value && productItems.value.length > 0) || showDraftOrderCard.value
  })

  const canConfirmOrder = computed(
    () => canSubmit.value && Boolean(selectedProductCode.value) && !isSending.value && !isUpdatingOrderInfo.value,
  )

  const canCancelOrder = computed(() => {
    return ['collecting', 'product_selection', 'pre_order'].includes(String(phase.value)) && !isSending.value
  })

  const missingInfoText = computed(() =>
    missingInfo.value.map((field) => MISSING_INFO_LABELS[field] || field).join('、'),
  )

  const submissionMissingText = computed(() =>
    submissionMissingFields.value.map((field) => MISSING_INFO_LABELS[field] || field).join('、'),
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
      low: { label: '低优先级', icon: '↓', color: 'text-emerald-700', bg: 'bg-emerald-50' },
      medium: { label: '普通', icon: '→', color: 'text-blue-700', bg: 'bg-blue-50' },
      high: { label: '较急', icon: '↑', color: 'text-amber-700', bg: 'bg-amber-50' },
      urgent: { label: '紧急', icon: '!', color: 'text-red-700', bg: 'bg-red-50' },
    }[orderInfo.value.urgency]
  })

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
        hint: field.hint ?? null,
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
      makeReadonlyField('secondArea', '⌖', '二级区域', orderInfo.value.second_area),
      makeReadonlyField('roomNumber', '🏠', '房间号', orderInfo.value.room_number),
    ]
  })

  const filledCount = computed(() => orderFields.value.filter((field) => Boolean(field.value)).length)
  const totalFieldCount = computed(() => Math.max(orderFields.value.length, 1))
  const orderCompleteness = computed(() => Math.round((filledCount.value / totalFieldCount.value) * 100))

  const progressR = 32
  const progressCircumference = computed(() => +(2 * Math.PI * progressR).toFixed(2))
  const progressOffset = computed(() =>
    +(progressCircumference.value - (orderCompleteness.value / 100) * progressCircumference.value).toFixed(2),
  )

  return {
    orderInfo,
    phase,
    submission,
    submittedOrder,
    serviceTypeDisplay,
    effectiveServiceTypeDisplay,
    missingInfo,
    coverage,
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
  }
}

export type OrderPreviewContext = ReturnType<typeof useOrderPreview>

export function displayOrderFieldValue(field: {
  value?: string | null
  options?: Array<{ label: string; value: string }>
}): string {
  const value = field.value ?? ''
  const option = field.options?.find((item) => item.value === value)
  return option?.label || value || '待识别'
}
