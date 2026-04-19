from fastapi import FastAPI, HTTPException, UploadFile, File, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
from datetime import datetime
import requests
import httpx
import os
import time
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from enhanced_routes import setup_enhanced_routes
from order_engine import get_engine, MENU, _SORTED_KEYS
from threading import Thread
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
import asyncio
from openai import OpenAI
from upsell_engine import get_upsell_engine, generate_upsell_audio, UPSELL_MAP
from upsell_map import (get_upsell_audio, get_upsell_audio_path, get_upsell_audio_info,
                        UPSELL_AUDIO_MAP, get_combo_cross_sell, get_general_response_audio)
from menu_validator import validate_order_items, validate_menu_item, log_order_pipeline, get_recent_logs, get_whisper_prompt

# ========== Qwen3 API Setup ==========
_qwen_client = None

def get_qwen_client():
    """Lazy-init Qwen3 client (OpenAI-compatible)."""
    global _qwen_client
    if _qwen_client is None:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("QWEN_API_URL")
        if not api_key or not base_url:
            return None
        _qwen_client = OpenAI(api_key=api_key, base_url=base_url)
    return _qwen_client

# ========== DeepSeek API Setup (Intent Extraction) ==========
_deepseek_client = None

def get_deepseek_client():
    """Lazy-init DeepSeek client (OpenAI-compatible)."""
    global _deepseek_client
    if _deepseek_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        _deepseek_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _deepseek_client

# ========== OpenAI Whisper STT Setup ==========
_whisper_client = None

def get_whisper_client():
    """Lazy-init OpenAI Whisper client for audio transcription."""
    global _whisper_client
    if _whisper_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        _whisper_client = OpenAI(api_key=api_key)
    return _whisper_client

def transcribe_audio(audio_file_path):
    """Transcribe an audio file using OpenAI Whisper API with Khulafa menu hints."""
    client = get_whisper_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not set")
    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ms",
            prompt=get_whisper_prompt(),
        )
    print(f"[Whisper] Transcribed: {transcript.text}")
    return transcript.text

def _build_menu_list() -> str:
    """Build a flat menu list string from the MENU dict for the system prompt."""
    lines = []
    for name, item in MENU.items():
        lines.append(f"- {name} (RM{item['price']:.2f})")
    return "\n".join(lines)

AISHA_SYSTEM_PROMPT = f"""You are Aisha, the virtual waitress at Khulafa Bistro. Your role is to take orders and suggest upgrades.

RULES:
1. Confirm what customer ordered
2. Keep responses SHORT - max 2 sentences
3. Example: "Baiklah, mee goreng satu! Nak try Mee Goreng Seafood? Lagi sedap!"
4. NEVER say "Kami ada...", "Boleh cuba..."
5. NEVER list menu categories or suggest promotions
6. When the customer confirms the order ("tu je" / "cukup" / "dah" / "hantar" / "confirm" / "settle" / "setel" / "sekian"), reply with ONLY: CONFIRM_ORDER
7. Understand common Malay speech patterns, slang, and misspellings
8. CRITICAL: All mee goreng, maggi goreng, bihun, kuey teow, and indomee items ARE on the menu. NEVER say they are unavailable.
9. If customer says "tak nak" / "no" to upsell, accept immediately: "Okay! Ada lagi?"
10. Only suggest upsells that are provided in the UPSELL context — never make up suggestions.

MENU ITEMS:
{_build_menu_list()}

RESPONSE FORMAT — Always respond in this EXACT JSON format, nothing else:

When customer orders items:
{{"items": ["roti canai", "maggi goreng"], "action": "add_items", "reply": "Roti Canai dan Maggi Goreng! Nak try Maggi Goreng Kambing? Lagi power!"}}

When customer confirms the order:
{{"items": [], "action": "confirm_order", "reply": "Terima kasih! Pesanan sudah dihantar."}}

When you cannot understand:
{{"items": [], "action": "unclear", "reply": "Maaf, boleh ulang sekali lagi?"}}

IMPORTANT:
- Item names in the "items" array MUST be lowercase and match the menu item names EXACTLY
- NEVER include items that are not on the menu — if you cannot match, set action to "unclear" and ask the customer to repeat
- Always respond with valid JSON only — no extra text before or after"""


# Unwanted generic recommendation phrases to strip (NOT upsell suggestions)
_RECOMMENDATION_PATTERNS = [
    r"kami\s+ada",
    r"promosi",
    r"special\s+hari\s+ini",
    r"menu\s+hari\s+ini",
]

def _strip_recommendations(reply: str) -> str:
    """Remove unwanted generic recommendation sentences from Aisha's reply.
    Preserves intentional upsell suggestions (nak try, sedap jugak, lagi best)."""
    import re
    sentences = re.split(r'(?<=[.?!])\s+', reply.strip())
    clean = []
    for s in sentences:
        s_lower = s.lower()
        if any(re.search(p, s_lower) for p in _RECOMMENDATION_PATTERNS):
            continue
        clean.append(s)
    result = ' '.join(clean).strip()
    return result if result else reply


def fuzzy_match_menu_item(item_text: str) -> list:
    """
    Fuzzy-match a text string to one or more MENU items.
    Handles partial names (e.g. 'min bandung' -> 'bandung') and compound
    inputs (e.g. 'sirap ais barli' -> ['sirap ais', 'barli ais']).
    Returns a list of matched menu keys.
    """
    item_text = item_text.lower().strip()

    # Exact match
    if item_text in MENU:
        return [item_text]

    # Phase 1: Greedy substring matching — find all MENU keys within item_text
    length = len(item_text)
    used = [False] * length
    matches = []

    for key in _SORTED_KEYS:
        klen = len(key)
        start = 0
        while start <= length - klen:
            idx = item_text.find(key, start)
            if idx == -1:
                break
            if not any(used[idx:idx + klen]):
                matches.append(key)
                for i in range(idx, idx + klen):
                    used[i] = True
                start = idx + klen
            else:
                start = idx + 1

    # Phase 2: For remaining unmatched words, try prefix matching
    # e.g. "barli" leftover -> matches "barli ais" (shortest prefix match)
    remaining_words = []
    current_word = []
    for i in range(length):
        if not used[i]:
            if item_text[i] != ' ':
                current_word.append(item_text[i])
            else:
                if current_word:
                    remaining_words.append("".join(current_word))
                    current_word = []
        else:
            if current_word:
                remaining_words.append("".join(current_word))
                current_word = []
    if current_word:
        remaining_words.append("".join(current_word))

    for word in remaining_words:
        if len(word) >= 3:
            candidates = [k for k in _SORTED_KEYS if k.startswith(word + " ") or k == word]
            if candidates:
                best = min(candidates, key=len)
                if best not in matches:
                    matches.append(best)

    if matches:
        return matches

    # Phase 3: item_text is contained within a MENU key
    for key in _SORTED_KEYS:
        if item_text in key:
            return [key]

    return []


# Telegram Bot Configuration — strictly from environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CASHIER_CHAT_ID = os.environ.get("CASHIER_CHAT_ID", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

if not BOT_TOKEN:
    print("⚠️ TELEGRAM_BOT_TOKEN is not set! Telegram notifications will not work.")
if not CASHIER_CHAT_ID:
    print("⚠️ CASHIER_CHAT_ID is not set! Order notifications will not be sent.")
if not OWNER_CHAT_ID:
    print("⚠️ OWNER_CHAT_ID is not set! Owner will not receive notifications.")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Startup diagnostic: show configured Telegram recipients
print(f"[Telegram Config] BOT_TOKEN: {'SET ✅' if BOT_TOKEN else 'NOT SET ❌'}")
print(f"[Telegram Config] CASHIER_CHAT_ID: {CASHIER_CHAT_ID if CASHIER_CHAT_ID else 'NOT SET ❌'}")
print(f"[Telegram Config] OWNER_CHAT_ID: {OWNER_CHAT_ID if OWNER_CHAT_ID else 'NOT SET ❌'}")
if CASHIER_CHAT_ID and OWNER_CHAT_ID and CASHIER_CHAT_ID == OWNER_CHAT_ID:
    print("[Telegram Config] ⚠️ CASHIER_CHAT_ID and OWNER_CHAT_ID are the SAME — owner will NOT receive duplicate messages")

# ── Unclear-order fallback configuration (Change 4) ──
UNCLEAR_MIN_WORDS = 2
UNCLEAR_CONFIDENCE_THRESHOLD = 0.6
UNCLEAR_DEDUP_WINDOW_SECONDS = 30
UNCLEAR_RATE_LIMIT_PER_TABLE_PER_MINUTE = 10
UNCLEAR_RATE_LIMIT_GLOBAL_PER_HOUR = 50
UNCLEAR_AUDIO_RETENTION_HOURS = 24
UNCLEAR_TRANSCRIBE_CACHE_TTL_SECONDS = 300
UNCLEAR_TRANSCRIBE_CACHE_MAX = 50

_unclear_lock = threading.Lock()
_unclear_dedup_cache: dict = {}
_unclear_rate_table: dict = {}
_unclear_rate_global: list = []
_unclear_alerts_pending: dict = {}
_transcribe_audio_cache: "OrderedDict" = OrderedDict()


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.lower().split())


def _cache_transcribe_audio(table: str, text: str, audio_bytes: bytes) -> None:
    """Store raw audio bytes keyed by (table, normalized text) so the unclear
    fallback can persist them later if triggered. Bounded + TTL-evicted."""
    key = (table, _normalize_text(text))
    now = time.time()
    with _unclear_lock:
        expired = [k for k, (_, ts) in _transcribe_audio_cache.items()
                   if now - ts > UNCLEAR_TRANSCRIBE_CACHE_TTL_SECONDS]
        for k in expired:
            _transcribe_audio_cache.pop(k, None)
        _transcribe_audio_cache[key] = (audio_bytes, now)
        _transcribe_audio_cache.move_to_end(key)
        while len(_transcribe_audio_cache) > UNCLEAR_TRANSCRIBE_CACHE_MAX:
            _transcribe_audio_cache.popitem(last=False)


