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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables with defaults
API_ID = int(os.environ.get("API_ID", 29382018))
API_HASH = os.environ.get("API_HASH", "4734a726c04620c61ec0a28a1ae0d57f")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7317446159:AAFLP_OEPQhHSMX3NQ_99eLqJDMLEXYsLUQ")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1003858672695")
PORT = int(os.environ.get("PORT", 3000))

# Optimized Bot Client
bot = Client(
    "fast_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    max_concurrent_transmissions=10,  # Faster concurrent requests
    parse_mode="html"
)

# Flask app for keeping alive
app = Flask(__name__)

@app.route('/')
def home():
    return f'✅ Bot is alive! Uptime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

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
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"API fetch error: {e}, attempt {attempt+1}")
            if attempt == 2:
                return None
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return None

async def send_post(client, chat_id, item, semaphore):
    """Send a single post with rate limiting"""
    async with semaphore:
        try:
            name = item.get("name", "No Title")[:200]  # Limit title length
            desc = item.get("description", "No Description")[:500]  # Limit description
            date = item.get("upload_date", "Unknown Date")
            thumbnail = item.get("thumbnail", "") or item.get("image", "") or item.get("url", "")
            content_url = item.get("content_url", "#") or item.get("video_url", "#")
            
            # Optimized caption
            caption = f"<b>📌 {name}</b>\n\n{desc}\n\n<b>📅 Upload Date:</b> {date}"
            
            # Truncate caption if too long
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
            
            # Create inline button
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎥 Watch Video", url=content_url)],
                [InlineKeyboardButton("📢 Share", url=f"https://t.me/share/url?url={content_url}")]
            ])
            
            # Send with fallback methods
            if thumbnail and thumbnail.startswith(('http://', 'https://')):
                try:
                    await client.send_photo(
                        chat_id=chat_id,
                        photo=thumbnail,
                        caption=caption,
                        reply_markup=keyboard,
                        disable_notification=True  # Silent mode for faster sending
                    )
                except Exception:
                    # Fallback to text if photo fails
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
            logger.warning(f"Flood wait {e.x} seconds")
            await asyncio.sleep(e.x)
            return False
        except RPCError as e:
            logger.error(f"RPC Error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending post: {e}")
            return False

@bot.on_message(filters.command(["post", "start"]) & filters.private)
async def handle_commands(client, message):
    if message.command[0] == "start":
        await message.reply(
            "🚀 <b>Welcome to Fast Content Bot!</b>\n\n"
            "🔹 Send <code>/post</code> to fetch and post content\n"
            "🔹 Send <code>/status</code> to check bot status\n"
            "🔹 Send <code>/ping</code> to check latency\n\n"
            "<i>⚡ Optimized for blazing fast performance</i>"
        )
        return
    
    # Handle /post command
    status_msg = await message.reply("🔄 <b>Fetching content from API...</b>")
    
    try:
        async with aiohttp.ClientSession() as session:
            api_urls = [
                "https://nsfw-noob-api.vercel.app/xnxx/10/desi",
                "https://xynoob-api.vercel.app/xnxx/10/boobs"  # Fetch more at once
            ]
            
            all_data = []
            for url in api_urls:
                data = await fetch_api_data(session, url)
                if data and data.get("data"):
                    all_data.extend(data["data"])
                await asyncio.sleep(0.5)  # Small delay between API calls
            
            if not all_data:
                await status_msg.edit("❌ No content found or API error")
                return
            
            # Remove duplicates (if any)
            seen = set()
            unique_data = []
            for item in all_data:
                item_id = item.get("id") or item.get("name", "")
                if item_id not in seen:
                    seen.add(item_id)
                    unique_data.append(item)
            
            # Update progress
            total = len(unique_data)
            await status_msg.edit(f"🔄 <b>Processing {total} items...</b>")
            
            # Send posts concurrently
            tasks = []
            for item in unique_data[:30]:  # Limit to 30 items
                task = send_post(client, CHANNEL_ID, item, semaphore)
                tasks.append(task)
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if r is True)
            
            # Final status
            await status_msg.edit(
                f"✅ <b>Successfully posted {success_count}/{total} items!</b>\n\n"
                f"⚡ Performance: {success_count} posts sent\n"
                f"📊 Total processed: {total}\n"
                f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            
    except Exception as e:
        logger.error(f"Error in post command: {e}", exc_info=True)
        await status_msg.edit(f"❌ <b>Error:</b> {str(e)[:200]}")

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message):
    try:
        # Check bot status
        me = await client.get_me()
        chat = await client.get_chat(CHANNEL_ID)
        
        status_text = (
            f"📊 <b>Bot Status</b>\n\n"
            f"🤖 Bot: @{me.username}\n"
            f"📢 Channel: {chat.title}\n"
            f"🆔 Channel ID: {CHANNEL_ID}\n"
            f"⚡ Status: <b>Online</b>\n"
            f"⏰ Uptime: Running\n"
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

# Error handler
@bot.on_error()
async def error_handler(client, update, error):
    logger.error(f"Error: {error}", exc_info=True)
    try:
        if update and hasattr(update, 'chat') and hasattr(update.chat, 'id'):
            await client.send_message(
                update.chat.id,
                f"⚠️ <b>Error occurred:</b>\n<code>{str(error)[:100]}</code>"
            )
    except Exception:
        pass

if __name__ == "__main__":
    # Start Flask server in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    logger.info("🚀 Bot is starting...")
    bot.run()
