import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F

from config import load_config
from db import DB
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Задать вопрос")],
    ],
    resize_keyboard=True
)



logging.basicConfig(level=logging.INFO)
async def start_health_server():
    app = web.Application()

    async def handle_root(request):
        return web.Response(text="OK")

    app.router.add_get("/", handle_root)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", "10000"))  # Render задаёт PORT автоматически
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

CATEGORIES = ["Кашрут", "Шаббат", "Семья", "Учёба", "Другое"]

class AskFlow(StatesGroup):
    waiting_name = State()
    waiting_category = State()
    waiting_question = State()

    rabbi_private_answer = State()
    rabbi_group_answer = State()

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
    

def answer_kb(ticket_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Ответить приватно", callback_data=f"ans_priv:{ticket_id}")
    kb.button(text="💬 Ответить в группе", callback_data=f"ans_grp:{ticket_id}")
    kb.adjust(2)
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
    
    @dp.message(Command("chatid"))
    async def chat_id(message: Message):
        await message.answer(f"chat_id этого чата: {message.chat.id}")
    

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext):
        await state.clear()
        if message.chat.type == "private":
            await message.answer("Шалом! Нажмите кнопку ниже, чтобы задать вопрос.", reply_markup=MAIN_KB)

    @dp.message(F.text == "📝 Задать вопрос")
    async def start_ask_flow(message: Message, state: FSMContext):
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
        await cb.message.answer("Выберите тему вопроса:", reply_markup=())
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

    @dp.callback_query(F.data.startswith("ans_priv:"))
    async def start_private_answer(cb: CallbackQuery, state: FSMContext):
        ticket_id = int(cb.data.split(":")[1])
        await cb.answer()

        await state.clear()
        await state.update_data(ticket_id=ticket_id)

    
        await cb.message.bot.send_message(
            cb.from_user.id,
            f"✍️ Напишите ответ на вопрос #{ticket_id} (ответ будет скрыт от других участников группы):"
        )

        await state.set_state(AskFlow.rabbi_private_answer)

    @dp.callback_query(F.data.startswith("ans_grp:"))
    async def start_group_answer(cb: CallbackQuery, state: FSMContext):
        ticket_id = int(cb.data.split(":")[1])
        await cb.answer()

        await state.clear()
        await state.update_data(ticket_id=ticket_id)

    
        await cb.message.reply(
            f"✍️ Напишите следующим сообщением ваш ответ на вопрос #{ticket_id}.\n"
            f"Я отправлю его пользователю и опубликую reply-ом к вопросу."
        )

        await state.set_state(AskFlow.rabbi_group_answer)


    @dp.message(AskFlow.rabbi_group_answer, F.chat.id == cfg.group_chat_id, F.text)
async def handle_group_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        await message.reply("⚠️ Нет активного вопроса. Нажмите кнопку под вопросом ещё раз.")
        await state.clear()
        return

    row = await db.find_ticket_by_id(ticket_id)
    if not row:
        await message.reply("⚠️ Вопрос не найден.")
        await state.clear()
        return

    user_id, group_chat_id, group_msg_id = row

    # 1) Отправляем пользователю
    await message.bot.send_message(
        user_id,
        f"Ответ по вопросу #{ticket_id}:\n\n{message.text}",
        reply_markup=MAIN_KB
    )

    # 2) Публикуем в группе reply-ом к вопросу (ботом)
    await message.bot.send_message(
        group_chat_id,
        f"💬 Ответ по вопросу #{ticket_id}:\n\n{message.text}",
        reply_to_message_id=group_msg_id
    )

    await db.mark_ticket_answered(ticket_id, message.from_user.id)

    # (Опционально) удалить исходное сообщение раввина, чтобы не было дубля
    # нужно, чтобы бот был админом с правом удалять
    # try:
    #     await message.delete()
    # except Exception:
    #     pass

    await message.reply("✅ Ответ отправлен пользователю и опубликован в группе.")
    await state.clear()

    
    @dp.message(AskFlow.rabbi_private_answer, F.chat.type == "private", F.text)
    async def handle_private_answer(message: Message, state: FSMContext):
        data = await state.get_data()
        ticket_id = data.get("ticket_id")

        if not ticket_id:
            await message.answer("⚠️ Нет активного вопроса. Нажмите кнопку под вопросом в группе ещё раз.")
            await state.clear()
            return

        row = await db.find_ticket_by_id(ticket_id)
        if not row:
            await message.answer("⚠️ Вопрос не найден.")
            await state.clear()
            return

        user_id, group_chat_id, group_msg_id = row

    
        await message.bot.send_message(
            user_id,
            f"Ответ по вопросу #{ticket_id}:\n\n{message.text}",
            reply_markup=MAIN_KB
        )

        await message.bot.send_message(
            group_chat_id,
            f"✅ Ответ по вопросу #{ticket_id} отправлен пользователю (приватно).",
            reply_to_message_id=group_msg_id
        )

        await db.mark_ticket_answered(ticket_id, message.from_user.id)
        await message.answer("✅ Ответ отправлен пользователю. (Приватно)")
        await state.clear()

        
    @dp.message(AskFlow.waiting_category)
    async def reject_text_in_category(message: Message, state: FSMContext):
        await message.answer(
            "Пожалуйста, выберите тему кнопкой ниже 👇",
            reply_markup=categories_kb()
        )

    @dp.message(AskFlow.waiting_question, F.text)
    async def get_question(message: Message, state: FSMContext):

        data = await state.get_data()
        name = data.get("name") or "Анонимно"
        category = data.get("category")
        
        
        question = message.text.strip()
        if not question:
            await message.answer("Пожалуйста, отправьте вопрос текстом.")
            return

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
        try:
            header_msg = await bot.send_message(cfg.group_chat_id, text, reply_markup=answer_kb(ticket_id))

        except Exception as e:
            logging.exception("FAILED to send to group")
            await message.answer(
                "⚠️ Я не смог отправить вопрос в группу раввинов.\n"
                "Проверьте, что бот добавлен в группу, назначен админом, и GROUP_CHAT_ID правильный."
            )
            return

        
        await db.set_ticket_group_message(ticket_id, header_msg.message_id)
        
        await state.clear()
        await message.answer(
            f"Спасибо! Вопрос принят. №{ticket_id}\n\n"
            "Чтобы задать ещё один вопрос — нажмите кнопку ниже.",
            reply_markup=MAIN_KB
        )



    @dp.message(AskFlow.waiting_question)
    async def reject_non_text(message: Message, state: FSMContext):
        await message.answer("Сейчас можно отправлять вопрос только текстом. Фото/голосовые отключены.")


    @dp.message(F.chat.id == cfg.group_chat_id, F.reply_to_message)
    async def operators_reply(message: Message):
        if not message.reply_to_message:
            return

        row = await db.find_ticket_by_group_message(
            message.chat.id,
            message.reply_to_message.message_id
        )
        if not row:
            await message.reply("⚠️ Не нашёл вопрос по этому reply. Ответьте reply именно на сообщение бота с номером вопроса.")
            return

        ticket_id, user_id = row
        await bot.send_message(
            user_id,
            f"Ответ по вопросу #{ticket_id}:\n\n{message.text}\n\n"
        )

        await db.mark_ticket_answered(ticket_id, message.from_user.id)
        await message.reply("Ответ отправлен пользователю.")
        
    @dp.message(F.chat.type == "private")
    async def fallback(message: Message, state: FSMContext):
        if await state.get_state() is None:
            await message.answer("Нажмите 📝 Задать вопрос", reply_markup=MAIN_KB)



    await start_health_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
