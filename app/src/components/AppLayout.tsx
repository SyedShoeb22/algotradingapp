import { Activity, CandlestickChart, FlaskConical, LayoutDashboard, ListChecks, Settings } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'
import { DemoBanner } from './DemoBanner'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/watchlist', label: 'Watchlist', labelMobile: 'Stocks', icon: ListChecks },
  { to: '/trading', label: 'Paper Trading', labelMobile: 'Trading', icon: Activity },
  { to: '/charts', label: 'Charts', icon: CandlestickChart },
  { to: '/backtest', label: 'Backtest', labelMobile: 'Test', icon: FlaskConical },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function AppLayout() {
  return (
    <div className="min-h-100dvh bg-background lg:pl-60">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-sidebar-border bg-sidebar-background lg:flex">
        <div className="flex h-16 items-center gap-3 border-b border-sidebar-border px-5">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15">
            <CandlestickChart className="h-5 w-5 text-primary" aria-hidden />
          </span>
          <div className="leading-tight">
            <p className="font-mono text-[13px] font-semibold tracking-wide text-sidebar-accent-foreground">
              NSE PAPER DESK
            </p>
            <p className="text-[11px] text-sidebar-foreground">algo trading · paper only</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Primary">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex min-h-11 items-center gap-3 rounded-full px-4 text-sm font-medium transition-colors duration-200 ${
                  isActive
                    ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                    : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                }`
              }
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-sidebar-border p-4">
          <p className="font-mono text-[11px] leading-relaxed text-sidebar-foreground">
            Real order execution is <span className="text-warn">disabled</span>. All trades are paper trades.
          </p>
        </div>
      </aside>

      {/* Top bar (mobile: brand; desktop: spacer for content header) */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/90 px-4 backdrop-blur lg:h-16 lg:px-8">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 lg:hidden">
          <CandlestickChart className="h-4 w-4 text-primary" aria-hidden />
        </span>
        <p className="font-mono text-[13px] font-semibold tracking-wide lg:hidden">NSE PAPER DESK</p>
        <div className="ml-auto">
          <DemoBanner />
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 pb-28 pt-5 lg:px-8 lg:pb-12 lg:pt-8">
        <Outlet />
      </main>

      {/* Mobile bottom navigation */}
      <nav
        className="pb-safe fixed inset-x-0 bottom-0 z-40 border-t border-border bg-sidebar-background/95 backdrop-blur lg:hidden"
        aria-label="Primary mobile"
      >
        <div className="grid grid-cols-6">
          {NAV_ITEMS.map(({ to, label, labelMobile, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex min-h-14 flex-col items-center justify-center gap-0.5 pt-1 text-[10px] font-medium transition-colors ${
                  isActive ? 'text-primary' : 'text-sidebar-foreground'
                }`
              }
            >
              <Icon className="h-5 w-5" aria-hidden />
              {labelMobile ?? label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
