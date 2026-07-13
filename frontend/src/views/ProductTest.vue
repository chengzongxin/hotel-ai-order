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

const SEARCH_SERVICE_TYPES = ['托管维修', '单次安装', '单次测量']
const SERVICE_TYPES = ['全部', '单次维修服务', ...SEARCH_SERVICE_TYPES]

const PRESETS = [
  { label: '客房维修', product: '空调',   fault: '不制冷', serviceType: '托管维修' },
  { label: '公区维修', product: '门锁',   fault: '坏了',   serviceType: '托管维修' },
  { label: '安装',     product: '洗衣机', fault: '',       serviceType: '单次安装' },
  { label: '测量',     product: '窗帘',   fault: '',       serviceType: '单次测量' },
  { label: '水路',     product: '水龙头', fault: '漏水',   serviceType: '托管维修' },
]

// 商品库
const allProducts = ref<ProductItem[]>([])
const activeServiceType = ref('全部')
const productKeyword = ref('')
const loadingProducts = ref(false)
const productError = ref('')
const showLibrary = ref(true)

// 检索
const searchServiceType = ref('托管维修')
const searchProduct = ref('')
const searchFault = ref('')
const topK = ref(5)
const threshold = ref(0.4)
const showParams = ref(false)
const searching = ref(false)
const searchError = ref('')
const searchResults = ref<SearchResult[]>([])
const lastQuery = ref('')

const actualQuery = computed(() => {
  const serviceHint = ({
    '单次安装': '安装',
    '单次测量': '测量',
  } as Record<string, string>)[searchServiceType.value]
  return [searchProduct.value, searchFault.value, serviceHint].filter(Boolean).join(' ').trim()
})

const filteredProducts = computed(() => {
  let items = allProducts.value
  if (activeServiceType.value !== '全部')
    items = items.filter(p => p.service_order_type === activeServiceType.value)
  const kw = productKeyword.value.trim().toLowerCase()
  if (kw)
    items = items.filter(p =>
      p.service_product_name.toLowerCase().includes(kw) ||
      p.service_product_code.toLowerCase().includes(kw) ||
      p.fault_phenomenon.toLowerCase().includes(kw)
    )
  return items
})

const serviceTypeCounts = computed(() => {
  const counts: Record<string, number> = { '全部': allProducts.value.length }
  for (const t of SERVICE_TYPES.slice(1))
    counts[t] = allProducts.value.filter(p => p.service_order_type === t).length
  return counts
})

function scoreColor(score: number) {
  if (score >= 0.75) return 'text-emerald-600 bg-emerald-50 border-emerald-200'
  if (score >= 0.6)  return 'text-amber-600 bg-amber-50 border-amber-200'
  return 'text-slate-500 bg-slate-100 border-slate-200'
}

function scoreBarColor(score: number) {
  if (score >= 0.75) return 'bg-emerald-500'
  if (score >= 0.6)  return 'bg-amber-400'
  return 'bg-slate-300'
}

function serviceTypeBadge(type: string) {
  return ({
    '单次维修服务': 'bg-rose-50 text-rose-600 border-rose-100',
    '单次安装':     'bg-blue-50 text-blue-600 border-blue-100',
    '单次测量':     'bg-violet-50 text-violet-600 border-violet-100',
    '托管维修':     'bg-amber-50 text-amber-600 border-amber-100',
  } as Record<string, string>)[type] ?? 'bg-slate-50 text-slate-500 border-slate-200'
}

function applyPreset(preset: typeof PRESETS[0]) {
  searchServiceType.value = preset.serviceType
  searchProduct.value = preset.product
  searchFault.value   = preset.fault
  searchResults.value = []
  searchError.value   = ''
  lastQuery.value     = ''
}

function fillFromProduct(product: ProductItem) {
  searchServiceType.value = SEARCH_SERVICE_TYPES.includes(product.service_order_type)
    ? product.service_order_type
    : '托管维修'
  searchProduct.value = product.service_product_name
  searchFault.value   = ''
  searchResults.value = []
  lastQuery.value     = ''
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
  const query = actualQuery.value
  if (!query) { searchError.value = '请至少填写商品名称或故障现象'; return }
  searching.value = true
  searchError.value = ''
  searchResults.value = []
  lastQuery.value = ''
  try {
    const res = await fetch('/api/products/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        top_k:     topK.value,
        threshold: threshold.value,
        service_type: searchServiceType.value,
      }),
    })
    if (!res.ok) throw new Error(`请求失败 ${res.status}`)
    const data = await res.json()
    searchResults.value = data.products
    lastQuery.value     = data.query
  } catch (e) {
    searchError.value = e instanceof Error ? e.message : '检索失败'
  } finally {
    searching.value = false
  }
}

