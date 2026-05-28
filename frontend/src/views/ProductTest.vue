<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

interface ProductItem {
  service_product_code: string
  service_product_name: string
  product_type: string
  category: string
  service_order_type: string
  unit: string
  price: string
  price_status: string
  related_category: string
  related_area: string
  fault_phenomenon: string
  remark: string
}

interface SearchResult {
  score: number
  service_product_code: string
  service_product_name: string
  service_order_type: string
  product_type: string
  related_area: string
  fault_phenomenon: string
  price: string
  unit: string
}

const SERVICE_TYPES = ['全部', '单次维修服务', '单次安装', '单次测量', '托管维修']

// 商品库
const allProducts = ref<ProductItem[]>([])
const activeServiceType = ref('全部')
const productKeyword = ref('')
const loadingProducts = ref(false)
const productError = ref('')

// 检索面板
const searchQuery = ref('')
const searchProduct = ref('')
const searchFault = ref('')
const searchArea = ref('')
const searchServiceType = ref('')
const topK = ref(10)
const threshold = ref(0.4)
const nameWeight = ref(0.55)
const faultWeight = ref(0.45)
const searching = ref(false)
const searchError = ref('')
const searchResults = ref<SearchResult[]>([])
const showParams = ref(false)

const filteredProducts = computed(() => {
  let items = allProducts.value
  if (activeServiceType.value !== '全部') {
    items = items.filter(p => p.service_order_type === activeServiceType.value)
  }
  const kw = productKeyword.value.trim().toLowerCase()
  if (kw) {
    items = items.filter(p =>
      p.service_product_name.toLowerCase().includes(kw) ||
      p.service_product_code.toLowerCase().includes(kw) ||
      p.fault_phenomenon.toLowerCase().includes(kw)
    )
  }
  return items
})

const serviceTypeCounts = computed(() => {
  const counts: Record<string, number> = { '全部': allProducts.value.length }
  for (const t of SERVICE_TYPES.slice(1)) {
    counts[t] = allProducts.value.filter(p => p.service_order_type === t).length
  }
  return counts
})

function scoreColor(score: number) {
  if (score >= 0.75) return 'text-emerald-600 bg-emerald-50'
  if (score >= 0.6) return 'text-amber-600 bg-amber-50'
  return 'text-slate-500 bg-slate-100'
}

function scoreBarColor(score: number) {
  if (score >= 0.75) return 'bg-emerald-500'
  if (score >= 0.6) return 'bg-amber-400'
  return 'bg-slate-300'
}

function serviceTypeBadge(type: string) {
  return {
    '单次维修服务': 'bg-rose-50 text-rose-600 border-rose-100',
    '单次安装':     'bg-blue-50 text-blue-600 border-blue-100',
    '单次测量':     'bg-violet-50 text-violet-600 border-violet-100',
    '托管维修':     'bg-amber-50 text-amber-600 border-amber-100',
  }[type] ?? 'bg-slate-50 text-slate-500 border-slate-200'
}

function fillFromProduct(product: ProductItem) {
  searchProduct.value = product.service_product_name
  if (product.related_area) searchArea.value = product.related_area
}

async function loadProducts() {
  loadingProducts.value = true
  productError.value = ''
  try {
    const res = await fetch('/api/products')
    if (!res.ok) throw new Error(`请求失败 ${res.status}`)
    const data = await res.json()
    allProducts.value = data.items
  } catch (e) {
    productError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loadingProducts.value = false
  }
}

