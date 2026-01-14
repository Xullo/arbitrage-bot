import { useState, useEffect } from 'react'
import './App.css'
import MarketPairing from './MarketPairing'

const API_URL = 'http://localhost:5000/api'

function App() {
  const [currentPage, setCurrentPage] = useState('dashboard') // 'dashboard' or 'pairing'
  const [status, setStatus] = useState(null)
  const [markets, setMarkets] = useState([])
  const [opportunities, setOpportunities] = useState([])
  const [trades, setTrades] = useState([])
  const [stats, setStats] = useState(null)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(new Date())
  const [logPage, setLogPage] = useState(0)
  const [oppPage, setOppPage] = useState(0)

  const LOGS_PER_PAGE = 20
  const OPPS_PER_PAGE = 15

  // Fetch all data
  const fetchData = async () => {
    try {
      const [statusRes, marketsRes, oppsRes, tradesRes, statsRes, logsRes] = await Promise.all([
        fetch(`${API_URL}/status`),
        fetch(`${API_URL}/markets`),
        fetch(`${API_URL}/opportunities`),
        fetch(`${API_URL}/trades`),
        fetch(`${API_URL}/stats`),
        fetch(`${API_URL}/logs`)
      ])

      const statusData = await statusRes.json()
      const marketsData = (await marketsRes.json()).markets || []
      const oppsData = (await oppsRes.json()).opportunities || []
      const tradesData = (await tradesRes.json()).trades || []
      const statsData = await statsRes.json()
      const logsData = (await logsRes.json()).logs || []

      setStatus(statusData)
      setMarkets(marketsData)
      setOpportunities(oppsData)
      setTrades(tradesData)
      setStats(statsData)
      setLogs(logsData)
      setLastUpdate(new Date())
      setLoading(false)
    } catch (error) {
      console.error('Error fetching data:', error)
      setLoading(false)
    }
  }

  // Auto-refresh every 3 seconds
  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [])

  // Pagination handlers
  const totalLogPages = Math.ceil(logs.length / LOGS_PER_PAGE)
  const totalOppPages = Math.ceil(opportunities.length / OPPS_PER_PAGE)

  const paginatedLogs = logs.slice().reverse().slice(logPage * LOGS_PER_PAGE, (logPage + 1) * LOGS_PER_PAGE)
  const paginatedOpps = opportunities.slice(oppPage * OPPS_PER_PAGE, (oppPage + 1) * OPPS_PER_PAGE)

  // If on pairing page, render it
  if (currentPage === 'pairing') {
    return <MarketPairing onBack={() => setCurrentPage('dashboard')} />
  }

  if (loading) {
    return (
      <div className="terminal loading">
        <div className="loader"></div>
        <p className="loading-text">LOADING SYSTEM...</p>
      </div>
    )
  }

  const actualMonitoredMarkets = markets.length || 3

  return (
    <div className="terminal">
      {/* Header with metrics */}
      <header className="header">
        <div className="header-left">
          <h1 className="title">ARB-BOT</h1>
          <div className="subtitle">v2.7.0</div>
        </div>

        {/* Navigation */}
        <div className="nav-buttons">
          <button
            className={`nav-btn ${currentPage === 'dashboard' ? 'active' : ''}`}
            onClick={() => setCurrentPage('dashboard')}
          >
            DASHBOARD
          </button>
          <button
            className={`nav-btn ${currentPage === 'pairing' ? 'active' : ''}`}
            onClick={() => setCurrentPage('pairing')}
          >
            MARKET PAIRING
          </button>
        </div>

        <div className="header-metrics">
          <div className="metric-chip">
            <span className="metric-label">MARKETS</span>
            <span className="metric-num">{actualMonitoredMarkets}</span>
          </div>
          <div className="metric-chip">
            <span className="metric-label">OPPS</span>
            <span className="metric-num">{opportunities.length}</span>
          </div>
          <div className="metric-chip">
            <span className="metric-label">TRADES</span>
            <span className="metric-num">{trades.length}</span>
          </div>
          <div className="metric-chip">
            <span className="metric-label">CAPITAL</span>
            <span className="metric-num">${(stats?.total_invested || 0).toFixed(2)}</span>
          </div>
        </div>

        <div className="header-right">
          <div className="status-group">
            <div className={`status-dot ${status?.status === 'active' ? 'active' : 'inactive'}`}></div>
            <span className="status-text">{status?.status?.toUpperCase()}</span>
          </div>
          <div className="mode-badge">{status?.simulation_mode ? 'PAPER' : 'LIVE'}</div>
          <div className="time">{lastUpdate.toLocaleTimeString()}</div>
        </div>
      </header>

      <div className="content">

        {/* Active Market */}
        {status?.active_market && (
          <section className="section active-market-section">
            <div className="section-title">ACTIVE MARKET</div>
            <div className="active-market">
              <span className="market-icon">▶</span>
              <code>{status.active_market}</code>
            </div>
          </section>
        )}

        {/* Monitored Markets */}
        <section className="section">
          <div className="section-header">
            <div className="section-title">MONITORED MARKETS</div>
            <div className="section-count">{markets.length}</div>
          </div>
          <div className="section-body">
            {markets.length === 0 ? (
              <div className="empty">No active markets</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>ASSET</th>
                    <th>KALSHI</th>
                    <th>POLYMARKET</th>
                    <th>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {markets.map((market, idx) => (
                    <tr key={idx}>
                      <td className="asset">{market.asset}</td>
                      <td><code className="mono-sm">{market.kalshi_ticker}</code></td>
                      <td><code className="mono-sm">{market.poly_ticker}</code></td>
                      <td><span className="pill">{market.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* Opportunities with Pagination */}
        <section className="section">
          <div className="section-header">
            <div className="section-title">OPPORTUNITIES</div>
            <div className="section-count">{opportunities.length}</div>
          </div>
          <div className="section-body">
            {opportunities.length === 0 ? (
              <div className="empty">No opportunities detected</div>
            ) : (
              <>
                <table className="table opps-table">
                  <thead>
                    <tr>
                      <th>DATE</th>
                      <th>TIME</th>
                      <th>STATUS</th>
                      <th>EXECUTION</th>
                      <th>TYPE</th>
                      <th>MARKET</th>
                      <th>PROFIT</th>
                      <th>KALSHI PRICE</th>
                      <th>POLY PRICE</th>
                      <th>TOTAL VOL</th>
                      <th>KALSHI VOL</th>
                      <th>POLY VOL</th>
                      <th>REASON</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedOpps.map((opp) => {
                      const date = new Date(opp.timestamp)
                      const executionStatus = opp.decision === 'REJECTED' ? 'REJECTED' : (opp.simulated ? 'SIMULATED' : 'EXECUTED')
                      const volumes = opp.volumes || { total: 0, kalshi: 0, polymarket: 0 }
                      const prices = opp.prices || { kalshi_yes: 0, kalshi_no: 0, poly_yes: 0, poly_no: 0 }

                      // Determine which price was used based on strategy
                      const strategy = opp.strategy || 'N/A'
                      let kalshiPrice = 0
                      let polyPrice = 0

                      if (strategy === 'YES_K_NO_P') {
                        kalshiPrice = prices.kalshi_yes
                        polyPrice = prices.poly_no
                      } else if (strategy === 'NO_K_YES_P') {
                        kalshiPrice = prices.kalshi_no
                        polyPrice = prices.poly_yes
                      }

                      return (
                        <tr key={opp.id} className={opp.decision === 'REJECTED' ? 'rejected' : 'accepted'}>
                          <td className="date">{date.toLocaleDateString()}</td>
                          <td className="time">{date.toLocaleTimeString()}</td>
                          <td>
                            {opp.decision === 'REJECTED' ? (
                              <span className="badge rejected">REJECTED</span>
                            ) : (
                              <span className="badge accepted">ACCEPTED</span>
                            )}
                          </td>
                          <td>
                            {executionStatus === 'REJECTED' ? (
                              <span className="badge rejected">REJECTED</span>
                            ) : executionStatus === 'SIMULATED' ? (
                              <span className="badge simulated">SIMULATED</span>
                            ) : (
                              <span className="badge executed">EXECUTED</span>
                            )}
                          </td>
                          <td><span className="type-badge">{opp.type}</span></td>
                          <td><code className="ticker">{opp.kalshi_ticker?.substring(0, 20) || 'N/A'}</code></td>
                          <td className="profit">{(opp.profit * 100).toFixed(2)}%</td>
                          <td className="price">${kalshiPrice.toFixed(2)}</td>
                          <td className="price">${polyPrice.toFixed(2)}</td>
                          <td className="volume">${volumes.total.toFixed(2)}</td>
                          <td className="volume">${volumes.kalshi.toFixed(2)}</td>
                          <td className="volume">${volumes.polymarket.toFixed(2)}</td>
                          <td className="reason" title={opp.reason}>
                            {opp.decision === 'REJECTED' ? (
                              <span>{opp.reason?.substring(0, 30) || 'N/A'}</span>
                            ) : (
                              <span>-</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {totalOppPages > 1 && (
                  <div className="pagination">
                    <button
                      onClick={() => setOppPage(Math.max(0, oppPage - 1))}
                      disabled={oppPage === 0}
                      className="pag-btn"
                    >
                      &lt;&lt; PREV
                    </button>
                    <span className="pag-info">PAGE {oppPage + 1} / {totalOppPages}</span>
                    <button
                      onClick={() => setOppPage(Math.min(totalOppPages - 1, oppPage + 1))}
                      disabled={oppPage === totalOppPages - 1}
                      className="pag-btn"
                    >
                      NEXT &gt;&gt;
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* System Logs with Pagination */}
        <section className="section">
          <div className="section-header">
            <div className="section-title">SYSTEM LOGS</div>
            <div className="section-count">{logs.length}</div>
          </div>
          <div className="section-body logs-body">
            {logs.length === 0 ? (
              <div className="empty">No logs available</div>
            ) : (
              <>
                <div className="logs-container">
                  {paginatedLogs.map((log, idx) => (
                    <div key={idx} className={`log log-${log.level.toLowerCase()}`}>
                      <span className="log-time">{log.timestamp.split(' ')[1]?.split(',')[0]}</span>
                      <span className="log-level">{log.level}</span>
                      <span className="log-msg">{log.message}</span>
                    </div>
                  ))}
                </div>
                {totalLogPages > 1 && (
                  <div className="pagination">
                    <button
                      onClick={() => setLogPage(Math.max(0, logPage - 1))}
                      disabled={logPage === 0}
                      className="pag-btn"
                    >
                      &lt;&lt; PREV
                    </button>
                    <span className="pag-info">PAGE {logPage + 1} / {totalLogPages}</span>
                    <button
                      onClick={() => setLogPage(Math.min(totalLogPages - 1, logPage + 1))}
                      disabled={logPage === totalLogPages - 1}
                      className="pag-btn"
                    >
                      NEXT &gt;&gt;
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </div>

      <footer className="footer">
        <div className="footer-info">
          <span>Auto-refresh: 3s</span>
          <span>API: {API_URL}</span>
        </div>
      </footer>
    </div>
  )
}

export default App
