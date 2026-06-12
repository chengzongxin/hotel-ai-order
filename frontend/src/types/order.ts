export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: number
  role: Role
  content: string
  time: string
  variant?: 'order_success'
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
}

export interface OrderCardSection {
  card_type?: string | null
  title?: string | null
  fields?: OrderCardField[]
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
  urgency?: UrgencyLevel | string | null
  expected_start_time?: string | null
  goods_arrival_status?: string | null
  product_quantity?: number | null
  contacts?: string | null
  phone?: string | null
}

export interface OrderPreview {
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
    urgency?: UrgencyLevel | null
    expected_start_time?: string | null
    goods_arrival_status?: string | null
    product_quantity?: number | null
  }
  products?: ProductSection
  order_card?: OrderCardSection
  coverage?: CoverageSection
  missing_info?: string[]
  submission?: {
    attempted?: boolean
    state?: SubmissionState | string
    order_no?: string | null
    failure_code?: string | null
    failure_message?: string | null
    missing_fields?: string[]
    request_payload?: Record<string, unknown>
    response_payload?: Record<string, unknown>
  }
  submitted_order?: SubmittedOrder | null
}

export interface StreamEvent {
  type: 'session' | 'status' | 'preview' | 'token' | 'final' | 'error'
  session_id?: string
  step?: string
  message?: string
  content?: string
  answer?: string
  order_preview?: OrderPreview | null
}

export interface SessionSummary {
  id: string
  title: string
  status: string
  time: string
}
