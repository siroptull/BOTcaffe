import os
import asyncio
import logging
import sqlite3
import pytz
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Загрузка переменных окружения
load_dotenv()

# Проверка токена
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен бота не найден в .env файле!")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключение к БД
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("anticafe.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Создание таблиц в базе данных"""
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT, 
                      full_name TEXT,
                      phone TEXT,
                      reg_date TEXT)""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS visits
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      visit_date TEXT,
                      FOREIGN KEY(user_id) REFERENCES users(user_id))""")

        self.cursor.execute("""CREATE TABLE IF NOT EXISTS events
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      title TEXT,
                      description TEXT,
                      event_date TEXT,
                      photo_id TEXT)""")
        
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)""")
        
        self.conn.commit()

    def add_admin(self, user_id):
        """Добавление администратора"""
        self.cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (user_id,))
        self.conn.commit()

    def is_admin(self, user_id):
        """Проверка прав администратора"""
        self.cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return bool(self.cursor.fetchone())

    def add_user(self, user_id, username, full_name):
        """Добавление нового пользователя"""
        reg_date = datetime.now(pytz.timezone('Europe/Moscow')).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, reg_date) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, reg_date)
        )
        self.conn.commit()

    def update_phone(self, user_id, phone):
        """Обновление номера телефона"""
        self.cursor.execute(
            "UPDATE users SET phone = ? WHERE user_id = ?",
            (phone, user_id)
        )
        self.conn.commit()

    def add_visit(self, user_id):
        """Добавление посещения"""
        visit_date = datetime.now(pytz.timezone('Europe/Moscow')).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO visits (user_id, visit_date) VALUES (?, ?)",
            (user_id, visit_date)
        )
        self.conn.commit()
        return self.get_visits_count(user_id)

    def get_visits_count(self, user_id):
        """Получение количества посещений"""
        self.cursor.execute(
            "SELECT COUNT(*) FROM visits WHERE user_id = ?",
            (user_id,)
        )
        return self.cursor.fetchone()[0]

    def get_all_users(self):
        """Получение списка всех пользователей"""
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]

    def get_stats(self):
        """Получение статистики"""
        self.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM visits")
        total_visits = self.cursor.fetchone()[0]
        
        self.cursor.execute("""
            SELECT u.full_name, COUNT(v.id) as visits 
            FROM users u
            LEFT JOIN visits v ON u.user_id = v.user_id
            GROUP BY u.user_id
            ORDER BY visits DESC
            LIMIT 5
        """)
        top_users = self.cursor.fetchall()
        
        return total_users, total_visits, top_users

    def add_event(self, title, description, event_date, photo_id=None):
        """Добавление события"""
        self.cursor.execute(
            "INSERT INTO events (title, description, event_date, photo_id) VALUES (?, ?, ?, ?)",
            (title, description, event_date, photo_id)
        )
        self.conn.commit()

    def get_events(self):
        """Получение списка событий"""
        self.cursor.execute("SELECT * FROM events ORDER BY event_date")
        return self.cursor.fetchall()

db = Database()

# Состояния FSM
class Form(StatesGroup):
    phone = State()
    event_title = State()
    event_description = State()
    event_date = State()
    event_photo = State()
    mailing_message = State()
    feedback = State()

# Проверка прав администратора
async def is_admin(user_id: int) -> bool:
    return db.is_admin(user_id)

# ---- Основные команды ----

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    await message.answer(
        f"👋 Привет, {message.from_user.full_name}!\n"
        "Добро пожаловать в наше антикафе!\n\n"
        "📱 Поделитесь номером телефона для программы лояльности:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="📞 Отправить номер", request_contact=True)]],
            resize_keyboard=True
        )
    )

