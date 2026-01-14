
from bot import ArbitrageBot
from logger import logger

def main():
    import time
    while True:
        try:
            logger.info("--- Starting Bot Instance ---")
            bot = ArbitrageBot()
            bot.initialize()
            bot.run()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.critical(f"Fatal error in main: {e}")
            logger.info("Restarting bot in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
