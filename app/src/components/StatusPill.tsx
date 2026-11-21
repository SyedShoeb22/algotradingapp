import { cn } from '@/lib/utils'

const TONES: Record<string, string> = {
  green: 'bg-primary/15 text-primary',
  red: 'bg-down/15 text-down',
  amber: 'bg-warn/15 text-warn',
  gray: 'bg-muted text-muted-foreground',
}

export function StatusPill({
  tone,
  children,
  pulse = false,
  className,
}: {
  tone: keyof typeof TONES
  children: React.ReactNode
  pulse?: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex min-h-6 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-medium',
        TONES[tone],
        className,
      )}
    >
      {pulse && (
        <span className="relative flex h-1.5 w-1.5" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {children}
    </span>
  )
}

export function SignalPill({ signal }: { signal: string | null | undefined }) {
  if (!signal || signal === 'HOLD') {
    return <StatusPill tone="gray">{signal ?? '—'}</StatusPill>
  }
  return <StatusPill tone={signal === 'BUY' ? 'green' : 'red'}>{signal}</StatusPill>
}
