from pydantic import BaseModel
from typing import Any, Optional

class ApiResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: Optional[Any] = None
