"""Rebuild freqtrade backtest schema

Revision ID: 0001_backtest_rebuild
Revises: 
Create Date: 2025-10-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0001_backtest_rebuild"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Reference tables
    op.execute("""
    CREATE TABLE IF NOT EXISTS strategy_run (
      id               BIGSERIAL PRIMARY KEY,
      strategy_name    TEXT NOT NULL,
      timeframe        TEXT,
      timerange        TEXT,
      trading_mode     TEXT,
      stake_currency   TEXT,
      starting_balance NUMERIC,
      final_balance    NUMERIC,
      backtest_start   TIMESTAMPTZ,
      backtest_end     TIMESTAMPTZ,
      backtest_days    NUMERIC,
      total_trades     INT,
      trades_per_day   NUMERIC,
      market_change    NUMERIC,
      created_at       TIMESTAMPTZ DEFAULT now()
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS pair_summary (
      id                BIGSERIAL PRIMARY KEY,
      run_id            BIGINT REFERENCES strategy_run(id) ON DELETE CASCADE,
      pair_key          TEXT NOT NULL,
      trades            INT,
      profit_mean       NUMERIC,
      profit_total_abs  NUMERIC,
      profit_total_pct  NUMERIC,
      winrate           NUMERIC,
      cagr              NUMERIC,
      sharpe            NUMERIC,
      sortino           NUMERIC,
      calmar            NUMERIC,
      profit_factor     NUMERIC,
      max_dd_abs        NUMERIC,
      UNIQUE(run_id, pair_key)
    );
    """)

    # 2. Trades & Orders
    op.execute("""
    CREATE TABLE IF NOT EXISTS trade (
      id                 BIGSERIAL PRIMARY KEY,
      run_id             BIGINT REFERENCES strategy_run(id) ON DELETE CASCADE,
      pair               TEXT NOT NULL,
      stake_amount       NUMERIC,
      amount             NUMERIC,
      open_ts            TIMESTAMPTZ,
      close_ts           TIMESTAMPTZ,
      open_rate          NUMERIC,
      close_rate         NUMERIC,
      fee_open           NUMERIC,
      fee_close          NUMERIC,
      trade_duration_min INT,
      profit_ratio       NUMERIC,
      profit_abs         NUMERIC,
      exit_reason        TEXT,
      initial_sl_abs     NUMERIC,
      initial_sl_ratio   NUMERIC,
      stop_loss_abs      NUMERIC,
      stop_loss_ratio    NUMERIC,
      min_rate           NUMERIC,
      max_rate           NUMERIC,
      leverage           NUMERIC,
      is_short           BOOLEAN,
      enter_tag          TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_trade_run_pair ON trade(run_id, pair);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS trade_order (
      id            BIGSERIAL PRIMARY KEY,
      trade_id      BIGINT REFERENCES trade(id) ON DELETE CASCADE,
      amount        NUMERIC,
      price         NUMERIC,
      side          TEXT,
      filled_ts     TIMESTAMPTZ,
      is_entry      BOOLEAN,
      order_tag     TEXT,
      cost          NUMERIC
    );
    """)

    # 3. Exit reason summary
    op.execute("""
    CREATE TABLE IF NOT EXISTS exit_reason_summary (
      id                 BIGSERIAL PRIMARY KEY,
      run_id             BIGINT REFERENCES strategy_run(id) ON DELETE CASCADE,
      reason_key         TEXT,
      trades             INT,
      profit_mean        NUMERIC,
      profit_total_abs   NUMERIC,
      duration_avg_text  TEXT,
      winrate            NUMERIC,
      profit_factor      NUMERIC,
      UNIQUE(run_id, reason_key)
    );
    """)

    # 4. Periodic breakdowns
    op.execute("""
    CREATE TABLE IF NOT EXISTS periodic_profit (
      id            BIGSERIAL PRIMARY KEY,
      run_id        BIGINT REFERENCES strategy_run(id) ON DELETE CASCADE,
      period_type   TEXT CHECK (period_type IN ('day','week','month','year','weekday')),
      period_date   DATE,
      profit_abs    NUMERIC,
      wins          INT,
      losses        INT,
      trades        INT,
      profit_factor NUMERIC
    );
    """)

    # 5. Daily P/L series
    op.execute("""
    CREATE TABLE IF NOT EXISTS daily_profit (
      id         BIGSERIAL PRIMARY KEY,
      run_id     BIGINT REFERENCES strategy_run(id) ON DELETE CASCADE,
      day        DATE,
      profit_abs NUMERIC
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daily_profit CASCADE;")
    op.execute("DROP TABLE IF EXISTS periodic_profit CASCADE;")
    op.execute("DROP TABLE IF EXISTS exit_reason_summary CASCADE;")
    op.execute("DROP TABLE IF EXISTS trade_order CASCADE;")
    op.execute("DROP TABLE IF EXISTS trade CASCADE;")
    op.execute("DROP TABLE IF EXISTS pair_summary CASCADE;")
    op.execute("DROP TABLE IF EXISTS strategy_run CASCADE;")
