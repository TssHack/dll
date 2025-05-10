from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, CallbackQueryHandler, filters
from telegram.constants import ParseMode
import json
import requests
import os
import logging
from datetime import datetime
import aiohttp
import asyncio
import random
from urllib.parse import urlparse
import re
import sqlite3
import threading

# تنظیم لاگر
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تنظیمات ربات
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_IDS = [123456789]  # آی‌دی‌های ادمین را اینجا وارد کنید
CHANNEL_ID = "@YOUR_CHANNEL"  # آی‌دی کانال برای جوین اجباری

# آدرس‌های API
API_INSTA = "http://amirplus.alfahost.space/api/downloader/insta-2.php?url="
API_PINTEREST = "http://amirplus.alfahost.space/api/downloader/pinterest.php?url="
API_TIKTOK = "http://amirplus.alfahost.space/api/downloader/tiktok.php?url="

# متغیر قفل برای عملیات همزمان با دیتابیس
db_lock = threading.Lock()

# کلاس مدیریت دیتابیس SQLite
class DatabaseManager:
    def __init__(self, db_file="bot_database.db"):
        self.db_file = db_file
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_file)
    
    def init_db(self):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # جدول کاربران
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TEXT,
                downloads INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
            ''')
            
            # جدول تنظیمات
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            ''')
            
            # افزودن تنظیمات پیش‌فرض اگر وجود نداشته باشند
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                         ("mandatory_join", "1"))
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                         ("bot_active", "1"))
            
            conn.commit()
            conn.close()
    
    def add_user(self, user_id, username, first_name, last_name):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date, downloads) 
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, join_date, 0))
            
            conn.commit()
            conn.close()
    
    def increment_downloads(self, user_id):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE users SET downloads = downloads + 1 WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
    
    def ban_user(self, user_id):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE users SET is_banned = 1 WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
    
    def unban_user(self, user_id):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE users SET is_banned = 0 WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
    
    def is_user_banned(self, user_id):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT is_banned FROM users WHERE user_id = ?
            ''', (user_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result is None:
                return False
            
            return bool(result[0])
    
    def get_setting(self, key):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT value FROM settings WHERE key = ?
            ''', (key,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result is None:
                return None
            
            return result[0]
    
    def update_setting(self, key, value):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE settings SET value = ? WHERE key = ?
            ''', (value, key))
            
            conn.commit()
            conn.close()
    
    def get_all_users(self):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT user_id FROM users WHERE is_banned = 0
            ''')
            
            users = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            return users
    
    def get_stats(self):
        with db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
            banned_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT SUM(downloads) FROM users')
            total_downloads = cursor.fetchone()[0] or 0
            
            conn.close()
            
            return {
                'total_users': total_users,
                'banned_users': banned_users,
                'total_downloads': total_downloads
            }

# ایجاد نمونه از مدیریت دیتابیس
db = DatabaseManager()

# تشخیص نوع لینک
def detect_link_type(url):
    if "instagram.com" in url or "instagr.am" in url:
        return "instagram"
    elif "tiktok.com" in url:
        return "tiktok"
    elif "pinterest.com" in url or "pin.it" in url:
        return "pinterest"
    else:
        return None

# بررسی عضویت کاربر در کانال
async def check_user_membership(user_id, bot):
    mandatory_join = db.get_setting("mandatory_join") == "1"
    if not mandatory_join:
        return True
    
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status = chat_member.status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {str(e)}")
        return False

# دکمه‌های جوین به کانال
def get_join_markup():
    keyboard = [
        [InlineKeyboardButton("عضویت در کانال ما", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")],
        [InlineKeyboardButton("بررسی عضویت", callback_data="check_membership")]
    ]
    return InlineKeyboardMarkup(keyboard)

# منوی اصلی
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📥 راهنمای استفاده", callback_data="help")],
        [InlineKeyboardButton("👨‍💻 ارتباط با توسعه‌دهندگان", url="https://t.me/YOUR_SUPPORT_USERNAME")]
    ]
    return InlineKeyboardMarkup(keyboard)

# منوی ادمین
def get_admin_menu():
    join_status = "✅ فعال" if db.get_setting("mandatory_join") == "1" else "❌ غیرفعال"
    bot_status = "✅ فعال" if db.get_setting("bot_active") == "1" else "❌ غیرفعال"
    
    keyboard = [
        [InlineKeyboardButton(f"وضعیت جوین اجباری: {join_status}", callback_data="toggle_join")],
        [InlineKeyboardButton(f"وضعیت ربات: {bot_status}", callback_data="toggle_bot")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="stats")],
        [InlineKeyboardButton("📨 ارسال پیام همگانی", callback_data="broadcast")],
        [InlineKeyboardButton("🚫 مدیریت کاربران", callback_data="user_management")]
    ]
    return InlineKeyboardMarkup(keyboard)