def _pop_transcribe_audio(table: str, text: str):
    """Pop cached audio bytes for (table, text). None if missing or expired."""
    key = (table, _normalize_text(text))
    now = time.time()
    with _unclear_lock:
        entry = _transcribe_audio_cache.pop(key, None)
        if not entry:
            return None
        audio_bytes, ts = entry
        if now - ts > UNCLEAR_TRANSCRIBE_CACHE_TTL_SECONDS:
            return None
        return audio_bytes


def should_trigger_unclear_fallback(table: str, text: str, deepseek_result):
    """Evaluate the 5 trigger conditions for the unclear-order fallback.

    Returns (should_fire, reason). SIDE EFFECT: when returning True, updates
    the dedup and rate-limit caches so repeat calls in the window are
    suppressed. Call at most once per voice/chat request.

    Reasons: empty_text | single_word | clear_match | dedup |
    rate_limit_table | rate_limit_global | unclear
    """
    if not text or not text.strip():
        return False, "empty_text"
    if len(text.split()) < UNCLEAR_MIN_WORDS:
        return False, "single_word"

    is_unclear = False
    if deepseek_result:
        for item in deepseek_result:
            if not isinstance(item, dict):
                continue
            if item.get("needs_clarification") is True:
                is_unclear = True
                break
            matched = (item.get("matched_item") or "").strip()
            try:
                confidence = float(item.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if matched == "" or confidence < UNCLEAR_CONFIDENCE_THRESHOLD:
                is_unclear = True
                break
    if not is_unclear:
        return False, "clear_match"

    normalized = _normalize_text(text)
    now = time.time()
    with _unclear_lock:
        last_sent = _unclear_dedup_cache.get((table, normalized))
        if last_sent is not None and now - last_sent < UNCLEAR_DEDUP_WINDOW_SECONDS:
            return False, "dedup"

        table_times = [t for t in _unclear_rate_table.get(table, []) if now - t < 60]
        if len(table_times) >= UNCLEAR_RATE_LIMIT_PER_TABLE_PER_MINUTE:
            _unclear_rate_table[table] = table_times
            return False, "rate_limit_table"

        global_times = [t for t in _unclear_rate_global if now - t < 3600]
        if len(global_times) >= UNCLEAR_RATE_LIMIT_GLOBAL_PER_HOUR:
            _unclear_rate_global[:] = global_times
            return False, "rate_limit_global"

        _unclear_dedup_cache[(table, normalized)] = now
        stale = [k for k, ts in _unclear_dedup_cache.items()
                 if now - ts > UNCLEAR_DEDUP_WINDOW_SECONDS * 10]
        for k in stale:
            _unclear_dedup_cache.pop(k, None)
        table_times.append(now)
        _unclear_rate_table[table] = table_times
        global_times.append(now)
        _unclear_rate_global[:] = global_times

    return True, "unclear"


def _purge_old_customer_audio(directory: Path, max_age_hours: int) -> None:
    if not directory.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for p in directory.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def save_customer_audio(audio_bytes: bytes, table: str) -> str:
    """Persist customer audio and return its /audio URL. Runs best-effort
    retention purge on each call."""
    directory = Path("static/audio/customer")
    directory.mkdir(parents=True, exist_ok=True)
    _purge_old_customer_audio(directory, UNCLEAR_AUDIO_RETENTION_HOURS)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    safe_table = "".join(ch for ch in (table or "") if ch.isalnum() or ch in ("-", "_")) or "unknown"
    filename = f"{safe_table}_{timestamp}.webm"
    path = directory / filename
    with open(path, "wb") as f:
        f.write(audio_bytes)
    return f"/audio/customer/{filename}"


def send_unclear_alert(table: str, text: str, audio_url=None):
    """Send the unclear-order Telegram alert with Handled/Left buttons.
    Never raises — returns alert_id or None."""
    try:
        alert_id = uuid.uuid4().hex[:8]
        with _unclear_lock:
            _unclear_alerts_pending[alert_id] = {
                "table": table,
                "text": text,
                "created_at": time.time(),
            }

        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        lines = [
            f"⚠️ TABLE {table} NEEDS WAITER",
            f"🕐 {time_str}",
            f"🎤 Customer said: \"{text}\"",
        ]
        if audio_url:
            lines.append(f"🔊 Audio: {audio_url}")
        message = "\n".join(lines)

        inline_keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Handled",
                 "callback_data": f"unclear_handled_{alert_id}"},
                {"text": "❌ Customer Left",
                 "callback_data": f"unclear_left_{alert_id}"},
            ]],
        }

        if CASHIER_CHAT_ID:
            send_message(CASHIER_CHAT_ID, message, reply_markup=inline_keyboard)
        if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
            send_message(OWNER_CHAT_ID, message, reply_markup=inline_keyboard)

        return alert_id
    except Exception as e:
        print(f"[Unclear] send_unclear_alert failed: {e}")
        return None


def log_unclear_event(kind: str, payload: dict) -> None:
    """Append a JSON line to logs/unclear_{resolved,lost}.jsonl."""
    try:
        Path("logs").mkdir(exist_ok=True)
        filename = "unclear_resolved.jsonl" if kind == "resolved" else "unclear_lost.jsonl"
        entry = dict(payload)
        entry["kind"] = kind
        entry["timestamp"] = datetime.now().isoformat()
        with open(Path("logs") / filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Unclear] log_unclear_event failed: {e}")


app = FastAPI(title="Khulafa Bistro API")

# Mount audio files for Aisha voice system
Path("static/audio/customer").mkdir(parents=True, exist_ok=True)
if os.path.exists("static/audio"):
    app.mount("/audio", StaticFiles(directory="static/audio"), name="audio")


# Auto-run database migration on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and run migrations on startup, then start Telegram bot"""
    # First, initialize the database (creates base tables + menu items)
    try:
        print("Initializing database...")
        import init_db
        init_db.init_database()
        print("Database initialized!")
    except Exception as e:
        print(f"Database initialization error: {e}")

    # Then run migrations (adds columns, extra tables, seed data)
    try:
        print("Running database migration...")
        import migrate_database
        migrate_database.migrate_database()
        print("Migration completed!")
    except Exception as e:
        print(f"Migration error (may already be done): {e}")

    try:
        print("Running voice tables migration...")
        import migrate_add_tables
        migrate_add_tables.migrate()
        print("Voice tables migration completed!")
    except Exception as e:
        print(f"Voice tables migration error (may already be done): {e}")

    # Start Telegram bot in background thread for button handling
    try:
        print("🚀 Starting Telegram bot in background...")
        bot_thread = Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        print("✅ Telegram bot started!")
    except Exception as e:
        print(f"❌ Error starting Telegram bot: {e}")

# CORS - Allow Telegram Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve frontend directly
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

@app.get("/static/index.html")
def read_index():
    return FileResponse("static/index.html")

# Create uploads directory
if not os.path.exists("uploads"):
    os.makedirs("uploads")

# Database helper
def get_db():
    conn = sqlite3.connect('khulafa_bistro.db')
    conn.row_factory = sqlite3.Row
    return conn

# Pydantic Models
class MenuItem(BaseModel):
    id: int
    name: str
    category: str
    price: float
    available: bool

class OrderItem(BaseModel):
    menu_item_id: int
    quantity: int
    note: Optional[str] = None

class CreateOrder(BaseModel):
    customer_telegram_id: str
    customer_name: str
    customer_phone: str
    order_type: str
    arrival_time: Optional[str] = None
    items: List[OrderItem]

class UpdateOrderStatus(BaseModel):
    status: str

# API Endpoints

@app.get("/api/")
async def root():
    return {"message": "Khulafa Bistro API is running!"}

@app.get("/api/menu")
async def get_menu():
    """Get all menu items grouped by category"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM menu_items WHERE available = 1 ORDER BY category, name')
    items = cursor.fetchall()

    # Group by category
    menu_by_category = {}
    for item in items:
        category = item['category']
        if category not in menu_by_category:
            menu_by_category[category] = []

        menu_by_category[category].append({
            'id': item['id'],
            'name': item['name'],
            'price': item['price'],
            'available': bool(item['available'])
        })

    conn.close()
    return {"menu": menu_by_category}

@app.post("/api/orders")
async def create_order(order: CreateOrder):
    """Create a new order"""
    conn = get_db()
    cursor = conn.cursor()

    # Generate order number
    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Calculate total price
    total_price = 0
    order_items_data = []

    for item in order.items:
        cursor.execute('SELECT price FROM menu_items WHERE id = ?', (item.menu_item_id,))
        menu_item = cursor.fetchone()
        if not menu_item:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Menu item {item.menu_item_id} not found")

        item_total = menu_item['price'] * item.quantity
        total_price += item_total
        order_items_data.append({
            'menu_item_id': item.menu_item_id,
            'quantity': item.quantity,
            'price': menu_item['price'],
            'note': item.note
        })

    # Insert order
    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, arrival_time, total_price, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, order.customer_telegram_id, order.customer_name, order.customer_phone,
          order.order_type, order.arrival_time, total_price, 'pending'))

    order_id = cursor.lastrowid

    # Insert order items
    for item_data in order_items_data:
        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, item_data['menu_item_id'], item_data['quantity'],
              item_data['price'], item_data['note']))

    conn.commit()
    conn.close()

    # Send order to Telegram group WITH BUTTONS
    order_text = f"🆕 NEW ORDER!\n\n"
    order_text += f"Order #: {order_number}\n"
    order_text += f"Customer: {order.customer_name}\n"
    order_text += f"Phone: {order.customer_phone}\n"
    order_text += f"Type: {order.order_type}\n\n"
    order_text += f"Items:\n"
    
    conn2 = get_db()
    cursor2 = conn2.cursor()
    for item_data in order_items_data:
        cursor2.execute('SELECT name FROM menu_items WHERE id = ?', (item_data['menu_item_id'],))
        menu_name = cursor2.fetchone()
        order_text += f"• {item_data['quantity']}x {menu_name['name']} - RM{item_data['price']*item_data['quantity']:.2f}"
        if item_data.get('note'):
            order_text += f"\n  📝 Note: {item_data['note']}"
        order_text += "\n"
    conn2.close()
    
    order_text += f"\nTOTAL: RM{total_price:.2f}"
    
    # Create inline keyboard with action buttons
    inline_keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Confirm Order",
                    "callback_data": f"confirm_{order_id}"
                },
                {
                    "text": "❌ Cancel Order",
                    "callback_data": f"cancel_{order_id}"
                }
            ],
            [
                {
                    "text": "🔔 Remind Payment",
                    "callback_data": f"remind_{order_id}"
                }
            ]
        ]
    }
    
    print(f"Sending order {order_number} to Telegram...")

    # Send to cashier with action buttons
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, order_text, reply_markup=inline_keyboard)

    # Also send to owner if configured and different from cashier
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, order_text, reply_markup=inline_keyboard)

    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "total_price": total_price
    }

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int):
    """Get order details"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()

    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    # Get order items
    cursor.execute('''
        SELECT oi.*, mi.name as item_name
        FROM order_items oi
        JOIN menu_items mi ON oi.menu_item_id = mi.id
        WHERE oi.order_id = ?
    ''', (order_id,))
    items = cursor.fetchall()

    conn.close()

    return {
        "order": dict(order),
        "items": [dict(item) for item in items]
    }

