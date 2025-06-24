from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import datetime

from . import models, schemas


async def get_qr_code(db: AsyncSession, qr_code_id: str):
    result = await db.execute(select(models.QRCode).filter(models.QRCode.id == qr_code_id))
    return result.scalars().first()


async def get_qr_codes(db: AsyncSession, skip: int = 0, limit: int = 100):
    result = await db.execute(select(models.QRCode).offset(skip).limit(limit))
    return result.scalars().all()


async def get_qr_code_by_telegram_id(db: AsyncSession, telegram_id: str):
    """Ищет QR-код по Telegram ID пользователя."""
    result = await db.execute(select(models.QRCode).filter(models.QRCode.telegram_id == telegram_id))
    return result.scalars().first()


async def create_qr_code(db: AsyncSession, qr_code: schemas.QRCodeCreate):
    """
    Создает новый QR-код или возвращает существующий, если он уже был выдан
    этому пользователю.
    """
    # 1. Проверяем, есть ли у пользователя уже QR-код
    existing_qr_code = await get_qr_code_by_telegram_id(db, telegram_id=qr_code.telegram_id)
    if existing_qr_code:
        return existing_qr_code

    # 2. Если нет, создаем новый
    db_qr_code = models.QRCode(
        telegram_id=qr_code.telegram_id,
        user_first_name=qr_code.user_first_name,
        user_username=qr_code.user_username,
        status=models.QRCodeStatus.ISSUED, # Сразу помечаем как "выдан"
        issued_at=datetime.datetime.utcnow()
    )
    db.add(db_qr_code)
    await db.commit()
    await db.refresh(db_qr_code)
    return db_qr_code


async def update_qr_code_status(db: AsyncSession, qr_code_id: str, status: models.QRCodeStatus):
    db_qr_code = await get_qr_code(db, qr_code_id)
    if not db_qr_code:
        return None
    
    db_qr_code.status = status
    
    if status == models.QRCodeStatus.ISSUED:
        db_qr_code.issued_at = datetime.datetime.utcnow()
    elif status == models.QRCodeStatus.USED:
        db_qr_code.used_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(db_qr_code)
    return db_qr_code

