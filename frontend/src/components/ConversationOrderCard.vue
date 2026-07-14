<script setup lang="ts">
import { computed, toRef } from 'vue'
import type { OrderPreview, ProductOption } from '../types/order'
import { useOrderPreview } from '../composables/useOrderPreview'
import OrderPreviewCard from './OrderPreviewCard.vue'
import OrderStatusNotices from './OrderStatusNotices.vue'
import OrderSuccessCard from './OrderSuccessCard.vue'
import ProductSelectionCard from './ProductSelectionCard.vue'

const props = defineProps<{
  preview: OrderPreview
  active: boolean
  isSending: boolean
  isSelectingProduct: boolean
  selectingProductCode: string | null
  isUpdatingOrderInfo: boolean
  updatingFieldKey: string | null
}>()

const emit = defineEmits<{
  select: [item: ProductOption]
  reject: []
  updateField: [key: string, value: string | null]
  confirm: []
  cancel: []
}>()

const context = useOrderPreview(
  toRef(props, 'preview'),
  toRef(props, 'isSending'),
  toRef(props, 'isUpdatingOrderInfo'),
)

const fields = computed(() => context.orderFields.value.map((field) => ({
  ...field,
  editable: props.active && field.editable,
})))
const canSelect = computed(() => props.active && context.canSelectProduct.value)
const canReject = computed(() => props.active && context.canRejectProducts.value)
const canConfirm = computed(() => props.active && context.canConfirmOrder.value)
const canCancel = computed(() => props.active && context.canCancelOrder.value)
const showFailureOnly = computed(
  () => !context.showDraftOrderCard.value && context.hasSubmissionFailure.value,
)

function handleUpdateField(key: string, value: string) {
  emit('updateField', key, value)
}
</script>

<template>
  <OrderSuccessCard
    v-if="context.isOrderSubmitted.value"
    class="mt-3"
    :order-id="context.submittedOrderId.value"
    :service-type="context.effectiveServiceTypeDisplay.value"
    :selected-product="context.selectedProduct.value"
    :fields="fields"
    :submitted-order="context.submittedOrder.value"
  />

  <div
    v-else-if="context.isProductSelectionPhase.value && context.hasProductOptions.value && !context.productSelectionRejected.value"
    class="mt-3 overflow-hidden rounded-2xl border border-indigo-100 bg-white px-4 py-4 shadow-sm shadow-indigo-100/60"
  >
    <ProductSelectionCard
      :items="context.productItems.value"
      :feedback="context.productFeedback.value"
      :selected-code="context.selectedProductCode.value"
      :selecting-code="active ? selectingProductCode : null"
      :is-awaiting-selection="active && context.isAwaitingProductSelection.value"
      :is-selecting="active && isSelectingProduct"
      :is-submitted="!active"
      :can-select="canSelect"
      :can-reject="canReject"
      @select="emit('select', $event)"
      @reject="emit('reject')"
    />
  </div>

  <div
    v-else-if="context.showDraftOrderCard.value"
    class="mt-3 overflow-hidden rounded-2xl border border-indigo-100 bg-white px-4 py-4 shadow-sm shadow-indigo-100/60"
  >
    <OrderPreviewCard
      :fields="fields"
      :filled-count="context.filledCount.value"
      :total-field-count="context.totalFieldCount.value"
      :order-completeness="context.orderCompleteness.value"
      :effective-service-type-display="context.effectiveServiceTypeDisplay.value"
      :selected-product="context.selectedProduct.value"
      :product-feedback="context.productFeedback.value"
      :coverage-notice="context.coverageNotice.value"
      :missing-info-text="context.missingInfoText.value"
      :is-updating-order-info="active && isUpdatingOrderInfo"
      :updating-field-key="active ? updatingFieldKey : null"
      :can-confirm-order="canConfirm"
      :can-cancel-order="canCancel"
      :submission-failure-message="context.submissionFailureMessage.value"
      @update-field="handleUpdateField"
      @confirm="emit('confirm')"
      @cancel="emit('cancel')"
    />
  </div>

  <div v-else-if="showFailureOnly" class="mt-3">
    <OrderStatusNotices
      :is-submitting-order="context.isSubmittingOrder.value"
      :has-submission-failure="context.hasSubmissionFailure.value"
      :submission-missing-text="context.submissionMissingText.value"
      :submission-failure-message="context.submissionFailureMessage.value"
    />
  </div>
</template>
