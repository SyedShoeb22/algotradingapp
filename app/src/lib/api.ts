// API client with a built-in demo fallback.
//
// When the dashboard is served by `python3 -m app.main dashboard`, every
// call hits the real FastAPI backend. When it is previewed without a
// running engine (e.g. a static preview), the client transparently
// switches to a simulated dataset so the UI stays fully explorable.
// The demo banner makes that state explicit.

import type {
  AccountRow,
  BacktestResult,
  CandleRow,
  ConfigInfo,
  EngineStatus,
  EventRow,
  IndicatorRow,
  PaperTradeRequest,
  PaperTradeResult,
  PopularStock,
  SignalRow,
  StockQuote,
  TradeRow,
  WatchlistEntry,
} from './types'

export type ConnectionMode = 'live' | 'demo'

let mode: ConnectionMode = 'live'
let notified = false

export function getMode(): ConnectionMode {
  return mode
}

function setDemo() {
  if (!notified) {
    notified = true
    console.info('[desk] Engine API unreachable - using demo data feed')
  }
  mode = 'demo'
}

async function apiFetch<T>(path: string): Promise<T> {
  if (mode === 'demo') throw new Error('demo mode')
  try {
    const response = await fetch(path, {
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return (await response.json()) as T
  } catch (error) {
    setDemo()
    throw error
  }
}

// ---------------------------------------------------------------------
// Demo data generator (seeded random walk, evolves with wall clock)
// ---------------------------------------------------------------------

function seededRandom(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

const DEMO_SYMBOLS = [
  { symbol: 'TCS-EQ', anchor: 4150.0, capital: 100000 },
  { symbol: 'SBIN-EQ', anchor: 818.4, capital: 100000 },
  { symbol: 'KROSS-EQ', anchor: 251.7, capital: 100000 },
  { symbol: 'RELIANCE-EQ', anchor: 2980.0, capital: 100000 },
  { symbol: 'INFY-EQ', anchor: 1890.0, capital: 100000 },
  { symbol: 'TATAMOTORS-EQ', anchor: 980.5, capital: 100000 },
]

export const POPULAR_NSE_SYMBOLS: PopularStock[] = [
  { symbol: 'TCS', full_symbol: 'TCS-EQ', name: 'Tata Consultancy Services', sector: 'IT / Tech', anchor: 4150.0 },
  { symbol: 'RELIANCE', full_symbol: 'RELIANCE-EQ', name: 'Reliance Industries', sector: 'Energy / Retail', anchor: 2980.0 },
  { symbol: 'INFY', full_symbol: 'INFY-EQ', name: 'Infosys', sector: 'IT / Tech', anchor: 1890.0 },
  { symbol: 'SBIN', full_symbol: 'SBIN-EQ', name: 'State Bank of India', sector: 'Banking / PSU', anchor: 820.0 },
  { symbol: 'HDFCBANK', full_symbol: 'HDFCBANK-EQ', name: 'HDFC Bank', sector: 'Banking / Private', anchor: 1680.0 },
  { symbol: 'TATAMOTORS', full_symbol: 'TATAMOTORS-EQ', name: 'Tata Motors', sector: 'Automobile', anchor: 980.0 },
  { symbol: 'ICICIBANK', full_symbol: 'ICICIBANK-EQ', name: 'ICICI Bank', sector: 'Banking / Private', anchor: 1250.0 },
  { symbol: 'WIPRO', full_symbol: 'WIPRO-EQ', name: 'Wipro', sector: 'IT / Tech', anchor: 560.0 },
  { symbol: 'KROSS', full_symbol: 'KROSS-EQ', name: 'Kross', sector: 'Auto Ancillary', anchor: 252.0 },
  { symbol: 'LT', full_symbol: 'LT-EQ', name: 'Larsen & Toubro', sector: 'Infrastructure', anchor: 3620.0 },
  { symbol: 'ITC', full_symbol: 'ITC-EQ', name: 'ITC', sector: 'FMCG', anchor: 475.0 },
  { symbol: 'BHARTIARTL', full_symbol: 'BHARTIARTL-EQ', name: 'Bharti Airtel', sector: 'Telecom', anchor: 1580.0 },
]

function demoCandles(symbol: string, anchor: number, count = 200): CandleRow[] {
  const bucketMs = 5 * 60 * 1000
  const now = Math.floor(Date.now() / bucketMs) * bucketMs
  const rand = seededRandom(symbol.length * 7919 + count)
  const candles: CandleRow[] = []
  let price = anchor * 0.97
  for (let i = count; i >= 1; i--) {
    const t = now - i * bucketMs
    const drift = (rand() - 0.5) * price * 0.004
    const close = Math.max(1, price + drift)
    const open = price
    const high = Math.max(open, close) + rand() * price * 0.0012
    const low = Math.min(open, close) - rand() * price * 0.0012
    candles.push({
      time: new Date(t).toISOString().slice(0, 19),
      open: +open.toFixed(2),
      high: +high.toFixed(2),
      low: +low.toFixed(2),
      close: +close.toFixed(2),
      volume: Math.round(80000 + rand() * 90000),
    })
    price = close
  }
  return candles
}

function demoPrice(symbol: string, anchor: number): number {
  const bucket = Math.floor(Date.now() / 10000)
  const rand = seededRandom(bucket + symbol.charCodeAt(0) * 131)
  return +(anchor * (0.985 + rand() * 0.03)).toFixed(2)
}

const demoEvents: EventRow[] = [
  { id: 6, level: 'INFO', source: 'paper', message: 'SBIN-EQ: BUY 23 @ 842.52 (value Rs.19,378)', created_at: new Date(Date.now() - 120000).toISOString() },
  { id: 5, level: 'INFO', source: 'paper', message: 'KROSS-EQ: BUY 84 @ 235.57 (value Rs.19,788)', created_at: new Date(Date.now() - 180000).toISOString() },
  { id: 4, level: 'INFO', source: 'engine', message: 'Engine started in SIMULATION mode', created_at: new Date(Date.now() - 300000).toISOString() },
  { id: 3, level: 'INFO', source: 'collector', message: 'Simulated feed started for 3 symbols', created_at: new Date(Date.now() - 300000).toISOString() },
  { id: 2, level: 'WARN', source: 'paper', message: 'TATAMOTORS-EQ: BUY rejected - insufficient cash', created_at: new Date(Date.now() - 420000).toISOString() },
  { id: 1, level: 'INFO', source: 'history', message: 'Imported 375 candles for SBIN-EQ (5min)', created_at: new Date(Date.now() - 600000).toISOString() },
]

const demoTrades: TradeRow[] = [
  { id: 9, symbol: 'SBIN-EQ', side: 'SELL', quantity: 24, price: 832.93, trade_value: 19990.32, pnl: 130.0, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 86400000).toISOString() },
  { id: 8, symbol: 'SBIN-EQ', side: 'BUY', quantity: 24, price: 827.52, trade_value: 19860.48, pnl: null, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 90000000).toISOString() },
  { id: 7, symbol: 'KROSS-EQ', side: 'SELL', quantity: 80, price: 246.1, trade_value: 19688.0, pnl: -96.4, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 172800000).toISOString() },
  { id: 6, symbol: 'KROSS-EQ', side: 'BUY', quantity: 80, price: 247.3, trade_value: 19784.0, pnl: null, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 176400000).toISOString() },
  { id: 5, symbol: 'SBIN-EQ', side: 'BUY', quantity: 23, price: 842.52, trade_value: 19377.96, pnl: null, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 120000).toISOString() },
  { id: 4, symbol: 'KROSS-EQ', side: 'BUY', quantity: 84, price: 235.57, trade_value: 19787.88, pnl: null, strategy: 'EMA20_EMA50_RSI14_MACD', executed_at: new Date(Date.now() - 180000).toISOString() },
]

