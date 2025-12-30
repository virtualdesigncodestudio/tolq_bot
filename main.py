import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import load_config
from db import DB

logging.basicConfig(level=logging.INFO)

CATEGORIES = ["Кашрут", "Шаббат", "Семья", "Учёба", "Другое"]

class AskFlow(StatesGroup):
    waiting_name = State()
    waiting_category = State()
    waiting_question = State()

def categories_kb():
    kb = InlineKeyboardBuilder()
    for c in CATEGORIES:
        kb.button(text=c, callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()

def name_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="name:skip")
    return kb.as_markup()

async def main():
    cfg = load_config()
    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher()

    db = DB(cfg.db_path)
    await db.connect()

    @dp.message(Command("id"))
    async def my_id(message: Message):
        await message.answer(f"Ваш id: {message.from_user.id}")

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext):
        await state.clear()
        await db.upsert_user(message.from_user.id, None)
        await message.answer(
            "Шалом! Как к вам обращаться? (можно пропустить)",
            reply_markup=name_kb()
        )
        await state.set_state(AskFlow.waiting_name)

    @dp.callback_query(F.data == "name:skip")
    async def skip_name(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.update_data(name=None)
        await cb.message.answer("Выберите тему вопроса:", reply_markup=categories_kb())
        await state.set_state(AskFlow.waiting_category)

    @dp.message(AskFlow.waiting_name)
    async def get_name(message: Message, state: FSMContext):
        name = message.text.strip()
        await db.upsert_user(message.from_user.id, name)
        await state.update_data(name=name)
        await message.answer("Выберите тему вопроса:", reply_markup=categories_kb())
        await state.set_state(AskFlow.waiting_category)

    @dp.callback_query(F.data.startswith("cat:"))
    async def choose_category(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await state.update_data(category=cb.data[4:])
        await cb.message.answer("Напишите ваш вопрос:")
        await state.set_state(AskFlow.waiting_question)

    @dp.message(AskFlow.waiting_question)
    async def get_question(message: Message, state: FSMContext):
        data = await state.get_data()
        name = data.get("name") or "Анонимно"
        category = data.get("category")
        question = message.text

        ticket_id = await db.create_ticket(
            message.from_user.id,
            name,
            category,
            question,
            cfg.group_chat_id
        )

        text = (
            f"🆕 Вопрос #{ticket_id}\n"
            f"Тема: {category}\n"
            f"От: {name}\n\n"
            f"{question}\n\n"
            f"Ответьте reply — ответ уйдёт пользователю."
        )

        msg = await bot.send_message(cfg.group_chat_id, text)
        await db.set_ticket_group_message(ticket_id, msg.message_id)

        await message.answer(f"Спасибо! Вопрос принят. №{ticket_id}")
        await state.clear()

    @dp.message(F.chat.id == load_config().group_chat_id)
    async def operators_reply(message: Message):
        if not message.reply_to_message:
            return

        row = await db.find_ticket_by_group_message(
            message.chat.id,
            message.reply_to_message.message_id
        )
        if not row:
            return

        ticket_id, user_id = row
        await bot.send_message(
            user_id,
            f"Ответ по вопросу #{ticket_id}:\n\n{message.text}"
        )
        await db.mark_ticket_answered(ticket_id, message.from_user.id)
        await message.reply("Ответ отправлен пользователю.")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
