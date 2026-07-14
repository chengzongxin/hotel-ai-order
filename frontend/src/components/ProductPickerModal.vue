<script setup lang="ts">
import { computed, ref, watch } from 'vue'

interface CatalogProduct {
  service_product_code: string
  service_product_name: string
  service_order_type: string
  category: string
  unit: string
  price: string
  fault_phenomenon: string
}

const props = defineProps<{
  open: boolean
  serviceType?: string | null
  existingCodes?: string[]
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  select: [productCode: string]
}>()

const products = ref<CatalogProduct[]>([])
const keyword = ref('')
const error = ref('')
const isLoading = ref(false)

const existingCodeSet = computed(() => new Set(props.existingCodes ?? []))
const filteredProducts = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  const source = query
    ? products.value.filter((item) => [
        item.service_product_code,
        item.service_product_name,
        item.category,
        item.fault_phenomenon,
      ].some((value) => value?.toLowerCase().includes(query)))
    : products.value
  return source.slice(0, 100)
})

async function loadProducts() {
  isLoading.value = true
  error.value = ''
  try {
    const query = props.serviceType ? `?service_type=${encodeURIComponent(props.serviceType)}` : ''
    const response = await fetch(`/api/products${query}`)
    if (!response.ok) throw new Error(`加载商品失败 ${response.status}`)
    const data = await response.json() as { items?: CatalogProduct[] }
    products.value = data.items ?? []
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载商品失败'
  } finally {
    isLoading.value = false
  }
}

watch(() => props.open, (open) => {
  if (!open) return
  keyword.value = ''
  void loadProducts()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4" @click.self="emit('close')">
      <section class="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h3 class="text-base font-semibold text-slate-900">新增商品</h3>
            <p class="mt-0.5 text-xs text-slate-500">仅展示当前订单服务类型的商品</p>
          </div>
          <button class="rounded-lg px-2 py-1 text-xl text-slate-400 hover:bg-slate-100" @click="emit('close')">×</button>
        </header>

        <div class="border-b border-slate-100 p-4">
          <input v-model="keyword" autofocus class="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100" placeholder="搜索商品名称、编码、分类或故障现象" />
        </div>

        <div class="flex-1 overflow-y-auto p-3">
          <p v-if="isLoading" class="py-10 text-center text-sm text-slate-400">正在加载商品...</p>
          <p v-else-if="error" class="py-10 text-center text-sm text-red-500">{{ error }}</p>
          <p v-else-if="!filteredProducts.length" class="py-10 text-center text-sm text-slate-400">没有找到符合条件的商品</p>
          <template v-else>
          <button
            v-for="item in filteredProducts"
            :key="item.service_product_code"
            type="button"
            class="mb-2 flex w-full items-center gap-3 rounded-xl border border-slate-100 px-3.5 py-3 text-left transition hover:border-indigo-200 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading || existingCodeSet.has(item.service_product_code)"
            @click="emit('select', item.service_product_code)"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-semibold text-slate-800">{{ item.service_product_name }}</p>
              <p class="mt-1 truncate text-xs text-slate-500">{{ item.service_product_code }} · {{ item.category }} · {{ item.fault_phenomenon }}</p>
            </div>
            <div class="shrink-0 text-right text-xs">
              <p class="font-semibold text-indigo-600">¥{{ item.price }}/{{ item.unit }}</p>
              <p v-if="existingCodeSet.has(item.service_product_code)" class="mt-1 text-slate-400">已添加</p>
            </div>
          </button>
          </template>
        </div>
      </section>
    </div>
  </Teleport>
</template>
