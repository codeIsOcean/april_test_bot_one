#!/usr/bin/env python3
"""
Главный файл для запуска бота через кнопку Play в IDE
"""

import sys
import os
import asyncio

# Добавляем корневую директорию в PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Устанавливаем рабочую директорию
os.chdir(current_dir)

from bot.bot import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
