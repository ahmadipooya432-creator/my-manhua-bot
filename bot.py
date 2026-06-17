import sqlite3
import asyncio
import logging
import secrets
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = "8882465263:AAFCVqKdpbgYVws8Ky9E6OEd_LR353cy178"
OWNER_ID = 7753975817

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

conn = sqlite3.connect("data.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE, file_id TEXT, file_type TEXT, caption TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
conn.commit()

db_lock = asyncio.Lock()

def get_setting(k, d=""):
    cur.execute("SELECT value FROM settings WHERE key=?", (k,))
    r = cur.fetchone()
    return r[0] if r else d

def set_setting(k, v):
    cur.execute("REPLACE INTO settings VALUES (?,?)", (k, v))
    conn.commit()

async def check_join(user_id, bot):
    channels = get_setting("channels", "").split(",")
    for ch in channels:
        if not ch or not ch.strip(): continue
        try:
            m = await bot.get_chat_member(ch.strip(), user_id)
            if m.status in ["left", "kicked"]: return False
        except: return False
    return True

async def send_file_logic(update, context, token):
    async with db_lock:
        cur.execute("SELECT file_id, file_type, caption FROM files WHERE token=?", (token,))
        row = cur.fetchone()
    if not row:
        await update.effective_message.reply_text("❌ فایل یافت نشد.")
        return
    file_id, file_type, caption = row
    chat_id = update.effective_chat.id
    try:
        if file_type == 'photo': msg = await context.bot.send_photo(chat_id, file_id, caption=caption)
        elif file_type == 'video': msg = await context.bot.send_video(chat_id, file_id, caption=caption)
        else: msg = await context.bot.send_document(chat_id, file_id, caption=caption)
    except: return
    del_time = int(get_setting("delete_time", "0"))
    if del_time > 0:
        await asyncio.sleep(del_time)
        try: await context.bot.delete_message(chat_id, msg.message_id)
        except: pass

async def start(update, context):
    user_id = update.effective_user.id
    if context.args:
        token = context.args[0]
        if not await check_join(user_id, context.bot):
            channels = get_setting("channels", "").split(",")
            btn = [[InlineKeyboardButton(f"Join {c.strip()}", url=f"https://t.me/{c.strip().replace('@','')}")] for c in channels if c.strip()]
            btn.append([InlineKeyboardButton("✅ چک کردن عضویت", callback_data=f"check_{token}")])
            await update.message.reply_text("❌ ابتدا عضو شوید:", reply_markup=InlineKeyboardMarkup(btn))
            return
        await send_file_logic(update, context, token)
        return
    if user_id == OWNER_ID: await show_panel(update)

async def show_panel(update):
    btn = [[InlineKeyboardButton("📂 فایل‌ها", callback_data="manage_files")], [InlineKeyboardButton("⚙️ تنظیمات", callback_data="manage_settings")], [InlineKeyboardButton("➕ افزودن", callback_data="add_file")]]
    if update.message: await update.message.reply_text("🎛 پنل مدیریت", reply_markup=InlineKeyboardMarkup(btn))
    else: await update.callback_query.message.edit_text("🎛 پنل مدیریت", reply_markup=InlineKeyboardMarkup(btn))

async def callback_handler(update, context):
    query = update.callback_query
    if query.data.startswith("check_"):
        if await check_join(query.from_user.id, context.bot):
            try: await query.message.delete()
            except: pass
            await send_file_logic(update, context, query.data.split("_")[1])
        else: await query.answer("❌ عضو نشده‌اید!", show_alert=True)
        return
    if query.from_user.id != OWNER_ID: return
    data = query.data
    if data == "manage_files":
        cur.execute("SELECT id, token FROM files LIMIT 10")
        files = cur.fetchall()
        btn = [[InlineKeyboardButton(f"Token: {f[1][:8]}...", callback_data=f"edit_f_{f[0]}")] for f in files]
        btn.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
        await query.message.edit_text("📂 لیست:", reply_markup=InlineKeyboardMarkup(btn))
    elif data.startswith("edit_f_"):
        context.user_data['editing_f_id'] = data.split("_")[2]
        await query.message.edit_text("📝 کپشن جدید را بفرستید:")
    elif data == "manage_settings":
        btn = [[InlineKeyboardButton("⏳ زمان حذف", callback_data="set_time")], [InlineKeyboardButton("📥 کانال ذخیره", callback_data="set_storage")], [InlineKeyboardButton("📢 کانال‌ها", callback_data="set_channels")], [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]
        await query.message.edit_text("⚙️ تنظیمات:", reply_markup=InlineKeyboardMarkup(btn))
    elif data == "back_main": await show_panel(update)
    elif data == "add_file": context.user_data['state'] = 'adding_file'; await query.message.edit_text("📂 فایل را بفرستید:")
    elif data == "set_time": context.user_data['state'] = 'setting_time'; await query.message.edit_text("⏱ ثانیه:")
    elif data == "set_storage": context.user_data['state'] = 'setting_storage'; await query.message.edit_text("📥 آیدی کانال:")
    elif data == "set_channels": context.user_data['state'] = 'setting_channels'; await query.message.edit_text("📢 کانال‌ها (با , جدا کنید):")

async def message_handler(update, context):
    if update.effective_user.id != OWNER_ID: return
    state = context.user_data.get('state')
    if state == 'adding_file':
        msg = update.message
        f_id, f_type = (msg.document.file_id, 'doc') if msg.document else (msg.video.file_id, 'video') if msg.video else (msg.photo[-1].file_id, 'photo')
        token = f"file_{secrets.token_hex(4)}"
        cur.execute("INSERT INTO files (token, file_id, file_type, caption) VALUES (?,?,?,?)", (token, f_id, f_type, msg.caption or "Default"))
        conn.commit()
        await update.message.reply_text(f"✅ ثبت شد. Token: `{token}`", parse_mode="Markdown")
        context.user_data['state'] = None
    elif state == 'setting_time': set_setting("delete_time", update.message.text); await update.message.reply_text("✅"); context.user_data['state'] = None
    elif state == 'setting_storage': set_setting("storage_channel", update.message.text); await update.message.reply_text("✅"); context.user_data['state'] = None
    elif state == 'setting_channels': set_setting("channels", update.message.text); await update.message.reply_text("✅"); context.user_data['state'] = None

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
app.run_polling()