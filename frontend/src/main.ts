import 'virtual:uno.css'
import { createApp } from 'vue'
import RootApp from './RootApp.vue'
import router from './router'
import './style.css'

createApp(RootApp).use(router).mount('#app')