function demoEngineStatus(): EngineStatus {
  return {
    mode: 'SIMULATION',
    running: true,
    uptime_seconds: 3125,
    collector: {
      type: 'simulated',
      connected: true,
      symbols: DEMO_SYMBOLS.map((s) => s.symbol),
      ticks_received: 8124,
      ticks_written: 8101,
    },
    symbols: DEMO_SYMBOLS.map((s, i) => ({
      symbol: s.symbol,
      exchange: 'NSE',
      interval: '5min',
      token: `SIM-${s.symbol.split('-')[0]}`,
      token_status: 'OK',
      enabled: true,
      last_price: demoPrice(s.symbol, s.anchor),
      last_tick_at: new Date().toISOString(),
      last_candle_start: new Date(Math.floor(Date.now() / 300000) * 300000 - 300000).toISOString().slice(0, 19),
      last_candle_age_min: 4.2 + i,
      candle_count: 84,
      account: {
        initial_capital: s.capital,
        cash: i === 2 ? 4710.55 : s.capital - 19378 - i * 410,
        realized_pnl: i === 0 ? 130.0 : i === 1 ? -96.4 : 0,
      },
      position:
        i === 2
          ? null
          : {
              quantity: i === 0 ? 23 : 84,
              average_price: i === 0 ? 842.52 : 235.57,
              last_price: demoPrice(s.symbol, s.anchor),
              unrealized_pnl: i === 0 ? -172.4 : 328.9,
            },
      last_signal: i === 2 ? 'HOLD' : 'BUY',
      last_evaluation: 'SIGNAL_ONLY',
      last_evaluation_reason:
        i === 2 ? 'EMA, RSI and MACD are not fully aligned' : 'Bullish EMA, RSI and MACD confirmation',
    })),
  }
}

