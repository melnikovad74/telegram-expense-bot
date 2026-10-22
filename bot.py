import asyncio
import os
import re
import sqlite3
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "expenses.db")

DEFAULT_CATEGORIES = [
    ("🍔", "Еда"), ("🚕", "Транспорт"), ("🛍", "Покупки"),
    ("🏠", "Дом"), ("☕", "Кафе"), ("💊", "Здоровье"),
    ("🎮", "Развлечения"), ("💡", "Коммунальные"),
    ("📱", "Связь"), ("📦", "Другое"),
]

class ExpenseFlow(StatesGroup):
    waiting_expense = State()
    waiting_category_name = State()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(user_id, name)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category_id INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )""")

def ensure_categories(user_id: int):
    with db() as con:
        count = con.execute("SELECT COUNT(*) n FROM categories WHERE user_id=?", (user_id,)).fetchone()["n"]
        if count == 0:
            con.executemany(
                "INSERT OR IGNORE INTO categories(user_id, emoji, name) VALUES (?, ?, ?)",
                [(e, n) for e, n in DEFAULT_CATEGORIES]
            ) if False else con.executemany(
                "INSERT OR IGNORE INTO categories(user_id, emoji, name) VALUES (?, ?, ?)",
                [(user_id, e, n) for e, n in DEFAULT_CATEGORIES]
            )

def categories_for(user_id: int):
    ensure_categories(user_id)
    with db() as con:
        return con.execute("SELECT id, emoji, name FROM categories WHERE user_id=? ORDER BY id", (user_id,)).fetchall()

def category_keyboard(user_id: int):
    rows, row = [], []
    for c in categories_for(user_id):
        row.append(InlineKeyboardButton(text=f"{c['emoji']} {c['name']}", callback_data=f"cat:{c['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows += [[InlineKeyboardButton(text="➕ Создать категорию", callback_data="add_category")],
             [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить расход", callback_data="new_expense")],
        [InlineKeyboardButton(text="📊 Статистика за месяц", callback_data="month_report"),
         InlineKeyboardButton(text="🧾 Последние расходы", callback_data="recent")],
        [InlineKeyboardButton(text="🗂 Мои категории", callback_data="show_categories")],
    ])

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
    return title, float(amount)

def money(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"

async def show_category_prompt(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    await message.answer(
        f"Расход: <b>{data['title']}</b>\nСумма: <b>{money(data['amount'])}</b>\n\nВыбери категорию:",
        parse_mode="HTML", reply_markup=category_keyboard(user_id)
    )

async def start_expense(message: Message, state: FSMContext, raw: str):
    parsed = parse_expense(raw)
    if not parsed:
        await message.answer("Не получилось распознать сумму.\nНапиши название и сумму, например: Кофе 300 или Такси 1 000.")
        return
    title, amount = parsed
    await state.update_data(title=title, amount=amount)
    await state.set_state(ExpenseFlow.waiting_expense)
    await show_category_prompt(message, state, message.from_user.id)

async def save_expense(user_id: int, title: str, amount: float, category_id: int):
    with db() as con:
        cat = con.execute("SELECT emoji, name FROM categories WHERE id=? AND user_id=?", (category_id, user_id)).fetchone()
        if not cat:
            return None
        con.execute(
            "INSERT INTO expenses(user_id,title,amount,category_id,comment,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, title, amount, category_id, "", datetime.now().isoformat(timespec="seconds"))
        )
        return cat["emoji"], cat["name"]

async def report_text(user_id: int):
    month = date.today().replace(day=1).isoformat()
    with db() as con:
        total = con.execute(
            "SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE user_id=? AND substr(created_at,1,10)>=?",
            (user_id, month)
        ).fetchone()["total"]
        rows = con.execute(
            """SELECT c.emoji,c.name,SUM(e.amount) total FROM expenses e
               JOIN categories c ON c.id=e.category_id
               WHERE e.user_id=? AND substr(e.created_at,1,10)>=?
               GROUP BY c.id ORDER BY total DESC""", (user_id, month)
        ).fetchall()
    lines = [f"📊 Расходы за {date.today().strftime('%m.%Y')}", f"Всего: {money(total)}", ""]
    lines.extend(f"{r['emoji']} {r['name']}: {money(r['total'])}" for r in rows)
    return "\n".join(lines)

async def main():
    if not TOKEN:
        raise SystemExit("Не найден BOT_TOKEN. Добавьте переменную окружения BOT_TOKEN.")
    init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext):
        await state.clear()
        ensure_categories(message.from_user.id)
        await message.answer(
            "Привет! Я помогу учитывать расходы.\n\n"
            "Отправь название и сумму, например:\n☕ Кофе 300\n🚕 Такси 1 000\n\n"
            "Я покажу категории, а после выбора сохраню расход.",
            reply_markup=main_keyboard()
        )

    @dp.message(Command("help"))
    async def help_cmd(message: Message):
        await message.answer(
            "Как пользоваться:\n• Отправь: Кофе 300\n• Выбери категорию кнопкой.\n"
            "• /report — статистика за текущий месяц.\n• /cancel — отменить ввод.\n"
            "Сумму можно писать как 1000, 1 000 или 250,50.",
            reply_markup=main_keyboard()
        )

    @dp.message(Command("cancel"))
    async def cancel_cmd(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_keyboard())

    @dp.message(Command("report"))
    async def report_cmd(message: Message):
        await message.answer(await report_text(message.from_user.id), reply_markup=main_keyboard())

    @dp.callback_query(F.data == "new_expense")
    async def new_expense_cb(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await state.set_state(ExpenseFlow.waiting_expense)
        await call.message.answer("Напиши название расхода и сумму, например: Кофе 300.")
        await call.answer()

    @dp.callback_query(F.data == "cancel")
    async def cancel_cb(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await call.message.answer("Добавление расхода отменено.", reply_markup=main_keyboard())
        await call.answer()

    @dp.callback_query(F.data == "add_category")
    async def add_category_cb(call: CallbackQuery, state: FSMContext):
        await state.set_state(ExpenseFlow.waiting_category_name)
        await call.message.answer("Отправь название категории, например: 🐶 Животные. Эмодзи можно не указывать.")
        await call.answer()

    @dp.message(ExpenseFlow.waiting_category_name)
    async def add_category_msg(message: Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw:
            await message.answer("Напиши название категории текстом.")
            return
        parts = raw.split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) <= 4 and not any(ch.isalnum() for ch in parts[0]):
            emoji, name = parts[0], parts[1].strip()
        else:
            emoji, name = "📌", raw
        if not name or len(name) > 40:
            await message.answer("Название должно быть от 1 до 40 символов.")
            return
        try:
            with db() as con:
                con.execute("INSERT INTO categories(user_id,emoji,name) VALUES(?,?,?)", (message.from_user.id, emoji, name))
        except sqlite3.IntegrityError:
            await message.answer("Такая категория уже есть. Напиши другое название.")
            return
        pending = await state.get_data()
        has_expense = "title" in pending and "amount" in pending
        if has_expense:
            await state.set_state(ExpenseFlow.waiting_expense)
        else:
            await state.clear()
        await message.answer(f"Готово! Добавлена категория: {emoji} {name}")
        if has_expense:
            await show_category_prompt(message, state, message.from_user.id)
        else:
            await message.answer("Главное меню:", reply_markup=main_keyboard())

    @dp.callback_query(F.data.startswith("cat:"))
    async def choose_category(call: CallbackQuery, state: FSMContext):
        if await state.get_state() != ExpenseFlow.waiting_expense.state:
            await call.answer("Сначала введи расход.", show_alert=True)
            return
        try:
            category_id = int(call.data.split(":", 1)[1])
        except ValueError:
            await call.answer("Некорректная категория.", show_alert=True)
            return
        data = await state.get_data()
        result = await save_expense(call.from_user.id, data["title"], data["amount"], category_id)
        await state.clear()
        if not result:
            await call.answer("Категория не найдена.", show_alert=True)
            return
        emoji, name = result
        await call.message.answer(
            f"✅ Расход сохранён\n\n{emoji} {name}\n📝 {data['title']}\n💰 {money(data['amount'])}",
            reply_markup=main_keyboard()
        )
        await call.answer("Сохранено!")

    @dp.callback_query(F.data == "month_report")
    async def month_report_cb(call: CallbackQuery):
        await call.message.answer(await report_text(call.from_user.id), reply_markup=main_keyboard())
        await call.answer()

    @dp.callback_query(F.data == "recent")
    async def recent_cb(call: CallbackQuery):
        with db() as con:
            rows = con.execute(
                """SELECT e.title,e.amount,e.created_at,c.emoji,c.name FROM expenses e
                   JOIN categories c ON c.id=e.category_id WHERE e.user_id=?
                   ORDER BY e.id DESC LIMIT 10""", (call.from_user.id,)
            ).fetchall()
        if not rows:
            answer = "Пока расходов нет. Отправь, например: Кофе 300."
        else:
            lines = ["🧾 Последние расходы:"]
            for r in rows:
                lines.append(f"{r['emoji']} {r['name']} — {r['title']}: {money(r['amount'])}")
                lines.append(f"   {r['created_at'][:16].replace('T',' ')}")
            answer = "\n".join(lines)
        await call.message.answer(answer, reply_markup=main_keyboard())
        await call.answer()

    @dp.callback_query(F.data == "show_categories")
    async def show_categories_cb(call: CallbackQuery):
        lines = ["🗂 Твои категории:"]
        lines.extend(f"{c['emoji']} {c['name']}" for c in categories_for(call.from_user.id))
        lines.append("\nДобавить категорию можно при добавлении расхода.")
        await call.message.answer("\n".join(lines), reply_markup=main_keyboard())
        await call.answer()

    @dp.message()
    async def any_text(message: Message, state: FSMContext):
        if not message.text or await state.get_state() == ExpenseFlow.waiting_category_name.state:
            return
        await start_expense(message, state, message.text)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
