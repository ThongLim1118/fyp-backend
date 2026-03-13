from fastapi import Request
from src.app.services.ft import FT
from src.app.db.session import get_db, get_local_db

def get_ft(request: Request) -> FT:
    return request.app.state.ft
