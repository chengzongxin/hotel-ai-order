export type Role = 'user' | 'assistant'

export interface ChatMessage {
  id: number
  role: Role
  content: string
  time: string
}

export type UrgencyLevel = 'low' | 'medium' | 'high' | 'urgent'

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
  input_type?: 'text' | 'textarea' | 'select' | 'datetime'
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
  inputType: 'text' | 'textarea' | 'select' | 'datetime'
  options: Array<{ label: string; value: string }>
}

export interface OrderPreview {
  ui_phase?: string | null
  service_type?: string | null
  service_type_display?: string | null
  effective_service_type?: string | null
  effective_service_type_display?: string | null
  status?: string | null
  order_info?: {
    room_number?: string | null
    product?: string | null
    fault?: string | null
    area?: string | null
    urgency?: UrgencyLevel | null
    expected_start_time?: string | null
    goods_arrival_status?: string | null
  }
  products?: ProductSection
  order_card?: OrderCardSection
  coverage?: CoverageSection
  missing_info?: string[]
  submission?: {
    payload?: Record<string, unknown>
    result?: Record<string, unknown>
    missing_fields?: string[]
  }
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