// ---------------------------------------------------------------------
// Public endpoint wrappers
// ---------------------------------------------------------------------

export async function fetchStatus(): Promise<EngineStatus> {
  try {
    return await apiFetch<EngineStatus>('/api/status')
  } catch {
    return demoEngineStatus()
  }
}

export async function fetchConfig(): Promise<ConfigInfo> {
  try {
    return await apiFetch<ConfigInfo>('/api/config')
  } catch {
    return {
      mode: 'SIMULATION',
      running: true,
      simulate: true,
      angel_credentials_configured: false,
      risk: { max_candle_age_minutes: 10, global_max_open_positions: 5 },
    }
  }
}

export async function fetchWatchlist(): Promise<WatchlistEntry[]> {
  try {
    const data = await apiFetch<{ symbols: WatchlistEntry[] }>('/api/watchlist')
    return data.symbols
  } catch {
    return DEMO_SYMBOLS.map((s) => ({
      symbol: s.symbol,
      exchange: 'NSE',
      interval: '5min',
      token: `SIM-${s.symbol.split('-')[0]}`,
      token_status: 'OK',
      enabled: true,
    }))
  }
}

export async function fetchAccounts(): Promise<AccountRow[]> {
  try {
    const data = await apiFetch<{ accounts: AccountRow[] }>('/api/accounts')
    return data.accounts
  } catch {
    return DEMO_SYMBOLS.map((s, i) => ({
      symbol: s.symbol,
      initial_capital: s.capital,
      cash: i === 2 ? 4710.55 : s.capital - 19378 - i * 410,
      realized_pnl: i === 0 ? 130.0 : i === 1 ? -96.4 : 0,
      position_value: i === 2 ? 0 : i === 0 ? 19377.96 : 19787.88,
      position:
        i === 2
          ? null
          : {
              quantity: i === 0 ? 23 : 84,
              average_price: i === 0 ? 842.52 : 235.57,
              last_price: demoPrice(s.symbol, s.anchor),
              unrealized_pnl: i === 0 ? -172.4 : 328.9,
            },
    }))
  }
}

export async function fetchTrades(symbol?: string): Promise<TradeRow[]> {
  try {
    const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''
    const data = await apiFetch<{ trades: TradeRow[] }>(`/api/trades${query}`)
    return data.trades
  } catch {
    return symbol ? demoTrades.filter((t) => t.symbol === symbol) : demoTrades
  }
}

export async function fetchCandles(symbol: string, interval = '5min'): Promise<CandleRow[]> {
  try {
    const data = await apiFetch<{ candles: CandleRow[] }>(
      `/api/candles/${encodeURIComponent(symbol)}?interval=${interval}&limit=400`,
    )
    return data.candles
  } catch {
    const anchor = DEMO_SYMBOLS.find((s) => s.symbol === symbol)?.anchor ?? 500
    return demoCandles(symbol, anchor, 260)
  }
}

