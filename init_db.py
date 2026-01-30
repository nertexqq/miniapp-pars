"""
Script for initializing MySQL database
Run this script once before starting the bot
"""

import asyncio
import aiomysql
import logging
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        pass

from config import DB_HOST, DB_USER, DB_PASS, DB_NAME

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_database():
    """Create database and table"""
    try:
        # Connect to MySQL without specifying database
        conn = await aiomysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            db=None  # Connect without database
        )
        
        async with conn.cursor() as cur:
            # Create database if not exists
            await cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            logger.info(f"Database '{DB_NAME}' created or already exists")
            
            # Select database
            await cur.execute(f"USE {DB_NAME}")
            
            # Create table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS gifts (
                    name VARCHAR(255) NOT NULL,
                    model VARCHAR(255),
                    price FLOAT DEFAULT 0,
                    floor_price FLOAT DEFAULT 0,
                    photo_url TEXT,
                    model_rarity VARCHAR(50),
                    user_id BIGINT NOT NULL,
                    PRIMARY KEY (user_id, name(255), model(255))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            logger.info("Table 'gifts' created or already exists")
            
            await conn.commit()
        
        conn.close()
        logger.info("Database initialization completed successfully!")
        return True
        
    except aiomysql.Error as e:
        logger.error(f"MySQL Error: {e}")
        return False
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


if __name__ == "__main__":
    print("Initializing database...")
    print(f"Host: {DB_HOST}")
    print(f"User: {DB_USER}")
    print(f"Database: {DB_NAME}")
    print()
    
    success = asyncio.run(init_database())
    
    if success:
        print("\nDatabase initialized successfully!")
        print("You can now run the bot: python bot.py")
    else:
        print("\nError initializing database")
        print("Check:")
        print("1. MySQL server is running")
        print("2. Connection data in .env file is correct")
        print("3. User has permissions to create databases")