function clearSearch() {
  searchServiceType.value = '托管维修'
  searchProduct.value = ''
  searchFault.value   = ''
  searchResults.value = []
  searchError.value   = ''
  lastQuery.value     = ''
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
        <RouterLink to="/" class="rounded-lg px-3 py-1.5 text-[12px] font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-700">下单对话</RouterLink>
        <RouterLink to="/products" class="rounded-lg bg-indigo-50 px-3 py-1.5 text-[12px] font-medium text-indigo-700">商品库</RouterLink>
      </nav>
      <div class="ml-auto flex items-center gap-2">
        <span class="text-[12px] text-slate-400">共 {{ allProducts.length }} 件商品</span>
        <button
          class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:bg-slate-50"
          @click="showLibrary = !showLibrary"
        >{{ showLibrary ? '隐藏商品库' : '显示商品库' }}</button>
        <button
          class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:bg-slate-50"
          @click="loadProducts"
        >刷新</button>
      </div>
    </header>

    <!-- Main: 三栏 -->
    <main class="flex flex-1 gap-3 overflow-hidden p-4">

      <!-- Col 1: 搜索控制 (固定宽度) -->
      <div class="flex w-60 shrink-0 flex-col gap-3 overflow-y-auto">

        <!-- 快速预设 -->
        <div class="rounded-2xl border border-slate-200 bg-white p-3.5 shadow-sm">
          <p class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">场景预设</p>
          <div class="space-y-1">
            <button
              v-for="preset in PRESETS"
              :key="preset.label"
              class="flex w-full items-center gap-2.5 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-left transition hover:border-indigo-200 hover:bg-indigo-50"
              @click="applyPreset(preset)"
            >
              <div class="min-w-0 flex-1">
                <p class="text-[12px] font-semibold text-slate-700">{{ preset.label }}</p>
                <p class="truncate text-[11px] text-slate-400">{{ preset.product }}<span v-if="preset.fault"> · {{ preset.fault }}</span></p>
              </div>
              <span class="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{{ preset.serviceType }}</span>
            </button>
          </div>
        </div>

        <!-- 检索输入 -->
        <div class="rounded-2xl border border-slate-200 bg-white p-3.5 shadow-sm">
          <p class="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">混合检索</p>
          <div class="space-y-2">
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">服务类型</label>
              <select v-model="searchServiceType"
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
              >
                <option v-for="type in SEARCH_SERVICE_TYPES" :key="type" :value="type">{{ type }}</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">商品 / 设备</label>
              <input v-model="searchProduct" type="text" placeholder="空调"
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                @keydown.enter="doSearch"
              />
            </div>
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">故障现象 <span class="text-slate-300">（安装/测量可留空）</span></label>
              <input v-model="searchFault" type="text" placeholder="不制冷"
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                @keydown.enter="doSearch"
              />
            </div>
            <!-- query 预览 -->
            <div class="rounded-xl border border-indigo-100 bg-indigo-50/60 px-3 py-2">
              <p class="mb-0.5 text-[10px] font-medium text-indigo-400">实际 query</p>
              <p class="font-mono text-[12px] text-indigo-700">{{ actualQuery || '—' }}</p>
            </div>
          </div>

          <!-- 高级参数 -->
          <button
            class="mt-2.5 flex w-full items-center justify-between rounded-xl border border-slate-100 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-500 transition hover:bg-slate-100"
            @click="showParams = !showParams"
          >
            <span>高级参数</span>
            <svg class="h-3.5 w-3.5 transition-transform" :class="showParams ? 'rotate-180' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          <div v-if="showParams" class="mt-2 grid grid-cols-2 gap-2 rounded-xl border border-slate-100 bg-slate-50/70 p-2.5">
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">Top-K</label>
              <input v-model.number="topK" type="number" min="1" max="50"
                class="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[12px] outline-none focus:border-indigo-300"
              />
            </div>
            <div>
              <label class="mb-1 block text-[11px] font-medium text-slate-500">阈值</label>
              <input v-model.number="threshold" type="number" min="0" max="1" step="0.05"
                class="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[12px] outline-none focus:border-indigo-300"
              />
            </div>
          </div>

          <div class="mt-3 flex gap-2">
            <button
              class="flex-1 rounded-xl bg-indigo-600 py-2 text-[13px] font-semibold text-white shadow-sm shadow-indigo-600/20 transition hover:bg-indigo-700 active:scale-[0.98] disabled:opacity-40"
              :disabled="searching || !actualQuery"
              @click="doSearch"
            >{{ searching ? '检索中...' : '检索' }}</button>
            <button
              class="rounded-xl border border-slate-200 px-3 text-[13px] font-medium text-slate-500 transition hover:bg-slate-50"
              @click="clearSearch"
            >清空</button>
          </div>
        </div>
      </div>

      <!-- Col 2: 检索结果 (固定宽度，始终可见) -->
      <div class="flex w-80 shrink-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div class="flex shrink-0 items-center justify-between border-b border-slate-100 px-4 py-3">
          <p class="text-[13px] font-semibold text-slate-700">匹配结果</p>
          <span v-if="searchResults.length" class="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-600">{{ searchResults.length }} 条</span>
        </div>

        <!-- query 回显 -->
        <div v-if="lastQuery" class="shrink-0 border-b border-slate-50 bg-slate-50/60 px-4 py-2">
          <p class="text-[10px] text-slate-400">混合检索 query</p>
          <p class="mt-0.5 font-mono text-[12px] font-medium text-indigo-600">"{{ lastQuery }}"</p>
        </div>

        <!-- 错误 -->
        <div v-if="searchError" class="m-3 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
          {{ searchError }}
        </div>

        <!-- 空态 -->
        <div v-else-if="!searching && !searchResults.length" class="flex flex-1 flex-col items-center justify-center gap-2 text-center">
          <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100">
            <svg class="h-6 w-6 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
          </div>
          <p class="text-[12px] text-slate-400">填写商品和故障后点击检索</p>
          <p class="text-[11px] text-slate-300">或点击左侧场景预设</p>
        </div>

        <!-- 加载中 -->
        <div v-else-if="searching" class="flex flex-1 items-center justify-center">
          <div class="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-600"></div>
        </div>

        <!-- 结果列表 -->
        <div v-else class="flex-1 overflow-y-auto divide-y divide-slate-50">
          <div
            v-for="(result, i) in searchResults"
            :key="result.service_product_code"
            class="px-4 py-4"
            :class="i === 0 ? 'bg-indigo-50/30' : ''"
          >
            <!-- 排名 + 名称 + 分数 -->
            <div class="flex items-start gap-2.5">
              <span class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                :class="i === 0 ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500'"
              >{{ i + 1 }}</span>
              <div class="min-w-0 flex-1">
                <p class="text-[14px] font-semibold leading-snug text-slate-800">{{ result.service_product_name }}</p>
                <p class="mt-0.5 font-mono text-[11px] text-slate-400">{{ result.service_product_code }}</p>
              </div>
              <span class="shrink-0 rounded-lg border px-2 py-0.5 text-[12px] font-bold" :class="scoreColor(result.score)">
                {{ (result.score * 100).toFixed(1) }}
              </span>
            </div>

            <!-- 分数条 -->
            <div class="mt-2.5 flex items-center gap-2">
              <span class="w-10 shrink-0 text-[10px] text-slate-400">相似度</span>
              <div class="h-1.5 flex-1 rounded-full bg-slate-100">
                <div class="h-full rounded-full" :class="scoreBarColor(result.score)" :style="{ width: `${result.score * 100}%` }"></div>
              </div>
              <span class="w-8 text-right text-[10px] text-slate-400">{{ (result.score * 100).toFixed(0) }}%</span>
            </div>

            <!-- 服务类型 + 区域 -->
            <div class="mt-2.5 flex flex-wrap gap-1.5">
              <span class="rounded-md border px-2 py-0.5 text-[11px] font-semibold" :class="serviceTypeBadge(result.service_order_type)">
                {{ result.service_order_type }}
              </span>
              <span v-if="result.related_area" class="rounded-md border border-slate-100 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-500">
                {{ result.related_area }}
              </span>
              <span v-if="result.price" class="rounded-md border border-slate-100 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-500">
                ¥{{ result.price }}
              </span>
            </div>

            <!-- 故障现象（索引文本） -->
            <div v-if="result.fault_phenomenon" class="mt-2 rounded-lg bg-slate-50 px-3 py-2">
              <p class="mb-0.5 text-[10px] font-medium text-slate-400">故障现象（向量索引）</p>
              <p class="text-[12px] leading-5 text-slate-600">{{ result.fault_phenomenon }}</p>
            </div>
            <div v-else class="mt-2 rounded-lg bg-slate-50 px-3 py-2">
              <p class="text-[11px] italic text-slate-300">安装 / 测量类，无故障现象索引</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Col 3: 商品库 (可折叠) -->
      <div v-if="showLibrary" class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <!-- Toolbar -->
        <div class="flex shrink-0 items-center gap-3 border-b border-slate-100 px-4 py-3">
          <div class="flex items-center gap-1 overflow-x-auto">
            <button
              v-for="type in SERVICE_TYPES"
              :key="type"
              class="flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition"
              :class="activeServiceType === type ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'"
              @click="activeServiceType = type"
            >
              {{ type }}
              <span class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                :class="activeServiceType === type ? 'bg-indigo-100 text-indigo-600' : 'bg-slate-100 text-slate-400'"
              >{{ serviceTypeCounts[type] || 0 }}</span>
            </button>
          </div>
          <div class="ml-auto flex shrink-0 items-center gap-2">
            <div class="relative">
              <svg class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
              <input v-model="productKeyword" type="text" placeholder="搜索名称 / 编码 / 故障"
                class="w-44 rounded-xl border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-[12px] text-slate-700 placeholder-slate-300 outline-none focus:border-indigo-300 focus:bg-white focus:ring-2 focus:ring-indigo-100"
              />
            </div>
            <span class="text-[12px] text-slate-400">{{ filteredProducts.length }} 条</span>
          </div>
        </div>

        <!-- Loading / error -->
        <div v-if="loadingProducts" class="flex flex-1 items-center justify-center">
          <div class="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-600"></div>
        </div>
        <div v-else-if="productError" class="flex flex-1 items-center justify-center">
          <div class="rounded-2xl border border-rose-100 bg-rose-50 px-6 py-4 text-center">
            <p class="text-[13px] font-medium text-rose-600">{{ productError }}</p>
            <button class="mt-2 text-[12px] text-rose-500 underline" @click="loadProducts">重新加载</button>
          </div>
        </div>

        <!-- Table -->
        <div v-else class="flex-1 overflow-auto">
          <table class="w-full min-w-[700px] border-collapse text-[13px]">
            <thead class="sticky top-0 z-10 bg-slate-50">
              <tr>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">编码</th>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">商品名称</th>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">服务类型</th>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">价格</th>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">区域</th>
                <th class="border-b border-slate-200 px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">故障现象（向量索引）</th>
                <th class="border-b border-slate-200 px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="product in filteredProducts"
                :key="product.service_product_code"
                class="group border-b border-slate-50 transition hover:bg-indigo-50/30"
              >
                <td class="px-4 py-2.5 font-mono text-[11px] text-slate-400">{{ product.service_product_code }}</td>
                <td class="px-4 py-2.5 font-medium text-slate-800">{{ product.service_product_name }}</td>
                <td class="px-4 py-2.5">
                  <span class="rounded-md border px-2 py-0.5 text-[11px] font-medium" :class="serviceTypeBadge(product.service_order_type)">
                    {{ product.service_order_type }}
                  </span>
                </td>
                <td class="px-4 py-2.5 text-slate-600">{{ product.price || '—' }}</td>
                <td class="px-4 py-2.5 text-slate-500">{{ product.related_area || '—' }}</td>
                <td class="max-w-[200px] px-4 py-2.5">
                  <p v-if="product.fault_phenomenon" class="truncate text-slate-500" :title="product.fault_phenomenon">{{ product.fault_phenomenon }}</p>
                  <p v-else class="text-[11px] italic text-slate-300">安装/测量，无故障现象</p>
                </td>
                <td class="px-4 py-2.5">
                  <button
                    class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-500 opacity-0 transition hover:border-indigo-200 hover:text-indigo-600 group-hover:opacity-100"
                    @click="fillFromProduct(product)"
                  >填入检索</button>
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
