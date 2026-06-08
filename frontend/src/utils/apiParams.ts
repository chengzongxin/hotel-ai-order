/** 请求鉴权参数：默认值 + localStorage 持久化 + 构造 Header */

export interface ApiRequestParams {
  accessToken: string
  userId: string
  tenantId: string
  platform: string
  appType: string
  deviceId: string
  version: string
  channel: string
  spirit: string
  contacts: string
  phone: string
}

export interface ApiParamField {
  key: keyof ApiRequestParams
  label: string
  placeholder?: string
}

const STORAGE_KEY = 'order_voice_api_params'

export const API_PARAM_FIELDS: ApiParamField[] = [
  { key: 'accessToken', label: 'Access Token', placeholder: '用户登录 token' },
  { key: 'userId', label: '用户 ID', placeholder: 'X-User-Id' },
  { key: 'tenantId', label: '租户 ID', placeholder: 'tenant-id' },
  { key: 'platform', label: '平台', placeholder: 'ios / android' },
  { key: 'appType', label: 'App 类型', placeholder: 'type，默认 2' },
  { key: 'deviceId', label: '设备 ID', placeholder: 'device-id' },
  { key: 'version', label: '版本号', placeholder: 'version' },
  { key: 'channel', label: '渠道', placeholder: 'channel' },
  { key: 'spirit', label: 'Spirit', placeholder: 'App spirit header' },
  { key: 'contacts', label: '联系人', placeholder: 'X-User-Contacts（可选）' },
  { key: 'phone', label: '手机号', placeholder: 'X-User-Phone（可选）' },
]

export function getDefaultApiParams(): ApiRequestParams {
  return {
    accessToken: import.meta.env.VITE_ACCESS_TOKEN ?? 'd5d15b2e6fc7480b9fe87ea8f43591c0',
    userId: import.meta.env.VITE_USER_ID ?? 'dev-user',
    tenantId: import.meta.env.VITE_TENANT_ID ?? '2123',
    platform: import.meta.env.VITE_APP_PLATFORM ?? 'ios',
    appType: import.meta.env.VITE_APP_TYPE ?? '2',
    deviceId: import.meta.env.VITE_DEVICE_ID ?? '1234567890',
    version: import.meta.env.VITE_APP_VERSION ?? '1.1.2',
    channel: import.meta.env.VITE_APP_CHANNEL ?? 'appstore',
    spirit: import.meta.env.VITE_APP_SPIRIT ?? 'IDontKnowPasswordtoo/1708hxcchang',
    contacts: '',
    phone: '',
  }
}

export function loadApiParams(): ApiRequestParams {
  const defaults = getDefaultApiParams()
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaults }
    const stored = JSON.parse(raw) as Partial<ApiRequestParams>
    return { ...defaults, ...stored }
  } catch {
    return { ...defaults }
  }
}

export function saveApiParams(params: ApiRequestParams): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(params))
}

export function resetApiParams(): ApiRequestParams {
  const defaults = getDefaultApiParams()
  saveApiParams(defaults)
  return defaults
}

export function buildApiHeaders(params: ApiRequestParams): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${params.accessToken.trim()}`,
    'X-User-Id': params.userId.trim(),
    'tenant-id': params.tenantId.trim(),
    platform: params.platform.trim(),
    type: params.appType.trim(),
    'device-id': params.deviceId.trim(),
    version: params.version.trim(),
    channel: params.channel.trim(),
    spirit: params.spirit.trim(),
  }
  if (params.contacts.trim()) headers['X-User-Contacts'] = params.contacts.trim()
  if (params.phone.trim()) headers['X-User-Phone'] = params.phone.trim()
  return headers
}
