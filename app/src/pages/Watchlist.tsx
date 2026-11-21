import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePolling } from '@/hooks/usePolling'
import {
  addSymbol,
  fetchStatus,
  fetchWatchlist,
  importHistory,
  patchSymbol,
  removeSymbol,
  resolveTokens,
} from '@/lib/api'
import { formatINR, formatTime } from '@/lib/format'
import type { EngineStatus, WatchlistEntry } from '@/lib/types'
import { RefreshCw, Search, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

export default function Watchlist() {
  const navigate = useNavigate()
  const watchlist = usePolling<WatchlistEntry[]>(() => fetchWatchlist(), 8000)
  const status = usePolling<EngineStatus>(() => fetchStatus(), 8000)
  const [newSymbol, setNewSymbol] = useState('')
  const [capital, setCapital] = useState('100000')
  const [maxPosValue, setMaxPosValue] = useState('20000')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const prices = new Map(
    (status.data?.symbols ?? []).map((s) => [s.symbol, s.last_price]),
  )
  const tickTimes = new Map(
    (status.data?.symbols ?? []).map((s) => [s.symbol, s.last_tick_at]),
  )
  const capitals = new Map(
    (status.data?.symbols ?? []).map((s) => [s.symbol, s.account.initial_capital]),
  )

  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true)
    setFeedback(null)
    try {
      await action()
      setFeedback(message)
      await watchlist.refresh()
      await status.refresh()
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const handleAdd = () => {
    const symbol = newSymbol.trim().toUpperCase()
    if (!symbol) return
    void run(async () => {
      const result = await addSymbol({
        symbol,
        initial_capital: Number(capital) || 100000,
        max_position_value: Number(maxPosValue) || 20000,
        max_position_pct: 0.2,
      })
      setNewSymbol('')
      setFeedback(
        result.token
          ? `${result.symbol} added · token ${result.token} resolved`
          : `${result.symbol} added · token unresolved (run instruments download)`,
      )
    }, '')
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Watchlist</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Symbols are resolved to NSE instrument tokens automatically from the Angel One scrip
          master. Each stock gets its own isolated paper capital.
        </p>
      </div>

      <Card className="border-border bg-card p-4">
        <form
          className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            handleAdd()
          }}
        >
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              placeholder="NSE symbol (e.g. RELIANCE-EQ or RELIANCE)"
              aria-label="Symbol"
              className="h-11 pl-9"
              list="symbol-suggestions"
            />
          </div>
          <Input
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            placeholder="Paper capital ₹"
            aria-label="Paper capital"
            inputMode="numeric"
            className="h-11"
          />
          <Input
            value={maxPosValue}
            onChange={(e) => setMaxPosValue(e.target.value)}
            placeholder="Max position ₹"
            aria-label="Max position value"
            inputMode="numeric"
            className="h-11"
          />
          <Button type="submit" disabled={busy || !newSymbol.trim()} className="h-11">
            Add symbol
          </Button>
        </form>
        {feedback && <p className="mt-2 text-xs text-muted-foreground">{feedback}</p>}
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void run(() => resolveTokens(), 'Token resolution complete')}
          className="min-h-10"
        >
          <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden />
          Resolve tokens
        </Button>
        <p className="text-xs text-muted-foreground">
          Downloads/uses the scrip master to map every symbol to its broker token.
        </p>
      </div>

      <Card className="border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead className="hidden md:table-cell">Token</TableHead>
              <TableHead className="text-right">Last price</TableHead>
              <TableHead className="hidden sm:table-cell">Last tick</TableHead>
              <TableHead className="text-center">Active</TableHead>
              <TableHead className="hidden sm:table-cell text-right">Capital</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {watchlist.data?.map((entry) => {
              const price = prices.get(entry.symbol)
              return (
                <TableRow key={`${entry.symbol}-${entry.interval}`}>
                  <TableCell className="font-mono text-sm font-medium">{entry.symbol}</TableCell>
                  <TableCell className="hidden md:table-cell">
                    <span className="font-mono text-xs text-muted-foreground">
                      {entry.token ?? '—'}
                    </span>
                    <span
                      className={`ml-2 text-[10px] font-medium ${
                        entry.token_status === 'OK' ? 'text-up' : 'text-warn'
                      }`}
                    >
                      {entry.token_status}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular">
                    {price !== undefined && price !== null ? formatINR(price) : '—'}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell text-xs text-muted-foreground">
                    {formatTime(tickTimes.get(entry.symbol))}
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={entry.enabled}
                      onCheckedChange={(checked) =>
                        void run(
                          () => patchSymbol(entry.symbol, { enabled: checked }),
                          `${entry.symbol} ${checked ? 'enabled' : 'paused'}`,
                        )
                      }
                      aria-label={`Toggle ${entry.symbol}`}
                    />
                  </TableCell>
                  <TableCell className="hidden sm:table-cell text-right font-mono tabular text-xs text-muted-foreground">
                    {formatINR(capitals.get(entry.symbol) ?? 0, 0)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 text-primary hover:text-primary hover:bg-primary/10"
                        title="Paper Trade this stock"
                        onClick={() => navigate(`/trading?symbol=${encodeURIComponent(entry.symbol)}`)}
                      >
                        <Zap className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9"
                        title="Import historical candles"
                        onClick={() =>
                          void run(
                            () => importHistory(entry.symbol, 5),
                            `History import requested for ${entry.symbol}`,
                          )
                        }
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 text-down hover:text-down"
                        title="Remove symbol"
                        onClick={() =>
                          void run(() => removeSymbol(entry.symbol), `${entry.symbol} removed`)
                        }
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        {watchlist.data?.length === 0 && (
          <p className="p-6 text-sm text-muted-foreground">
            Watchlist is empty. Add your first symbol above.
          </p>
        )}
      </Card>
    </div>
  )
}
