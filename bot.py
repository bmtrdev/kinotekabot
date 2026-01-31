import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from dotenv import load_dotenv

# Загруженные переменные окружения
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
KP_API_KEY = os.getenv('KP_API_KEY')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

#   Запрос к API kinopoisk.dev
async def get_movie_info(title):
    url = "https://api.kinopoisk.dev/v1.4/movie/search"
    headers = {
        "X-API-KEY": KP_API_KEY,
        "accept": "application/json"
    }
    params = {"query": title, "limit": 1}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('docs'):
                        return data['docs'][0]
                    return None
        except Exception as e:
            logging.error(f"Ошибка при запросе: {e}")
            return None

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("Привет! Напиши название фильма, и я найду информацию о нем.")

# Обработчик текстовых сообщений (поиск фильма) 
@dp.message(F.text)
async def search_handler(message: types.Message):
    # Сообщение о начале поиска
    wait_message = await message.answer("Ищу в базе...")
    
    movie = await get_movie_info(message.text)
    
    if movie:
        name = movie.get('name') or movie.get('alternativeName', 'Без названия')
        year = movie.get('year', '????')
        rating = movie.get('rating', {}).get('kp', 0)
        desc = movie.get('shortDescription') or movie.get('description', 'Описания пока нет.')
        poster_url = movie.get('poster', {}).get('url')

        caption = (f"🎬 **{name}** ({year})\n"
                   f"⭐️ Рейтинг Кинопоиска: {rating:.1f}\n\n"
                   f"📝 {desc}")

        if poster_url:
            await message.answer_photo(photo=poster_url, caption=caption, parse_mode="Markdown")
        else:
            await message.answer(caption, parse_mode="Markdown")
    else:
        await message.answer("К сожалению, я не нашел такой фильм. Попробуй другое название.")
    
    # Удаляем сообщение о поиске
    await wait_message.delete()

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())