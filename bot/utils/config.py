import os
from dotenv import load_dotenv

# Всегда ищем .env относительно корня проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Получаем путь до .env файла. Локальная загрузка
env_path = os.getenv("ENV_PATH", os.path.join(BASE_DIR, ".env.dev"))
print(f" 🔃 Загрузка .env из: {env_path}")
load_dotenv(dotenv_path=env_path)

env_path = os.getenv("ENV_PATH", ".env.dev")
print(f"🔃 Загрузка env из: {env_path}")
print(f"📁 Абсолютный путь: {os.path.abspath(env_path)}")
print(f"📁 Текущая рабочая директория: {os.getcwd()}")

# Вытаскиваем переменные из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
raw_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]

# Выводим в терминале для проверки
print(f"BOT_TOKEN: {BOT_TOKEN}")
print(f"DATABASE_URL: {DATABASE_URL}")
print(f"LOG_CHANNEL_ID: {LOG_CHANNEL_ID}")
print(f"[DEBUG] BOT_TOKEN = {repr(BOT_TOKEN)}")
