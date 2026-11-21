import { getMode } from '@/lib/api'
import { useEffect, useState } from 'react'

/** Shown only when the dashboard cannot reach a running engine. */
export function DemoBanner() {
  const [demo, setDemo] = useState(false)

  useEffect(() => {
    const check = () => setDemo(getMode() === 'demo')
    check()
    const id = window.setInterval(check, 2000)
    return () => window.clearInterval(id)
  }, [])

  if (!demo) return null

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/40 bg-warn/10 px-3 py-1 text-[11px] font-medium text-warn">
      <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden />
      Demo data — engine not connected
    </span>
  )
}
