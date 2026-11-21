import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export function StatCard({
  label,
  value,
  sub,
  tone = 'neutral',
  mono = true,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  tone?: 'neutral' | 'up' | 'down'
  mono?: boolean
}) {
  return (
    <Card className="border-border bg-card px-4 py-3.5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          'mt-1.5 text-xl font-semibold leading-none tabular',
          mono && 'font-mono',
          tone === 'up' && 'text-up',
          tone === 'down' && 'text-down',
        )}
      >
        {value}
      </p>
      {sub && <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  )
}
