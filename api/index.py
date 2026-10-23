import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import psycopg
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")
if not WEBHOOK_SECRET:
    raise RuntimeError("TELEGRAM_WEBHOOK_SECRET environment variable is required")

app = FastAPI()
bot = Bot(TOKEN)

DEFAULT_CATEGORIES = [
    ("🍔", "Еда"), ("🚕", "Транспорт"), ("🛍", "Покупки"),
    ("🏠", "Дом"), ("☕", "Кафе"), ("💊", "Здоровье"),
    ("🎮", "Развлечения"), ("💡", "Коммунальные"),
    ("📱", "Связь"), ("📦", "Другое"),
]


def db():
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                emoji TEXT NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                category_id BIGINT NOT NULL REFERENCES categories(id),
                comment TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id BIGINT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT '',
                pending_title TEXT,
                pending_amount NUMERIC(14,2)
            )
        """)


def ensure_categories(user_id: int):
    with db() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM categories WHERE user_id=%s", (user_id,)
        ).fetchone()
        if row[0] == 0:
            con.executemany(
                "INSERT INTO categories(user_id,emoji,name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                [(user_id, emoji, name) for emoji, name in DEFAULT_CATEGORIES],
            )


def categories_for(user_id: int):
    ensure_categories(user_id)
    with db() as con:
        return con.execute(
            "SELECT id,emoji,name FROM categories WHERE user_id=%s ORDER BY id", (user_id,)
        ).fetchall()


def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить расход", callback_data="new_expense")],
        [InlineKeyboardButton(text="📊 Статистика за месяц", callback_data="month_report"),
         InlineKeyboardButton(text="🧾 Последние расходы", callback_data="recent")],
        [InlineKeyboardButton(text="🗂 Мои категории", callback_data="show_categories")],
    ])


def category_keyboard(user_id: int):
    rows, row = [], []
    for category_id, emoji, name in categories_for(user_id):
        row.append(InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"cat:{category_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows += [
        [InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def money(value):
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def parse_expense(raw: str):
    cleaned = raw.strip().replace("\u00a0", " ")
    match = re.match(r"^(.+?)\s+([\d\s]+(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля)?|р)?$", cleaned, re.I)
    if not match:
        return None
    title = " ".join(match.group(1).split()).strip(" -:")
    try:
        amount = Decimal(match.group(2).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    if not title or amount <= 0 or amount > Decimal("1000000000"):
        return None
    return title, amount


def get_state(user_id: int):
    with db() as con:
        row = con.execute(
            "SELECT state,pending_title,pending_amount FROM user_state WHERE user_id=%s",
            (user_id,),
        ).fetchone()
    return row or ("", None, None)


def set_state(user_id: int, state: str, title=None, amount=None):
    with db() as con:
        con.execute("""
            INSERT INTO user_state(user_id,state,pending_title,pending_amount)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET state=EXCLUDED.state,
                pending_title=EXCLUDED.pending_title,pending_amount=EXCLUDED.pending_amount
        """, (user_id, state, title, amount))


def clear_state(user_id: int):
    set_state(user_id, "", None, None)


async def send(chat_id: int, text: str, reply_markup=None, parse_mode=None):
    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)


async def report_text(user_id: int):
    with db() as con:
        total = con.execute("""
            SELECT COALESCE(SUM(amount),0) FROM expenses
            WHERE user_id=%s AND date_trunc('month',created_at)=date_trunc('month',CURRENT_DATE::timestamp)
        """, (user_id,)).fetchone()[0]
        rows = con.execute("""
            SELECT c.emoji,c.name,SUM(e.amount) AS total
            FROM expenses e JOIN categories c ON c.id=e.category_id
            WHERE e.user_id=%s AND date_trunc('month',e.created_at)=date_trunc('month',CURRENT_DATE::timestamp)
            GROUP BY c.id,c.emoji,c.name ORDER BY total DESC
        """, (user_id,)).fetchall()
    lines = [f"📊 Расходы за {date.today().strftime('%m.%Y')}", f"Всего: {money(total)}", ""]
    lines.extend(f"{emoji} {name}: {money(amount)}" for emoji, name, amount in rows)
    return "\n".join(lines)


async def handle_message(message):
    user = message.get("from") or {}
    user_id = user.get("id")
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not user_id or not chat_id or not text:
        return
    state, pending_title, pending_amount = get_state(user_id)

    if text.startswith("/start"):
        clear_state(user_id)
        ensure_categories(user_id)
        await send(chat_id,
            "Привет! Я помогу учитывать расходы.\n\n"
            "Отправь название и сумму, например:\n☕ Кофе 300\n🚕 Такси 1 000\n\n"
            "Я покажу категории, а после выбора сохраню расход.",
            main_keyboard())
        return
    if text.startswith("/help"):
        await send(chat_id, "Как пользоваться:\n• Отправь: Кофе 300\n• Выбери категорию кнопкой.\n"
            "• /report — статистика за текущий месяц.\n• /cancel — отменить ввод.\n"
            "Сумму можно писать как 1000, 1 000 или 250,50.", main_keyboard())
        return
    if text.startswith("/cancel"):
        clear_state(user_id)
        await send(chat_id, "Действие отменено.", main_keyboard())
        return
    if text.startswith("/report"):
        await send(chat_id, await report_text(user_id), main_keyboard())
        return
    if state == "waiting_category_name":
        raw = text
        parts = raw.split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) <= 4 and not any(ch.isalnum() for ch in parts[0]):
            emoji, name = parts[0], parts[1].strip()
        else:
            emoji, name = "📌", raw
        if not name or len(name) > 40:
            await send(chat_id, "Название должно быть от 1 до 40 символов.")
            return
        try:
            with db() as con:
                con.execute("INSERT INTO categories(user_id,emoji,name) VALUES(%s,%s,%s)", (user_id, emoji, name))
        except psycopg.errors.UniqueViolation:
            await send(chat_id, "Такая категория уже есть. Напиши другое название.")
            return
        if pending_title and pending_amount is not None:
            set_state(user_id, "waiting_expense", pending_title, pending_amount)
            await send(chat_id, f"Готово! Добавлена категория: {emoji} {name}\n\nВыбери категорию:",
                category_keyboard(user_id))
        else:
            clear_state(user_id)
            await send(chat_id, f"Готово! Добавлена категория: {emoji} {name}", main_keyboard())
        return

    parsed = parse_expense(text)
    if state == "waiting_expense" and not parsed:
        await send(chat_id, "Напиши название и сумму, например: Кофе 300.")
        return
    if parsed:
        title, amount = parsed
        set_state(user_id, "waiting_expense", title, amount)
        await send(chat_id, f"Расход: <b>{title}</b>\nСумма: <b>{money(amount)}</b>\n\nВыбери категорию:",
            category_keyboard(user_id), parse_mode="HTML")
    elif state != "waiting_expense":
        await send(chat_id, "Не получилось распознать сумму. Напиши, например: Кофе 300.")


async def handle_callback(callback):
    user_id = (callback.get("from") or {}).get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    data = callback.get("data", "")
    callback_id = callback.get("id")
    if not user_id or not chat_id:
        return
    state, title, amount = get_state(user_id)

    if data == "new_expense":
        set_state(user_id, "waiting_expense", None, None)
        await send(chat_id, "Напиши название расхода и сумму, например: Кофе 300.")
    elif data == "cancel":
        clear_state(user_id)
        await send(chat_id, "Добавление расхода отменено.", main_keyboard())
    elif data == "add_category":
        set_state(user_id, "waiting_category_name", title, amount)
        await send(chat_id, "Отправь название категории, например: 🐶 Животные. Эмодзи можно не указывать.")
    elif data.startswith("cat:"):
        if state != "waiting_expense" or not title or amount is None:
            await bot.answer_callback_query(callback_id, text="Сначала введи расход.", show_alert=True)
            return
        try:
            category_id = int(data.split(":", 1)[1])
        except ValueError:
            await bot.answer_callback_query(callback_id, text="Некорректная категория.", show_alert=True)
            return
        with db() as con:
            cat = con.execute("SELECT emoji,name FROM categories WHERE id=%s AND user_id=%s",
                              (category_id, user_id)).fetchone()
            if cat:
                con.execute("INSERT INTO expenses(user_id,title,amount,category_id) VALUES(%s,%s,%s,%s)",
                            (user_id, title, amount, category_id))
        if not cat:
            await bot.answer_callback_query(callback_id, text="Категория не найдена.", show_alert=True)
            return
        clear_state(user_id)
        await send(chat_id, f"✅ Расход сохранён\n\n{cat[0]} {cat[1]}\n📝 {title}\n💰 {money(amount)}",
                   main_keyboard())
    elif data == "month_report":
        await send(chat_id, await report_text(user_id), main_keyboard())
    elif data == "recent":
        with db() as con:
            rows = con.execute("""
                SELECT e.title,e.amount,e.created_at,c.emoji,c.name FROM expenses e
                JOIN categories c ON c.id=e.category_id WHERE e.user_id=%s ORDER BY e.id DESC LIMIT 10
            """, (user_id,)).fetchall()
        if not rows:
            answer = "Пока расходов нет. Отправь, например: Кофе 300."
        else:
            lines = ["🧾 Последние расходы:"]
            for expense_title, expense_amount, created_at, emoji, name in rows:
                lines.append(f"{emoji} {name} — {expense_title}: {money(expense_amount)}")
                lines.append(f"   {created_at.strftime('%Y-%m-%d %H:%M')}")
            answer = "\n".join(lines)
        await send(chat_id, answer, main_keyboard())
    elif data == "show_categories":
        lines = ["🗂 Твои категории:"]
        lines.extend(f"{emoji} {name}" for _, emoji, name in categories_for(user_id))
        lines.append("\nДобавить категорию можно при добавлении расхода.")
        await send(chat_id, "\n".join(lines), main_keyboard())
    if callback_id:
        await bot.answer_callback_query(callback_id)


@app.get("/")
async def health():
    return {"ok": True, "service": "telegram-expense-bot"}


@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = await request.json()
        init_db()
        if "message" in update:
            await handle_message(update["message"])
        elif "callback_query" in update:
            await handle_callback(update["callback_query"])
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        # Return 500 so Telegram retries temporary database or API failures.
        raise HTTPException(status_code=500, detail="Update processing failed") from exc
