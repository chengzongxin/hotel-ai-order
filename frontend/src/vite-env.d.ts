/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ACCESS_TOKEN?: string
  readonly VITE_USER_ID?: string
  readonly VITE_TENANT_ID?: string
  readonly VITE_APP_PLATFORM?: string
  readonly VITE_APP_TYPE?: string
  readonly VITE_DEVICE_ID?: string
  readonly VITE_APP_VERSION?: string
  readonly VITE_APP_CHANNEL?: string
  readonly VITE_APP_SPIRIT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  SpeechRecognition?: typeof SpeechRecognition
  webkitSpeechRecognition?: typeof SpeechRecognition
}
