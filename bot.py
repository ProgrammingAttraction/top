import asyncio
import hashlib
import json
import logging
import os
import random
import string
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, request, jsonify

from telegram import (
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

# ---------- MONGODB IMPORTS ----------
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, ConnectionFailure, PyMongoError
from pymongo.write_concern import WriteConcern

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURATION ---
API_BASE = "https://partners.servcul.com/CashdeskBotAPI/"

HASH_KEY = os.getenv("HASH_KEY", "e149eefe46e0ac6dda3f229c6cfeac315996a3060b3a2cbd375db9be0171bd60")
CASHIER_PASS = os.getenv("CASHIER_PASS", "457547")
CASHDESK_ID = os.getenv("CASHDESK_ID", "1169474")
CASHIER_LOGIN = os.getenv("CASHIER_LOGIN", "Moazz1")

BOT_TOKEN = os.getenv("BOT_TOKEN", "8725056932:AAH76_QqBjFFSFXj55oBUGGZPHPuLQgHaGs")

ORDER_API_URL = "https://asmm.worldxxpp.com/api/createOrder"
INQUIRY_ORDER_API_URL = "https://asmm.worldxxpp.com/api/inquiryOrder"
PAYMENT_ORDER_API_URL = "https://asmm.worldxxpp.com/api/createPaymentOrder"

CALLBACK_HOST = os.getenv("CALLBACK_HOST", "0.0.0.0")
CALLBACK_PORT = int(os.getenv("PORT") or os.getenv("CALLBACK_PORT", "8080"))
CALLBACK_PATH = os.getenv("CALLBACK_PATH", "/api/callback")

_default_callback = f"https://bdtopup.onexbbbot.com{CALLBACK_PATH}"
MERCHANT_CALLBACK_URL = os.getenv("MERCHANT_CALLBACK_URL", _default_callback)

# ---------- SAME CREDENTIALS FOR DEPOSIT + PAYOUT ----------
SHOP_USER_LONG_ID = "49cd235e-38bf-4528-92cb-8dd86d355859"
MERCHANT_HASH_KEY = os.getenv("MERCHANT_HASH_KEY", "xP17Zxkh10dZkTdWlF4ZphLyIer1x4oN")

PAYOUT_HASH_KEY = MERCHANT_HASH_KEY
PAYOUT_SHOP_USER_LONG_ID = SHOP_USER_LONG_ID

WITHDRAW_CHANNELS = [
    (34, "বিকাশ", "💖"),
    (35, "নগদ", "🧡"),
    (46, "রকেট", "💜"),
]
WITHDRAW_CURRENCY_ID = 11

DEFAULT_PAYEE_ACCOUNT_NAME = os.getenv("PAYEE_ACCOUNT_NAME", "ASMPAY")
DEFAULT_PAYEE_PHONE_NUMBER = os.getenv("PAYEE_PHONE_NUMBER", "01700000000")

BANNER_IMAGE_URL = "https://i.ibb.co/sample-banner.jpg"
TXN_EXAMPLE_IMAGE = "https://i.ibb.co/T6NZ3Yw/photo-2026-10-05-20-56-36.jpg"

WITHDRAW_CITY = "Madhabdi"
WITHDRAW_STREET = "Niketon House (24/7)"
EXPECTED_CURRENCY_ID = None

SUPPORT_USERNAME = "@depositeandwithdrawal_service"
SUPPORT_LINK = "https://t.me/depositeandwithdrawal_service"
PROMO_CODE = "diposite19"

SUPPORT_MESSAGE = (
    "📣 💬 সার্বিক সহযোগিতার জন্য: প্রথমে আমাদের অফিসিয়াল সাপোর্ট গ্রুপ "
    f"বা চ্যানেলে মেসেজ করুন 👉 {SUPPORT_USERNAME}"
)

ADMIN_USER_IDS = set(
    x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
)

CHANNEL_MAP = {
    ("বিকাশ", "পারসোনাল"): 1104,
    ("বিকাশ", "এজেন্ট"): 34,
    ("নগদ", "পারসোনাল"): 1105,
    ("নগদ", "এজেন্ট"): 35,
    ("রকেট", "পারসোনাল"): 46,
    ("রকেট", "এজেন্ট"): 46,
}

TERMINAL_TRX_ERRORS = {
    "ThisTransferCodeAlreadySuccessOrder",
    "ThisTransferCodeIsNotYourOrder",
    "OrderAlreadySuccess",
    "OrderAlreadyMakeUp",
    "NoOrder",
    "OrderStatusError",
}

PAYOUT_ERROR_BN = {
    100406: "❌ এই ইউজারের জন্য কোনো পেআউট রিকোয়েস্ট পাওয়া যায়নি। উইথড্র কোডটি সঠিক কিনা যাচাই করুন।",
    100337: "⚠️ এই পেআউট রিকোয়েস্ট আগেই প্রসেস হয়েছে।",
    100400: "⚠️ উইথড্র কোডটি সঠিক নয়। দয়া করে সঠিক কোড দিন।",
    100401: "⚠️ উইথড্র কোডটি মেয়াদোত্তীর্ণ (expired)।",
    100403: "⚠️ এই উইথড্র কোডটি আগেই ব্যবহার করা হয়েছে।",
    100404: "❌ এই প্লেয়ারের একাউন্টে পর্যাপ্ত ব্যালেন্স নেই।",
}

PAYOUT_ERROR_TEXT_BN = {
    "не найдено ни одного запроса на выплату": "এই ইউজারের জন্য কোনো পেআউট রিকোয়েস্ট পাওয়া যায়নি।",
    "уже был проведен": "এই পেআউট রিকোয়েস্ট আগেই সম্পন্ন হয়েছে।",
    "недостаточно средств": "একাউন্টে পর্যাপ্ত ব্যালেন্স নেই।",
    "неверный код": "উইথড্র কোডটি সঠিক নয়।",
    "код не найден": "উইথড্র কোডটি খুঁজে পাওয়া যায়নি।",
    "истек": "উইথড্র কোডটির মেয়াদ শেষ হয়ে গেছে।",
}

PAYMENT_ORDER_ERROR_BN = {
    "PaymentChannelClosed": "❌ এই পেমেন্ট চ্যানেলটি এখন বন্ধ আছে।",
    "InsufficientBalance": "❌ আমাদের একাউন্টে পর্যাপ্ত ব্যালেন্স নেই।",
    "TryAgainLater": "⚠️ সিস্টেম এখন ব্যস্ত। একটু পরে চেষ্টা করুন।",
    "DevError": "❌ সিস্টেমে সমস্যা হয়েছে।",
    "PairingFailed": "❌ এই চ্যানেলটি এই মুহূর্তে কাজ করছে না।",
    "CheckIpAddressFailed": "❌ IP যাচাই ব্যর্থ হয়েছে।",
    "CheckEncryptValueFailed": "❌ এনক্রিপশন যাচাই ব্যর্থ হয়েছে।",
    "NoPayeeAccountName": "❌ পেউআউট নম্বর সঠিক নয়।",
}

PAYMENT_ORDER_ERROR_TEXT_BN = {
    "channel closed": "❌ এই পেমেন্ট চ্যানেলটি এখন বন্ধ আছে।",
    "insufficient": "❌ আমাদের একাউন্টে পর্যাপ্ত ব্যালেন্স নেই।",
    "try again later": "⚠️ সিস্টেম এখন ব্যস্ত। একটু পরে চেষ্টা করুন।",
    "busy": "⚠️ সিস্টেম এখন ব্যস্ত। একটু পরে চেষ্টা করুন।",
    "pairing": "❌ এই চ্যানেলটি এই মুহূর্তে কাজ করছে না।",
    "unavailable": "❌ এই চ্যানেলটি এই মুহূর্তে কাজ করছে না।",
}

# ---------- Payout status codes (from PaymentOrderStatusId) ----------
PAYOUT_STATUS_PAID = {2}
PAYOUT_STATUS_FAILED = {3, 4}
PAYOUT_STATUS_PENDING = {0, 1}

PAYMENT_ORDER_STATUS_BN = {
    1: "⏳ পেন্ডিং",
    2: "✅ পেমেন্ট সম্পন্ন",
    3: "❌ পেমেন্ট ব্যর্থ",
    4: "🚫 বাতিল / মেয়াদোত্তীর্ণ",
}


def translate_payout_error(message: str, message_id) -> str:
    if message_id is not None:
        try:
            mid = int(message_id)
            if mid in PAYOUT_ERROR_BN:
                return PAYOUT_ERROR_BN[mid]
        except (TypeError, ValueError):
            pass

    if not isinstance(message, str):
        return "❌ উইথড্র ব্যর্থ হয়েছে। সাপোর্টে যোগাযোগ করুন।"

    lower = message.lower()
    for ru_key, bn_val in PAYOUT_ERROR_TEXT_BN.items():
        if ru_key in lower:
            return f"❌ {bn_val}"

    return f"❌ উইথড্র ব্যর্থ: {message}"


def translate_payment_order_error(message: str) -> str:
    if not isinstance(message, str):
        return "❌ এই পেমেন্ট চ্যানেলটি এই মুহূর্তে কাজ করছে না। অন্য চ্যানেল বেছে নিন।"

    for key, val in PAYMENT_ORDER_ERROR_BN.items():
        if key in message:
            return val

    lower = message.lower()
    for key, val in PAYMENT_ORDER_ERROR_TEXT_BN.items():
        if key in lower:
            return val

    return "❌ এই পেমেন্ট চ্যানেলটি এই মুহূর্তে কাজ করছে না।"


# =========================================================================
# --- 1.5 MONGODB SETUP ---
# =========================================================================
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://shihabmoni15_db_user:KyLsKAVROQFFMXLL@cluster0.jzuaxih.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "onexbet_bot")

mongo_client = None
mongo_db = None
col_processed = None
col_pending = None
col_users = None
col_txns = None
col_payouts = None
col_events = None
col_refunds = None     # NEW: dedicated collection for refunds audit


def _ensure_index(collection, keys, name=None, **kwargs):
    try:
        collection.create_index(keys, name=name, **kwargs)
        print(f"✅ [MONGO] index OK: {name}")
        return True
    except Exception as e:
        err_str = str(e)
        if ("IndexKeySpecsConflict" in err_str
                or "already exists with a different name" in err_str
                or "same name as the requested index" in err_str):
            try:
                for idx in collection.list_indexes():
                    if idx.get("name") == name:
                        collection.drop_index(name)
                        print(f"⚠️  [MONGO] dropped conflicting index: {name}")
                        break
            except Exception as de:
                print(f"⚠️  [MONGO] could not drop index {name}: {de}")
            try:
                collection.create_index(keys, name=name, **kwargs)
                print(f"✅ [MONGO] recreated index: {name}")
                return True
            except Exception as re:
                print(f"❌ [MONGO] still failed to create {name}: {re}")
                return False
        else:
            print(f"❌ [MONGO] index create failed for {name}: {e}")
            return False


def init_mongodb():
    global mongo_client, mongo_db
    global col_processed, col_pending, col_users, col_txns, col_payouts, col_events, col_refunds

    try:
        mongo_client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            socketTimeoutMS=20000,
            maxPoolSize=50,
            retryWrites=True,
            w="majority",
        )
        mongo_client.admin.command("ping")
        mongo_db = mongo_client[MONGO_DB_NAME]

        col_processed = mongo_db["processed_orders"]
        col_pending = mongo_db["pending_deposits"]
        col_users = mongo_db["users"]
        col_txns = mongo_db["transactions"]
        col_payouts = mongo_db["payouts"]
        col_events = mongo_db["events"]
        col_refunds = mongo_db["refunds"]

        _ensure_index(col_processed, "shop_order_id", unique=True, name="uniq_shop_order_id")
        _ensure_index(col_processed, "player_id", name="idx_player_id")
        _ensure_index(col_processed, "created_at", name="idx_created_at")

        _ensure_index(col_pending, "shop_order_id", unique=True, name="uniq_pending_shop_order_id")
        _ensure_index(col_pending, "created_at", name="idx_pending_created_at",
                      expireAfterSeconds=60 * 60 * 24)

        _ensure_index(col_users, "player_id", unique=True, name="uniq_player_id", sparse=True)

        _ensure_index(col_txns, "shop_order_id", unique=True, name="uniq_txn_shop_order_id")
        _ensure_index(col_txns, [("player_id", ASCENDING), ("created_at", DESCENDING)],
                      name="idx_txn_player_time")
        _ensure_index(col_txns, "status", name="idx_txn_status")

        _ensure_index(col_payouts, "operation_id", name="idx_payout_op_id", sparse=True)
        _ensure_index(col_payouts, "payment_order_id", name="idx_payout_payment_order_id",
                      sparse=True)
        _ensure_index(col_payouts, [("player_id", ASCENDING), ("created_at", DESCENDING)],
                      name="idx_payout_player_time")

        _ensure_index(col_events, "created_at", name="idx_event_created_at",
                      expireAfterSeconds=60 * 60 * 24 * 7)

        # NEW: refunds collection
        _ensure_index(col_refunds, "payment_order_id", unique=True,
                      name="uniq_refund_payment_order_id")
        _ensure_index(col_refunds, [("player_id", ASCENDING), ("created_at", DESCENDING)],
                      name="idx_refund_player_time")

        logger.info(f"[MONGO] connected to {MONGO_DB_NAME} and indexes ensured ✅")
        print(f"🗄️  [MONGO] Connected to MongoDB database: {MONGO_DB_NAME}")
        return True
    except ConnectionFailure as e:
        logger.error(f"[MONGO] connection failed: {e}")
        print(f"❌ [MONGO] connection failed: {e}")
        return False
    except Exception as e:
        logger.error(f"[MONGO] init error: {e}")
        print(f"❌ [MONGO] init error: {e}")
        return False