@dp.message(F.contact)
async def process_phone(message: types.Message):
    db.update_phone(message.from_user.id, message.contact.phone_number)
    await message.answer(
        "✅ Теперь вы участник программы лояльности!",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await show_main_menu(message)

# ---- Программа лояльности ----

async def show_main_menu(message: types.Message):
    visits_count = db.get_visits_count(message.from_user.id)
    remaining = 7 - (visits_count % 7) if visits_count % 7 != 0 else 0
    
    text = (
        f"🏠 Главное меню\n\n"
        f"🔄 Посещений: {visits_count}\n"
        f"🎫 До бесплатного кофе: {remaining}"
    )
    
    if remaining == 0 and visits_count > 0:
        text += "\n\n🎉 У вас сегодня бесплатный кофе!"
    
    await message.answer(
        text,
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="☕ Отметить посещение")],
                [types.KeyboardButton(text="🎁 Мои бонусы"), types.KeyboardButton(text="📅 События")],
                [types.KeyboardButton(text="📱 Контакты"), types.KeyboardButton(text="✉️ Отзыв")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(F.text == "☕ Отметить посещение")
async def mark_visit(message: types.Message):
    visits_count = db.add_visit(message.from_user.id)
    
    if visits_count % 7 == 0:
        await message.answer("🎉 Поздравляем! Ваше посещение №7 - бесплатный кофе!")
    else:
        await message.answer(
            f"✅ Посещение засчитано! Всего: {visits_count}\n"
            f"До бесплатного кофе: {7 - (visits_count % 7)}"
        )
    
    await show_main_menu(message)

@dp.message(F.text == "🎁 Мои бонусы")
async def show_bonuses(message: types.Message):
    visits_count = db.get_visits_count(message.from_user.id)
    await message.answer(
        f"Ваша карта лояльности:\n\n"
        f"☕ Посещений: {visits_count}\n"
        f"🎁 До бесплатного кофе: {7 - (visits_count % 7)}"
    )

@dp.message(F.text == "📅 События")
async def show_events(message: types.Message):
    events = db.get_events()
    
    if not events:
        await message.answer("На данный момент нет запланированных событий.")
        return
    
    for event in events:
        event_id, title, description, event_date, photo_id = event
        formatted_date = datetime.strptime(event_date, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y в %H:%M")
        
        text = f"🎪 <b>{title}</b>\n📅 {formatted_date}\n\n{description}"
        
        if photo_id:
            await message.answer_photo(photo_id, caption=text)
        else:
            await message.answer(text)

# ---- Админ-панель ----

@dp.message(F.text == "/admin")
async def admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора")
        return
    
    await message.answer(
        "👨‍💻 Панель администратора:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="📊 Статистика")],
                [types.KeyboardButton(text="📢 Рассылка")],
                [types.KeyboardButton(text="➕ Добавить событие")],
                [types.KeyboardButton(text="◀️ В главное меню")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    
    total_users, total_visits, top_users = db.get_stats()
    
    text = (
        f"📊 Статистика:\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🔄 Посещений: {total_visits}\n\n"
        f"🏆 Топ-5 клиентов:\n"
    )
    
    for i, (name, visits) in enumerate(top_users, 1):
        text += f"{i}. {name}: {visits} посещений\n"
    
    await message.answer(text)

@dp.message(F.text == "📢 Рассылка")
async def start_mailing(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    await message.answer(
        "Введите сообщение для рассылки:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Form.mailing_message)

@dp.message(Form.mailing_message)
async def process_mailing(message: types.Message, state: FSMContext):
    users = db.get_all_users()
    success = 0
    
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text)
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
    
    await message.answer(
        f"📤 Рассылка завершена!\n"
        f"✅ Успешно отправлено: {success}/{len(users)}",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.clear()
    await admin_panel(message)

@dp.message(F.text == "➕ Добавить событие")
async def start_adding_event(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    await message.answer(
        "Введите название события:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Form.event_title)

@dp.message(Form.event_title)
async def process_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите описание события:")
    await state.set_state(Form.event_description)

@dp.message(Form.event_description)
async def process_event_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите дату и время события (в формате ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(Form.event_date)

@dp.message(Form.event_date)
async def process_event_date(message: types.Message, state: FSMContext):
    try:
        event_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        await state.update_data(event_date=event_date.strftime("%Y-%m-%d %H:%M:%S"))
        await message.answer("Отправьте фото для события (или напишите 'пропустить'):")
        await state.set_state(Form.event_photo)
    except ValueError:
        await message.answer("Неверный формат даты. Введите дату в формате ДД.ММ.ГГГГ ЧЧ:ММ")

@dp.message(Form.event_photo)
async def process_event_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text and message.text.lower() == "пропустить":
        photo_id = None
    elif message.photo:
        photo_id = message.photo[-1].file_id
    else:
        await message.answer("Пожалуйста, отправьте фото или напишите 'пропустить'")
        return
    
    db.add_event(data['title'], data['description'], data['event_date'], photo_id)
    
    await message.answer("✅ Событие успешно добавлено!")
    await state.clear()
    await admin_panel(message)

@dp.message(F.text == "◀️ В главное меню")
async def back_to_main_menu(message: types.Message):
    await show_main_menu(message)

# ---- Дополнительные функции ----

@dp.message(F.text == "📱 Контакты")
async def show_contacts(message: types.Message):
    await message.answer(
        "🏠 Наш адрес: ул. Примерная, 123\n"
        "📞 Телефон: +7 (123) 456-78-90\n"
        "🕒 Часы работы: Пн-Пт 10:00-22:00, Сб-Вс 11:00-23:00"
    )

@dp.message(F.text == "✉️ Отзыв")
async def start_feedback(message: types.Message, state: FSMContext):
    await message.answer(
        "Напишите ваш отзыв или предложение:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Form.feedback)

@dp.message(Form.feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    # Здесь можно сохранить отзыв в базу или отправить администратору
    await message.answer("✅ Спасибо за ваш отзыв!")
    await state.clear()
    await show_main_menu(message)

# ---- Запуск бота ----

async def main():
    # Добавляем администратора при первом запуске
    db.add_admin(586842186)  # Замените на ваш ID
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())