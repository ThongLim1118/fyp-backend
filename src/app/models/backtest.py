# from sqlalchemy import Column, BigInteger, Integer, Text, Numeric, DateTime, ForeignKey
# from sqlalchemy.dialects.postgresql import JSONB
# from sqlalchemy.orm import relationship
# from src.app.db.config import Base

# class BacktestRun(Base):
#     __tablename__ = "backtest_runs"
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     strategy = Column(Text, nullable=False)
#     timeframe = Column(Text)
#     timerange = Column(Text)
#     run_started_at = Column(DateTime(timezone=True))
#     run_finished_at = Column(DateTime(timezone=True))
#     total_trades = Column(Integer)
#     winrate = Column(Numeric)
#     total_return = Column(Numeric)
#     max_drawdown = Column(Numeric)
#     sharpe = Column(Numeric)
#     sortino = Column(Numeric)
#     src_zip_path = Column(Text, nullable=False)
#     raw_json = Column(JSONB, nullable=False)

#     pairs = relationship("BacktestPair", back_populates="run", cascade="all, delete-orphan")
#     trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")

# class BacktestPair(Base):
#     __tablename__ = "backtest_pairs"
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     run_id = Column(BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"))
#     pair = Column(Text, nullable=False)
#     trades = Column(Integer)
#     profit_abs = Column(Numeric)
#     profit_pct = Column(Numeric)
#     drawdown_pct = Column(Numeric)
#     sharpe = Column(Numeric)
#     sortino = Column(Numeric)
#     run = relationship("BacktestRun", back_populates="pairs")

# class BacktestTrade(Base):
#     __tablename__ = "backtest_trades"
#     id = Column(BigInteger, primary_key=True, autoincrement=True)
#     run_id = Column(BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"))
#     pair = Column(Text, nullable=False)
#     open_time = Column(DateTime(timezone=True))
#     close_time = Column(DateTime(timezone=True))
#     duration_sec = Column(Integer)
#     side = Column(Text)
#     open_rate = Column(Numeric)
#     close_rate = Column(Numeric)
#     profit_abs = Column(Numeric)
#     profit_pct = Column(Numeric)
#     exit_reason = Column(Text)
#     run = relationship("BacktestRun", back_populates="trades")
