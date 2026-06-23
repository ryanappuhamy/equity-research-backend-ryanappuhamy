"""
Portfolio risk decomposition using 1 year of daily price history (yfinance).
"""

import numpy as np
import pandas as pd
import yfinance as yf

import config


def _download_returns(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """Daily simple returns for tickers, columns = tickers."""
    if not tickers:
        return pd.DataFrame()

    data = yf.download(
        tickers,
        period=period,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )
    if data.empty:
        raise ValueError("No price history returned")

    closes = {}
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                closes[t] = data[t]["Close"]
            else:
                closes[t] = data["Close"]
        except (KeyError, TypeError):
            continue

    prices = pd.DataFrame(closes).dropna(how="all")
    return prices.pct_change().dropna()


def _portfolio_weights(positions: list[dict]) -> pd.Series:
    """Weight by current market value."""
    weights = {}
    total = sum(p.get("market_value") or 0 for p in positions)
    if total <= 0:
        n = len(positions)
        return pd.Series({p["ticker"]: 1 / n for p in positions})
    for p in positions:
        weights[p["ticker"]] = (p.get("market_value") or 0) / total
    return pd.Series(weights)


def _annualized_vol(cov: pd.DataFrame, weights: pd.Series) -> float:
    """cov is annualized (daily cov × 252)."""
    w = weights.reindex(cov.index).fillna(0).values
    var = w @ cov.values @ w
    return float(np.sqrt(max(var, 0)))


def _risk_contributions(cov: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Each holding's contribution to portfolio variance (sums to total variance)."""
    w = weights.reindex(cov.index).fillna(0)
    port_var = w.values @ cov.values @ w.values
    if port_var <= 0:
        return pd.Series(0.0, index=cov.index)
    marginal = cov.values @ w.values
    contrib = w.values * marginal
    return pd.Series(contrib / port_var, index=cov.index)


def _betas(returns: pd.DataFrame, benchmark: str = "SPY") -> pd.Series:
    tickers = [c for c in returns.columns if c != benchmark]
    if benchmark not in returns.columns:
        bench = yf.download(benchmark, period="1y", auto_adjust=True, progress=False)["Close"]
        bench_ret = bench.pct_change().dropna()
        returns = returns.copy()
        returns[benchmark] = bench_ret.reindex(returns.index).fillna(0)

    bench_var = returns[benchmark].var()
    if bench_var == 0:
        return pd.Series(1.0, index=tickers)
    return pd.Series(
        {t: returns[t].cov(returns[benchmark]) / bench_var for t in tickers}
    )


def _rate_sensitivity(returns: pd.DataFrame, rate_proxy: str = "TLT") -> pd.Series:
    """Sensitivity to rate moves via TLT (bond ETF) daily returns."""
    tickers = list(returns.columns)
    if rate_proxy not in returns.columns:
        tlt = yf.download(rate_proxy, period="1y", auto_adjust=True, progress=False)["Close"]
        tlt_ret = tlt.pct_change().dropna()
        returns = returns.copy()
        returns[rate_proxy] = tlt_ret.reindex(returns.index).fillna(0)

    tlt_var = returns[rate_proxy].var()
    if tlt_var == 0:
        return pd.Series(-0.5, index=tickers)
    return pd.Series(
        {t: returns[t].cov(returns[rate_proxy]) / tlt_var for t in tickers}
    )


def analyze_portfolio_risk(positions: list[dict]) -> dict:
    """
    Risk decomposition for a portfolio (from portfolio.get_portfolio output).

    Returns correlation matrix, portfolio vol, per-holding risk contribution,
    and simple scenario analysis.
    """
    if not positions:
        return {"available": False, "note": "Empty portfolio"}

    tickers = [p["ticker"] for p in positions]
    weights = _portfolio_weights(positions)

    try:
        returns = _download_returns(tickers)
    except ValueError as e:
        return {"available": False, "note": str(e)}

    valid = [t for t in tickers if t in returns.columns]
    if len(valid) < 1:
        return {"available": False, "note": "Insufficient price history for holdings"}

    returns = returns[valid]
    weights = weights.reindex(valid).fillna(0)
    if weights.sum() > 0:
        weights = weights / weights.sum()

    cov = returns.cov() * 252
    corr = returns.corr()
    port_vol = _annualized_vol(cov, weights)
    risk_pct = _risk_contributions(cov, weights)

    betas = _betas(returns)
    rate_sens = _rate_sensitivity(returns)

    market_shock = -0.20
    tlt_move_for_1pct_rate = -0.04  # ~4% bond price move per 1% rate rise
    scenario_market = float(sum(weights[t] * betas.get(t, 1.0) * market_shock for t in valid))
    scenario_rates = float(
        sum(weights[t] * rate_sens.get(t, -0.5) * tlt_move_for_1pct_rate for t in valid)
    )

    holdings_risk = []
    for t in valid:
        holdings_risk.append(
            {
                "ticker": t,
                "weight": round(float(weights[t]), 4),
                "annualized_volatility": round(float(returns[t].std() * np.sqrt(252)), 4),
                "beta_vs_spy": round(float(betas.get(t, 1.0)), 3),
                "risk_contribution_pct": round(float(risk_pct.get(t, 0)), 4),
                "rate_sensitivity": round(float(rate_sens.get(t, -0.5)), 3),
            }
        )

    return {
        "available": True,
        "lookback": "1y",
        "holdings_count": len(valid),
        "portfolio_annualized_volatility": round(port_vol, 4),
        "correlation_matrix": corr.round(4).to_dict(),
        "holdings_risk": holdings_risk,
        "scenarios": {
            "market_down_20pct": {
                "estimated_portfolio_return": round(scenario_market, 4),
                "description": "Weighted beta × -20% market move",
            },
            "rates_up_1pct": {
                "estimated_portfolio_return": round(scenario_rates, 4),
                "description": "Rate sensitivity via TLT covariance proxy",
            },
        },
    }
