from fastapi import Request
from app.services.ft import FT
from app.db.session import get_db

def get_ft(request: Request) -> FT:
    return request.app.state.ft
