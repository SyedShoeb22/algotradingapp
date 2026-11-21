import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Poll an async loader on an interval. The loader is re-invoked
 * immediately by `refresh()`. Errors leave the previous data in place
 * and surface through `error` so pages can show degraded states.
 */
export function usePolling<T>(
  loader: () => Promise<T>,
  intervalMs = 5000,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const tick = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) setLoading(true)
    try {
      const result = await loaderRef.current()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    void tick(true)
    const id = window.setInterval(() => void tick(false), intervalMs)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick])

  return { data, error, loading, refresh: () => tick(false) }
}
