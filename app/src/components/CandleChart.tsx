import type { CandleRow, IndicatorRow } from '@/lib/types'
import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type Time,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type UTCTimestamp,
} from 'lightweight-charts'

const UP = '#2fbf8f'
const DOWN = '#e5484d'
const EMA20 = '#5aa2ff'
const EMA50 = '#f5a524'

function toTimestamp(iso: string): UTCTimestamp {
  // Server timestamps are UTC-naive; parse them as UTC explicitly.
  const normalized = iso.includes('Z') || iso.includes('+') ? iso : iso + 'Z'
  return (Math.floor(new Date(normalized).getTime() / 1000)) as UTCTimestamp
}

interface ChartRefs {
  chart: IChartApi | null
  candles: ISeriesApi<'Candlestick'> | null
  ema20: ISeriesApi<'Line'> | null
  ema50: ISeriesApi<'Line'> | null
  markers: ISeriesMarkersPluginApi<Time> | null
}

export function CandleChart({
  candles,
  indicators,
  height = 420,
}: {
  candles: CandleRow[]
  indicators?: IndicatorRow[]
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const refs = useRef<ChartRefs>({
    chart: null,
    candles: null,
    ema20: null,
    ema50: null,
    markers: null,
  })

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b93a7',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(139, 147, 167, 0.08)' },
        horzLines: { color: 'rgba(139, 147, 167, 0.08)' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: 'rgba(139,147,167,0.4)', labelBackgroundColor: '#1c2233' },
        horzLine: { color: 'rgba(139,147,167,0.4)', labelBackgroundColor: '#1c2233' },
      },
      rightPriceScale: { borderColor: 'rgba(139,147,167,0.2)' },
      timeScale: { borderColor: 'rgba(139,147,167,0.2)', timeVisible: true },
      width: container.clientWidth,
      height,
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
    })
    const ema20Series = chart.addSeries(LineSeries, {
      color: EMA20,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    const ema50Series = chart.addSeries(LineSeries, {
      color: EMA50,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    refs.current = {
      chart,
      candles: candleSeries,
      ema20: ema20Series,
      ema50: ema50Series,
      markers: createSeriesMarkers(candleSeries, []),
    }

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      refs.current = { chart: null, candles: null, ema20: null, ema50: null, markers: null }
    }
  }, [height])

  useEffect(() => {
    const { candles: series, ema20, ema50, markers, chart } = refs.current
    if (!chart || !series || candles.length === 0) return

    series.setData(
      candles.map((c) => ({
        time: toTimestamp(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    )

    if (indicators && indicators.length > 0) {
      ema20?.setData(
        indicators
          .filter((r) => r.ema_20 !== null)
          .map((r) => ({ time: toTimestamp(r.time), value: r.ema_20 as number })),
      )
      ema50?.setData(
        indicators
          .filter((r) => r.ema_50 !== null)
          .map((r) => ({ time: toTimestamp(r.time), value: r.ema_50 as number })),
      )

      markers?.setMarkers(
        indicators
          .filter((r) => r.signal === 'BUY' || r.signal === 'SELL')
          .map((r) => ({
            time: toTimestamp(r.time),
            position: r.signal === 'BUY' ? ('belowBar' as const) : ('aboveBar' as const),
            color: r.signal === 'BUY' ? UP : DOWN,
            shape: r.signal === 'BUY' ? ('arrowUp' as const) : ('arrowDown' as const),
            text: r.signal,
          })),
      )
    }

    chart.timeScale().fitContent()
    chart.timeScale().scrollToPosition(10, false)
  }, [candles, indicators])

  return <div ref={containerRef} className="w-full" style={{ height }} />
}

export function EquityChart({
  points,
  height = 320,
}: {
  points: { time: string; equity: number }[]
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || points.length === 0) return

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b93a7',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(139,147,167,0.08)' },
        horzLines: { color: 'rgba(139,147,167,0.08)' },
      },
      rightPriceScale: { borderColor: 'rgba(139,147,167,0.2)' },
      timeScale: { borderColor: 'rgba(139,147,167,0.2)' },
      width: container.clientWidth,
      height,
    })

    const equity = chart.addSeries(LineSeries, {
      color: UP,
      lineWidth: 2,
      priceLineVisible: false,
    })
    equity.setData(points.map((p) => ({ time: toTimestamp(p.time), value: p.equity })))

    const baseline = chart.addSeries(LineSeries, {
      color: 'rgba(139,147,167,0.5)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    baseline.setData(points.map((p) => ({ time: toTimestamp(p.time), value: points[0].equity })))

    chart.timeScale().fitContent()

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [points, height])

  return <div ref={containerRef} className="w-full" style={{ height }} />
}
