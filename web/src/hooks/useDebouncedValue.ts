import { useEffect, useState } from 'react'

export function useDebouncedValue<T>(value: T, milliseconds = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), milliseconds)
    return () => window.clearTimeout(timer)
  }, [value, milliseconds])
  return debounced
}