export async function fetchSignals(symbol: string): Promise<SignalRow[]> {
  try {
    const data = await apiFetch<{ signals: SignalRow[] }>(
      `/api/signals/${encodeURIComponent(symbol)}?limit=120`,
    )
    return data.signals
  } catch {
    const candles = demoCandles(symbol, 500, 60)
    return candles.slice(-40).map((c) => ({
      candle_start: c.time,
      signal: c.close % 7 < 1.2 ? 'BUY' : c.close % 11 < 1.0 ? 'SELL' : 'HOLD',
      processed_at: c.time,
    }))
  }
}

export async function fetchIndicators(symbol: string): Promise<IndicatorRow[]> {
  try {
    const data = await apiFetch<{ rows: IndicatorRow[] }>(
      `/api/indicators/${encodeURIComponent(symbol)}?limit=160`,
    )
    return data.rows
  } catch {
    const candles = demoCandles(symbol, 500, 160)
    return candles.map((c, i) => {
      const slice = candles.slice(Math.max(0, i - 50), i + 1)
      const mean = slice.reduce((a, x) => a + x.close, 0) / slice.length
      return {
        time: c.time,
        close: c.close,
        ema_20: i < 20 ? null : +(mean * 1.001).toFixed(3),
        ema_50: i < 50 ? null : +(mean * 0.999).toFixed(3),
        rsi_14: i < 14 ? null : +(45 + ((c.close % 30) - 15)).toFixed(2),
        macd: i < 35 ? null : +((c.close - mean) / mean).toFixed(4),
        macd_signal: i < 44 ? null : +((c.close - mean) / mean / 1.1).toFixed(4),
        signal: c.close % 7 < 1.2 && i > 50 ? 'BUY' : c.close % 11 < 1.0 && i > 50 ? 'SELL' : 'HOLD',
        reason: 'Demo dataset',
      }
    })
  }
}

export async function fetchEvents(): Promise<EventRow[]> {
  try {
    const data = await apiFetch<{ events: EventRow[] }>('/api/events?limit=120')
    return data.events
  } catch {
    return demoEvents
  }
}

export async function fetchBacktest(symbol: string, days = 30): Promise<BacktestResult> {
  const params = new URLSearchParams({ days: String(days) })
  try {
    return await apiFetch<BacktestResult>(
      `/api/backtest/${encodeURIComponent(symbol)}?${params}`,
    )
  } catch {
    const candles = demoCandles(symbol, 800, days * 69)
    let cash = 100000
    let qty = 0
    let avg = 0
    const equity_curve: BacktestResult['equity_curve'] = []
    const trades: BacktestResult['trades'] = []
    for (const c of candles) {
      const buy = c.close % 9 < 1.1 && qty === 0
      const sell = c.close % 13 < 1.0 && qty > 0
      if (buy) {
        qty = Math.floor(Math.min(20000, cash * 0.2) / c.close)
        if (qty > 0) {
          cash -= qty * c.close
          avg = c.close
          trades.push({ side: 'BUY', quantity: qty, price: c.close, time: c.time })
        }
      } else if (sell) {
        cash += qty * c.close
        trades.push({ side: 'SELL', quantity: qty, price: c.close, time: c.time, pnl: +((c.close - avg) * qty).toFixed(2) })
        qty = 0
      }
      equity_curve.push({ time: c.time, equity: +(cash + qty * c.close).toFixed(2), close: c.close })
    }
    const final = cash + qty * candles[candles.length - 1].close
    return {
      symbol,
      interval: '5min',
      initial_capital: 100000,
      final_equity: +final.toFixed(2),
      total_return_pct: +(((final - 100000) / 100000) * 100).toFixed(2),
      buy_signals: trades.filter((t) => t.side === 'BUY').length,
      sell_signals: trades.filter((t) => t.side === 'SELL').length,
      trades: trades.slice(-100),
      equity_curve,
    }
  }
}

// ---------------------------------------------------------------------
// Mutations (no-ops in demo mode, but they still resolve so the UI
// gives feedback instead of hanging)
// ---------------------------------------------------------------------

export async function startEngine(simulate: boolean): Promise<{ status: string; mode?: string }> {
  if (mode === 'demo') return { status: 'demo', mode: 'SIMULATION' }
  const response = await fetch('/api/engine/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ simulate }),
  })
  return response.json()
}