# NEW FEATURE: Cancel Order
@app.post("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: int):
    """Cancel an order - for fake or unpaid receipts"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Update order status to cancelled
    cursor.execute('''
        UPDATE orders 
        SET status = 'cancelled', 
            updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    conn.close()
    
    # Send cancellation notice to customer
    cancel_message = f"""❌ Order Cancelled

We're sorry, but your order has been cancelled.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

Reason: Payment not verified

If you believe this is an error or have already paid, please contact us directly with your payment proof.

Thank you for your understanding.
Khulafa Bistro 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], cancel_message)
        print(f"✅ Cancellation notice sent to customer")
    except Exception as e:
        print(f"Error sending cancellation notice: {e}")
    
    return {"success": True, "message": "Order cancelled successfully"}

# NEW FEATURE: Remind Payment
@app.post("/api/orders/{order_id}/remind")
async def remind_payment(order_id: int):
    """Send payment reminder to customer"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    conn.close()
    
    # Send payment reminder to customer
    reminder_message = f"""🔔 Payment Reminder

Hi {order['customer_name']},

We noticed your order is still pending payment verification.

📋 Order Details:
Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}
Type: {order['order_type']}

⚠️ Please upload your payment receipt as soon as possible.

If you have already paid, please upload a clear screenshot of your payment confirmation in the chat.

Thank you for choosing Khulafa Bistro! 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], reminder_message)
        print(f"✅ Payment reminder sent to customer")
        return {"success": True, "message": "Payment reminder sent successfully"}
    except Exception as e:
        print(f"Error sending payment reminder: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reminder")

