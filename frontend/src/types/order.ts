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
  id: string
  role: Role
  content: string
  time: string
  orderPreview?: OrderPreview | null
  toolCalls?: ToolCallRecord[]
}

export interface ConversationMessagePayload {
  id: string
  role: 'human' | 'ai'
  content: string
  order_preview: OrderPreview | null
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
}

export interface OrderCardField {
  key: string
  label: string
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

export interface OrderItem {
  id: string
  code: string
  name: string
  service_type?: string | null
  quantity: number
  unit?: string | null
  price?: string | null
  category?: string | null
  repair_category?: string | null
  related_category?: string | null
  related_area?: string | null
  fault_phenomenon?: string | null
  remark?: string | null
  fault?: string | null
  coverage?: Record<string, unknown>
  errors?: string[]
  can_edit?: boolean
  can_remove?: boolean
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
  items?: OrderItem[]
}

export interface OrderPreview {
  schema_version?: number
  phase?: OrderPhase | string | null
  service_type?: string | null
  service_type_display?: string | null
  effective_service_type?: string | null
  effective_service_type_display?: string | null
  product_request?: {
    room_number?: string | null
    product?: string | null
    fault?: string | null
    area?: string | null
    second_area?: string | null
    second_area_id?: string | null
    managed_repair_scope?: string | null
    available_second_areas?: string[]
    available_second_area_options?: Array<Record<string, unknown>>
    second_area_needs_confirmation?: boolean
  }
  order?: {
    room_number?: string | null
    area?: string | null
    second_area?: string | null
    second_area_id?: string | null
    managed_repair_scope?: string | null
    available_second_areas?: string[]
    available_second_area_options?: Array<Record<string, unknown>>
    second_area_needs_confirmation?: boolean
    urgency?: UrgencyLevel | null
    expected_start_time?: string | null
    goods_arrival_status?: string | null
    contacts?: string | null
    phone?: string | null
    remark?: string | null
    special_requirement?: string | null
    total_fee?: string | null
    user_confirmed?: boolean
    user_cancelled?: boolean
    items?: OrderItem[]
  }
  products?: ProductOption[]
  form?: OrderForm
  errors?: string[]
  actions?: string[]
  submission?: {
    state?: SubmissionState | string
    order_no?: string | null
    message?: string | null
  }
  submitted_order?: SubmittedOrder | null
}

export interface StreamEvent {
  type: 'status' | 'token' | 'final' | 'error' | 'tool_call'
  session_id?: string
  step?: string
  message?: string
  content?: string
  conversation_messages?: ConversationMessagePayload[]
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
