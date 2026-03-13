from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.app.settings import settings

Base = declarative_base()

# Supabase cloud database to store results for frontend display
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


# Local database to store large volume datasets
localEngine = create_engine(settings.LOCAL_DATABASE_URL, pool_pre_ping=True, future=True)
LocalSessionLocal = sessionmaker(bind=localEngine, autocommit=False, autoflush=False, future=True)