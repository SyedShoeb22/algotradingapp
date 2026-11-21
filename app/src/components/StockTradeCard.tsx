import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { executePaperTrade, fetchPopularSymbols, fetchStockQuote, POPULAR_NSE_SYMBOLS } from '@/lib/api'
import { formatINR, formatPnl, pnlClass } from '@/lib/format'
import type { PopularStock, StockQuote } from '@/lib/types'
import { ArrowDownRight, ArrowUpRight, CheckCircle2, ChevronRight, RefreshCw, Search, Sparkles, TrendingUp, Zap } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

interface StockTradeCardProps {
  initialSymbol?: string
  onTradeExecuted?: () => void
}

export function StockTradeCard({ initialSymbol = 'TCS', onTradeExecuted }: StockTradeCardProps) {
  const navigate = useNavigate()
  const [symbolInput, setSymbolInput] = useState(initialSymbol)
  const [selectedStock, setSelectedStock] = useState<string>(initialSymbol.toUpperCase())
  const [popularList, setPopularList] = useState<PopularStock[]>(POPULAR_NSE_SYMBOLS)
  const [quote, setQuote] = useState<StockQuote | null>(null)
  const [loadingQuote, setLoadingQuote] = useState(false)
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [quantity, setQuantity] = useState('5')
  const [customPrice, setCustomPrice] = useState('')
  const [useMarketPrice, setUseMarketPrice] = useState(true)
  const [enableAutoTrading, setEnableAutoTrading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string; details?: string } | null>(null)

  // Fetch popular symbols on mount
  useEffect(() => {
    let mounted = true
    fetchPopularSymbols()
      .then((symbols) => {
        if (mounted && symbols.length > 0) setPopularList(symbols)
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  // Update selected stock if initialSymbol prop changes
  useEffect(() => {
    if (initialSymbol) {
      const clean = initialSymbol.trim().toUpperCase()
      setSelectedStock(clean)
      setSymbolInput(clean.replace(/-EQ$/, ''))
    }
  }, [initialSymbol])

  // Load quote whenever selectedStock changes
  const loadQuote = async (stock: string) => {
    setLoadingQuote(true)
    try {
      const q = await fetchStockQuote(stock)
      setQuote(q)
    } catch {
      // Handled gracefully
    } finally {
      setLoadingQuote(false)
    }
  }

  useEffect(() => {
    if (selectedStock) {
      void loadQuote(selectedStock)
    }
  }, [selectedStock])

  // Derived stock details from popular list or quote
  const matchedPopular = useMemo(() => {
    const raw = selectedStock.replace(/-EQ$/, '')
    return popularList.find((p) => p.symbol === raw || p.full_symbol === selectedStock)
  }, [selectedStock, popularList])

  const effectivePrice = useMemo(() => {
    if (!useMarketPrice && Number(customPrice) > 0) {
      return Number(customPrice)
    }
    return quote?.price ?? matchedPopular?.anchor ?? 4150.0
  }, [useMarketPrice, customPrice, quote?.price, matchedPopular?.anchor])

  const numQty = Math.max(1, parseInt(quantity, 10) || 1)
  const estTradeValue = Math.round(numQty * effectivePrice * 100) / 100
  const availableCash = quote?.account.cash ?? 100000
  const positionQty = quote?.position?.quantity ?? 0

  const handleSelectStock = (sym: string) => {
    const clean = sym.trim().toUpperCase()
    setSelectedStock(clean)
    setSymbolInput(clean.replace(/-EQ$/, ''))
    setFeedback(null)
  }

  const handleApplyInput = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const clean = symbolInput.trim().toUpperCase()
    if (!clean) return
    setSelectedStock(clean)
    setFeedback(null)
  }

  const handleMaxBuy = () => {
    if (effectivePrice > 0 && availableCash > 0) {
      const maxShares = Math.max(1, Math.floor(availableCash / effectivePrice))
      setQuantity(String(maxShares))
      setSide('BUY')
    }
  }

  const handleMaxSell = () => {
    if (positionQty > 0) {
      setQuantity(String(positionQty))
      setSide('SELL')
    }
  }

  const handleExecuteTrade = async () => {
    if (numQty <= 0) return
    setBusy(true)
    setFeedback(null)

    try {
      const result = await executePaperTrade({
        symbol: selectedStock,
        side,
        quantity: numQty,
        price: useMarketPrice ? undefined : effectivePrice,
        enable_auto_trading: enableAutoTrading,
      })

      setFeedback({
        type: 'success',
        message: `Paper Trade Executed: ${result.trade.side} ${result.trade.quantity} ${result.trade.symbol} @ ${formatINR(result.trade.price)}`,
        details: `Trade value: ${formatINR(result.trade.trade_value)} · Paper cash: ${formatINR(result.account.cash)} · Strategy: ${result.trade.strategy}`,
      })

      // Reload quote and notify parent
      await loadQuote(selectedStock)
      if (onTradeExecuted) {
        onTradeExecuted()
      }
    } catch (error) {
      setFeedback({
        type: 'error',
        message: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="overflow-hidden border-border bg-gradient-to-b from-card to-card/90 shadow-md">
      {/* Header */}
      <div className="border-b border-border/80 bg-muted/30 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Zap className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-semibold tracking-tight">Stock Selection & Paper Trading</h2>
              <p className="text-xs text-muted-foreground">
                Enter or select any NSE stock (e.g. <span className="font-semibold text-foreground">TCS</span>) to take paper trades with zero risk.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
              <Sparkles className="h-3 w-3" />
              Paper Mode Active
            </span>
          </div>
        </div>

        {/* Stock Search & Selection Bar */}
        <div className="mt-4 flex flex-col gap-3">
          <form onSubmit={handleApplyInput} className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                placeholder="Enter stock name (e.g. TCS, RELIANCE, INFY, SBIN)..."
                className="h-10 pl-9 font-mono uppercase"
              />
            </div>
            <Button type="submit" variant="secondary" className="h-10 px-4 font-medium">
              Select Stock
            </Button>
          </form>

          {/* Popular Stock Quick Badges */}
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-[11px] font-medium text-muted-foreground">Quick Select:</span>
            {popularList.slice(0, 8).map((stk) => {
              const isSelected =
                selectedStock === stk.symbol ||
                selectedStock === stk.full_symbol ||
                selectedStock.replace(/-EQ$/, '') === stk.symbol
              return (
                <button
                  key={stk.symbol}
                  type="button"
                  onClick={() => handleSelectStock(stk.symbol)}
                  className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-mono font-medium transition-all ${
                    isSelected
                      ? 'bg-primary text-primary-foreground shadow-sm ring-1 ring-primary'
                      : 'border border-border/80 bg-background/60 hover:bg-accent hover:text-accent-foreground'
                  }`}
                >
                  {stk.symbol === 'TCS' && <Zap className="h-3 w-3 text-amber-400" />}
                  {stk.symbol}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Main Trade Section */}
      <div className="p-5">
        <div className="grid gap-6 lg:grid-cols-12">
          {/* Left Column: Stock Snapshot & Account info */}
          <div className="space-y-4 lg:col-span-5">
            <div className="rounded-lg border border-border/70 bg-card/60 p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xl font-bold tracking-tight">
                      {quote?.symbol ?? (selectedStock.includes('-') ? selectedStock : `${selectedStock}-EQ`)}
                    </span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                      NSE
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {matchedPopular?.name ?? `${selectedStock.replace(/-EQ$/, '')} Equity`}
                  </p>
                </div>
                <div className="text-right">
                  <div className="font-mono text-xl font-bold tabular tracking-tight">
                    {formatINR(effectivePrice)}
                  </div>
                  <span className="inline-flex items-center gap-0.5 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                    <TrendingUp className="h-3 w-3" />
                    Paper LTP
                  </span>
                </div>
              </div>

              {/* Metrics Grid */}
              <div className="mt-4 grid grid-cols-2 gap-2 border-t border-border/60 pt-3 text-xs">
                <div>
                  <span className="text-[11px] text-muted-foreground">Paper Cash Balance:</span>
                  <p className="font-mono font-semibold text-foreground">{formatINR(availableCash)}</p>
                </div>
                <div>
                  <span className="text-[11px] text-muted-foreground">Current Holding:</span>
                  <p className="font-mono font-semibold text-foreground">
                    {positionQty > 0 ? `${positionQty} shares` : '0 shares (Flat)'}
                  </p>
                </div>
                {positionQty > 0 && quote?.position && (
                  <>
                    <div>
                      <span className="text-[11px] text-muted-foreground">Avg Price:</span>
                      <p className="font-mono font-medium">{formatINR(quote.position.average_price ?? 0)}</p>
                    </div>
                    <div>
                      <span className="text-[11px] text-muted-foreground">Unrealized P&L:</span>
                      <p className={`font-mono font-semibold ${pnlClass(quote.position.unrealized_pnl)}`}>
                        {formatPnl(quote.position.unrealized_pnl)}
                      </p>
                    </div>
                  </>
                )}
              </div>

              {/* Action Buttons to Charts/Watchlist */}
              <div className="mt-4 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 flex-1 text-xs"
                  onClick={() => navigate(`/charts`)}
                >
                  View Chart
                  <ChevronRight className="ml-1 h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  title="Refresh Quote"
                  onClick={() => loadQuote(selectedStock)}
                  disabled={loadingQuote}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${loadingQuote ? 'animate-spin' : ''}`} />
                </Button>
              </div>
            </div>

            {/* Auto Trading Strategy Toggle */}
            <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 p-3">
              <div className="space-y-0.5 pr-2">
                <p className="text-xs font-medium">Auto Strategy Paper Trading</p>
                <p className="text-[11px] text-muted-foreground">
                  Continuous EMA + RSI + MACD strategy evaluation for {selectedStock.replace(/-EQ$/, '')}
                </p>
              </div>
              <Switch
                checked={enableAutoTrading}
                onCheckedChange={setEnableAutoTrading}
                aria-label="Toggle auto trading"
              />
            </div>
          </div>

          {/* Right Column: Order Placement Form */}
          <div className="flex flex-col justify-between space-y-4 rounded-lg border border-border/70 bg-card/60 p-4 lg:col-span-7">
            <div>
              {/* Buy / Sell Toggle Buttons */}
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setSide('BUY')}
                  className={`flex h-11 items-center justify-center gap-2 rounded-lg font-medium transition-all ${
                    side === 'BUY'
                      ? 'bg-emerald-600 text-white shadow-sm ring-2 ring-emerald-500/50'
                      : 'border border-border/70 bg-background/70 text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                  }`}
                >
                  <ArrowUpRight className="h-4 w-4" />
                  BUY (Paper)
                </button>
                <button
                  type="button"
                  onClick={() => setSide('SELL')}
                  className={`flex h-11 items-center justify-center gap-2 rounded-lg font-medium transition-all ${
                    side === 'SELL'
                      ? 'bg-rose-600 text-white shadow-sm ring-2 ring-rose-500/50'
                      : 'border border-border/70 bg-background/70 text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                  }`}
                >
                  <ArrowDownRight className="h-4 w-4" />
                  SELL (Paper)
                </button>
              </div>

              {/* Quantity Input and Presets */}
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="trade-quantity" className="text-xs font-medium text-foreground">
                    Number of Shares
                  </label>
                  <div className="flex items-center gap-1">
                    {side === 'BUY' ? (
                      <button
                        type="button"
                        onClick={handleMaxBuy}
                        className="text-[11px] font-medium text-primary hover:underline"
                      >
                        Max Buy ({effectivePrice > 0 ? Math.floor(availableCash / effectivePrice) : 0})
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={handleMaxSell}
                        disabled={positionQty <= 0}
                        className="text-[11px] font-medium text-primary hover:underline disabled:text-muted-foreground"
                      >
                        Sell All ({positionQty})
                      </button>
                    )}
                  </div>
                </div>

                <div className="flex gap-2">
                  <Input
                    id="trade-quantity"
                    type="number"
                    min="1"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    className="h-10 font-mono text-base font-semibold"
                    placeholder="Quantity"
                  />
                  {['1', '5', '10', '25'].map((q) => (
                    <Button
                      key={q}
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setQuantity(q)}
                      className="h-10 px-3 font-mono text-xs"
                    >
                      +{q}
                    </Button>
                  ))}
                </div>
              </div>

              {/* Execution Price Option */}
              <div className="mt-4 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Order Price:</span>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="radio"
                      name="price-type"
                      checked={useMarketPrice}
                      onChange={() => setUseMarketPrice(true)}
                      className="accent-primary"
                    />
                    <span>Market ({formatINR(effectivePrice)})</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="radio"
                      name="price-type"
                      checked={!useMarketPrice}
                      onChange={() => {
                        setUseMarketPrice(false)
                        if (!customPrice) setCustomPrice(String(effectivePrice))
                      }}
                      className="accent-primary"
                    />
                    <span>Custom Limit</span>
                  </label>
                </div>
              </div>

              {!useMarketPrice && (
                <div className="mt-2">
                  <Input
                    type="number"
                    step="0.05"
                    value={customPrice}
                    onChange={(e) => setCustomPrice(e.target.value)}
                    placeholder="Enter limit price"
                    className="h-9 font-mono text-sm"
                  />
                </div>
              )}

              {/* Trade Value & Margin Summary */}
              <div className="mt-4 rounded-lg bg-muted/40 p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Est. Order Value:</span>
                  <span className="font-mono font-semibold text-foreground">{formatINR(estTradeValue)}</span>
                </div>
                <div className="mt-1 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    {side === 'BUY' ? 'Cash After Trade:' : 'Cash After Sell:'}
                  </span>
                  <span className="font-mono text-muted-foreground">
                    {side === 'BUY' ? formatINR(Math.max(0, availableCash - estTradeValue)) : formatINR(availableCash + estTradeValue)}
                  </span>
                </div>
              </div>
            </div>

            {/* Execute Paper Trade Button */}
            <div className="pt-3">
              <Button
                type="button"
                disabled={busy || numQty <= 0 || (side === 'BUY' && availableCash < estTradeValue) || (side === 'SELL' && positionQty <= 0)}
                onClick={handleExecuteTrade}
                className={`h-12 w-full text-base font-semibold transition-all ${
                  side === 'BUY'
                    ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                    : 'bg-rose-600 hover:bg-rose-700 text-white'
                }`}
              >
                {busy ? (
                  <span className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Executing Paper Trade…
                  </span>
                ) : (
                  <span>
                    Take Paper Trade: {side} {numQty} {selectedStock.replace(/-EQ$/, '')} ({formatINR(estTradeValue)})
                  </span>
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`mt-4 rounded-lg border p-4 text-xs ${
              feedback.type === 'success'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                : 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300'
            }`}
          >
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">{feedback.message}</p>
                {feedback.details && <p className="mt-1 text-muted-foreground">{feedback.details}</p>}
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
