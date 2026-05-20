-- market.db — shared market-data cache for personal finance skills.
-- All tables idempotent (IF NOT EXISTS) so init can run repeatedly.

-- Daily OHLCV per (ticker, date). All prices are split- and dividend-adjusted.
CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT    NOT NULL,
    date        TEXT    NOT NULL,            -- ISO date YYYY-MM-DD
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    source      TEXT    NOT NULL,            -- 'yfinance' | 'fmp'
    fetched_at  TEXT    NOT NULL,            -- ISO datetime
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);

-- Quarterly fundamentals — long format, target ~20 quarters per ticker on FMP,
-- yfinance fallback gives ~4-5 quarters.
CREATE TABLE IF NOT EXISTS quarterly_financials (
    ticker            TEXT    NOT NULL,
    period_end        TEXT    NOT NULL,      -- ISO date (fiscal period end)
    eps_diluted       REAL,
    revenue           REAL,
    net_income        REAL,
    gross_profit      REAL,
    operating_income  REAL,
    free_cash_flow    REAL,
    shares_diluted    REAL,
    eps_estimate      REAL,                  -- consensus at the time (if known)
    eps_surprise_pct  REAL,                  -- (actual - estimate)/|estimate| * 100
    source            TEXT    NOT NULL,
    fetched_at        TEXT    NOT NULL,
    PRIMARY KEY (ticker, period_end)
);
CREATE INDEX IF NOT EXISTS idx_qfin_ticker ON quarterly_financials(ticker);

-- Annual fundamentals (5-10 years per ticker)
CREATE TABLE IF NOT EXISTS annual_financials (
    ticker        TEXT    NOT NULL,
    fiscal_year   INTEGER NOT NULL,
    eps_diluted   REAL,
    revenue       REAL,
    net_income    REAL,
    fcf           REAL,
    source        TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL,
    PRIMARY KEY (ticker, fiscal_year)
);

-- Key metrics by quarter (ROE, margins). FMP-only currently; yfinance can't.
CREATE TABLE IF NOT EXISTS key_metrics_quarterly (
    ticker              TEXT    NOT NULL,
    period_end          TEXT    NOT NULL,
    roe                 REAL,
    roa                 REAL,
    gross_margin        REAL,
    operating_margin    REAL,
    net_margin          REAL,
    fcf_margin          REAL,
    source              TEXT    NOT NULL,
    fetched_at          TEXT    NOT NULL,
    PRIMARY KEY (ticker, period_end)
);

-- Ticker metadata — latest snapshot only (no history).
CREATE TABLE IF NOT EXISTS ticker_info (
    ticker             TEXT    PRIMARY KEY,
    long_name          TEXT,
    short_name         TEXT,
    sector             TEXT,
    industry           TEXT,
    market_cap         REAL,
    trailing_eps       REAL,
    forward_eps        REAL,
    roe                REAL,                -- returnOnEquity (fraction, e.g. 0.32 = 32%)
    next_earnings_date TEXT,
    source             TEXT    NOT NULL,
    fetched_at         TEXT    NOT NULL
);

-- Cache state: per (ticker, data_type), tracks when we last fetched.
-- The client checks this before deciding whether to refetch.
CREATE TABLE IF NOT EXISTS cache_state (
    ticker      TEXT    NOT NULL,
    data_type   TEXT    NOT NULL,            -- 'prices'|'quarterly'|'annual'|'metrics'|'info'
    last_fetch  TEXT    NOT NULL,
    ttl_hours   INTEGER NOT NULL,
    PRIMARY KEY (ticker, data_type)
);

-- API call log — debug rate limits + see which skill drove which fetch.
CREATE TABLE IF NOT EXISTS fetch_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,           -- 'yfinance' | 'fmp'
    ticker       TEXT,
    endpoint     TEXT,                       -- 'history' | 'quarterly_income_stmt' | etc.
    status       TEXT,                       -- 'ok' | 'error' | 'cached'
    duration_ms  INTEGER,
    rows         INTEGER,                    -- number of rows returned/written
    skill        TEXT,                       -- caller (when known)
    error        TEXT,
    timestamp    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetch_log_ts ON fetch_log(timestamp);
