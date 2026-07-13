export type Role = 'user' | 'assistant'

export type ToolCallPhase = 'start' | 'end' | 'error'

export type ToolCallStatus = 'running' | 'success' | 'error' | 'fallback' | string

export interface ToolCallRecord {
  call_id: string
  phase?: ToolCallPhase | string
  kind?: 'tool' | 'interface' | string
  name: string
  display_name?: string
  step?: string
  status?: ToolCallStatus
  params?: unknown
  result?: unknown
  error?: string | null
  duration_ms?: number | null
  summary?: string | null
}

export interface ChatMessage {
  id: number
  role: Role
  content: string
  time: string
  variant?: 'order_success'
  toolCalls?: ToolCallRecord[]
  orderSuccess?: {
    orderId?: string | null
    serviceType?: string | null
    selectedProduct?: ProductOption | null
    fields?: UiOrderField[]
    submittedOrder?: SubmittedOrder | null
  }
}

export type UrgencyLevel = 'low' | 'medium' | 'high' | 'urgent'

export type OrderPhase =
  | 'idle'
  | 'collecting'
  | 'product_selection'
  | 'pre_order'
  | 'submitted'
  | 'cancelled'

export type SubmissionState =
  | 'not_attempted'
  | 'submitting'
  | 'succeeded'
  | 'failed'
  | 'disabled'

export interface ProductOption {
  code?: string
  name?: string
  service_type?: string
  price?: string | null
  repair_category?: string | null
  fault_phenomenon?: string | null
  score?: number | null
  rank?: number
  is_recommended?: boolean
  is_selected?: boolean
}

export interface ProductSection {
  status?: string | null
  query?: string | null
  feedback?: string | null
  selected_code?: string | null
  selection_rejected?: boolean
  items?: ProductOption[]
}

export interface OrderCardField {
  key: string
  label: string
  value?: unknown
  required?: boolean
  source?: string
  editable?: boolean
  input_type?: 'text' | 'textarea' | 'select' | 'datetime' | 'number'
  options?: Array<{ label: string; value: string }>
  hint?: string | null
}

export interface OrderForm {
  fields?: OrderCardField[]
}

export interface WorkflowValidation {
  ready?: boolean
  missing_fields?: string[]
}

export interface WorkflowCapabilities {
  select_product?: boolean
  reject_products?: boolean
  update_order?: boolean
  confirm_order?: boolean
  cancel_order?: boolean
  retry_submission?: boolean
}

export interface CoverageSection {
  checked?: boolean
  covered?: boolean | null
  reason?: string | null
  effective_service_type?: string | null
  hosting_card_name?: string | null
}

export interface CoverageNotice {
  tone: 'warning' | 'ok'
  title: string
  message: string
}

export interface UiOrderField {
  key: string
  icon: string
  label: string
  value: string | null
  required: boolean
  editable: boolean
  inputType: 'text' | 'textarea' | 'select' | 'datetime' | 'number'
  options: Array<{ label: string; value: string }>
  hint?: string | null
}

export interface SubmittedOrder {
  order_no?: string | null
  service_type?: string | null
  effective_service_type?: string | null
  product_code?: string | null
  product_name?: string | null
  room_number?: string | null
  product?: string | null
  fault?: string | null
  area?: string | null
  second_area?: string | null
  urgency?: UrgencyLevel | string | null
  expected_start_time?: string | null
  goods_arrival_status?: string | null
  product_quantity?: number | null
  contacts?: string | null
  phone?: string | null
}

export interface OrderPreview {
  schema_version?: number
  phase?: OrderPhase | string | null
  service_type?: string | null
  service_type_display?: string | null
  effective_service_type?: string | null
  effective_service_type_display?: string | null
  order_info?: {
    room_number?: string | null
    product?: string | null
    fault?: string | null
    area?: string | null
    second_area?: string | null
    urgency?: UrgencyLevel | null
    expected_start_time?: string | null
    goods_arrival_status?: string | null
    product_quantity?: number | null
  }
  products?: ProductSection
  form?: OrderForm
  validation?: WorkflowValidation
  capabilities?: WorkflowCapabilities
  coverage?: CoverageSection
  submission?: {
    state?: SubmissionState | string
    order_no?: string | null
    failure_code?: string | null
    failure_message?: string | null
    missing_fields?: string[]
  }
  submitted_order?: SubmittedOrder | null
}

export interface StreamEvent {
  type: 'status' | 'preview' | 'token' | 'final' | 'error' | 'tool_call'
  session_id?: string
  step?: string
  message?: string
  content?: string
  answer?: string
  order_preview?: OrderPreview | null
  phase?: ToolCallPhase | string
  call_id?: string
  kind?: 'tool' | 'interface' | string
  name?: string
  display_name?: string
  status?: ToolCallStatus
  params?: unknown
  result?: unknown
  error?: string | null
  duration_ms?: number | null
  summary?: string | null
}

export interface SessionSummary {
  id: string
  title: string
  status: string
  time: string
}