async function doSearch() {
  if (!searchQuery.value.trim() && !searchProduct.value.trim() && !searchFault.value.trim()) {
    searchError.value = '请至少填写查询描述、商品名称或故障现象之一'
    return
  }
  searching.value = true
  searchError.value = ''
  searchResults.value = []
  try {
    const body: Record<string, unknown> = {
      query: searchQuery.value || [searchProduct.value, searchFault.value, searchArea.value].filter(Boolean).join(' '),
      top_k: topK.value,
      threshold: threshold.value,
    }
    if (searchProduct.value) body.product = searchProduct.value
    if (searchFault.value) body.fault = searchFault.value
    if (searchArea.value) body.area = searchArea.value

    const res = await fetch('/api/products/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`请求失败 ${res.status}`)
    const data = await res.json()
    searchResults.value = data.results
  } catch (e) {
    searchError.value = e instanceof Error ? e.message : '检索失败'
  } finally {
    searching.value = false
  }
}

function clearSearch() {
  searchQuery.value = ''
  searchProduct.value = ''
  searchFault.value = ''
  searchArea.value = ''
  searchServiceType.value = ''
  searchResults.value = []
  searchError.value = ''
}

onMounted(() => loadProducts())
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-slate-100 font-sans antialiased">

    <!-- Header -->
    <header class="flex h-14 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-5 shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
      <div class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-sm shadow-indigo-600/30">H</div>
        <div class="leading-none">
          <p class="text-[13px] font-semibold text-slate-800">AI 下单助手</p>
          <p class="text-[10px] text-slate-400">Hotel Desk</p>
        </div>
      </div>

      <div class="h-6 w-px bg-slate-200"></div>

      <nav class="flex items-center gap-1">
        <RouterLink
          to="/"
          class="rounded-lg px-3 py-1.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
        >下单对话</RouterLink>
        <RouterLink
          to="/products"
          class="rounded-lg bg-indigo-50 px-3 py-1.5 text-[12px] font-medium text-indigo-700 transition"
        >商品库</RouterLink>
      </nav>

      <div class="ml-auto flex items-center gap-2">
        <span class="text-[12px] text-slate-400">共 {{ allProducts.length }} 件商品</span>
        <button
          class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
          @click="loadProducts"
        >刷新</button>
      </div>
    </header>

    <!-- Main -->
    <main class="flex flex-1 gap-4 overflow-hidden p-4">

      <!-- Left: Search Panel -->
      <div class="flex w-72 shrink-0 flex-col gap-3 overflow-y-auto">

        <!-- Search inputs -->
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p class="mb-3 text-[12px] font-semibold uppercase tracking-wider text-slate-400">检索测试</p>

          <div class="space-y-2.5">
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">查询描述</label>
              <textarea
                v-model="searchQuery"
                rows="2"
                placeholder="例：门锁打不开"
                class="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                @keydown.enter.prevent="doSearch"
              />
            </div>

            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">商品/设备</label>
                <input
                  v-model="searchProduct"
                  type="text"
                  placeholder="门锁"
                  class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">故障现象</label>
                <input
                  v-model="searchFault"
                  type="text"
                  placeholder="打不开"
                  class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">区域</label>
                <input
                  v-model="searchArea"
                  type="text"
                  placeholder="卫生间"
                  class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">服务类型</label>
                <select
                  v-model="searchServiceType"
                  class="w-full rounded-xl border border-slate-200 bg-slate-50 px-2 py-2 text-[13px] text-slate-700 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                >
                  <option value="">自动推断</option>
                  <option v-for="t in SERVICE_TYPES.slice(1)" :key="t" :value="t">{{ t }}</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Param panel toggle -->
          <button
            class="mt-3 flex w-full items-center justify-between rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-[11px] font-medium text-slate-500 transition hover:bg-slate-100"
            @click="showParams = !showParams"
          >
            <span>高级参数</span>
            <svg class="h-3.5 w-3.5 transition-transform" :class="showParams ? 'rotate-180' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>

          <div v-if="showParams" class="mt-2 space-y-2.5 rounded-xl border border-slate-100 bg-slate-50/70 p-3">
            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">Top-K</label>
                <input v-model.number="topK" type="number" min="1" max="50"
                  class="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[12px] text-slate-700 outline-none focus:border-indigo-300"
                />
              </div>
              <div>
                <label class="mb-1 block text-[11px] font-medium text-slate-500">阈值</label>
                <input v-model.number="threshold" type="number" min="0" max="1" step="0.05"
                  class="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[12px] text-slate-700 outline-none focus:border-indigo-300"
                />
              </div>
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <label class="text-[11px] font-medium text-slate-500">名称权重</label>
                <span class="text-[11px] text-indigo-600">{{ nameWeight }}</span>
              </div>
              <input v-model.number="nameWeight" type="range" min="0" max="1" step="0.05" class="w-full accent-indigo-600" />
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <label class="text-[11px] font-medium text-slate-500">故障权重</label>
                <span class="text-[11px] text-indigo-600">{{ faultWeight }}</span>
              </div>
              <input v-model.number="faultWeight" type="range" min="0" max="1" step="0.05" class="w-full accent-indigo-600" />
            </div>
          </div>

          <div class="mt-3 flex gap-2">
            <button
              class="flex-1 rounded-xl bg-indigo-600 py-2.5 text-[13px] font-semibold text-white shadow-sm shadow-indigo-600/20 transition hover:bg-indigo-700 active:scale-[0.98] disabled:opacity-40"
              :disabled="searching"
              @click="doSearch"
            >
              <span v-if="searching">检索中...</span>
              <span v-else>检索</span>
            </button>
            <button
              class="rounded-xl border border-slate-200 px-3 text-[13px] font-medium text-slate-500 transition hover:bg-slate-50"
              @click="clearSearch"
            >清空</button>
          </div>
        </div>

        <!-- Search results -->
        <div v-if="searchError" class="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
          {{ searchError }}
        </div>

        <div v-if="searchResults.length > 0" class="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div class="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <p class="text-[12px] font-semibold text-slate-700">匹配结果</p>
            <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">{{ searchResults.length }} 条</span>
          </div>

          <div class="divide-y divide-slate-50">
            <div
              v-for="(result, i) in searchResults"
              :key="result.service_product_code"
              class="px-4 py-3"
            >
              <!-- Rank + name -->
              <div class="flex items-start gap-2">
                <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                  :class="i === 0 ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500'"
                >{{ i + 1 }}</span>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[13px] font-semibold text-slate-800">{{ result.service_product_name }}</p>
                  <p class="mt-0.5 text-[11px] text-slate-400">{{ result.service_product_code }}</p>
                </div>
                <span class="shrink-0 rounded-lg px-2 py-0.5 text-[11px] font-bold" :class="scoreColor(result.score)">
                  {{ (result.score * 100).toFixed(1) }}
                </span>
              </div>

              <!-- Score bar -->
              <div class="mt-2 flex items-center gap-2">
                <span class="w-14 shrink-0 text-[10px] text-slate-400">相似度</span>
                <div class="h-1.5 flex-1 rounded-full bg-slate-100">
                  <div class="h-full rounded-full transition-all" :class="scoreBarColor(result.score)" :style="{ width: `${result.score * 100}%` }"></div>
                </div>
              </div>

              <!-- Fault phenomenon -->
              <p v-if="result.fault_phenomenon" class="mt-2 text-[11px] leading-4 text-slate-400" :title="result.fault_phenomenon">
                {{ result.fault_phenomenon }}
              </p>

              <!-- Tags -->
              <div class="mt-2 flex flex-wrap gap-1.5">
                <span class="rounded-md border px-1.5 py-0.5 text-[10px] font-medium" :class="serviceTypeBadge(result.service_order_type)">
                  {{ result.service_order_type }}
                </span>
                <span v-if="result.related_area" class="rounded-md border border-slate-100 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                  {{ result.related_area }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="!searching && searchResults.length === 0 && !searchError" class="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center">
          <p class="text-[12px] text-slate-400">输入查询条件后点击检索</p>
        </div>
      </div>

      <!-- Right: Product Library -->
      <div class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">

        <!-- Toolbar -->
        <div class="flex shrink-0 items-center gap-3 border-b border-slate-100 px-5 py-3">
          <!-- Service type tabs -->
          <div class="flex items-center gap-1">
            <button
              v-for="type in SERVICE_TYPES"
              :key="type"
              class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition"
              :class="activeServiceType === type
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'"
              @click="activeServiceType = type"
            >
              {{ type }}
              <span class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                :class="activeServiceType === type ? 'bg-indigo-100 text-indigo-600' : 'bg-slate-100 text-slate-400'"
              >{{ serviceTypeCounts[type] || 0 }}</span>
            </button>
          </div>

          <div class="ml-auto flex items-center gap-2">
            <div class="relative">
              <svg class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
              <input
                v-model="productKeyword"
                type="text"
                placeholder="搜索名称/编码/故障"
                class="w-52 rounded-xl border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-[12px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
              />
            </div>
            <span class="text-[12px] text-slate-400">{{ filteredProducts.length }} 条</span>
          </div>
        </div>

        <!-- Loading / error -->
        <div v-if="loadingProducts" class="flex flex-1 items-center justify-center">
          <div class="flex flex-col items-center gap-3">
            <div class="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-600"></div>
            <p class="text-[13px] text-slate-400">加载商品库...</p>
          </div>
        </div>

        <div v-else-if="productError" class="flex flex-1 items-center justify-center">
          <div class="rounded-2xl border border-rose-100 bg-rose-50 px-6 py-4 text-center">
            <p class="text-[13px] font-medium text-rose-600">{{ productError }}</p>
            <button class="mt-2 text-[12px] text-rose-500 underline" @click="loadProducts">重新加载</button>
          </div>
        </div>

        <!-- Table -->
        <div v-else class="flex-1 overflow-auto">
          <table class="w-full min-w-[900px] border-collapse text-[13px]">
            <thead class="sticky top-0 z-10 bg-slate-50">
              <tr>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">商品编码</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">商品名称</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">服务类型</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">价格</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">区域</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">故障现象</th>
                <th class="border-b border-slate-200 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="product in filteredProducts"
                :key="product.service_product_code"
                class="group border-b border-slate-50 transition hover:bg-indigo-50/30"
              >
                <td class="px-4 py-3 font-mono text-[11px] text-slate-400">{{ product.service_product_code }}</td>
                <td class="px-4 py-3 font-medium text-slate-800">{{ product.service_product_name }}</td>
                <td class="px-4 py-3">
                  <span class="rounded-md border px-2 py-0.5 text-[11px] font-medium" :class="serviceTypeBadge(product.service_order_type)">
                    {{ product.service_order_type }}
                  </span>
                </td>
                <td class="px-4 py-3 text-slate-600">{{ product.price || '—' }}</td>
                <td class="px-4 py-3 text-slate-500">{{ product.related_area || '—' }}</td>
                <td class="max-w-[200px] px-4 py-3">
                  <p class="truncate text-slate-500" :title="product.fault_phenomenon">{{ product.fault_phenomenon || '—' }}</p>
                </td>
                <td class="px-4 py-3">
                  <button
                    class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-500 opacity-0 transition hover:border-indigo-200 hover:text-indigo-600 group-hover:opacity-100"
                    @click="fillFromProduct(product)"
                  >
                    填入检索
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="filteredProducts.length === 0" class="py-16 text-center">
            <p class="text-[13px] text-slate-400">没有匹配的商品</p>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
