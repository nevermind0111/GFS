
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from threading import Thread

from flask import Flask, render_template, request, jsonify
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

TOKEN = "8733448156:AAFkVO59emlRIazwOVXGewwK0UGeEb5SAos1"
WEBAPP_URL = "https://fitness-miniapp.onrender.com/"
ADMIN_IDS = [601663687]

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

app = Flask(__name__)

conn = sqlite3.connect("bookings.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_date TEXT,
    booking_time TEXT,
    full_name TEXT,
    username TEXT,
    comment TEXT
)
""")
conn.commit()


class BookingState(StatesGroup):
    waiting_comment = State()


def cleanup_old():

    now = datetime.now()

    cursor.execute("""
        SELECT id, booking_date, booking_time
        FROM bookings
    """)

    rows = cursor.fetchall()

    for booking_id, d, t in rows:

        dt = datetime.strptime(
            f"{d} {t}",
            "%Y-%m-%d %H:%M"
        )

        if dt <= now:
            cursor.execute(
                "DELETE FROM bookings WHERE id=?",
                (booking_id,)
            )

    conn.commit()


def booked_slots():

    cleanup_old()

    cursor.execute("""
        SELECT booking_date, booking_time
        FROM bookings
    """)

    return [
        f"{x[0]}|{x[1]}"
        for x in cursor.fetchall()
    ]


def create_dates_keyboard():

    builder = InlineKeyboardBuilder()

    for i in range(7):

        d = datetime.now() + timedelta(days=i)

        builder.button(
            text=f"✨ {d.strftime('%d.%m')}",
            callback_data=f"date|{d.strftime('%Y-%m-%d')}"
        )

    builder.adjust(2)

    return builder.as_markup()


def create_slots_keyboard(date_str):

    builder = InlineKeyboardBuilder()

    booked = booked_slots()

    for hour in range(10, 21):

        slot = f"{hour}:00"

        dt = datetime.strptime(
            f"{date_str} {slot}",
            "%Y-%m-%d %H:%M"
        )

        if dt <= datetime.now():
            continue

        key = f"{date_str}|{slot}"

        if key in booked:
            continue

        builder.button(
            text=f"🤍 {slot}",
            callback_data=f"book|{date_str}|{slot}"
        )

    builder.adjust(3)

    return builder.as_markup()


@router.message(Command("start"))
async def start(message: Message):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Mini App",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Запис через Telegram",
                    callback_data="tg_booking"
                )
            ]
        ]
    )

    await message.answer_photo(
        photo="https://images.unsplash.com/photo-1518611012118-696072aa579a?q=80&w=1200",
        caption=(
            "✨ <b>Онлайн запис на тренування</b>\n\n"
            "🤍 Wellness • Fitness • Stretching\n\n"
            "Оберіть формат запису нижче ✨"
        ),
        reply_markup=keyboard
    )


@router.callback_query(F.data == "tg_booking")
async def tg_booking(callback: CallbackQuery):

    await callback.message.answer(
        "📅 <b>Оберіть дату тренування</b>",
        reply_markup=create_dates_keyboard()
    )


@router.callback_query(F.data.startswith("date|"))
async def choose_date(callback: CallbackQuery):

    _, date_str = callback.data.split("|")

    await callback.message.answer(
        f"⏰ <b>Вільний час на {date_str}</b>",
        reply_markup=create_slots_keyboard(date_str)
    )


@router.callback_query(F.data.startswith("book|"))
async def start_booking(callback: CallbackQuery, state: FSMContext):

    _, booking_date, booking_time = callback.data.split("|")

    await state.update_data(
        booking_date=booking_date,
        booking_time=booking_time
    )

    await state.set_state(BookingState.waiting_comment)

    await callback.message.answer(
        "✍️ <b>Напишіть коментар, побажання до запису</b>\n\n"
        "Наприклад:\n"
        "• Хочу тренування на ноги\n"
        "• Перший раз у залі\n"
        "• Групове заняття\n\n"
        "Або відправте '-' якщо немає побажань"
    )


@router.message(BookingState.waiting_comment)
async def finish_booking(message: Message, state: FSMContext):

    data = await state.get_data()

    booking_date = data["booking_date"]
    booking_time = data["booking_time"]

    comment = message.text

    full_name = message.from_user.full_name
    username = message.from_user.username or "no_username"

    cursor.execute("""
        INSERT INTO bookings (
            booking_date,
            booking_time,
            full_name,
            username,
            comment
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        booking_date,
        booking_time,
        full_name,
        username,
        comment
    ))

    conn.commit()

    text = (
        f"✨ <b>Нова бронь</b>\n\n"
        f"👤 <b>{full_name}</b>\n"
        f"📱 @{username}\n"
        f"📅 {booking_date}\n"
        f"⏰ {booking_time}\n"
        f"💬 {comment}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            print(e)

    await message.answer(
        "🤍 <b>Ви успішно записані на тренування</b>\n\n"
        f"📅 {booking_date}\n"
        f"⏰ {booking_time}"
    )

    await state.clear()


@router.message(Command("admin"))
async def admin_panel(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    cleanup_old()

    cursor.execute("""
        SELECT booking_date,
               booking_time,
               full_name,
               username,
               comment
        FROM bookings
        ORDER BY booking_date, booking_time
    """)

    rows = cursor.fetchall()

    if not rows:
        await message.answer("🤍 Активних записів немає")
        return

    text = "📋 <b>Активні записи</b>\n\n"

    for row in rows:

        text += (
            f"👤 <b>{row[2]}</b>\n"
            f"📱 @{row[3]}\n"
            f"📅 {row[0]}\n"
            f"⏰ {row[1]}\n"
            f"💬 {row[4]}\n\n"
        )

    await message.answer(text)


@app.route("/")
def home():

    cleanup_old()

    return render_template(
        "index.html",
        booked_slots=booked_slots()
    )


@app.route("/api/book", methods=["POST"])
def api_book():

    cleanup_old()

    data = request.json

    booking_date = data["date"]
    booking_time = data["time"]
    full_name = data["name"]
    username = data["username"]
    comment = data["comment"]

    key = f"{booking_date}|{booking_time}"

    if key in booked_slots():
        return jsonify({
            "success": False
        })

    cursor.execute("""
        INSERT INTO bookings (
            booking_date,
            booking_time,
            full_name,
            username,
            comment
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        booking_date,
        booking_time,
        full_name,
        username,
        comment
    ))

    conn.commit()

    text = (
        f"✨ <b>Нова бронь через Mini App</b>\n\n"
        f"👤 <b>{full_name}</b>\n"
        f"📱 @{username}\n"
        f"📅 {booking_date}\n"
        f"⏰ {booking_time}\n"
        f"💬 {comment}"
    )

    async def notify():
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                print(e)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(notify())
    loop.close()

    return jsonify({
        "success": True
    })


def run_flask():
    app.run(host="0.0.0.0", port=5000)


async def main():
    Thread(target=run_flask).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
