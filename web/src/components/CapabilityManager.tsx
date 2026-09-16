import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import {
  createCapability,
  deleteCapability,
  fetchCategories,
  fetchManageCapabilities,
  updateCapability,
  updateCapabilityStatus,
  type CapabilityManageItem,
  type CapabilityStatus,
  type CategoryItem,
} from '@/api/capability'
import {
  EmptyNote,
  ErrorNote,
  Field,
  GhostButton,
  Loading,
  Modal,
  Pager,
  PrimaryButton,
  StatusTag,
} from '@/components/ui'

const PAGE_SIZE = 8
const CODE_PATTERN = /^[a-z0-9][a-z0-9-]*$/

const STATUS_FILTERS: Array<{ value: '' | CapabilityStatus; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'online', label: '已上架' },
  { value: 'offline', label: '已下架' },
]

interface CapabilityForm {
  category_id: string
  name: string
  code: string
  service_name: string
  path: string
  price_per_call: string
  description: string
  param_schema: string
  status: CapabilityStatus
}

const EMPTY_FORM: CapabilityForm = {
  category_id: '',
  name: '',
  code: '',
  service_name: '',
  path: '',
  price_per_call: '0',
  description: '',
  param_schema: '',
  status: 'draft',
}

/** 能力登记与管理：登记后默认草稿，需通过上下架接口上架才会出现在市场。 */
export function CapabilityManager({ onChanged }: { onChanged?: () => void }) {
  const [categories, setCategories] = useState<CategoryItem[]>([])
  const [items, setItems] = useState<CapabilityManageItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<'' | CapabilityStatus>('')
  const [categoryId, setCategoryId] = useState('')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<CapabilityManageItem | null>(null)
  const [form, setForm] = useState<CapabilityForm>(EMPTY_FORM)
  const [formError, setFormError] = useState('')

  const loadCategories = useCallback(async () => {
    try {
      const data = await fetchCategories()
      setCategories(data.list ?? [])
    } catch {
      setCategories([])
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchManageCapabilities({
        status: status || undefined,
        category_id: categoryId ? Number(categoryId) : undefined,
        keyword: keyword.trim() || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      setItems(result.list ?? [])
      setTotal(result.total ?? 0)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '能力列表加载失败')
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [status, categoryId, keyword, page])

  useEffect(() => {
    void loadCategories()
  }, [loadCategories])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setPage(1)
  }, [status, categoryId, keyword])

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setFormError('')
    setCreating(true)
  }

  const openEdit = (item: CapabilityManageItem) => {
    setForm({
      category_id: String(item.category_id),
      name: item.name,
      code: item.code,
      service_name: item.service_name,
      path: item.path,
      price_per_call: String(item.price_per_call),
      description: item.description,
      param_schema: item.param_schema ? JSON.stringify(item.param_schema, null, 2) : '',
      status: item.status,
    })
    setFormError('')
    setEditing(item)
  }

  const buildPayload = () => {
    if (!form.category_id) {
      setFormError('请选择所属分类')
      return null
    }
    if (!form.name.trim()) {
      setFormError('能力名称不能为空')
      return null
    }
    if (!CODE_PATTERN.test(form.code.trim())) {
      setFormError('编码只允许小写字母、数字和连字符，且以字母或数字开头')
      return null
    }
    if (!form.service_name.trim() || !form.path.trim()) {
      setFormError('服务名与调用路径不能为空')
      return null
    }
    const price = Number(form.price_per_call)
    if (!Number.isInteger(price) || price < 0) {
      setFormError('单价必须是非负整数（积分数）')
      return null
    }
    let paramSchema: Record<string, unknown> | null = null
    if (form.param_schema.trim()) {
      try {
        const parsed: unknown = JSON.parse(form.param_schema)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
          setFormError('参数 Schema 必须是 JSON 对象')
          return null
        }
        paramSchema = parsed as Record<string, unknown>
      } catch {
        setFormError('参数 Schema 不是合法 JSON')
        return null
      }
    }
    return {
      category_id: Number(form.category_id),
      name: form.name.trim(),
      code: form.code.trim(),
      service_name: form.service_name.trim(),
      path: form.path.trim(),
      price_per_call: price,
      description: form.description.trim(),
      param_schema: paramSchema,
    }
  }

  const submit = async () => {
    const payload = buildPayload()
    if (!payload) return
    try {
      if (editing) {
        await updateCapability(editing.id, payload)
        setNotice(`能力「${payload.name}」已更新`)
      } else {
        await createCapability({ ...payload, status: form.status })
        setNotice(`能力「${payload.name}」已登记（${form.status === 'online' ? '已上架' : '草稿'}）`)
      }
      setCreating(false)
      setEditing(null)
      await load()
      onChanged?.()
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : '保存失败')
    }
  }

  const switchStatus = async (item: CapabilityManageItem) => {
    const next: CapabilityStatus = item.status === 'online' ? 'offline' : 'online'
    setNotice('')
    try {
      await updateCapabilityStatus(item.id, next)
      setNotice(`能力「${item.name}」已${next === 'online' ? '上架' : '下架'}`)
      await load()
      onChanged?.()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '状态更新失败')
    }
  }

  const remove = async (item: CapabilityManageItem) => {
    setNotice('')
    try {
      await deleteCapability(item.id)
      setNotice(`能力「${item.name}」已删除`)
      await load()
      onChanged?.()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '删除失败')
    }
  }

  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-medium text-white">能力管理</h2>
          <p className="mt-1 text-sm text-white/35">
            登记服务名、路径与单价；市场只展示 online 能力，编辑不改状态。
          </p>
        </div>
        <PrimaryButton onClick={openCreate}>
          <span className="flex items-center gap-2">
            <Plus size={15} /> 登记能力
          </span>
        </PrimaryButton>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2">
          {STATUS_FILTERS.map((option) => (
            <button
              key={option.value || 'all'}
              onClick={() => setStatus(option.value)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                status === option.value
                  ? 'bg-white text-[#11130f]'
                  : 'border border-white/10 text-white/45 hover:border-[#c9f05b] hover:text-[#c9f05b]'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <select
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          className="rounded-full border border-white/12 bg-[#11130f] px-4 py-2 text-xs text-white/70 outline-none focus:border-[#c9f05b]"
        >
          <option value="">全部分类</option>
          {categories.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索能力名称或编码"
          className="min-w-[180px] flex-1 rounded-full border border-white/12 bg-[#11130f] px-4 py-2 text-xs text-white outline-none placeholder:text-white/25 focus:border-[#c9f05b]"
        />
      </div>

      {notice && <p className="mt-4 text-sm text-[#c9f05b]">{notice}</p>}

      <div className="mt-6">
        {loading && <Loading label="正在加载能力列表…" />}
        {!loading && error && <ErrorNote message={error} onRetry={() => void load()} />}
        {!loading && !error && items.length === 0 && (
          <EmptyNote message="没有符合条件的能力。" />
        )}
        {!loading && !error && items.length > 0 && (
          <div className="divide-y divide-white/10">
            {items.map((item) => (
              <div key={item.id} className="py-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-[260px] flex-1">
                    <div className="flex items-center gap-3">
                      <p className="text-white">{item.name}</p>
                      <StatusTag value={item.status} />
                    </div>
                    <p className="mt-1 font-mono text-xs text-white/40">
                      {item.code} · {item.category_name}
                    </p>
                    <p className="mt-1 text-xs text-white/35">
                      {item.service_name} {item.path} · 单价 {item.price_per_call} 积分
                    </p>
                    {item.description && (
                      <p className="mt-2 max-w-2xl text-xs leading-5 text-white/45">
                        {item.description}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <GhostButton onClick={() => void switchStatus(item)}>
                      {item.status === 'online' ? '下架' : '上架'}
                    </GhostButton>
                    <GhostButton onClick={() => openEdit(item)}>
                      <span className="flex items-center gap-1">
                        <Pencil size={13} /> 编辑
                      </span>
                    </GhostButton>
                    <GhostButton onClick={() => void remove(item)}>
                      <span className="flex items-center gap-1">
                        <Trash2 size={13} /> 删除
                      </span>
                    </GhostButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-6">
        <Pager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
      </div>

      <Modal
        title={editing ? `编辑能力 · ${editing.name}` : '登记能力'}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
        footer={
          <>
            <GhostButton
              onClick={() => {
                setCreating(false)
                setEditing(null)
              }}
            >
              取消
            </GhostButton>
            <PrimaryButton onClick={() => void submit()}>{editing ? '保存' : '登记'}</PrimaryButton>
          </>
        }
      >
        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <label className="block">
            <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/40">
              所属分类
            </span>
            <select
              value={form.category_id}
              onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              className="w-full rounded-xl border border-white/12 bg-[#11130f] px-4 py-3 text-sm text-white outline-none focus:border-[#c9f05b]"
            >
              <option value="">请选择分类</option>
              {categories.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </select>
          </label>
          <Field
            label="能力名称"
            value={form.name}
            onChange={(value) => setForm({ ...form, name: value })}
            placeholder="多轮对话"
          />
          <Field
            label="能力编码"
            value={form.code}
            onChange={(value) => setForm({ ...form, code: value })}
            placeholder="chat-completions"
          />
          <Field
            label="服务名"
            value={form.service_name}
            onChange={(value) => setForm({ ...form, service_name: value })}
            placeholder="ai-chat-service"
          />
          <Field
            label="调用路径"
            value={form.path}
            onChange={(value) => setForm({ ...form, path: value })}
            placeholder="/api/chat/completions"
          />
          <Field
            label="单价（积分 / 次）"
            value={form.price_per_call}
            onChange={(value) => setForm({ ...form, price_per_call: value })}
            placeholder="5"
          />
          <Field
            label="能力描述"
            value={form.description}
            onChange={(value) => setForm({ ...form, description: value })}
            placeholder="多轮对话与文本生成"
          />
          <label className="block">
            <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/40">
              参数 Schema（JSON，可留空）
            </span>
            <textarea
              value={form.param_schema}
              onChange={(event) => setForm({ ...form, param_schema: event.target.value })}
              rows={4}
              placeholder='{"type": "object", "properties": {}}'
              className="w-full rounded-xl border border-white/12 bg-[#11130f] px-4 py-3 font-mono text-xs text-white outline-none placeholder:text-white/25 focus:border-[#c9f05b]"
            />
          </label>
          {!editing && (
            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/40">
                初始状态
              </span>
              <select
                value={form.status}
                onChange={(event) =>
                  setForm({ ...form, status: event.target.value as CapabilityStatus })
                }
                className="w-full rounded-xl border border-white/12 bg-[#11130f] px-4 py-3 text-sm text-white outline-none focus:border-[#c9f05b]"
              >
                <option value="draft">草稿（不上架）</option>
                <option value="online">直接上架</option>
              </select>
            </label>
          )}
          {formError && <p className="text-sm text-red-300">{formError}</p>}
        </div>
      </Modal>
    </div>
  )
}
