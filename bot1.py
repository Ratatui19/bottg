import logging
import sqlite3
import html
import time
import asyncio
import math
import os  # Для работы с переменными окружения Render
import threading  # Для параллельного запуска веб-сервера
from flask import Flask  # Для обхода ошибки портов на Render
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants, BotCommand, BotCommandScopeChat, BotCommandScopeAllPrivateChats
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# === БЛОК ОБХОДА ОШИБКИ PORT SCAN (ДЛЯ БЕСПЛАТНОГО RENDER) ===
app_web = Flask('')

@app_web.route('/')
def home():
    return "Бот работает стабильно! 🚀"

def run_web():
    # Render передает порт в переменную среды PORT
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

# Запускаем Flask в отдельном потоке
threading.Thread(target=run_web, daemon=True).start()
# ==========================================================

# ОПТИМИЗАЦИЯ: Уровень логирования WARNING
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# === КОНФИГУРАЦИЯ ===
TOKEN = "8213858702:AAFS23dAJDViTymEeEPzeh50cpwe8l2VwS0"
LOG_GROUP_ID = -1003316835520 

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect('messages_log.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS global_ban (user_id INTEGER PRIMARY KEY, reason TEXT, expire_at INTEGER)')
    cursor.execute('CREATE TABLE IF NOT EXISTS msg_count (id INTEGER PRIMARY KEY, total INTEGER)')
    cursor.execute('CREATE TABLE IF NOT EXISTS reply_map (msg_id INTEGER, chat_id INTEGER, original_sender_id INTEGER, created_at INTEGER, PRIMARY KEY(msg_id, chat_id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS local_blocks (owner_id INTEGER, blocked_id INTEGER, PRIMARY KEY(owner_id, blocked_id))')
    conn.commit()
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def is_locally_blocked(owner_id, sender_id):
    conn = sqlite3.connect('messages_log.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM local_blocks WHERE owner_id = ? AND blocked_id = ?', (owner_id, sender_id))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def get_ban_info(user_id):
    conn = sqlite3.connect('messages_log.db')
    cursor = conn.cursor()
    cursor.execute('SELECT reason, expire_at FROM global_ban WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    if res:
        reason, expire_at = res
        if expire_at and time.time() > expire_at:
            conn = sqlite3.connect('messages_log.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM global_ban WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            return None
        return res
    return None

def format_ban_message(reason, expire_at):
    time_str = datetime.fromtimestamp(expire_at).strftime('%d.%m.%Y %H:%M') if expire_at else "Навсегда ♾"
    text = (f"🚫 <b>Доступ ограничен</b>\n"
            f"────────────────────\n"
            f"Ваш аккаунт был заблокирован администрацией.\n\n"
            f"📅 <b>Разблокировка:</b> <code>{time_str}</code>")
    if reason and reason != "Не указана":
        text += f"\n📝 <b>Причина:</b> <code>{reason}</code>"
    return text

# --- ЛОГИРОВАНИЕ ---
async def send_iron_log(context, sender, target_id, update: Update, event_type):
    try:
        s_full = f"{html.escape(sender.first_name or '')} {html.escape(sender.last_name or '')}".strip()
        s_user = f"@{sender.username}" if sender.username else "нет"
        
        try:
            target_chat = await context.bot.get_chat(target_id)
            t_info = f"{html.escape(target_chat.first_name or '')} ({f'@{target_chat.username}' if target_chat.username else 'нет'})"
        except:
            t_info = f"ID: {target_id}"

        report = (f"👤 <b>ОТПРАВИТЕЛЬ:</b> <a href='tg://user?id={sender.id}'>{s_full}</a>\n"
                  f"🔗 <b>Юзернейм:</b> {s_user}\n"
                  f"🆔 <b>ID:</b> <code>{sender.id}</code>\n"
                  f"────────────────────\n"
                  f"📝 <b>ТИП:</b> {event_type}\n"
                  f"🎯 <b>КОМУ:</b> {t_info}\n"
                  f"🆔 <b>ID Получателя:</b> <code>{target_id}</code>")
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ответить пользователю 💬", callback_data=f"adm_reply_{sender.id}")]])
        
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=report, parse_mode='HTML', reply_markup=kb)
        await context.bot.copy_message(chat_id=LOG_GROUP_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
        
        conn = sqlite3.connect('messages_log.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO msg_count (id, total) VALUES (1, 0)')
        cursor.execute('UPDATE msg_count SET total = total + 1 WHERE id = 1')
        conn.commit()
        conn.close()
    except Exception:
        pass 

# --- ОБРАБОТКА СООБЩЕНИЙ ---
async def handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    sender = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id == LOG_GROUP_ID:
        target_uid = context.user_data.get(f"wait_reply_{sender.id}")
        if target_uid:
            try:
                header = "<b>Вам пришел ответ на ваше сообщение!</b> 💬"
                if update.message.text:
                    await context.bot.send_message(chat_id=target_uid, text=f"{header}\n\n{update.message.text}", parse_mode='HTML')
                else:
                    await context.bot.copy_message(chat_id=target_uid, from_chat_id=LOG_GROUP_ID, message_id=update.message.message_id, caption=header, parse_mode='HTML')
                await update.message.reply_text(f"✅ Ответ отправлен пользователю <code>{target_uid}</code>", parse_mode='HTML')
                del context.user_data[f"wait_reply_{sender.id}"]
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
        return 

    ban = get_ban_info(sender.id)
    if ban:
        await update.message.reply_text(format_ban_message(*ban), parse_mode='HTML')
        return

    target_id = context.user_data.get('target_id')
    is_reply = False

    if update.message.reply_to_message:
        conn = sqlite3.connect('messages_log.db')
        cursor = conn.cursor()
        cursor.execute('SELECT original_sender_id FROM reply_map WHERE msg_id = ? AND chat_id = ?', (update.message.reply_to_message.message_id, sender.id))
        res = cursor.fetchone()
        conn.close()
        if res:
            target_id, is_reply = res[0], True

    await send_iron_log(context, sender, target_id or "0", update, "ОТВЕТ" if is_reply else "ОТПРАВКА")

    if not target_id:
        await update.message.reply_text("❌ Ошибка. Пожалуйста, перейдите по ссылке получателя снова.")
        return

    if not is_reply and is_locally_blocked(int(target_id), sender.id):
        await update.message.reply_text("❌ К сожалению, этот пользователь ограничил вам доступ к отправке сообщений.")
        return
    
    try:
        t_id = int(target_id)
        header = "<b>Вам пришел ответ на ваше сообщение!</b> 💬" if is_reply else "<b>Вам пришло новое анонимное сообщение!</b> 💌"
        kb_block = None if is_reply else InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Заблокировать автора", callback_data=f"lblock_{sender.id}")]])
        
        if update.message.text:
            sent = await context.bot.send_message(chat_id=t_id, text=f"{header}\n\n{update.message.text}", parse_mode='HTML', reply_markup=kb_block)
        else:
            sent = await context.bot.copy_message(chat_id=t_id, from_chat_id=chat_id, message_id=update.message.message_id, caption=header, parse_mode='HTML', reply_markup=kb_block)

        if sent:
            conn = sqlite3.connect('messages_log.db')
            cursor = conn.cursor()
            cursor.execute('INSERT INTO reply_map (msg_id, chat_id, original_sender_id, created_at) VALUES (?, ?, ?, ?)', (sent.message_id, t_id, sender.id, int(time.time())))
            conn.commit()
            conn.close()
            
            if not is_reply:
                kb_retry = InlineKeyboardMarkup([[InlineKeyboardButton("Написать еще ✍️", callback_data=f"retry_{target_id}")]])
                await update.message.reply_text("Выберите следующее действие:", reply_markup=kb_retry)
            
            s_msg = await update.message.reply_text("✅")
            await asyncio.sleep(2); await s_msg.delete()
    except Exception:
        s_msg = await update.message.reply_text("❌"); await asyncio.sleep(2); await s_msg.delete()

# --- КОМАНДА START ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != constants.ChatType.PRIVATE: return
    
    user_id = update.effective_user.id
    msg = update.effective_message
    
    conn = sqlite3.connect('messages_log.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

    ban = get_ban_info(user_id)
    if ban:
        await msg.reply_text(format_ban_message(*ban), parse_mode='HTML')
        return

    if context.args:
        context.user_data['target_id'] = context.args[0]
        await msg.reply_text(
            "<b>Напишите ваше сообщение:</b>", 
            parse_mode='HTML', 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена ❌", callback_data="main_menu")]])
        )
    else:
        text = ("В этом боте ты можешь получать и отправлять анонимные сообщения 💌\n\n"
                "Жми кнопочку ниже⤵️")
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Начать получать сообщения", callback_data="get_link")]
        ])
        
        if update.callback_query:
            await update.callback_query.message.edit_text(text, parse_mode='HTML', reply_markup=kb)
        else:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)

