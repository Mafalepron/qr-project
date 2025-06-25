from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import qrcode
from io import BytesIO
import uuid

from . import crud, models, schemas
from .database import engine, get_db, Base

app = FastAPI(title="QR Code Service")

# Создаем таблицы в БД при старте
# В реальном проекте лучше использовать миграции (Alembic)
@app.on_event("startup")
async def startup():
    """Создает таблицы в базе данных при запуске приложения, если их нет."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/", summary="Проверка работы сервиса")
async def root():
    """Корневой эндпоинт для проверки, что сервис запущен и работает."""
    return {"message": "QR Code Service is running"}


@app.post("/qrcodes/", response_model=schemas.QRCode, summary="Создать или получить QR-код")
async def create_qr_code_endpoint(
    qr_code: schemas.QRCodeCreate, db: AsyncSession = Depends(get_db)
):
    """
    Создает QR-код для пользователя по его Telegram ID.
    Если у пользователя уже есть код, возвращает существующий.
    """
    return await crud.create_qr_code(db=db, qr_code=qr_code)


@app.get("/qrcodes/", response_model=list[schemas.QRCode])
async def read_qr_codes(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    return await crud.get_qr_codes(db, skip=skip, limit=limit)


@app.get("/qrcodes/{qr_code_id}", response_model=schemas.QRCode)
async def read_qr_code(qr_code_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_qr_code = await crud.get_qr_code(db, qr_code_id=qr_code_id)
    if db_qr_code is None:
        raise HTTPException(status_code=404, detail="QR code not found")
    return db_qr_code

@app.get("/qrcodes/{qr_code_id}/image", summary="Получить изображение QR-кода")
async def get_qr_code_image(qr_code_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Генерирует и возвращает PNG-изображение QR-кода по его UUID."""
    db_qr_code = await crud.get_qr_code(db, qr_code_id=qr_code_id)
    if db_qr_code is None:
        raise HTTPException(status_code=404, detail="QR code not found")

    img = qrcode.make(str(qr_code_id))
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    
    return Response(content=buf.getvalue(), media_type="image/png")

@app.put("/qrcodes/{qr_code_id}/status", response_model=schemas.QRCode)
async def update_qr_code_status(
    qr_code_id: uuid.UUID, status: models.QRCodeStatus, db: AsyncSession = Depends(get_db)
):
    db_qr_code = await crud.update_qr_code_status(db, qr_code_id=qr_code_id, status=status)
    if db_qr_code is None:
        raise HTTPException(status_code=404, detail="QR code not found")
    return db_qr_code

@app.get("/scanner", response_class=FileResponse, summary="Получить страницу сканера")
async def get_scanner_page():
    """Отдает HTML-страницу веб-приложения для сканирования QR-кодов."""
    return "frontend/scanner.html"


@app.post("/check_qr/{qr_code_id}", summary="Проверить QR-код")
async def check_qr_code(qr_code_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Эндпоинт для веб-сканера. Проверяет QR-код, обновляет его статус на 'used'
    и возвращает информацию о пользователе.
    """
    db_qr_code = await crud.get_qr_code(db, qr_code_id=qr_code_id)
    
    if not db_qr_code:
        return JSONResponse(
            status_code=404, 
            content={"status": "error", "message": "❌ Код не найден"}
        )

    if db_qr_code.status == models.QRCodeStatus.USED:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"⚠️ Код уже был использован"}
        )

    if db_qr_code.status == models.QRCodeStatus.ISSUED:
        await crud.update_qr_code_status(db, qr_code_id=qr_code_id, status=models.QRCodeStatus.USED)
        user_info = db_qr_code.user_first_name or ""
        if db_qr_code.user_username:
            user_info += f" (@{db_qr_code.user_username})"
        
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": f"✅ Успех! {user_info}"}
        )

    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": f"❓ Неверный статус кода: {db_qr_code.status.value}"}
    )
