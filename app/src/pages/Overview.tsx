import { SignalPill, StatusPill } from '@/components/StatusPill'
import { StatCard } from '@/components/StatCard'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { usePolling } from '@/hooks/usePolling'
import { fetchEvents, fetchStatus, getMode, startEngine, stopEngine } from '@/lib/api'
import { formatClock, formatINR, formatPnl, formatTime, pnlClass } from '@/lib/format'
import type { EngineStatus } from '@/lib/types'
import { Pause, Play, Zap } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

export default function Overview() {
  const navigate = useNavigate()
  const status = usePolling<EngineStatus>(() => fetchStatus(), 5000)
  const events = usePolling(() => fetchEvents(), 6000)
  const [busy, setBusy] = useState(false)

  const data = status.data

  const totals = data?.symbols.reduce(
    (acc, s) => {
      acc.cash += s.account.cash ?? 0
      acc.invested += s.position ? s.position.quantity * (s.position.last_price ?? s.position.average_price ?? 0) : 0
      acc.realized += s.account.realized_pnl
      acc.open += s.position && s.position.quantity > 0 ? 1 : 0
      acc.unrealized += s.position?.unrealized_pnl ?? 0
      return acc
    },
    { cash: 0, invested: 0, realized: 0, open: 0, unrealized: 0 },
  )

  const handleStartStop = async () => {
    setBusy(true)
    try {
      if (data?.running) await stopEngine()
      else await startEngine(true)
      await status.refresh()
      await events.refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
        <StatusPill
          tone={data?.running ? 'green' : 'gray'}
          pulse={data?.running}
        >
          {data?.running ? data.mode : 'STOPPED'}
        </StatusPill>
        <StatusPill tone={data?.collector.connected ? 'green' : 'red'}>
          collector: {data?.collector.type ?? '—'}
          {data?.running ? (data.collector.connected ? ' · up' : ' · down') : ''}
        </StatusPill>
        {data?.running && (
          <span className="text-xs text-muted-foreground">
            uptime {formatClock(data.uptime_seconds)} · {data.collector.ticks_written.toLocaleString('en-IN')} ticks written
          </span>
        )}
        <Button
          size="sm"
          variant={data?.running ? 'outline' : 'default'}
          disabled={busy || getMode() === 'demo'}
          title={getMode() === 'demo' ? 'Start the engine with: python3 -m app.main dashboard' : undefined}
          onClick={handleStartStop}
          className="ml-auto min-h-10"
        >
          {data?.running ? <Pause className="mr-1.5 h-4 w-4" aria-hidden /> : <Play className="mr-1.5 h-4 w-4" aria-hidden />}
          {data?.running ? 'Stop engine' : 'Start engine (sim)'}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard label="Cash" value={formatINR(totals?.cash)} />
        <StatCard label="Invested" value={formatINR(totals?.invested)} />
        <StatCard
          label="Unrealized P&L"
          value={formatPnl(totals?.unrealized)}
          tone={totals && totals.unrealized >= 0 ? 'up' : 'down'}
        />
        <StatCard
          label="Realized P&L"
          value={formatPnl(totals?.realized)}
          tone={totals && totals.realized >= 0 ? 'up' : 'down'}
        />
        <StatCard label="Open positions" value={totals?.open ?? 0} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-3 lg:col-span-2" aria-label="Watchlist symbols">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Symbols
          </h2>
          {status.loading && !data ? (
            <Card className="p-6 text-sm text-muted-foreground">Loading engine status…</Card>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {data?.symbols.map((s) => (
                <Card key={s.symbol} className="border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-mono text-sm font-semibold">{s.symbol}</p>
                      <p className="text-[11px] text-muted-foreground">
                        {s.exchange} · {s.interval}
                      </p>
                    </div>
                    <SignalPill signal={s.last_signal} />
                  </div>

                  <p className="mt-3 font-mono text-2xl font-semibold tabular">
                    {s.last_price !== null ? formatINR(s.last_price) : '—'}
                  </p>

                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                    <div>
                      <dt className="text-muted-foreground">Cash</dt>
                      <dd className="font-mono tabular">{formatINR(s.account.cash, 0)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Candle age</dt>
                      <dd className="font-mono tabular">
                        {s.last_candle_age_min !== null ? `${s.last_candle_age_min} min` : '—'}
                      </dd>
                    </div>
                    {s.position && (
                      <>
                        <div>
                          <dt className="text-muted-foreground">Position</dt>
                          <dd className="font-mono tabular">
                            {s.position.quantity} @ {formatINR(s.position.average_price)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground">Unrealized</dt>
                          <dd className={pnlClass(s.position.unrealized_pnl) + ' font-mono tabular'}>
                            {formatPnl(s.position.unrealized_pnl)}
                          </dd>
                        </div>
                      </>
                    )}
                  </dl>

                  {s.last_evaluation_reason && (
                    <p className="mt-3 line-clamp-1 text-[11px] text-muted-foreground">
                      {s.last_evaluation}
                      {s.last_evaluation_reason ? ` · ${s.last_evaluation_reason}` : ''}
                    </p>
                  )}

                  <div className="mt-3 pt-3 border-t border-border/50 flex justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => navigate(`/trading?symbol=${encodeURIComponent(s.symbol)}`)}
                      className="h-8 text-xs font-medium"
                    >
                      <Zap className="mr-1.5 h-3.5 w-3.5 text-amber-500" />
                      Paper Trade
                    </Button>
                  </div>
                </Card>
              ))}
              {data && data.symbols.length === 0 && (
                <Card className="p-6 text-sm text-muted-foreground sm:col-span-2">
                  No symbols in the watchlist yet. Add one from the Watchlist page.
                </Card>
              )}
            </div>
          )}
        </section>

        <section aria-label="System events">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Event log
          </h2>
          <Card className="mt-3 max-h-[480px] overflow-y-auto scrollbar-thin p-2">
            <ul className="space-y-0.5">
              {events.data?.map((e) => (
                <li key={e.id} className="rounded-md px-2.5 py-2 hover:bg-muted/50">
                  <div className="flex items-center gap-2">
                    <StatusPill
                      tone={e.level === 'ERROR' ? 'red' : e.level === 'WARN' ? 'amber' : 'gray'}
                      className="shrink-0"
                    >
                      {e.source}
                    </StatusPill>
                    <time className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                      {formatTime(e.created_at)}
                    </time>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-foreground/90">{e.message}</p>
                </li>
              ))}
              {events.data?.length === 0 && (
                <li className="px-3 py-4 text-sm text-muted-foreground">No events yet.</li>
              )}
            </ul>
          </Card>
          <Separator className="my-4" />
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Duplicate-candle protection, stale-data checks and risk limits are enforced on every
            evaluation cycle. Rejected actions are logged here.
          </p>
        </section>
      </div>
    </div>
  )
}
