import { useCallback, useEffect, useState } from 'react'

/** Ignore stale responses after a dependency change or unmount. */
export function useAsyncResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion((value) => value + 1), [])
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void load().then((value) => { if (active) setData(value) })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '加载失败，请稍后重试') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [load, version])
  return { data, error, loading, reload }
}
