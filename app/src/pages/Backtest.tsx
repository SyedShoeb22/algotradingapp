import { EquityChart } from '@/components/CandleChart'
import { StatusPill } from '@/components/StatusPill'
import { StatCard } from '@/components/StatCard'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fetchBacktest, fetchWatchlist } from '@/lib/api'
import { formatINR, formatPct, formatPnl, formatTime, pnlClass } from '@/lib/format'
import type { BacktestResult, WatchlistEntry } from '@/lib/types'
import { usePolling } from '@/hooks/usePolling'
import { Play } from 'lucide-react'
import { useEffect, useState } from 'react'

export default function Backtest() {
  const watchlist = usePolling<WatchlistEntry[]>(() => fetchWatchlist(), 30000)
  const [symbol, setSymbol] = useState('')
  const [days, setDays] = useState('30')
  const [capital, setCapital] = useState('100000')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!symbol && watchlist.data && watchlist.data.length > 0) {
      setSymbol(watchlist.data[0].symbol)
    }
  }, [watchlist.data, symbol])

  const run = async () => {
    if (!symbol) return
    setRunning(true)
    setError(null)
    try {
      const data = await fetchBacktest(symbol, Number(days) || 30)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  const wins = result?.trades.filter((t) => t.side === 'SELL' && (t.pnl ?? 0) > 0).length ?? 0
  const losses = result?.trades.filter((t) => t.side === 'SELL' && (t.pnl ?? 0) <= 0).length ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Backtest</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Walk-forward replay of the live strategy rules (EMA 20/50 + RSI 14 + MACD) over stored
          candles, with the same position-sizing and risk limits as the paper engine.
        </p>
      </div>

      <Card className="border-border bg-card p-4">
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_120px_160px_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            void run()
          }}
        >
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="h-11 font-mono" aria-label="Symbol">
              <SelectValue placeholder="Symbol" />
            </SelectTrigger>
            <SelectContent>
              {watchlist.data?.map((w) => (
                <SelectItem key={w.symbol} value={w.symbol} className="font-mono">
                  {w.symbol}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={days}
            onChange={(e) => setDays(e.target.value)}
            inputMode="numeric"
            aria-label="Days of history"
            className="h-11 font-mono"
          />
          <Input
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            inputMode="numeric"
            aria-label="Capital"
            className="h-11 font-mono"
          />
          <Button type="submit" disabled={running || !symbol} className="h-11">
            <Play className="mr-1.5 h-4 w-4" aria-hidden />
            {running ? 'Running…' : 'Run backtest'}
          </Button>
        </form>
        {error && <p className="mt-2 text-xs text-down">{error}</p>}
      </Card>

      {result && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatCard
              label="Return"
              value={formatPct(result.total_return_pct)}
              tone={result.total_return_pct >= 0 ? 'up' : 'down'}
            />
            <StatCard label="Final equity" value={formatINR(result.final_equity)} />
            <StatCard label="Buys" value={result.buy_signals} />
            <StatCard label="Sells" value={result.sell_signals} />
            <StatCard label="Winners" value={wins} tone={wins >= losses ? 'up' : 'down'} />
            <StatCard label="Losers" value={losses} tone={losses > wins ? 'down' : 'up'} />
          </div>

          <Card className="border-border bg-card p-3">
            <h2 className="mb-2 px-1 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Equity curve
            </h2>
            <EquityChart points={result.equity_curve} height={300} />
          </Card>

          <Card className="border-border bg-card">
            <div className="flex items-center justify-between px-4 pt-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Trades
              </h2>
              <StatusPill tone="gray">{result.trades.length}</StatusPill>
            </div>
            <div className="max-h-80 overflow-y-auto scrollbar-thin">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...result.trades].reverse().map((t, i) => (
                    <TableRow key={`${t.time}-${i}`}>
                      <TableCell className="text-xs text-muted-foreground">{formatTime(t.time)}</TableCell>
                      <TableCell>
                        <StatusPill tone={t.side === 'BUY' ? 'green' : 'red'}>{t.side}</StatusPill>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular">{t.quantity}</TableCell>
                      <TableCell className="text-right font-mono tabular">{formatINR(t.price)}</TableCell>
                      <TableCell className={`text-right font-mono tabular ${pnlClass(t.pnl)}`}>
                        {t.pnl !== undefined ? formatPnl(t.pnl) : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </>
      )}

      {!result && !running && (
        <Card className="p-6 text-sm text-muted-foreground">
          Pick a symbol and run a backtest. Results include an equity curve and per-trade P&L.
        </Card>
      )}
    </div>
  )
}
