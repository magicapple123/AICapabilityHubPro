import { ArrowUpRight, ChevronRight, LoaderCircle, RefreshCw, Search, SlidersHorizontal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  fetchMarketCapabilities,
  fetchMarketCategories,
  type MarketCapability,
  type MarketCategory,
} from '@/api/capability'

const ALL_CATEGORIES = '全部'

/** 展示用的装饰资源；接口不返回图片字段，按序循环即可。 */
const TONES = [
  'from-[#d6f77b] to-[#718c2e]',
  'from-[#eee8db] to-[#888e82]',
  'from-[#b4d2ff] to-[#526a86]',
  'from-[#f7b18a] to-[#744d3d]',
]

const CARD_IMAGES = ['vision-market', 'long-form', 'retrieval', 'transcript']

const SEARCH_DEBOUNCE_MS = 300

export function CapabilitiesPage() {
  const navigate = useNavigate()
  const [categories, setCategories] = useState<MarketCategory[]>([])
  const [activeCategory, setActiveCategory] = useState(ALL_CATEGORIES)
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [capabilities, setCapabilities] = useState<MarketCapability[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 输入防抖，避免每敲一个字都打一次网关。
  useEffect(() => {
    const timer = window.setTimeout(() => setKeyword(keywordInput.trim()), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [keywordInput])

  const activeCategoryId = useMemo(
    () => categories.find((item) => item.name === activeCategory)?.id,
    [activeCategory, categories],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const page = await fetchMarketCapabilities({
        category_id: activeCategoryId,
        keyword: keyword || undefined,
        page: 1,
        page_size: 50,
      })
      setCapabilities(page.list ?? [])
      setTotal(page.total ?? 0)
    } catch (cause) {
      setCapabilities([])
      setTotal(0)
      setError(cause instanceof Error ? cause.message : '能力市场加载失败')
    } finally {
      setLoading(false)
    }
  }, [activeCategoryId, keyword])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    // 筛选栏只展示确实有已上架能力的分类，与市场接口口径保持一致。
    fetchMarketCategories()
      .then((data) => setCategories(data.list ?? []))
      .catch(() => setCategories([]))
  }, [])

  const tabs = useMemo(
    () => [ALL_CATEGORIES, ...categories.map((item) => item.name)],
    [categories],
  )

  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-32 pt-12 md:px-10 md:pt-20">
      <div className="flex flex-col justify-between gap-8 md:flex-row md:items-end">
        <div>
          <p className="mb-5 text-sm text-[#c9f05b]">可组合的能力目录</p>
          <h1 className="max-w-5xl text-5xl font-medium leading-[.95] tracking-[-.07em] text-[#f4f4ef] md:text-7xl">
            找到一块<br />
            <span className="text-white/35">能立即使用的积木。</span>
          </h1>
        </div>
        <button
          onClick={() => navigate('/chat')}
          className="group flex items-center gap-3 self-start rounded-full bg-[#c9f05b] px-5 py-3 text-sm font-semibold text-[#11130f] md:self-end"
        >
          打开调试台
          <ArrowUpRight size={16} className="transition group-hover:translate-x-1 group-hover:-translate-y-1" />
        </button>
      </div>

      <div className="mt-20 flex flex-col gap-4 border-y border-white/10 py-5 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap gap-2">
          {tabs.map((item) => (
            <button
              key={item}
              onClick={() => setActiveCategory(item)}
              className={`rounded-full px-4 py-2 text-xs transition ${
                activeCategory === item
                  ? 'bg-white text-[#11130f]'
                  : 'border border-white/10 text-white/45 hover:border-[#c9f05b] hover:text-[#c9f05b]'
              }`}
            >
              {item}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-3 text-sm text-white/40">
          <Search size={16} />
          <input
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            placeholder="搜索能力"
            className="w-full bg-transparent outline-none placeholder:text-white/25 md:w-40"
          />
        </label>
      </div>

      {loading && (
        <p className="mt-10 flex items-center gap-2 text-sm text-white/40">
          <LoaderCircle size={15} className="animate-spin" /> 正在加载能力市场…
        </p>
      )}

      {!loading && error && (
        <div className="mt-10 flex items-center gap-4 rounded-2xl border border-white/10 bg-[#181c17] px-6 py-5 text-sm text-white/60">
          <span>{error}</span>
          <button onClick={() => void load()} className="flex items-center gap-2 text-[#c9f05b]">
            <RefreshCw size={14} /> 重试
          </button>
        </div>
      )}

      {!loading && !error && capabilities.length === 0 && (
        <p className="mt-10 text-sm text-white/35">没有符合条件的能力，换个分类或关键字试试。</p>
      )}

      {!loading && !error && capabilities.length > 0 && (
        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {capabilities.map((item, index) => (
            <button
              key={item.id}
              onClick={() => navigate('/chat')}
              className={`group relative min-h-[420px] overflow-hidden rounded-[1.75rem] bg-gradient-to-br ${TONES[index % TONES.length]} p-7 text-left`}
            >
              <img
                src={`https://picsum.photos/seed/${CARD_IMAGES[index % CARD_IMAGES.length]}/1000/800`}
                alt=""
                className="absolute inset-0 h-full w-full object-cover opacity-25 grayscale transition duration-700 group-hover:scale-105 group-hover:opacity-40"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-[#11130f]/90 via-[#11130f]/10 to-transparent" />
              <div className="relative flex h-full flex-col justify-between">
                <div className="flex items-center justify-between text-xs uppercase tracking-[.18em] text-white/70">
                  <span>{item.category_name}</span>
                  <SlidersHorizontal size={15} />
                </div>
                <div>
                  <div className="mb-4 flex items-end justify-between gap-3">
                    <h2 className="text-3xl font-medium tracking-[-.05em] text-white md:text-4xl">
                      {item.name}
                    </h2>
                    <ChevronRight size={22} className="transition group-hover:translate-x-2" />
                  </div>
                  <p className="max-w-md text-sm leading-6 text-white/65">
                    {item.description || '暂无描述'}
                  </p>
                  <div className="mt-7 flex gap-8 text-xs text-white/50">
                    <span>
                      每次 <strong className="ml-1 text-white">{item.price_per_call} 积分</strong>
                    </span>
                    <span>
                      编号 <strong className="ml-1 text-white">{item.code}</strong>
                    </span>
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      <p className="mt-8 text-xs text-white/30">
        数据来自 capability-service 市场接口，当前共 {total} 个已上架能力。
      </p>
    </section>
  )
}
