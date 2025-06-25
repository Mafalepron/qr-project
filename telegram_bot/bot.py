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
    """Обрабатывает команду /start. Приветствует пользователя и информирует админов."""
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
    """Обрабатывает команду /get_qr. Запрашивает у бэкенда QR-код и отправляет его пользователю."""
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
    """(Только для админов) Отправляет кнопку для запуска Web App сканера."""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    public_url = os.getenv('PUBLIC_URL')
    if not public_url:
        await update.message.reply_text("Ошибка: Публичный URL (PUBLIC_URL) не настроен в .env файле. Сканирование невозможно.")
        return
    
    if not public_url.startswith("https://"):
        await update.message.reply_text(
            "Ошибка: Публичный URL должен начинаться с https://. "
            "Пожалуйста, убедитесь, что вы используете ngrok или аналогичный сервис и правильно указали URL."
        )
        return
        
    scanner_url = f"{public_url}/scanner"
    # Создаем кнопку, которая открывает Web App
    keyboard = [[InlineKeyboardButton("🚀 Открыть сканер", web_app=WebAppInfo(url=scanner_url))]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение с этой кнопкой
    await update.message.reply_text(
        "Нажмите кнопку ниже, чтобы открыть камеру и начать сканирование.",
        reply_markup=reply_markup
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Доступ запрещён.")
        return
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_API_URL}/stats", timeout=10)
            data = response.json()
            await update.message.reply_text(
                f"📊 Общая статистика:\n"
                f"✅ Всего успешно: {data.get('success', 0)}\n"
                f"⛔ Всего отклонено: {data.get('fail', 0)}"
            )
    except Exception as e:
        await update.message.reply_text("Ошибка при получении статистики.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует ошибки, полученные от Telegram."""
    logger.error("Произошло исключение при обработке обновления:", exc_info=context.error)


def main() -> None:
    """Основная функция: настраивает и запускает бота."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен бота не найден в .env файле! Завершение работы.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_qr", get_qr))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_error_handler(error_handler)

    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
