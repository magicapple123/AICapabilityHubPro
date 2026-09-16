import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import {
  createCategory,
  deleteCategory,
  fetchCategories,
  updateCategory,
  type CategoryItem,
  type CategoryStatus,
} from '@/api/capability'
import {
  EmptyNote,
  ErrorNote,
  Field,
  GhostButton,
  Loading,
  Modal,
  PrimaryButton,
  StatusTag,
} from '@/components/ui'

interface CategoryForm {
  name: string
  code: string
  sort: string
  status: CategoryStatus
}

const EMPTY_FORM: CategoryForm = { name: '', code: '', sort: '0', status: 'enabled' }
const CODE_PATTERN = /^[a-z0-9][a-z0-9-]*$/

/** 分类管理：新增 / 编辑 / 软删除，删除前由后端校验引用关系（2005）。 */
export function CategoryManager({ onChanged }: { onChanged?: () => void }) {
  const [categories, setCategories] = useState<CategoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<CategoryItem | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<CategoryForm>(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchCategories()
      setCategories(data.list ?? [])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '分类加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setFormError('')
    setCreating(true)
  }

  const openEdit = (item: CategoryItem) => {
    setForm({
      name: item.name,
      code: item.code,
      sort: String(item.sort),
      status: item.status,
    })
    setFormError('')
    setEditing(item)
  }

  const validate = (): number | null => {
    const name = form.name.trim()
    const code = form.code.trim()
    if (!name) {
      setFormError('分类名称不能为空')
      return null
    }
    if (!CODE_PATTERN.test(code)) {
      setFormError('编码只允许小写字母、数字和连字符，且以字母或数字开头')
      return null
    }
    const sort = Number(form.sort)
    if (!Number.isInteger(sort)) {
      setFormError('排序值必须是整数')
      return null
    }
    return sort
  }

  const submit = async () => {
    const sort = validate()
    if (sort === null) return
    try {
      const payload = { name: form.name.trim(), code: form.code.trim(), sort }
      if (editing) {
        await updateCategory(editing.id, { ...payload, status: form.status })
        setNotice(`分类「${payload.name}」已更新`)
      } else {
        await createCategory(payload)
        setNotice(`分类「${payload.name}」已创建`)
      }
      setCreating(false)
      setEditing(null)
      await load()
      onChanged?.()
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : '保存失败')
    }
  }

  const remove = async (item: CategoryItem) => {
    setError('')
    try {
      await deleteCategory(item.id)
      setNotice(`分类「${item.name}」已删除`)
      await load()
      onChanged?.()
    } catch (cause) {
      // 分类下仍有能力时后端返回 2005，直接把 message 呈现给运营。
      setError(cause instanceof Error ? cause.message : '删除失败')
    }
  }

  const formFooter = (
    <>
      <GhostButton
        onClick={() => {
          setCreating(false)
          setEditing(null)
        }}
      >
        取消
      </GhostButton>
      <PrimaryButton onClick={() => void submit()}>{editing ? '保存' : '创建'}</PrimaryButton>
    </>
  )

  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-medium text-white">分类管理</h2>
          <p className="mt-1 text-sm text-white/35">
            分类被能力引用时不可删除（返回 2005），需先迁移或删除其能力。
          </p>
        </div>
        <PrimaryButton onClick={openCreate}>
          <span className="flex items-center gap-2">
            <Plus size={15} /> 新建分类
          </span>
        </PrimaryButton>
      </div>

      {notice && <p className="mt-4 text-sm text-[#c9f05b]">{notice}</p>}

      <div className="mt-6">
        {loading && <Loading label="正在加载分类…" />}
        {!loading && error && <ErrorNote message={error} onRetry={() => void load()} />}
        {!loading && !error && categories.length === 0 && (
          <EmptyNote message="还没有分类，先创建一个再登记能力。" />
        )}
        {!loading && !error && categories.length > 0 && (
          <div className="divide-y divide-white/10">
            {categories.map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-4 py-4 text-sm"
              >
                <div className="min-w-[200px]">
                  <p className="text-white">{item.name}</p>
                  <p className="mt-1 font-mono text-xs text-white/40">
                    {item.code} · 排序 {item.sort}
                  </p>
                </div>
                <StatusTag value={item.status} />
                <div className="flex gap-2">
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
            ))}
          </div>
        )}
      </div>

      <Modal
        title={editing ? `编辑分类 · ${editing.name}` : '新建分类'}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
        footer={formFooter}
      >
        <div className="space-y-4">
          <Field
            label="分类名称"
            value={form.name}
            onChange={(value) => setForm({ ...form, name: value })}
            placeholder="语言处理"
          />
          <Field
            label="分类编码"
            value={form.code}
            onChange={(value) => setForm({ ...form, code: value })}
            placeholder="nlp"
          />
          <Field
            label="排序（越小越靠前）"
            value={form.sort}
            onChange={(value) => setForm({ ...form, sort: value })}
            placeholder="10"
          />
          {editing && (
            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/40">
                状态
              </span>
              <select
                value={form.status}
                onChange={(event) =>
                  setForm({ ...form, status: event.target.value as CategoryStatus })
                }
                className="w-full rounded-xl border border-white/12 bg-[#11130f] px-4 py-3 text-sm text-white outline-none focus:border-[#c9f05b]"
              >
                <option value="enabled">启用</option>
                <option value="disabled">停用</option>
              </select>
            </label>
          )}
          {formError && <p className="text-sm text-red-300">{formError}</p>}
        </div>
      </Modal>
    </div>
  )
}
