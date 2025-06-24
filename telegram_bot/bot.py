import logging
import os
import httpx
from dotenv import load_dotenv
from telegram import Update, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from PIL import Image
from pyzbar.pyzbar import decode
from io import BytesIO

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "0").split(",")]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение по команде /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}!\n\n"
        f"Я бот для выдачи QR-кодов на мероприятие. "
        f"Чтобы получить свой уникальный QR-код, введите команду /get_qr.",
    )
    if update.effective_user.id in ADMIN_IDS:
        await update.message.reply_text(
            "Вы вошли как администратор. Используйте команду /scan для запуска сканера QR-кодов."
        )


async def get_qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создает и отправляет пользователю QR-код."""
    user = update.effective_user
    telegram_id = str(user.id)
    logger.info(f"User {telegram_id} ({user.first_name}) requested a QR code.")

    try:
        # 1. Отправляем запрос на backend для создания QR-кода
        async with httpx.AsyncClient() as client:
            payload = {
                "telegram_id": telegram_id,
                "user_first_name": user.first_name,
                "user_username": user.username
            }
            response = await client.post(
                f"{BACKEND_API_URL}/qrcodes/",
                json=payload,
                timeout=20.0
            )
            response.raise_for_status()
            qr_data = response.json()
            qr_code_id = qr_data.get("id")

            if not qr_code_id:
                raise ValueError("Backend did not return a QR code ID.")

            logger.info(f"Successfully created/retrieved QR code with id {qr_code_id} for user {telegram_id}")

            # 2. Скачиваем изображение QR-кода от backend
            image_url = f"{BACKEND_API_URL}/qrcodes/{qr_code_id}/image"

            async with httpx.AsyncClient() as client:
                image_response = await client.get(image_url, timeout=20.0)
                image_response.raise_for_status()
                image_bytes = image_response.content

            await update.message.reply_photo(
                photo=image_bytes,
                caption="Ваш уникальный QR-код. Предъявите его на входе."
            )
    except httpx.RequestError as e:
        logger.error(f"Could not connect to backend: {e}")
        await update.message.reply_text(
            "Не удалось связаться с сервером. Пожалуйста, попробуйте позже."
        )
    except Exception as e:
        logger.error(f"An error occurred in get_qr for user {telegram_id}: {e}")
        await update.message.reply_text(
            "Произошла ошибка при генерации QR-кода. Пожалуйста, попробуйте позже."
        )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет кнопку для запуска Web App сканера (только для админов)."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    # ЗАМЕНА: URL должен быть HTTPS. Для локальной разработки используем ngrok или аналог.
    # Пока что оставим заглушку. Вам нужно будет заменить NGROK_URL на ваш реальный адрес.
    scanner_url = f"{os.getenv('PUBLIC_URL', 'YOUR_PUBLIC_HTTPS_URL_HERE')}/scanner"

    keyboard = [
        [InlineKeyboardButton("🚀 Открыть сканер", web_app=WebAppInfo(url=scanner_url))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите кнопку ниже, чтобы открыть камеру и начать сканирование.",
        reply_markup=reply_markup
    )


def main() -> None:
    """Запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_qr", get_qr))
    application.add_handler(CommandHandler("scan", scan_command))

    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
