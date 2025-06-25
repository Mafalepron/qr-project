import uuid
import enum
from sqlalchemy import Column, String, DateTime, func, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import UUID
from .database import Base
import datetime

class QRCodeStatus(str, enum.Enum):
    CREATED = "created"
    ISSUED = "issued"
    USED = "used"
    INVALID = "invalid"

class QRCode(Base):
    __tablename__ = "qrcodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(SQLEnum(QRCodeStatus), nullable=False, default=QRCodeStatus.CREATED)
    telegram_id = Column(String, nullable=True, index=True, unique=True)
    user_first_name = Column(String, nullable=True)
    user_username = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    issued_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)

class QRStats(Base):
    __tablename__ = "qr_stats"
    id = Column(Integer, primary_key=True, index=True)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
