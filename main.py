"""Mrx Vinyl Transfer Bot — Charge Only On Success"""
from __future__ import annotations
import asyncio, base64, datetime, hashlib, hmac, json, logging, math, os, re, struct, threading, time, urllib.parse
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Optional

import aiohttp, aiosqlite, telebot, uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from telebot.types import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, MenuButtonWebApp, PreCheckoutQuery, Update, WebAppInfo,
)
try:
    import brotli
except ImportError:
    brotli = None
from Crypto.Cipher import AES

load_dotenv()

# ==========================================================
# CONFIG
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8820198558:AAHHFchT0qjdyqvIimLBvBLtcxYqRGOucWM").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "612673014"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
DB_PATH = os.getenv("DB_PATH", "mrx.db").strip() or "mrx.db"
REF_REWARD = 5
BOT_USERNAME = None
SUPPORT_URL = "https://t.me/PRO_MR_X"

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
def now_ist(): return datetime.datetime.now(IST)
def ts_ist(): return now_ist().strftime("%Y-%m-%d %H:%M:%S")

COST_CPM1_TO_CPM2 = 15
COST_CPM2_TO_CPM2 = 15
COST_POLICE = 10
COST_AIRSUS = 10
COST_INSPECT_CPM1 = 10
COST_INSPECT_CPM2 = 10

DEFAULT_PACKAGES = [
    {"id": "mini", "coins": 10, "bonus": 0, "price": 10, "label": "10 Coins", "bonus_label": ""},
    {"id": "basic", "coins": 15, "bonus": 0, "price": 15, "label": "15 Coins", "bonus_label": ""},
    {"id": "pro", "coins": 30, "bonus": 5, "price": 30, "label": "30 Coins", "bonus_label": "+5 bonus"},
    {"id": "plus", "coins": 50, "bonus": 10, "price": 50, "label": "50 Coins", "bonus_label": "+10 bonus"},
    {"id": "mega", "coins": 100, "bonus": 20, "price": 100, "label": "100 Coins", "bonus_label": "+20 bonus"},
]
def pkg_total(pkg): return int(pkg["coins"]) + int(pkg.get("bonus", 0))

CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
CPM1_DATABASE_URL = "https://carparkingmultiplayer-dc1d2.firebaseio.com"
CPM1_API_BASE = "https://us-central1-carparkingmultiplayer-dc1d2.cloudfunctions.net"
CPM2_API_BASE = "https://europe-west1-cpm-2-7cea1.cloudfunctions.net"
CPM1_CARS_FUNCTION = "GetAllCars2"
CPM1_FALLBACK_BASES = ("https://europe-west1-cp-multiplayer.cloudfunctions.net","https://us-central1-cp-multiplayer.cloudfunctions.net")
CPM2_CARS_FUNCTION_CANDIDATES = ("GetAllCars24_1","GetAllCars23_1","GetAllCars22_1","GetAllCars21_1","GetAllCars20_2")
CPM2_SAVE_CAR_FUNCTION = "SaveCar22_1"
CPM2_SAVE_CAR_FUNCTION_CANDIDATES = ("SaveCar24_1","SaveCar23_1","SaveCar22_1","SaveCar21_1","SaveCar20_2")
CPM1_UNSUPPORTED_CLOUD_ERROR = "CPM1_CLOUD_UNSUPPORTED_OR_NEW_FORMAT"

DEFAULT_SUBS = {
    "1624855384": "2026-09-26", "6531314640": "2300-06-28", "7155957662": "2026-12-15",
    "7448355677": "2054-02-04", "7660342146": "2026-09-19", "7722203213": "2029-06-16",
    "7852579148": "2026-09-20", "8143093081": "2300-07-02", "8143326682": "2300-06-30",
    "8519787927": "2026-09-21", "8544788758": "2029-06-08", "8591766812": "2054-02-04",
    "8635946613": "2054-02-05", "8686082215": "2054-01-28", "8727641773": "2054-01-28",
    "8742471038": "2029-06-09", "8743824286": "2026-09-23", "8880294699": "2026-11-15",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mrx")
if not BOT_TOKEN or ":" not in BOT_TOKEN: raise SystemExit("BOT_TOKEN missing")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==========================================================
# BACKGROUND LOOP
# ==========================================================
_bg_loop = None
_bg_thread = None
def _start_bg_loop():
    global _bg_loop, _bg_thread
    if _bg_loop is not None and _bg_loop.is_running(): return
    def _run():
        global _bg_loop
        _bg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bg_loop)
        _bg_loop.run_forever()
    _bg_thread = threading.Thread(target=_run, daemon=True, name="bg_loop")
    _bg_thread.start()
    for _ in range(50):
        if _bg_loop is not None and _bg_loop.is_running(): break
        time.sleep(0.02)
    log.info("✅ Background event loop started")

def _run_async(coro):
    if _bg_loop is None or not _bg_loop.is_running(): _start_bg_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    try: return fut.result(timeout=30)
    except Exception as e:
        log.error(f"_run_async error: {e}")
        return None
_start_bg_loop()

# ==========================================================
# EMOJIS
# ==========================================================
EMOJI_IDS = {
    "art": "5220195193923328112","rocket": "5445284980978621387",
    "car1": "5190458184690588640","car2": "5190458184690588640",
    "target": "5350460637182993292","crown": "5969740061648884524",
    "chat": "5260535596941582167","point_down": "5470177992950946662",
    "check": "5980930633298350051","cross": "5974083768233760323",
    "ping_pong": "5269563867305879894","warning": "5285139029333919650",
    "zap": "5431449001532594346","lock": "5472308992514464048",
    "diamond": "5109480514809497205","clipboard": "5837003105228558796",
}
def e(char, key): return f'<tg-emoji emoji-id="{EMOJI_IDS[key]}">{char}</tg-emoji>'
E_ART = e("🎨","art"); E_ROCKET = e("🚀","rocket")
E_CAR1 = e("🚗","car1"); E_CAR2 = e("🚙","car2")
E_TARGET = e("🎯","target"); E_CROWN = e("👑","crown")
E_CHAT = e("💬","chat"); E_DOWN = e("👇","point_down")
E_CHECK = e("✅","check"); E_CROSS = e("❌","cross")
E_PING = e("🏓","ping_pong"); E_WARN = e("⚠️","warning")
E_ZAP = e("⚡","zap"); E_LOCK = e("🔒","lock")
E_DIAMOND = e("💎","diamond"); E_CLIP = e("📋","clipboard")

# ==========================================================
# SQLITE DB LAYER
# ==========================================================
class _Rows:
    __slots__ = ("rows",)
    def __init__(self, rows): self.rows = rows

class SQLiteClient:
    def __init__(self, conn): self.conn = conn
    async def execute(self, sql, params=None):
        params = params or []
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        if cur.description is not None:
            rows = await cur.fetchall()
            await cur.close()
            return _Rows(rows)
        await cur.close()
        return _Rows([])
    async def close(self):
        try: await self.conn.close()
        except Exception: pass

@asynccontextmanager
async def db_client():
    try:
        conn = await aiosqlite.connect(DB_PATH, timeout=30)
    except Exception as ex:
        log.error(f"db connect: {ex}")
        yield None
        return
    client = SQLiteClient(conn)
    try:
        yield client
    except Exception as ex:
        log.error(f"db_client error: {type(ex).__name__}: {ex}")
        raise
    finally:
        try: await client.close()
        except Exception: pass

def db_ok(): return True

async def init_db():
    async with db_client() as c:
        if not c: return False
        try:
            r = await c.execute("SELECT 1 AS t")
            if r is not None:
                log.info(f"✅ SQLite connected ({DB_PATH})")
                return True
        except Exception as ex:
            log.error(f"❌ SQLite init: {type(ex).__name__}: {ex}")
        return False

async def db_ping():
    async with db_client() as c:
        if not c: return False
        try:
            await c.execute("SELECT 1")
            return True
        except Exception as ex:
            log.error(f"SQLite ping: {ex}")
            return False

async def ensure_indexes():
    async with db_client() as c:
        if not c: return
        try:
            await c.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                coins INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            await c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                expiry TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            await c.execute("""CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                details TEXT,
                cost INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_at_ist TEXT
            )""")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_activities_user ON activities(user_id)")
            await c.execute("""CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                package_id TEXT,
                coins INTEGER,
                price INTEGER,
                currency TEXT DEFAULT 'XTR',
                status TEXT,
                kind TEXT,
                description TEXT,
                telegram_charge_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_at_ist TEXT,
                paid_at TEXT,
                paid_at_ist TEXT
            )""")
            await c.execute("""CREATE TABLE IF NOT EXISTS shop_config (
                id TEXT PRIMARY KEY,
                coins INTEGER NOT NULL,
                bonus INTEGER DEFAULT 0,
                price INTEGER NOT NULL,
                label TEXT,
                bonus_label TEXT
            )""")
            await c.execute("""CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_at_ist TEXT
            )""")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_ref_referrer ON referrals(referrer_id)")
            log.info("✅ Tables + indexes ready")
        except Exception as ex:
            log.error(f"ensure_indexes: {ex}")

async def seed_default_subs():
    async with db_client() as c:
        if not c: return
        try:
            for uid, expiry in DEFAULT_SUBS.items():
                await c.execute("INSERT OR IGNORE INTO subscriptions (user_id, expiry) VALUES (?, ?)", [int(uid), expiry])
            log.info(f"✅ Seeded {len(DEFAULT_SUBS)} default subs")
        except Exception as ex:
            log.warning(f"seed subs: {ex}")