# هندلر شروع
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    
    # ثبت کاربر در دیتابیس
    db.add_user(user_id, user.username, user.first_name, user.last_name)
    
    # بررسی وضعیت بن
    if db.is_user_banned(user_id):
        await update.message.reply_text("⛔️ شما از استفاده از این ربات محروم شده‌اید.")
        return
    
    # بررسی وضعیت ربات
    if db.get_setting("bot_active") != "1" and user_id not in ADMIN_IDS:
        await update.message.reply_text("🔧 ربات در حال حاضر در دسترس نمی‌باشد. لطفاً بعداً مراجعه کنید.")
        return
    
    welcome_text = f"""
🌟 *به ربات دانلودر چندرسانه‌ای خوش آمدید* 🌟

با استفاده از این ربات می‌توانید محتوا را از پلتفرم‌های زیر دانلود کنید:
• اینستاگرام
• تیک‌تاک
• پینترست

🔹 *راهنمای استفاده*:
فقط کافیست لینک مورد نظر خود را ارسال کنید!
    """
    
    # بررسی عضویت کاربر
    is_member = await check_user_membership(user_id, context.bot)
    
    if not is_member and db.get_setting("mandatory_join") == "1":
        await update.message.reply_text(
            "👋 برای استفاده از ربات ابتدا در کانال ما عضو شوید:",
            reply_markup=get_join_markup()
        )
    else:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu())

# هندلر پیام‌های متنی
async def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text
    
    # بررسی وضعیت بن
    if db.is_user_banned(user_id):
        return
    
    # بررسی وضعیت ربات
    if db.get_setting("bot_active") != "1" and user_id not in ADMIN_IDS:
        await update.message.reply_text("🔧 ربات در حال حاضر در دسترس نمی‌باشد. لطفاً بعداً مراجعه کنید.")
        return
    
    # بررسی حالت انتظار برای دریافت پیام همگانی
    if user_id in ADMIN_IDS and context.user_data.get('awaiting_broadcast'):
        context.user_data['awaiting_broadcast'] = False
        context.user_data['broadcast_message'] = text
        
        confirm_keyboard = [
            [InlineKeyboardButton("✅ ارسال", callback_data="confirm_broadcast")],
            [InlineKeyboardButton("❌ انصراف", callback_data="back_to_admin")]
        ]
        
        await update.message.reply_text(
            f"📣 *پیش‌نمایش پیام همگانی*\n\n{text}\n\nآیا از ارسال این پیام به تمام کاربران اطمینان دارید؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(confirm_keyboard)
        )
        return
    
    # بررسی حالت انتظار برای دریافت آی‌دی کاربر برای بن/آنبن
    if user_id in ADMIN_IDS and context.user_data.get('awaiting_user_id_for_ban'):
        context.user_data['awaiting_user_id_for_ban'] = False
        try:
            target_user_id = int(text)
            db.ban_user(target_user_id)
            await update.message.reply_text(f"✅ کاربر با آی‌دی {target_user_id} با موفقیت بن شد.")
        except ValueError:
            await update.message.reply_text("❌ آی‌دی وارد شده معتبر نیست. لطفاً یک عدد صحیح وارد کنید.")
        return
    
    if user_id in ADMIN_IDS and context.user_data.get('awaiting_user_id_for_unban'):
        context.user_data['awaiting_user_id_for_unban'] = False
        try:
            target_user_id = int(text)
            db.unban_user(target_user_id)
            await update.message.reply_text(f"✅ کاربر با آی‌دی {target_user_id} با موفقیت آنبن شد.")
        except ValueError:
            await update.message.reply_text("❌ آی‌دی وارد شده معتبر نیست. لطفاً یک عدد صحیح وارد کنید.")
        return
    
    # بررسی دستورات ادمین
    if user_id in ADMIN_IDS and text == "/admin":
        await update.message.reply_text("🔐 *پنل مدیریت ربات*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_menu())
        return
    
    # تشخیص لینک
    link_type = detect_link_type(text)
    
    if not link_type:
        await update.message.reply_text("❌ لینک معتبر نیست. لطفاً لینک معتبری از اینستاگرام، تیک‌تاک یا پینترست ارسال کنید.")
        return
    
    # بررسی عضویت کاربر
    is_member = await check_user_membership(user_id, context.bot)
    
    if not is_member and db.get_setting("mandatory_join") == "1":
        await update.message.reply_text(
            "👋 برای استفاده از ربات ابتدا در کانال ما عضو شوید:",
            reply_markup=get_join_markup()
        )
        return
    
    # ارسال پیام در حال پردازش
    progress_message = await update.message.reply_text("🔄 در حال پردازش لینک...")
    
    try:
        # پردازش لینک بر اساس نوع
        if link_type == "instagram":
            await download_instagram(update, context, text, progress_message)
        elif link_type == "tiktok":
            await download_tiktok(update, context, text, progress_message)
        elif link_type == "pinterest":
            await download_pinterest(update, context, text, progress_message)
        
        # افزایش تعداد دانلودهای کاربر
        db.increment_downloads(user_id)
            
    except Exception as e:
        logger.error(f"Error processing link: {str(e)}")
        await progress_message.edit_text(f"❌ خطا در پردازش لینک:\n{str(e)}")

# دانلود از اینستاگرام
async def download_instagram(update: Update, context: CallbackContext, url: str, progress_message):
    # بروزرسانی پیام پیشرفت
    await progress_message.edit_text("⏳ در حال دانلود از اینستاگرام... (25%)")
    
    async with aiohttp.ClientSession() as session:
        # فراخوانی API
        async with session.get(API_INSTA + url) as response:
            await progress_message.edit_text("⏳ در حال دانلود از اینستاگرام... (50%)")
            
            if response.status != 200:
                await progress_message.edit_text("❌ خطا در دریافت اطلاعات از اینستاگرام.")
                return
            
            data = await response.json()
            await progress_message.edit_text("⏳ در حال دانلود از اینستاگرام... (75%)")
            
            if 'video' in data and len(data['video']) > 0:
                video_url = data['video'][0]['video']
                thumbnail = data['video'][0]['thumbnail']
                
                # ارسال ویدیو
                await progress_message.edit_text("⏳ در حال آپلود ویدیو... (90%)")
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_url,
                    caption="🎬 دانلود شده با ربات دانلودر چندرسانه‌ای",
                    supports_streaming=True
                )
                await progress_message.delete()
            else:
                await progress_message.edit_text("❌ ویدیو یافت نشد یا فرمت داده‌های دریافتی نامعتبر است.")

