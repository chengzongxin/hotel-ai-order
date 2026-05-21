import { defineConfig, presetUno, presetAttributify } from 'unocss'

export default defineConfig({
  presets: [
    presetUno(),       // Tailwind/Windi CSS compatible utilities
    presetAttributify(), // optional: allow class-like attributes
  ],
  theme: {
    extend: {
      animation: {
        bounce: 'bounce 1s infinite',
      },
    },
  },
})