# --- АДМИН КОМАНДЫ ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != LOG_GROUP_ID: return
    if not context.args:
        await update.message.reply_text("⚠️ Формат: `/ban [ID] [мин] [причина]`")
        return
    try:
        uid = int(context.args[0])
        mins = 0; reason = "Не указана"; expire = None

        if len(context.args) > 1:
            if context.args[1].isdigit():
                mins = int(context.args[1])
                if mins > 0: expire = int(time.time() + (mins * 60))
                if len(context.args) > 2: reason = " ".join(context.args[2:])
            else:
                reason = " ".join(context.args[1:])
        
        conn = sqlite3.connect('messages_log.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO global_ban (user_id, reason, expire_at) VALUES (?, ?, ?)', (uid, reason, expire))
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(chat_id=uid, text=format_ban_message(reason, expire), parse_mode='HTML')
        except: pass

        await update.message.reply_text(f"✅ Пользователь <code>{uid}</code> забанен.\nСрок: {f'{mins} мин.' if mins > 0 else 'Навсегда'}", parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Ошибка в параметрах.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != LOG_GROUP_ID or not context.args: return
    try:
        uid = int(context.args[0])
        conn = sqlite3.connect('messages_log.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM global_ban WHERE user_id = ?', (uid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Пользователь <code>{uid}</code> разбанен.", parse_mode='HTML')
    except: pass

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != LOG_GROUP_ID: return
    conn = sqlite3.connect('messages_log.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users'); u = cursor.fetchone()[0]
    cursor.execute('SELECT total FROM msg_count WHERE id = 1'); m = cursor.fetchone()
    conn.close()
    await update.message.reply_text(f"📊 <b>Статистика:</b>\n👥 Юзеров: {u}\n💬 Сообщений: {m[0] if m else 0}", parse_mode='HTML')

# --- КОМАНДА /BANAN ---
async def banan_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    user_id = update.effective_user.id
    if update.effective_chat.id == LOG_GROUP_ID: return 

    conn = sqlite3.connect('messages_log.db'); cursor = conn.cursor()
    cursor.execute('SELECT blocked_id FROM local_blocks WHERE owner_id = ?', (user_id,))
    blocked_users = cursor.fetchall(); conn.close()

    if not blocked_users:
        text = "У вас нет заблокированных пользователей. 🍌"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Назад ⬅️", callback_data="main_menu")]])
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    total_pages = math.ceil(len(blocked_users) / 10)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * 10
    current_list = blocked_users[start_idx:start_idx+10]

    text = "<b>Ваш список блокировок:</b>\n\n"
    buttons = []; row = []
    for i, (b_id,) in enumerate(current_list, start=start_idx + 1):
        text += f"{i}. ID: <code>{b_id}</code>\n"
        row.append(InlineKeyboardButton(str(i), callback_data=f"unlblock_{b_id}_{page}"))
        if len(row) == 5: buttons.append(row); row = []
    if row: buttons.append(row)
    
    buttons.append([InlineKeyboardButton("Назад в меню ⬅️", callback_data="main_menu")])
    
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')

# --- КОЛЛБЭКИ ---
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data; user_id = query.from_user.id

    if data.startswith("adm_reply_"):
        target_uid = data.split("_")[2]
        context.user_data[f"wait_reply_{user_id}"] = target_uid
        kb_cancel = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена ❌", callback_data=f"adm_cancel_reply_{user_id}")]])
        await context.bot.send_message(chat_id=LOG_GROUP_ID, text=f"✍️ Пишем ответ для <code>{target_uid}</code>. Жду сообщение:", parse_mode='HTML', reply_markup=kb_cancel)

    elif data.startswith("adm_cancel_reply_"):
        admin_id = int(data.split("_")[3])
        if f"wait_reply_{admin_id}" in context.user_data:
            del context.user_data[f"wait_reply_{admin_id}"]
            await query.edit_message_text("❌ Ответ отменен. Сообщение не будет отправлено.")

    elif data == "get_link":
        bot_info = await context.bot.get_me()
        bot_name = bot_info.username
        user_link = f"https://t.me/{bot_name}?start={user_id}"
        link_text = (
            f"👋 <b>Твоя персональная ссылка:</b>\n\n"
            f"🔗 <tg-spoiler><code>{user_link}</code></tg-spoiler>\n\n"
            f"<i>(Нажми на ссылку выше, чтобы скопировать)</i>\n\n"
            f"<b>Что с ней делать?</b>\n"
            f"• Размести её в профиле Instagram, VK или TikTok.\n"
            f"• Добавь в описание своих сторис.\n"
            f"• Люди смогут писать тебе анонимно, нажав на неё!"
        )
        await query.message.edit_text(link_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад ⬅️", callback_data="main_menu")]]), disable_web_page_preview=True)
    
    elif data == "main_menu":
        context.user_data.pop('target_id', None)
        await start(update, context)

    elif data.startswith("lblock_"):
        to_block = int(data.split("_")[1])
        conn = sqlite3.connect('messages_log.db'); cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO local_blocks (owner_id, blocked_id) VALUES (?, ?)', (user_id, to_block))
        conn.commit(); conn.close()
        await query.message.reply_text("🚫 Пользователь заблокирован.")

    elif data.startswith("unlblock_"):
        parts = data.split("_")
        b_id = int(parts[1]); page = int(parts[2])
        conn = sqlite3.connect('messages_log.db'); cursor = conn.cursor()
        cursor.execute('DELETE FROM local_blocks WHERE owner_id = ? AND blocked_id = ?', (user_id, b_id))
        conn.commit(); conn.close()
        await banan_command(update, context, page)

    elif data.startswith("retry_"):
        target_id = data.split("_")[1]
        context.user_data['target_id'] = target_id
        await query.message.reply_text("💬 Введите новое сообщение:")

# --- ЗАПУСК ---
async def post_init(application):
    await application.bot.set_my_commands([BotCommand("stats", "📊 Статистика"), BotCommand("ban", "🚫 Бан [ID] [мин] [причина]"), BotCommand("unban", "✅ Разбан [ID]")], scope=BotCommandScopeChat(chat_id=LOG_GROUP_ID))
    await application.bot.set_my_commands([BotCommand("start", "♻️ Перезапуск"), BotCommand("banan", "🍌 Мои блокировки")], scope=BotCommandScopeAllPrivateChats())

if __name__ == '__main__':
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("banan", banan_command))
    app.add_handler(CommandHandler("stats", get_stats))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_content))
    
    app.run_polling(drop_pending_updates=True, poll_interval=1.0, timeout=30)