# دانلود از پینترست
async def download_pinterest(update: Update, context: CallbackContext, url: str, progress_message):
    # بروزرسانی پیام پیشرفت
    await progress_message.edit_text("⏳ در حال دانلود از پینترست... (25%)")
    
    async with aiohttp.ClientSession() as session:
        # فراخوانی API
        async with session.get(API_PINTEREST + url) as response:
            await progress_message.edit_text("⏳ در حال دانلود از پینترست... (50%)")
            
            if response.status != 200:
                await progress_message.edit_text("❌ خطا در دریافت اطلاعات از پینترست.")
                return
            
            data = await response.json()
            await progress_message.edit_text("⏳ در حال دانلود از پینترست... (75%)")
            
            # یافتن بهترین تصویر (با بالاترین کیفیت)
            best_image = None
            if 'thumbnails' in data and len(data['thumbnails']) > 0:
                # مرتب‌سازی بر اساس ابعاد تصویر
                thumbnails = sorted(data['thumbnails'], key=lambda x: x.get('width', 0) * x.get('height', 0), reverse=True)
                if thumbnails:
                    best_image = thumbnails[0]['url']
            
            if best_image:
                # ارسال تصویر
                await progress_message.edit_text("⏳ در حال آپلود تصویر... (90%)")
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=best_image,
                    caption="🖼 دانلود شده با ربات دانلودر چندرسانه‌ای"
                )
                await progress_message.delete()
            else:
                await progress_message.edit_text("❌ تصویر یافت نشد یا فرمت داده‌های دریافتی نامعتبر است.")

