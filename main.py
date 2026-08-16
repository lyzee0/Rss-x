import os
import asyncio
import aiohttp
from asyncio import Semaphore
from datetime import datetime
from threading import Thread
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, RPCError
import logging
import tgcrypto  # Add this for speed optimization

# Install tgcrypto: pip install tgcrypto

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
API_ID = int(os.environ.get("API_ID", 29382018))
API_HASH = os.environ.get("API_HASH", "4734a726c04620c61ec0a28a1ae0d57f")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8027197031:AAHhjRgVcA5QlfcryW6EAm2PrIUHS3kMXoU")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1002616383974")
PORT = int(os.environ.get("PORT", 3000))

# Optimized Bot Client with TgCrypto
bot = Client(
    "fast_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    max_concurrent_transmissions=10,
    parse_mode="html",
    sleep_threshold=30  # Auto handle flood waits
)

# Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return f'✅ Bot is alive! Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

@app.route('/health')
def health():
    return 'OK', 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)

# Global semaphore for rate limiting
semaphore = Semaphore(5)

async def fetch_api_data(session, url):
    """Async fetch with retry logic"""
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"API returned {response.status}, attempt {attempt+1}")
                if response.status == 404:
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"API fetch error: {e}, attempt {attempt+1}")
            if attempt == 2:
                return None
            await asyncio.sleep(2 ** attempt)
    return None

async def send_post(client, chat_id, item, semaphore):
    """Send a single post with rate limiting"""
    async with semaphore:
        try:
            # Extract data with fallbacks
            name = item.get("name", "No Title")[:200]
            desc = item.get("description", "No Description")[:500]
            date = item.get("upload_date", "Unknown Date")
            
            # Try multiple possible thumbnail fields
            thumbnail = (
                item.get("thumbnail") or 
                item.get("image") or 
                item.get("url") or 
                item.get("cover") or
                ""
            )
            
            # Try multiple possible content URLs
            content_url = (
                item.get("content_url") or 
                item.get("video_url") or 
                item.get("link") or 
                item.get("url") or 
                "#"
            )
            
            # Create caption
            caption = f"<b>📌 {name}</b>\n\n{desc}\n\n<b>📅 Upload Date:</b> {date}"
            
            # Truncate if too long
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            
            # Create inline keyboard
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎥 Watch Video", url=content_url)],
                [InlineKeyboardButton("📢 Share", url=f"https://t.me/share/url?url={content_url}")]
            ])
            
            # Send based on content type
            if thumbnail and thumbnail.startswith(('http://', 'https://')):
                try:
                    await client.send_photo(
                        chat_id=chat_id,
                        photo=thumbnail,
                        caption=caption,
                        reply_markup=keyboard,
                        disable_notification=True
                    )
                except Exception as e:
                    logger.warning(f"Photo send failed, using text: {e}")
                    await client.send_message(
                        chat_id=chat_id,
                        text=caption,
                        reply_markup=keyboard,
                        disable_notification=True
                    )
            else:
                await client.send_message(
                    chat_id=chat_id,
                    text=caption,
                    reply_markup=keyboard,
                    disable_notification=True
                )
            return True
            
        except FloodWait as e:
            logger.warning(f"Flood wait {e.value} seconds")
            await asyncio.sleep(e.value)
            return False
        except RPCError as e:
            logger.error(f"RPC Error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending post: {e}")
            return False

# Command Handlers
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply(
        "🚀 <b>Welcome to Fast Content Bot!</b>\n\n"
        "🔹 Send <code>/post</code> to fetch and post content\n"
        "🔹 Send <code>/status</code> to check bot status\n"
        "🔹 Send <code>/ping</code> to check latency\n\n"
        "<i>⚡ Optimized with TgCrypto for blazing speed</i>"
    )

