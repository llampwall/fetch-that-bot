import logging
import os
import sys

from telegram.ext import Application, MessageHandler, filters

from config import BOT_TOKEN, WEBHOOK_PATH, WEBHOOK_PORT, WEBHOOK_URL, TEMP_DIR
from handlers import handle_message

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("fetch")


def main() -> None:
    if not BOT_TOKEN:
        logger.error("FETCH_BOT_TOKEN not set. Get one from @BotFather on Telegram.")
        sys.exit(1)
    if not WEBHOOK_URL:
        logger.error("FETCH_WEBHOOK_URL not set. Example: https://yourtunnel.com/webhook/fetch")
        sys.exit(1)

    # Ensure temp dir exists
    os.makedirs(TEMP_DIR, exist_ok=True)

    logger.info("Starting Fetch bot...")
    logger.info("Webhook URL: %s", WEBHOOK_URL)
    logger.info("Listening on port: %d", WEBHOOK_PORT)

    app = Application.builder().token(BOT_TOKEN).build()

    # Handle all text messages (not commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start webhook server
    app.run_webhook(
        listen="0.0.0.0",
        port=WEBHOOK_PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL,
    )


if __name__ == "__main__":
    main()
