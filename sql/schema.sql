-- Schema DuckDB: hợp đồng giữa pipeline và MCP server (docs/design/stock-pipeline-collection.md, mục 6)
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL CHECK (status IN ('running', 'published', 'failed')),
    as_of_date        DATE,
    provider          TEXT,
    provider_version  TEXT,
    symbols_total     INTEGER,
    symbols_ok        INTEGER,
    symbols_excluded  INTEGER,
    symbols_failed    INTEGER
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol       TEXT PRIMARY KEY,
    exchange     TEXT,
    name         TEXT,
    in_universe  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS prices_daily (
    symbol      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        DOUBLE NOT NULL CHECK (open > 0),
    high        DOUBLE NOT NULL CHECK (high > 0),
    low         DOUBLE NOT NULL CHECK (low > 0),
    close       DOUBLE NOT NULL CHECK (close > 0),
    volume      BIGINT NOT NULL CHECK (volume >= 0),
    adjusted    BOOLEAN NOT NULL DEFAULT TRUE,
    source      TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    PRIMARY KEY (symbol, trade_date),
    CHECK (low <= high),
    CHECK (close BETWEEN low AND high)
);

CREATE TABLE IF NOT EXISTS symbol_run_status (
    run_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'excluded', 'failed')),
    row_count   INTEGER,
    first_date  DATE,
    last_date   DATE,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS quality_issues (
    run_id      TEXT NOT NULL,
    symbol      TEXT,
    check_code  TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('error', 'warn')),
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS features_daily (
    symbol           TEXT NOT NULL,
    trade_date       DATE NOT NULL,
    sma20 DOUBLE, sma50 DOUBLE, sma200 DOUBLE,
    ema12 DOUBLE, ema26 DOUBLE,
    rsi14 DOUBLE,
    macd DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE,
    bb_upper DOUBLE, bb_mid DOUBLE, bb_lower DOUBLE,
    atr14 DOUBLE,
    vol_sma20 DOUBLE,
    feature_version  TEXT NOT NULL,
    run_id           TEXT NOT NULL,
    PRIMARY KEY (symbol, trade_date)
);
