"""
Точка входа в приложение
"""

import asyncio
import logging
import signal
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .di import container
from .middlewares.logging import LoggingMiddleware
from .middlewares.throttling import ThrottlingMiddleware
from .middlewares.errors import ErrorMiddleware
from .middlewares.access import AccessControlMiddleware
from .handlers import register_all_handlers

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Инициализация при запуске"""
    logger.info("Starting bot...")
    
    # Инициализируем зависимости
    await container.init_bot()
    await container.init_db_pool()
    await container.init_dispatcher()
    
    # Инициализируем БД
    db_service = await container.get_db_service()
    await db_service.init_schema()
    
    logger.info("Bot started successfully")


async def on_shutdown(bot: Bot):
    """Очистка при остановке"""
    logger.info("Shutting down bot...")
    await container.shutdown()
    logger.info("Bot stopped")


async def main():
    """Главная функция"""
    # Инициализируем бота и диспетчер
    bot = await container.init_bot()
    dp = await container.init_dispatcher()
    
    # Регистрируем миддлвари (порядок важен!)
    # 1. Access Control - проверка доступа (первым, чтобы блокировать неавторизованных)
    dp.message.middleware(AccessControlMiddleware())
    dp.callback_query.middleware(AccessControlMiddleware())
    
    # 2. Logging - логирование
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    
    # 3. Throttling - ограничение частоты
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    
    # 4. Error handling - обработка ошибок (последним)
    dp.message.middleware(ErrorMiddleware())
    dp.callback_query.middleware(ErrorMiddleware())
    
    # Регистрируем хэндлеры
    register_all_handlers(dp)
    
    # Запускаем фоновые задачи
    from .tasks.scheduler import start_background_tasks
    await start_background_tasks()
    
    # Настройка graceful shutdown
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(on_shutdown(bot))
    
    signal.signal(signal.SIGINT, lambda s, f: signal_handler())
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler())
    
    # Запуск
    try:
        # Webhook режим (если указан WEBHOOK_URL)
        webhook_url = getattr(settings, 'WEBHOOK_URL', None)
        if webhook_url:
            await bot.set_webhook(webhook_url)
            app = web.Application()
            webhook_requests_handler = SimpleRequestHandler(
                dispatcher=dp,
                bot=bot,
            )
            webhook_requests_handler.register(app, path="/webhook")
            setup_application(app, dp, bot=bot)
            
            await on_startup(bot)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=8000)
            await site.start()
            logger.info("Webhook server started on port 8000")
            
            # Держим приложение запущенным
            await asyncio.Event().wait()
        else:
            # Polling режим
            await on_startup(bot)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Error in main: {e}", exc_info=True)
    finally:
        await on_shutdown(bot)


if __name__ == "__main__":
    asyncio.run(main())

