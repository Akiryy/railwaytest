import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", BASE_DIR / "config.json"))
DB_PATH = Path(os.getenv("DB_PATH", "/data/bot.db"))


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


CONFIG = load_config()

load_dotenv()

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                interval_minutes INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Almaty'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_orders (
                chat_id INTEGER NOT NULL,
                order_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, order_key)
            )
            """
        )
        conn.commit()


def ensure_settings(chat_id: int) -> sqlite3.Row:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (chat_id, enabled, interval_minutes, threshold, timezone)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                int(CONFIG.get("default_enabled", True)),
                int(CONFIG.get("default_interval_minutes", 180)),
                int(CONFIG.get("default_threshold", 10)),
                "Asia/Almaty",
            ),
        )
        conn.commit()
        return conn.execute("SELECT * FROM settings WHERE chat_id = ?", (chat_id,)).fetchone()


def update_setting(chat_id: int, field: str, value) -> None:
    allowed_fields = {"enabled", "interval_minutes", "threshold", "timezone"}
    if field not in allowed_fields:
        raise ValueError("Unknown setting")

    ensure_settings(chat_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE settings SET {field} = ? WHERE chat_id = ?", (value, chat_id))
        conn.commit()


def calculate_score(title: str, description: str) -> tuple[int, list[str]]:
    text = f"{title} {description}".lower()
    score = 0
    matched = []

    for keyword, weight in CONFIG.get("keywords", {}).items():
        if keyword.lower() in text:
            score += int(weight)
            matched.append(keyword)

    return score, matched


def order_key(order: dict) -> str:
    return order.get("url") or order.get("title", "unknown")


def was_seen(chat_id: int, key: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_orders WHERE chat_id = ? AND order_key = ?",
            (chat_id, key),
        ).fetchone()
    return row is not None


def mark_seen(chat_id: int, key: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO seen_orders (chat_id, order_key, created_at)
            VALUES (?, ?, ?)
            """,
            (chat_id, key, datetime.utcnow().isoformat()),
        )
        conn.commit()


async def check_orders_for_chat(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = int(context.job.chat_id)
    settings = ensure_settings(chat_id)

    if not settings["enabled"]:
        return

    found_count = 0

    for order in CONFIG.get("test_orders", []):
        key = order_key(order)
        if was_seen(chat_id, key):
            continue

        score, matched = calculate_score(order["title"], order["description"])
        if score < settings["threshold"]:
            mark_seen(chat_id, key)
            continue

        found_count += 1
        mark_seen(chat_id, key)

        message = (
            "🔥 Подходящий заказ найден\n\n"
            f"📌 {order['title']}\n"
            f"💬 {order['description']}\n"
            f"💰 {order['price']}\n"
            f"⭐ Релевантность: {score}\n"
            f"🔑 Совпадения: {', '.join(matched) or 'нет'}\n"
            f"🔗 {order['url']}"
        )
        await context.bot.send_message(chat_id=chat_id, text=message)

    if found_count == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Проверка завершена. Новых подходящих тестовых заказов нет.",
        )


def schedule_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int, interval_minutes: int) -> None:
    job_name = f"check_orders_{chat_id}"

    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    context.job_queue.run_repeating(
        check_orders_for_chat,
        interval=interval_minutes * 60,
        first=10,
        chat_id=chat_id,
        name=job_name,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings = ensure_settings(chat_id)
    schedule_job(context, chat_id, settings["interval_minutes"])

    await update.message.reply_text(
        "Бот запущен ✅\n\n"
        "Команды:\n"
        "/status — настройки\n"
        "/check — проверить сейчас\n"
        "/interval 180 — интервал в минутах\n"
        "/threshold 10 — минимальный балл\n"
        "/on — включить проверки\n"
        "/off — выключить проверки\n"
        "/reset_seen — очистить просмотренные тестовые заказы"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings = ensure_settings(chat_id)

    await update.message.reply_text(
        "⚙️ Текущие настройки:\n\n"
        f"Работает: {'да' if settings['enabled'] else 'нет'}\n"
        f"Интервал: {settings['interval_minutes']} мин.\n"
        f"Порог: {settings['threshold']}\n"
        f"SQLite: {DB_PATH}\n"
        f"JSON: {CONFIG_PATH}"
    )


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Проверяю тестовые заказы...")
    fake_job = type("FakeJob", (), {"chat_id": update.effective_chat.id})()
    context.job = fake_job
    await check_orders_for_chat(context)


async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Пример: /interval 180")
        return

    minutes = int(context.args[0])
    if minutes < 1:
        await update.message.reply_text("Интервал должен быть минимум 1 минута.")
        return

    update_setting(chat_id, "interval_minutes", minutes)
    schedule_job(context, chat_id, minutes)
    await update.message.reply_text(f"✅ Интервал изменён: {minutes} мин.")


async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Пример: /threshold 10")
        return

    threshold = int(context.args[0])
    update_setting(chat_id, "threshold", threshold)
    await update.message.reply_text(f"✅ Порог изменён: {threshold}")


async def turn_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings = ensure_settings(chat_id)
    update_setting(chat_id, "enabled", 1)
    schedule_job(context, chat_id, settings["interval_minutes"])
    await update.message.reply_text("✅ Проверки включены.")


async def turn_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    update_setting(chat_id, "enabled", 0)
    await update.message.reply_text("⏸ Проверки выключены.")


async def reset_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with get_connection() as conn:
        conn.execute("DELETE FROM seen_orders WHERE chat_id = ?", (chat_id,))
        conn.commit()
    await update.message.reply_text("✅ Список просмотренных тестовых заказов очищен.")


async def dbtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with get_connection() as conn:
        settings_count = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
        seen_count = conn.execute("SELECT COUNT(*) FROM seen_orders").fetchone()[0]

    await update.message.reply_text(
        "🧪 SQLite test\n\n"
        f"DB_PATH: {DB_PATH}\n"
        f"DB exists: {DB_PATH.exists()}\n"
        f"Settings rows: {settings_count}\n"
        f"Seen orders rows: {seen_count}"
    )


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN environment variable")

    init_db()

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("check", check_now))
    application.add_handler(CommandHandler("interval", set_interval))
    application.add_handler(CommandHandler("threshold", set_threshold))
    application.add_handler(CommandHandler("on", turn_on))
    application.add_handler(CommandHandler("off", turn_off))
    application.add_handler(CommandHandler("reset_seen", reset_seen))
    application.add_handler(CommandHandler("dbtest", dbtest))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
