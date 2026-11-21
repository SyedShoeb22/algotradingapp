export interface SymbolStatus {
  symbol: string
  exchange: string
  interval: string
  token: string | null
  token_status: string
  enabled: boolean
  last_price: number | null
  last_tick_at: string | null
  last_candle_start: string | null
  last_candle_age_min: number | null
  candle_count: number
  account: {
    initial_capital: number
    cash: number | null
    realized_pnl: number
  }
  position: {
    quantity: number
    average_price: number | null
    last_price: number | null
    unrealized_pnl: number
  } | null
  last_signal: string | null
  last_evaluation: string | null
  last_evaluation_reason: string | null
}

export interface CollectorStatus {
  type: string
  connected: boolean
  symbols: string[]
  ticks_received: number
  ticks_written: number
}

export interface EngineStatus {
  mode: string
  running: boolean
  uptime_seconds: number
  collector: CollectorStatus
  symbols: SymbolStatus[]
}

export interface WatchlistEntry {
  symbol: string
  exchange: string
  interval: string
  token: string | null
  token_status: string
  enabled: boolean
}

export interface AccountRow {
  symbol: string
  initial_capital: number
  cash: number
  realized_pnl: number
  position_value: number
  position: {
    quantity: number
    average_price: number | null
    last_price: number | null
    unrealized_pnl: number
  } | null
}

export interface TradeRow {
  id: number
  symbol: string
  side: string
  quantity: number
  price: number
  trade_value: number
  pnl: number | null
  strategy: string | null
  executed_at: string
}

export interface CandleRow {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface SignalRow {
  candle_start: string
  signal: string
  processed_at: string
}

export interface IndicatorRow {
  time: string
  close: number
  ema_20: number | null
  ema_50: number | null
  rsi_14: number | null
  macd: number | null
  macd_signal: number | null
  signal: string
  reason: string
}

export interface EventRow {
  id: number
  level: string
  source: string
  message: string
  created_at: string
}

export interface BacktestResult {
  symbol: string
  interval: string
  initial_capital: number
  final_equity: number
  total_return_pct: number
  buy_signals: number
  sell_signals: number
  trades: {
    side: string
    quantity: number
    price: number
    time: string
    pnl?: number
  }[]
  equity_curve: { time: string; equity: number; close: number }[]
}

export interface ConfigInfo {
  mode: string
  running: boolean
  simulate: boolean
  angel_credentials_configured: boolean
  risk: {
    max_candle_age_minutes: number
    global_max_open_positions: number
  }
}

export interface PaperTradeRequest {
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  price?: number
  enable_auto_trading?: boolean
  initial_capital?: number
}

export interface PaperTradeResult {
  success: boolean
  trade: TradeRow
  account: {
    symbol: string
    initial_capital: number
    cash: number
    realized_pnl: number
  }
  position: {
    quantity: number
    average_price: number | null
    last_price: number | null
    unrealized_pnl: number
  }
}

export interface StockQuote {
  symbol: string
  input_symbol: string
  price: number
  exists_in_watchlist: boolean
  auto_trading_enabled: boolean
  account: {
    initial_capital: number
    cash: number
    realized_pnl: number
  }
  position: {
    quantity: number
    average_price: number | null
    last_price: number | null
    unrealized_pnl: number
  } | null
}

export interface PopularStock {
  symbol: string
  full_symbol: string
  name: string
  sector: string
  anchor: number
}
