# Документация: QR-пропускная система с Telegram-ботом

Этот документ описывает архитектуру, компоненты и процесс развертывания системы для генерации и проверки QR-кодов на мероприятиях с использованием Telegram-бота и веб-сканера.

## 1. Архитектура системы

Система состоит из трех основных компонентов: Backend-сервер, Telegram-бот и Frontend-сканер (Web App), которые взаимодействуют между собой и с пользователями.

```mermaid
graph TD
    subgraph "Пользователи"
        A[Гость]
        B[Администратор]
    end

    subgraph "Интерфейс Telegram"
        C[Telegram Бот]
    end

    subgraph "Серверная часть (на вашем ПК)"
        D[Backend API <br/>(FastAPI, Python)]
        E[База данных <br/>(SQLite, qrcodes.db)]
        F[Веб-сканер <br/>(HTML/JS)]
    end
    
    A -- /get_qr --> C
    C -- Запрос на создание QR --> D
    D -- Создает/возвращает запись --> E
    D -- Возвращает ID кода --> C
    C -- Скачивает картинку с QR --> D
    D -- Отдает картинку --> C
    C -- Отправляет QR-код --> A

    B -- /scan --> C
    C -- Отправляет кнопку "Открыть сканер" --> B
    B -- Нажимает кнопку --> F
    F -- Запрашивает доступ к камере --> B
    F -- Сканирует QR и отправляет ID --> D
    D -- Проверяет/обновляет статус в БД --> E
    D -- Возвращает результат (имя гостя) --> F
    F -- Показывает результат --> B
```

## 2. Технологический стек

- **Backend**: Python, FastAPI, SQLAlchemy, Uvicorn, QRcode.
- **База данных**: SQLite.
- **Telegram-бот**: Python, `python-telegram-bot`.
- **Frontend (сканер)**: HTML, CSS, JavaScript, `html5-qrcode`.
- **Прокси-туннель (для разработки)**: ngrok.

## 3. Структура проекта

Финальная структура директорий и файлов выглядит следующим образом:

```
qr-project/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── crud.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   └── schemas.py
│   └── requirements.txt
├── frontend/
│   └── scanner.html
├── telegram_bot/
│   ├── bot.py
│   └── requirements.txt
├── .env
├── PROJECT_DOCUMENTATION.md
├── qrcodes.db
└── run_server.py
```

---

## 4. Описание и код компонентов

### 4.1. Backend API (FastAPI)

Отвечает за всю бизнес-логику: работа с базой данных, генерация QR-кодов, проверка статусов.

#### `backend/app/models.py`
Описывает структуру таблицы `qrcodes` в базе данных.

```python
import uuid
import enum
from sqlalchemy import Column, String, DateTime, func, Enum as SQLEnum
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
```

#### `backend/app/schemas.py`
Описывает Pydantic-схемы для валидации данных в API-запросах и ответах.

```python
from pydantic import BaseModel, ConfigDict
import uuid
import datetime
from typing import Optional

from .models import QRCodeStatus

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

class QRCodeCreate(BaseModel):
    telegram_id: str
    user_first_name: Optional[str] = None
    user_username: Optional[str] = None

class QRCodeUpdate(BaseModel):
    status: Optional[QRCodeStatus] = None
    telegram_id: Optional[str] = None
    issued_at: Optional[datetime.datetime] = None
    used_at: Optional[datetime.datetime] = None
```

#### `backend/app/crud.py`
Содержит функции для непосредственного взаимодействия с базой данных (Create, Read, Update, Delete).

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import datetime
import uuid

from . import models, schemas

async def get_qr_code(db: AsyncSession, qr_code_id: uuid.UUID):
    """Получает один QR-код из БД по его UUID."""
    result = await db.execute(select(models.QRCode).filter(models.QRCode.id == qr_code_id))
    return result.scalars().first()

