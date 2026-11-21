import { AppLayout } from '@/components/AppLayout'
import { Route, Routes } from 'react-router'
import Backtest from './pages/Backtest'
import Charts from './pages/Charts'
import Overview from './pages/Overview'
import Settings from './pages/Settings'
import Trading from './pages/Trading'
import Watchlist from './pages/Watchlist'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Overview />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="trading" element={<Trading />} />
        <Route path="charts" element={<Charts />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  )
}