export async function stopEngine(): Promise<{ status: string }> {
  if (mode === 'demo') return { status: 'demo' }
  const response = await fetch('/api/engine/stop', { method: 'POST' })
  return response.json()
}

export async function addSymbol(payload: {
  symbol: string
  initial_capital: number
  max_position_value: number
  max_position_pct: number
}): Promise<{ symbol: string; token: string | null; token_status: string }> {
  if (mode === 'demo') {
    return { symbol: payload.symbol.toUpperCase(), token: null, token_status: 'UNRESOLVED' }
  }
  const response = await fetch('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${response.status}`)
  }
  return response.json()
}

export async function removeSymbol(symbol: string): Promise<void> {
  if (mode === 'demo') return
  await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' })
}

export async function patchSymbol(
  symbol: string,
  patch: { enabled?: boolean; initial_capital?: number; max_position_value?: number; max_position_pct?: number },
): Promise<void> {
  if (mode === 'demo') return
  await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export async function resolveTokens(): Promise<Record<string, string | null>> {
  if (mode === 'demo') return {}
  const response = await fetch('/api/watchlist/resolve', { method: 'POST' })
  const body = await response.json()
  return body.resolved ?? {}
}

export async function importHistory(symbol: string, days: number): Promise<{ candles: number }> {
  if (mode === 'demo') return { candles: 375 }
  const response = await fetch('/api/history/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, days }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${response.status}`)
  }
  return response.json()
}

export async function fetchPopularSymbols(): Promise<PopularStock[]> {
  try {
    const data = await apiFetch<{ symbols: PopularStock[] }>('/api/symbols/popular')
    return data.symbols
  } catch {
    return POPULAR_NSE_SYMBOLS
  }
}

export async function fetchStockQuote(symbol: string): Promise<StockQuote> {
  const norm = symbol.trim().toUpperCase()
  try {
    return await apiFetch<StockQuote>(`/api/paper/quote/${encodeURIComponent(norm)}`)
  } catch {
    const pop = POPULAR_NSE_SYMBOLS.find(
      (p) => p.symbol === norm || p.full_symbol === norm || norm.startsWith(p.symbol),
    )
    const anchor = pop ? pop.anchor : 500
    const price = demoPrice(norm, anchor)
    const fullSym = norm.includes('-') ? norm : `${norm}-EQ`
    return {
      symbol: fullSym,
      input_symbol: norm,
      price,
      exists_in_watchlist: DEMO_SYMBOLS.some((s) => s.symbol === fullSym),
      auto_trading_enabled: false,
      account: {
        initial_capital: 100000,
        cash: 100000,
        realized_pnl: 0,
      },
      position: null,
    }
  }
}

export async function executePaperTrade(payload: PaperTradeRequest): Promise<PaperTradeResult> {
  if (mode === 'demo') {
    const sym = payload.symbol.trim().toUpperCase()
    const fullSym = sym.includes('-') ? sym : `${sym}-EQ`
    const pop = POPULAR_NSE_SYMBOLS.find(
      (p) => p.symbol === sym || p.full_symbol === sym || sym.startsWith(p.symbol),
    )
    const price = payload.price ?? (pop ? demoPrice(sym, pop.anchor) : 500)
    const tradeValue = Math.round(payload.quantity * price * 100) / 100
    const trade: TradeRow = {
      id: Date.now(),
      symbol: fullSym,
      side: payload.side,
      quantity: payload.quantity,
      price,
      trade_value: tradeValue,
      pnl: payload.side === 'SELL' ? 250 : null,
      strategy: 'MANUAL',
      executed_at: new Date().toISOString(),
    }
    demoTrades.unshift(trade)
    return {
      success: true,
      trade,
      account: {
        symbol: fullSym,
        initial_capital: 100000,
        cash: payload.side === 'BUY' ? 100000 - tradeValue : 100000 + tradeValue,
        realized_pnl: payload.side === 'SELL' ? 250 : 0,
      },
      position: {
        quantity: payload.side === 'BUY' ? payload.quantity : 0,
        average_price: payload.side === 'BUY' ? price : null,
        last_price: price,
        unrealized_pnl: 0,
      },
    }
  }

  const response = await fetch('/api/paper/trade', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${response.status}: Failed to execute paper trade`)
  }

  return response.json()
}