async def get_qr_codes(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Получает список QR-кодов из БД с пагинацией."""
    result = await db.execute(select(models.QRCode).offset(skip).limit(limit))
    return result.scalars().all()

async def get_qr_code_by_telegram_id(db: AsyncSession, telegram_id: str):
    """Находит QR-код в БД по Telegram ID пользователя."""
    result = await db.execute(select(models.QRCode).filter(models.QRCode.telegram_id == telegram_id))
    return result.scalars().first()

async def create_qr_code(db: AsyncSession, qr_code: schemas.QRCodeCreate):
    """
    Создает новый QR-код или возвращает существующий для данного Telegram ID.
    Гарантирует, что у одного пользователя будет только один QR-код.
    """
    existing_qr_code = await get_qr_code_by_telegram_id(db, telegram_id=qr_code.telegram_id)
    if existing_qr_code:
        return existing_qr_code

    db_qr_code = models.QRCode(
        telegram_id=qr_code.telegram_id,
        user_first_name=qr_code.user_first_name,
        user_username=qr_code.user_username,
        status=models.QRCodeStatus.ISSUED,
        issued_at=datetime.datetime.utcnow()
    )
    db.add(db_qr_code)
    await db.commit()
    await db.refresh(db_qr_code)
    return db_qr_code

async def update_qr_code_status(db: AsyncSession, qr_code_id: uuid.UUID, status: models.QRCodeStatus):
    """Обновляет статус существующего QR-кода (например, на 'used')."""
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
```

#### `backend/app/main.py`
Основной файл FastAPI-приложения, определяющий все API-эндпоинты.

```python
from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import qrcode
from io import BytesIO
import uuid

from . import crud, models, schemas
from .database import engine, get_db, Base

app = FastAPI(title="QR Code Service")

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
        return JSONResponse(status_code=404, content={"status": "error", "message": "❌ Код не найден"})
    if db_qr_code.status == models.QRCodeStatus.USED:
        return JSONResponse(status_code=400, content={"status": "error", "message": f"⚠️ Код уже был использован"})
    if db_qr_code.status == models.QRCodeStatus.ISSUED:
        await crud.update_qr_code_status(db, qr_code_id=qr_code_id, status=models.QRCodeStatus.USED)
        user_info = db_qr_code.user_first_name or ""
        if db_qr_code.user_username:
            user_info += f" (@{db_qr_code.user_username})"
        return JSONResponse(status_code=200, content={"status": "ok", "message": f"✅ Успех! {user_info}"})
    return JSONResponse(status_code=400, content={"status": "error", "message": f"❓ Неверный статус кода: {db_qr_code.status.value}"})
```

#### `run_server.py`
Скрипт для удобного запуска backend-сервера.

```python
import uvicorn
import os

if __name__ == "__main__":
    if os.path.exists(".env"):
        from dotenv import load_dotenv
        load_dotenv()
    
    host = os.getenv("HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
    
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=True
    )
```

### 4.2. Telegram-бот

Взаимодействует с пользователями и администраторами, отправляет запросы на Backend.

#### `telegram_bot/bot.py`
Основной код бота.

```python
import logging
import os
import httpx
from dotenv import load_dotenv
from telegram import Update, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "0").split(",")]

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start. Приветствует пользователя и информирует админов."""
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}!\n\n"
        f"Я бот для выдачи QR-кодов на мероприятие. "
        f"Чтобы получить свой уникальный QR-код, введите команду /get_qr."
    )
    if user.id in ADMIN_IDS:
        await update.message.reply_text("Вы администратор. Используйте /scan для запуска сканера.")

async def get_qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /get_qr. Запрашивает у бэкенда QR-код и отправляет его пользователю."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.first_name}) requested a QR code.")
    try:
        async with httpx.AsyncClient() as client:
            payload = {"telegram_id": str(user.id), "user_first_name": user.first_name, "user_username": user.username}
            response = await client.post(f"{BACKEND_API_URL}/qrcodes/", json=payload, timeout=20.0)
            response.raise_for_status()
            qr_data = response.json()
            qr_code_id = qr_data.get("id")

            if not qr_code_id:
                raise ValueError("Backend did not return a QR code ID.")
            
            image_url = f"{BACKEND_API_URL}/qrcodes/{qr_code_id}/image"
            async with httpx.AsyncClient() as client_img:
                image_response = await client_img.get(image_url, timeout=20.0)
                image_response.raise_for_status()
                await update.message.reply_photo(photo=image_response.content, caption="Ваш уникальный QR-код.")
    except Exception as e:
        logger.error(f"Error in get_qr for {user.id}: {e}")
        await update.message.reply_text("Произошла ошибка при генерации QR-кода.")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(Только для админов) Отправляет кнопку для запуска Web App сканера."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: return

    public_url = os.getenv('PUBLIC_URL')
    if not public_url:
        await update.message.reply_text("Ошибка: Публичный URL не настроен. Сканирование невозможно.")
        return
        
    scanner_url = f"{public_url}/scanner"
    keyboard = [[InlineKeyboardButton("🚀 Открыть сканер", web_app=WebAppInfo(url=scanner_url))]]
    await update.message.reply_text("Нажмите кнопку для запуска сканера:", reply_markup=InlineKeyboardMarkup(keyboard))