async def seed_default_shop():
    async with db_client() as c:
        if not c: return
        try:
            for p in DEFAULT_PACKAGES:
                await c.execute("""INSERT OR IGNORE INTO shop_config (id, coins, bonus, price, label, bonus_label)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    [p["id"], p["coins"], p.get("bonus",0), p["price"], p.get("label",""), p.get("bonus_label","")])
            log.info("✅ Shop packages ready")
        except Exception as ex:
            log.warning(f"seed shop: {ex}")

# ==========================================================
# DB — SHOP
# ==========================================================
async def db_get_shop_packages():
    async with db_client() as c:
        if c:
            try:
                r = await c.execute("SELECT id, coins, bonus, price, label, bonus_label FROM shop_config ORDER BY price ASC")
                if r and r.rows and len(r.rows) > 0:
                    cols = ["id","coins","bonus","price","label","bonus_label"]
                    return [dict(zip(cols, row)) for row in r.rows]
            except Exception as ex:
                log.warning(f"shop get: {ex}")
    return DEFAULT_PACKAGES

async def db_update_shop_package(pkg_id: str, data: dict):
    async with db_client() as c:
        if c:
            try:
                await c.execute("""INSERT INTO shop_config (id, coins, bonus, price) VALUES (?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET coins = excluded.coins, bonus = excluded.bonus, price = excluded.price""",
                    [pkg_id, data.get("coins",0), data.get("bonus",0), data.get("price",0)])
            except Exception as ex:
                log.warning(f"shop update: {ex}")
    return True

# ==========================================================
# DB — USER
# ==========================================================
async def db_get_user(user_id):
    async with db_client() as c:
        if not c: return None
        try:
            r = await c.execute("SELECT user_id, username, first_name, last_name, language_code, coins FROM users WHERE user_id = ?", [user_id])
            if r and r.rows and len(r.rows) > 0:
                cols = ["user_id","username","first_name","last_name","language_code","coins"]
                return dict(zip(cols, r.rows[0]))
        except Exception as ex:
            log.warning(f"get_user: {ex}")
    return None

async def db_upsert_user(user_id, data):
    async with db_client() as c:
        if not c: return
        try:
            await c.execute("""INSERT INTO users (user_id, username, first_name, last_name, language_code, coins, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    language_code = COALESCE(excluded.language_code, users.language_code),
                    updated_at = CURRENT_TIMESTAMP""",
                [user_id, data.get("username"), data.get("first_name"), data.get("last_name"), data.get("language_code")])
        except Exception as ex:
            log.warning(f"upsert user: {ex}")

# ==========================================================
# DB — SUBSCRIPTION
# ==========================================================
async def db_get_subscription(user_id):
    async with db_client() as c:
        if not c: return None
        try:
            r = await c.execute("SELECT user_id, expiry FROM subscriptions WHERE user_id = ?", [user_id])
            if r and r.rows and len(r.rows) > 0:
                return {"user_id": r.rows[0][0], "expiry": r.rows[0][1]}
        except Exception as ex:
            log.warning(f"get_sub: {ex}")
    return None

async def db_is_subscribed(user_id):
    if user_id == ADMIN_ID: return True
    sub = await db_get_subscription(user_id)
    if not sub: return False
    try: expiry = datetime.datetime.strptime(sub["expiry"], "%Y-%m-%d").date()
    except: return False
    return expiry >= datetime.date.today()

async def db_add_subscription(user_id, days):
    today = datetime.date.today()
    cur = await db_get_subscription(user_id)
    if cur:
        try: exp = datetime.datetime.strptime(cur["expiry"], "%Y-%m-%d").date()
        except: exp = today
        new = (exp if exp > today else today) + datetime.timedelta(days=days)
    else:
        new = today + datetime.timedelta(days=days)
    s = new.strftime("%Y-%m-%d")
    async with db_client() as c:
        if c:
            try:
                await c.execute("""INSERT INTO subscriptions (user_id, expiry) VALUES (?, ?)
                    ON CONFLICT (user_id) DO UPDATE SET expiry = excluded.expiry""", [user_id, s])
            except Exception as ex:
                log.warning(f"add_sub: {ex}")
    return s

async def db_remove_subscription(user_id):
    async with db_client() as c:
        if not c: return False
        try:
            r = await c.execute("SELECT user_id FROM subscriptions WHERE user_id = ?", [user_id])
            if r and r.rows and len(r.rows) > 0:
                await c.execute("DELETE FROM subscriptions WHERE user_id = ?", [user_id])
                return True
        except Exception as ex:
            log.warning(f"rm_sub: {ex}")
    return False

async def db_list_subscriptions():
    async with db_client() as c:
        if c:
            try:
                r = await c.execute("SELECT user_id, expiry FROM subscriptions ORDER BY user_id ASC")
                if r and r.rows and len(r.rows) > 0:
                    return [{"user_id": row[0], "expiry": row[1]} for row in r.rows]
            except Exception as ex:
                log.warning(f"list_subs: {ex}")
    return []

# ==========================================================
# DB — COINS
# ==========================================================
async def db_get_coins(user_id):
    async with db_client() as c:
        if not c: return 0
        try:
            r = await c.execute("SELECT coins FROM users WHERE user_id = ?", [user_id])
            if r and r.rows and len(r.rows) > 0: return int(r.rows[0][0] or 0)
        except Exception as ex:
            log.error(f"get_coins FAILED: {ex}")
    return 0

async def db_add_coins(user_id, amount):
    async with db_client() as c:
        if not c:
            log.error("add_coins: no client available"); return 0
        try:
            r = await c.execute("""INSERT INTO users (user_id, coins, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    coins = users.coins + excluded.coins,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING coins""", [user_id, amount])
            if r and r.rows and len(r.rows) > 0:
                new_bal = int(r.rows[0][0] or 0)
                log.info(f"✅ coins added: {user_id} +{amount} → {new_bal}")
                return new_bal
        except Exception as ex:
            log.error(f"❌ add_coins FAILED: {type(ex).__name__}: {ex}")
    return 0

async def db_deduct_coins(user_id, amount):
    async with db_client() as c:
        if not c: return False
        try:
            r = await c.execute("SELECT coins FROM users WHERE user_id = ?", [user_id])
            cur = int(r.rows[0][0] or 0) if (r and r.rows) else 0
            if cur < amount:
                log.warning(f"deduct_coins: {user_id} has {cur} < {amount}")
                return False
            await c.execute("UPDATE users SET coins = MAX(coins - ?, 0), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", [amount, user_id])
            return True
        except Exception as ex:
            log.error(f"deduct_coins FAILED: {ex}")
    return False

async def db_list_all_coin_holders(limit=200):
    async with db_client() as c:
        if not c: return []
        try:
            r = await c.execute("SELECT user_id, coins, username, first_name FROM users WHERE coins > 0 ORDER BY coins DESC LIMIT ?", [limit])
            if r and r.rows:
                return [{"user_id": int(row[0]), "coins": int(row[1] or 0), "username": row[2] or "", "first_name": row[3] or ""} for row in r.rows]
        except Exception as ex:
            log.error(f"coin_holders: {ex}")
    return []

# ==========================================================
# DB — ACTIVITY
# ==========================================================
async def db_log_activity(user_id, username, action, details="", cost=0):
    async with db_client() as c:
        if not c: return
        try:
            await c.execute("INSERT INTO activities (user_id, username, action, details, cost, created_at_ist) VALUES (?, ?, ?, ?, ?, ?)",
                [user_id, username or "", action, (details or "")[:300], cost, ts_ist()])
        except Exception as ex:
            log.warning(f"log_activity: {ex}")

async def db_get_activities(limit=100, user_id=None):
    async with db_client() as c:
        if not c: return []
        try:
            if user_id:
                r = await c.execute("SELECT user_id, username, action, details, cost, created_at_ist FROM activities WHERE user_id = ? ORDER BY id DESC LIMIT ?", [user_id, limit])
            else:
                r = await c.execute("SELECT user_id, username, action, details, cost, created_at_ist FROM activities ORDER BY id DESC LIMIT ?", [limit])
            if r and r.rows:
                cols = ["user_id","username","action","details","cost","created_at_ist"]
                return [dict(zip(cols, row)) for row in r.rows]
        except Exception as ex:
            log.warning(f"get_acts: {ex}")
    return []

async def db_get_user_feature_stats(user_id):
    async with db_client() as c:
        if not c: return {}
        try:
            r = await c.execute("SELECT action, COUNT(*) FROM activities WHERE user_id = ? GROUP BY action ORDER BY 2 DESC", [user_id])
            if r and r.rows:
                return {row[0]: int(row[1]) for row in r.rows}
        except Exception as ex:
            log.warning(f"feature_stats: {ex}")
    return {}

# ==========================================================
# DB — PAYMENTS
# ==========================================================
async def db_create_pending_payment(user_id, username, package_id, coins, stars, kind="coins", description=""):
    pid = f"{kind}_{user_id}_{int(time.time()*1000)}"
    async with db_client() as c:
        if c:
            try:
                await c.execute("""INSERT INTO payments (payment_id, user_id, username, package_id, coins, price, currency, status, kind, description, created_at_ist)
                    VALUES (?, ?, ?, ?, ?, ?, 'XTR', 'awaiting_payment', ?, ?, ?)""",
                    [pid, user_id, username or "", package_id, coins, stars, kind, description, ts_ist()])
            except Exception as ex:
                log.warning(f"payment insert: {ex}")
    return pid

async def db_get_payment(payment_id):
    async with db_client() as c:
        if c:
            try:
                r = await c.execute("SELECT * FROM payments WHERE payment_id = ?", [payment_id])
                if r and r.rows and len(r.rows) > 0:
                    cols = ["payment_id","user_id","username","package_id","coins","price","currency","status","kind","description","telegram_charge_id","created_at","created_at_ist","paid_at","paid_at_ist"]
                    return dict(zip(cols, r.rows[0]))
            except Exception as ex:
                log.warning(f"get_payment: {ex}")
    return None

async def db_mark_paid(payment_id, charge_id):
    async with db_client() as c:
        if c:
            try:
                await c.execute("""UPDATE payments SET status = 'completed', telegram_charge_id = ?, paid_at = CURRENT_TIMESTAMP, paid_at_ist = ? WHERE payment_id = ?""",
                    [charge_id, ts_ist(), payment_id])
            except Exception as ex:
                log.warning(f"mark_paid: {ex}")
    return True

async def db_list_payments(status=None, limit=100):
    async with db_client() as c:
        if c:
            try:
                if status:
                    r = await c.execute("SELECT * FROM payments WHERE status = ? ORDER BY created_at DESC LIMIT ?", [status, limit])
                else:
                    r = await c.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", [limit])
                if r and r.rows:
                    cols = ["payment_id","user_id","username","package_id","coins","price","currency","status","kind","description","telegram_charge_id","created_at","created_at_ist","paid_at","paid_at_ist"]
                    return [dict(zip(cols, row)) for row in r.rows]
            except Exception as ex:
                log.warning(f"list_payments: {ex}")
    return []

# ==========================================================
# DB — REFERRAL
# ==========================================================
async def process_referral(referrer_id, referred_id, referred_username):
    if referrer_id == referred_id: return
    ok = False
    async with db_client() as c:
        if not c: return
        try:
            r = await c.execute("SELECT id FROM referrals WHERE referred_id = ?", [referred_id])
            if r and r.rows and len(r.rows) > 0: return
            r2 = await c.execute("SELECT user_id FROM users WHERE user_id = ?", [referrer_id])
            if not (r2 and r2.rows and len(r2.rows) > 0): return
            await c.execute("INSERT INTO referrals (referrer_id, referred_id, created_at_ist) VALUES (?, ?, ?)", [referrer_id, referred_id, ts_ist()])
            ok = True
        except Exception as ex:
            log.warning(f"process_ref: {ex}"); return
    if not ok: return
    await db_add_coins(referrer_id, REF_REWARD)
    await db_add_coins(referred_id, REF_REWARD)
    await db_log_activity(referrer_id, "", "referral_bonus", f"+{REF_REWARD} for inviting {referred_id}", 0)
    await db_log_activity(referred_id, "", "referral_welcome", f"+{REF_REWARD} welcome bonus", 0)
    try: bot.send_message(referrer_id, f"🎉 <b>New Referral!</b>\n\n👤 @{referred_username or referred_id} joined\n💎 +{REF_REWARD} coins added!")
    except: pass

async def db_get_referral_stats(user_id):
    async with db_client() as c:
        if not c: return {"count": 0, "recent": []}
        try:
            r = await c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", [user_id])
            count = int(r.rows[0][0]) if r and r.rows else 0
            r2 = await c.execute("SELECT referred_id, created_at_ist FROM referrals WHERE referrer_id = ? ORDER BY id DESC LIMIT 10", [user_id])
            recent = [{"user_id": int(row[0]), "at": row[1]} for row in (r2.rows if r2 and r2.rows else [])]
            return {"count": count, "recent": recent}
        except Exception as ex:
            log.warning(f"ref_stats: {ex}"); return {"count": 0, "recent": []}

async def db_get_referral_leaderboard(limit=10):
    async with db_client() as c:
        if not c: return []
        try:
            r = await c.execute("""SELECT r.referrer_id, COUNT(*) as cnt, u.username, u.first_name
                FROM referrals r LEFT JOIN users u ON u.user_id = r.referrer_id
                GROUP BY r.referrer_id ORDER BY cnt DESC LIMIT ?""", [limit])
            if r and r.rows:
                return [{"user_id": int(row[0]), "count": int(row[1]), "username": row[2] or "", "first_name": row[3] or ""} for row in r.rows]
        except Exception as ex:
            log.warning(f"ref_lb: {ex}")
    return []

# ==========================================================
# VINYL CORE
# ==========================================================
_cars_function_name = None
_save_car_function_name = None
_balance_http_session = ContextVar("balance_http_session", default=None)
def set_balance_session(s): return _balance_http_session.set(s)
def reset_balance_session(t): _balance_http_session.reset(t)

@lru_cache(maxsize=1)
def _load_car_names():
    for p in (Path(__file__).with_name("cpm2_car_names.json"), Path(__file__).parent / "assets" / "cpm2_car_names.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {str(k): " ".join(str(v).split()) for k, v in d.items()}
        except: continue
    return {}

async def firebase_verify_password(email, password, *, api_key, session=None):
    if not api_key: return {"error": {"message": "NO_KEY"}}
    url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
    async def do(s):
        try:
            async with s.post(url, json={"email": email, "password": password, "returnSecureToken": True}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                try: d = await r.json(content_type=None)
                except: return {"error": {"message": "SERVICE_UNAVAILABLE", "transient": True}}
                if r.status == 429 or r.status >= 500:
                    return {"error": {"message": "SERVICE_UNAVAILABLE", "transient": True}}
                return d
        except: return {"error": {"message": "CONNECTION_ERROR", "transient": True}}
    if session: return await do(session)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as own:
        return await do(own)

def _derive_key_iv(local_id):
    if not local_id: return None, None
    raw = (local_id[:8] + "12345678").encode()[:16]
    return raw, raw

def _encrypt_value(value, local_id):
    k, iv = _derive_key_iv(local_id)
    if not k: return None
    raw = value.encode(); pad = 16 - len(raw) % 16; raw += bytes([pad]) * pad
    return base64.b64encode(AES.new(k, AES.MODE_CBC, iv).encrypt(raw)).decode()

def _json_unwrap(v):
    c = v
    for _ in range(4):
        if not isinstance(c, str): break
        try: c = json.loads(c)
        except: break
    return c

def _int_value(v, d=0):
    try: return int(v)
    except: return d
def _float_value(v):
    try: n = float(v)
    except: return 0.0
    return n if math.isfinite(n) else 0.0
def _uint32_value(v): return _int_value(v) & 0xFFFFFFFF
def _int64_value(v):
    n = _int_value(v)
    if n > 0x7FFFFFFFFFFFFFFF: n -= 0x10000000000000000
    if n < -0x8000000000000000: n = -0x8000000000000000
    return n
def _memorypack_string(v):
    e = v.encode()
    if not e: return struct.pack("<i", 0)
    return struct.pack("<ii", ~len(e), len(v)) + e
def _vector3(v):
    if not isinstance(v, dict): return 0.0, 0.0, 0.0
    return (_float_value(v.get("x", v.get("X"))), _float_value(v.get("y", v.get("Y"))), _float_value(v.get("z", v.get("Z"))))
def _serialize_vinyl_item(item):
    p = _vector3(item.get("position")); s = _vector3(item.get("scaleRotation", item.get("scale_rotation")))
    ic = _vector3(item.get("iconPosition", item.get("icon_position"))); t = str(item.get("text") or "")
    return (b"\x06" + struct.pack("<9f", *p, *s, *ic) + _memorypack_string(t) + struct.pack("<Iq", _uint32_value(item.get("color")), _int64_value(item.get("packedData"))))
def _serialize_vinyl_list(items):
    return struct.pack("<i", len(items)) + b"".join(_serialize_vinyl_item(i) for i in items)
def _extract_vinyl_items(v):
    if isinstance(v, list): return [i for i in v if isinstance(i, dict)]
    if not isinstance(v, dict): return None
    for k in ("allVynils","oneVynil"):
        if isinstance(v.get(k), list): return [i for i in v[k] if isinstance(i, dict)]
    if {"position","scaleRotation","iconPosition"} & set(v): return [v]
    return None
def _brotli_decompress(p):
    if brotli is None: return None
    try: return brotli.decompress(p)
    except: return None
def _extract_vinyl_raw_candidate(p):
    d = _read_memorypack_vinyl_list(p, 0, len(p))
    if d is not None and d[0] == len(p): return p, d[1]
    if not p: return None
    w = _read_memorypack_vinyl_list(p, 1, len(p))
    if w is None: return None
    if len(p) - w[0] in (0, 4): return p[1:w[0]], w[1]
    return None
def _normalize_cpm1_vinyl_field(v):
    items = _extract_vinyl_items(v)
    if items is not None: return _serialize_vinyl_list(items), len(items)
    if v in (None,"",[]): return _serialize_vinyl_list([]), 0
    if not isinstance(v, str): return None
    try: dec = base64.b64decode(v, validate=True)
    except: return None
    for c in (dec, _brotli_decompress(dec)):
        if not isinstance(c, (bytes, bytearray)): continue
        r = _extract_vinyl_raw_candidate(bytes(c))
        if r: return r
    return None
def _instance_id_from_car(car):
    texts = car.get("texts")
    if isinstance(texts, list):
        for i in (2,1,0):
            if i < len(texts):
                v = str(texts[i] or "").strip()
                if v: return v
    return ""
def _normalize_cpm1_car(raw, idx, names):
    if not isinstance(raw, dict): return None
    cid = _int_value(raw.get("CarID"))
    if cid <= 0: return None
    v = _normalize_cpm1_vinyl_field(raw.get("Vynils")); w = _normalize_cpm1_vinyl_field(raw.get("WindowVinyls"))
    sup = v is not None and w is not None
    return {"id": cid, "index": idx, "name": names.get(str(cid), f"Car {cid}"),
            "instance_id": _instance_id_from_car(raw), "transferable": sup, "style_transferable": sup,
            "vinyls": v[1] if v else -1, "window": w[1] if w else -1,
            "vinyls_raw": v[0] if v else None, "window_raw": w[0] if w else None}
def _memorypack_xor_key(local_id):
    c = list(local_id or "")
    if len(c) >= 7: c[6], c[4] = c[4], c[6]
    if len(c) >= 9: c.pop(8)
    if c: c.append(c[0])
    return "".join(c).encode()
_B64_TEXT = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n"
def _decode_current_memorypack(v, local_id):
    if not isinstance(v, dict) or v.get("code") != 1 or not isinstance(v.get("data"), str): return None
    if brotli is None: return None
    try:
        enc = base64.b64decode("".join(v["data"].split()), validate=True)
        for _ in range(2):
            if not enc or any(chr(b) not in _B64_TEXT for b in enc[:256]): break
            try: enc = base64.b64decode(enc.translate(None, b"\r\n"), validate=True)
            except: break
        xk = _memorypack_xor_key(local_id)
        if not xk: return None
        packed = bytes(b ^ xk[i % len(xk)] for i, b in enumerate(enc))
        return brotli.decompress(packed)
    except: return None
def _read_memorypack_string(p, o, e):
    if o + 4 > e: return None
    m = struct.unpack_from("<i", p, o)[0]; o += 4
    if m in (-1,0): return o
    if m > 0: bc = m * 2
    else:
        bc = ~m
        if o + 4 > e: return None
        o += 4
    if bc < 0 or o + bc > e: return None
    return o + bc
def _decode_memorypack_string_at(p, o, e):
    if o + 4 > e: return None
    m = struct.unpack_from("<i", p, o)[0]; c = o + 4
    if m in (-1,0): return c, ""
    if m > 0:
        bc = m * 2
        if c + bc > e: return None
        try: return c + bc, p[c:c+bc].decode("utf-16-le")
        except: return None
    bc = ~m
    if c + 4 + bc > e: return None
    cc = struct.unpack_from("<i", p, c)[0]; c += 4
    try: v = p[c:c+bc].decode("utf-8")
    except: return None
    if cc >= 0 and len(v) != cc: return None
    return c + bc, v
def _read_memorypack_vinyl(p, o, e):
    if o >= e: return None
    mc = p[o]; o += 1
    if mc == 255: return o
    if mc != 6 or o + 36 > e: return None
    vals = struct.unpack_from("<9f", p, o)
    if not all(math.isfinite(v) and abs(v) < 1e6 for v in vals): return None
    o += 36
    o = _read_memorypack_string(p, o, e)
    if o is None or o + 12 > e: return None
    return o + 12
def _read_memorypack_vinyl_list(p, o, e):
    if o + 4 > e: return None
    c = struct.unpack_from("<i", p, o)[0]; o += 4
    if c == -1: return o, 0
    if c < 0 or c > 2000: return None
    for _ in range(c):
        o = _read_memorypack_vinyl(p, o, e)
        if o is None: return None
    return o, c
def _read_memorypack_int_list(p, o, e):
    if o + 4 > e: return None
    c = struct.unpack_from("<i", p, o)[0]; o += 4
    if c == -1: return o
    if c < 0 or c > 1000 or o + c*4 > e: return None
    return o + c*4
def _read_memorypack_installed_body_kits(p, o, e):
    if o >= e: return None
    mc = p[o]; o += 1
    if mc == 255: return o
    if mc != 10 or o + 32 > e: return None
    o += 32; ts = o
    o = _read_memorypack_int_list(p, o, e)
    if o is None: o = _read_memorypack_string(p, ts, e)
    if o is None or o + 4 > e: return None
    return o + 4
def _read_memorypack_body_kit_colors(p, o, e):
    if o >= e: return None
    mc = p[o]; o += 1
    if mc == 255: return o
    if mc != 1 or o + 4 > e: return None
    c = struct.unpack_from("<i", p, o)[0]; o += 4
    if c == -1: return o
    if c < 0 or c > 128: return None
    for _ in range(c):
        if o >= e: return None
        im = p[o]; o += 1
        if im == 255: continue
        if im not in (2,3) or o + 12 > e: return None
        o += 12
    return o
def _read_memorypack_colors(p, o, e):
    if o >= e: return None
    mc = p[o]; o += 1
    if mc == 255: return o
    if mc != 8 or o + 32 > e: return None
    o += 32
    return _read_memorypack_body_kit_colors(p, o, e)
def _read_memorypack_bought_body_kits(p, o, e):
    if o >= e: return None
    mc = p[o]; o += 1
    if mc == 255: return o
    if mc != 10: return None
    for _ in range(10):
        o = _read_memorypack_int_list(p, o, e)
        if o is None: return None
    return o
def _extract_memorypack_style_fields(p, s, e, vo, ir):
    ist = s + 5
    ie = _read_memorypack_installed_body_kits(p, ist, e)
    if ie is None: return None
    cs = ie
    ce = _read_memorypack_colors(p, cs, e)
    if ce is None: return None
    ii = p.find(ir, ce, vo)
    if ii < 0: return None
    ien = ii + len(ir)
    bc = [o for o in range(ien, vo) if _read_memorypack_bought_body_kits(p, o, vo) == vo]
    if not bc: return None
    bs = max(bc)
    if not (ce < ii < ien < bs < vo): return None
    return {2: p[bs:vo], 3: p[cs:ce], 4: p[ien:bs], 5: p[ce:ii], 6: p[ist:ie]}
def _find_memorypack_car_instance(p, s, vo):
    strict = re.compile(r"^[A-Za-z]{2}\d{3,}_[A-Za-z]{2}\d{2,}_\d{2,}$")
    fb = None
    for o in range(s + 5, max(s + 5, vo - 3)):
        d = _decode_memorypack_string_at(p, o, vo)
        if d is None: continue
        e, t = d
        if not (8 <= len(t) <= 80 and t.count("_") >= 2 and any(c.isdigit() for c in t)): continue
        raw = p[o:e]
        if strict.fullmatch(t): return t, raw
        if fb is None and re.fullmatch(r"[A-Za-z0-9_-]+", t): fb = (t, raw)
    return fb
def _memorypack_car_offsets(p):
    if len(p) < 4: return None
    n = struct.unpack_from("<i", p, 0)[0]
    if n == 0: return []
    if n < 0 or n > 5000: return None
    ki = {int(c) for c in _load_car_names() if str(c).isdigit()}
    kn, bd = [], []
    for o in range(4, len(p) - 5):
        if p[o] != 9 or p[o+5] not in (10, 255): continue
        cid = struct.unpack_from("<i", p, o+1)[0]
        if 0 < cid <= 5000:
            bd.append((o, cid))
            if cid in ki: kn.append((o, cid))
    if len(kn) == n: return kn
    if len(bd) == n: return bd
    cf = []
    for o, cid in bd:
        ie = _read_memorypack_installed_body_kits(p, o+5, len(p))
        if ie is None: continue
        if _read_memorypack_colors(p, ie, len(p)) is None: continue
        cf.append((o, cid))
    if len(cf) == n: return cf
    return None
def _parse_memorypack_cloud_vinyls(v, local_id):
    p = _decode_current_memorypack(v, local_id)
    if p is None: return None
    recs = _memorypack_car_offsets(p)
    if recs is None: return None
    out = []
    for i, (s, cid) in enumerate(recs):
        e = recs[i+1][0] if i+1 < len(recs) else len(p)
        m = None
        for o in range(s+5, max(s+5, e-7)):
            f = _read_memorypack_vinyl_list(p, o, e)
            if f is None: continue
            s2 = _read_memorypack_vinyl_list(p, f[0], e)
            if s2 is not None and s2[0] == e:
                c = (f[1], s2[1], o, f[0])
                if m is None or (c[0]+c[1], c[2]) > (m[0]+m[1], m[2]): m = c
        car = {"index": i, "id": cid, "vinyls": m[0] if m else -1, "window": m[1] if m else -1,
               "transferable": False, "fingerprint": hashlib.sha256(p[s:e]).hexdigest()}
        if m:
            inst = _find_memorypack_car_instance(p, s, m[2])
            if inst:
                iid, iraw = inst
                sf = _extract_memorypack_style_fields(p, s, e, m[2], iraw)
                car.update({"instance_id": iid, "car_id_raw": p[s+1:s+5], "instance_raw": iraw,
                            "vinyls_raw": p[m[2]:m[3]], "window_raw": p[m[3]:e],
                            "style_fields": sf, "style_transferable": sf is not None, "transferable": True})
        out.append(car)
    return out
def _parse_cpm1_memorypack_vinyls(p):
    recs = _memorypack_car_offsets(p)
    if recs is None: return None
    names = _load_car_names()
    out = []
    for i, (s, cid) in enumerate(recs):
        e = recs[i+1][0] if i+1 < len(recs) else len(p)
        m = None
        for o in range(s+5, e-10):
            f = _read_memorypack_vinyl_list(p, o, e)
            if f is None: continue
            s2 = _read_memorypack_vinyl_list(p, f[0], e)
            if s2 is not None:
                c = (f[1], s2[1], o, f[0], s2[0])
                if m is None or (c[0]+c[1]) > (m[0]+m[1]): m = c
        tr = m is not None
        out.append({"id": cid, "index": i, "name": names.get(str(cid), f"Car {cid}"),
                    "transferable": tr, "style_transferable": tr,
                    "vinyls": m[0] if m else -1, "window": m[1] if m else -1,
                    "vinyls_raw": p[m[2]:m[3]] if m else None, "window_raw": p[m[3]:m[4]] if m else None})
    return out

async def _call_cpm1_function(fn, tok, lid, s):
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    ep = _encrypt_value(json.dumps({}), lid)
    if not ep: return None, "ENC_FAIL"
    le = ""
    for base in (CPM1_API_BASE, *CPM1_FALLBACK_BASES):
        try:
            async with s.post(f"{base}/{fn}", json={"data": ep}, headers=h, timeout=aiohttp.ClientTimeout(total=20)) as r:
                try: b = await r.json(content_type=None)
                except: b = await r.text()
                if r.status != 200: le = f"HTTP_{r.status}"; continue
                if not isinstance(b, dict) or "result" not in b: le = "BAD"; continue
                return _json_unwrap(b.get("result")), ""
        except Exception as ex: le = type(ex).__name__
    return None, le

async def _read_cpm1_cloud(tok, lid, s):
    raw, err = await _call_cpm1_function(CPM1_CARS_FUNCTION, tok, lid, s)
    if err: return None, err
    if not isinstance(raw, list): return None, "INVALID"
    names = _load_car_names()
    cars = [n for i, c in enumerate(raw) if (n := _normalize_cpm1_car(c, i, names))]
    if not cars: return None, "EMPTY"
    if any(c.get("style_transferable") for c in cars): return cars, ""
    return None, "NO_VINYLS"

async def _read_cpm1_rtdb(tok, lid, s):
    h = {"Authorization": f"Bearer {tok}"}
    paths = [f"/users/{lid}/OneCar.json", f"/OneCar/{lid}.json", f"/users/{lid}/cars.json", f"/users/{lid}/garage.json", f"/cars/{lid}.json"]
    for path in paths:
        try:
            async with s.get(f"{CPM1_DATABASE_URL}{path}", headers=h, timeout=aiohttp.ClientTimeout(total=15)) as r:
                t = await r.text()
                if r.status == 200 and t and t.strip() != "null":
                    try: v = json.loads(t)
                    except: v = t.strip().strip('"')
                    if isinstance(v, str) and len(v) > 10:
                        try: return base64.b64decode(v), ""
                        except: return None, "B64_ERR"
                elif r.status == 401: return None, "EXPIRED"
        except: pass
    return None, "NOT_FOUND"

async def open_cpm1_cloud_session(email, password):
    res = {"cars": None, "error": ""}
    auth = await firebase_verify_password(email, password, api_key=CPM1_API_KEY)
    if "error" in auth:
        res["error"] = str(auth["error"].get("message","AUTH_ERR")); return res
    tok = auth.get("idToken"); lid = auth.get("localId")
    if not tok or not lid: res["error"] = "INVALID_AUTH"; return res
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
        cars, _ = await _read_cpm1_cloud(tok, lid, s)
        if cars: res["cars"] = cars; return res
        rb, _ = await _read_cpm1_rtdb(tok, lid, s)
        if rb:
            lc = _parse_cpm1_memorypack_vinyls(rb)
            if lc: res["cars"] = lc; return res
    res["error"] = CPM1_UNSUPPORTED_CLOUD_ERROR
    return res

async def _call_cpm2_function(fn, tok, lid):
    ep = _encrypt_value(json.dumps({}), lid)
    if not ep: return False, None
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    async def do(s):
        try:
            async with s.post(f"{CPM2_API_BASE}/{fn}", json={"data": ep}, headers=h, timeout=aiohttp.ClientTimeout(total=15)) as r:
                try: b = await r.json(content_type=None)
                except: return False, None
                if r.status != 200 or not isinstance(b, dict) or "result" not in b: return False, None
            res = b.get("result")
            if isinstance(res, str):
                try: res = json.loads(res)
                except: pass
            return True, res
        except: return False, None
    shared = _balance_http_session.get()
    if shared: return await do(shared)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as own:
        return await do(own)

async def _call_cpm2_payload(fn, tok, payload, session):
    global _save_car_function_name
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    async def try_ep(fnc):
        try:
            async with session.post(f"{CPM2_API_BASE}/{fnc}", json={"data": payload}, headers=h, timeout=aiohttp.ClientTimeout(total=20)) as r:
                text = await r.text()
                log.info(f"[SaveCar] {fnc} → {r.status} — {text[:180]}")
                if r.status == 404: return None
                try: body = json.loads(text)
                except: return False, {"_raw": text[:300], "_status": r.status}
                if r.status != 200: return False, {"_raw": text[:300], "_status": r.status, "_body": body}
                if not isinstance(body, dict) or "result" not in body:
                    return False, {"_raw": text[:300], "_body": body}
                res = body.get("result")
                if isinstance(res, str):
                    try:
                        p = json.loads(res)
                        if p is not None: res = p
                    except: pass
                if _function_error_code(res) is not None: return False, res
                return True, res
        except Exception as ex:
            log.error(f"[SaveCar] {fnc} exception: {ex}")
            return False, {"_exception": str(ex)}
    if _save_car_function_name:
        r = await try_ep(_save_car_function_name)
        if r is not None: return r
    for fnc in CPM2_SAVE_CAR_FUNCTION_CANDIDATES:
        if fnc == _save_car_function_name: continue
        r = await try_ep(fnc)
        if r is None: continue
        _save_car_function_name = fnc
        return r
    return False, {"_raw": "All SaveCar 404"}

def _function_error_code(res):
    if isinstance(res, (int, float)) and not isinstance(res, bool):
        if res == 1: return None
        return int(res) if float(res).is_integer() else str(res)
    if isinstance(res, str) and res.strip().lstrip("-").isdigit():
        n = int(res.strip()); return None if n == 1 else n
    if not isinstance(res, dict): return None
    c = res.get("code")
    if c is not None:
        try: nc = int(c)
        except: nc = str(c)
        if nc != 1: return nc
    if res.get("success") is False: return "success=false"
    if res.get("error"): return str(res["error"])
    return None

async def _read_raw_cars_cpm2(tok, lid):
    global _cars_function_name
    if _cars_function_name:
        try:
            ok, v = await _call_cpm2_function(_cars_function_name, tok, lid)
            if ok: return v
        except: pass
    results = await asyncio.gather(*(_call_cpm2_function(n, tok, lid) for n in CPM2_CARS_FUNCTION_CANDIDATES), return_exceptions=True)
    for n, r in zip(CPM2_CARS_FUNCTION_CANDIDATES, results):
        if isinstance(r, Exception): continue
        ok, v = r
        if ok:
            _cars_function_name = n
            return v
    return None

async def _auth_vinyl(email, password, session):
    a = {}
    for i in range(3):
        a = await firebase_verify_password(email, password, api_key=CPM2_API_KEY, session=session)
        er = (a.get("error") or {}).get("message", "")
        tr = bool(a.get("error", {}).get("transient")) or any(m in er.upper() for m in ("SERVICE_UNAVAILABLE","CONNECTION_ERROR","TOO_MANY_ATTEMPTS","TIMEOUT"))
        if not tr: break
        if i < 2: await asyncio.sleep(0.35 * (2**i))
    tok = str(a.get("idToken") or ""); lid = str(a.get("localId") or "")
    ec = str((a.get("error") or {}).get("message") or "AUTH_FAILED")
    return tok, lid, "" if tok and lid else ec

async def open_cloud_vinyl_session(email, password):
    res = {"cars": None, "error": ""}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            tok, lid, ae = await _auth_vinyl(email, password, s)
            if ae: res["error"] = ae; return res
            t = set_balance_session(s)
            try: v = await _read_raw_cars_cpm2(tok, lid)
            finally: reset_balance_session(t)
        if v is None: res["error"] = "CARS_UNAVAILABLE"; return res
        if isinstance(v, list) and len(v) == 0:
            res["cars"] = []
            return res
        cars = _parse_memorypack_cloud_vinyls(v, lid)
        if cars is None: res["error"] = "VINYL_SCHEMA_UNSUPPORTED"; return res
        names = _load_car_names()
        res["cars"] = [{**c, "name": names.get(str(c["id"]), f"Car {c['id']}")} for c in cars]
    except Exception as ex:
        log.error(f"open_cloud_vinyl_session error: {ex}")
        res["error"] = "CONNECTION_ERROR"
    return res

def _encode_save_car_fields(target, donor, local_id):
    values = {0: bytes(target["car_id_raw"]), 1: bytes(target["instance_raw"]), 7: bytes(donor["vinyls_raw"]), 8: bytes(donor["window_raw"])}
    fields = tuple(sorted(values.items()))
    ser = bytearray(struct.pack("<i", len(fields)))
    for k, f in fields:
        ser.extend(struct.pack("<Hi", k, len(f))); ser.extend(f)
    xk = _memorypack_xor_key(local_id)
    if brotli is None or not xk: raise ValueError("UNAVAIL")
    packed = brotli.compress(bytes(ser))
    enc = bytes(b ^ xk[i % len(xk)] for i, b in enumerate(packed))
    return base64.b64encode(enc).decode("ascii")

async def _save_and_verify_pairs(pairs, tgt_email, tgt_pw, res):
    try:
        for t, d in pairs:
            if not isinstance(d.get("vinyls_raw"), (bytes, bytearray)):
                res["error"] = f"DONOR_NO_VINYLS:{d.get('name')}"; return res
            if not isinstance(d.get("window_raw"), (bytes, bytearray)):
                res["error"] = f"DONOR_NO_WINDOW:{d.get('name')}"; return res
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            tok, lid, ae = await _auth_vinyl(tgt_email, tgt_pw, s)
            if ae:
                res["error"] = f"CPM2_AUTH_FAILED: {ae}"; return res
            t = set_balance_session(s)
            try:
                ep = []
                for tgt, dn in pairs:
                    pl = _encode_save_car_fields(tgt, dn, lid)
                    ok, sr = await _call_cpm2_payload(_save_car_function_name or CPM2_SAVE_CAR_FUNCTION, tok, pl, s)
                    if not ok:
                        sc = _function_error_code(sr)
                        if sc is not None: res["server_code"] = sc
                        if sc is not None: res["error"] = f"SAVE_REJECTED: {tgt.get('name')} (code={sc})"
                        else:
                            diag = ""
                            if isinstance(sr, dict):
                                if "_raw" in sr: diag = f"HTTP {sr.get('_status')}: {sr['_raw'][:180]}"
                                elif "_exception" in sr: diag = f"Exc: {sr['_exception'][:180]}"
                                elif "_body" in sr: diag = f"Body: {str(sr['_body'])[:180]}"
                            res["error"] = f"SAVE_FAILED: {tgt.get('name')} — {diag or str(sr)[:180]}"
                        return res
                    res["sent"] += 1
                    ep.append((str(tgt.get("instance_id") or ""), dn.get("vinyls_raw"), dn.get("window_raw")))
                for at in range(7):
                    if at: await asyncio.sleep(float(at))
                    vv = await _read_raw_cars_cpm2(tok, lid)
                    vc = _parse_memorypack_cloud_vinyls(vv, lid)
                    if vc is None: continue
                    vm = {str(c.get("instance_id")): c for c in vc if c.get("instance_id")}
                    cnt = 0
                    for iid, dv, dw in ep:
                        x = vm.get(iid)
                        if x and x.get("vinyls_raw") == dv and x.get("window_raw") == dw: cnt += 1
                    res["verified"] = cnt
                    if cnt == len(ep): break
                if res["verified"] != res["sent"]:
                    res["error"] = "SAVE_VERIFY_PENDING"
                return res
            finally:
                reset_balance_session(t)
    except Exception as ex:
        res["error"] = f"EXCEPTION:{ex}"; return res

def _apply_unlock_fields(tc, mode="police"):
    style = tc.get("style_fields")
    if not isinstance(style, dict): raise ValueError("STYLE_UNAVAIL")
    if 5 not in style: raise ValueError("FIELD5_MISSING")
    f5 = bytearray(style[5])
    po = None
    for i in range(len(f5) - 3):
        if f5[i] == 0x04 and f5[i+3] == 0x05 and f5[i+1] in (0,1) and f5[i+2] in (0,1):
            po = i; break
    if po is None: raise ValueError("POLICE_MARKER_MISSING")
    if mode == "police":
        f5[po+1] = 0x01; f5[po+2] = 0x01
    elif mode == "air":
        ao = po + 29
        if ao >= len(f5): raise ValueError(f"AIRSUS_OOB({ao}>={len(f5)})")
        if f5[ao] == 0x02:
            f5[ao+1] = 0x01; f5[ao+2] = 0x01
        elif f5[ao] in (0x00, 0xFF):
            f5 = bytearray(f5[:ao]) + bytearray([0x02, 0x01, 0x01]) + bytearray(f5[ao+1:])
        else: raise ValueError(f"AIRSUS_BYTE_{f5[ao]:02x}")
    else: raise ValueError("INVALID_MODE")
    return {5: bytes(f5)}

def _encode_unlock_payload(tc, lid, mode):
    style = tc.get("style_fields")
    if not isinstance(style, dict) or any(k not in style for k in range(2,7)):
        raise ValueError("STYLE_SCHEMA_UNSUPPORTED")
    values = {0: bytes(tc["car_id_raw"]), 1: bytes(tc["instance_raw"]),
              2: bytes(style[2]), 3: bytes(style[3]), 4: bytes(style[4]),
              5: bytes(style[5]), 6: bytes(style[6])}
    values.update(_apply_unlock_fields(tc, mode))
    fields = tuple(sorted(values.items()))
    ser = bytearray(struct.pack("<i", len(fields)))
    for k, f in fields:
        ser.extend(struct.pack("<Hi", k, len(f))); ser.extend(f)
    xk = _memorypack_xor_key(lid)
    if brotli is None or not xk: raise ValueError("UNAVAIL")
    packed = brotli.compress(bytes(ser))
    enc = bytes(b ^ xk[i % len(xk)] for i, b in enumerate(packed))
    return base64.b64encode(enc).decode("ascii")

async def execute_api_unlock(email, password, car_index, mode):
    out = {"sent": 0, "verified": 0, "total": 1, "error": "", "mode": mode}
    snap = await open_cloud_vinyl_session(email, password)
    if snap.get("error"): out["error"] = f"CPM2: {snap['error']}"; return out
    cars = snap.get("cars") or []
    target = next((c for c in cars if c.get("index") == car_index), None)
    if not target: out["error"] = "Car not found"; return out
    if not target.get("transferable"): out["error"] = "Car not accessible"; return out
    if not isinstance(target.get("style_fields"), dict): out["error"] = "Style missing"; return out
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as s:
            tok, lid, err = await _auth_vinyl(email, password, s)
            if err: out["error"] = f"Auth: {err}"; return out
            try: pl = _encode_unlock_payload(target, lid, mode)
            except Exception as ee: out["error"] = f"Encode: {ee}"; return out
            ok, sr = await _call_cpm2_payload(_save_car_function_name or CPM2_SAVE_CAR_FUNCTION, tok, pl, s)
            if not ok:
                code = _function_error_code(sr)
                if code is None and isinstance(sr, dict):
                    if "_raw" in sr: diag = f"HTTP {sr.get('_status')}: {sr['_raw'][:180]}"
                    elif "_exception" in sr: diag = f"Exc: {sr['_exception'][:180]}"
                    elif "_body" in sr: diag = f"Body: {str(sr['_body'])[:180]}"
                    else: diag = f"Unknown: {str(sr)[:180]}"
                    out["error"] = f"Save rejected — {diag}"
                else: out["error"] = f"Save rejected (code={code})"
                return out
            out["sent"] = 1
            expected = str(target.get("instance_id"))
            for at in range(5):
                if at: await asyncio.sleep(float(at))
                vv = await _read_raw_cars_cpm2(tok, lid)
                vc = _parse_memorypack_cloud_vinyls(vv, lid)
                if vc is None: continue
                for c in vc:
                    if str(c.get("instance_id")) != expected: continue
                    st = c.get("style_fields", {})
                    if not isinstance(st, dict) or 5 not in st: continue
                    f5 = st[5]; po = None
                    for i in range(len(f5) - 3):
                        if f5[i] == 0x04 and f5[i+3] == 0x05: po = i; break
                    if po is None: continue
                    if mode == "police":
                        if f5[po+1] == 1 and f5[po+2] == 1: out["verified"] = 1; break
                    elif mode == "air":
                        ao = po + 29
                        if ao + 2 < len(f5) and f5[ao] == 0x02 and f5[ao+1] == 1 and f5[ao+2] == 1:
                            out["verified"] = 1; break
                if out["verified"] == 1: break
            if out["verified"] != 1: out["error"] = "Sent, verification pending"
            return out
    except Exception as ex:
        out["error"] = f"Exc: {ex}"; return out

# ==========================================================
# STARS HANDLERS
# ==========================================================
@bot.pre_checkout_query_handler(func=lambda q: True)
def handle_pre_checkout(query: PreCheckoutQuery):
    try: bot.answer_pre_checkout_query(query.id, ok=True)
    except Exception as ex:
        log.error(f"Pre-checkout: {ex}")

@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    try:
        sp = message.successful_payment
        payload = sp.invoice_payload; charge_id = sp.telegram_payment_charge_id; total = sp.total_amount
        parts = payload.split("|")
        if len(parts) != 4: return
        kind = parts[0]; user_id = int(parts[1]); package_id = parts[2]; payment_id = parts[3]
        existing = _run_async(db_get_payment(payment_id))
        if existing and existing.get("status") == "completed": return
        if kind == "coins":
            pkgs = _run_async(db_get_shop_packages())
            pkg = next((p for p in pkgs if p["id"] == package_id), None)
            if not pkg: return
            total_coins = pkg_total(pkg)
            new_bal = _run_async(db_add_coins(user_id, total_coins))
            _run_async(db_mark_paid(payment_id, charge_id))
            _run_async(db_log_activity(user_id, message.from_user.username or "", "stars_payment_success", f"+{total_coins} coins ({total}⭐)", 0))
            try: bot.send_message(user_id, f"{E_CHECK} <b>Payment Successful!</b>\n\n💎 +{total_coins} coins added\n⭐ Paid: {total} Stars\n💰 Balance: <b>{new_bal}</b> coins")
            except: pass
            try: bot.send_message(ADMIN_ID, f"💰 <b>NEW STARS PAYMENT</b>\n\n👤 @{message.from_user.username or '?'} ({user_id})\n📦 {total_coins} coins\n⭐ {total} Stars\n🆔 <code>{charge_id}</code>")
            except: pass
        elif kind == "custom":
            _run_async(db_mark_paid(payment_id, charge_id))
            desc = (existing or {}).get("description", "")
            try: bot.send_message(user_id, f"{E_CHECK} <b>Payment Received!</b>\n\n⭐ Paid: {total} Stars\n📝 {desc or 'Custom payment'}\n\nℹ️ Admin will credit your account manually.")
            except: pass
            try: bot.send_message(ADMIN_ID, f"💳 <b>CUSTOM PAYMENT RECEIVED</b>\n\n👤 @{message.from_user.username or '?'} (<code>{user_id}</code>)\n⭐ {total} Stars\n📝 {desc or '(no description)'}\n🆔 <code>{charge_id}</code>")
            except: pass
    except Exception as ex:
        log.exception(f"successful_payment: {ex}")

# ==========================================================
# BOT HANDLERS
# ==========================================================
def _main_keyboard(uid):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=WEBAPP_URL), icon_custom_emoji_id=EMOJI_IDS["rocket"]))
    if BOT_USERNAME:
        ref_link = f"https://t.me/{BOT_USERNAME}?start=REF_{uid}"
        kb.add(InlineKeyboardButton("🎁 Share Referral", url=f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote('Join Mrx Bot! Get +5 free coins 🎁')}"))
    kb.add(InlineKeyboardButton("Support", url=SUPPORT_URL, icon_custom_emoji_id=EMOJI_IDS["chat"]))
    return kb

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    uid = message.from_user.id
    parts = message.text.strip().split(maxsplit=1)
    ref_payload = parts[1].strip() if len(parts) > 1 else ""
    if ref_payload.startswith("REF_"):
        try:
            rid = int(ref_payload[4:])
            _run_async(process_referral(rid, uid, message.from_user.username or ""))
        except: pass
    try:
        _run_async(db_upsert_user(uid, {"username": message.from_user.username, "first_name": message.from_user.first_name, "last_name": message.from_user.last_name, "language_code": message.from_user.language_code}))
    except: pass
    coins = _run_async(db_get_coins(uid)) or 0
    subbed = _run_async(db_is_subscribed(uid))
    wallet = "👑 FREE (Subscriber)" if subbed else f"💎 {coins} coins"
    ref_link = f"https://t.me/{BOT_USERNAME}?start=REF_{uid}" if BOT_USERNAME else "(loading...)"
    txt = (f"{E_ART} <b>Mrx Vinyl Transfer Bot</b>\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
           f"👤 <b>Your Wallet:</b> {wallet}\n🆔 <code>{uid}</code>\n\n"
           f"<b>✨ Features:</b>\n\n{E_CAR1} CPM1 → CPM2 vinyl transfer\n{E_CAR2} CPM2 → CPM2 vinyl transfer\n"
           f"🚓 Police Unlock\n🚗 AirSus Unlock\n💎 Buy coins via Telegram Stars\n\n"
           f"<b>🎁 Referral Program:</b>\nInvite friends → <b>+{REF_REWARD} coins</b> each\n<code>{ref_link}</code>\n\n"
           f"👑 <b>Subscribers get FREE access!</b>\n\n━━━━━━━━━━━━━━━━━━━━\n{E_ZAP} <b>Powered by Mrx</b>\n\n{E_DOWN} <i>Tap below to launch</i>")
    try: bot.send_message(message.chat.id, txt, reply_markup=_main_keyboard(uid))
    except: pass

@bot.message_handler(commands=["ping"])
def cmd_ping(message):
    try: bot.reply_to(message, f"{E_PING} <b>Pong!</b> {E_CHECK}")
    except: pass

@bot.message_handler(commands=["balance", "coins"])
def cmd_balance(message):
    uid = message.from_user.id
    coins = _run_async(db_get_coins(uid)) or 0
    subbed = _run_async(db_is_subscribed(uid))
    if subbed: txt = f"👑 <b>Subscriber</b> — all features FREE\n🆔 <code>{uid}</code>"
    else: txt = f"💎 <b>Your Balance: {coins} coins</b>\n🆔 <code>{uid}</code>"
    try: bot.reply_to(message, txt)
    except: pass

@bot.message_handler(commands=["referral", "ref"])
def cmd_referral(message):
    uid = message.from_user.id
    stats = _run_async(db_get_referral_stats(uid)) or {"count": 0}
    link = f"https://t.me/{BOT_USERNAME}?start=REF_{uid}" if BOT_USERNAME else ""
    txt = (f"🎁 <b>Your Referral Stats</b>\n\n👥 Total invites: <b>{stats['count']}</b>\n💎 Coins earned: <b>{stats['count'] * REF_REWARD}</b>\n🎯 Reward per invite: <b>+{REF_REWARD} coins</b>\n\n<b>Your Link:</b>\n<code>{link}</code>")
    try: bot.reply_to(message, txt)
    except: pass

@bot.message_handler(commands=["list"])
def cmd_list(message):
    if message.from_user.id != ADMIN_ID: return
    subs = _run_async(db_list_subscriptions()) or []
    if not subs: bot.reply_to(message, "None"); return
    lines = [f"<b>{E_CLIP} Active Subs:</b>\n"]
    for s in subs: lines.append(f"• <code>{s['user_id']}</code> — {s['expiry']}")
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["add"])
def cmd_add(message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.strip().split()
    if len(p) != 3: bot.reply_to(message, "Usage: /add uid days"); return
    try: uid = int(p[1]); days = int(p[2])
    except: bot.reply_to(message, "Invalid"); return
    s = _run_async(db_add_subscription(uid, days))
    bot.reply_to(message, f"{E_CHECK} {uid} → <b>{s}</b>")

@bot.message_handler(commands=["remove"])
def cmd_remove(message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.strip().split()
    if len(p) != 2: bot.reply_to(message, "Usage: /remove uid"); return
    try: uid = int(p[1])
    except: bot.reply_to(message, "Invalid"); return
    ok = _run_async(db_remove_subscription(uid))
    bot.reply_to(message, f"{E_CHECK} Removed {uid}" if ok else f"{E_WARN} Not found")

@bot.message_handler(commands=["givecoins"])
def cmd_givecoins(message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.strip().split()
    if len(p) != 3: bot.reply_to(message, "Usage: /givecoins uid amount"); return
    try: uid = int(p[1]); amt = int(p[2])
    except: bot.reply_to(message, "Invalid"); return
    new = _run_async(db_add_coins(uid, amt))
    _run_async(db_log_activity(uid, "", "admin_coin_add", f"+{amt}", 0))
    try: bot.send_message(uid, f"{E_CHECK} +{amt} coins! Balance: {new}")
    except: pass
    bot.reply_to(message, f"✅ {uid} +{amt} = {new}")

@bot.message_handler(commands=["logs"])
def cmd_logs(message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.strip().split()
    uid = int(p[1]) if len(p) > 1 else None
    logs = _run_async(db_get_activities(limit=10, user_id=uid)) or []
    if not logs: bot.reply_to(message, "No logs found."); return
    txt = "<b>📋 Recent Logs</b>\n\n"
    for l in logs:
        txt += f"👤 <code>{l['user_id']}</code> | {l['action']}\n📝 {str(l.get('details',''))[:50]}\n💰 {l.get('cost', 0)} | 🕒 {l.get('created_at_ist','')}\n━━━━━━━━━━━━━━━\n"
    bot.reply_to(message, txt)

@bot.message_handler(commands=["bonusall"])
def cmd_bonusall(message):
    if message.from_user.id != ADMIN_ID: return
    p = message.text.strip().split()
    if len(p) != 2: bot.reply_to(message, "Usage: /bonusall amount"); return
    try: amt = int(p[1])
    except: bot.reply_to(message, "Invalid"); return
    if amt < 1 or amt > 10000: bot.reply_to(message, "1-10000 only"); return
    threading.Thread(target=lambda: _run_async(_bonus_all_inner(amt)), daemon=True).start()
    bot.reply_to(message, f"⏳ Sending +{amt} coins to all users...")

async def _bonus_all_inner(amount):
    count = 0; failed = 0
    async with db_client() as c:
        if not c: return
        r = await c.execute("SELECT user_id FROM users")
        rows = list(r.rows) if (r and r.rows) else []
    for row in rows:
        uid = row[0]
        if not uid: continue
        try:
            await db_add_coins(int(uid), amount); count += 1
            try: bot.send_message(int(uid), f"🎁 <b>BONUS!</b>\n\n💎 +{amount} coins!\n🕒 {ts_ist()}")
            except: pass
            await asyncio.sleep(0.05)
        except: failed += 1
    try: bot.send_message(ADMIN_ID, f"✅ Bonus: +{amount} to {count} users (failed: {failed})")
    except: pass

# ==========================================================
# FASTAPI
# ==========================================================
app = FastAPI(title="Mrx Mini App")
_sessions = {}

def _start_polling_thread():
    def _poll():
        try:
            log.info("🔄 Starting bot polling...")
            bot.polling(none_stop=True, interval=0, timeout=20, long_polling_timeout=20, skip_pending=True)
        except Exception as ex:
            log.error(f"Polling fatal: {ex}")
            time.sleep(5)
            try: _start_polling_thread()
            except: pass
    threading.Thread(target=_poll, daemon=True, name="bot_polling").start()

@app.on_event("startup")
async def _startup():
    global BOT_USERNAME
    ok = await init_db()
    if not ok:
        for attempt in range(4):
            await asyncio.sleep(3)
            ok = await init_db()
            if ok: break
    if ok and await db_ping():
        log.info("✅ SQLite ping OK")
        await ensure_indexes()
        await seed_default_subs()
        await seed_default_shop()
        log.info("✅ DB fully ready")
    else:
        log.error("❌ DB unavailable")
    # remove any legacy webhook (we run via polling only)
    try: bot.remove_webhook()
    except: pass
    try:
        me = bot.get_me()
        BOT_USERNAME = me.username
        log.info(f"✅ Bot: @{BOT_USERNAME}")
    except Exception as ex:
        log.warning(f"get_me: {ex}")
    try:
        bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Open App", web_app=WebAppInfo(url=WEBAPP_URL)))
        bot.set_my_commands([BotCommand("start", "Start"), BotCommand("balance", "My Coins"), BotCommand("referral", "My Referral"), BotCommand("ping", "Ping")])
    except: pass
    _start_polling_thread()
    log.info("✅ Startup complete — polling active")

@app.get("/health")
async def health():
    ping_ok = await db_ping()
    return {"ok": True, "db_path": DB_PATH, "db_ping": ping_ok, "bot_username": BOT_USERNAME, "polling_active": True, "time_ist": ts_ist()}

def _verify_init_data(idt):
    try: p = dict(urllib.parse.parse_qsl(idt, keep_blank_values=True))
    except: return None
    h = p.pop("hash", None)
    if not h: return None
    dc = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
    sk = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(sk, dc.encode(), hashlib.sha256).hexdigest(), h): return None
    try: return json.loads(p.get("user", "{}"))
    except: return None

async def _get_current_user(x_init_data: str = Header(default="")):
    if not x_init_data: raise HTTPException(401, "Missing init data")
    user = _verify_init_data(x_init_data)
    if not user: raise HTTPException(401, "Invalid init data")
    uid = int(user.get("id"))
    try:
        await db_upsert_user(uid, {"username": user.get("username"), "first_name": user.get("first_name"), "last_name": user.get("last_name"), "language_code": user.get("language_code")})
    except: pass
    return user

class CredsIn(BaseModel): email: str; password: str
class TransferPlanIn(BaseModel):
    source_type: str; src_email: str; src_password: str
    tgt_email: str; tgt_password: str; plan: list[dict]
class AddSubIn(BaseModel): user_id: int; days: int
class UnlockIn(BaseModel): email: str; password: str; car_index: int
class BuyCoinsIn(BaseModel): package_id: str
class CustomInvoiceIn(BaseModel):
    user_id: int; stars: int; description: str = ""
class BonusAllIn(BaseModel): amount: int
class UpdateShopIn(BaseModel):
    id: str; coins: int; bonus: int; price: int
class BroadcastIn(BaseModel):
    text: str; photo_url: str = ""

@app.get("/", response_class=HTMLResponse)
async def index(): return INDEX_HTML

@app.get("/api/me")
async def api_me(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    sub = await db_get_subscription(uid)
    coins = await db_get_coins(uid)
    is_sub = await db_is_subscribed(uid)
    return {"user_id": uid, "username": user.get("username"), "first_name": user.get("first_name"), "coins": coins, "is_admin": uid == ADMIN_ID, "subscription": sub, "is_subscriber": is_sub, "server_time_ist": ts_ist()}

@app.get("/api/subscriptions")
async def api_subs(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    if uid == ADMIN_ID:
        return {"ok": True, "subscriptions": await db_list_subscriptions(), "is_admin": True}
    sub = await db_get_subscription(uid)
    return {"ok": True, "subscriptions": [sub] if sub else [], "is_admin": False}

@app.get("/api/coin-shop")
async def api_shop(x_init_data: str = Header(default="")):
    await _get_current_user(x_init_data)
    pkgs = await db_get_shop_packages()
    pkgs = [{**p, "total": pkg_total(p)} for p in pkgs]
    return {"ok": True, "packages": pkgs}

@app.post("/api/coin-shop/buy")
async def api_buy(body: BuyCoinsIn, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    pkgs = await db_get_shop_packages()
    pkg = next((p for p in pkgs if p["id"] == body.package_id), None)
    if not pkg: raise HTTPException(400, "Invalid package")
    total_coins = pkg_total(pkg)
    pid = await db_create_pending_payment(uid, user.get("username") or "", pkg["id"], total_coins, pkg["price"], kind="coins")
    payload = f"coins|{uid}|{pkg['id']}|{pid}"
    label = f"{total_coins} Mrx Coins"
    if pkg.get("bonus"): label = f"{pkg['coins']} Coins + {pkg['bonus']} Bonus"
    prices = [LabeledPrice(label=label, amount=pkg["price"])]
    try:
        invoice_link = bot.create_invoice_link(title=f"{total_coins} Mrx Coins", description=f"Buy {total_coins} coins for Mrx Mini App", payload=payload, provider_token="", currency="XTR", prices=prices)
        try: bot.send_message(ADMIN_ID, f"💳 <b>NEW STARS INVOICE</b>\n\n👤 @{user.get('username') or '?'} ({uid})\n📦 {total_coins} coins\n⭐ {pkg['price']} Stars\nID: <code>{pid}</code>")
        except: pass
        return {"ok": True, "payment_id": pid, "package": {**pkg, "total": total_coins}, "invoice_link": invoice_link}
    except Exception as ex:
        log.error(f"❌ create_invoice_link: {ex}")
        return {"ok": False, "error": f"Payment unavailable: {str(ex)[:120]}"}

@app.get("/api/activities")
async def api_acts(user_id: Optional[int] = Query(None), x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    return {"ok": True, "activities": await db_get_activities(100, user_id)}

@app.get("/api/admin/user-features")
async def api_user_features(user_id: int = Query(...), x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    features = await db_get_user_feature_stats(user_id)
    return {"ok": True, "user_id": user_id, "features": features}

@app.get("/api/admin/payments")
async def api_admin_pay(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    return {"ok": True, "payments": await db_list_payments(limit=200)}

@app.get("/api/admin/coin-holders")
async def api_admin_holders(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    users = await db_list_all_coin_holders(300)
    return {"ok": True, "users": users}

@app.get("/api/admin/users")
async def api_admin_users(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    async with db_client() as c:
        if not c: return {"ok": True, "users": []}
        try:
            r = await c.execute("""SELECT u.user_id, u.username, u.first_name, u.coins, u.updated_at,
                COALESCE(a.cnt, 0) as act_cnt, COALESCE(p.cnt, 0) as pay_cnt, s.expiry
                FROM users u
                LEFT JOIN (SELECT user_id, COUNT(*) as cnt FROM activities GROUP BY user_id) a ON a.user_id = u.user_id
                LEFT JOIN (SELECT user_id, COUNT(*) as cnt FROM payments WHERE status='completed' GROUP BY user_id) p ON p.user_id = u.user_id
                LEFT JOIN subscriptions s ON s.user_id = u.user_id
                ORDER BY u.updated_at DESC LIMIT 200""")
            users = []
            if r and r.rows:
                today = datetime.date.today()
                for row in r.rows:
                    uid = int(row[0]); expiry = row[7]
                    is_sub = False
                    if expiry:
                        try: is_sub = datetime.datetime.strptime(expiry, "%Y-%m-%d").date() >= today
                        except: pass
                    users.append({"user_id": uid, "username": row[1] or "", "first_name": row[2] or "", "coins": int(row[3] or 0), "activities": int(row[5] or 0), "completed_payments": int(row[6] or 0), "is_subscriber": uid == ADMIN_ID or is_sub, "expiry": expiry, "updated_at_ist": str(row[4] or "")[:19]})
            return {"ok": True, "users": users}
        except Exception as ex:
            log.error(f"admin users: {ex}")
            return {"ok": True, "users": []}

@app.get("/api/referral/stats")
async def api_ref_stats(x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    link = f"https://t.me/{BOT_USERNAME}?start=REF_{uid}" if BOT_USERNAME else ""
    stats = await db_get_referral_stats(uid)
    return {"ok": True, "referral_link": link, "count": stats["count"], "coins_earned": stats["count"] * REF_REWARD, "reward_per_ref": REF_REWARD, "recent": stats["recent"]}

@app.get("/api/referral/leaderboard")
async def api_ref_lb(x_init_data: str = Header(default="")):
    await _get_current_user(x_init_data)
    leaders = await db_get_referral_leaderboard(10)
    return {"ok": True, "leaders": leaders}

@app.post("/api/admin/broadcast")
async def api_broadcast(body: BroadcastIn, x_init_data: str = Header(default="")):
    admin = await _get_current_user(x_init_data)
    if int(admin["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    if not body.text.strip() and not body.photo_url.strip(): raise HTTPException(400, "Empty message")
    async with db_client() as c:
        if not c: raise HTTPException(503, "DB unavailable")
        r = await c.execute("SELECT user_id FROM users")
        user_ids = [int(row[0]) for row in (r.rows if r and r.rows else [])]
    def _do_broadcast():
        sent = 0; failed = 0
        for uid in user_ids:
            try:
                if body.photo_url.strip(): bot.send_photo(uid, body.photo_url.strip(), caption=body.text.strip() or None, parse_mode="HTML")
                else: bot.send_message(uid, body.text.strip(), parse_mode="HTML", disable_web_page_preview=True)
                sent += 1
            except: failed += 1
            time.sleep(0.05)
        try: bot.send_message(ADMIN_ID, f"📢 <b>Broadcast Done</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}")
        except: pass
    threading.Thread(target=_do_broadcast, daemon=True).start()
    return {"ok": True, "total": len(user_ids), "started": True}

@app.post("/api/inspect/{kind}")
async def api_inspect(kind: str, body: CredsIn, source: str = Query(""), x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    if kind not in ("cpm1","cpm2"): raise HTTPException(400, "Invalid")
    is_sub = await db_is_subscribed(uid)

    if source in ("police", "air", "airsus"):
        cost = 0
    else:
        cost = 0 if is_sub else (COST_INSPECT_CPM1 if kind == "cpm1" else COST_INSPECT_CPM2)

    if cost > 0:
        cur = await db_get_coins(uid)
        if cur < cost: raise HTTPException(402, f"Need {cost} coins (you have {cur})")
        ok = await db_deduct_coins(uid, cost)
        if not ok: raise HTTPException(402, "Deduct failed")
    if kind == "cpm1": snap = await open_cpm1_cloud_session(body.email, body.password)
    else: snap = await open_cloud_vinyl_session(body.email, body.password)
    if snap.get("error"):
        if cost > 0: await db_add_coins(uid, cost)
        return JSONResponse({"ok": False, "error": snap["error"], "refunded": cost > 0})
    await db_log_activity(uid, user.get("username") or "", f"inspect_{kind}", f"{len(snap.get('cars') or [])} cars", cost)
    cars = snap.get("cars") or []
    safe = [{k:v for k,v in c.items() if k not in ("vinyls_raw","window_raw","car_id_raw","instance_raw","style_fields")} for c in cars]
    return {"ok": True, "cars": safe, "count": len(safe), "supported": sum(1 for c in cars if c.get("transferable")), "cost": cost, "free": is_sub}

@app.post("/api/transfer/connect")
async def api_tcn(body: dict, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    st = body.get("source_type", "cpm1")
    if st == "cpm1": src = await open_cpm1_cloud_session(body["src_email"], body["src_password"])
    else: src = await open_cloud_vinyl_session(body["src_email"], body["src_password"])
    if src.get("error"): return {"ok": False, "error": f"SOURCE: {src['error']}"}
    tgt = await open_cloud_vinyl_session(body["tgt_email"], body["tgt_password"])
    if tgt.get("error"): return {"ok": False, "error": f"TARGET: {tgt['error']}"}
    def clean(cars):
        return [{k:v for k,v in c.items() if k not in ("vinyls_raw","window_raw","car_id_raw","instance_raw","style_fields")} for c in cars]
    _sessions[int(user["id"])] = {"src_cars_raw": src.get("cars") or [], "tgt_cars_raw": tgt.get("cars") or [], "tgt_email": body["tgt_email"], "tgt_password": body["tgt_password"], "source_type": st}
    return {"ok": True, "src_cars": clean(src.get("cars") or []), "tgt_cars": clean(tgt.get("cars") or [])}

@app.post("/api/transfer/execute")
async def api_tex(body: TransferPlanIn, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    sess = _sessions.get(uid)
    if not sess: raise HTTPException(400, "Connect first")
    if not body.plan: raise HTTPException(400, "Empty")
    is_sub = await db_is_subscribed(uid)
    cost = 0 if is_sub else (COST_CPM1_TO_CPM2 if body.source_type == "cpm1" else COST_CPM2_TO_CPM2)
    if cost > 0:
        cur = await db_get_coins(uid)
        if cur < cost: raise HTTPException(402, f"Need {cost} coins (you have {cur})")
    sm = {c["index"]: c for c in sess["src_cars_raw"]}
    tm = {c["index"]: c for c in sess["tgt_cars_raw"]}
    pairs = [(tm[e["target_index"]], sm[e["donor_index"]]) for e in body.plan if e["donor_index"] in sm and e["target_index"] in tm]
    result = {"sent": 0, "verified": 0, "total": len(pairs), "error": ""}
    out = await _save_and_verify_pairs(pairs, sess["tgt_email"], sess["tgt_password"], result)
    verified_ok = out.get("verified", 0) == out.get("sent", 0) and out.get("sent", 0) > 0
    if cost > 0 and verified_ok:
        ok = await db_deduct_coins(uid, cost)
        if ok:
            out["cost"] = cost
            out["charged"] = True
            log.info(f"💎 Charged {cost} coins to {uid} (vinyl success)")
        else:
            out["cost"] = 0
            out["charged"] = False
    else:
        out["cost"] = 0
        out["charged"] = False
        if cost > 0: log.info(f"⚠️ No charge to {uid} (vinyl failed)")
    out["free"] = is_sub
    await db_log_activity(uid, user.get("username") or "", f"vinyl_transfer_{body.source_type}", f"sent={out.get('sent',0)} verified={out.get('verified',0)} charged={out.get('charged',False)}", out.get("cost", 0))
    if not out.get("error"): _sessions.pop(uid, None)
    return {"ok": not out.get("error"), **out}

@app.post("/api/police")
async def api_police(body: UnlockIn, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    is_sub = await db_is_subscribed(uid)
    cost = 0 if is_sub else COST_POLICE
    if cost > 0:
        cur = await db_get_coins(uid)
        if cur < cost: raise HTTPException(402, f"Need {cost} coins (you have {cur})")
    result = await execute_api_unlock(body.email, body.password, body.car_index, mode="police")
    if cost > 0:
        if result.get("verified", 0) == 1:
            ok = await db_deduct_coins(uid, cost)
            if ok:
                result["cost"] = cost
                result["charged"] = True
                log.info(f"💎 Charged {cost} coins to {uid} (police success)")
            else:
                result["cost"] = 0
                result["charged"] = False
        else:
            result["cost"] = 0
            result["charged"] = False
            log.info(f"⚠️ No charge to {uid} (police failed — sent={result.get('sent',0)} verified={result.get('verified',0)})")
    else:
        result["cost"] = 0
        result["charged"] = False
    result["free"] = is_sub
    await db_log_activity(uid, user.get("username") or "", "police_unlock", f"car={body.car_index} sent={result.get('sent',0)} verified={result.get('verified',0)} charged={result.get('charged',False)}", result.get("cost", 0))
    return result

@app.post("/api/airsus")
async def api_airsus(body: UnlockIn, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    uid = int(user["id"])
    is_sub = await db_is_subscribed(uid)
    cost = 0 if is_sub else COST_AIRSUS
    if cost > 0:
        cur = await db_get_coins(uid)
        if cur < cost: raise HTTPException(402, f"Need {cost} coins (you have {cur})")
    result = await execute_api_unlock(body.email, body.password, body.car_index, mode="air")
    if cost > 0:
        if result.get("verified", 0) == 1:
            ok = await db_deduct_coins(uid, cost)
            if ok:
                result["cost"] = cost
                result["charged"] = True
                log.info(f"💎 Charged {cost} coins to {uid} (airsus success)")
            else:
                result["cost"] = 0
                result["charged"] = False
        else:
            result["cost"] = 0
            result["charged"] = False
            log.info(f"⚠️ No charge to {uid} (airsus failed — sent={result.get('sent',0)} verified={result.get('verified',0)})")
    else:
        result["cost"] = 0
        result["charged"] = False
    result["free"] = is_sub
    await db_log_activity(uid, user.get("username") or "", "airsus_unlock", f"car={body.car_index} sent={result.get('sent',0)} verified={result.get('verified',0)} charged={result.get('charged',False)}", result.get("cost", 0))
    return result

@app.post("/api/admin/custom-invoice")
async def api_custom_invoice(body: CustomInvoiceIn, x_init_data: str = Header(default="")):
    admin = await _get_current_user(x_init_data)
    if int(admin["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    if body.stars < 1 or body.stars > 100000: raise HTTPException(400, "Stars must be 1-100000")
    target_info = await db_get_user(body.user_id) or {}
    desc = body.description or f"Custom payment — {body.stars}⭐"
    pid = await db_create_pending_payment(body.user_id, target_info.get("username") or "", "custom", 0, body.stars, kind="custom", description=desc)
    payload = f"custom|{body.user_id}|0|{pid}"
    try:
        link = bot.create_invoice_link(title=f"Payment — {body.stars}⭐", description=desc[:255], payload=payload, provider_token="", currency="XTR", prices=[LabeledPrice(label=desc[:32] or "Payment", amount=body.stars)])
    except Exception as ex:
        return {"ok": False, "error": f"Invoice failed: {str(ex)[:150]}"}
    delivered = False
    try:
        bot.send_message(body.user_id, f"💳 <b>Payment Request</b>\n\n⭐ Amount: <b>{body.stars} Stars</b>\n📝 {desc}\n\n👇 Tap below to pay:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"Pay {body.stars}⭐", url=link)]]), disable_web_page_preview=True)
        delivered = True
    except Exception as ex:
        log.warning(f"send custom invoice: {ex}")
    return {"ok": True, "payment_id": pid, "invoice_link": link, "stars": body.stars, "delivered": delivered, "note": "" if delivered else "User must /start the bot first to receive DMs"}

@app.post("/api/admin/bonus-all")
async def api_bonus_all(body: BonusAllIn, x_init_data: str = Header(default="")):
    admin = await _get_current_user(x_init_data)
    if int(admin["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    if body.amount < 1 or body.amount > 10000: raise HTTPException(400, "Amount 1-10000")
    count = 0; failed = 0
    async with db_client() as c:
        if not c: raise HTTPException(503, "DB error")
        r = await c.execute("SELECT user_id FROM users")
        rows = list(r.rows) if (r and r.rows) else []
    for row in rows:
        uid = row[0]
        if not uid: continue
        try:
            await db_add_coins(int(uid), body.amount); count += 1
            try: bot.send_message(int(uid), f"🎁 <b>BONUS!</b>\n\n💎 +{body.amount} coins!\n🕒 {ts_ist()}")
            except: pass
            await asyncio.sleep(0.05)
        except: failed += 1
    await db_log_activity(0, "admin", "bonus_all", f"+{body.amount} to {count} users", 0)
    return {"ok": True, "credited": count, "failed": failed, "amount": body.amount}

@app.post("/api/admin/shop/update")
async def api_shop_update(body: UpdateShopIn, x_init_data: str = Header(default="")):
    admin = await _get_current_user(x_init_data)
    if int(admin["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    await db_update_shop_package(body.id, {"coins": body.coins, "bonus": body.bonus, "price": body.price})
    return {"ok": True}

@app.post("/api/admin/subscriptions/add")
async def api_asa(body: AddSubIn, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    return {"ok": True, "expiry": await db_add_subscription(body.user_id, body.days)}

@app.post("/api/admin/subscriptions/remove")
async def api_asr(body: dict, x_init_data: str = Header(default="")):
    user = await _get_current_user(x_init_data)
    if int(user["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    return {"ok": await db_remove_subscription(int(body["user_id"]))}

@app.post("/api/admin/coins/add")
async def api_aca(body: dict, x_init_data: str = Header(default="")):
    admin = await _get_current_user(x_init_data)
    if int(admin["id"]) != ADMIN_ID: raise HTTPException(403, "Admin")
    uid = int(body["user_id"]); amount = int(body["amount"])
    new = await db_add_coins(uid, amount)
    await db_log_activity(uid, "", "admin_coin_add", f"+{amount}", 0)
    try: bot.send_message(uid, f"{E_CHECK} +{amount} coins! Balance: {new}")
    except: pass
    return {"ok": True, "new_balance": new}

# ==========================================================
# MINI APP HTML
# ==========================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" />
<title>Mrx</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg-0:#0d0619;--card:rgba(255,255,255,.045);--card-br:rgba(168,85,247,.14);--txt:#f5f1ff;--txt-dim:#a89bc4;--purple:#a855f7;--grad:linear-gradient(135deg,#9333ea 0%,#c026d3 100%);--grad-soft:linear-gradient(135deg,rgba(147,51,234,.35),rgba(192,38,211,.25));--gold:linear-gradient(135deg,#f59e0b,#fbbf24)}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg-0);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Inter",system-ui,sans-serif;-webkit-font-smoothing:antialiased;overscroll-behavior:none}
body{background:radial-gradient(120% 60% at 50% 0%,#2a1050 0%,transparent 60%),radial-gradient(90% 60% at 100% 100%,#2a0f3f 0%,transparent 55%),linear-gradient(180deg,#150a26 0%,#0d0619 100%);min-height:100vh}
.app{max-width:520px;margin:0 auto;min-height:100vh;display:flex;flex-direction:column;padding-bottom:calc(96px + env(safe-area-inset-bottom))}
.topbar{display:grid;grid-template-columns:40px 1fr auto;align-items:center;gap:8px;padding:calc(14px + env(safe-area-inset-top)) 16px 12px;position:sticky;top:0;z-index:20;background:linear-gradient(180deg,rgba(13,6,25,.95) 60%,rgba(13,6,25,0));backdrop-filter:blur(14px)}
.icon-btn{width:36px;height:36px;border-radius:50%;background:transparent;border:none;color:var(--txt);font-size:26px;line-height:1;display:grid;place-items:center;cursor:pointer}
.topbar-title{text-align:center;font-size:16px;font-weight:600;color:#fff}
.topbar-title .powered{display:block;font-size:9.5px;font-weight:500;letter-spacing:.6px;color:#a855f7;margin-top:2px;text-transform:uppercase;opacity:.85}
.pill{display:inline-flex;align-items:center;gap:5px;height:28px;padding:0 10px;border-radius:14px;background:linear-gradient(135deg,rgba(245,158,11,.2),rgba(251,191,36,.15));border:1px solid rgba(245,158,11,.35);font-size:12.5px;font-weight:700;color:#fbbf24}
.pill.free{background:linear-gradient(135deg,rgba(34,197,94,.2),rgba(22,163,74,.15));border-color:rgba(34,197,94,.35);color:#22c55e}
.content{flex:1;padding:6px 14px 16px}
.tab-title{text-align:center;font-size:22px;font-weight:700;margin:8px 0 6px;color:#fff}
.tab-sub{text-align:center;font-size:12.5px;color:var(--txt-dim);margin:0 12px 18px;line-height:1.5}
.card{background:var(--card);border:1px solid var(--card-br);border-radius:18px;padding:14px;margin-bottom:10px}
.card.cta{background:linear-gradient(135deg,rgba(255,140,40,.18) 0%,rgba(168,85,247,.10) 100%),rgba(255,255,255,.03);border:1px solid rgba(255,140,40,.25);display:grid;grid-template-columns:48px 1fr auto;align-items:center;gap:12px}
.card-icon{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;font-size:22px;background:linear-gradient(135deg,#8b5cf6,#c026d3)}
.card-icon.blue{background:linear-gradient(135deg,#3b82f6,#6366f1)}
.card-icon.pink{background:linear-gradient(135deg,#ec4899,#f43f5e)}
.card-icon.police{background:linear-gradient(135deg,#3b82f6,#1e40af)}
.card-icon.air{background:linear-gradient(135deg,#f59e0b,#dc2626)}
.card-icon.gold{background:linear-gradient(135deg,#f59e0b,#fbbf24)}
.card-icon.green{background:linear-gradient(135deg,#22c55e,#16a34a)}
.card-name{font-size:14px;font-weight:600;color:#fff;margin-bottom:3px}
.card-meta{font-size:12px;color:var(--txt-dim)}
.row{display:grid;grid-template-columns:40px 1fr auto;align-items:center;gap:12px;padding:12px 14px;margin-bottom:10px;background:var(--card);border:1px solid var(--card-br);border-radius:16px;cursor:pointer}
.row-ico{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-size:18px;background:rgba(255,255,255,.06)}
.row-ico.blue{background:linear-gradient(135deg,#3b82f6,#06b6d4)}
.row-ico.purple{background:linear-gradient(135deg,#8b5cf6,#c026d3)}
.row-ico.police{background:linear-gradient(135deg,#3b82f6,#1e40af)}
.row-ico.air{background:linear-gradient(135deg,#f59e0b,#dc2626)}
.row-ico.gold{background:linear-gradient(135deg,#f59e0b,#fbbf24)}
.row-ico.green{background:linear-gradient(135deg,#22c55e,#16a34a)}
.row-name{font-size:13.5px;font-weight:600;color:#fff}
.row-sub{font-size:11.5px;color:var(--txt-dim);margin-top:3px}
.row-arrow{color:#7c6b9c;font-size:20px;width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.06);display:grid;place-items:center}
.btn{border:none;cursor:pointer;font-family:inherit;font-weight:600;border-radius:12px;transition:transform .1s}
.btn:active{transform:scale(.96)}
.btn-primary{background:var(--grad);color:#fff;padding:10px 18px;font-size:13px;box-shadow:0 6px 20px rgba(168,85,247,.35)}
.btn-block{width:100%;padding:14px;font-size:14.5px;border-radius:14px}
.btn-ghost{background:rgba(255,255,255,.06);color:#fff;padding:10px 16px;font-size:13px;border:1px solid rgba(255,255,255,.08)}
.btn-gold{background:var(--gold);color:#000;padding:10px 18px;font-size:13px;box-shadow:0 6px 20px rgba(245,158,11,.35)}
.btn-danger{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3);padding:6px 10px;font-size:12px;border-radius:8px;cursor:pointer}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.stat-box{background:var(--card);border:1px solid var(--card-br);border-radius:16px;padding:16px 12px;text-align:center}
.stat-box .big{font-size:22px;font-weight:800;color:#fff}
.stat-box .lbl{font-size:11.5px;color:var(--txt-dim);margin-top:6px}
.bottom-nav{position:fixed;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(4,1fr);padding:8px 8px calc(8px + env(safe-area-inset-bottom));background:linear-gradient(180deg,rgba(13,6,25,.4),#0d0619);backdrop-filter:blur(20px);z-index:30;max-width:520px;margin:auto;border-top:1px solid rgba(255,255,255,.04)}
.nav-item{background:none;border:none;color:var(--txt-dim);display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 4px;cursor:pointer;font-family:inherit}
.nav-item svg{width:20px;height:20px}
.nav-label{font-size:10.5px;font-weight:500}
.nav-item.active{color:#fff}
.nav-item.active .nav-ico{background:var(--grad);box-shadow:0 4px 14px rgba(168,85,247,.45);width:34px;height:34px;margin-top:-6px;margin-bottom:-4px;border-radius:50%;display:grid;place-items:center}
.nav-ico{display:grid;place-items:center}
.form-group{margin-bottom:14px}
.form-label{display:block;font-size:12px;font-weight:600;color:var(--txt-dim);margin-bottom:8px;text-transform:uppercase}
.form-input{width:100%;padding:14px 16px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);border-radius:14px;color:#fff;font-size:14px;font-family:inherit;outline:none}
.form-input:focus{border-color:var(--purple);background:rgba(168,85,247,.06)}
textarea.form-input{resize:vertical;font-family:inherit}
.loader{display:flex;align-items:center;justify-content:center;padding:40px 0;color:var(--txt-dim);font-size:13px;gap:10px}
.spinner{width:18px;height:18px;border-radius:50%;border:2px solid rgba(168,85,247,.25);border-top-color:var(--purple);animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.plan-item{display:grid;grid-template-columns:24px 1fr;gap:12px;padding:12px 14px;background:var(--card);border:1px solid var(--card-br);border-radius:14px;margin-bottom:8px}
.plan-num{width:24px;height:24px;border-radius:50%;background:var(--grad);color:#fff;font-size:12px;font-weight:700;display:grid;place-items:center}
.car-grid{display:grid;grid-template-columns:1fr;gap:8px}
.car-item{display:grid;grid-template-columns:36px 1fr auto;align-items:center;gap:10px;padding:10px 12px;background:var(--card);border:1px solid var(--card-br);border-radius:14px;cursor:pointer}
.car-item.disabled{opacity:.45}
.car-badge{width:36px;height:36px;border-radius:10px;background:var(--grad-soft);display:grid;place-items:center;font-weight:700;font-size:12px;color:#fff}
.car-name{font-size:13.5px;font-weight:600;color:#fff}
.car-meta{font-size:11.5px;color:var(--txt-dim);margin-top:2px}
.car-meta span{margin-right:8px}
.pager{display:flex;justify-content:space-between;gap:10px;margin-top:12px}
.toast{position:fixed;left:50%;bottom:calc(100px + env(safe-area-inset-bottom));transform:translateX(-50%) translateY(20px);background:rgba(30,15,55,.96);border:1px solid rgba(168,85,247,.35);color:#fff;font-size:13px;padding:10px 18px;border-radius:14px;opacity:0;pointer-events:none;transition:.25s;z-index:100;max-width:90vw;text-align:center}
.toast.on{opacity:1;transform:translateX(-50%)}
.info-box{background:rgba(239,68,68,.10);border:1px solid rgba(239,68,68,.35);color:#fecaca;font-size:12.5px;padding:12px 14px;border-radius:12px;margin:10px 0;word-break:break-word}
.info-box.ok{background:rgba(34,197,94,.10);border-color:rgba(34,197,94,.35);color:#bbf7d0}
.sub-row{display:flex;justify-content:space-between;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px;gap:8px}
.sub-row:last-child{border-bottom:none}
.sub-row code{color:#c084fc;font-size:12.5px;background:rgba(168,85,247,.08);padding:3px 8px;border-radius:6px;flex:1}
.sub-row .exp{color:var(--txt-dim);font-size:12px;flex-shrink:0}
.powered-footer{text-align:center;font-size:10.5px;color:#7c6b9c;letter-spacing:.4px;padding:14px 0 8px;text-transform:uppercase}
.powered-footer b{color:var(--purple)}
.pkg{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;background:var(--card);border:1px solid var(--card-br);border-radius:16px;padding:14px;margin-bottom:10px}
.pkg.hot{border-color:rgba(245,158,11,.5);background:linear-gradient(135deg,rgba(245,158,11,.10),rgba(168,85,247,.05)),rgba(255,255,255,.03)}
.pkg-coins{font-size:20px;font-weight:800;color:#fbbf24}
.pkg-label{font-size:12px;color:var(--txt-dim);margin-top:2px}
.pkg-bonus{display:inline-block;background:linear-gradient(135deg,#f59e0b,#fbbf24);color:#000;font-size:10px;font-weight:800;padding:2px 8px;border-radius:8px;margin-left:6px;letter-spacing:.3px}
.pkg-price{font-size:16px;font-weight:700;color:#fff;text-align:right}
.pkg-price small{display:block;font-size:10px;color:var(--txt-dim);font-weight:500}
.act-row{padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.05);font-size:12.5px}
.act-row:last-child{border-bottom:none}
.act-user{color:#c084fc;font-weight:600}
.act-action{color:#fff;font-weight:600;margin-top:2px}
.act-detail{color:var(--txt-dim);font-size:11.5px;margin-top:2px;word-break:break-word}
.act-time{color:#7c6b9c;font-size:10.5px;margin-top:3px}
.status-chip{display:inline-block;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:700}
.status-completed{background:rgba(34,197,94,.15);color:#22c55e;border:1px solid rgba(34,197,94,.3)}
.feature-chip{display:inline-block;padding:4px 10px;border-radius:8px;font-size:11.5px;font-weight:700;margin:3px;background:rgba(168,85,247,.15);color:#c084fc;border:1px solid rgba(168,85,247,.3)}
.free-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:10.5px;font-weight:700;background:rgba(34,197,94,.15);color:#22c55e;border:1px solid rgba(34,197,94,.3);margin-left:6px}
.cost-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:10.5px;font-weight:700;background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(245,158,11,.3);margin-left:6px}
.wallet-hero{background:linear-gradient(135deg,rgba(245,158,11,.20),rgba(168,85,247,.15));border:1px solid rgba(245,158,11,.35);border-radius:20px;padding:22px 18px;text-align:center;margin-bottom:14px}
.wallet-hero .wh-label{font-size:11.5px;color:#fbbf24;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.wallet-hero .wh-val{font-size:38px;font-weight:900;color:#fff;margin-top:6px;line-height:1}
.wallet-hero .wh-sub{font-size:12.5px;color:var(--txt-dim);margin-top:8px}
.holder-row{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.holder-row:last-child{border-bottom:none}
.holder-rank{width:28px;height:28px;border-radius:50%;background:var(--grad-soft);display:grid;place-items:center;font-weight:700;font-size:12px;color:#fff}
.holder-name{color:#fff;font-weight:600}
.holder-id{color:var(--txt-dim);font-size:11px;margin-top:2px}
.holder-coins{color:#fbbf24;font-weight:800;font-size:14px;white-space:nowrap}
.shop-mgr-row{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.shop-mgr-row input{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);color:#fff;border-radius:8px;padding:6px;font-size:12px;width:100%;text-align:center}
.shop-mgr-btn{background:var(--grad);border:none;color:#fff;border-radius:8px;padding:6px 10px;font-size:11px;font-weight:700;cursor:pointer}
.search-box{display:flex;gap:8px;margin-bottom:12px}
.search-box input{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);color:#fff;border-radius:12px;padding:12px;font-size:14px}
.search-box button{background:var(--grad);border:none;color:#fff;border-radius:12px;padding:0 16px;font-weight:700;cursor:pointer}
</style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <button class="icon-btn" id="backBtn">‹</button>
    <div class="topbar-title" id="topTitle">Mrx<span class="powered">Powered by Mrx</span></div>
    <div><div class="pill" id="coinBalance">💎 0</div></div>
  </header>
  <main class="content" id="content"></main>
  <div class="powered-footer">⚡ Powered by <b>Mrx</b></div>
  <nav class="bottom-nav">
    <button class="nav-item" data-tab="transfer"><span class="nav-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h12l-3-3M20 17H8l3 3" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="nav-label">Transfer</span></button>
    <button class="nav-item" data-tab="shop"><span class="nav-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3h2l2 12h12l3-9H6"/><circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/></svg></span><span class="nav-label">Shop</span></button>
    <button class="nav-item active" data-tab="subs"><span class="nav-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5" stroke-linecap="round"/></svg></span><span class="nav-label">Subs</span></button>
    <button class="nav-item" data-tab="wallet"><span class="nav-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10h18" stroke-linecap="round"/></svg></span><span class="nav-label">Wallet</span></button>
  </nav>
  <div class="toast" id="toast"></div>
</div>
<script>
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor?.("#0d0619"); tg.setBackgroundColor?.("#0d0619"); }
const haptic = (t="light")=>{try{if(!tg?.HapticFeedback)return;if(["success","error","warning"].includes(t))tg.HapticFeedback.notificationOccurred(t);else tg.HapticFeedback.impactOccurred(t);}catch(_){}};
const INIT_DATA = tg?.initData || "";
async function api(path,{method="GET",body=null}={}){
  const o={method,headers:{"x-init-data":INIT_DATA,...(body?{"Content-Type":"application/json"}:{})}};
  if(body)o.body=JSON.stringify(body);
  const r=await fetch(path,o);
  if(!r.ok){let m="HTTP "+r.status;try{const j=await r.json();m=j.detail||j.error||m;}catch(_){}throw new Error(m);}
  return r.json();
}
async function refreshMe(){
  try{const me=await api("/api/me");state.me=me;updateHeader();return me;}catch(e){return null;}
}
let toastT;
function toast(m,t="info"){const el=document.getElementById("toast");el.textContent=m;el.classList.add("on");haptic(t==="error"?"error":t==="success"?"success":"light");clearTimeout(toastT);toastT=setTimeout(()=>el.classList.remove("on"),2200);}
const COSTS={cpm1:15,cpm2:15,police:10,air:10,inspect:10};
const state={tab:"subs",me:null,srcCars:[],tgtCars:[],plan:[],tempDonorIndex:null,sourceType:"cpm1",srcEmail:"",srcPassword:"",tgtEmail:"",tgtPassword:"",unlockMode:"police",unlockEmail:"",unlockPass:"",unlockCars:[],unlockPage:0,adminLogsUser:""};
const $=(s)=>document.querySelector(s);
const content=$("#content");
const topTitle=$("#topTitle");
const backBtn=$("#backBtn");
function updateHeader(){if(!state.me)return;const el=$("#coinBalance");if(state.me.is_subscriber){el.className="pill free";el.textContent="👑 FREE";}else{el.className="pill";el.textContent="💎 "+(state.me.coins ?? 0);}}
function setActiveNav(tab){document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));}
document.querySelectorAll(".nav-item").forEach(btn=>{btn.addEventListener("click",()=>{haptic("light");goTab(btn.dataset.tab);});});
backBtn.addEventListener("click",()=>{haptic("light");if(state.tab==="unlock-flow")goTab("transfer");else if(state.tab==="admin")goTab("subs");else if(["transfer","inspect","flow"].includes(state.tab))goTab("subs");else if(tg?.close)tg.close();else history.back();});
function goTab(tab){state.tab=tab;setActiveNav(tab);if(tab==="transfer")renderTransfer();else if(tab==="subs")renderSubs();else if(tab==="wallet")renderWallet();else if(tab==="shop")renderShop();else if(tab==="flow")renderTransferFlow();else if(tab==="unlock-flow")renderUnlockFlow(state.unlockMode||"police");else if(tab==="admin")renderAdmin();}
function costBadge(cost){if(state.me?.is_subscriber) return `<span class="free-badge">FREE</span>`;return `<span class="cost-badge">${cost} coins</span>`;}

function renderTransfer(){
  topTitle.innerHTML='Transfer<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="hidden";
  const free=state.me?.is_subscriber;
  content.innerHTML=`
    <h2 class="tab-title">Mrx Tools</h2>
    <p class="tab-sub">${free ? "👑 Subscriber — All features FREE" : "Charge only on success"}</p>
    <div class="card cta" id="startTransfer"><div class="card-icon">🎨</div><div><div class="card-name">Start Vinyl Transfer ${costBadge(15)}</div><div class="card-meta">CPM1→CPM2 or CPM2→CPM2</div></div><button class="btn btn-primary">Start</button></div>
    <div class="row" id="policeCard"><div class="row-ico police">🚓</div><div><div class="row-name">Police Unlock ${costBadge(10)}</div><div class="row-sub">Enable police lights + siren</div></div><div class="row-arrow">›</div></div>
    <div class="row" id="airsusCard"><div class="row-ico air">🚗</div><div><div class="row-name">Air Suspension Unlock ${costBadge(10)}</div><div class="row-sub">Enable air suspension</div></div><div class="row-arrow">›</div></div>
    <div class="row" id="inspectCpm1"><div class="row-ico blue">🔍</div><div><div class="row-name">Inspect CPM1 ${costBadge(10)}</div><div class="row-sub">View cars &amp; vinyls</div></div><div class="row-arrow">›</div></div>
    <div class="row" id="inspectCpm2"><div class="row-ico purple">🔍</div><div><div class="row-name">Inspect CPM2 ${costBadge(10)}</div><div class="row-sub">View cars &amp; vinyls</div></div><div class="row-arrow">›</div></div>`;
  $("#startTransfer").onclick=()=>{haptic("medium");goTab("flow");};
  $("#policeCard").onclick=()=>{haptic("light");renderUnlockFlow("police");};
  $("#airsusCard").onclick=()=>{haptic("light");renderUnlockFlow("air");};
  $("#inspectCpm1").onclick=()=>{haptic("light");renderInspect("cpm1");};
  $("#inspectCpm2").onclick=()=>{haptic("light");renderInspect("cpm2");};
}
async function renderShop(){
  topTitle.innerHTML='Coin Shop<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="hidden";
  content.innerHTML=`<div class="loader"><div class="spinner"></div>Loading...</div>`;
  try{
    const r=await api("/api/coin-shop");
    const pkgs=r.packages||[];
    const rows=pkgs.map(p=>{
      const isHot=p.bonus>0;
      return `<div class="pkg ${isHot?'hot':''}"><div><div class="pkg-coins">💎 ${p.total} coins ${p.bonus>0?`<span class="pkg-bonus">+${p.bonus} BONUS</span>`:''}</div><div class="pkg-label">${p.coins} base${p.bonus>0?` + ${p.bonus} bonus`:''}</div></div><div><div class="pkg-price">⭐ ${p.price}<small>Telegram Stars</small></div><button class="btn btn-gold" style="margin-top:6px;padding:8px 14px;font-size:12px" data-pkg="${p.id}">Pay ⭐${p.price}</button></div></div>`;
    }).join("");
    content.innerHTML=`<h2 class="tab-title">💎 Coin Shop</h2><p class="tab-sub">Pay with Telegram Stars — coins auto-credited</p>${rows}`;
    content.querySelectorAll("[data-pkg]").forEach(btn=>{
      btn.onclick=async()=>{
        haptic("medium");const pid=btn.dataset.pkg;const pkg=pkgs.find(p=>p.id===pid);
        if(!pkg)return;btn.disabled=true;btn.textContent="...";
        try{
          const r2=await api("/api/coin-shop/buy",{method:"POST",body:{package_id:pid}});
          if(!r2.ok){btn.disabled=false;btn.textContent=`Pay ⭐${pkg.price}`;toast(r2.error||"Failed","error");return;}
          if(r2.invoice_link && tg?.openInvoice){
            tg.openInvoice(r2.invoice_link,(status)=>{
              if(status==="paid"){haptic("success");toast(`✅ +${pkg.total} coins!`,"success");setTimeout(()=>{renderShop();refreshMe();},1500);}
              else{btn.disabled=false;btn.textContent=`Pay ⭐${pkg.price}`;}
            });
          }else if(r2.invoice_link){
            if(tg?.openTelegramLink) tg.openTelegramLink(r2.invoice_link); else window.open(r2.invoice_link,"_blank");
            btn.disabled=false;btn.textContent=`Pay ⭐${pkg.price}`;
          }else{btn.disabled=false;btn.textContent=`Pay ⭐${pkg.price}`;toast("Payment unavailable","error");}
        }catch(e){btn.disabled=false;btn.textContent=`Pay ⭐${pkg.price}`;toast(e.message,"error");}
      };
    });
  }catch(e){content.innerHTML=`<div class="info-box">${e.message}</div>`;}
}
async function renderSubs(){
  topTitle.innerHTML='Mrx<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="hidden";
  content.innerHTML=`<div class="loader"><div class="spinner"></div>Loading...</div>`;
  try{
    const r=await api("/api/subscriptions");
    const subs=r.subscriptions||[];
    const rows=subs.map(s=>`<div class="sub-row" data-uid="${s.user_id}"><code>${s.user_id}</code><span class="exp">${s.expiry}</span>${r.is_admin?`<button class="btn-danger" data-uid="${s.user_id}">✕</button>`:""}</div>`).join("");
    content.innerHTML=`<h2 class="tab-title">Active Subscriptions</h2><p class="tab-sub">${r.is_admin?`All users — ${subs.length} total`:`Your subscription`}</p><div class="card" style="padding:10px 14px">${rows||'<div style="text-align:center;color:#a89bc4;padding:20px 0;font-size:13px">No active subscriptions</div>'}</div>${r.is_admin?`<div class="row" id="adminPanelBtn" style="margin-top:14px"><div class="row-ico gold">👑</div><div><div class="row-name">Admin Panel</div><div class="row-sub">Payments • Users • Bonus • Shop • Broadcast</div></div><div class="row-arrow">›</div></div><div class="form-label" style="margin-top:18px">Add / Extend Subscription</div><div class="card" style="padding:14px"><div class="form-group"><label class="form-label">User ID</label><input class="form-input" id="subUid" inputmode="numeric" /></div><div class="form-group"><label class="form-label">Days</label><input class="form-input" id="subDays" placeholder="30" inputmode="numeric" /></div><button class="btn btn-primary btn-block" id="addSubBtn">➕ Add / Extend</button></div>`:""}`;
    $("#adminPanelBtn")?.addEventListener("click",()=>{haptic("medium");goTab("admin");});
    $("#addSubBtn")?.addEventListener("click",async()=>{
      haptic("medium");
      const uid=parseInt($("#subUid").value.trim(),10);const days=parseInt($("#subDays").value.trim(),10);
      if(!uid||!days)return toast("Enter valid values","error");
      try{const r2=await api("/api/admin/subscriptions/add",{method:"POST",body:{user_id:uid,days}});toast("Added ✓ "+r2.expiry,"success");renderSubs();}catch(e){toast(e.message,"error");}
    });
    content.querySelectorAll(".btn-danger").forEach(btn=>{
      btn.onclick=async(e)=>{
        e.stopPropagation();haptic("warning");
        const uid=btn.dataset.uid;
        if(!confirm("Remove "+uid+"?"))return;
        try{const r2=await api("/api/admin/subscriptions/remove",{method:"POST",body:{user_id:parseInt(uid,10)}});if(r2.ok){toast("Removed","success");renderSubs();}}catch(err){toast(err.message,"error");}
      };
    });
  }catch(e){content.innerHTML=`<div class="info-box">${e.message}</div>`;}
}
async function renderAdmin(){
  topTitle.innerHTML='Admin Panel<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="visible";
  content.innerHTML=`<div class="loader"><div class="spinner"></div>Loading...</div>`;
  try{
    const [payRes,usersRes,actRes,holdRes,shopRes]=await Promise.all([
      api("/api/admin/payments"),api("/api/admin/users"),
      api("/api/activities"),api("/api/admin/coin-holders"),api("/api/coin-shop")
    ]);
    const payments=payRes.payments||[];const users=usersRes.users||[];const activities=actRes.activities||[];const holders=holdRes.users||[];const shopPkgs=shopRes.packages||[];
    const completedPay=payments.filter(p=>p.status==="completed");
    const totalStars=completedPay.reduce((s,p)=>s+(p.price||0),0);
    const shopRows=shopPkgs.map(p=>`<div class="shop-mgr-row" data-pkgid="${p.id}"><input type="number" value="${p.coins}" class="sm-coins" /><input type="number" value="${p.bonus}" class="sm-bonus" /><input type="number" value="${p.price}" class="sm-price" /><button class="shop-mgr-btn" data-save="${p.id}">Save</button></div>`).join("");
    const userRows=users.slice(0,80).map(u=>`<div class="act-row"><div class="act-user">@${u.username||u.first_name||"?"} (${u.user_id})${u.is_subscriber?' <span class="status-chip status-completed">SUB</span>':''}</div><div class="act-detail">💎 ${u.coins} coins • 📊 ${u.activities} ops • ✅ ${u.completed_payments} pay</div>${u.expiry?`<div class="act-detail">Expires: ${u.expiry}</div>`:''}<div class="act-time">🕒 ${u.updated_at_ist||""}</div></div>`).join("")||'<div style="text-align:center;color:#a89bc4;padding:20px 0">No users</div>';
    const holderRows=holders.slice(0,60).map((h,i)=>`<div class="holder-row"><div class="holder-rank">${i+1}</div><div><div class="holder-name">@${h.username||h.first_name||"User"}</div><div class="holder-id">${h.user_id}</div></div><div class="holder-coins">💎 ${h.coins}</div></div>`).join("")||'<div style="text-align:center;color:#a89bc4;padding:20px 0">No coin holders</div>';
    const actRows=activities.slice(0,60).map(a=>`<div class="act-row"><div class="act-user">@${a.username||"?"} (${a.user_id})</div><div class="act-action">${a.action}</div>${a.details?`<div class="act-detail">${a.details}</div>`:""}${a.cost?`<div class="act-detail">💰 ${a.cost} coins</div>`:""}<div class="act-time">🕒 ${a.created_at_ist||""}</div></div>`).join("")||'<div style="text-align:center;color:#a89bc4;padding:20px 0">No activities</div>';
    const payRows=payments.slice(0,60).map(p=>`<div class="act-row"><div class="act-user">@${p.username||"?"} (${p.user_id})</div><div class="act-action">💎 ${p.coins} — ⭐ ${p.price} <span class="status-chip ${p.status==='completed'?'status-completed':''}">${p.status}</span></div><div class="act-detail">ID: ${p.payment_id}</div><div class="act-time">🕒 ${p.created_at_ist||""}</div></div>`).join("")||'<div style="text-align:center;color:#a89bc4;padding:20px 0">No payments</div>';
    content.innerHTML=`<h2 class="tab-title">👑 Admin Panel</h2><p class="tab-sub">All times in IST</p><div class="stat-grid"><div class="stat-box"><div class="big">${completedPay.length}</div><div class="lbl">Completed</div></div><div class="stat-box"><div class="big">⭐ ${totalStars}</div><div class="lbl">Total Stars</div></div></div>
    <h3 style="color:#fbbf24;font-size:15px;margin:18px 0 8px">🛒 Shop Manager</h3><div class="card" style="padding:14px">${shopRows}</div>
    <h3 style="color:#22c55e;font-size:15px;margin:18px 0 8px">📜 User Logs & Features</h3><div class="card" style="padding:14px"><div class="search-box"><input type="number" id="logSearchId" placeholder="User ID..." /><button id="logSearchBtn">Search</button></div><div id="logResults"><div style="text-align:center;color:#a89bc4;padding:20px 0;font-size:13px">Enter User ID</div></div></div>
    <h3 style="color:#fbbf24;font-size:15px;margin:18px 0 8px">🎁 Bonus to ALL</h3><div class="card" style="padding:14px"><input class="form-input" id="bonusAmt" placeholder="Coins" inputmode="numeric" style="margin-bottom:10px" /><button class="btn btn-gold btn-block" id="bonusBtn">🎁 Give Bonus</button></div>
    <h3 style="color:#22c55e;font-size:15px;margin:18px 0 8px">💳 Custom Invoice</h3><div class="card" style="padding:14px"><input class="form-input" id="ciUid" placeholder="User ID" inputmode="numeric" style="margin-bottom:8px" /><input class="form-input" id="ciStars" placeholder="Stars" inputmode="numeric" style="margin-bottom:8px" /><input class="form-input" id="ciDesc" placeholder="Description" style="margin-bottom:10px" /><button class="btn btn-primary btn-block" id="ciBtn">📩 Send</button></div>
    <h3 style="color:#ec4899;font-size:15px;margin:18px 0 8px">📢 Broadcast</h3><div class="card" style="padding:14px"><textarea class="form-input" id="bcText" rows="4" placeholder="Message text..." style="margin-bottom:10px"></textarea><input class="form-input" id="bcPhoto" placeholder="Image URL (optional)" style="margin-bottom:10px" /><button class="btn btn-block" id="bcBtn" style="background:linear-gradient(135deg,#ec4899,#f43f5e);color:#fff">📢 Send to ALL Users</button></div>
    <h3 style="color:#fbbf24;font-size:15px;margin:18px 0 8px">💎 Coin Holders (${holders.length})</h3><div class="card" style="padding:6px 14px">${holderRows}</div>
    <h3 style="color:#a855f7;font-size:15px;margin:18px 0 8px">👥 Users (${users.length})</h3><div class="card" style="padding:6px 14px">${userRows}</div>
    <h3 style="color:#a855f7;font-size:15px;margin:18px 0 8px">📊 Recent Activities</h3><div class="card" style="padding:6px 14px">${actRows}</div>
    <h3 style="color:#fbbf24;font-size:15px;margin:18px 0 8px">💳 All Payments</h3><div class="card" style="padding:6px 14px">${payRows}</div>`;
    content.querySelectorAll("[data-save]").forEach(btn=>{
      btn.onclick=async()=>{
        const pkgId=btn.dataset.save;const row=btn.closest(".shop-mgr-row");
        const coins=parseInt(row.querySelector(".sm-coins").value);const bonus=parseInt(row.querySelector(".sm-bonus").value);const price=parseInt(row.querySelector(".sm-price").value);
        if(isNaN(coins)||isNaN(bonus)||isNaN(price)) return toast("Invalid","error");
        btn.disabled=true;btn.textContent="...";
        try{await api("/api/admin/shop/update",{method:"POST",body:{id:pkgId,coins,bonus,price}});toast("✅ Updated!","success");}catch(e){toast(e.message,"error");}
        btn.disabled=false;btn.textContent="Save";
      };
    });
    $("#logSearchBtn").onclick=async()=>{
      const uid=parseInt($("#logSearchId").value.trim(),10);
      if(!uid) return toast("Enter ID","error");
      $("#logResults").innerHTML=`<div class="loader"><div class="spinner"></div>Loading...</div>`;
      try{
        const [logsRes,featRes]=await Promise.all([api(`/api/activities?user_id=${uid}`),api(`/api/admin/user-features?user_id=${uid}`)]);
        const logs=logsRes.activities||[];const features=featRes.features||{};
        let featHtml="";
        if(Object.keys(features).length){
          const keys=Object.keys(features);
          featHtml=`<div style="margin-bottom:12px"><div style="font-size:12px;color:var(--txt-dim);margin-bottom:6px;text-transform:uppercase;font-weight:600">Feature Usage</div><div>${keys.map(k=>`<span class="feature-chip">${k}: ${features[k]}</span>`).join("")}</div></div>`;
        }
        let logsHtml="";
        if(logs.length===0){logsHtml=`<div style="text-align:center;color:#a89bc4;padding:20px 0">No logs</div>`;}
        else{logsHtml=logs.map(a=>`<div class="act-row"><div class="act-action">${a.action}</div>${a.details?`<div class="act-detail">${a.details}</div>`:""}${a.cost?`<div class="act-detail">💰 ${a.cost}</div>`:""}<div class="act-time">🕒 ${a.created_at_ist||""}</div></div>`).join("");}
        $("#logResults").innerHTML=featHtml+logsHtml;
      }catch(e){$("#logResults").innerHTML=`<div class="info-box">${e.message}</div>`;}
    };
    $("#bonusBtn").onclick=async()=>{
      haptic("heavy");
      const amt=parseInt($("#bonusAmt").value.trim(),10);
      if(!amt||amt<1)return toast("Enter amount","error");
      if(!confirm(`Give +${amt} coins to ALL?`))return;
      $("#bonusBtn").disabled=true;$("#bonusBtn").textContent="Sending...";
      try{const r=await api("/api/admin/bonus-all",{method:"POST",body:{amount:amt}});toast(`✅ +${amt} to ${r.credited} users!`,"success");setTimeout(()=>renderAdmin(),1200);}
      catch(e){$("#bonusBtn").disabled=false;$("#bonusBtn").textContent="🎁 Give Bonus";toast(e.message,"error");}
    };
    $("#ciBtn").onclick=async()=>{
      haptic("heavy");
      const uid=parseInt($("#ciUid").value.trim(),10);const stars=parseInt($("#ciStars").value.trim(),10);const desc=$("#ciDesc").value.trim();
      if(!uid||!stars)return toast("Fill ID + Stars","error");
      $("#ciBtn").disabled=true;$("#ciBtn").textContent="Sending...";
      try{
        const r=await api("/api/admin/custom-invoice",{method:"POST",body:{user_id:uid,stars:stars,description:desc}});
        if(!r.ok){toast(r.error||"Failed","error");}
        else{toast(`✅ Sent to ${uid}`,"success");}
      }catch(e){toast(e.message,"error");}
      $("#ciBtn").disabled=false;$("#ciBtn").textContent="📩 Send";
    };
    $("#bcBtn").onclick=async()=>{
      haptic("heavy");
      const text=$("#bcText").value.trim();const photo=$("#bcPhoto").value.trim();
      if(!text&&!photo)return toast("Enter text or image","error");
      if(!confirm("Broadcast to ALL users?"))return;
      $("#bcBtn").disabled=true;$("#bcBtn").textContent="Sending...";
      try{
        const r=await api("/api/admin/broadcast",{method:"POST",body:{text:text,photo_url:photo}});
        toast(`✅ Broadcasting to ${r.total} users...`,"success");
      }catch(e){toast(e.message,"error");}
      setTimeout(()=>{$("#bcBtn").disabled=false;$("#bcBtn").textContent="📢 Send to ALL Users";},3000);
    };
  }catch(e){content.innerHTML=`<div class="info-box">${e.message}</div>`;}
}
async function renderWallet(){
  topTitle.innerHTML='Mrx<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="hidden";
  content.innerHTML=`<div class="loader"><div class="spinner"></div>Loading...</div>`;
  try{
    const me=await refreshMe();
    const sub=me.subscription;const coins=me.coins ?? 0;const isSub=me.is_subscriber;
    const hero=isSub?`<div class="wallet-hero" style="background:linear-gradient(135deg,rgba(34,197,94,.20),rgba(168,85,247,.15));border-color:rgba(34,197,94,.35)"><div class="wh-label" style="color:#22c55e">👑 SUBSCRIBER</div><div class="wh-val">FREE</div><div class="wh-sub">All features unlocked</div></div>`:`<div class="wallet-hero"><div class="wh-label">💎 YOUR COIN BALANCE</div><div class="wh-val">${coins}</div><div class="wh-sub">Tap Shop to buy more</div></div>`;
    content.innerHTML=`<h2 class="tab-title">Wallet</h2>${hero}<div class="card cta"><div class="card-icon ${sub?"green":"pink"}">📅</div><div><div class="card-name">${sub?"Active Subscription":"No Subscription"}</div><div class="card-meta">${sub?"Expires: "+sub.expiry:"Contact @PRO_MR_X"}</div></div><span style="color:${sub?"#22c55e":"#ef4444"};font-size:20px">${sub?"✓":"!"}</span></div>${!isSub?`<button class="btn btn-gold btn-block" id="goShopBtn" style="margin-bottom:10px">💎 Buy Coins</button>`:""}<div class="row" id="supportRow"><div class="row-ico blue">💬</div><div><div class="row-name">Support</div><div class="row-sub">@PRO_MR_X</div></div><div class="row-arrow">›</div></div><div class="row" id="refreshRow"><div class="row-ico purple">↻</div><div><div class="row-name">Refresh</div><div class="row-sub">${me.server_time_ist||""}</div></div><div class="row-arrow">›</div></div><div id="refSection"></div>`;
    $("#goShopBtn")?.addEventListener("click",()=>{haptic("medium");goTab("shop");});
    $("#supportRow").onclick=()=>{haptic("light");if(tg?.openTelegramLink)tg.openTelegramLink("https://t.me/PRO_MR_X");};
    $("#refreshRow").onclick=()=>{haptic("light");renderWallet();};
    (async()=>{
      try{
        const ref=await api("/api/referral/stats");
        if(!ref.ok)return;
        const lb=await api("/api/referral/leaderboard");
        const leaders=(lb.leaders||[]).slice(0,5).map((l,i)=>`<div class="holder-row"><div class="holder-rank">${i+1}</div><div><div class="holder-name">@${l.username||l.first_name||"User"}</div><div class="holder-id">${l.user_id}</div></div><div class="holder-coins">${l.count} refs</div></div>`).join("")||'<div style="text-align:center;color:#a89bc4;padding:14px 0;font-size:12.5px">Be the first!</div>';
        const refHtml=`<h3 style="color:#22c55e;font-size:15px;margin:20px 0 8px">🎁 Referral Program</h3>
          <div class="card" style="padding:14px">
            <div style="font-size:12.5px;color:var(--txt-dim);margin-bottom:10px;line-height:1.6">Invite friends and earn <b style="color:#fbbf24">+${ref.reward_per_ref} coins</b> for each. They also get <b style="color:#fbbf24">+${ref.reward_per_ref}</b>!</div>
            <div class="form-group"><label class="form-label">Your Referral Link</label><input class="form-input" id="refLink" value="${ref.referral_link}" readonly style="font-size:11.5px" /></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px"><button class="btn btn-primary" id="refCopy">📋 Copy</button><button class="btn btn-gold" id="refShare">📤 Share</button></div>
            <div class="stat-grid" style="margin-bottom:0"><div class="stat-box"><div class="big">${ref.count}</div><div class="lbl">Total Referrals</div></div><div class="stat-box"><div class="big">💎 ${ref.coins_earned}</div><div class="lbl">Coins Earned</div></div></div>
          </div>
          <h3 style="color:#fbbf24;font-size:15px;margin:20px 0 8px">🏆 Top Referrers</h3>
          <div class="card" style="padding:6px 14px">${leaders}</div>`;
        $("#refSection").innerHTML = refHtml;
        $("#refCopy").onclick=()=>{haptic("success");navigator.clipboard.writeText(ref.referral_link);toast("Link copied!","success");};
        $("#refShare").onclick=()=>{haptic("medium");const txt=`Join Mrx Vinyl Transfer Bot! +${ref.reward_per_ref} free coins on signup 🎁`;
          if(tg?.openTelegramLink) tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(ref.referral_link)}&text=${encodeURIComponent(txt)}`);
          else window.open(`https://t.me/share/url?url=${encodeURIComponent(ref.referral_link)}&text=${encodeURIComponent(txt)}`,"_blank");};
      }catch(e){console.error(e);}
    })();
  }catch(e){content.innerHTML=`<div class="info-box">${e.message}</div>`;}
}
async function renderUnlockFlow(mode){
  await refreshMe();
  const cfg={police:{label:"Police",emoji:"🚓",cost:10,cls:"police"},air:{label:"AirSus",emoji:"🚗",cost:10,cls:"air"}};
  const c=cfg[mode]||cfg.police;const free=state.me?.is_subscriber;
  const myCoins=state.me?.coins ?? 0;
  topTitle.innerHTML=c.label+'<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="visible";state.tab="unlock-flow";state.unlockMode=mode;
  const balLine=free?`<span style="color:#22c55e">👑 FREE</span>`:`<span style="color:${myCoins>=c.cost?'#22c55e':'#ef4444'}">💎 ${myCoins} coins</span>`;
  content.innerHTML=`<h2 class="tab-title">${c.emoji} ${c.label} Unlock</h2><p class="tab-sub">Cost: <b>${free?"FREE":c.cost+" coins"}</b> • Balance: ${balLine}<br><span style="font-size:11px;color:#22c55e">✓ Coins katengi sirf tab jab unlock success ho jaye</span></p><div class="form-group"><label class="form-label">CPM2 Email</label><input class="form-input" id="ulEmail" /></div><div class="form-group"><label class="form-label">Password</label><input class="form-input" id="ulPass" type="password" /></div><button class="btn btn-primary btn-block" id="ulNext">Connect</button><button class="btn btn-ghost btn-block" id="ulBack" style="margin-top:10px">Back</button>`;
  $("#ulBack").onclick=()=>{haptic("light");goTab("transfer");};
  $("#ulNext").onclick=()=>{haptic("medium");const e=$("#ulEmail").value.trim();const p=$("#ulPass").value;if(!e||!p)return toast("Fill both","error");state.unlockEmail=e;state.unlockPass=p;loadUnlockCars(mode);};
}
async function loadUnlockCars(mode){
  content.innerHTML=`<div class="loader"><div class="spinner"></div>Loading cars...</div>`;
  try{
    const r=await api("/api/inspect/cpm2?source=" + mode,{method:"POST",body:{email:state.unlockEmail,password:state.unlockPass}});
    if(!r.ok){toast(r.error||"Failed","error");return renderUnlockFlow(mode);}
    await refreshMe();
    state.unlockCars=r.cars||[];renderUnlockCarPicker(mode,0);
  }catch(e){toast(e.message,"error");renderUnlockFlow(mode);}
}
function renderUnlockCarPicker(mode,page){
  const cfg={police:{label:"Police",emoji:"🚓"},air:{label:"AirSus",emoji:"🚗"}};const c=cfg[mode]||cfg.police;
  topTitle.innerHTML=`Pick Car<span class="powered">${c.label}</span>`;
  const start=page*8;const end=start+8;const slice=state.unlockCars.slice(start,end);
  const items=slice.map(car=>`<div class="car-item ${car.transferable?"":"disabled"}" data-index="${car.index}"><div class="car-badge">${car.id}</div><div><div class="car-name">${car.name}</div><div class="car-meta"><span>🎨 ${car.vinyls===-1?0:car.vinyls}</span></div></div><div class="row-arrow">›</div></div>`).join("");
  const total=Math.ceil(state.unlockCars.length/8);
  content.innerHTML=`<h2 class="tab-title">${c.emoji} Pick Car</h2><p class="tab-sub">${page+1}/${total||1}</p><div class="car-grid">${items||'<div class="info-box">No cars</div>'}</div><div class="pager"><button class="btn btn-ghost" id="ulPrev" ${page===0?"disabled":""}>⬅️</button><button class="btn btn-ghost" id="ulNextP" ${end>=state.unlockCars.length?"disabled":""}>➡️</button></div><button class="btn btn-ghost btn-block" id="ulBack2" style="margin-top:10px">Back</button>`;
  $("#ulPrev").onclick=()=>renderUnlockCarPicker(mode,page-1);
  $("#ulNextP").onclick=()=>renderUnlockCarPicker(mode,page+1);
  $("#ulBack2").onclick=()=>renderUnlockFlow(mode);
  content.querySelectorAll(".car-item").forEach(el=>{
    el.onclick=()=>{
      if(el.classList.contains("disabled"))return toast("Not accessible","error");
      applyUnlock(mode,parseInt(el.dataset.index,10));
    };
  });
}
async function applyUnlock(mode,carIndex){
  const cfg={police:{label:"Police",emoji:"🚓",endpoint:"/api/police",cls:"police"},air:{label:"AirSus",emoji:"🚗",endpoint:"/api/airsus",cls:"air"}};const c=cfg[mode]||cfg.police;
  haptic("heavy");content.innerHTML=`<div class="loader"><div class="spinner"></div>Applying ${c.label}...</div>`;
  try{
    const r=await api(c.endpoint,{method:"POST",body:{email:state.unlockEmail,password:state.unlockPass,car_index:carIndex}});
    await refreshMe();
    const verified=r.verified===1;
    const charged=r.charged===true;
    if(verified){
      haptic("success");
      content.innerHTML=`<h2 class="tab-title">✅ ${c.emoji} ${c.label} Applied!</h2>
        <p class="tab-sub">Sent: ${r.sent} • Verified: Yes • ${r.free ? "FREE" : "Charged: " + r.cost + " coins"}</p>
        <div class="card cta"><div class="card-icon ${c.cls}">${c.emoji}</div><div><div class="card-name">${c.label} Unlocked</div><div class="card-meta">Force close game &amp; re-open</div></div></div>
        <button class="btn btn-primary btn-block" id="ulHome">Back</button>`;
    }else{
      haptic("warning");
      const msg = r.error || (r.sent===0 ? "Could not send unlock request" : "Sent but couldn't verify");
      content.innerHTML=`<h2 class="tab-title">⚠️ ${c.label} Failed</h2>
        <div class="info-box">${msg}<br><br>💎 <b>No coins deducted</b>${charged?" (unexpected)":""}</div>
        <p class="tab-sub" style="font-size:11.5px">Sent: ${r.sent||0} • Verified: ${r.verified||0}</p>
        <button class="btn btn-primary btn-block" id="ulHome">Back</button>`;
    }
    document.getElementById("ulHome").onclick=()=>goTab("transfer");
  }catch(e){
    haptic("error");
    await refreshMe();
    content.innerHTML=`<div class="info-box">${e.message}</div><button class="btn btn-primary btn-block" id="ulHome">Back</button>`;
    document.getElementById("ulHome").onclick=()=>goTab("transfer");
  }
}
function renderTransferFlow(){
  topTitle.innerHTML='Transfer<span class="powered">Powered by Mrx</span>';
  backBtn.style.visibility="visible";setActiveNav("transfer");
  const free=state.me?.is_subscriber;
  content.innerHTML=`<h2 class="tab-title">Vinyl Transfer</h2><p class="tab-sub">Choose source</p><div class="card cta" id="srcCpm1"><div class="card-icon blue">🚗</div><div><div class="card-name">CPM1 Source</div><div class="card-meta">${free?"FREE":COSTS.cpm1+" coins"}</div></div><button class="btn btn-primary">Pick</button></div><div class="card cta" id="srcCpm2"><div class="card-icon">🚙</div><div><div class="card-name">CPM2 Source</div><div class="card-meta">${free?"FREE":COSTS.cpm2+" coins"}</div></div><button class="btn btn-primary">Pick</button></div><button class="btn btn-ghost btn-block" id="cancel1" style="margin-top:10px">Cancel</button>`;
  $("#srcCpm1").onclick=()=>renderCredsForm("cpm1");
  $("#srcCpm2").onclick=()=>renderCredsForm("cpm2");
  $("#cancel1").onclick=()=>goTab("transfer");
}
function renderCredsForm(sourceType){
  topTitle.innerHTML='Credentials';const lbl=sourceType==="cpm1"?"CPM1":"CPM2";
  content.innerHTML=`<h2 class="tab-title">Connect</h2><p class="tab-sub">Source</p><div class="form-group"><label class="form-label">${lbl} Email</label><input class="form-input" id="srcEmail" /></div><div class="form-group"><label class="form-label">Password</label><input class="form-input" id="srcPass" type="password" /></div><button class="btn btn-primary btn-block" id="nextBtn">Next</button><button class="btn btn-ghost btn-block" id="backBtn2" style="margin-top:10px">Back</button>`;
  $("#nextBtn").onclick=()=>{const e=$("#srcEmail").value.trim();const p=$("#srcPass").value;if(!e||!p)return toast("Fill both","error");renderTargetForm(sourceType,e,p);};
  $("#backBtn2").onclick=()=>renderTransferFlow();
}
function renderTargetForm(sourceType,srcEmail,srcPassword){
  topTitle.innerHTML='Target';
  content.innerHTML=`<h2 class="tab-title">Connect</h2><p class="tab-sub">Target CPM2</p><div class="form-group"><label class="form-label">Target Email</label><input class="form-input" id="tgtEmail" /></div><div class="form-group"><label class="form-label">Password</label><input class="form-input" id="tgtPass" type="password" /></div><button class="btn btn-primary btn-block" id="connectBtn">Connect</button><button class="btn btn-ghost btn-block" id="backBtn3" style="margin-top:10px">Back</button>`;
  $("#connectBtn").onclick=async()=>{
    haptic("heavy");const te=$("#tgtEmail").value.trim();const tp=$("#tgtPass").value;
    if(!te||!tp)return toast("Fill both","error");
    content.innerHTML=`<div class="loader"><div class="spinner"></div>Connecting...</div>`;
    try{
      const r=await api("/api/transfer/connect",{method:"POST",body:{source_type:sourceType,src_email:srcEmail,src_password:srcPassword,tgt_email:te,tgt_password:tp}});
      if(!r.ok){toast(r.error||"Failed","error");return renderTargetForm(sourceType,srcEmail,srcPassword);}
      state.srcCars=r.src_cars||[];state.tgtCars=r.tgt_cars||[];state.plan=[];
      state.sourceType=sourceType;state.srcEmail=srcEmail;state.srcPassword=srcPassword;state.tgtEmail=te;state.tgtPassword=tp;
      toast("Connected ✓","success");renderPlan();
    }catch(e){toast(e.message,"error");renderTargetForm(sourceType,srcEmail,srcPassword);}
  };
  $("#backBtn3").onclick=()=>renderCredsForm(sourceType);
}
function renderPlan(){
  topTitle.innerHTML='Plan';
  const free=state.me?.is_subscriber;const cost=free?0:(state.sourceType==="cpm1"?COSTS.cpm1:COSTS.cpm2);
  const list=state.plan.length?state.plan.map((p,i)=>{const d=state.srcCars.find(c=>c.index===p.donor_index);const t=state.tgtCars.find(c=>c.index===p.target_index);return `<div class="plan-item"><div class="plan-num">${i+1}</div><div style="font-size:13px;font-weight:600;color:#fff">${d?.name||"?"} → ${t?.name||"?"}</div></div>`;}).join(""):`<div style="text-align:center;color:#a89bc4;padding:24px 0;font-size:13px">No transfers</div>`;
  content.innerHTML=`<h2 class="tab-title">🚀 Plan</h2><p class="tab-sub">${free?"FREE":`Cost: ${cost} (charged only on success)`}</p>${list}<button class="btn btn-primary btn-block" id="addTransfer">➕ Add</button>${state.plan.length?`<button class="btn btn-primary btn-block" id="execTransfer" style="margin-top:10px">🚀 Execute</button><button class="btn btn-ghost btn-block" id="clearPlan" style="margin-top:10px">🧹 Clear</button>`:""}<button class="btn btn-ghost btn-block" id="cancelPlan" style="margin-top:10px">Cancel</button>`;
  $("#addTransfer").onclick=()=>pickDonor(0);
  $("#clearPlan")?.addEventListener("click",()=>{state.plan=[];renderPlan();});
  $("#cancelPlan").onclick=()=>goTab("transfer");
  $("#execTransfer")?.addEventListener("click",executePlan);
}
function pickDonor(p=0){renderCarPicker("donor",state.srcCars,p,"Pick Source",state.sourceType);}
function pickTarget(p=0){renderCarPicker("target",state.tgtCars,p,"Pick Target","cpm2");}
function renderCarPicker(role,cars,page,title,sourceType){
  topTitle.innerHTML=title;
  const start=page*8;const end=start+8;const slice=cars.slice(start,end);
  const items=slice.map(c=>{
    const v=c.vinyls===-1?0:c.vinyls;const w=c.window===-1?0:c.window;
    const ok=role==="donor"?(sourceType==="cpm2"?c.transferable:c.style_transferable):c.transferable;
    return `<div class="car-item ${ok?"":"disabled"}" data-index="${c.index}"><div class="car-badge">${c.id}</div><div><div class="car-name">${c.name}</div><div class="car-meta"><span>🎨 ${v}</span><span>📦 ${w}</span></div></div><div class="row-arrow">›</div></div>`;
  }).join("");
  const total=Math.ceil(cars.length/8);
  content.innerHTML=`<h2 class="tab-title">${title}</h2><p class="tab-sub">${page+1}/${total||1}</p><div class="car-grid">${items||'<div class="info-box">No cars</div>'}</div><div class="pager"><button class="btn btn-ghost" id="prevPage" ${page===0?"disabled":""}>⬅️</button><button class="btn btn-ghost" id="nextPage" ${end>=cars.length?"disabled":""}>➡️</button></div><button class="btn btn-ghost btn-block" id="backToPlan" style="margin-top:10px">Back</button>`;
  $("#prevPage").onclick=()=>{role==="donor"?pickDonor(page-1):pickTarget(page-1);};
  $("#nextPage").onclick=()=>{role==="donor"?pickDonor(page+1):pickTarget(page+1);};
  $("#backToPlan").onclick=()=>renderPlan();
  content.querySelectorAll(".car-item").forEach(el=>{
    el.onclick=()=>{
      if(el.classList.contains("disabled"))return toast("Not transferable","error");
      const idx=parseInt(el.dataset.index,10);
      if(role==="donor"){state.tempDonorIndex=idx;pickTarget(0);}
      else{state.plan=state.plan.filter(p=>p.target_index!==idx);state.plan.push({donor_index:state.tempDonorIndex,target_index:idx});state.tempDonorIndex=null;toast("Added ✓","success");renderPlan();}
    };
  });
}
async function executePlan(){
  haptic("heavy");content.innerHTML=`<div class="loader"><div class="spinner"></div>Executing...</div>`;
  try{
    const r=await api("/api/transfer/execute",{method:"POST",body:{source_type:state.sourceType,src_email:state.srcEmail,src_password:state.srcPassword,tgt_email:state.tgtEmail,tgt_password:state.tgtPassword,plan:state.plan}});
    await refreshMe();
    if(!r.ok){
      haptic("error");
      const chargeInfo = r.charged ? `Charged: ${r.cost} coins` : "No coins deducted";
      content.innerHTML=`<h2 class="tab-title">❌ Failed</h2><div class="info-box">${r.error||"Unknown"}<br><br>💎 ${chargeInfo}</div><button class="btn btn-primary btn-block" id="backHome">Back</button>`;
    }else{
      haptic("success");
      content.innerHTML=`<h2 class="tab-title">✅ Done</h2><p class="tab-sub">Sent: ${r.sent} | Verified: ${r.verified} | ${r.charged?("Charged: "+r.cost):"No charge"}</p><button class="btn btn-primary btn-block" id="backHome">Back</button>`;
    }
    document.getElementById("backHome").onclick=()=>{state.plan=[];goTab("transfer");};
  }catch(e){await refreshMe();content.innerHTML=`<div class="info-box">${e.message}</div><button class="btn btn-primary btn-block" id="backHome">Back</button>`;document.getElementById("backHome").onclick=()=>goTab("transfer");}
}
async function renderInspect(kind){
  await refreshMe();
  topTitle.innerHTML='Inspect';backBtn.style.visibility="visible";state.tab="inspect";
  const free=state.me?.is_subscriber;const cost=free?0:10;const myCoins=state.me?.coins??0;
  content.innerHTML=`<h2 class="tab-title">Inspect ${kind.toUpperCase()}</h2><p class="tab-sub">${free?"FREE":cost+" coins"} • Balance: <b>${myCoins}</b></p><div class="form-group"><label class="form-label">Email</label><input class="form-input" id="ie" /></div><div class="form-group"><label class="form-label">Password</label><input class="form-input" id="ip" type="password" /></div><button class="btn btn-primary btn-block" id="inspectGo">Inspect</button><button class="btn btn-ghost btn-block" id="inspectBack" style="margin-top:10px">Back</button>`;
  $("#inspectBack").onclick=()=>goTab("transfer");
  $("#inspectGo").onclick=async()=>{
    const e=$("#ie").value.trim();const p=$("#ip").value;if(!e||!p)return toast("Fill both","error");
    content.innerHTML=`<div class="loader"><div class="spinner"></div>Inspecting...</div>`;
    try{
      const r=await api("/api/inspect/"+kind,{method:"POST",body:{email:e,password:p}});
      await refreshMe();
      if(!r.ok){content.innerHTML=`<div class="info-box">${r.error}</div><button class="btn btn-primary btn-block" id="backHome">Back</button>`;document.getElementById("backHome").onclick=()=>goTab("transfer");return;}
      const items=(r.cars||[]).map(c=>`<div class="car-item disabled"><div class="car-badge">${c.id}</div><div><div class="car-name">${c.name}</div><div class="car-meta"><span>🎨 ${c.vinyls===-1?0:c.vinyls}</span></div></div></div>`).join("");
      content.innerHTML=`<h2 class="tab-title">✅ Connected</h2><p class="tab-sub">${r.count} cars</p><div class="car-grid">${items}</div><button class="btn btn-primary btn-block" id="backHome" style="margin-top:14px">Back</button>`;
      document.getElementById("backHome").onclick=()=>goTab("transfer");
    }catch(err){await refreshMe();toast(err.message,"error");renderInspect(kind);}
  };
}
(async function boot(){
  try{const me=await api("/api/me");state.me=me;updateHeader();goTab("subs");}
  catch(e){content.innerHTML=`<div class="info-box" style="margin-top:60px"><b>Access Denied</b><br/>${e.message}</div>`;}
})();
</script>
</body>
</html>"""

# ==========================================================
# ENTRY
# ==========================================================
if __name__ == "__main__":
    print("=" * 55)
    print("🎨 Mrx — Charge Only On Success")
    print("=" * 55)
    print(f"👑 Admin: {ADMIN_ID}")
    print(f"🌐 URL: {WEBAPP_URL}")
    print(f"🗄️  DB: {DB_PATH}")
    print(f"🕒 IST: {ts_ist()}")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), log_level="info")
