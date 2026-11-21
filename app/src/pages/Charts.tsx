import { CandleChart } from '@/components/CandleChart'
import { SignalPill, StatusPill } from '@/components/StatusPill'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePolling } from '@/hooks/usePolling'
import { fetchCandles, fetchIndicators, fetchWatchlist } from '@/lib/api'
import { formatINR, formatTime } from '@/lib/format'
import type { CandleRow, IndicatorRow, WatchlistEntry } from '@/lib/types'
import { Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

export default function Charts() {
  const navigate = useNavigate()
  const watchlist = usePolling<WatchlistEntry[]>(() => fetchWatchlist(), 30000)
  const [symbol, setSymbol] = useState<string>('')

  useEffect(() => {
    if (!symbol && watchlist.data && watchlist.data.length > 0) {
      setSymbol(watchlist.data[0].symbol)
    }
  }, [watchlist.data, symbol])

  const candles = usePolling<CandleRow[]>(
    () => (symbol ? fetchCandles(symbol) : Promise.resolve([])),
    8000,
    [symbol],
  )
  const indicators = usePolling<IndicatorRow[]>(
    () => (symbol ? fetchIndicators(symbol) : Promise.resolve([])),
    8000,
    [symbol],
  )

  const latest = indicators.data?.[indicators.data.length - 1]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Charts</h1>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-10 w-48 font-mono text-sm" aria-label="Symbol">
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
        {symbol && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/trading?symbol=${encodeURIComponent(symbol)}`)}
            className="h-10 text-xs font-medium"
          >
            <Zap className="mr-1.5 h-3.5 w-3.5 text-amber-500" />
            Trade {symbol.replace(/-EQ$/, '')}
          </Button>
        )}
        {latest && (
          <div className="ml-auto flex items-center gap-3">
            <span className="font-mono text-lg font-semibold tabular">{formatINR(latest.close)}</span>
            <SignalPill signal={latest.signal} />
          </div>
        )}
      </div>

      <Card className="border-border bg-card p-3">
        <div className="mb-2 flex flex-wrap items-center gap-4 px-1 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: '#5aa2ff' }} aria-hidden />
            EMA 20
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: '#f5a524' }} aria-hidden />
            EMA 50
          </span>
          <span className="ml-auto hidden sm:block">5-minute candles · signals marked on chart</span>
        </div>
        <CandleChart candles={candles.data ?? []} indicators={indicators.data ?? []} height={430} />
      </Card>

      {latest && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card className="border-border bg-card px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">RSI (14)</p>
            <p
              className={`mt-1 font-mono text-lg font-semibold tabular ${
                latest.rsi_14 === null
                  ? 'text-muted-foreground'
                  : latest.rsi_14 > 70
                    ? 'text-down'
                    : latest.rsi_14 < 30
                      ? 'text-up'
                      : ''
              }`}
            >
              {latest.rsi_14 ?? '—'}
            </p>
          </Card>
          <Card className="border-border bg-card px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">MACD</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular">
              {latest.macd ?? '—'}
            </p>
          </Card>
          <Card className="border-border bg-card px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">MACD signal</p>
            <p className="mt-1 font-mono text-lg font-semibold tabular">
              {latest.macd_signal ?? '—'}
            </p>
          </Card>
          <Card className="border-border bg-card px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Signal basis</p>
            <p className="mt-1 truncate text-xs">{latest.reason}</p>
          </Card>
        </div>
      )}

      <section aria-label="Recent evaluations">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Recent evaluations
        </h2>
        <Card className="mt-3 max-h-72 overflow-y-auto scrollbar-thin border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candle (IST)</TableHead>
                <TableHead className="text-right">Close</TableHead>
                <TableHead className="hidden sm:table-cell text-right">RSI</TableHead>
                <TableHead className="text-center">Signal</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...(indicators.data ?? [])].reverse().slice(0, 40).map((r) => (
                <TableRow key={r.time}>
                  <TableCell className="text-xs text-muted-foreground">{formatTime(r.time)}</TableCell>
                  <TableCell className="text-right font-mono tabular">{formatINR(r.close)}</TableCell>
                  <TableCell className="hidden sm:table-cell text-right font-mono tabular">
                    {r.rsi_14 ?? '—'}
                  </TableCell>
                  <TableCell className="text-center">
                    {r.signal === 'HOLD' ? (
                      <StatusPill tone="gray">HOLD</StatusPill>
                    ) : (
                      <SignalPill signal={r.signal} />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </section>
    </div>
  )
}
