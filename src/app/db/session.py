# from contextlib import contextmanager
from src.app.db.config import LocalSessionLocal, SessionLocal

async def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

async def get_local_db():
    db = LocalSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()