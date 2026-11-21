import { StatusPill } from '@/components/StatusPill'
import { StatCard } from '@/components/StatCard'
import { StockTradeCard } from '@/components/StockTradeCard'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePolling } from '@/hooks/usePolling'
import { fetchAccounts, fetchTrades } from '@/lib/api'
import { formatINR, formatPnl, formatTime, pnlClass } from '@/lib/format'
import type { AccountRow, TradeRow } from '@/lib/types'
import { useState } from 'react'
import { useSearchParams } from 'react-router'

export default function Trading() {
  const [searchParams] = useSearchParams()
  const initialStock = searchParams.get('symbol') ?? 'TCS'
  const accounts = usePolling<AccountRow[]>(() => fetchAccounts(), 5000)
  const trades = usePolling<TradeRow[]>(() => fetchTrades(), 5000)
  const [symbolFilter, setSymbolFilter] = useState<string | null>(null)
  const [activeStock, setActiveStock] = useState<string>(initialStock)

  const rows = accounts.data ?? []
  const totals = rows.reduce(
    (acc, r) => {
      acc.capital += r.initial_capital
      acc.cash += r.cash
      acc.realized += r.realized_pnl
      acc.invested += r.position_value
      acc.unrealized += r.position?.unrealized_pnl ?? 0
      return acc
    },
    { capital: 0, cash: 0, realized: 0, invested: 0, unrealized: 0 },
  )

  const visibleTrades = (trades.data ?? []).filter(
    (t) => !symbolFilter || t.symbol === symbolFilter,
  )

  const handleRefresh = async () => {
    await Promise.all([accounts.refresh(), trades.refresh()])
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Paper Trading</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Select or enter any stock (e.g. TCS) to take paper trades. Every stock trades with its own
          capital, position limits and risk checks. No real orders are ever placed.
        </p>
      </div>

      {/* Stock Selection & Paper Trading Desk */}
      <StockTradeCard
        initialSymbol={activeStock}
        onTradeExecuted={() => void handleRefresh()}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard label="Total capital" value={formatINR(totals.capital, 0)} />
        <StatCard label="Cash" value={formatINR(totals.cash)} />
        <StatCard label="Invested" value={formatINR(totals.invested)} />
        <StatCard
          label="Unrealized P&L"
          value={formatPnl(totals.unrealized)}
          tone={totals.unrealized >= 0 ? 'up' : 'down'}
        />
        <StatCard
          label="Realized P&L"
          value={formatPnl(totals.realized)}
          tone={totals.realized >= 0 ? 'up' : 'down'}
        />
      </div>

      <section aria-label="Per-stock accounts">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Per-stock accounts
          </h2>
          <span className="text-xs text-muted-foreground">Click any row to trade or filter</span>
        </div>
        <Card className="mt-3 overflow-x-auto border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead className="text-right">Capital</TableHead>
                <TableHead className="text-right">Cash</TableHead>
                <TableHead className="text-right">Invested</TableHead>
                <TableHead className="hidden sm:table-cell">Position</TableHead>
                <TableHead className="text-right">Realized P&L</TableHead>
                <TableHead className="text-right">Unrealized P&L</TableHead>
                <TableHead className="text-center">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.symbol}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => {
                    setActiveStock(r.symbol)
                    setSymbolFilter(r.symbol === symbolFilter ? null : r.symbol)
                  }}
                >
                  <TableCell className="font-mono text-sm font-medium">{r.symbol}</TableCell>
                  <TableCell className="text-right font-mono tabular">{formatINR(r.initial_capital, 0)}</TableCell>
                  <TableCell className="text-right font-mono tabular">{formatINR(r.cash)}</TableCell>
                  <TableCell className="text-right font-mono tabular">{formatINR(r.position_value)}</TableCell>
                  <TableCell className="hidden sm:table-cell font-mono text-xs tabular">
                    {r.position
                      ? `${r.position.quantity} @ ${formatINR(r.position.average_price)}`
                      : '—'}
                  </TableCell>
                  <TableCell className={`text-right font-mono tabular ${pnlClass(r.realized_pnl)}`}>
                    {formatPnl(r.realized_pnl)}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono tabular ${pnlClass(r.position?.unrealized_pnl)}`}
                  >
                    {formatPnl(r.position?.unrealized_pnl)}
                  </TableCell>
                  <TableCell className="text-center">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setActiveStock(r.symbol)
                      }}
                      className="rounded bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                    >
                      Trade
                    </button>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && !accounts.loading && (
                <TableRow>
                  <TableCell colSpan={8} className="py-6 text-center text-sm text-muted-foreground">
                    No paper accounts yet — they are created automatically for each watchlist symbol.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
        {symbolFilter && (
          <p className="mt-2 text-xs text-muted-foreground">
            Trade filter: <span className="font-mono">{symbolFilter}</span>{' '}
            <button
              type="button"
              className="ml-2 underline underline-offset-2 hover:text-foreground"
              onClick={() => setSymbolFilter(null)}
            >
              clear
            </button>
          </p>
        )}
      </section>

      <section aria-label="Trade history">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Trade history
          </h2>
          <StatusPill tone="gray">{visibleTrades.length} trades</StatusPill>
        </div>
        <Card className="mt-3 overflow-x-auto border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="hidden sm:table-cell text-right">Value</TableHead>
                <TableHead className="text-right">P&L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleTrades.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="text-xs text-muted-foreground">{formatTime(t.executed_at)}</TableCell>
                  <TableCell className="font-mono text-xs font-medium">{t.symbol}</TableCell>
                  <TableCell>
                    <StatusPill tone={t.side === 'BUY' ? 'green' : 'red'}>{t.side}</StatusPill>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular">{t.quantity}</TableCell>
                  <TableCell className="text-right font-mono tabular">{formatINR(t.price)}</TableCell>
                  <TableCell className="hidden sm:table-cell text-right font-mono tabular">
                    {formatINR(t.trade_value, 0)}
                  </TableCell>
                  <TableCell className={`text-right font-mono tabular ${pnlClass(t.pnl)}`}>
                    {t.pnl !== null ? formatPnl(t.pnl) : '—'}
                  </TableCell>
                </TableRow>
              ))}
              {visibleTrades.length === 0 && !trades.loading && (
                <TableRow>
                  <TableCell colSpan={7} className="py-6 text-center text-sm text-muted-foreground">
                    No trades yet. Signals from the strategy will appear here automatically.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      </section>
    </div>
  )
}