@bot.on_message(filters.command("post") & filters.private)
async def post_command(client, message):
    status_msg = await message.reply("🔄 <b>Fetching content from API...</b>")
    
    try:
        async with aiohttp.ClientSession() as session:
            api_urls = [
                "https://nsfw-noob-api.vercel.app/xnxx/10/desi",
                "https://xynoob-api.vercel.app/xnxx/10/boobs"
            ]
            
            all_data = []
            for url in api_urls:
                data = await fetch_api_data(session, url)
                if data and data.get("data"):
                    all_data.extend(data["data"])
                await asyncio.sleep(0.3)
            
            if not all_data:
                await status_msg.edit("❌ No content found or API error")
                return
            
            # Remove duplicates
            seen = set()
            unique_data = []
            for item in all_data:
                item_id = item.get("id") or item.get("name", str(item))
                if item_id not in seen:
                    seen.add(item_id)
                    unique_data.append(item)
            
            total = len(unique_data)
            await status_msg.edit(f"🔄 <b>Processing {total} items...</b>")
            
            # Process in batches for better performance
            batch_size = 10
            success_count = 0
            
            for i in range(0, min(total, 30), batch_size):
                batch = unique_data[i:i+batch_size]
                tasks = [send_post(client, CHANNEL_ID, item, semaphore) for item in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                success_count += sum(1 for r in results if r is True)
                
                # Update progress
                await status_msg.edit(
                    f"🔄 <b>Progress: {min(i+batch_size, 30)}/{min(total, 30)}</b>\n"
                    f"✅ Success: {success_count}"
                )
            
            # Final status
            await status_msg.edit(
                f"✅ <b>Successfully posted {success_count} items!</b>\n\n"
                f"⚡ Total processed: {min(total, 30)}\n"
                f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}\n"
                f"🚀 Speed: <b>Optimized with TgCrypto</b>"
            )
            
    except Exception as e:
        logger.error(f"Error in post command: {e}", exc_info=True)
        await status_msg.edit(f"❌ <b>Error:</b> {str(e)[:200]}")

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message):
    try:
        me = await client.get_me()
        chat = await client.get_chat(CHANNEL_ID)
        
        # Check if TgCrypto is working
        try:
            import tgcrypto
            crypto_status = "✅ Active"
        except ImportError:
            crypto_status = "❌ Not installed (slower)"
        
        status_text = (
            f"📊 <b>Bot Status</b>\n\n"
            f"🤖 Bot: @{me.username}\n"
            f"📢 Channel: {chat.title}\n"
            f"🆔 Channel ID: {CHANNEL_ID}\n"
            f"⚡ Status: <b>Online</b>\n"
            f"🔐 TgCrypto: {crypto_status}\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await message.reply(status_text)
    except Exception as e:
        await message.reply(f"❌ Status check failed: {e}")

@bot.on_message(filters.command("ping") & filters.private)
async def ping_command(client, message):
    start = datetime.now()
    await client.send_chat_action(message.chat.id, "typing")
    end = datetime.now()
    latency = (end - start).total_seconds() * 1000
    await message.reply(f"🏓 <b>Pong!</b>\n\n⚡ Latency: <code>{latency:.2f}ms</code>")

# Global error handler for all messages
@bot.on_message(filters.all)
async def global_error_handler(client, message):
    # This catches all messages and handles errors gracefully
    pass

# Exception handler for the bot
@bot.on_exception()
async def exception_handler(client, update, exception):
    logger.error(f"Global exception: {exception}", exc_info=True)
    try:
        if update and hasattr(update, 'chat') and hasattr(update.chat, 'id'):
            await client.send_message(
                update.chat.id,
                f"⚠️ <b>Error occurred:</b>\n<code>{str(exception)[:100]}</code>"
            )
    except Exception:
        pass

if __name__ == "__main__":
    # Check TgCrypto
    try:
        import tgcrypto
        logger.info("✅ TgCrypto is installed - FAST mode enabled")
    except ImportError:
        logger.warning("⚠️ TgCrypto not installed - Install it for faster performance: pip install tgcrypto")
    
    # Start Flask server
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    logger.info("🚀 Bot is starting with optimized performance...")
    bot.run()