# دانلود از تیک‌تاک
async def download_tiktok(update: Update, context: CallbackContext, url: str, progress_message):
    await progress_message.edit_text("⏳ در حال دانلود از تیک‌تاک... (25%)")
    
    async with aiohttp.ClientSession() as session:
        # فراخوانی API
        async with session.get(API_TIKTOK + url) as response:
            await progress_message.edit_text("⏳ در حال دانلود از تیک‌تاک... (50%)")
            
            if response.status != 200:
                await progress_message.edit_text("❌ خطا در دریافت اطلاعات از تیک‌تاک.")
                return
            
            try:
                data = await response.json()
                await progress_message.edit_text("⏳ در حال دانلود از تیک‌تاک... (75%)")
                
                if data.get('success') and data.get('data'):
                    # ابتدا تلاش برای دانلود نسخه HD بدون واترمارک
                    video_url = None
                    
                    if 'Download without watermark (HD)' in data['data'] and data['data']['Download without watermark (HD)']:
                        video_url = data['data']['Download without watermark (HD)'][0]
                    elif 'Download without watermark' in data['data'] and data['data']['Download without watermark']:
                        video_url = data['data']['Download without watermark'][0]
                    elif 'Download watermark' in data['data'] and data['data']['Download watermark']:
                        video_url = data['data']['Download watermark'][0]
                    
                    if video_url:
                        # ارسال ویدیو
                        await progress_message.edit_text("⏳ در حال آپلود ویدیو... (90%)")
                        try:
                            await context.bot.send_video(
                                chat_id=update.effective_chat.id,
                                video=video_url,
                                caption="🎬 دانلود شده با ربات دانلودر چندرسانه‌ای",
                                supports_streaming=True
                            )
                            await progress_message.delete()
                        except Exception as e:
                            # اگر ارسال ویدیو با مشکل مواجه شد، لینک مستقیم را ارسال کنیم
                            await progress_message.edit_text(
                                f"⚠️ ارسال مستقیم ویدیو با مشکل مواجه شد. می‌توانید از لینک زیر دانلود کنید:\n\n{video_url}"
                            )
                    else:
                        await progress_message.edit_text("❌ هیچ لینک ویدیویی یافت نشد.")
                else:
                    await progress_message.edit_text("❌ داده‌های دریافتی از API تیک‌تاک نامعتبر است.")
            except Exception as e:
                await progress_message.edit_text(f"❌ خطا در پردازش پاسخ تیک‌تاک: {str(e)}")

# کالبک هندلر
async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    # بررسی وضعیت بن
    if db.is_user_banned(user_id):
        await query.answer("⛔️ شما از استفاده از این ربات محروم شده‌اید.")
        return
    
    await query.answer()
    
    # پردازش کالبک‌های مختلف
    if data == "check_membership":
        is_member = await check_user_membership(user_id, context.bot)
        if is_member:
            await query.message.edit_text(
                "✅ عضویت شما تأیید شد. اکنون می‌توانید از ربات استفاده کنید!",
                reply_markup=get_main_menu()
            )
        else:
            await query.message.edit_text(
                "❌ شما هنوز عضو کانال نیستید. برای استفاده از ربات لطفاً عضو شوید:",
                reply_markup=get_join_markup()
            )
    
    elif data == "help":
        help_text = """
📚 *راهنمای استفاده از ربات* 📚

برای دانلود محتوا، کافیست لینک مورد نظر خود را از یکی از پلتفرم‌های زیر ارسال کنید:

*اینستاگرام*: لینک پست، ریل یا استوری
*تیک‌تاک*: لینک ویدیو
*پینترست*: لینک پین

🔹 ربات به صورت خودکار نوع لینک را تشخیص داده و محتوا را برای شما دانلود می‌کند.
        """
        await query.message.edit_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu())
    
    # کالبک‌های مدیریتی (فقط برای ادمین‌ها)
    elif data == "toggle_join" and user_id in ADMIN_IDS:
        current_value = db.get_setting("mandatory_join")
        new_value = "0" if current_value == "1" else "1"
        db.update_setting("mandatory_join", new_value)
        await query.message.edit_text("🔐 *پنل مدیریت ربات*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_menu())
    
    elif data == "toggle_bot" and user_id in ADMIN_IDS:
        current_value = db.get_setting("bot_active")
        new_value = "0" if current_value == "1" else "1"
        db.update_setting("bot_active", new_value)
        await query.message.edit_text("🔐 *پنل مدیریت ربات*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_menu())
    
    elif data == "stats" and user_id in ADMIN_IDS:
        stats = db.get_stats()
        
        stats_text = f"""
📊 *آمار ربات* 📊

👥 تعداد کاربران: {stats['total_users']}
📥 تعداد دانلودها: {stats['total_downloads']}
🚫 کاربران محروم: {stats['banned_users']}

📅 تاریخ بروزرسانی: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        """
        
        back_button = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_admin")]]
        await query.message.edit_text(stats_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_button))
    
    elif data == "broadcast" and user_id in ADMIN_IDS:
        # ذخیره وضعیت فعلی در context برای استفاده در مراحل بعدی
        context.user_data['awaiting_broadcast'] = True
        
        back_button = [[InlineKeyboardButton("🔙 انصراف", callback_data="back_to_admin")]]
        await query.message.edit_text(
            "📣 *ارسال پیام همگانی*\n\nلطفاً پیام مورد نظر خود را ارسال کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(back_button)
        )
    
    elif data == "confirm_broadcast" and user_id in ADMIN_IDS:
        broadcast_message = context.user_data.get('broadcast_message', '')
        if not broadcast_message:
            await