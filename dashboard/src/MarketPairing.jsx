import { useState, useEffect } from 'react'
import './MarketPairing.css'

function MarketPairing({ onBack }) {
  const [kalshiMarkets, setKalshiMarkets] = useState([])
  const [polyMarkets, setPolyMarkets] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedKalshi, setSelectedKalshi] = useState(null)
  const [selectedPoly, setSelectedPoly] = useState(null)
  const [pairs, setPairs] = useState([])
  const [sortBy, setSortBy] = useState('time') // 'time' or 'ticker'

  // Fetch all markets
  useEffect(() => {
    fetchMarkets()
    const interval = setInterval(fetchMarkets, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const fetchMarkets = async () => {
    try {
      const response = await fetch('http://localhost:5000/api/all-markets')
      const data = await response.json()

      setKalshiMarkets(data.kalshi || [])
      setPolyMarkets(data.polymarket || [])
      setLoading(false)
    } catch (error) {
      console.error('Error fetching markets:', error)
      setLoading(false)
    }
  }

  // Sort markets
  const sortedKalshi = [...kalshiMarkets].sort((a, b) => {
    if (sortBy === 'time') {
      return a.close_timestamp - b.close_timestamp
    }
    return a.ticker.localeCompare(b.ticker)
  })

  const sortedPoly = [...polyMarkets].sort((a, b) => {
    if (sortBy === 'time') {
      return a.close_timestamp - b.close_timestamp
    }
    return a.ticker.localeCompare(b.ticker)
  })

  // Find potential matches (same close time within 60 seconds)
  const findMatches = (kalshiMarket) => {
    return polyMarkets.filter(poly => {
      const timeDiff = Math.abs(kalshiMarket.close_timestamp - poly.close_timestamp)
      return timeDiff <= 60
    })
  }

  // Create a pair
  const createPair = () => {
    if (selectedKalshi && selectedPoly) {
      const timeDiff = Math.abs(selectedKalshi.close_timestamp - selectedPoly.close_timestamp)

      const newPair = {
        id: pairs.length + 1,
        kalshi: selectedKalshi,
        poly: selectedPoly,
        timeDiff: timeDiff,
        status: timeDiff <= 60 ? 'VALID' : 'WARNING'
      }

      setPairs([...pairs, newPair])
      setSelectedKalshi(null)
      setSelectedPoly(null)
    }
  }

  // Remove a pair
  const removePair = (id) => {
    setPairs(pairs.filter(p => p.id !== id))
  }

  // Calculate arbitrage opportunity for a pair
  const calculateArbitrage = (pair) => {
    const k = pair.kalshi
    const p = pair.poly

    // Strategy A: Buy Poly YES + Kalshi NO
    const costA = p.yes_price + k.no_price
    const profitA = 1.0 - costA

    // Strategy B: Buy Poly NO + Kalshi YES
    const costB = p.no_price + k.yes_price
    const profitB = 1.0 - costB

    const bestProfit = Math.max(profitA, profitB)
    const bestStrategy = profitA > profitB ? 'YES_P + NO_K' : 'NO_P + YES_K'

    return {
      profit: bestProfit,
      profitPct: (bestProfit * 100).toFixed(2),
      strategy: bestStrategy,
      isArb: bestProfit > 0.01 // At least 1% profit
    }
  }

  if (loading) {
    return (
      <div className="pairing-container">
        <div className="loading">Loading markets...</div>
      </div>
    )
  }

  return (
    <div className="pairing-container">
      <div className="pairing-header">
        <div className="header-top">
          <h1>Market Pairing Tool</h1>
          <button className="back-btn" onClick={onBack}>← BACK TO DASHBOARD</button>
        </div>
        <div className="stats">
          <div className="stat">
            <span className="label">Kalshi Markets:</span>
            <span className="value">{kalshiMarkets.length}</span>
          </div>
          <div className="stat">
            <span className="label">Polymarket Markets:</span>
            <span className="value">{polyMarkets.length}</span>
          </div>
          <div className="stat">
            <span className="label">Your Pairs:</span>
            <span className="value">{pairs.length}</span>
          </div>
        </div>

        <div className="controls">
          <label>
            Sort by:
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="time">Close Time</option>
              <option value="ticker">Ticker</option>
            </select>
          </label>
        </div>
      </div>

      <div className="markets-grid">
        {/* Kalshi Markets */}
        <div className="market-column">
          <h2>Kalshi Markets ({sortedKalshi.length})</h2>
          <div className="market-list">
            {sortedKalshi.map((market, idx) => {
              const matches = findMatches(market)
              const isSelected = selectedKalshi?.ticker === market.ticker

              return (
                <div
                  key={idx}
                  className={`market-card ${isSelected ? 'selected' : ''} ${matches.length > 0 ? 'has-match' : ''}`}
                  onClick={() => setSelectedKalshi(market)}
                >
                  <div className="market-ticker">{market.ticker}</div>
                  <div className="market-time">{market.close_time}</div>
                  <div className="market-prices">
                    <span className="yes">YES: {market.yes_price.toFixed(2)}</span>
                    <span className="no">NO: {market.no_price.toFixed(2)}</span>
                  </div>
                  {matches.length > 0 && (
                    <div className="match-indicator">{matches.length} potential match(es)</div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Polymarket Markets */}
        <div className="market-column">
          <h2>Polymarket Markets ({sortedPoly.length})</h2>
          <div className="market-list">
            {sortedPoly.map((market, idx) => {
              const isSelected = selectedPoly?.ticker === market.ticker
              const matchesKalshi = selectedKalshi ? Math.abs(selectedKalshi.close_timestamp - market.close_timestamp) <= 60 : false

              return (
                <div
                  key={idx}
                  className={`market-card ${isSelected ? 'selected' : ''} ${matchesKalshi ? 'highlighted' : ''}`}
                  onClick={() => setSelectedPoly(market)}
                >
                  <div className="market-ticker">{market.ticker}</div>
                  <div className="market-title">{market.title}</div>
                  <div className="market-time">{market.close_time}</div>
                  <div className="market-prices">
                    <span className="yes">YES: {market.yes_price.toFixed(2)}</span>
                    <span className="no">NO: {market.no_price.toFixed(2)}</span>
                  </div>
                  {matchesKalshi && (
                    <div className="match-indicator">Matches selected Kalshi!</div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Pairing Controls */}
      <div className="pairing-controls">
        <div className="selected-info">
          <div className="selected-market">
            <strong>Kalshi:</strong> {selectedKalshi ? selectedKalshi.ticker : 'None'}
          </div>
          <div className="selected-market">
            <strong>Polymarket:</strong> {selectedPoly ? selectedPoly.ticker : 'None'}
          </div>
          {selectedKalshi && selectedPoly && (
            <div className="time-diff">
              Time diff: {Math.abs(selectedKalshi.close_timestamp - selectedPoly.close_timestamp)}s
              {Math.abs(selectedKalshi.close_timestamp - selectedPoly.close_timestamp) > 60 && (
                <span className="warning"> ⚠️ More than 60s!</span>
              )}
            </div>
          )}
        </div>
        <button
          className="create-pair-btn"
          onClick={createPair}
          disabled={!selectedKalshi || !selectedPoly}
        >
          Create Pair
        </button>
      </div>

      {/* Created Pairs */}
      {pairs.length > 0 && (
        <div className="pairs-section">
          <h2>Your Market Pairs ({pairs.length})</h2>
          <table className="pairs-table">
            <thead>
              <tr>
                <th>Kalshi</th>
                <th>Polymarket</th>
                <th>Close Time</th>
                <th>Time Diff</th>
                <th>Prices (K)</th>
                <th>Prices (P)</th>
                <th>Arb Opp</th>
                <th>Strategy</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map(pair => {
                const arb = calculateArbitrage(pair)
                return (
                  <tr key={pair.id} className={arb.isArb ? 'has-arb' : ''}>
                    <td className="ticker">{pair.kalshi.ticker}</td>
                    <td className="ticker">{pair.poly.ticker}</td>
                    <td>{pair.kalshi.close_time}</td>
                    <td className={pair.timeDiff > 60 ? 'warning' : 'ok'}>{pair.timeDiff}s</td>
                    <td>
                      <span className="yes">Y:{pair.kalshi.yes_price.toFixed(2)}</span>
                      {' '}
                      <span className="no">N:{pair.kalshi.no_price.toFixed(2)}</span>
                    </td>
                    <td>
                      <span className="yes">Y:{pair.poly.yes_price.toFixed(2)}</span>
                      {' '}
                      <span className="no">N:{pair.poly.no_price.toFixed(2)}</span>
                    </td>
                    <td className={arb.isArb ? 'profit' : ''}>{arb.profitPct}%</td>
                    <td className="strategy">{arb.strategy}</td>
                    <td className={`status ${pair.status.toLowerCase()}`}>{pair.status}</td>
                    <td>
                      <button className="remove-btn" onClick={() => removePair(pair.id)}>Remove</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default MarketPairing
