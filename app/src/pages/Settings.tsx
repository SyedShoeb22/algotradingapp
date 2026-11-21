import { StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { usePolling } from '@/hooks/usePolling'
import { fetchConfig, getMode, startEngine, stopEngine } from '@/lib/api'
import type { ConfigInfo } from '@/lib/types'
import { CheckCircle2, KeyRound, Pause, Play, ShieldAlert, XCircle } from 'lucide-react'
import { useState } from 'react'

const CLI_COMMANDS = [
  ['python3 -m app.main init-db', 'create or upgrade the database tables'],
  ['python3 -m app.main instruments', 'download the NSE scrip master (token map)'],
  ['python3 -m app.main resolve', 'resolve watchlist symbols to broker tokens'],
  ['python3 -m app.main import-history', 'back-fill recent candles for every symbol'],
  ['python3 -m app.main backtest -s SBIN-EQ', 'replay the strategy over stored candles'],
  ['python3 -m app.main run --simulate', 'headless engine with the simulated feed'],
  ['python3 -m app.main dashboard --simulate', 'engine + API + this dashboard on :8000'],
] as const

export default function Settings() {
  const config = usePolling<ConfigInfo>(() => fetchConfig(), 5000)
  const [busy, setBusy] = useState(false)
  const data = config.data

  const toggleEngine = async () => {
    setBusy(true)
    try {
      if (data?.running) await stopEngine()
      else await startEngine(true)
      await config.refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Engine mode, broker credentials and the built-in safety rails.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="border-border bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Play className="h-4 w-4 text-primary" aria-hidden />
              Engine
            </CardTitle>
            <CardDescription>
              The engine runs the collector, candle builder and strategy loops in one process.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <StatusPill tone={data?.running ? 'green' : 'gray'} pulse={data?.running}>
                {data ? data.mode : '…'}
              </StatusPill>
              <Button
                variant={data?.running ? 'outline' : 'default'}
                size="sm"
                disabled={busy || getMode() === 'demo'}
                title={getMode() === 'demo' ? 'Start the engine with: python3 -m app.main dashboard' : undefined}
                onClick={() => void toggleEngine()}
                className="min-h-10"
              >
                {data?.running ? (
                  <>
                    <Pause className="mr-1.5 h-4 w-4" aria-hidden /> Stop
                  </>
                ) : (
                  <>
                    <Play className="mr-1.5 h-4 w-4" aria-hidden /> Start (simulation)
                  </>
                )}
              </Button>
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-muted-foreground">Feed</dt>
                <dd className="font-mono">{data?.simulate ? 'simulated' : data?.running ? 'Angel One WebSocket' : '—'}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Execution</dt>
                <dd className="font-mono text-warn">paper only</dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card className="border-border bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="h-4 w-4 text-primary" aria-hidden />
              Angel One credentials
            </CardTitle>
            <CardDescription>
              Needed for live mode only. Copy <span className="font-mono">.env.example</span> to{' '}
              <span className="font-mono">.env</span> and fill in your API key, client code, PIN
              and TOTP secret.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 text-sm">
              {data?.angel_credentials_configured ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-up" aria-hidden />
                  <span>Configured — live mode available</span>
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4 text-down" aria-hidden />
                  <span>Missing — simulation mode only</span>
                </>
              )}
            </div>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              Then run <span className="font-mono">python3 -m app.main dashboard</span> (without{' '}
              <span className="font-mono">--simulate</span>) to trade on the live NSE feed. History
              import happens automatically at startup.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4 text-primary" aria-hidden />
            Safety rails
          </CardTitle>
          <CardDescription>Enforced by the engine on every evaluation cycle.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-x-8 gap-y-2 text-sm md:grid-cols-2">
            <li className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" aria-hidden />
              Duplicate-candle protection — each candle is claimed exactly once (database-enforced).
            </li>
            <li className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" aria-hidden />
              Stale-data check — candles older than {data?.risk.max_candle_age_minutes ?? 10} minutes
              are never traded on.
            </li>
            <li className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" aria-hidden />
              Per-stock position limit (value and % of cash), editable per symbol on the Watchlist.
            </li>
            <li className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" aria-hidden />
              Global cap of {data?.risk.global_max_open_positions ?? 5} open positions across all
              stocks.
            </li>
          </ul>
        </CardContent>
      </Card>

      <Card className="border-border bg-card">
        <CardHeader>
          <CardTitle className="text-base">CLI reference</CardTitle>
          <CardDescription>Every operation is also available from the terminal.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="space-y-2.5">
            {CLI_COMMANDS.map(([cmd, desc]) => (
              <div key={cmd} className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                <dt className="shrink-0 font-mono text-xs text-primary">$ {cmd}</dt>
                <dd className="text-xs text-muted-foreground">{desc}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}
