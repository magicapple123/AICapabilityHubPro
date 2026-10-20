import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

export function usePendingNavigation(pending: boolean, dirty: boolean) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    (pending || dirty) && (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search))
  useEffect(() => {
    if (!pending && !dirty) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [pending, dirty])
  return blocker
}
