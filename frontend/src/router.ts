import { createRouter, createWebHistory } from 'vue-router'
import Chat from './App.vue'
import ProductTest from './views/ProductTest.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Chat },
    { path: '/products', component: ProductTest },
  ],
})