@app.post("/api/orders/{order_id}/upload_payment")
async def upload_payment_slip(order_id: int, file: UploadFile = File(...)):
    """Upload payment slip"""
    # Save file
    file_ext = file.filename.split('.')[-1]
    filename = f"payment_{order_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_ext}"
    filepath = f"uploads/{filename}"

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    # Update order
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET payment_slip_url = ? WHERE id = ?', (filepath, order_id))
    conn.commit()

    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()

    # Send payment screenshot to Telegram group
    if TELEGRAM_API and CASHIER_CHAT_ID:
        print(f"[Telegram] Sending payment photo to CASHIER: {CASHIER_CHAT_ID}")
        try:
            with open(filepath, 'rb') as photo:
                resp = requests.post(
                    f"{TELEGRAM_API}/sendPhoto",
                    data={
                        'chat_id': CASHIER_CHAT_ID,
                        'caption': f"💳 Payment Receipt\nOrder #{order['order_number']}\nCustomer: {order['customer_name']}\nTotal: RM{order['total_price']:.2f}"
                    },
                    files={'photo': photo}
                )
                result = resp.json()
                if result.get("ok"):
                    print(f"[Telegram] ✅ Payment photo sent to CASHIER ({CASHIER_CHAT_ID})")
                else:
                    print(f"[Telegram] ❌ FAILED sending photo to CASHIER ({CASHIER_CHAT_ID}): "
                          f"[{result.get('error_code', '?')}] {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"[Telegram] ❌ Exception sending payment photo to CASHIER ({CASHIER_CHAT_ID}): {e}")

    # Also send payment photo to owner if configured and different from cashier
    if TELEGRAM_API and OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        print(f"[Telegram] Sending payment photo to OWNER: {OWNER_CHAT_ID}")
        try:
            with open(filepath, 'rb') as photo:
                resp = requests.post(
                    f"{TELEGRAM_API}/sendPhoto",
                    data={
                        'chat_id': OWNER_CHAT_ID,
                        'caption': f"💳 Payment Receipt\nOrder #{order['order_number']}\nCustomer: {order['customer_name']}\nTotal: RM{order['total_price']:.2f}"
                    },
                    files={'photo': photo}
                )
                result = resp.json()
                if result.get("ok"):
                    print(f"[Telegram] ✅ Payment photo sent to OWNER ({OWNER_CHAT_ID})")
                else:
                    print(f"[Telegram] ❌ FAILED sending photo to OWNER ({OWNER_CHAT_ID}): "
                          f"[{result.get('error_code', '?')}] {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"[Telegram] ❌ Exception sending payment photo to OWNER ({OWNER_CHAT_ID}): {e}")

    # Send confirmation to customer
    customer_message = f"""✅ Payment Receipt Received!

Thank you for your payment!

📋 Order Details:
Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}
Type: {order['order_type']}

Your order is now being prepared! 🍳

We will notify you when it's ready.

Thank you for choosing Khulafa Bistro! 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], customer_message)
        print(f"Confirmation sent to customer")
    except Exception as e:
        print(f"Error sending customer confirmation: {e}")

    return {"success": True, "filepath": filepath, "message": "Payment received! You will be notified when your order is ready."}

@app.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get a setting value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="Setting not found")

    return {"key": key, "value": result['value']}

@app.put("/api/settings/{key}")
async def update_setting(key: str, value: str):
    """Update a setting value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

    return {"success": True, "key": key, "value": value}

@app.post("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, update: UpdateOrderStatus):
    """Update order status"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                   (update.status, order_id))
    conn.commit()

    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()

    # Send notification to customer
    if order:
        send_customer_notification(order['customer_telegram_id'], order, update.status)

    return {"success": True}

@app.post("/api/orders/{order_id}/confirm_payment")
async def confirm_payment(order_id: int):
    """Confirm payment"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET payment_confirmed = 1 WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()

    return {"success": True}

# Telegram Helper Functions
def send_message(chat_id, text, reply_markup=None):
    """Send a Telegram message"""
    if not BOT_TOKEN:
        print("❌ Cannot send Telegram message: TELEGRAM_BOT_TOKEN not set")
        return None
    if not chat_id:
        print("❌ Cannot send Telegram message: chat_id is empty")
        return None

    # Identify which recipient this is for
    recipient_label = "unknown"
    if str(chat_id) == str(CASHIER_CHAT_ID):
        recipient_label = "CASHIER"
    elif str(chat_id) == str(OWNER_CHAT_ID):
        recipient_label = "OWNER"
    else:
        recipient_label = "CUSTOMER"

    print(f"[Telegram] Sending to {recipient_label}: {chat_id}")

    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload)
        result = response.json()
        if result.get("ok"):
            print(f"[Telegram] ✅ Message sent successfully to {recipient_label} ({chat_id})")
        else:
            error_code = result.get("error_code", "?")
            description = result.get("description", "Unknown error")
            print(f"[Telegram] ❌ FAILED to send to {recipient_label} ({chat_id}): [{error_code}] {description}")
            if error_code == 403:
                print(f"[Telegram] ⚠️ Bot was blocked or /start was never sent by chat_id {chat_id}. "
                      f"The user must send /start to the bot first!")
        return result
    except Exception as e:
        print(f"[Telegram] ❌ Exception sending to {recipient_label} ({chat_id}): {e}")
        return None

def send_customer_notification(customer_telegram_id: str, order, status: str):
    """Send status update to customer"""
    status_messages = {
        "preparing": "🍳 Your order is being prepared!",
        "ready": "✅ Your order is ready!",
        "completed": "✅ Order completed. Thank you!"
    }

    message = status_messages.get(status, f"Status updated: {status}")
    message += f"\n\nOrder: {order['order_number']}"
    message += f"\nTotal: RM {order['total_price']:.2f}"

    if status == "ready":
        if order['order_type'] == "pickup":
            message += "\n\n📍 Please come to collect your order!"
        else:
            message += "\n\n🍽️ Your table is ready! Please come in!"

    send_message(customer_telegram_id, message)

# Telegram Bot Handler for Buttons
async def handle_telegram_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from Telegram group"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    print(f"🔘 Button clicked: {callback_data}")

    try:
        if callback_data.startswith("unclear_handled_") or callback_data.startswith("unclear_left_"):
            await _handle_unclear_callback(query, callback_data)
            return

        action, order_id = callback_data.split('_')
        order_id = int(order_id)
        
        if action == "cancel":
            print(f"Cancelling order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
            order = cursor.fetchone()
            
            if order:
                cursor.execute('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
                             ('cancelled', order_id))
                conn.commit()
                conn.close()
                
                # Notify customer
                cancel_msg = f"""❌ Order Cancelled

We're sorry, your order has been cancelled.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

Reason: Payment not verified

Please contact us if you have questions.
Khulafa Bistro 🌟"""
                
                send_message(order['customer_telegram_id'], cancel_msg)
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ ORDER CANCELLED ❌\nCustomer notified.")
                print(f"✅ Order {order_id} cancelled")
        
        elif action == "remind":
            print(f"Sending reminder for order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
            order = cursor.fetchone()
            conn.close()
            
            if order:
                reminder_msg = f"""🔔 Payment Reminder

Hi {order['customer_name']},

Your order is pending payment verification.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

⚠️ Please upload your payment receipt ASAP.

Thank you!
Khulafa Bistro 🌟"""
                
                send_message(order['customer_telegram_id'], reminder_msg)
                await query.edit_message_text(text=f"{query.message.text}\n\n🔔 REMINDER SENT ✅\nCustomer reminded.")
                print(f"✅ Reminder sent for order {order_id}")
        
        elif action == "confirm":
            print(f"Confirming order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE orders SET payment_confirmed = 1 WHERE id = ?', (order_id,))
            conn.commit()
            conn.close()
            
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ ORDER CONFIRMED ✅\nPayment verified.")
            print(f"✅ Order {order_id} confirmed")
    
    except Exception as e:
        print(f"❌ Error handling button: {e}")
        await query.edit_message_text(text=f"{query.message.text}\n\n⚠️ Error: {str(e)}")


async def _handle_unclear_callback(query, callback_data: str):
    """Handle ✅ Handled / ❌ Customer Left clicks on unclear-order alerts."""
    try:
        if callback_data.startswith("unclear_handled_"):
            kind = "resolved"
            alert_id = callback_data[len("unclear_handled_"):]
        elif callback_data.startswith("unclear_left_"):
            kind = "lost"
            alert_id = callback_data[len("unclear_left_"):]
        else:
            return

        with _unclear_lock:
            pending = _unclear_alerts_pending.pop(alert_id, None)

        user = getattr(query, "from_user", None)
        username = (user.username if user and getattr(user, "username", None)
                    else (user.first_name if user and getattr(user, "first_name", None)
                          else "unknown"))

        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        base_text = ""
        if getattr(query, "message", None) and getattr(query.message, "text", None):
            base_text = query.message.text

        if pending is None:
            new_text = f"{base_text}\n\n⚠️ Alert expired or unknown."
            try:
                await query.edit_message_text(text=new_text)
            except Exception as e:
                print(f"[Unclear] edit_message_text failed: {e}")
            return

        if kind == "resolved":
            duration = int(time.time() - pending["created_at"])
            new_text = (f"{base_text}\n\n"
                        f"✅ RESOLVED by @{username} at {time_str} ({duration}s)")
            log_unclear_event("resolved", {
                "alert_id": alert_id,
                "table": pending["table"],
                "text": pending["text"],
                "resolver": username,
                "duration_seconds": duration,
            })
        else:
            new_text = (f"{base_text}\n\n"
                        f"❌ CUSTOMER LEFT — reported by @{username}")
            log_unclear_event("lost", {
                "alert_id": alert_id,
                "table": pending["table"],
                "text": pending["text"],
                "reporter": username,
            })

        try:
            await query.edit_message_text(text=new_text)
        except Exception as e:
            print(f"[Unclear] edit_message_text failed: {e}")
    except Exception as e:
        print(f"[Unclear] _handle_unclear_callback error: {e}")


# Run Telegram Bot in Background
def run_telegram_bot():
    """Run Telegram bot to handle button clicks"""
    if not BOT_TOKEN:
        print("❌ Cannot start Telegram bot: TELEGRAM_BOT_TOKEN not set")
        return

    async def start_bot():
        try:
            application = Application.builder().token(BOT_TOKEN).build()
            application.add_handler(CallbackQueryHandler(handle_telegram_buttons))
            print("🤖 Telegram bot started - Ready to handle button clicks!")
            # Use stop_signals=None to avoid signal handler issues in background thread
            await application.initialize()
            await application.start()
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            # Keep running
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ Bot error: {e}")

    # Run in new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot())

# ========== Voice QR Ordering Routes ==========

class VoiceOrderItem(BaseModel):
    name: str
    quantity: int
    price: float
    modifiers: List[str] = []

class VoiceSubmitOrder(BaseModel):
    table_number: str
    items: List[VoiceOrderItem]
    total: float

@app.get("/table/{table_number}")
async def serve_voice_page(table_number: str):
    """Verify table exists and serve voice ordering page."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM restaurant_tables WHERE table_number = ?', (table_number,))
    table = cursor.fetchone()
    conn.close()

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    return FileResponse("static/voice.html")

@app.post("/api/voice/chat")
async def voice_chat(request: Request, background_tasks: BackgroundTasks):
    """
    Dual AI Pipeline:
    STEP 1 - DeepSeek: Intent extraction & fuzzy menu matching from raw speech
    STEP 2 - Qwen Max: Natural Aisha conversation response

    Non-ordering messages (greetings, confirmations, cancel) skip DeepSeek
    and go straight to Qwen Max.
    """
    import json as json_lib
    import re

    body = await request.json()
    speech = body.get("message", "")
    alternatives = body.get("alternatives", [])
    current_order = body.get("order", [])
    table = body.get("table_number", "T01")
    upsell_pending = body.get("upsell_pending")  # {item, upsell_item, upsell_price}

    from order_engine import MENU, AUDIO_RESPONSES

    # ── Handle upsell yes/no response ──
    if upsell_pending:
        speech_lower = speech.lower().strip()
        accept_patterns = r"\b(ya|ok|okay|boleh|nak|yes|mau|tambah|try|jom|can)\b"
        decline_patterns = r"\b(tak|takpe|taknak|tidak|no|cukup|skip|pass|sudah|jangan)\b"

        accepted = bool(re.search(accept_patterns, speech_lower))
        declined = bool(re.search(decline_patterns, speech_lower))

        upsell_item_name = upsell_pending.get("upsell_item", "")
        upsell_item_key = upsell_item_name.lower().strip()

        updated_order = list(current_order)

        if accepted and not declined:
            # Add the upsell item to order
            if upsell_item_key in MENU:
                menu_item = MENU[upsell_item_key]
                new_upsell = {
                    "name": upsell_item_key.title(),
                    "qty": 1,
                    "price": menu_item["price"],
                    "modifiers": [],
                }
                updated_order.append(new_upsell)
                total = sum(i["price"] * i["qty"] for i in updated_order)
                reply = f"Okay, {upsell_item_key.title()} ditambah! Ada lagi?"
                # Use pre-recorded accept audio (UP_109)
                accept_audio = get_general_response_audio("accept")
                audio_matches = []
                if accept_audio:
                    audio_matches.append({"audio_path": accept_audio["audio_path"], "audio_exists": True, "is_upsell": True})
                if menu_item.get("audio_id"):
                    audio_matches.append({"audio_path": f"/audio/wavs/{menu_item['audio_id']}.wav", "audio_exists": True})
                audio_matches.append({"audio_path": "/audio/wavs/0043.wav", "audio_exists": True})
                return {
                    "text": reply,
                    "audio_matches": audio_matches,
                    "has_audio": len(audio_matches) > 0,
                    "action": "add_items",
                    "new_items": [new_upsell],
                    "extracted_items": [upsell_item_key],
                    "order": updated_order,
                    "total": total,
                    "pipeline": "upsell_accept",
                    "upsell_accepted": True,
                }
            else:
                reply = f"Maaf, {upsell_item_name} tiada dalam menu. Ada lagi?"
        else:
            reply = "Okay, takpe! Ada lagi?"

        total = sum(i["price"] * i["qty"] for i in updated_order)
        # Use pre-recorded decline audio (UP_110 or UP_111 for tak nak)
        decline_type = "tak_nak" if re.search(r"\b(tak\s*nak|taknak)\b", speech_lower) else "reject"
        decline_audio = get_general_response_audio(decline_type)
        decline_audio_matches = []
        if decline_audio:
            decline_audio_matches.append({"audio_path": decline_audio["audio_path"], "audio_exists": True, "is_upsell": True})
        else:
            decline_audio_matches.append({"audio_path": "/audio/wavs/0043.wav", "audio_exists": True})
        return {
            "text": reply,
            "audio_matches": decline_audio_matches,
            "has_audio": True,
            "action": "upsell_declined",
            "new_items": [],
            "extracted_items": [],
            "order": updated_order,
            "total": total,
            "pipeline": "upsell_decline",
            "upsell_accepted": False,
        }

    qwen_client = get_qwen_client()
    model = os.getenv("QWEN_MODEL", "qwen-max")

    # ── Detect if this is an ordering message or a non-ordering message ──
    # Non-ordering: greetings, confirmations, cancellations, questions, etc.
    speech_lower = speech.lower().strip()

    NON_ORDER_PATTERNS = [
        # Confirmations / end-of-order
        r"\b(tu\s*je|tu\s*jer|itu\s*je|cukup|dah|sekian|confirm|settle|setel|hantar)\b",
        # Cancel / remove / change
        r"\b(cancel|batal|tak\s*jadi|tak\s*nak|remove|buang|padam|tukar|ubah|salah|mula\s*balik|start\s*over)\b",
        # Greetings
        r"\b(hi|hello|helo|hey|assalamualaikum|salam|selamat)\b",
        # Questions about menu / recommendations
        r"\b(apa\s+yang|recommend|cadang|menu|senarai)\b",
        # Yes/No responses
        r"^(ya|yes|ok|okay|tidak|tak|no)\s*$",
        # Thank you
        r"\b(terima\s*kasih|thank|thanks|tq)\b",
    ]

    is_ordering = True
    for pattern in NON_ORDER_PATTERNS:
        if re.search(pattern, speech_lower):
            is_ordering = False
            break

    # ── STEP 1: DeepSeek Intent Extraction (only for ordering messages) ──
    deepseek_result = None

    if is_ordering:
        deepseek_client = get_deepseek_client()
        if deepseek_client:
            menu_list_str = "\n".join([f"- {name}" for name in MENU.keys()])

            # Build enhanced message with all speech alternatives
            if alternatives and len(alternatives) > 1:
                alt_text = " | ".join([
                    f'"{a["text"]}" ({a.get("confidence", 0):.0%})'
                    if isinstance(a, dict) else f'"{a}"'
                    for a in alternatives
                ])
                alt_section = f"\nSpeech recognition alternatives (use ALL to determine correct items):\n{alt_text}"
            else:
                alt_section = ""

            deepseek_prompt = f"""You are a food order extraction AI for Khulafa Bistro, a Malaysian mamak restaurant.

IMPORTANT: Customer is ordering via voice. Speech recognition may mishear words.
You will receive multiple speech alternatives — use ALL of them to determine the correct menu item.
Always match to the closest menu item. If unsure, ask customer to repeat. Never guess randomly.

Common mishearings in Malay speech recognition:
- "main"/"man"/"magic"/"major"/"mega" = "maggi"
- "going"/"goring" = "goreng"
- "camping"/"coming" = "kambing"
- "green"/"me going" = "mee goreng"
- "me"/"mi"/"mie"/"ming"/"meet"/"meer"/"ming" = "mee"
- "queen teow"/"key toe"/"kway teow" = "kuey teow"
- "non"/"nun"/"nan"/"none" = "naan"
- "batu"/"batter" = "butter"
- "galic"/"gali" = "garlic"
- "aming"/"ayang"/"i am"/"eye am" = "ayam"
- "nancy"/"nan si" = "naan cheese"
- "non batu galic" = "naan butter garlic"
- "roti canal"/"roti cana"/"roti channel" = "roti canai"
- "teh tariq"/"the tarik"/"tea tarik"/"teh trick" = "teh tarik"
- "nasi lemak" = "nasi lemak bungkus"
- "mi goreng"/"mie goreng"/"minggu ring"/"minggu ni"/"mingu ni"/"minggu"/"mingu" = "mee goreng"
- "main goreng" = could be "maggi goreng" or "mee goreng" (use context to decide)
- "maggie"/"megi"/"meggi"/"mackey" = "maggi"
- "bee hun"/"bi hun"/"mihun" = "bihun"
- "kuay teow"/"koay teow"/"char kuey teow"/"kuey tiau"/"kuetiau"/"kway tiaw"/"kwetiau" = "kuey teow goreng"
- "indo mee"/"indo mi"/"indomie" = "indomee"
- "die ging"/"dye ging" = "daging"
- "running"/"rending" = "rendang"
- "my sir"/"my sir" = "mysur"
- "roti channel"/"roti chenai" = "roti canai"
- "martabak" = "murtabak"
- "biryani"/"beriani" = "briyani"
- "my low"/"mi lo"/"mellow" = "milo"
- "melo ice"/"milo ice" = "milo ais"
- "copy ice"/"coffee ice"/"kopi ice" = "kopi ais"
- "copy"/"coffee" = "kopi panas"
- "banding"/"bandong"/"ban dong"/"min bandung" = "bandung"
- "sir up"/"serap"/"syrup" = "sirap"
- "barley"/"bali"/"barely" = "barli"
- "air crossing"/"air kosmos" = "air kosong"
- "chin chow"/"chin chou"/"cincao" = "cincau"
- "long an"/"long gone" = "longan"

NOODLE ITEMS ON MENU (these are ALL valid - never say they are unavailable):
- maggi goreng, maggi goreng mamak, maggi goreng ayam, maggi goreng daging, maggi goreng kambing
- maggi tomyam, maggi sup
- mee goreng, mee goreng mamak, mee goreng ayam, mee goreng daging, mee goreng seafood
- mee rebus, mee sup, mee campur bihun
- bihun goreng, bihun goreng mamak, bihun sup
- kuey teow goreng, kuey teow goreng mamak, kuey teow tomyam
- indomee goreng, indomee double, indomee kosong

DRINK ITEMS ON MENU (these are ALL valid - never say they are unavailable):
- milo ais, milo panas
- teh tarik, teh ais
- kopi ais, kopi panas
- bandung, bandung ais, bandung panas
- sirap ais, sirap panas
- barli ais, barli panas
- air kosong, air mineral
- cincau, longan

FUZZY MATCHING RULES:
- If customer says a partial name like "min bandung", match to "bandung"
- If customer says multiple drink keywords in one phrase like "sirap ais barli", extract MULTIPLE items: "sirap ais" AND "barli ais"
- Always prefer the longest matching menu item name
- If customer says just "milo" without hot/cold, default to "milo ais"
- If customer says just "kopi" without hot/cold, default to "kopi panas"
- If customer says just "barli" without hot/cold, default to "barli ais"
- If customer says just "sirap" without hot/cold, default to "sirap ais"

COMMON ORDERS (prioritize these when ambiguous):
ais kosong, teh o ais, roti canai, teh, nasi ayam, teh ais, milo ais, air suam, nasi ayam sayur, roti telur, ayam goreng, nasi ayam bawang, telur mata, teh o, naan mozzerella cheese, nasi goreng ayam, mee goreng mamak, teh o limau ais, nasi ayam bawang sayur, nasi putih, nasi goreng kampung, maggi goreng, limau ais, extra joss angur, maggi goreng telur mata, ayam tandoori, roti bakar, naan biasa, nasi lemak bungkus, telur masin

MALAY NUMBER WORDS: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, sembilan=9, sepuluh=10

CUSTOMER SPECIAL REQUESTS & MODIFIERS:
Customers frequently add modifiers to their orders. You MUST capture these as "modifiers" in the JSON output.

SWEETNESS MODIFIERS:
- "kurang manis" = less sugar
- "tak nak manis" / "tanpa gula" / "kosong" (for drinks) = no sugar
- "manis" / "lebih manis" = extra sweet
- "sikit manis" / "sikit je manis" = just a little sweet

STRENGTH/THICKNESS MODIFIERS (drinks):
- "kaw" / "kow" / "pekat" = strong/thick (extra concentrated)
- "cair" / "ringan" = diluted/light/weak

TEMPERATURE MODIFIERS:
- "kurang ais" / "sikit ais" = less ice
- "tak nak ais" / "tanpa ais" = no ice
- "banyak ais" / "extra ice" = extra ice
- "panas" / "hot" = hot
- "suam" / "warm" = warm/lukewarm

MILK MODIFIERS (for teh/kopi/milo/nescafe):
- "tarik" = pulled with condensed milk (frothy)
- "tabur" = powder sprinkled on top (for Milo/Nescafe)
- "dinosaur" / "dino" = iced milo + extra milo powder on top

SIZE MODIFIERS:
- "besar" / "jumbo" / "large" = large size
- "kecil" / "small" = small size

FOOD EXCLUSIONS (tak nak / remove):
- "tak nak sayur" = no vegetables
- "tak nak biji" = no seeds/tapioca pearls
- "tak nak timun" = no cucumber
- "tak nak kacang" = no peanuts/beans
- "tak nak sambal" = no sambal
- "tak nak telur" = no egg
- "tak nak bawang" = no onion
- "tak nak cili" = no chili
- "tak nak kuah" / "kering" = no gravy / dry
- "tanpa ___" = without ___

FOOD ADDITIONS (tambah / extra):
- "tambah telur" = add egg
- "tambah sambal" = extra sambal
- "tambah sayur" = extra vegetables
- "extra ___" / "lebih ___" = extra ___
- "double" = double portion
- "tambah cheese" / "tambah keju" = add cheese
- "tambah daging" = add meat

SPICINESS MODIFIERS:
- "pedas" = spicy
- "kurang pedas" = less spicy
- "tak nak pedas" / "tak pedas" = not spicy
- "extra pedas" / "pedas gila" = extra spicy

COOKING PREFERENCES:
- "garing" / "crispy" = crispy (for roti, ayam)
- "lembut" = soft
- "well done" / "masak betul" = well cooked
- "setengah masak" = half cooked (for eggs)

GENERAL MODIFIER PATTERNS:
- "kurang ___" = less of something
- "tak nak ___" / "tanpa ___" = without / remove something
- "tambah ___" / "extra ___" / "lebih ___" = add more of something
- "sikit ___" = a little bit of something
- "banyak ___" = a lot of something

IMPORTANT: Modifiers are words/phrases that describe HOW the customer wants the item prepared, NOT the item name itself. Do NOT include modifiers in the "matched_item" field. Only capture modifiers that are NOT already part of the menu item name.

MENU:
{menu_list_str}

Return ONLY a JSON array of matched items. Each element:
{{"matched_item": "exact menu item name", "quantity": number, "confidence": float 0-1, "modifiers": ["modifier1", "modifier2"]}}

If no modifiers, return empty array: "modifiers": []

EXAMPLES:
Input: "satu teh tarik kurang manis"
Output: [{{"matched_item": "teh tarik", "quantity": 1, "confidence": 0.95, "modifiers": ["kurang manis"]}}]

Input: "milo ais kaw satu, roti canai garing dua"
Output: [{{"matched_item": "milo ais", "quantity": 1, "confidence": 0.95, "modifiers": ["kaw"]}}, {{"matched_item": "roti canai", "quantity": 2, "confidence": 0.95, "modifiers": ["garing"]}}]

Input: "nasi goreng tak nak pedas tambah telur"
Output: [{{"matched_item": "nasi goreng biasa", "quantity": 1, "confidence": 0.9, "modifiers": ["tak nak pedas", "tambah telur"]}}]

Input: "milo dinosaur satu"
Output: [{{"matched_item": "milo ais", "quantity": 1, "confidence": 0.95, "modifiers": ["dinosaur"]}}]

If multiple items are ordered, return multiple elements.
If unclear or no confident match (confidence < 0.6), return: [{{"matched_item": "", "quantity": 0, "confidence": 0, "modifiers": [], "needs_clarification": true, "heard_text": "what you heard"}}]
NEVER guess randomly — only match items you are confident about.

Customer said: "{speech}"{alt_section}
Pick the most likely correct menu items from these alternatives."""

            print(f"[Whisper] Raw text: {speech}")
            try:
                ds_response = deepseek_client.chat.completions.create(
                    model="deepseek-chat",
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": "You extract structured food orders from messy speech transcripts. The customer orders via voice and speech recognition may mishear Malay food words. You receive multiple speech alternatives — use ALL of them to determine the correct menu items. Return ONLY valid JSON arrays, nothing else."},
                        {"role": "user", "content": deepseek_prompt}
                    ]
                )

                ds_raw = ds_response.choices[0].message.content.strip()
                # Parse DeepSeek JSON response
                try:
                    deepseek_result = json_lib.loads(ds_raw)
                except json_lib.JSONDecodeError:
                    # Try extracting JSON array from response
                    arr_match = re.search(r'\[.*\]', ds_raw, re.DOTALL)
                    if arr_match:
                        deepseek_result = json_lib.loads(arr_match.group())

                # Normalize to list
                if isinstance(deepseek_result, dict):
                    deepseek_result = [deepseek_result]

                print(f"[DeepSeek] Extracted: {deepseek_result}")
            except Exception as e:
                print(f"[DeepSeek] Error: {e} - falling back to Qwen-only")
                deepseek_result = None

    # ── Unclear-order fallback (Change 4) ──
    # Alerts cashier+waiter via Telegram when DeepSeek signals low confidence.
    # Fires in background so customer-facing latency is unaffected.
    try:
        should_alert, alert_reason = should_trigger_unclear_fallback(
            table, speech, deepseek_result)
        if should_alert:
            audio_bytes = _pop_transcribe_audio(table, speech)
            audio_url = save_customer_audio(audio_bytes, table) if audio_bytes else None
            background_tasks.add_task(send_unclear_alert, table, speech, audio_url)
            print(f"[Unclear] Fallback queued (table={table}, audio={'yes' if audio_url else 'no'})")
        elif alert_reason not in ("clear_match", "empty_text", "single_word"):
            print(f"[Unclear] Suppressed: {alert_reason}")
    except Exception as e:
        print(f"[Unclear] Trigger check failed (non-blocking): {e}")

    # ── STEP 2: Look up upsell suggestions for extracted items ──
    upsell_context = ""
    upsell_suggestions = []
    if deepseek_result and is_ordering:
        upsell_engine = get_upsell_engine()
        for ds_item in deepseek_result:
            item_name = ds_item.get("matched_item", "").lower().strip()
            if item_name:
                suggestion = upsell_engine.get_upsell(item_name)
                if suggestion:
                    upsell_suggestions.append(suggestion)

        if upsell_suggestions:
            upsell_lines = []
            for s in upsell_suggestions:
                upsell_lines.append(
                    f"- {s['original'].title()} (RM{s['original_price']:.2f}) → "
                    f"SUGGEST: {s['upsell_display']} (RM{s['upsell_price']:.2f})"
                )
            upsell_context = "\n".join(upsell_lines)

    # ── STEP 3: Qwen Max Conversation Response ──
    if deepseek_result and is_ordering:
        # Build a structured prompt for Qwen using DeepSeek's extraction
        extracted_items = []
        for item in deepseek_result:
            name = item.get("matched_item", "")
            qty = item.get("quantity", 1)
            confidence = item.get("confidence", 0)
            modifiers = item.get("modifiers", [])
            if name:
                qty_str = f" x{qty}" if qty > 1 else ""
                mod_str = f" [{', '.join(modifiers)}]" if modifiers else ""
                extracted_items.append(f"{name}{qty_str}{mod_str} (confidence: {confidence})")

        items_summary = ", ".join(extracted_items) if extracted_items else "unclear"

        # Build upsell instruction block for the prompt
        upsell_instruction = ""
        if upsell_context:
            upsell_instruction = f"""

UPSELL RECOMMENDATIONS (IMPORTANT — you MUST include ONE upsell in your reply):
{upsell_context}

After confirming the customer's order, ALWAYS suggest ONE upgrade from the list above.
Use casual mamak Malay style: "sedap jugak!", "nak try?", "lagi best!"
Example: Customer orders Maggi Goreng → "Maggi Goreng satu! Nak try Maggi Goreng Kambing? Lagi power!"
- Confirm order FIRST, then add upsell suggestion
- Only ONE upsell suggestion per response
- Keep it natural and friendly"""

        qwen_prompt = f"""You are Aisha, AI waitress for Khulafa Bistro.

RULES:
- Confirm what customer ordered first
- Keep responses SHORT - max 2 sentences
- When an item has modifiers (e.g. kurang manis, kaw, garing), ALWAYS mention them in the reply
- Example with modifiers: "Okay, satu Milo Ais kaw dan dua Roti Canai garing. Ada lagi?"
- NEVER say "Kami ada...", "Cuba juga...", "Mungkin nak try...", "Boleh cuba..."
- NEVER list menu categories or suggest promotions
- IMPORTANT: If the item exists in the menu list below, NEVER say it is unavailable
{upsell_instruction}

The customer said: "{speech}"
Our order extraction system detected these items: {items_summary}

MENU ITEMS AVAILABLE:
{chr(10).join([f"- {name}" for name in MENU.keys()])}

TASK:
- Match the extracted items to the closest menu item names
- Confirm items then {"include the upsell suggestion" if upsell_context else "say 'Ada lagi?'"}
- ALWAYS include modifiers in the reply (e.g. "kurang manis", "kaw", "garing", "tak nak pedas")

RESPONSE FORMAT - Always respond in this EXACT JSON, nothing else:
{{"items": ["item1", "item2"], "quantities": [1, 2], "action": "add", "reply": "Baiklah, [items]. Nak try [upsell]? Lagi sedap!"}}

IMPORTANT:
- "items" array = lowercase exact menu item names (only what customer ordered, NOT the upsell)
- "quantities" array = quantity for each item (same order as items array)
- "action" must be "add"
- Always respond with valid JSON only"""

    else:
        # Non-ordering: greetings, confirmations, cancel etc go straight to Qwen
        order_list_str = ""
        if current_order:
            order_list_str = ", ".join([f"{i.get('name','')} x{i.get('qty',1)}" for i in current_order])

        qwen_prompt = f"""You are Aisha, AI waitress for Khulafa Bistro.

STRICT RULES:
- NEVER recommend or suggest menu items on your own
- ONLY confirm what customer ordered and say "Ada lagi?"
- Keep responses SHORT - max 1 sentence
- NEVER say "Kami ada...", "Cuba juga...", "Mungkin nak try...", "Boleh cuba...", "Nak tambah..."
- NEVER mention any food item the customer did NOT order
- The "reply" field must ONLY contain what the customer ordered + "Ada lagi?" — nothing else

CURRENT ORDER: {json_lib.dumps(current_order) if current_order else "empty"}

The customer said: "{speech}"

Handle this naturally:
- Greetings: "Hai! Nak order apa?"
- Confirmations (tu je/cukup/dah/hantar/confirm/settle/setel/sekian): "Terima kasih! Pesanan sudah dihantar."
- Questions: answer briefly
- If ordering food, match to menu items

CANCEL/CHANGE HANDLING:
- If customer says "cancel", "batalkan", "tak nak", "buang", "remove" WITHOUT specifying an item:
  - If order is empty: {{"items": [], "quantities": [], "action": "cancel_request", "reply": "Tiada item untuk dibatalkan."}}
  - If order has items: {{"items": [], "quantities": [], "action": "cancel_request", "reply": "Nombor mana nak batalkan?"}}
- If customer says "cancel [item]", "buang [item]", "batalkan [item]", "tak nak [item]":
  {{"items": ["item name to cancel"], "quantities": [1], "action": "cancel_item", "reply": "Okay, [item] dah dibuang. Ada lagi?"}}
- If customer says "tukar [old] kepada [new]", "change [old] to [new]", "ubah [old] jadi [new]":
  {{"items": ["old item", "new item"], "quantities": [1, 1], "action": "change_item", "reply": "Okay, [old] ditukar kepada [new]. Ada lagi?"}}
- If customer says "cancel semua", "buang semua", "mula balik", "start over":
  {{"items": [], "quantities": [], "action": "cancel_all", "reply": "Semua dah dibuang. Nak order apa?"}}
- If customer says a number like "nombor 1", "nombor 2", "yang pertama", "yang kedua":
  {{"items": ["nombor X"], "quantities": [1], "action": "cancel_by_index", "reply": "Okay, [item] dah dibuang. Ada lagi?"}}

RESPONSE FORMAT - Always respond in this EXACT JSON, nothing else:

When customer orders items:
{{"items": ["roti canai"], "quantities": [1], "action": "add", "reply": "Baiklah, Roti Canai. Ada lagi?"}}

When customer confirms order:
{{"items": [], "quantities": [], "action": "confirm", "reply": "Terima kasih! Pesanan sudah dihantar."}}

When customer cancels (general):
{{"items": [], "quantities": [], "action": "cancel_request", "reply": "Nombor mana nak batalkan?"}}

When greeting or unclear:
{{"items": [], "quantities": [], "action": "greeting", "reply": "your response"}}

IMPORTANT: Always respond with valid JSON only - no extra text."""

    # Build user message with structured alternatives for better accuracy
    user_msg = speech
    if alternatives:
        # Handle both new format [{text, confidence}] and legacy [string] format
        alt_parts = []
        for a in alternatives:
            if isinstance(a, dict):
                text = a.get("text", "")
                conf = a.get("confidence", 0)
                if text and text != speech:
                    alt_parts.append(f'"{text}" ({conf:.0%})')
            elif a and a != speech:
                alt_parts.append(f'"{a}"')
        if alt_parts:
            user_msg = f'{speech} (speech alternatives: {" | ".join(alt_parts)})'

    response = qwen_client.chat.completions.create(
        model=model,
        max_tokens=100,  # Short responses = faster
        messages=[
            {"role": "system", "content": qwen_prompt},
            {"role": "user", "content": user_msg}
        ],
        extra_body={"enable_thinking": False}
    )

    # Parse Qwen response
    raw = response.choices[0].message.content.strip()
    try:
        data = json_lib.loads(raw)
    except json_lib.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                data = json_lib.loads(match.group())
            except json_lib.JSONDecodeError:
                data = {"items": [], "quantities": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}
        else:
            data = {"items": [], "quantities": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}

    items = data.get("items", [])
    quantities = data.get("quantities", [])
    action = data.get("action", "unclear")
    reply = _strip_recommendations(data.get("reply", ""))

    # Pad quantities to match items length (default qty=1)
    while len(quantities) < len(items):
        quantities.append(1)

    # Build modifiers lookup from DeepSeek result
    deepseek_modifiers = {}
    if deepseek_result:
        for ds_item in deepseek_result:
            ds_name = ds_item.get("matched_item", "").lower().strip()
            ds_mods = ds_item.get("modifiers", [])
            if ds_name and ds_mods:
                deepseek_modifiers[ds_name] = ds_mods

    # ── VALIDATION LAYER: Ground every item against the real menu ──
    # Build extracted_items list for the validator (merge Qwen items + DeepSeek data)
    items_for_validation = []
    for idx, item_name in enumerate(items):
        item_lower = item_name.lower().strip()
        qty = quantities[idx] if idx < len(quantities) else 1
        mods = deepseek_modifiers.get(item_lower, [])
        items_for_validation.append({
            "matched_item": item_lower,
            "quantity": qty,
            "confidence": 0.9,
            "modifiers": mods,
        })

    # Also validate DeepSeek items that Qwen may have missed
    if deepseek_result and is_ordering:
        qwen_item_names = {i.lower().strip() for i in items}
        for ds_item in deepseek_result:
            ds_name = ds_item.get("matched_item", "").lower().strip()
            if ds_name and ds_name not in qwen_item_names:
                # DeepSeek found an item Qwen missed — include it
                items_for_validation.append(ds_item)

    validation_result = validate_order_items(items_for_validation)

    # Build audio_matches and new_items from VALIDATED items only
    audio_matches = []
    new_items = []

    for vi in validation_result["valid_items"]:
        menu_item = MENU[vi["item_key"]]
        if menu_item["audio_id"]:
            audio_matches.append({"audio_path": f"/audio/wavs/{menu_item['audio_id']}.wav", "audio_exists": True})
        new_items.append({
            "name": vi["item_key"].title(),
            "qty": vi["quantity"],
            "price": vi["price"],
            "modifiers": vi["modifiers"],
        })
        if vi.get("corrected_from"):
            print(f"[Validator] Corrected '{vi['corrected_from']}' -> '{vi['item_key']}'")

    # Handle invalid items — ask for clarification instead of silently dropping
    if validation_result["invalid_items"]:
        invalid_names = [inv["original"] for inv in validation_result["invalid_items"]]
        print(f"[Validator] Invalid items rejected: {invalid_names}")
        if not new_items:
            # ALL items were invalid — ask customer to clarify
            reply = f"Maaf, saya tak pasti '{', '.join(invalid_names)}'. Boleh ulang sekali lagi?"
            action = "unclear"
        else:
            # Some valid, some invalid — confirm valid ones, ask about invalid
            invalid_text = ", ".join(invalid_names)
            reply = reply + f" ('{invalid_text}' — maaf, boleh ulang item tu?)"

    # Log modifier warnings
    for mw in validation_result.get("modifier_warnings", []):
        print(f"[Validator] Modifier warning: '{mw['modifier']}' not valid for {mw['item']} ({mw['reason']})")

    # Normalize action names for frontend consistency
    if action == "add" and new_items:
        action = "add_items"
    if action == "confirm":
        action = "confirm_order"

    # ── Handle cancel/change actions ──
    remove_item = None
    add_item = None
    cancel_index = None

    if action == "cancel_item" and items:
        # Remove specific item from order
        remove_item = items[0].lower().strip()

    elif action == "change_item" and len(items) >= 2:
        # Swap old item for new item
        remove_item = items[0].lower().strip()
        add_item_name = items[1].lower().strip()
        # Look up the new item in menu
        if add_item_name in MENU:
            menu_item = MENU[add_item_name]
            add_item = {"name": add_item_name.title(), "qty": 1, "price": menu_item["price"]}

    elif action == "cancel_by_index" and items:
        # Parse index from "nombor X" pattern
        idx_str = items[0].lower().strip()
        idx_match = re.search(r'(\d+)', idx_str)
        if idx_match:
            cancel_index = int(idx_match.group(1)) - 1  # 0-based
        else:
            # Try Malay ordinal words
            malay_ordinals = {"pertama": 0, "kedua": 1, "ketiga": 2, "keempat": 3, "kelima": 4}
            for word, idx in malay_ordinals.items():
                if word in idx_str:
                    cancel_index = idx
                    break

    # Add "ada lagi?" audio for add action
    if action == "add_items" and new_items:
        audio_matches.append({"audio_path": "/audio/wavs/0043.wav", "audio_exists": True})

    # Add terima kasih audio for confirm
    if action == "confirm_order":
        audio_matches.append({"audio_path": "/audio/wavs/0021.wav", "audio_exists": True})

    # Update order
    updated_order = list(current_order)

    # Handle cancel actions on the order
    if action == "cancel_all":
        updated_order = []
    elif action == "cancel_item" and remove_item:
        updated_order = [i for i in updated_order if i["name"].lower() != remove_item]
    elif action == "cancel_by_index" and cancel_index is not None:
        if 0 <= cancel_index < len(updated_order):
            removed = updated_order.pop(cancel_index)
            reply = reply.replace("[item]", removed["name"])
        else:
            reply = "Nombor tu tiada dalam senarai. Cuba lagi?"
            action = "cancel_request"
    elif action == "change_item" and remove_item:
        updated_order = [i for i in updated_order if i["name"].lower() != remove_item]
        if add_item:
            updated_order.append(add_item)

    # Add new items for ordering actions
    # Items with different modifiers are treated as separate entries
    def _find_existing(order_list, new_item):
        for i in order_list:
            if i["name"].lower() == new_item["name"].lower() and i.get("modifiers", []) == new_item.get("modifiers", []):
                return i
        return None

    if action == "add_items":
        for ni in new_items:
            existing = _find_existing(updated_order, ni)
            if existing:
                existing["qty"] += ni["qty"]
            else:
                updated_order.append(ni)
    elif action not in ("cancel_all", "cancel_item", "cancel_by_index", "change_item"):
        for ni in new_items:
            existing = _find_existing(updated_order, ni)
            if existing:
                existing["qty"] += ni["qty"]
            else:
                updated_order.append(ni)

    total = sum(i["price"] * i["qty"] for i in updated_order)

    # Build extracted_items list for frontend upsell checking
    extracted_items = [ni["name"].lower() for ni in new_items]

    # Check for pre-recorded upsell audio from upsell_map
    upsell_audio_base64 = None
    upsell_audio_info = None
    if action == "add_items" and new_items:
        for ni in new_items:
            info = get_upsell_audio_info(ni["name"])
            if info:
                audio_matches.append({
                    "audio_path": info["audio_path"],
                    "audio_exists": True,
                    "is_upsell": True,
                })
                upsell_audio_info = {
                    "item": ni["name"],
                    "audio_id": info["audio_id"],
                    "audio_path": info["audio_path"],
                    "text": info["text"],
                }
                print(f"[UpsellAudio] Pre-recorded upsell for '{ni['name']}': {info['audio_path']}")
                break  # Only one upsell per response

        # Combo cross-sell: suggest drink if customer ordered food but no drink
        if not upsell_audio_info:
            for ni in new_items:
                combo = get_combo_cross_sell(ni["name"], updated_order)
                if combo:
                    audio_matches.append({
                        "audio_path": combo["audio_path"],
                        "audio_exists": True,
                        "is_upsell": True,
                    })
                    upsell_audio_info = {
                        "item": ni["name"],
                        "audio_id": combo["audio_id"],
                        "audio_path": combo["audio_path"],
                        "text": combo["text"],
                        "type": "combo_cross_sell",
                    }
                    print(f"[ComboUpsell] Drink suggestion for '{ni['name']}': {combo['audio_path']}")
                    break

        # Fallback to ElevenLabs TTS if no pre-recorded upsell audio found
        if not upsell_audio_info and upsell_suggestions:
            try:
                audio_bytes = await generate_upsell_audio(reply)
                if audio_bytes:
                    import base64
                    upsell_audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            except Exception as e:
                print(f"[UpsellTTS] Error generating audio: {e}")

    result = {
        "text": reply,
        "audio_matches": audio_matches,
        "has_audio": len(audio_matches) > 0 or upsell_audio_base64 is not None,
        "action": action,
        "new_items": new_items,
        "extracted_items": extracted_items,
        "order": updated_order,
        "total": total,
        "pipeline": "deepseek+qwen" if (deepseek_result and is_ordering) else "qwen-only"
    }
    if upsell_suggestions or upsell_audio_info:
        result["upsell"] = {
            "suggestions": upsell_suggestions,
            "has_upsell": True,
        }
        if upsell_audio_info:
            result["upsell"]["audio_info"] = upsell_audio_info
    if upsell_audio_base64:
        result["upsell_audio"] = upsell_audio_base64
    if remove_item:
        result["remove_item"] = remove_item
    if add_item:
        result["add_item"] = add_item
    if cancel_index is not None:
        result["cancel_index"] = cancel_index

    # Include validation info for transparency
    if validation_result.get("invalid_items"):
        result["validation_warnings"] = validation_result["invalid_items"]
    if validation_result.get("modifier_warnings"):
        result["modifier_warnings"] = validation_result["modifier_warnings"]

    # ── LOG: Full pipeline for observability ──
    try:
        ds_raw_str = ""
        if deepseek_result:
            import json as _jl
            ds_raw_str = _jl.dumps(deepseek_result, ensure_ascii=False)
        log_order_pipeline(
            table_number=table,
            whisper_transcript=speech,
            deepseek_raw=ds_raw_str,
            deepseek_parsed=deepseek_result,
            validated_result=validation_result,
            final_order=updated_order,
            pipeline=result.get("pipeline", "unknown"),
            qwen_reply=reply,
        )
    except Exception as log_err:
        print(f"[OrderLog] Logging failed (non-blocking): {log_err}")

    return result

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """
    Whisper-based server-side speech-to-text endpoint (upgrade path for scale).

    Accepts audio blob from frontend MediaRecorder, transcribes using OpenAI
    Whisper API with Malay language + food vocabulary hints, then returns the
    accurate transcript. Frontend should then call /api/voice/chat with the text.

    Usage:
      1. Frontend records audio via MediaRecorder
      2. POST audio blob to this endpoint
      3. Get back accurate Malay transcript
      4. Frontend calls /api/voice/chat with the transcript as message

    Cost: ~$0.006/min — affordable for 100+ restaurants.
    Set OPENAI_API_KEY env var to enable.
    """
    form = await request.form()
    audio_file = form.get("audio")
    table_number = form.get("table_number", "T01")

    if not audio_file:
        raise HTTPException(status_code=400, detail="No audio file provided")

    if not get_whisper_client():
        raise HTTPException(status_code=500, detail="Whisper API not configured (set OPENAI_API_KEY)")

    try:
        import io
        import tempfile
        audio_content = await audio_file.read()

        # Write to a temp file so transcribe_audio can open it by path
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_content)
            tmp_path = tmp.name

        transcribed_text = transcribe_audio(tmp_path).strip()
        _cache_transcribe_audio(table_number, transcribed_text, audio_content)
        os.unlink(tmp_path)

        print(f"[Whisper] Transcribed: '{transcribed_text}'")

        return {
            "text": transcribed_text,
            "table_number": table_number,
            "source": "whisper"
        }

    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"[Whisper] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Whisper transcription failed: {str(e)}")


@app.get("/api/voice/order-logs")
async def get_order_logs(limit: int = 50):
    """View recent order pipeline logs for debugging and observability."""
    logs = get_recent_logs(limit)
    return {"logs": logs, "count": len(logs)}


@app.post("/api/voice/confirm-order")
async def voice_confirm_order(request: Request):
    """
    Confirmation flow: customer must confirm the readback before Telegram send.
    Frontend calls this AFTER Aisha reads back the order and customer says "ya"/"confirm".
    This prevents wrong orders from being sent to kitchen.
    """
    body = await request.json()
    table = body.get("table_number", "T01")
    order_items = body.get("items", [])
    total = body.get("total", 0)
    confirmed = body.get("confirmed", False)

    if not confirmed:
        # Build readback text for Aisha to speak
        if not order_items:
            return {
                "action": "no_items",
                "text": "Anda belum order apa-apa lagi.",
                "confirmed": False,
            }

        items_text = ", ".join(
            f"{i.get('qty', 1)} {i['name']}" +
            (f" ({', '.join(i['modifiers'])})" if i.get('modifiers') else "")
            for i in order_items
        )
        total_calc = sum(i.get("price", 0) * i.get("qty", 1) for i in order_items)
        readback = f"Pesanan anda: {items_text}. Jumlah RM{total_calc:.2f}. Betul ke?"

        return {
            "action": "readback",
            "text": readback,
            "items": order_items,
            "total": total_calc,
            "confirmed": False,
        }

    # Customer confirmed — proceed to send
    return {
        "action": "confirmed",
        "text": "Terima kasih! Pesanan sudah dihantar ke dapur.",
        "confirmed": True,
        "ready_to_send": True,
    }


@app.get("/api/voice/greeting")
async def voice_greeting():
    """Return time-based greeting with pre-recorded audio."""
    engine = get_engine()
    result = engine.get_greeting()
    audio_matches = [
        {"audio_path": f"/audio/wavs/{aid}.wav", "audio_exists": True}
        for aid in result["audio_ids"]
    ]
    return {
        "text": result["text"],
        "audio_matches": audio_matches,
        "has_audio": True,
    }

@app.post("/api/voice/order")
async def submit_voice_order(request: Request):
    body = await request.json()
    table = body.get("table_number", "T01")
    items = body.get("items", [])
    total = body.get("total", 0)

    if not items:
        return {"status": "error", "message": "No items"}

    # Save order to database
    conn = get_db()
    cursor = conn.cursor()
    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    total_price = sum(i.get('price', 0) * i.get('qty', 1) for i in items)

    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, total_price, status, table_number, order_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, 'voice_qr', f'Table {table}', '',
          'dine_in', total_price, 'pending', table, 'voice_qr'))

    order_id = cursor.lastrowid

    for i in items:
        cursor.execute('SELECT id, price FROM menu_items WHERE name = ? AND available = 1', (i['name'],))
        menu_item = cursor.fetchone()
        menu_item_id = menu_item['id'] if menu_item else 0
        item_price = menu_item['price'] if menu_item else i.get('price', 0)
        item_note = ', '.join(i.get('modifiers', [])) if i.get('modifiers') else None

        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, menu_item_id, i.get('qty', 1), item_price, item_note))

    conn.commit()
    conn.close()

    # Build Telegram message
    def _format_item_line(i):
        mod_str = f" ({', '.join(i['modifiers'])})" if i.get('modifiers') else ""
        return f"  • {i['name']}{mod_str} x{i.get('qty', 1)} - RM{i.get('price', 0) * i.get('qty', 1):.2f}"
    items_text = "\n".join([_format_item_line(i) for i in items])

    message = (
        f"🎤 VOICE ORDER - MEJA {table}\n"
        f"📋 Order #: {order_number}\n"
        f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
        f"{items_text}\n\n"
        f"💰 TOTAL: RM{total_price:.2f}\n\n"
        f"➡️ Sila key into POS"
    )

    # Create inline keyboard with action buttons
    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Order", "callback_data": f"confirm_{order_id}"},
                {"text": "❌ Cancel Order", "callback_data": f"cancel_{order_id}"}
            ],
            [
                {"text": "🔔 Remind Payment", "callback_data": f"remind_{order_id}"}
            ]
        ]
    }

    # Send to cashier using module-level BOT_TOKEN and CASHIER_CHAT_ID
    print(f"Sending voice order {order_number} to Telegram...")
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, message, reply_markup=inline_keyboard)

    # Send to owner if configured and different from cashier
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, message, reply_markup=inline_keyboard)

    return {"status": "sent", "table": table, "total": total_price, "order_id": order_id, "order_number": order_number}

@app.post("/api/voice/submit-order")
async def voice_submit_order(req: VoiceSubmitOrder):
    """Submit a voice order to the database and notify via Telegram."""
    conn = get_db()
    cursor = conn.cursor()

    # Verify table
    cursor.execute('SELECT * FROM restaurant_tables WHERE table_number = ?', (req.table_number,))
    table = cursor.fetchone()
    if not table:
        conn.close()
        raise HTTPException(status_code=404, detail="Table not found")

    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Calculate total from items
    total_price = sum(item.price * item.quantity for item in req.items)

    # Insert order
    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, total_price, status, table_number, order_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, 'voice_qr', f'Table {req.table_number}', '',
          'dine_in', total_price, 'pending', req.table_number, 'voice_qr'))

    order_id = cursor.lastrowid

    # Insert order items - match to menu items by name
    for item in req.items:
        cursor.execute('SELECT id, price FROM menu_items WHERE name = ? AND available = 1', (item.name,))
        menu_item = cursor.fetchone()
        menu_item_id = menu_item['id'] if menu_item else 0
        item_price = menu_item['price'] if menu_item else item.price
        item_note = ', '.join(item.modifiers) if item.modifiers else None

        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, menu_item_id, item.quantity, item_price, item_note))

    conn.commit()
    conn.close()

    # Send Telegram notification
    send_voice_order_telegram(order_id, req.table_number, req.items, total_price)

    return {"success": True, "order_id": order_id, "order_number": order_number}


def send_voice_order_telegram(order_id, table_number, items, total):
    """Send voice order notification to Telegram."""
    now = datetime.now().strftime('%H:%M %d/%m/%Y')

    items_text = ""
    for item in items:
        line_total = item.price * item.quantity
        mod_str = ""
        if hasattr(item, 'modifiers') and item.modifiers:
            mod_str = f" ({', '.join(item.modifiers)})"
        items_text += f"  • {item.name}{mod_str} x{item.quantity} - RM{line_total:.2f}\n"

    message = (
        f"🔔 TABLE {table_number} - NEW ORDER\n"
        f"⏰ {now}\n\n"
        f"Items:\n{items_text}\n"
        f"💰 TOTAL: RM{total:.2f}\n\n"
        f"Please key into POS."
    )

    # Send to cashier
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, message)

    # Send to owner if different
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, message)


# ========== Aisha Upsell Engine API ==========

@app.get("/api/upsell/suggest")
async def upsell_suggest(item: str):
    """Get upsell suggestion for an ordered item."""
    engine = get_upsell_engine()
    suggestion = engine.get_upsell(item.strip().lower())
    if suggestion:
        return {"has_upsell": True, **suggestion}
    return {"has_upsell": False, "item": item}

@app.get("/api/upsell/options")
async def upsell_options(item: str):
    """Get ALL upsell options for an item (for UI display)."""
    engine = get_upsell_engine()
    options = engine.get_all_upsells(item.strip().lower())
    return {"item": item, "options": options, "count": len(options)}

@app.post("/api/upsell/accept")
async def upsell_accept(request: Request):
    """Customer accepted upsell — return replacement item."""
    body = await request.json()
    original = body.get("original_item", "")
    upsell = body.get("upsell_item", "")
    engine = get_upsell_engine()
    result = engine.accept_upsell(original, upsell)
    if result:
        return {"accepted": True, **result}
    return {"accepted": False, "error": "Invalid upsell item"}

@app.post("/api/upsell/decline")
async def upsell_decline(request: Request):
    """Customer declined upsell — don't ask again for this item."""
    body = await request.json()
    item = body.get("item", "")
    engine = get_upsell_engine()
    engine.decline_upsell(item)
    return {"declined": True, "item": item}

@app.post("/api/upsell/reset")
async def upsell_reset():
    """Reset upsell session (new customer)."""
    engine = get_upsell_engine()
    engine.reset_session()
    return {"reset": True}

@app.get("/api/upsell/stats")
async def upsell_stats():
    """Get upsell engine statistics."""
    engine = get_upsell_engine()
    return engine.get_upsell_stats()

@app.get("/api/upsell/map")
async def upsell_map():
    """Return the full upsell map for debugging/admin."""
    return {"upsell_map": {k: v for k, v in UPSELL_MAP.items()}}

@app.post("/api/upsell/tts")
async def upsell_tts(request: Request):
    """Generate ElevenLabs TTS audio for an upsell suggestion."""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' field")

    audio_bytes = await generate_upsell_audio(text)
    if audio_bytes:
        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        return {
            "has_audio": True,
            "audio_base64": audio_b64,
            "content_type": "audio/mpeg",
            "text": text,
        }
    return {
        "has_audio": False,
        "text": text,
        "reason": "ElevenLabs not configured or TTS failed",
    }


# Setup all enhanced features
setup_enhanced_routes(app)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