def main() -> None:
    """Основная функция: настраивает и запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен бота не найден в .env файле! Завершение работы.")
        return
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_qr", get_qr))
    application.add_handler(CommandHandler("scan", scan_command))
    application.run_polling()

if __name__ == "__main__":
    main()
```

### 4.3. Frontend (Веб-сканер)

HTML-страница, которая открывается в Telegram и использует камеру для сканирования.

#### `frontend/scanner.html`

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QR Scanner</title>
    <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: sans-serif; background-color: #000; color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
        #qr-reader { width: 90vw; max-width: 500px; border: 2px solid #555; border-radius: 10px; overflow: hidden; }
        #qr-reader-results { margin-top: 20px; padding: 15px; border-radius: 10px; width: 90vw; max-width: 500px; text-align: center; font-size: 1.2em; display: none; }
        .success { background-color: #28a745; color: white; }
        .error { background-color: #dc3545; color: white; }
    </style>
</head>
<body>
    <div id="qr-reader"></div>
    <div id="qr-reader-results"></div>
    <script>
        const resultDiv = document.getElementById('qr-reader-results');
        let lastScanTime = 0;
        const scanCooldown = 3000;

        function onScanSuccess(decodedText, decodedResult) {
            const currentTime = Date.now();
            if (currentTime - lastScanTime < scanCooldown) return;
            lastScanTime = currentTime;

            if (window.navigator.vibrate) window.navigator.vibrate(200);

            fetch(`/check_qr/${decodedText}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    resultDiv.style.display = 'block';
                    resultDiv.textContent = data.message;
                    resultDiv.className = data.status === 'ok' ? 'success' : 'error';
                    setTimeout(() => Telegram.WebApp.close(), scanCooldown);
                })
                .catch(error => {
                    resultDiv.style.display = 'block';
                    resultDiv.className = 'error';
                    resultDiv.textContent = 'Ошибка сети при проверке кода.';
                });
        }
        document.addEventListener('DOMContentLoaded', () => {
            Telegram.WebApp.ready();
            const scanner = new Html5QrcodeScanner("qr-reader", { fps: 10, qrbox: {width: 250, height: 250} }, false);
            scanner.render(onScanSuccess, () => {});
        });
    </script>
</body>
</html>
```

---

## 5. Запуск и развертывание проекта

Это самая важная часть, так как окружение требует специфической настройки.

**Шаг 1: Установка системных зависимостей**
Для распознавания QR-кодов требуется библиотека `zbar`.

```bash
sudo apt update
sudo apt install -y zbar-tools
```

**Шаг 2: Установка зависимостей Python**
Из-за особенностей защиты вашей ОС, мы устанавливаем пакеты глобально для пользователя, используя флаг `--break-system-packages`.

```bash
/usr/bin/python3 -m pip install --break-system-packages -r backend/requirements.txt
/usr/bin/python3 -m pip install --break-system-packages -r telegram_bot/requirements.txt
/usr/bin/python3 -m pip install --break-system-packages pyzbar Pillow
```

**Шаг 3: Настройка переменных окружения**
Создайте в корне проекта файл `.env` со следующим содержимым:

```env
# Токен вашего бота, полученный у @BotFather
TELEGRAM_BOT_TOKEN="12345:ABCDE..."

# Telegram ID администраторов через запятую
ADMIN_IDS="ВАШ_ID_1,ВАШ_ID_2"

# Публичный HTTPS-адрес, полученный от ngrok на шаге 5
PUBLIC_URL="https://xxxx-xxxx.ngrok-free.app"
```

**Шаг 4: Запуск Backend-сервера**
Откройте первый терминал и выполните:

```bash
/usr/bin/python3 run_server.py
```
Вы должны увидеть логи Uvicorn. Оставьте этот терминал работать.

**Шаг 5: Запуск ngrok**
Скачайте `ngrok` с [официального сайта](https://ngrok.com/download) и запустите его во втором терминале, чтобы создать туннель к нашему серверу на порту 8000:

```bash
./ngrok http 8000
```
`ngrok` выдаст вам HTTPS-адрес. Скопируйте его и вставьте в поле `PUBLIC_URL` в вашем `.env` файле. **Сохраните файл `.env`**.

**Шаг 6: Запуск Telegram-бота**
Откройте третий терминал и запустите бота:

```bash
/usr/bin/python3 telegram_bot/bot.py
```

**Готово!** Теперь система полностью функциональна. Гости могут получать QR-коды, а администраторы — сканировать их с помощью камеры телефона через Web App в Telegram. 