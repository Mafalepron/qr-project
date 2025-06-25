from fastapi import FastAPI, Depends, HTTPException, Response, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import qrcode
from io import BytesIO
import uuid
import httpx
import os
from sqlalchemy import select, update
from fastapi.staticfiles import StaticFiles

from . import crud, models, schemas
from .database import engine, get_db, Base
from .models import QRStats

app = FastAPI(title="QR Code Service")

# Раздача статических файлов из папки frontend
frontend_path = os.path.join(os.path.dirname(__file__), '../../frontend')
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

# Создаем таблицы в БД при старте
# В реальном проекте лучше использовать миграции (Alembic)
@app.on_event("startup")
async def startup():
    """Создает таблицы в базе данных при запуске приложения, если их нет. И инициализирует статистику."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Инициализация статистики
    async with AsyncSession(engine) as session:
        result = await session.execute(select(QRStats))
        stats = result.scalars().first()
        if not stats:
            stats = QRStats(success_count=0, fail_count=0)
            session.add(stats)
            await session.commit()


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
    file_path = os.path.join(os.path.dirname(__file__), "frontend", "scanner.html")
    return FileResponse(file_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Глобальная статистика по сканированиям для каждого админа
admin_stats = {}
# Глобальная статистика по всем сканированиям
global_success = 0
global_fail = 0

async def send_telegram_message(chat_id: str, text: str):
    """Отправляет сообщение пользователю через Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10)
        except Exception:
            pass

@app.post("/check_qr/{qr_code_id}", summary="Проверить QR-код")
async def check_qr_code(qr_code_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Эндпоинт для веб-сканера. Проверяет QR-код, обновляет его статус на 'used',
    возвращает информацию о пользователе и отправляет уведомления пользователю и админу.
    """
    db_qr_code = await crud.get_qr_code(db, qr_code_id=qr_code_id)
    data = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    admin_telegram_id = str(data.get('admin_telegram_id')) if data.get('admin_telegram_id') else None

    # Инициализация статистики для админа
    if admin_telegram_id:
        if admin_telegram_id not in admin_stats:
            admin_stats[admin_telegram_id] = {"success": 0, "fail": 0}

    global global_success, global_fail

    # Получаем объект статистики
    result = await db.execute(select(QRStats))
    stats = result.scalars().first()
    if not stats:
        stats = QRStats(success_count=0, fail_count=0)
        db.add(stats)
        await db.commit()
        await db.refresh(stats)

    # Сохраняем значения статистики в переменные
    stats_success = stats.success_count
    stats_fail = stats.fail_count

    if not db_qr_code:
        if admin_telegram_id:
            admin_stats[admin_telegram_id]["fail"] += 1
            global_fail += 1
            stats.fail_count += 1
            stats_fail = stats.fail_count  # сохраняем до коммита
            await db.commit()
            await send_telegram_message(
                admin_telegram_id,
                f"❌ Код не найден.\n\nВаша статистика:\n  ✅ Успешно: {admin_stats[admin_telegram_id]['success']}\n  ⛔ Отклонено: {admin_stats[admin_telegram_id]['fail']}\n\nОбщая статистика:\n  ✅ Всего успешно: {global_success}\n  ⛔ Всего отклонено: {global_fail}"
            )
        return JSONResponse(status_code=404, content={"status": "error", "message": "❌ Код не найден"})
    if db_qr_code.status == models.QRCodeStatus.USED:
        await send_telegram_message(db_qr_code.telegram_id, "⛔ Этот QR-код уже был использован ранее. Вход запрещён.")
        if admin_telegram_id:
            admin_stats[admin_telegram_id]["fail"] += 1
            global_fail += 1
            stats.fail_count += 1
            stats_fail = stats.fail_count
            await db.commit()
            await send_telegram_message(
                admin_telegram_id,
                f"⛔ Этот QR-код уже был использован ранее. Вход запрещён.\n\nВаша статистика:\n  ✅ Успешно: {admin_stats[admin_telegram_id]['success']}\n  ⛔ Отклонено: {admin_stats[admin_telegram_id]['fail']}\n\nОбщая статистика:\n  ✅ Всего успешно: {global_success}\n  ⛔ Всего отклонено: {global_fail}"
            )
        return JSONResponse(status_code=400, content={"status": "error", "message": f"⚠️ Код уже был использован"})
    if db_qr_code.status == models.QRCodeStatus.ISSUED:
        await crud.update_qr_code_status(db, qr_code_id=qr_code_id, status=models.QRCodeStatus.USED)
        user_info = db_qr_code.user_first_name or ""
        if db_qr_code.user_username:
            user_info += f" (@{db_qr_code.user_username})"
        await send_telegram_message(db_qr_code.telegram_id, "✅ Ваш QR-код успешно отсканирован! Добро пожаловать на мероприятие.")
        if admin_telegram_id:
            admin_stats[admin_telegram_id]["success"] += 1
            global_success += 1
            stats.success_count += 1
            stats_success = stats.success_count
            await db.commit()
            await send_telegram_message(
                admin_telegram_id,
                f"✅ QR-код успешно отсканирован: {user_info}\n\nВаша статистика:\n  ✅ Успешно: {admin_stats[admin_telegram_id]['success']}\n  ⛔ Отклонено: {admin_stats[admin_telegram_id]['fail']}\n\nОбщая статистика:\n  ✅ Всего успешно: {global_success}\n  ⛔ Всего отклонено: {global_fail}"
            )
        return JSONResponse(status_code=200, content={"status": "ok", "message": f"✅ Успех! {user_info}"})
    if admin_telegram_id:
        admin_stats[admin_telegram_id]["fail"] += 1
        global_fail += 1
        stats.fail_count += 1
        stats_fail = stats.fail_count
        await db.commit()
        await send_telegram_message(
            admin_telegram_id,
            f"❓ Неверный статус кода: {db_qr_code.status.value}\n\nВаша статистика:\n  ✅ Успешно: {admin_stats[admin_telegram_id]['success']}\n  ⛔ Отклонено: {admin_stats[admin_telegram_id]['fail']}\n\nОбщая статистика:\n  ✅ Всего успешно: {global_success}\n  ⛔ Всего отклонено: {global_fail}"
        )
    return JSONResponse(status_code=400, content={"status": "error", "message": f"❓ Неверный статус кода: {db_qr_code.status.value}"})

@app.get("/stats", summary="Получить общую статистику")
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(QRStats))
    stats = result.scalars().first()
    if not stats:
        return {"success": 0, "fail": 0}
    return {"success": stats.success_count, "fail": stats.fail_count}
