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
  const orderInfo = computed(() => {
    const preview = orderPreview.value
    const item = preview?.order?.items?.[0]
    return {
      ...(preview?.product_request ?? {}),
      ...(preview?.order ?? {}),
      ...(item ? {
        product: item.name,
        fault: item.fault,
      } : {}),
    }
  })
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
  const actions = computed(() => orderPreview.value?.actions ?? [])
  const missingInfo = computed(() => orderPreview.value?.errors ?? [])
  const productItems = computed(() => orderPreview.value?.products ?? [])
  const productFeedback = computed(() => null)
  const productSelectionRejected = computed(() => false)
  const formFields = computed(() => orderPreview.value?.form?.fields ?? [])
  const orderItems = computed(() => orderPreview.value?.order?.items ?? [])
  const coverage = computed(() => orderItems.value[0]?.coverage ?? {})
  const isProductSelectionPhase = computed(() => phase.value === 'product_selection')
  const isPreOrderPhase = computed(() => phase.value === 'pre_order')
  const hasProductOptions = computed(() => productItems.value.length > 0)

  const selectedProduct = computed<ProductOption | null>(() => {
    const item = orderItems.value[0]
    return item ? { code: item.code, name: item.name, service_type: item.service_type ?? undefined, price: item.price } : null
  })

  const isAwaitingProductSelection = computed(
    () => isProductSelectionPhase.value && hasProductOptions.value && !productSelectionRejected.value,
  )
  const showDraftOrderCard = computed(
    () => isPreOrderPhase.value && formFields.value.length > 0,
  )
  const submittedOrderId = computed(() => submittedOrder.value?.order_no || submission.value.order_no || null)
  const submissionState = computed(() => submission.value.state ?? 'not_attempted')
  const isSubmittingOrder = computed(() => submissionState.value === 'submitting' || (isSending.value && isPreOrderPhase.value))
  const submissionMissingFields = computed(() => [] as string[])
  const hasSubmissionFailure = computed(() => submissionState.value === 'failed' || submissionState.value === 'disabled')
  const submissionFailureMessage = computed(() => submission.value.message || '')

  const canSubmit = computed(() => actions.value.includes('confirm_order'))
  const canSelectProduct = computed(
    () => actions.value.includes('select_product') && !isSending.value,
  )
  const canRejectProducts = computed(
    () => actions.value.includes('reject_products') && !isSending.value,
  )
  const canAddOrderItem = computed(() => actions.value.includes('add_item') && !isUpdatingOrderInfo.value)
  const canUpdateOrderItem = computed(() => actions.value.includes('update_item') && !isUpdatingOrderInfo.value)
  const canRemoveOrderItem = computed(() => actions.value.includes('remove_item') && !isUpdatingOrderInfo.value)

  const isOrderSubmitted = computed(() => phase.value === 'submitted' || submissionState.value === 'succeeded')

  const showChatOrderPanel = computed(() => {
    if (phase.value === 'submitted') return false
    if (phase.value === 'cancelled') return false
    if (!phase.value || phase.value === 'idle') return false
    if (productSelectionRejected.value) return false
    return (isProductSelectionPhase.value && productItems.value.length > 0) || showDraftOrderCard.value
  })

  const canConfirmOrder = computed(
    () => canSubmit.value && !isSending.value && !isUpdatingOrderInfo.value,
  )

  const canCancelOrder = computed(
    () => actions.value.includes('cancel_order') && !isSending.value,
  )

  const missingInfoText = computed(() =>
    missingInfo.value.map((field) => MISSING_INFO_LABELS[field] || field).join('、'),
  )

  const submissionMissingText = computed(() =>
    submissionMissingFields.value.map((field) => MISSING_INFO_LABELS[field] || field).join('、'),
  )

  const coverageNotice = computed<CoverageNotice | null>(() => {
    const data = coverage.value
    if (!data.checked || typeof data.reason !== 'string' || !data.reason) return null
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
    return formFields.value
      .filter((field) => !(orderItems.value.length && field.key === 'product_quantity'))
      .map((field) => ({
      key: field.key,
      icon: iconForOrderField(field.key),
      label: field.label,
      value: formatOrderFieldValue((() => {
        const common = orderPreview.value?.order ?? {}
        const item = orderItems.value[0] ?? {}
        if (field.key === 'area_room') return common.room_number || common.area
        if (field.key === 'second_area') return common.second_area_id || common.second_area
        if (field.key === 'expected_time') return common.expected_start_time
        if (field.key === 'product_quantity') return item.quantity
        return (common as Record<string, unknown>)[field.key] ?? (item as unknown as Record<string, unknown>)[field.key]
      })()),
      required: Boolean(field.required),
      editable: field.editable !== false && actions.value.includes('update_order'),
      inputType: field.input_type || 'text',
      options: field.options || [],
      hint: field.hint ?? null,
      }))
  })

  const requiredFields = computed(() => orderFields.value.filter((field) => field.required))
  const filledCount = computed(() => requiredFields.value.filter((field) => Boolean(field.value)).length)
  const totalFieldCount = computed(() => requiredFields.value.length)
  const orderCompleteness = computed(() => (
    totalFieldCount.value === 0 ? 100 : Math.round((filledCount.value / totalFieldCount.value) * 100)
  ))

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
    productSelectionRejected,
    selectedProduct,
    orderItems,
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
    canAddOrderItem,
    canUpdateOrderItem,
    canRemoveOrderItem,
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