# =========================================================================
# --- 2. HELPERS ---
# =========================================================================
def sha256(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def md5(t):
    return hashlib.md5(t.encode("utf-8")).hexdigest()


def get_confirm(identifier):
    return md5(f"{identifier}:{HASH_KEY}")


def get_sign(sha_part, md5_part):
    return sha256(sha_part + md5_part)


def format_json(data):
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return str(data)


def php_json_encode(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def generate_encrypt_value(params, hash_key):
    kv_pairs = []
    for key in sorted(params.keys()):
        if key in ("EncryptValue", "File"):
            continue
        val = params[key]
        if val is None or val == "":
            continue
        if isinstance(val, bool):
            val = "true" if val else "false"
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        kv_pairs.append(f"{key}={val}")

    kv_pairs.append(f"HashKey={hash_key.strip()}")
    raw_string = "&".join(kv_pairs).lower()
    return hashlib.sha256(raw_string.encode("utf-8")).hexdigest().upper()


def escape_md(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    return (
        text.replace("\\", "\\\\")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("`", "\\`")
            .replace("[", "\\[")
    )


def safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# =========================================================================
# --- 2.4 DUPLICATE-PROTECTION (MONGODB PERSISTENT) ---
# =========================================================================
processed_orders_lock = threading.Lock()
processed_orders = set()


def _load_processed_orders_from_mongo():
    global processed_orders
    try:
        cursor = col_processed.find({}, {"shop_order_id": 1, "_id": 0})
        with processed_orders_lock:
            for doc in cursor:
                sid = doc.get("shop_order_id")
                if sid:
                    processed_orders.add(str(sid))
        logger.info(
            f"[DUP-GUARD] loaded {len(processed_orders)} processed orders from MongoDB"
        )
        print(f"🔒 [DUP-GUARD] loaded {len(processed_orders)} processed orders from MongoDB")
    except Exception as e:
        logger.error(f"[DUP-GUARD] load failed: {e}")
        print(f"❌ [DUP-GUARD] load failed: {e}")


def is_order_processed(shop_order_id: str) -> bool:
    sid = str(shop_order_id)
    with processed_orders_lock:
        if sid in processed_orders:
            return True
    try:
        doc = col_processed.find_one({"shop_order_id": sid}, {"_id": 1})
        if doc:
            with processed_orders_lock:
                processed_orders.add(sid)
            return True
    except Exception as e:
        logger.error(f"[DUP-GUARD] mongo lookup failed: {e}")
    return False


def mark_order_processed(shop_order_id: str, player_id: str = None,
                          amount: int = None, extra: dict = None) -> bool:
    sid = str(shop_order_id)
    with processed_orders_lock:
        if sid in processed_orders:
            return False

    doc = {
        "shop_order_id": sid,
        "player_id": str(player_id) if player_id else None,
        "amount": safe_int(amount) if amount is not None else None,
        "created_at": datetime.now(timezone.utc),
        "source": "callback",
    }
    if extra:
        doc.update(extra)

    try:
        col_processed.insert_one(doc)
    except DuplicateKeyError:
        with processed_orders_lock:
            processed_orders.add(sid)
        logger.warning(f"[DUP-GUARD] {sid} already in MongoDB — duplicate prevented")
        print(f"🚫 [DUP-GUARD] {sid} already in MongoDB — skipping credit")
        return False
    except Exception as e:
        logger.error(f"[DUP-GUARD] insert failed: {e}")
        return False

    with processed_orders_lock:
        processed_orders.add(sid)
    logger.info(f"[DUP-GUARD] {sid} marked processed (MongoDB persisted)")
    print(f"🔒 [DUP-GUARD] {sid} marked in MongoDB BEFORE API call")
    return True


# =========================================================================
# --- 2.5 SHOP ORDER ID ENCODE / DECODE ---
# =========================================================================
def make_shop_order_id(player_id):
    ts = int(datetime.now().timestamp())
    rand4 = "".join(random.choices("0123456789abcdef", k=4))
    return f"ORD-{player_id}-{ts}-{rand4}"


def extract_player_id_from_shop_order_id(shop_order_id):
    if not shop_order_id:
        return None
    s = str(shop_order_id).strip()
    parts = s.split("-")
    if len(parts) >= 4 and parts[0].upper() == "ORD" and parts[1].isdigit():
        return parts[1]
    if len(parts) >= 4 and parts[0].upper() == "ORD":
        if parts[2].isdigit():
            return None
    return None


# =========================================================================
# --- 2.6 PENDING DEPOSIT REGISTRY (MONGODB) ---
# =========================================================================
pending_deposits_lock = threading.Lock()


def register_pending_deposit(shop_order_id, chat_id, user_id, name, amount, wallet, trxid):
    try:
        col_pending.update_one(
            {"shop_order_id": str(shop_order_id)},
            {"$set": {
                "shop_order_id": str(shop_order_id),
                "chat_id": int(chat_id) if chat_id else 0,
                "user_id": str(user_id),
                "name": name,
                "amount": safe_int(amount),
                "wallet": wallet,
                "trxid": trxid,
                "notified": False,
                "updated_at": datetime.now(timezone.utc),
            },
             "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        logger.info(f"[PENDING] registered {shop_order_id} for user {user_id} amount {amount}")
        print(f"📝 [PENDING] registered {shop_order_id} user={user_id} amount={amount} trxid={trxid}")
    except Exception as e:
        logger.error(f"[PENDING] register failed: {e}")
        print(f"❌ [PENDING] register failed: {e}")


def pop_pending_deposit(shop_order_id):
    try:
        doc = col_pending.find_one_and_delete({"shop_order_id": str(shop_order_id)})
        return doc
    except Exception as e:
        logger.error(f"[PENDING] pop failed: {e}")
        return None


def peek_pending_deposit(shop_order_id):
    try:
        return col_pending.find_one({"shop_order_id": str(shop_order_id)})
    except Exception as e:
        logger.error(f"[PENDING] peek failed: {e}")
        return None


def mark_pending_notified(shop_order_id):
    try:
        col_pending.update_one(
            {"shop_order_id": str(shop_order_id)},
            {"$set": {"notified": True, "notified_at": datetime.now(timezone.utc)}},
        )
    except Exception as e:
        logger.error(f"[PENDING] mark notified failed: {e}")


def upsert_user(player_id, name=None, currency_id=None):
    if not player_id:
        return
    try:
        now = datetime.now(timezone.utc)
        set_doc = {"player_id": str(player_id), "last_seen": now}
        if name:
            set_doc["name"] = name
        if currency_id is not None:
            set_doc["currency_id"] = currency_id
        col_users.update_one(
            {"player_id": str(player_id)},
            {"$set": set_doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"[USERS] upsert failed: {e}")


def log_transaction(shop_order_id, player_id, paid_amount, wallet, trxid,
                    status, api_ok, api_message=None, api_message_id=None,
                    chat_id=None, name=None, order_amount=None,
                    extra=None):
    try:
        doc = {
            "shop_order_id": str(shop_order_id),
            "player_id": str(player_id) if player_id else None,
            "name": name,
            "chat_id": int(chat_id) if chat_id else None,
            "amount": safe_int(paid_amount) if paid_amount is not None else None,
            "paid_amount": safe_int(paid_amount) if paid_amount is not None else None,
            "order_amount": safe_int(order_amount) if order_amount is not None else None,
            "wallet": wallet,
            "trxid": trxid,
            "status": status,
            "api_ok": bool(api_ok),
            "api_message": api_message,
            "api_message_id": api_message_id,
            "created_at": datetime.now(timezone.utc),
        }
        if extra:
            doc.update(extra)
        col_txns.update_one(
            {"shop_order_id": str(shop_order_id)},
            {"$set": doc, "$setOnInsert": {"first_seen": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"[TXN] log failed: {e}")


def log_payout(player_id, code, amount, status, operation_id=None,
               phone=None, channel_id=None, channel_name=None,
               payment_order_id=None, error=None, chat_id=None,
               extra=None):
    try:
        doc = {
            "player_id": str(player_id) if player_id else None,
            "code": code,
            "amount": amount,
            "status": status,
            "operation_id": operation_id,
            "phone": phone,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "payment_order_id": payment_order_id,
            "chat_id": int(chat_id) if chat_id else None,
            "error": error,
            "created_at": datetime.now(timezone.utc),
            "callback_received": False,
            "callback_notified": False,
            "refund_done": False,   # ← NEW: refund idempotency flag
        }
        if extra:
            doc.update(extra)
        col_payouts.insert_one(doc)
    except Exception as e:
        logger.error(f"[PAYOUT LOG] failed: {e}")


def find_payout_by_payment_order_id(payment_order_id):
    if not payment_order_id:
        return None
    try:
        return col_payouts.find_one({"payment_order_id": str(payment_order_id)})
    except Exception as e:
        logger.error(f"[PAYOUT LOOKUP] failed: {e}")
        return None


def update_payout_callback(payment_order_id, updates: dict):
    if not payment_order_id:
        return
    try:
        col_payouts.update_one(
            {"payment_order_id": str(payment_order_id)},
            {"$set": updates},
        )
    except Exception as e:
        logger.error(f"[PAYOUT UPDATE] failed: {e}")


def log_event(event_type, payload, remote_addr=None):
    try:
        col_events.insert_one({
            "event_type": event_type,
            "payload": payload,
            "remote_addr": remote_addr,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(f"[EVENT] log failed: {e}")


# =========================================================================
# --- 2.6b REFUND HELPERS (NEW) ---
# =========================================================================
def _has_refund_been_done(payment_order_id: str) -> bool:
    """Check if a refund has already been issued for this payout."""
    if not payment_order_id:
        return False
    try:
        doc = col_refunds.find_one({"payment_order_id": str(payment_order_id)}, {"_id": 1})
        return doc is not None
    except Exception as e:
        logger.error(f"[REFUND-CHECK] failed: {e}")
        return False


def _mark_refund_done(payment_order_id: str, player_id: str, amount: int,
                      api_ok: bool, api_message: str = None,
                      message_id=None, chat_id=None):
    """Persist a refund record (idempotent via unique index)."""
    try:
        col_refunds.insert_one({
            "payment_order_id": str(payment_order_id),
            "player_id": str(player_id) if player_id else None,
            "amount": safe_int(amount),
            "api_ok": bool(api_ok),
            "api_message": api_message,
            "api_message_id": message_id,
            "chat_id": int(chat_id) if chat_id else None,
            "created_at": datetime.now(timezone.utc),
        })
        return True
    except DuplicateKeyError:
        logger.warning(f"[REFUND] refund already exists for {payment_order_id}")
        return False
    except Exception as e:
        logger.error(f"[REFUND] persist failed: {e}")
        return False


def refund_payout_to_player(player_id, amount, payment_order_id,
                             chat_id=None, reason: str = "") -> dict:
    """
    Refund a failed payout to the player's 1xBet balance.
    Returns dict with `success`, `duplicate`, `message`, `message_id`, `summa`.
    Idempotent: won't refund twice for the same payment_order_id.
    """
    player_id = str(player_id).strip()
    amount = safe_int(amount)

    if not player_id or amount <= 0:
        logger.warning(f"[REFUND] invalid args player_id={player_id!r} amount={amount}")
        return {"success": False, "message": "invalid refund args",
                "duplicate": False, "message_id": None, "summa": None}

    # ---------- IDEMPOTENCY CHECK ----------
    if _has_refund_been_done(payment_order_id):
        logger.info(f"[REFUND] already done for {payment_order_id} — skipping")
        print(f"♻️  [REFUND] already refunded {payment_order_id} — skipping")
        return {"success": True, "duplicate": True,
                "message": "refund already issued",
                "message_id": None, "summa": None}

    print("\n" + "=" * 78)
    print("♻️  [REFUND] calling api_deposit_add for failed payout")
    print(f"    player_id={player_id}  amount={amount}  payment_order_id={payment_order_id}")
    print("=" * 78)

    # ---------- CALL DEPOSIT API ----------
    try:
        add_res = api_deposit_add(player_id, amount)
    except Exception as e:
        logger.error(f"[REFUND] api_deposit_add exception: {e}")
        add_res = {"success": False, "message": f"Exception: {e}"}

    ok = bool(add_res.get("success"))
    dup = bool(add_res.get("duplicate_guard"))
    blocked = bool(add_res.get("withdrawal_blocked"))
    msg = add_res.get("message") or ""
    summa = add_res.get("summa")
    msg_id = add_res.get("message_id")

    print(
        f"♻️  [REFUND] api_deposit_add result: ok={ok} dup={dup} blocked={blocked} "
        f"msg_id={msg_id} msg={msg}"
    )

    # Duplicate guard from 1xBet API → treat as already-refunded
    if dup:
        logger.info(f"[REFUND] 1xBet reports duplicate for {payment_order_id}")
        _mark_refund_done(payment_order_id, player_id, amount,
                          api_ok=True, api_message=msg,
                          message_id=msg_id, chat_id=chat_id)
        log_transaction(
            shop_order_id=f"REFUND-{payment_order_id}",
            player_id=player_id,
            paid_amount=amount,
            wallet="REFUND",
            trxid=f"refund-dup-{payment_order_id}",
            status="refund_duplicate",
            api_ok=True,
            api_message=msg,
            api_message_id=msg_id,
            chat_id=chat_id,
            order_amount=amount,
            extra={"kind": "refund", "reason": reason,
                   "payment_order_id": payment_order_id},
        )
        return {"success": True, "duplicate": True, "message": msg,
                "message_id": msg_id, "summa": summa}

    # Persist refund regardless of success (so we don't spam API on retries)
    _mark_refund_done(payment_order_id, player_id, amount,
                      api_ok=ok, api_message=msg,
                      message_id=msg_id, chat_id=chat_id)

    # Log to transactions with REFUND- prefix to distinguish from real deposits
    log_transaction(
        shop_order_id=f"REFUND-{payment_order_id}",
        player_id=player_id,
        paid_amount=amount,
        wallet="REFUND",
        trxid=f"refund-{payment_order_id}",
        status="refund_success" if ok else "refund_failed",
        api_ok=ok,
        api_message=msg,
        api_message_id=msg_id,
        chat_id=chat_id,
        order_amount=amount,
        extra={
            "kind": "refund",
            "reason": reason,
            "payment_order_id": payment_order_id,
            "withdrawal_blocked": blocked,
        },
    )

    return {"success": ok, "duplicate": False, "message": msg,
            "message_id": msg_id, "summa": summa, "withdrawal_blocked": blocked}


# =========================================================================
# --- 2.7 CALLBACK HTTP SERVER (Flask) ---
# =========================================================================
flask_app = Flask(__name__)
telegram_app = None
bot_event_loop = None


def _notify_user_via_telegram(chat_id, text):
    if telegram_app is None or bot_event_loop is None:
        logger.warning("[CALLBACK] telegram_app/bot_event_loop not set")
        return
    try:
        coro = telegram_app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML"
        )
        asyncio.run_coroutine_threadsafe(coro, bot_event_loop)
    except Exception as e:
        logger.error(f"[CALLBACK] failed to send telegram message: {e}")


# =========================================================================
# --- 2.8 CALLBACK FIELD EXTRACTORS ---
# =========================================================================
def _extract_callback_paid_amount(payload: dict) -> int:
    for key in ("AmountPaid", "amountPaid", "RealAmount", "realAmount",
                "Amount", "amount"):
        if key in payload:
            v = payload.get(key)
            iv = safe_int(v, default=-1)
            if iv >= 0:
                return iv
    return 0


def _extract_callback_order_amount(payload: dict) -> int:
    for key in ("Amount", "amount"):
        if key in payload:
            v = payload.get(key)
            iv = safe_int(v, default=-1)
            if iv >= 0:
                return iv
    return 0


def _extract_callback_trxid(payload: dict) -> str:
    for key in ("MonitorTransferCode", "monitorTransferCode",
                "TransferCode", "transferCode"):
        v = payload.get(key)
        if v and str(v).strip() and str(v).strip().upper() != "PENDING":
            return str(v).strip()

    for key in ("TrackingNumber", "trackingNumber",
                "OriginalOrderTrackingNumber", "originalOrderTrackingNumber"):
        v = payload.get(key)
        if v and str(v).strip():
            return str(v).strip()

    return ""


def _is_placeholder_trxid(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    if not s:
        return True
    if s.upper() in ("PENDING", "N/A", "NA", "-", "NONE", "NULL", "TEST"):
        return True
    return False


# =========================================================================
# --- 2.9 PAYOUT CALLBACK DETECTION & HANDLING (WITH REFUND) ---
# =========================================================================
def _is_payout_callback(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    if "PaymentOrderStatusId" in payload or "paymentOrderStatusId" in payload:
        return True
    if "PaymentOrderId" in payload or "paymentOrderId" in payload:
        return True

    sid = str(payload.get("ShopOrderId") or payload.get("shopOrderId") or "")
    if sid and not sid.upper().startswith("ORD-"):
        return True

    return False


def _process_payout_callback(payload: dict, raw_text: str, remote_addr: str) -> dict:
    """
    Handle a payout callback from the merchant (createPaymentOrder result).
    ✅ On FAILURE → automatically refund the balance to the player.
    """
    shop_order_id = (
        payload.get("ShopOrderId")
        or payload.get("shopOrderId")
        or payload.get("PaymentOrderId")
    )
    if not shop_order_id:
        logger.warning("[PAYOUT-CB] no ShopOrderId in payout callback")
        return {"Success": False, "Message": "no ShopOrderId in payout callback",
                "MessageId": None}

    shop_order_id = str(shop_order_id)

    status_id = payload.get("PaymentOrderStatusId",
                            payload.get("paymentOrderStatusId"))
    failed_message = payload.get("FailedMessage") or payload.get("failedMessage") or ""
    tracking_number = payload.get("TrackingNumber") or payload.get("trackingNumber") or ""
    amount_from_cb = _extract_callback_order_amount(payload)

    log_event("payout_callback_received", payload, remote_addr)

    print("\n" + "=" * 78)
    print(f"💸 [PAYOUT CALLBACK] shop_order_id={shop_order_id}")
    print(f"                      status_id={status_id}")
    print(f"                      failed_message={failed_message!r}")
    print(f"                      tracking_number={tracking_number}")
    print(f"                      amount={amount_from_cb}")
    print("=" * 78 + "\n")

    payout_doc = find_payout_by_payment_order_id(shop_order_id)

    if not payout_doc:
        logger.warning(f"[PAYOUT-CB] no payout record found for {shop_order_id}")
        try:
            col_payouts.insert_one({
                "payment_order_id": shop_order_id,
                "status": "unknown_payout_callback",
                "raw_payload": payload,
                "created_at": datetime.now(timezone.utc),
            })
        except Exception:
            pass
        return {"Success": False,
                "Message": f"no payout record for {shop_order_id}",
                "MessageId": None}

    chat_id = payout_doc.get("chat_id")
    player_id = payout_doc.get("player_id")
    amount = payout_doc.get("amount")
    phone = payout_doc.get("phone") or "N/A"
    channel_name = payout_doc.get("channel_name") or "N/A"
    op_id = payout_doc.get("operation_id") or "N/A"

    already_callback = bool(payout_doc.get("callback_received"))
    already_notified = bool(payout_doc.get("callback_notified"))

    # Classify status
    try:
        sid_int = int(status_id) if status_id is not None else None
    except (TypeError, ValueError):
        sid_int = None

    is_paid = sid_int in PAYOUT_STATUS_PAID if sid_int is not None else False
    is_failed = sid_int in PAYOUT_STATUS_FAILED if sid_int is not None else False
    is_pending = sid_int in PAYOUT_STATUS_PENDING if sid_int is not None else False

    # If FailedMessage is present, treat as failure regardless of status
    if failed_message:
        is_failed = True
        is_paid = False

    final_status = "unknown"
    if is_paid:
        final_status = "paid_callback"
    elif is_failed:
        final_status = "failed_callback"
    elif is_pending:
        final_status = "pending_callback"

    # ================================================================
    # ✅ NEW: AUTO-REFUND ON FAILURE
    # ================================================================
    refund_result = None
    refund_ok = False
    refund_duplicate = False
    refund_msg = ""

    if is_failed:
        # Check if we've already refunded (idempotency in MongoDB)
        if _has_refund_been_done(shop_order_id):
            logger.info(f"[PAYOUT-CB] refund already done for {shop_order_id}")
            refund_ok = True
            refund_duplicate = True
            refund_msg = "refund already issued"
        else:
            # Reason for refund message
            reason_text = failed_message or "payout failed at merchant"
            print(f"♻️  [PAYOUT-CB] FAILED — initiating refund for player_id={player_id} amount={amount}")
            try:
                refund_result = refund_payout_to_player(
                    player_id=player_id,
                    amount=amount,
                    payment_order_id=shop_order_id,
                    chat_id=chat_id,
                    reason=reason_text,
                )
                refund_ok = bool(refund_result.get("success"))
                refund_duplicate = bool(refund_result.get("duplicate"))
                refund_msg = refund_result.get("message") or ""
            except Exception as e:
                logger.error(f"[PAYOUT-CB] refund exception: {e}")
                refund_result = {"success": False, "message": str(e),
                                 "duplicate": False, "message_id": None, "summa": None}
                refund_msg = str(e)

            print(
                f"♻️  [PAYOUT-CB] refund result: ok={refund_ok} dup={refund_duplicate} "
                f"msg={refund_msg!r}"
            )

    # Update payout record with callback data + refund info
    update_payout_callback(shop_order_id, {
        "callback_received": True,
        "callback_received_at": datetime.now(timezone.utc),
        "callback_status_id": sid_int,
        "callback_status_text": PAYMENT_ORDER_STATUS_BN.get(sid_int, "N/A"),
        "callback_failed_message": failed_message,
        "callback_tracking_number": tracking_number,
        "callback_payload": payload,
        "status": final_status,
        "refund_done": bool(refund_ok),
        "refund_at": datetime.now(timezone.utc) if refund_ok else None,
        "refund_message": refund_msg,
    })

    # ================================================================
    # ✅ Compose message for user
    # ================================================================
    if is_paid and not already_notified:
        text = (
            f"✅ <b>পেআউট সম্পন্ন হয়েছে!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📱 <b>প্রাপক নম্বর:</b> <code>{phone}</code>\n"
            f"🏦 <b>চ্যানেল:</b> {channel_name}\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{amount}</code> BDT\n"
            f"📦 <b>Payment Order:</b> <code>{shop_order_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🎉 টাকা আপনার নম্বরে পৌঁছে গেছে ✅\n"
            f"ধন্যবাদ আমাদের সেবা ব্যবহার করার জন্য 🙏"
        )

    elif is_failed and not already_notified:
        reason = translate_payment_order_error(failed_message) if failed_message else "পেমেন্ট চ্যানেল সমস্যা"

        # ✅ Refund info block
        if refund_ok:
            refund_block = (
                f"\n━━━━━━━━━━━━━━━━━\n"
                f"♻️ <b>রিফান্ড সম্পন্ন!</b>\n"
                f"➤ আপনার <b>{amount} BDT</b> খেলোয়াড় একাউন্টে ফেরত দেওয়া হয়েছে ✅\n"
                f"➤ কয়েক সেকেন্ডের মধ্যে ব্যালেন্সে দেখতে পাবেন।\n"
            )
        else:
            refund_block = (
                f"\n━━━━━━━━━━━━━━━━━\n"
                f"⚠️ <b>রিফান্ড প্রসেসিং সমস্যা</b>\n"
                f"➤ কারণ: <code>{refund_msg or 'unknown'}</code>\n"
                f"➤ অনুগ্রহ করে সাপোর্টে যোগাযোগ করুন: {SUPPORT_USERNAME}\n"
            )

        text = (
            f"❌ <b>পেআউট ব্যর্থ হয়েছে!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{player_id or 'N/A'}</code>\n"
            f"📱 <b>প্রাপক নম্বর:</b> <code>{phone}</code>\n"
            f"🏦 <b>চ্যানেল:</b> {channel_name}\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{amount}</code> BDT\n"
            f"🆔 <b>Payout Op ID:</b> <code>{op_id}</code>\n"
            f"📦 <b>Payment Order:</b> <code>{shop_order_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>কারণ:</b> {reason}\n"
            f"➤ <i>Raw: {failed_message or 'N/A'}</i>\n"
            f"{refund_block}\n"
            f"💡 <b>টিপস:</b> নম্বরটি চেক করে আবার চেষ্টা করুন।\n"
            f"📞 <b>সাপোর্ট:</b> {SUPPORT_USERNAME}"
        )

    elif is_pending:
        text = (
            f"⏳ <b>পেআউট পেন্ডিং</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{player_id or 'N/A'}</code>\n"
            f"📱 <b>প্রাপক নম্বর:</b> <code>{phone}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{amount}</code> BDT\n"
            f"📦 <b>Payment Order:</b> <code>{shop_order_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"অনুগ্রহ করে অপেক্ষা করুন... টাকা প্রসেস হচ্ছে।"
        )
    else:
        text = (
            f"ℹ️ <b>পেআউট আপডেট</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{player_id or 'N/A'}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{amount}</code> BDT\n"
            f"📦 <b>Payment Order:</b> <code>{shop_order_id}</code>\n"
            f"📊 <b>Status:</b> {PAYMENT_ORDER_STATUS_BN.get(sid_int, 'N/A')}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"বিস্তারিত জানতে সাপোর্টে যোগাযোগ করুন: {SUPPORT_USERNAME}"
        )

    if chat_id and not already_notified:
        _notify_user_via_telegram(chat_id, text)
        update_payout_callback(shop_order_id, {
            "callback_notified": True,
            "callback_notified_at": datetime.now(timezone.utc),
        })
    elif already_notified:
        print(f"[PAYOUT-CB] already notified user for {shop_order_id} — skipping notification")

    # ---- Return: always ACK the merchant ----
    return {
        "Success": True,
        "Message": f"payout callback processed: {final_status}"
                   + (f" + refund({'ok' if refund_ok else 'failed'})" if is_failed else ""),
        "MessageId": None,
    }


def _process_callback_payload(payload: dict, raw_text: str, remote_addr: str) -> dict:
    if not isinstance(payload, dict):
        logger.warning("[CALLBACK] payload is not dict; skipping credit logic")
        return {"Success": False, "Message": "payload not a dict", "MessageId": None}

    # ✅ Route: Payout vs Deposit
    if _is_payout_callback(payload):
        return _process_payout_callback(payload, raw_text, remote_addr)

    # ================================================================
    # Otherwise: Deposit callback
    # ================================================================
    shop_order_id = (
        payload.get("ShopOrderId")
        or payload.get("shopOrderId")
        or payload.get("shop_order_id")
    )
    if not shop_order_id:
        logger.warning("[CALLBACK] no ShopOrderId in payload; skipping credit logic")
        return {"Success": False, "Message": "no ShopOrderId", "MessageId": None}

    shop_order_id = str(shop_order_id)

    log_event("callback_received", payload, remote_addr)

    paid_amount = _extract_callback_paid_amount(payload)
    order_amount = _extract_callback_order_amount(payload)
    cb_trxid = _extract_callback_trxid(payload)

    # ---------- LAYER 1 ----------
    if is_order_processed(shop_order_id):
        logger.warning(f"[DUP-GUARD] ShopOrderId={shop_order_id} already credited; skipping")
        print(f"\n🚫 [DUP-GUARD] {shop_order_id} already credited — skipping\n")

        pending = peek_pending_deposit(shop_order_id)
        if pending and pending.get("chat_id") and not pending.get("notified"):
            mark_pending_notified(shop_order_id)
            disp_trxid = cb_trxid or pending.get("trxid") or "N/A"
            if _is_placeholder_trxid(disp_trxid):
                disp_trxid = "N/A"

            _notify_user_via_telegram(
                pending["chat_id"],
                f"✅ <b>ডিপোজিট সফল!</b> <i>(already credited)</i>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>প্লেয়ার আইডি:</b> <code>{pending.get('user_id')}</code>\n"
                f"💵 <b>অ্যামাউন্ট:</b> <code>{paid_amount or pending.get('amount')}</code> BDT\n"
                f"📦 <b>অর্ডার আইডি:</b> <code>{shop_order_id}</code>\n"
                f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{disp_trxid}</code>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ℹ️ এই ডিপোজিট আগেই সম্পন্ন হয়েছে।"
            )
            pop_pending_deposit(shop_order_id)

        log_transaction(
            shop_order_id, None, paid_amount, None, cb_trxid or None,
            status="duplicate", api_ok=False,
            api_message="already processed", order_amount=order_amount,
            extra={"dup_stage": "layer1", "callback_trxid": cb_trxid or None}
        )
        return {
            "Success": False,
            "Message": f"ShopOrderId {shop_order_id} already processed",
            "MessageId": 100337,
        }

    # ---------- LAYER 2 ----------
    pending = peek_pending_deposit(shop_order_id)
    if pending and pending.get("notified"):
        logger.info(f"[CALLBACK] {shop_order_id} pending already marked notified; skipping")
        return {"Success": False, "Message": "already processing", "MessageId": None}

    if not pending:
        extracted_player_id = extract_player_id_from_shop_order_id(shop_order_id)
        if extracted_player_id:
            logger.info(
                f"[CALLBACK] no pending deposit for {shop_order_id}; "
                f"extracted player_id={extracted_player_id} from ShopOrderId"
            )

            if paid_amount <= 0:
                logger.warning("[CALLBACK] paid amount is 0; skipping")
                return {"Success": False, "Message": "invalid amount", "MessageId": None}

            pending = {
                "chat_id": 0,
                "user_id": str(extracted_player_id),
                "name": "Player",
                "amount": order_amount or paid_amount,
                "wallet": "N/A",
                "trxid": cb_trxid or "N/A",
                "notified": False,
            }

            try:
                u = api_search_user(extracted_player_id)
                if isinstance(u, dict) and u.get("name"):
                    pending["name"] = u["name"]
                    upsert_user(extracted_player_id, name=u.get("name"),
                                currency_id=u.get("currencyId"))
            except Exception:
                pass
        else:
            logger.warning(
                f"[CALLBACK] no pending deposit and no player_id in ShopOrderId "
                f"({shop_order_id}); skipping"
            )
            return {"Success": False, "Message": "cannot extract player_id", "MessageId": None}

    user_id = str(pending.get("user_id") or "")
    name = pending.get("name") or "Guest User"
    chat_id = pending.get("chat_id")
    wallet = pending.get("wallet") or "N/A"

    pending_trxid = (pending.get("trxid") or "").strip()

    final_trxid = ""
    trxid_source = "none"

    if cb_trxid:
        final_trxid = cb_trxid
        trxid_source = "callback.MonitorTransferCode/TrackingNumber"
    elif not _is_placeholder_trxid(pending_trxid):
        final_trxid = pending_trxid
        trxid_source = "pending.trxid"
    else:
        final_trxid = "N/A"
        trxid_source = "fallback.N/A"

    pending_amount = safe_int(pending.get("amount") or 0)

    credit_amount = 0
    amount_source = "none"
    if paid_amount > 0:
        credit_amount = paid_amount
        amount_source = "callback.AmountPaid"
    elif pending_amount > 0:
        credit_amount = pending_amount
        amount_source = "pending.amount"
    elif order_amount > 0:
        credit_amount = order_amount
        amount_source = "callback.Amount"

    if credit_amount <= 0:
        logger.warning("[CALLBACK] no valid credit amount; skipping")
        return {"Success": False, "Message": "no credit amount", "MessageId": None}

    status_id = payload.get("OrderStatusId", payload.get("orderStatusId"))

    print("\n" + "-" * 78)
    print(f"🧠 [CREDIT ENGINE] shop_order_id={shop_order_id}")
    print(f"                    user_id={user_id}")
    print(f"                    pending_amount={pending_amount}")
    print(f"                    order_amount={order_amount}")
    print(f"                    callback_paid_amount={paid_amount}")
    print(f"                    ➜ CREDIT AMOUNT={credit_amount} (source={amount_source})")
    print(f"                    pending_trxid={pending_trxid!r}")
    print(f"                    callback_trxid={cb_trxid!r}")
    print(f"                    ➜ FINAL TRXID={final_trxid!r} (source={trxid_source})")
    print(f"                    status_id={status_id}")
    print("-" * 78)

    if pending_amount and paid_amount and pending_amount != paid_amount:
        print(
            f"⚠️  [AMOUNT-MISMATCH] pending={pending_amount} vs paid={paid_amount} "
            f"→ crediting paid amount {paid_amount}"
        )
        log_event("amount_mismatch", {
            "shop_order_id": shop_order_id,
            "pending_amount": pending_amount,
            "paid_amount": paid_amount,
            "order_amount": order_amount,
        }, remote_addr)

    try:
        if status_id is not None and int(status_id) not in (2, 1):
            logger.info(f"[CALLBACK] status_id={status_id} not a paid status; skipping")
            return {"Success": False, "Message": f"status_id={status_id}", "MessageId": None}
    except (TypeError, ValueError):
        pass

    mark_pending_notified(shop_order_id)

    newly_marked = mark_order_processed(
        shop_order_id,
        player_id=user_id,
        amount=credit_amount,
        extra={
            "wallet": wallet,
            "trxid": final_trxid,
            "pending_trxid": pending_trxid or None,
            "callback_trxid": cb_trxid or None,
            "trxid_source": trxid_source,
            "name": name,
            "chat_id": chat_id,
            "pending_amount": pending_amount,
            "order_amount": order_amount,
            "callback_paid_amount": paid_amount,
            "amount_source": amount_source,
        },
    )
    if not newly_marked:
        print(f"🚫 [DUP-GUARD] {shop_order_id} inserted concurrently — skipping credit")
        log_transaction(
            shop_order_id, user_id, credit_amount, wallet, final_trxid,
            status="duplicate", api_ok=False,
            api_message="concurrent duplicate", chat_id=chat_id, name=name,
            order_amount=order_amount,
            extra={"dup_stage": "atomic_insert"}
        )
        if chat_id and chat_id != 0:
            _notify_user_via_telegram(
                chat_id,
                f"✅ <b>ডিপোজিট সফল!</b> <i>(already credited)</i>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id}</code>\n"
                f"💵 <b>অ্যামাউন্ট:</b> <code>{credit_amount}</code> BDT\n"
                f"📦 <b>অর্ডার আইডি:</b> <code>{shop_order_id}</code>\n"
                f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{final_trxid}</code>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"ℹ️ এই ডিপোজিট আগেই সম্পন্ন হয়েছে।"
            )
        pop_pending_deposit(shop_order_id)
        return {
            "Success": False,
            "Message": f"ShopOrderId {shop_order_id} already processed (atomic)",
            "MessageId": 100337,
        }

    try:
        add_res = api_deposit_add(user_id, credit_amount)
    except Exception as e:
        add_res = {"success": False, "message": f"Exception: {e}"}

    add_ok = bool(add_res.get("success"))
    dup = bool(add_res.get("duplicate_guard"))
    withdrawal_blocked = bool(add_res.get("withdrawal_blocked"))
    add_msg = add_res.get("message") or ""
    add_summa = add_res.get("summa")
    msg_id = add_res.get("message_id")

    print(
        f"💰 [CREDIT ENGINE] add_ok={add_ok} dup={dup} blocked={withdrawal_blocked} "
        f"msg_id={msg_id} msg={add_msg}"
    )

    if add_ok:
        txn_status = "success"
    elif dup:
        txn_status = "duplicate"
    elif withdrawal_blocked:
        txn_status = "blocked"
    else:
        txn_status = "failed"

    log_transaction(
        shop_order_id, user_id, credit_amount, wallet, final_trxid,
        status=txn_status, api_ok=add_ok,
        api_message=add_msg, api_message_id=msg_id,
        chat_id=chat_id, name=name,
        order_amount=order_amount,
        extra={
            "api_summa": add_summa,
            "withdrawal_blocked": withdrawal_blocked,
            "amount_source": amount_source,
            "callback_paid_amount": paid_amount,
            "callback_trxid": cb_trxid or None,
            "pending_trxid": pending_trxid or None,
            "trxid_source": trxid_source,
        },
    )

    upsert_user(user_id, name=name)

    def _esc(s):
        return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    user_id_h = _esc(user_id)
    name_h = _esc(name)
    wallet_h = _esc(wallet)
    trxid_h = _esc(final_trxid)
    order_id_h = _esc(shop_order_id)
    add_msg_h = _esc(add_msg)

    display_amount = credit_amount

    if add_ok:
        final_text = (
            f"✅ <b>ডিপোজিট সফল!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id_h}</code>\n"
            f"📝 <b>নাম:</b> {name_h}\n"
            f"💳 <b>মেথড:</b> {wallet_h}\n"
            f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{trxid_h}</code>\n"
            f"📦 <b>অর্ডার আইডি:</b> <code>{order_id_h}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{display_amount}</code> BDT\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"⏱️ ফান্ড অ্যাড হয়ে গেছে ✅"
        )
    elif dup:
        final_text = (
            f"✅ <b>ডিপোজিট সফল!</b> <i>(already credited)</i>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id_h}</code>\n"
            f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{trxid_h}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{display_amount}</code> BDT\n"
            f"📦 <b>অর্ডার আইডি:</b> <code>{order_id_h}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"ℹ️ এই ডিপোজিট আগেই অ্যাড হয়েছে।"
        )
    elif withdrawal_blocked:
        final_text = (
            f"⚠️ <b>ডিপোজিট এখন করা যাচ্ছে না!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id_h}</code>\n"
            f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{trxid_h}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{display_amount}</code> BDT\n"
            f"📦 <b>অর্ডার আইডি:</b> <code>{order_id_h}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>কারণ:</b> আপনার একাউন্টে কিছু কনফার্মড উইথড্র রিকোয়েস্ট বাকি আছে।\n\n"
            f"💡 <b>সমাধান:</b>\n"
            f"১️⃣ 1xBet একাউন্টে লগইন করুন\n"
            f"২️⃣ উইথড্র রিকোয়েস্ট সম্পূর্ণ / ক্যান্সেল করুন\n"
            f"৩️⃣ তারপর আবার ডিপোজিট করুন\n\n"
            f"📞 সহায়তার জন্য যোগাযোগ করুন: {SUPPORT_USERNAME}"
        )
    else:
        final_text = (
            f"❌ <b>ফান্ড অ্যাড ব্যর্থ!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id_h}</code>\n"
            f"🆔 <b>ট্রানজেকশন আইডি:</b> <code>{trxid_h}</code>\n"
            f"💵 <b>অ্যামাউন্ট:</b> <code>{display_amount}</code> BDT\n"
            f"📦 <b>অর্ডার আইডি:</b> <code>{order_id_h}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"➤ কারণ: <code>{add_msg_h or 'Unknown error'}</code>\n\n"
            f"📞 সাপোর্টে যোগাযোগ করুন ({SUPPORT_USERNAME})।"
        )

    if chat_id and chat_id != 0:
        _notify_user_via_telegram(chat_id, final_text)

    pop_pending_deposit(shop_order_id)

    if add_ok:
        return {"Success": True, "Message": "Success", "MessageId": None}
    elif dup:
        return {"Success": False, "Message": add_msg or "duplicate", "MessageId": msg_id or 100337}
    elif withdrawal_blocked:
        return {"Success": False, "Message": add_msg or "withdrawal blocked", "MessageId": msg_id or 100331}
    else:
        return {"Success": False, "Message": add_msg or "failed", "MessageId": msg_id}


@flask_app.route(CALLBACK_PATH, methods=["POST", "GET"])
def merchant_callback():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "=" * 78)
    print(f"📩 [CALLBACK RECEIVED] {ts} UTC")
    print("=" * 78)
    print(f"Method        : {request.method}")
    print(f"Remote Addr   : {request.remote_addr}")
    print(f"Full Path     : {request.full_path}")
    print(f"URL           : {request.url}")
    print(f"User-Agent    : {request.headers.get('User-Agent', '?')}")

    print("\n--- Headers ---")
    for k, v in request.headers.items():
        print(f"  {k}: {v}")

    print("\n--- Query Params ---")
    if request.args:
        for k, v in request.args.items():
            print(f"  {k} = {v}")
    else:
        print("  (none)")

    print("\n--- Form Data ---")
    if request.form:
        for k, v in request.form.items():
            print(f"  {k} = {v}")
    else:
        print("  (none)")

    print("\n--- Raw Body ---")
    try:
        raw = request.get_data(as_text=True)
        print(raw if raw else "(empty)")
    except Exception as e:
        raw = ""
        print(f"(error reading body: {e})")

    parsed_json = None
    try:
        parsed_json = request.get_json(silent=True)
    except Exception:
        parsed_json = None

    print("\n--- Parsed JSON (if any) ---")
    if parsed_json is not None:
        print(format_json(parsed_json))
    else:
        print("  (not JSON or empty)")

    if parsed_json is None and raw:
        try:
            parsed_json = json.loads(raw)
            print("\n--- Parsed JSON (from raw) ---")
            print(format_json(parsed_json))
        except Exception:
            pass

    print("=" * 78 + "\n")

    logger.info(
        f"[CALLBACK] {request.method} {request.full_path} "
        f"from {request.remote_addr} ua={request.headers.get('User-Agent','?')} body={raw[:300]}"
    )

    try:
        result = _process_callback_payload(parsed_json, raw, request.remote_addr)
    except Exception as e:
        logger.error(f"[CALLBACK] credit processing failed: {e}")
        log_event("callback_error", {"error": str(e), "payload": parsed_json}, request.remote_addr)
        result = {"Success": False, "Message": f"internal error: {e}", "MessageId": None}

    if not isinstance(result, dict):
        result = {"Success": False, "Message": "unknown result", "MessageId": None}

    return jsonify({
        "Success": bool(result.get("Success", False)),
        "Message": str(result.get("Message") or ""),
        "MessageId": result.get("MessageId"),
    }), 200


@flask_app.route("/api/debug/register", methods=["POST"])
def debug_register_pending():
    data = request.get_json(silent=True) or {}
    shop_order_id = data.get("ShopOrderId")
    chat_id = data.get("ChatId")
    user_id = data.get("UserId")
    name = data.get("Name", "Guest User")
    amount = data.get("Amount")
    wallet = data.get("Wallet", "বিকাশ")
    trxid = data.get("TrxId", "TEST")

    if not shop_order_id or not chat_id or not user_id or not amount:
        return jsonify({
            "Success": False,
            "Message": "ShopOrderId, ChatId, UserId, and Amount are required"
        }), 400

    try:
        amount = int(amount)
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return jsonify({"Success": False, "Message": "Amount and ChatId must be numbers"}), 400

    register_pending_deposit(
        shop_order_id=str(shop_order_id),
        chat_id=chat_id,
        user_id=str(user_id),
        name=str(name),
        amount=amount,
        wallet=str(wallet),
        trxid=str(trxid),
    )

    return jsonify({
        "Success": True,
        "ShopOrderId": shop_order_id,
        "Message": "Pending deposit registered"
    }), 200


@flask_app.route("/api/debug/pending", methods=["GET"])
def debug_list_pending():
    try:
        docs = list(col_pending.find({}, {"_id": 0}))
        for d in docs:
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
            if isinstance(d.get("updated_at"), datetime):
                d["updated_at"] = d["updated_at"].isoformat()
        return jsonify({"count": len(docs), "pending": docs}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/pending/clear", methods=["POST"])
def debug_clear_pending():
    try:
        r = col_pending.delete_many({})
        return jsonify({"Success": True, "Cleared": r.deleted_count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/processed", methods=["GET"])
def debug_list_processed():
    try:
        docs = list(col_processed.find({}, {"_id": 0}).sort("created_at", DESCENDING).limit(500))
        for d in docs:
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
        return jsonify({"count": len(docs), "processed": docs}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/processed/clear", methods=["POST"])
def debug_clear_processed():
    try:
        r = col_processed.delete_many({})
        with processed_orders_lock:
            processed_orders.clear()
        return jsonify({"Success": True, "Cleared": r.deleted_count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/check/<shop_order_id>", methods=["GET"])
def debug_check_order(shop_order_id):
    try:
        p = col_processed.find_one({"shop_order_id": shop_order_id}, {"_id": 0})
        t = col_txns.find_one({"shop_order_id": shop_order_id}, {"_id": 0})
        po = col_payouts.find_one({"payment_order_id": shop_order_id}, {"_id": 0})
        rf = col_refunds.find_one({"payment_order_id": shop_order_id}, {"_id": 0})
        for d in (p, t, po, rf):
            if d:
                for k, v in list(d.items()):
                    if isinstance(v, datetime):
                        d[k] = v.isoformat()
        return jsonify({"processed": p, "transaction": t, "payout": po, "refund": rf}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/payouts", methods=["GET"])
def debug_list_payouts():
    try:
        docs = list(col_payouts.find({}, {"_id": 0}).sort("created_at", DESCENDING).limit(200))
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
        return jsonify({"count": len(docs), "payouts": docs}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/refunds", methods=["GET"])
def debug_list_refunds():
    try:
        docs = list(col_refunds.find({}, {"_id": 0}).sort("created_at", DESCENDING).limit(200))
        for d in docs:
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
        return jsonify({"count": len(docs), "refunds": docs}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/debug/stats", methods=["GET"])
def debug_stats():
    try:
        return jsonify({
            "processed_orders": col_processed.count_documents({}),
            "pending_deposits": col_pending.count_documents({}),
            "users": col_users.count_documents({}),
            "transactions": col_txns.count_documents({}),
            "success_txns": col_txns.count_documents({"status": "success"}),
            "duplicate_txns": col_txns.count_documents({"status": "duplicate"}),
            "failed_txns": col_txns.count_documents({"status": "failed"}),
            "blocked_txns": col_txns.count_documents({"status": "blocked"}),
            "payouts": col_payouts.count_documents({}),
            "refunds": col_refunds.count_documents({}),
            "refund_txns": col_txns.count_documents({"status": "refund_success"}),
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/", methods=["GET"])
def _health():
    try:
        pc = col_processed.count_documents({})
        pd = col_pending.count_documents({})
    except Exception:
        pc, pd = -1, -1
    return jsonify({
        "status": "ok",
        "callback": CALLBACK_PATH,
        "processed_orders": pc,
        "pending_deposits": pd,
        "mongodb": MONGO_DB_NAME,
    }), 200


def start_flask_in_background():
    def _run():
        try:
            print(f"🌐 Callback server listening on http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}")
            flask_app.run(
                host=CALLBACK_HOST,
                port=CALLBACK_PORT,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        except Exception as e:
            logger.error(f"[CALLBACK] Flask server failed: {e}")

    t = threading.Thread(target=_run, name="callback-http", daemon=True)
    t.start()
    return t


# --- 3. API FUNCTIONS ---

def api_balance():
    dt = datetime.now(timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
    confirm = get_confirm(CASHDESK_ID)

    sha_part = sha256(f"hash={HASH_KEY}&cashdeskid={CASHDESK_ID}&dt={dt}")
    md5_part = md5(f"dt={dt}&cashierpass={CASHIER_PASS}&cashdeskid={CASHDESK_ID}")
    sign = get_sign(sha_part, md5_part)

    dt_enc = quote(dt, safe=".")
    url = f"{API_BASE}Cashdesk/{CASHDESK_ID}/Balance?dt={dt_enc}&confirm={confirm}"

    try:
        r = requests.get(
            url,
            headers={"sign": sign, "Sign": sign, "accept": "application/json"},
            timeout=10,
        )
        logger.info(f"[BALANCE] URL: {url}")
        logger.info(f"[BALANCE] Status: {r.status_code}  Body: {r.text[:400]}")

        if r.status_code == 401:
            return {"error": "auth_error", "details": "401 Unauthorized on Balance."}
        if r.status_code == 403:
            return {"error": "forbidden", "details": "403 Forbidden"}
        if r.status_code != 200:
            return {"error": "api_error", "details": f"HTTP {r.status_code}: {r.text}"}

        data = r.json()
        return {
            "Balance": data.get("Balance", data.get("balance")),
            "Limit": data.get("Limit", data.get("limit")),
        }
    except requests.exceptions.RequestException as e:
        return {"error": "network_error", "details": str(e)}
    except Exception as e:
        return {"error": "unexpected", "details": str(e)}


def api_deposit_add(user_id, amount):
    user_id = str(user_id).strip()
    amount = int(amount)

    confirm = get_confirm(user_id)
    sha_part = sha256(f"hash={HASH_KEY}&lng=ru&userid={user_id}")
    md5_part = md5(f"summa={amount}&cashierpass={CASHIER_PASS}&cashdeskid={CASHDESK_ID}")
    sign = get_sign(sha_part, md5_part)

    url = f"{API_BASE}Deposit/{user_id}/Add"
    body = {
        "cashdeskid": int(CASHDESK_ID),
        "lng": "ru",
        "summa": amount,
        "confirm": confirm,
    }

    print("\n" + "=" * 78)
    print("💰 [DEPOSIT ADD → 1xBet]")
    print("=" * 78)
    print(f"URL   : {url}")
    print(f"Body  : {format_json(body)}")
    print(f"Sign  : {sign}")
    print("-" * 78)

    try:
        r = requests.post(
            url,
            json=body,
            headers={
                "sign": sign,
                "Sign": sign,
                "accept": "application/json",
                "content-type": "application/json",
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"[ADD] Network error: {e}")
        print(f"❌ Network error: {e}")
        print("=" * 78 + "\n")
        return {"success": False, "message": f"Network error: {e}", "http_status": 0}
    except Exception as e:
        logger.error(f"[ADD] Unexpected: {e}")
        print(f"❌ Unexpected: {e}")
        print("=" * 78 + "\n")
        return {"success": False, "message": f"Unexpected: {e}", "http_status": 0}

    print(f"📥 HTTP {r.status_code}")
    print(f"Body: {r.text[:600]}")
    print("=" * 78 + "\n")

    logger.info(f"[ADD] URL: {url}")
    logger.info(f"[ADD] Body: {format_json(body)}")
    logger.info(f"[ADD] Status: {r.status_code}  Body: {r.text[:400]}")

    try:
        data = r.json()
    except Exception:
        return {"success": False,
                "message": f"HTTP {r.status_code}: {r.text}",
                "http_status": r.status_code}

    if not isinstance(data, dict):
        return {"success": False,
                "message": f"HTTP {r.status_code}: {format_json(data)}",
                "http_status": r.status_code, "raw": data}

    success = bool(data.get("success", data.get("Success", False)))
    summa = data.get("summa", data.get("Summa"))
    message = data.get("message") or data.get("Message") or ""
    message_id = data.get("messageId", data.get("MessageId"))

    duplicate_guard = False
    withdrawal_blocked = False
    if not success:
        if isinstance(message, str):
            if "уже был проведен" in message or message_id == 100337:
                duplicate_guard = True
        if message_id == 100331:
            withdrawal_blocked = True
        elif isinstance(message, str):
            if "подтвержденные запросы на вывод" in message or "пополнение невозможно" in message:
                withdrawal_blocked = True

    return {
        "success": success,
        "summa": summa,
        "message": message,
        "message_id": message_id,
        "duplicate_guard": duplicate_guard,
        "withdrawal_blocked": withdrawal_blocked,
        "http_status": r.status_code,
        "raw": data,
    }


def api_search_user(user_id):
    confirm = get_confirm(user_id)
    sha = sha256(f"hash={HASH_KEY}&userid={user_id}&cashdeskid={CASHDESK_ID}")
    md5_part = md5(f"userid={user_id}&cashierpass={CASHIER_PASS}&hash={HASH_KEY}")
    sign = get_sign(sha, md5_part)

    url = f"{API_BASE}Users/{user_id}"
    try:
        r = requests.get(
            url,
            params={"confirm": confirm, "cashdeskid": CASHDESK_ID},
            headers={"sign": sign, "Sign": sign, "accept": "application/json"},
            timeout=10,
        )
        logger.info(f"[USER] Status: {r.status_code} Body: {r.text[:300]}")
        if r.status_code != 200:
            return {"error": f"API Error Code: {r.status_code}", "details": r.text}
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": "Network Connection Error", "details": str(e)}
    except Exception as e:
        return {"error": "Unexpected System Exception", "details": str(e)}


def api_verify_player(user_id):
    user_id = str(user_id).strip()
    if not user_id.isdigit() or int(user_id) <= 0:
        return {"valid": False, "reason": "invalid_format"}

    try:
        confirm = get_confirm(user_id)
        sha = sha256(f"hash={HASH_KEY}&userid={user_id}&cashdeskid={CASHDESK_ID}")
        md5_part = md5(f"userid={user_id}&cashierpass={CASHIER_PASS}&hash={HASH_KEY}")
        sign = get_sign(sha, md5_part)

        r = requests.get(
            f"{API_BASE}Users/{user_id}",
            params={"confirm": confirm, "cashdeskid": CASHDESK_ID},
            headers={"sign": sign, "Sign": sign, "accept": "application/json"},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return {"valid": False, "reason": "network_error", "details": str(e)}
    except Exception as e:
        return {"valid": False, "reason": "api_error", "details": str(e)}

    if r.status_code in (401, 403):
        return {"valid": False, "reason": "auth_error", "details": f"HTTP {r.status_code}: {r.text}"}
    if r.status_code == 404:
        return {"valid": False, "reason": "not_found"}
    if r.status_code != 200:
        return {"valid": False, "reason": "api_error", "details": f"HTTP {r.status_code}: {r.text}"}

    try:
        data = r.json()
    except Exception:
        return {"valid": False, "reason": "api_error", "details": f"Invalid JSON: {r.text}"}

    if not isinstance(data, dict):
        return {"valid": False, "reason": "not_found"}

    returned_id = data.get("userId", data.get("UserId"))
    name = data.get("name", data.get("Name"))
    currency_id = data.get("currencyId", data.get("CurrencyId"))

    try:
        returned_id_int = int(returned_id) if returned_id is not None else 0
    except (TypeError, ValueError):
        returned_id_int = 0

    if returned_id_int <= 0 or str(returned_id_int) != str(int(user_id)):
        return {"valid": False, "reason": "not_found"}

    if EXPECTED_CURRENCY_ID is not None and currency_id != EXPECTED_CURRENCY_ID:
        return {"valid": False, "reason": "currency_mismatch", "details": f"currencyId={currency_id}"}

    upsert_user(returned_id_int, name=(name or "").strip() or None, currency_id=currency_id)

    return {
        "valid": True,
        "user_id": str(returned_id_int),
        "name": (name or "").strip() or "Guest User",
        "currency_id": currency_id,
    }


def verify_error_message(result):
    reason = result.get("reason")
    if reason == "invalid_format":
        return "❌ **প্লেয়ার আইডি সঠিক নয়!**"
    if reason == "not_found":
        return "❌ **এই প্লেয়ার আইডি খুঁজে পাওয়া যায়নি!**"
    if reason == "currency_mismatch":
        return "❌ **এই একাউন্টের কারেন্সি সমর্থিত নয়!**"
    if reason == "auth_error":
        return "⚠️ **ভেরিফিকেশন সিস্টেমে সমস্যা হয়েছে। সাপোর্টে যোগাযোগ করুন।**"
    return "⚠️ **প্লেয়ার আইডি ভেরিফাই করা সম্ভব হয়নি।**"


async def verify_player_async(user_id):
    return await asyncio.to_thread(api_verify_player, user_id)


def api_create_order(payer_key, amount=1000, channel_id=35):
    shop_order_id = make_shop_order_id(payer_key)

    payload = {
        "Amount": int(amount),
        "CurrencyId": 11,
        "IsTest": "false",
        "PayerKey": str(payer_key).strip(),
        "PaymentChannelId": int(channel_id),
        "ShopInformUrl": MERCHANT_CALLBACK_URL.strip(),
        "ShopOrderId": str(shop_order_id),
        "ShopReturnUrl": MERCHANT_CALLBACK_URL.strip(),
        "ShopUserLongId": SHOP_USER_LONG_ID.strip(),
    }
    payload["EncryptValue"] = generate_encrypt_value(payload, MERCHANT_HASH_KEY)
    headers = {"accept": "application/json", "content-type": "application/json"}

    print("\n" + "=" * 78)
    print("💳 [CREATE ORDER]")
    print("=" * 78)
    print(f"URL            : {ORDER_API_URL}")
    print(f"ShopOrderId    : {shop_order_id}")
    print(f"ShopInformUrl  : {MERCHANT_CALLBACK_URL}")
    print(f"Body           : {format_json(payload)}")
    print("-" * 78)

    try:
        response = requests.post(ORDER_API_URL, json=payload, headers=headers, timeout=15)
        try:
            res_json = response.json()
        except Exception:
            return {"Success": False,
                    "error_message": f"HTTP {response.status_code}\nRaw: {response.text}"}

        print(f"📥 HTTP {response.status_code}  Body: {response.text[:500]}")
        print("=" * 78 + "\n")

        if response.status_code == 200 and res_json.get("Success") is True:
            res_json["ShopOrderId"] = shop_order_id
            return res_json
        error_msg = res_json.get("ErrorMessage", "")
        if error_msg == "PairingFailed" or "PairingFailed" in str(res_json):
            return {"Success": False, "pairing_failed": True,
                    "error_message": "Wallets unavailable right now."}
        return {"Success": False, "pairing_failed": False,
                "error_message": f"HTTP {response.status_code}\n{format_json(res_json)}"}
    except requests.exceptions.RequestException as req_err:
        return {"Success": False, "error_message": f"Network: {req_err}"}
    except Exception as e:
        return {"Success": False, "error_message": f"Unexpected: {e}"}


def api_submit_transfer_code(shop_order_id, transfer_code, file_info=None):
    payload = {
        "ShopOrderId": str(shop_order_id),
        "ShopUserLongId": SHOP_USER_LONG_ID.strip(),
        "TransferCode": str(transfer_code).strip(),
    }
    if file_info:
        payload["File"] = file_info
    payload["EncryptValue"] = generate_encrypt_value(payload, MERCHANT_HASH_KEY)
    headers = {"accept": "application/json", "content-type": "application/json"}
    try:
        response = requests.post(INQUIRY_ORDER_API_URL, json=payload,
                                 headers=headers, timeout=15)
        try:
            res_json = response.json()
        except Exception:
            return ({"Success": False,
                     "ErrorMessage": f"Invalid JSON (HTTP {response.status_code}): {response.text}",
                     "RawResponse": response.text}, payload)
        return res_json, payload
    except Exception as e:
        return {"Success": False, "ErrorMessage": f"Network error: {str(e)}"}, payload


def parse_inquiry_response(res_json):
    is_success = res_json.get("Success", False)
    if not is_success:
        err_msg = res_json.get("ErrorMessage", "Unknown Error")
        error_map = {
            "CheckIpAddressFailed": "IP check failed",
            "CheckEncryptValueFailed": "Encryption check failed",
            "DevError": "System error",
            "NoOrder": "Order does not exist",
            "OrderAlreadySuccess": "Order already successful",
            "NeedFileOrTransferCode": "Transaction ID or receipt required",
        }
        return False, f"❌ **Failed:** {error_map.get(err_msg, err_msg)}", None

    success_result = res_json.get("SuccessOrderResult")
    if success_result is None:
        return False, "❌ **এই ট্রানজেকশন আইডিটি ইতিমধ্যে ব্যবহার করা হয়েছে!**", "ThisTransferCodeAlreadySuccessOrder"

    content = success_result.get("Content", "")
    if content == "SuccessOrder":
        tn = success_result.get("OrderTrackingNumber", "N/A")
        return True, f"🎉 **ডিপোজিট সফল!** ট্র্যাকিং: `{tn}`", content
    elif content == "MakeUpOrder":
        rm = success_result.get("MakeUpOrderResultMessage", "")
        oa = success_result.get("OrderAmount", 0)
        ra = success_result.get("ReceivedAmount", 0)
        if rm == "Success":
            return True, f"✅ **MakeUp সফল!** Order {oa} | Recv {ra}", content
        return False, f"⚠️ **ব্যালেন্স গরমিল:** {oa} vs {ra}", content
    elif content == "PleaseMakeUpOrderManually":
        return False, "⚠️ **টাকার পরিমাণ মিলছে না!**", content
    elif content == "OrderAlreadySuccess":
        return True, "✅ **অর্ডার আগেই সফল!**", content
    elif content == "ThisTransferCodeAlreadySuccessOrder":
        return False, "❌ **ট্রানজেকশন আইডি ব্যবহৃত!**", content
    elif content == "ThisTransferCodeIsNotYourOrder":
        return False, "❌ **ট্রানজেকশন আইডি ব্যবহৃত।**", content
    elif content == "NoOrder":
        return False, "❌ **কোনো অর্ডার নেই!**", content
    elif content == "TransferCodeNotExists":
        return False, (
            "❌ **ট্রানজেকশন নম্বরটি সঠিক নয়!**\n\n"
            "দয়া করে সঠিক ট্রানজেকশন আইডি দিয়ে আবার চেষ্টা করুন।"
        ), content
    elif content == "OrderAlreadyMakeUp":
        return False, "⚠️ **ম্যানুয়াল পেমেন্ট হয়েছে।**", content
    elif content == "OrderStatusError":
        return False, "❌ **অর্ডার স্ট্যাটাস এরর!**", content
    return False, "⚠ **প্রসেস হয়নি।**", content


def api_payout(user_id, code):
    user_id = str(user_id).strip()
    code = str(code).strip()

    confirm = md5(f"{user_id}:{HASH_KEY}")

    step1_string = f"hash={HASH_KEY}&lng=ru&userid={user_id}"
    step1 = sha256(step1_string)

    step2_string = f"code={code}&cashierpass={CASHIER_PASS}&cashdeskid={CASHDESK_ID}"
    step2 = md5(step2_string)

    final_signature = sha256(step1 + step2)

    url = f"{API_BASE}Deposit/{user_id}/Payout"
    body = {
        "cashdeskId": int(CASHDESK_ID),
        "lng": "ru",
        "code": code,
        "confirm": confirm,
    }

    print("\n" + "=" * 78)
    print("💸 [PAYOUT REQUEST]")
    print("=" * 78)
    print(f"URL        : {url}")
    print(f"Body       : {format_json(body)}")
    print("-" * 78)

    try:
        r = requests.post(
            url,
            json=body,
            headers={
                "sign": final_signature,
                "Sign": final_signature,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"[PAYOUT] Network error: {e}")
        print(f"❌ [PAYOUT] Network error: {e}")
        print("=" * 78 + "\n")
        return {"success": False, "message": f"Network error: {e}", "http_status": 0}
    except Exception as e:
        logger.error(f"[PAYOUT] Unexpected: {e}")
        print(f"❌ [PAYOUT] Unexpected: {e}")
        print("=" * 78 + "\n")
        return {"success": False, "message": f"Unexpected: {e}", "http_status": 0}

    print(f"📥 [PAYOUT RESPONSE]")
    print(f"HTTP Status: {r.status_code}")
    print(f"Raw Body   : {r.text}")
    print("=" * 78 + "\n")

    logger.info(f"[PAYOUT] URL: {url}")
    logger.info(f"[PAYOUT] Body: {format_json(body)}")
    logger.info(f"[PAYOUT] Status: {r.status_code}  Body: {r.text[:400]}")

    try:
        data = r.json()
    except Exception:
        return {"success": False,
                "message": f"HTTP {r.status_code}: {r.text}",
                "http_status": r.status_code,
                "raw": None}

    if not isinstance(data, dict):
        return {"success": False,
                "message": f"HTTP {r.status_code}: {format_json(data)}",
                "http_status": r.status_code,
                "raw": data}

    api_success = bool(data.get("success", data.get("Success", False)))
    api_summa = data.get("summa", data.get("Summa"))
    message = data.get("message") or data.get("Message") or ""
    message_id = data.get("messageId", data.get("MessageId"))
    operation_id = data.get("OperationId", data.get("operationId"))

    try:
        summa_float = float(api_summa) if api_summa is not None else None
    except (TypeError, ValueError):
        summa_float = None

    valid_payout = api_success and (summa_float is not None and summa_float < 0)
    paid_out_amount = abs(summa_float) if valid_payout else None

    if api_success and summa_float is not None and summa_float >= 0:
        error_message = (
            f"Invalid payout amount: {summa_float}. "
            f"Expected negative value for withdrawal."
        )
    elif not api_success and message:
        error_message = message
    else:
        error_message = message or "CashDeskBot rejected payout"

    return {
        "success": valid_payout,
        "api_success": api_success,
        "summa": summa_float,
        "paid_out_amount": paid_out_amount,
        "message": error_message,
        "message_id": message_id,
        "operation_id": operation_id,
        "http_status": r.status_code,
        "raw": data,
    }


def api_create_payment_order(amount, channel_id, payee_name=None,
                             payee_account=None, payee_phone=None,
                             shop_order_id=None):
    if not shop_order_id:
        rand4 = "".join(random.choices("0123456789abcdef", k=4))
        shop_order_id = f"{int(time.time())}-{rand4}"

    payload = {
        "Amount": int(amount),
        "CurrencyId": 11,
        "IsTest": False,
        "PayeeAccountName": str(payee_name or DEFAULT_PAYEE_ACCOUNT_NAME),
        "PayeeAccountNumber": str(payee_account or "01700000000"),
        "PayeePhoneNumber": str(payee_phone or DEFAULT_PAYEE_PHONE_NUMBER),
        "PaymentChannelId": int(channel_id),
        "ShopInformUrl": MERCHANT_CALLBACK_URL.strip(),
        "ShopOrderId": str(shop_order_id),
        "ShopUserLongId": SHOP_USER_LONG_ID.strip(),
    }

    payload["EncryptValue"] = generate_encrypt_value(payload, MERCHANT_HASH_KEY)
    json_payload = php_json_encode(payload)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    print("\n" + "=" * 78)
    print(f"💳 [CREATE PAYMENT ORDER] channel={channel_id}")
    print("=" * 78)
    print(f"URL            : {PAYMENT_ORDER_API_URL}")
    print(f"ShopUserLongId : {SHOP_USER_LONG_ID.strip()}")
    print(f"HashKey used   : {'*' * 12}{MERCHANT_HASH_KEY[-6:]}")
    print(f"Body (json)    : {json_payload}")
    print("-" * 78)

    try:
        response = requests.post(
            PAYMENT_ORDER_API_URL,
            data=json_payload.encode("utf-8"),
            headers=headers,
            timeout=20,
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"[PAYMENT_ORDER ch={channel_id}] Network error: {e}")
        print(f"❌ Network error: {e}")
        print("=" * 78 + "\n")
        return {
            "Success": False,
            "channel_id": channel_id,
            "error_message": f"Network error: {e}",
            "http_status": 0,
            "shop_order_id": shop_order_id,
        }
    except Exception as e:
        logger.error(f"[PAYMENT_ORDER ch={channel_id}] Unexpected: {e}")
        print(f"❌ Unexpected: {e}")
        print("=" * 78 + "\n")
        return {
            "Success": False,
            "channel_id": channel_id,
            "error_message": f"Unexpected: {e}",
            "http_status": 0,
            "shop_order_id": shop_order_id,
        }

    print(f"📥 Response HTTP {response.status_code}")
    print(f"Raw: {response.text[:800]}")
    print("=" * 78 + "\n")

    logger.info(
        f"[PAYMENT_ORDER ch={channel_id}] Status: {response.status_code} Body: {response.text[:400]}"
    )

    try:
        res_json = response.json()
    except Exception:
        return {
            "Success": False,
            "channel_id": channel_id,
            "error_message": f"Invalid JSON (HTTP {response.status_code}): {response.text}",
            "http_status": response.status_code,
            "shop_order_id": shop_order_id,
        }

    if response.status_code == 200 and isinstance(res_json, dict) and res_json.get("Success") is True:
        res_json["ShopOrderId"] = shop_order_id
        res_json["channel_id"] = channel_id
        return res_json

    err_msg = ""
    if isinstance(res_json, dict):
        err_msg = res_json.get("ErrorMessage") or res_json.get("error_message") or ""
    if not err_msg:
        err_msg = f"HTTP {response.status_code}: {response.text[:300]}"

    return {
        "Success": False,
        "channel_id": channel_id,
        "error_message": err_msg,
        "raw": res_json,
        "http_status": response.status_code,
        "shop_order_id": shop_order_id,
    }


def api_create_payment_order_with_fallback(amount, payee_phone=None,
                                           payee_name=None, remark=None):
    attempts = []
    for ch_id, ch_name, _ in WITHDRAW_CHANNELS:
        print(f"\n🔁 Trying withdrawal channel: {ch_name} (id={ch_id})")
        res = api_create_payment_order(
            amount,
            ch_id,
            payee_name=payee_name,
            payee_phone=payee_phone,
            payee_account=payee_phone,
        )
        attempts.append({
            "channel_id": ch_id,
            "channel_name": ch_name,
            "success": bool(res.get("Success")),
            "raw": res,
        })
        if res.get("Success"):
            res["attempts"] = attempts
            res["channel_name"] = ch_name
            return res

    last = attempts[-1]["raw"] if attempts else {}
    last["attempts"] = attempts
    last["channel_name"] = attempts[-1]["channel_name"] if attempts else "N/A"
    last["Success"] = False
    return last


# --- 4. KEYBOARDS ---
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📥 Deposit"), KeyboardButton("📤 Withdraw")],
        [KeyboardButton("🎁 Promo Code"), KeyboardButton("💬 Support")],
        [KeyboardButton("⚙️ Settings")],
    ], resize_keyboard=True)


def get_settings_main_keyboard(is_admin=False):
    kb = [
        [InlineKeyboardButton("🎮 1xBet ID", callback_data="set_1xbet_id")],
    ]
    if is_admin:
        kb.append([
            InlineKeyboardButton("💰 Check Balance", callback_data="check_balance"),
            InlineKeyboardButton("🔍 Find Player", callback_data="find_player"),
        ])
    return InlineKeyboardMarkup(kb)


def get_saved_ids_keyboard(saved_ids):
    kb = []
    for pid in saved_ids:
        kb.append([InlineKeyboardButton(f"{pid}", callback_data=f"select_saved_id_{pid}"),
                   InlineKeyboardButton("🗑", callback_data=f"del_saved_id_{pid}")])
    kb.append([InlineKeyboardButton("➕ নতুন প্লেয়ার একাউন্ট সেভ করুন",
                                    callback_data="add_new_player_id")])
    kb.append([InlineKeyboardButton("⬅ সেটিংসে ফিরে যান", callback_data="back_to_settings")])
    return InlineKeyboardMarkup(kb)


def get_add_id_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ আইডি লিস্ট যান",
                                                       callback_data="set_1xbet_id")]])


def get_deposit_options_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💖 বিকাশ", callback_data="wallet_bkash"),
         InlineKeyboardButton("🧡 নগদ", callback_data="wallet_nagad"),
         InlineKeyboardButton("💜 রকেট", callback_data="wallet_rocket")],
        [InlineKeyboardButton("❌ বাতিল", callback_data="wallet_cancel")],
    ])


def get_account_type_keyboard(wallet_name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 পারসোনাল", callback_data=f"type_personal_{wallet_name}"),
         InlineKeyboardButton("🏢 এজেন্ট", callback_data=f"type_agent_{wallet_name}")],
        [InlineKeyboardButton("⬅ ফিরে যান", callback_data="back_to_wallets")],
    ])


def get_copy_number_keyboard(wallet_name, acc_type, number):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{wallet_name} {acc_type} নাম্বার কপি করুন",
                              callback_data=f"copy_num_{number}")],
        [InlineKeyboardButton("❌ বাতিল করুন", callback_data="wallet_cancel")],
    ])


def get_withdraw_info_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("শহর কপি করুন 📋", callback_data="copy_city"),
         InlineKeyboardButton("রাস্তা কপি করুন 📋", callback_data="copy_street")],
        [InlineKeyboardButton("❌ বাতিল করুন", callback_data="withdraw_cancel")],
    ])


def get_withdraw_channel_keyboard(exclude_ids=None):
    exclude_ids = exclude_ids or set()
    kb = []
    for ch_id, ch_name, emoji in WITHDRAW_CHANNELS:
        if ch_id in exclude_ids:
            continue
        kb.append([InlineKeyboardButton(
            f"{emoji} {ch_name}",
            callback_data=f"wpick_ch_{ch_id}"
        )])
    kb.append([InlineKeyboardButton("❌ বাতিল করুন", callback_data="withdraw_cancel")])
    return InlineKeyboardMarkup(kb)


def get_support_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "💬 Message Support on Telegram",
            url=SUPPORT_LINK
        ),
    ]])


# --- 5. DEPOSIT FLOW ---
async def proceed_with_deposit_user(user_id, amount, update, context):
    target_msg = update.message if update.message else update.callback_query.message
    vn = context.user_data.get("dep_verified_name")
    vi = context.user_data.get("dep_verified_id")
    if vn and vi == str(user_id):
        player_name = vn
    else:
        ud = api_search_user(user_id)
        player_name = "Guest User"
        if isinstance(ud, dict) and "name" in ud and ud.get("name"):
            player_name = ud["name"]

    context.user_data["dep_user_id"] = user_id
    context.user_data["dep_user_name"] = player_name
    context.user_data["dep_amount"] = amount
    context.user_data["txn_attempts"] = 0
    wallet = context.user_data.get("payment_method", "বিকাশ")
    acc_type = context.user_data.get("account_type", "পারসোনাল")
    channel_id = CHANNEL_MAP.get((wallet, acc_type), 35)

    order_res = api_create_order(payer_key=user_id, amount=amount, channel_id=channel_id)
    if order_res.get("Success") and order_res.get("AccountNumber"):
        account_number = order_res["AccountNumber"]
        shop_order_id = order_res.get("ShopOrderId")
        context.user_data["shop_order_id"] = shop_order_id

        register_pending_deposit(
            shop_order_id=shop_order_id,
            chat_id=update.effective_chat.id,
            user_id=user_id,
            name=player_name,
            amount=amount,
            wallet=f"{wallet} {acc_type}",
            trxid="PENDING",
        )
    else:
        if order_res.get("pairing_failed"):
            await target_msg.reply_text("⚠️ **দুঃখিত! এই মুহূর্তে ওয়ালেট এভেলেবল নেই।**",
                                        parse_mode="Markdown")
        else:
            err = order_res.get("error_message", "Unknown error")
            await target_msg.reply_text(f"❌ **অর্ডার তৈরিতে সমস্যা:**\n```\n{err}\n```",
                                        parse_mode="Markdown")
        return

    context.user_data["state"] = "AWAITING_TXN_ID"

    dep_instructions = (
        "✅ <b>ডিপোজিট নির্দেশনা</b>\n\n"
        f"👤 <b>প্লেয়ার আইডি:</b> <code>{user_id}</code>\n"
        f"📝 <b>নাম:</b> <b>{player_name}</b>\n"
        f"📦 <b>অর্ডার আইডি:</b> <code>{shop_order_id}</code>\n\n"
        "🏦 <b>উপরের একাউন্টে ডিপোজিট পেতে নিচের নাম্বারে ১০ মিনিটের মধ্যে টাকা পাঠান।</b>\n\n"
        f"📱 <b>{wallet} {acc_type} নাম্বার:</b> <code>{account_number}</code>\n"
        "💸 <b>সেন্ড মানি করুন</b>\n\n"
        "টাকা পাঠানোর পর আপনার ট্রানজেকশন আইডি লিখুন। ট্রানজেকশন আইডি কোথায় পাবেন তা জানতে উপরের ছবিটি দেখুন।"
    )
    try:
        await target_msg.reply_photo(
            photo=TXN_EXAMPLE_IMAGE, caption=dep_instructions, parse_mode="HTML",
            reply_markup=get_copy_number_keyboard(wallet, acc_type, account_number))
    except Exception:
        try:
            await target_msg.reply_text(dep_instructions, parse_mode="HTML",
                                        reply_markup=get_copy_number_keyboard(wallet, acc_type, account_number))
        except Exception:
            plain = dep_instructions.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
            await target_msg.reply_text(plain,
                                        reply_markup=get_copy_number_keyboard(wallet, acc_type, account_number))
    await target_msg.reply_text(
        "⌨ ট্রানজেকশন আইডি লিখুন",
        reply_markup=ForceReply(selective=True),
    )


# --- 6. WELCOME ---
async def send_welcome_notice(update, context):
    context.user_data["state"] = None

    notice_caption = (
        "🚀 <b>Onexbet - বট ব্যবহার করে মাত্র ৫ সেকেন্ডে ডিপোজিট</b> ⚡️\n\n"
        "💰 মিন ডিপোজিট: ১০০৳\n"
        "💸 মিন উইথড্র: ১৫০৳\n"
        "⏱️ উইথড্র সময়: মাত্র ৫ মিনিটের মধ্যেই ✅\n\n"
        "🤖 অটো ডিপোজিট &amp; অটো উইথড্র সাপোর্ট\n"
        "📲 সহজ, দ্রুত ও ঝামেলামুক্ত সার্ভিস\n\n"
        "🛡 আমরা 1xBet-এর বিশ্বস্ত ও নির্ভরযোগ্য পার্টনার ✅\n"
        "🔐 নিরাপদ লেনদেন | 💯 ট্রাস্টেড সার্ভিস\n\n"
        "📣 মেনুয়াল👨‍💻👨‍💻 এবং রোবট👍👍 উভয় ডিপোজিট চালু রয়েছে🔥\n\n"
        "📣 যার যেভাবে ইচ্ছে করেন😱\n\n"
        "    👇👇👇👇👇\n"
        "👉 @depositeandwithdrawal_service 👨‍💻 (মানুষ)\n"
        "👉 @onexbbbot 👍👍 (রোবট)\n"
        "         👆👆👆👆👆\n"
        "    <b>৫ সেকেন্ডে ডিপোজিট | উইথড্র</b>\n\n"
        f"📣 💬 সার্বিক সহযোগিতার জন্য: প্রথমে আমাদের অফিসিয়াল সাপোর্ট গ্রুপ বা চ্যানেলে মেসেজ করুন 👉 {SUPPORT_USERNAME}\n\n"
        "📍 <b>ডিপোজিট বা উইথড্র করতে START বা নিচের বাটন চাপুন</b>\n"
        "💬 <b>২৪/৭ সাপোর্ট অ্যাক্টিভ</b>\n\n"
        "ধন্যবাদ 🙏✅"
    )
    tm = update.message if update.message else update.callback_query.message
    try:
        await tm.reply_photo(photo=BANNER_IMAGE_URL, caption=notice_caption,
                             parse_mode="HTML", reply_markup=get_main_keyboard())
    except Exception:
        try:
            await tm.reply_text(notice_caption, parse_mode="HTML",
                                reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"[WELCOME] HTML parse failed: {e}; sending as plain text")
            plain = (notice_caption.replace("<b>", "")
                     .replace("</b>", "")
                     .replace("&amp;", "&"))
            await tm.reply_text(plain, reply_markup=get_main_keyboard())


async def start_cmd(update, context):
    try:
        u = update.effective_user
        if u:
            col_users.update_one(
                {"telegram_id": str(u.id)},
                {"$set": {
                    "telegram_id": str(u.id),
                    "username": u.username,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "last_seen": datetime.now(timezone.utc),
                },
                 "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
    except Exception as e:
        logger.error(f"[USERS] start upsert failed: {e}")

    await send_welcome_notice(update, context)


# --- 7. SAVED IDS ---
async def show_saved_ids_menu(update, context, message_text=None):
    saved_ids = context.user_data.get("saved_player_ids", [])
    caption = "🎮 **সেভ করা প্লেয়ার আইডি লিস্ট**" if saved_ids else \
              "🎮 **সেভ করা প্লেয়ার আইডি লিস্ট**\n\nএখনো কোনো প্লেয়ার আইডি সেভ করা নেই।"
    if message_text:
        caption = f"{message_text}\n\n{caption}"
    markup = get_saved_ids_keyboard(saved_ids)
    if update.callback_query:
        await update.callback_query.message.edit_text(caption, parse_mode="Markdown",
                                                      reply_markup=markup)
    else:
        await update.message.reply_text(caption, parse_mode="Markdown",
                                        reply_markup=markup)


# --- 8. MESSAGE HANDLER ---
async def handle_message(update, context):
    text = update.message.text.strip()
    state = context.user_data.get("state")

    if text == "📥 Deposit":
        context.user_data["state"] = None
        await update.message.reply_text("যেকোনো ওয়ালেট নির্বাচন করুন।",
                                        reply_markup=get_deposit_options_keyboard())
        return

    elif text == "📤 Withdraw":
        context.user_data["state"] = "AWAITING_PAYOUT_USER_ID"
        context.user_data.pop("payout_code", None)
        context.user_data.pop("payout_user_id", None)
        context.user_data.pop("payout_user_name", None)
        context.user_data.pop("withdraw_payout_amount", None)
        context.user_data.pop("withdraw_payout_op_id", None)
        context.user_data.pop("withdraw_phone", None)
        context.user_data.pop("withdraw_channel_id", None)
        context.user_data.pop("withdraw_channel_name", None)
        context.user_data["withdraw_failed_channels"] = []
        await update.message.reply_text(
            f"✦ **উত্তোলন** ✦\n\n"
            f"➤ **শহর:** `{WITHDRAW_CITY}`\n"
            f"➤ **রাস্তা:** `{WITHDRAW_STREET}`\n\n"
            f"👤 প্রথমে আপনার **1xBet Player ID** লিখুন:",
            parse_mode="Markdown",
            reply_markup=get_withdraw_info_keyboard(),
        )
        await update.message.reply_text(
            "⌨️ প্লেয়ার আইডি লিখুন",
            reply_markup=ForceReply(selective=True),
        )
        return

    elif text == "🎁 Promo Code":
        context.user_data["state"] = None
        await update.message.reply_text(
            f"🎁 **প্রোমো কোড:** `{PROMO_CODE}`\n\n"
            f"এই কোডটি ডিপোজিটের সময় ব্যবহার করুন।",
            parse_mode="Markdown",
        )
        return

    elif text == "💬 Support":
        context.user_data["state"] = None
        try:
            await update.message.reply_text(
                SUPPORT_MESSAGE,
                reply_markup=get_support_keyboard(),
                disable_web_page_preview=True,
            )
        except Exception:
            await update.message.reply_text(
                SUPPORT_MESSAGE,
                disable_web_page_preview=True,
            )
        return

    elif text in ["⚙️ Settings", "⚙ Settings", "⚙️ সেটিংস", "⚙ সেটিংস"]:
        context.user_data["state"] = None
        is_admin = str(update.effective_user.id) in ADMIN_USER_IDS
        await update.message.reply_text("⚙ **সেটিংস**", parse_mode="Markdown",
                                        reply_markup=get_settings_main_keyboard(is_admin=is_admin))
        return

    if state == "AWAITING_SAVE_PLAYER_ID":
        v = await verify_player_async(text)
        if not v.get("valid"):
            await update.message.reply_text(verify_error_message(v), parse_mode="Markdown",
                                            reply_markup=ForceReply(selective=True))
            return
        nid = v["user_id"]
        saved = context.user_data.get("saved_player_ids", [])
        if nid not in saved:
            saved.append(nid)
            context.user_data["saved_player_ids"] = saved
            msg = f"✅ **`{nid}` সেভ হয়েছে।**\n👤 {v['name']}"
        else:
            msg = f"⚠ **`{nid}` ইতিমধ্যেই সেভ আছে।**\n👤 {v['name']}"
        context.user_data["state"] = None
        await show_saved_ids_menu(update, context, message_text=msg)
        return

    if state == "AWAITING_DEP_USER_ID":
        v = await verify_player_async(text)
        if not v.get("valid"):
            await update.message.reply_text(verify_error_message(v), parse_mode="Markdown",
                                            reply_markup=ForceReply(selective=True))
            return
        context.user_data["temp_dep_user_id"] = v["user_id"]
        context.user_data["dep_verified_id"] = v["user_id"]
        context.user_data["dep_verified_name"] = v["name"]
        context.user_data["state"] = "AWAITING_DEP_AMOUNT"
        await update.message.reply_text(
            "✅ **ভেরিফাইড!**\n\n"
            f"👤 **Player ID:** `{v['user_id']}`\n"
            f"📝 **Name:** {v['name']}",
            parse_mode="Markdown"
        )
        await update.message.reply_text("💰 **ডিপোজিট পরিমাণ লিখুন:**",
                                        parse_mode="Markdown",
                                        reply_markup=ForceReply(selective=True))
        return

    elif state == "AWAITING_DEP_AMOUNT":
        if not text.isdigit():
            await update.message.reply_text("❌ সঠিক পরিমাণ লিখুন:")
            return
        uid = context.user_data.get("temp_dep_user_id")
        await proceed_with_deposit_user(uid, int(text), update, context)
        return

    elif state == "AWAITING_TXN_ID":
        uid = context.user_data.get("dep_user_id")
        pn = context.user_data.get("dep_user_name")
        wallet = context.user_data.get("payment_method", "বিকাশ")
        soid = context.user_data.get("shop_order_id")
        amount = context.user_data.get("dep_amount", 0)
        chat_id = update.effective_chat.id

        attempt = context.user_data.get("txn_attempts", 0) + 1
        context.user_data["txn_attempts"] = attempt

        loading = await update.message.reply_text(
            "⏳ যাচাই করা হচ্ছে...",
            parse_mode="Markdown",
        )

        res, _ = await asyncio.to_thread(api_submit_transfer_code, soid, text)
        is_success, fm, content = parse_inquiry_response(res)

        response_text = (
            f"👤 **প্লেয়ার আইডি:** `{uid}`\n"
            f"📝 **নাম:** {pn}\n"
            f"💳 **মেথড:** {wallet}\n"
            f"🆔 **ট্রানজেকশন আইডি:** `{text}`\n"
            f"📦 **অর্ডার আইডি:** `{soid}`\n\n"
            f"{fm}"
        )

        if is_success:
            register_pending_deposit(
                shop_order_id=soid,
                chat_id=chat_id,
                user_id=uid,
                name=pn,
                amount=int(amount),
                wallet=wallet,
                trxid=text,
            )

            final_text = (
                f"{response_text}\n\n"
                f"⏳ **পেমেন্ট যাচাই করা হচ্ছে...**\n"
                f"মার্চেন্ট কনফার্মেশন পেলে আমরা আপনার একাউন্টে ফান্ড অ্যাড করে দিব ইনশাআল্লাহ।\n"
                f"_(সাধারণত ১০ সেকেন্ড থেকে ১ মিনিট সময় লাগতে পারে)_"
            )

            try:
                await loading.edit_text(final_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(final_text, parse_mode="Markdown")

            context.user_data["state"] = None
            context.user_data.pop("txn_attempts", None)
            context.user_data.pop("shop_order_id", None)
            return

        elif content in TERMINAL_TRX_ERRORS:
            context.user_data["state"] = None
            context.user_data.pop("txn_attempts", None)
            context.user_data.pop("shop_order_id", None)

            try:
                await loading.edit_text(response_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(response_text, parse_mode="Markdown")

            await update.message.reply_text(
                "ℹ️ **অনুগ্রহ করে নতুন ডিপোজিট শুরু করতে 📥 Deposit বাটনে চাপুন।**",
                parse_mode="Markdown",
            )

        else:
            try:
                await loading.edit_text(response_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(response_text, parse_mode="Markdown")

            await update.message.reply_text(
                "🔁 **আবার চেষ্টা করুন**\nসঠিক ট্রানজেকশন আইডিটি লিখে পাঠান।",
                parse_mode="Markdown",
                reply_markup=ForceReply(selective=True),
            )
        return

    elif state == "AWAITING_PAYOUT_USER_ID":
        v = await verify_player_async(text)
        if not v.get("valid"):
            await update.message.reply_text(
                verify_error_message(v),
                parse_mode="Markdown",
                reply_markup=ForceReply(selective=True),
            )
            return

        context.user_data["payout_user_id"] = v["user_id"]
        context.user_data["payout_user_name"] = v["name"]

        context.user_data["state"] = "AWAITING_PAYOUT_CODE"
        await update.message.reply_text(
            f"✅ **প্লেয়ার ভেরিফাইড!**\n\n"
            f"👤 **Player ID:** `{v['user_id']}`\n"
            f"📝 **Name:** {v['name']}\n\n"
            f"🔑 এখন আপনার **উইথড্র সিক্রেট কোড** লিখুন:",
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            "⌨️ উইথড্র সিক্রেট কোড লিখুন",
            reply_markup=ForceReply(selective=True),
        )
        return

    elif state == "AWAITING_PAYOUT_CODE":
        code = text.strip()
        if not code:
            await update.message.reply_text(
                "❌ কোড খালি হতে পারে না। আবার লিখুন:",
                reply_markup=ForceReply(selective=True),
            )
            return

        uid = context.user_data.get("payout_user_id")
        uname = context.user_data.get("payout_user_name", "N/A")

        if not uid:
            await update.message.reply_text(
                "⚠️ **প্লেয়ার আইডি পাওয়া যায়নি।** আবার 📤 Withdraw থেকে শুরু করুন।",
                parse_mode="Markdown",
            )
            context.user_data["state"] = None
            return

        context.user_data["state"] = None

        loading = await update.message.reply_text(
            "⏳ **পেআউট প্রসেস করা হচ্ছে...**",
            parse_mode="Markdown",
        )

        try:
            data = await asyncio.to_thread(api_payout, uid, code)
        except Exception as e:
            data = {"success": False, "message": f"Exception: {e}"}

        success = bool(data.get("success"))
        paid_amount = data.get("paid_out_amount")
        raw_summa = data.get("summa")
        api_success = bool(data.get("api_success"))
        message = data.get("message") or ""
        message_id = data.get("message_id")
        operation_id = data.get("operation_id")

        base_info = (
            f"👤 **প্লেয়ার আইডি:** `{uid}`\n"
            f"📝 **নাম:** {uname}\n"
            f"🔑 **কোড:** `{code}`"
        )

        if not success:
            if api_success and raw_summa is not None and raw_summa >= 0:
                reason_bn = (
                    f"⚠️ অবৈধ পেআউট অ্যামাউন্ট: `{raw_summa}` "
                    f"(প্রত্যাশিত ঋণাত্মক মান)।"
                )
            else:
                reason_bn = translate_payout_error(message, message_id)

            final_text = (
                f"{base_info}\n\n"
                f"❌ **উইথড্র ব্যর্থ!**\n"
                f"💡 **সঠিক উইথড্র কোড দিয়ে আবার চেষ্টা করুন।**"
            )

            log_payout(uid, code, None, "failed_payout_code",
                       error=message, operation_id=operation_id)

            try:
                await loading.edit_text(final_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(final_text, parse_mode="Markdown")

            context.user_data["state"] = "AWAITING_PAYOUT_CODE"
            await update.message.reply_text(
                "🔁 **নতুন সিক্রেট কোড লিখুন।**",
                parse_mode="Markdown",
                reply_markup=ForceReply(selective=True),
            )
            return

        payout_amount = int(paid_amount) if paid_amount is not None else 0

        context.user_data["withdraw_payout_amount"] = payout_amount
        context.user_data["withdraw_payout_op_id"] = operation_id or str(raw_summa)
        context.user_data["payout_code"] = code
        context.user_data["state"] = "AWAITING_WITHDRAW_PHONE"
        context.user_data["withdraw_failed_channels"] = []

        try:
            await loading.edit_text(
                f"{base_info}\n\n"
                f"✅ **১xBet পেআউট সফল!**\n"
                f"➤ অ্যামাউন্ট: `{payout_amount:,.2f} BDT`\n"
                f"➤ রেফারেন্স: `{operation_id or raw_summa}`",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await update.message.reply_text(
            f"📱 **পেআউট নম্বর লিখুন**\n\n"
            f"যে বিকাশ / নগদ / রকেট নম্বরে টাকা পেতে চান, সেই নম্বরটি লিখুন:\n"
            f"_(যেমন: 01712345678)_",
            parse_mode="Markdown",
            reply_markup=ForceReply(selective=True),
        )
        return

    elif state == "AWAITING_WITHDRAW_PHONE":
        phone = text.strip().replace(" ", "").replace("-", "")
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 14:
            await update.message.reply_text(
                "❌ **সঠিক মোবাইল নম্বর লিখুন।**\n"
                "যেমন: `01712345678`",
                parse_mode="Markdown",
                reply_markup=ForceReply(selective=True),
            )
            return

        context.user_data["withdraw_phone"] = phone
        context.user_data["state"] = "AWAITING_WITHDRAW_CHANNEL"

        await update.message.reply_text(
            f"✅ **নম্বর গৃহীত:** `{phone}`\n\n"
            f"🏦 এখন **পেমেন্ট চ্যানেল নির্বাচন করুন:**",
            parse_mode="Markdown",
            reply_markup=get_withdraw_channel_keyboard(),
        )
        return

    elif state == "ADMIN_AWAITING_FIND_PLAYER":
        qid = text.strip()
        if not qid.isdigit():
            await update.message.reply_text("❌ শুধু সংখ্যা।", reply_markup=ForceReply(selective=True))
            return
        loading = await update.message.reply_text("🔍 খোঁজা হচ্ছে...")
        res = await asyncio.to_thread(api_search_user, qid)
        context.user_data["state"] = None
        if isinstance(res, dict) and "error" in res:
            await loading.edit_text(f"❌ ব্যর্থ: {res.get('details','')[:300]}",
                                    parse_mode="Markdown")
            return
        await loading.edit_text(
            f"🔍 **Player Found**\n👤 ID: `{res.get('userId', qid)}`\n"
            f"📝 Name: {res.get('name', 'N/A')}\n💱 Currency: `{res.get('currencyId', 'N/A')}`",
            parse_mode="Markdown")
        return


# --- 9. CALLBACK HANDLER ---
async def button_click(update, context):
    q = update.callback_query

    if q.data.startswith("copy_num_"):
        await q.answer(f"নম্বর: {q.data.replace('copy_num_','')}", show_alert=True)
        return
    elif q.data == "copy_city":
        await q.answer(f"City: {WITHDRAW_CITY}", show_alert=True)
        return
    elif q.data == "copy_street":
        await q.answer(f"Street: {WITHDRAW_STREET}", show_alert=True)
        return

    elif q.data.startswith("wpick_ch_"):
        if context.user_data.get("state") != "AWAITING_WITHDRAW_CHANNEL":
            await q.answer("⚠️ সেশন এক্সপায়ার হয়েছে। আবার শুরু করুন।", show_alert=True)
            return

        try:
            ch_id = int(q.data.replace("wpick_ch_", ""))
        except ValueError:
            await q.answer("❌ ভুল চ্যানেল।", show_alert=True)
            return

        failed_channels = context.user_data.get("withdraw_failed_channels", []) or []
        if ch_id in failed_channels:
            await q.answer("⚠️ এই চ্যানেল আগেই ব্যর্থ হয়েছে। অন্যটি বেছে নিন।", show_alert=True)
            return

        ch_name = "N/A"
        for cid, cname, _ in WITHDRAW_CHANNELS:
            if cid == ch_id:
                ch_name = cname
                break

        await q.answer(f"⏳ {ch_name} প্রসেস করা হচ্ছে...")

        uid = context.user_data.get("payout_user_id")
        uname = context.user_data.get("payout_user_name", "N/A")
        code = context.user_data.get("payout_code", "N/A")
        amount = context.user_data.get("withdraw_payout_amount", 0)
        op_id = context.user_data.get("withdraw_payout_op_id", "N/A")
        phone = context.user_data.get("withdraw_phone", "")
        chat_id = q.message.chat_id

        loading = await q.message.reply_text(
            f"⏳ **পেমেন্ট অর্ডার তৈরি করা হচ্ছে ({ch_name})...**",
            parse_mode="Markdown",
        )

        try:
            po_res = await asyncio.to_thread(
                api_create_payment_order,
                amount,
                ch_id,
                payee_name=uname,
                payee_phone=phone,
                payee_account=phone,
            )
        except Exception as e:
            po_res = {"Success": False, "error_message": f"Exception: {e}"}

        po_ok = bool(po_res.get("Success"))
        po_order_id = po_res.get("ShopOrderId", "N/A")
        po_err = po_res.get("error_message", "") or po_res.get("ErrorMessage", "")

        base_info = (
            f"👤 **প্লেয়ার আইডি:** `{uid}`\n"
            f"📝 **নাম:** {uname}\n"
            f"🔑 **কোড:** `{code}`\n"
            f"📱 **পেআউট নম্বর:** `{phone}`\n"
            f"🏦 **চ্যানেল:** {ch_name} (#{ch_id})"
        )

        amount_txt = f"{amount:,.2f} BDT"

        if po_ok:
            final_text = (
                f"{base_info}\n\n"
                f"✅ **উইথড্র রিকোয়েস্ট গৃহীত!**\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"💵 **অ্যামাউন্ট:** `{amount_txt}`\n"
                f"🆔 **Payout Op ID:** `{op_id}`\n"
                f"📦 **Payment Order:** `{po_order_id}`\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"⏳ পেমেন্ট প্রসেস হচ্ছে... কনফার্মেশন পেলে জানানো হবে।\n"
                f"_(সাধারণত ১০ সেকেন্ড থেকে ২ মিনিট সময় লাগতে পারে)_"
            )

            log_payout(uid, code, amount, "processing",
                       operation_id=op_id, phone=phone,
                       channel_id=ch_id, channel_name=ch_name,
                       payment_order_id=po_order_id,
                       chat_id=chat_id)

            try:
                await loading.edit_text(final_text, parse_mode="Markdown")
            except Exception:
                await q.message.reply_text(final_text, parse_mode="Markdown")

            bal = await asyncio.to_thread(api_balance)
            if "error" not in bal:
                b = bal.get("Balance")
                l = bal.get("Limit")
                bt = f"{b:,.2f}" if isinstance(b, (int, float)) else "N/A"
                lt = f"{l:,.2f}" if isinstance(l, (int, float)) else "N/A"
                try:
                    await q.message.reply_text(
                        f"💼 **ক্যাশডেস্ক ব্যালেন্স** _(cash in desk)_\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"🏦 **ক্যাশডেস্ক আইডি:** `{CASHDESK_ID}`\n"
                        f"💵 **ডেস্ক ব্যালেন্স:** `{bt}` BDT\n"
                        f"📊 **লিমিট:** `{lt}` BDT",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            context.user_data["state"] = None
            context.user_data.pop("payout_code", None)
            context.user_data.pop("withdraw_payout_amount", None)
            context.user_data.pop("withdraw_payout_op_id", None)
            context.user_data.pop("withdraw_phone", None)
            context.user_data.pop("withdraw_failed_channels", None)
            return

        if ch_id not in failed_channels:
            failed_channels.append(ch_id)
        context.user_data["withdraw_failed_channels"] = failed_channels

        reason_bn = translate_payment_order_error(po_err)
        remaining = [c for c in WITHDRAW_CHANNELS if c[0] not in failed_channels]

        raw_debug = f"\n\n🔧 _raw: `{po_err[:200]}`_" if po_err else ""

        if remaining:
            remaining_lines = "\n".join(
                [f"• {emoji} {name}" for _, name, emoji in remaining]
            )
            retry_text = (
                f"{base_info}\n\n"
                f"❌ **পেমেন্ট অর্ডার ব্যর্থ!**\n"
                f"➤ কারণ: {reason_bn}"
                f"{raw_debug}\n\n"
                f"💡 **অন্য একটি পেমেন্ট চ্যানেল বেছে নিন:**\n"
                f"{remaining_lines}"
            )

            context.user_data["state"] = "AWAITING_WITHDRAW_CHANNEL"

            try:
                await loading.edit_text(
                    retry_text,
                    parse_mode="Markdown",
                    reply_markup=get_withdraw_channel_keyboard(
                        exclude_ids=set(failed_channels)
                    ),
                )
            except Exception:
                await q.message.reply_text(
                    retry_text,
                    parse_mode="Markdown",
                    reply_markup=get_withdraw_channel_keyboard(
                        exclude_ids=set(failed_channels)
                    ),
                )
            return
        else:
            final_text = (
                f"{base_info}\n\n"
                f"❌ **সব পেমেন্ট চ্যানেলই ব্যর্থ হয়েছে!**\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"💵 **অ্যামাউন্ট:** `{amount_txt}`\n"
                f"🆔 **Payout Op ID:** `{op_id}`\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"➤ শেষ কারণ: {reason_bn}"
                f"{raw_debug}\n\n"
                f"📞 **অনুগ্রহ করে সাপোর্টে যোগাযোগ করুন ({SUPPORT_USERNAME})।**"
            )

            log_payout(uid, code, amount, "all_channels_failed",
                       operation_id=op_id, phone=phone,
                       error=po_err, chat_id=chat_id)

            try:
                await loading.edit_text(final_text, parse_mode="Markdown")
            except Exception:
                await q.message.reply_text(final_text, parse_mode="Markdown")

            context.user_data["state"] = None
            context.user_data.pop("payout_code", None)
            context.user_data.pop("withdraw_payout_amount", None)
            context.user_data.pop("withdraw_payout_op_id", None)
            context.user_data.pop("withdraw_phone", None)
            context.user_data.pop("withdraw_failed_channels", None)
            return

    elif q.data == "withdraw_cancel":
        await q.answer("বাতিল করা হয়েছে")
        context.user_data["state"] = None
        context.user_data.pop("payout_code", None)
        context.user_data.pop("payout_user_id", None)
        context.user_data.pop("payout_user_name", None)
        context.user_data.pop("withdraw_payout_amount", None)
        context.user_data.pop("withdraw_payout_op_id", None)
        context.user_data.pop("withdraw_phone", None)
        context.user_data.pop("withdraw_channel_id", None)
        context.user_data.pop("withdraw_channel_name", None)
        context.user_data.pop("withdraw_failed_channels", None)
        await q.message.reply_text(
            "❌ **উইথড্র বাতিল করা হয়েছে।**\n\nআবার শুরু করতে 📤 Withdraw বাটনে চাপুন।",
            parse_mode="Markdown",
        )
        return

    elif q.data == "cancel_txn":
        await q.answer("বাতিল করা হয়েছে")
        context.user_data["state"] = None
        context.user_data.pop("txn_attempts", None)
        await q.message.reply_text(
            "❌ **ট্রানজেকশন বাতিল করা হয়েছে।**\n\nনতুন করে শুরু করতে 📥 Deposit বাটনে চাপুন।",
            parse_mode="Markdown",
        )
        return

    elif q.data == "check_balance":
        if str(q.from_user.id) not in ADMIN_USER_IDS:
            await q.answer("⛔ Not authorized.", show_alert=True)
            return
        await q.answer("💰...")
        loading = await q.message.reply_text("⏳ Checking...")
        res = await asyncio.to_thread(api_balance)
        if "error" in res:
            await loading.edit_text(
                f"❌ **Failed**\n🔧 `{res.get('error')}`\n`{str(res.get('details',''))[:300]}`",
                parse_mode="Markdown")
            return
        b = res.get("Balance")
        l = res.get("Limit")
        bt = f"{b:,.2f}" if isinstance(b, (int, float)) else "N/A"
        lt = f"{l:,.2f}" if isinstance(l, (int, float)) else "N/A"
        await loading.edit_text(
            f"💼 **Cashdesk Balance**\n🏦 `{CASHDESK_ID}`\n💵 `{bt}` BDT\n📊 Limit `{lt}` BDT",
            parse_mode="Markdown")
        return

    elif q.data == "find_player":
        if str(q.from_user.id) not in ADMIN_USER_IDS:
            await q.answer("⛔", show_alert=True)
            return
        await q.answer()
        context.user_data["state"] = "ADMIN_AWAITING_FIND_PLAYER"
        await q.message.reply_text("🔍 Player ID লিখুন:", reply_markup=ForceReply(selective=True))
        return

    elif q.data == "set_1xbet_id":
        await q.answer()
        await show_saved_ids_menu(update, context)
        return

    elif q.data == "add_new_player_id":
        await q.answer()
        context.user_data["state"] = "AWAITING_SAVE_PLAYER_ID"
        await q.message.edit_text("🎮 **নতুন প্লেয়ার আইডি**\n\n1xBet ID লিখুন:",
                                  parse_mode="Markdown", reply_markup=get_add_id_keyboard())
        await q.message.reply_text("⌨ প্লেয়ার আইডি লিখুন",
                                   reply_markup=ForceReply(selective=True))
        return

    elif q.data.startswith("del_saved_id_"):
        tid = q.data.replace("del_saved_id_", "")
        saved = context.user_data.get("saved_player_ids", [])
        if tid in saved:
            saved.remove(tid)
            context.user_data["saved_player_ids"] = saved
            await q.answer(f"{tid} মুছে ফেলা হয়েছে", show_alert=True)
        else:
            await q.answer("পাওয়া যায়নি", show_alert=True)
        await show_saved_ids_menu(update, context)
        return

    elif q.data.startswith("select_saved_id_"):
        await q.answer(f"{q.data.replace('select_saved_id_','')}", show_alert=True)
        return

    elif q.data == "back_to_settings":
        await q.answer()
        is_admin = str(q.from_user.id) in ADMIN_USER_IDS
        await q.message.edit_text("⚙️️ **সেটিংস**", parse_mode="Markdown",
                                  reply_markup=get_settings_main_keyboard(is_admin=is_admin))
        return

    elif q.data in ["set_bkash", "set_nagad", "set_rocket"]:
        names = {"set_bkash": "বিকাশ", "set_nagad": "নগদ", "set_rocket": "রকেট"}
        await q.answer(f"{names[q.data]} সেটিংস", show_alert=True)
        return

    elif q.data.startswith("use_dep_id_"):
        sid = q.data.replace("use_dep_id_", "")
        await q.answer("🔍...")
        v = await verify_player_async(sid)
        if not v.get("valid"):
            await q.message.reply_text(verify_error_message(v), parse_mode="Markdown")
            return
        context.user_data["temp_dep_user_id"] = v["user_id"]
        context.user_data["dep_verified_id"] = v["user_id"]
        context.user_data["dep_verified_name"] = v["name"]
        context.user_data["state"] = "AWAITING_DEP_AMOUNT"
        await q.message.reply_text(
            "✅ **ভেরিফাইড!**\n\n"
            f"👤 **Player ID:** `{v['user_id']}`\n"
            f"📝 **Name:** {v['name']}",
            parse_mode="Markdown"
        )
        await q.message.reply_text("💰 **ডিপোজিট পরিমাণ লিখুন:**",
                                   parse_mode="Markdown",
                                   reply_markup=ForceReply(selective=True))
        return

    await q.answer()

    if q.data.startswith("wallet_"):
        if q.data == "wallet_cancel":
            context.user_data["state"] = None
            await q.message.delete()
            return
        names = {"wallet_bkash": "বিকাশ", "wallet_nagad": "নগদ", "wallet_rocket": "রকেট"}
        w = names.get(q.data, "ওয়ালেট")
        context.user_data["payment_method"] = w
        await q.message.reply_text(f"📱 **{w} নম্বরের ধরন:**",
                                   parse_mode="Markdown",
                                   reply_markup=get_account_type_keyboard(w))
        return

    elif q.data.startswith("type_"):
        at = "পারসোনাল" if q.data.split("_")[1] == "personal" else "এজেন্ট"
        context.user_data["account_type"] = at
        context.user_data["state"] = "AWAITING_DEP_USER_ID"
        saved = context.user_data.get("saved_player_ids", [])
        if saved:
            kb = [[InlineKeyboardButton(f"🎮 {p}", callback_data=f"use_dep_id_{p}")] for p in saved]
            await q.message.reply_text("সেভ করা আইডি বেছে নিন বা লিখুন:",
                                       reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.message.reply_text("আপনার প্লেয়ার আইডি লিখুন:")
        await q.message.reply_text("⌨ প্লেয়ার আইডি লিখুন",
                                   reply_markup=ForceReply(selective=True))
        return

    elif q.data == "back_to_wallets":
        await q.message.reply_text("যেকোনো ওয়ালেট নির্বাচন করুন।",
                                   reply_markup=get_deposit_options_keyboard())
        return


# --- 10. POST INIT ---
async def post_init(application):
    global telegram_app, bot_event_loop
    telegram_app = application
    bot_event_loop = asyncio.get_running_loop()
    await application.bot.set_my_commands([BotCommand("start", "রোবট শুরু করুন🥳")])


# --- 11. MAIN ---
if __name__ == "__main__":
    print("=" * 78)
    print("🚀 Bot starting...")
    print(f"🌐 Callback URL (as sent to merchant): {MERCHANT_CALLBACK_URL}")
    print(f"🌐 Local callback server listening on : http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}")
    print(f"🗄️  MongoDB database                  : {MONGO_DB_NAME}")
    print(f"🔑 Merchant ShopUserLongId            : {SHOP_USER_LONG_ID}")
    print(f"🔑 Merchant HashKey (last 6)          : ...{MERCHANT_HASH_KEY[-6:]}")
    print("=" * 78)

    if not init_mongodb():
        print("❌ Failed to connect to MongoDB. Exiting.")
        raise SystemExit(1)

    _load_processed_orders_from_mongo()

    start_flask_in_background()
    time.sleep(0.5)

    persistence = PicklePersistence(filepath="bot_data.pickle")
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))

    print("🚀 Bot running...")
    app.run_polling()