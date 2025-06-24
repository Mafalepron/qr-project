from pydantic import BaseModel, ConfigDict
import uuid
import datetime
from typing import Optional

from .models import QRCodeStatus


# Схема для возврата QR-кода в ответах API
class QRCode(BaseModel):
    id: uuid.UUID
    status: QRCodeStatus
    telegram_id: Optional[str] = None
    user_first_name: Optional[str] = None
    user_username: Optional[str] = None
    created_at: datetime.datetime
    issued_at: Optional[datetime.datetime] = None
    used_at: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Схема для создания нового QR-кода
class QRCodeCreate(BaseModel):
    telegram_id: str
    user_first_name: Optional[str] = None
    user_username: Optional[str] = None


# Схема для обновления QR-кода
class QRCodeUpdate(BaseModel):
    status: Optional[QRCodeStatus] = None
    telegram_id: Optional[str] = None
    issued_at: Optional[datetime.datetime] = None
    used_at: Optional[datetime.datetime] = None
