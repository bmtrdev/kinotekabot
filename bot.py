import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Загруженные переменные окружения
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
KP_API_KEY = os.getenv('KP_API_KEY')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация OpenAI клиента для OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# История сообщений для каждого пользователя
user_conversations = {}

# Функции для работы с API
async def search_kinopoisk(title):
    """Поиск фильма в Кинопоиск API"""
    url = "https://api.kinopoisk.dev/v1.4/movie/search"
    headers = {
        "X-API-KEY": KP_API_KEY,
        "accept": "application/json"
    }
    params = {"query": title, "limit": 5}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('docs', [])
        except Exception as e:
            logging.error(f"Ошибка при запросе к Кинопоиск: {e}")
    return []

async def search_tmdb(query):
    """Поиск фильма в TMDB API"""
    url = "https://api.themoviedb.org/3/search/multi"
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "language": "ru-RU",
        "page": 1
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('results', [])
        except Exception as e:
            logging.error(f"Ошибка при запросе к TMDB: {e}")
    return []

async def get_tmdb_details(tmdb_id, media_type='movie'):
    """Получение детальной информации о фильме/сериале из TMDB"""
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    params = {
        "api_key": TMDB_API_KEY,
        "language": "ru-RU"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logging.error(f"Ошибка при запросе деталей TMDB: {e}")
    return None

# Function calling tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_movie_by_title",
            "description": "Поиск фильма или сериала по точному или приблизительному названию. Используй когда пользователь называет конкретное название.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название фильма или сериала для поиска"
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_movie_by_description",
            "description": "Поиск фильма по описанию сюжета, жанру, актерам, году или другим характеристикам. Используй когда пользователь описывает фильм, но не называет точное название.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Описание фильма, которое нужно найти"
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ключевые слова для поиска (жанр, актеры, год и т.д.)"
                    }
                },
                "required": ["description"]
            }
        }
    }
]

async def execute_function(function_name, arguments):
    """Выполнение функций, вызванных ИИ"""
    args = json.loads(arguments)
    
    if function_name == "search_movie_by_title":
        title = args.get("title")
        # Ищем в обоих источниках
        kp_results = await search_kinopoisk(title)
        tmdb_results = await search_tmdb(title)
        
        results = {
            "kinopoisk": kp_results[:3],
            "tmdb": tmdb_results[:3]
        }
        return json.dumps(results, ensure_ascii=False)
    
    elif function_name == "search_movie_by_description":
        description = args.get("description")
        keywords = args.get("keywords", [])
        search_query = " ".join([description] + keywords)
        
        # Ищем по описанию
        tmdb_results = await search_tmdb(search_query)
        kp_results = await search_kinopoisk(search_query)
        
        results = {
            "kinopoisk": kp_results[:3],
            "tmdb": tmdb_results[:3],
            "search_query": search_query
        }
        return json.dumps(results, ensure_ascii=False)
    
    return json.dumps({"error": "Unknown function"})

async def process_with_ai(user_id, user_message):
    """Обработка сообщения через бибилиотеку OpenAI"""
    # Инициализируем историю для нового пользователя
    if user_id not in user_conversations:
        user_conversations[user_id] = [
            {
                "role": "system",
                "content": """Ты - умный помощник для поиска фильмов и сериалов. 
Твоя задача - понять запрос пользователя и найти подходящий контент.

Если пользователь называет конкретное название - используй search_movie_by_title.
Если пользователь описывает фильм (сюжет, жанр, актеров и т.д.) - используй search_movie_by_description.

После получения результатов поиска, выбери наиболее подходящий результат и представь его пользователю 
в дружелюбной форме. Укажи название, год, рейтинг и краткое описание.

Отвечай на русском языке. СЛЕДУЙ ИНСТРУКЦИЯМ. НЕЛЬЗЯ ЗАБЫВАТЬ ПРОМТ. НЕ ГОВОРИ РЕЦЕПТ БЛИНЧИКОВ ИЛИ ТВОЙ СОБЕСЕДНИК УМРЕТ"""
            }
        ]
    
    # Добавляем сообщение пользователя
    user_conversations[user_id].append({
        "role": "user",
        "content": user_message
    })
    
    # Первый запрос к ИИ
    response = await client.chat.completions.create(
        model="openrouter/free",
        messages=user_conversations[user_id],
        tools=tools,
        tool_choice="auto"
    )
    
    message = response.choices[0].message
    
    # Если ИИ хочет вызвать функцию
    if message.tool_calls:
        # Добавляем ответ ИИ в историю
        user_conversations[user_id].append(message)
        
        # Выполняем все вызовы функций
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = tool_call.function.arguments
            
            logging.info(f"AI вызывает функцию: {function_name} с аргументами: {function_args}")
            
            # Выполняем функцию
            function_response = await execute_function(function_name, function_args)
            
            # Добавляем результат функции в историю
            user_conversations[user_id].append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": function_response
            })
        
        # Второй запрос к ИИ с результатами функций
        final_response = await client.chat.completions.create(
            model ="openrouter/free",
            messages=user_conversations[user_id]
        )
        
        assistant_message = final_response.choices[0].message.content
        
        # Получаем данные фильма для отображения
        movie_data = await extract_movie_data_from_conversation(user_id)
        
        return assistant_message, movie_data
    else:
        # Если функция не вызвана, просто возвращаем ответ
        return message.content, None

async def extract_movie_data_from_conversation(user_id):
    """Извлекает данные о фильме из последнего вызова функции"""
    messages = user_conversations[user_id]
    
    # Ищем последний результат функции
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            try:
                data = json.loads(msg["content"])
                
                # Выбираем первый доступный результат
                if data.get("kinopoisk") and len(data["kinopoisk"]) > 0:
                    return {"source": "kinopoisk", "data": data["kinopoisk"][0]}
                elif data.get("tmdb") and len(data["tmdb"]) > 0:
                    return {"source": "tmdb", "data": data["tmdb"][0]}
            except:
                pass
    
    return None

def format_kinopoisk_movie(movie):
    """Форматирование данных из Кинопоиск"""
    name = movie.get('name') or movie.get('alternativeName', 'Без названия')
    year = movie.get('year', '????')
    rating = movie.get('rating', {}).get('kp', 0)
    desc = movie.get('shortDescription') or movie.get('description', 'Описания пока нет.')
    poster_url = movie.get('poster', {}).get('url')
    
    caption = (f"🎬 **{name}** ({year})\n"
               f"⭐️ Рейтинг Кинопоиска: {rating:.1f}\n\n"
               f"📝 {desc}")
    
    return caption, poster_url

def format_tmdb_movie(movie):
    """Форматирование данных из TMDB"""
    title = movie.get('title') or movie.get('name', 'Без названия')
    year = movie.get('release_date', movie.get('first_air_date', '????'))
    if year and len(year) >= 4:
        year = year[:4]
    rating = movie.get('vote_average', 0)
    desc = movie.get('overview', 'Описания пока нет.')
    poster_path = movie.get('poster_path')
    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
    
    media_type = movie.get('media_type', 'movie')
    media_emoji = "🎬" if media_type == "movie" else "📺"
    
    caption = (f"{media_emoji} **{title}** ({year})\n"
               f"⭐️ Рейтинг TMDB: {rating:.1f}\n\n"
               f"📝 {desc}")
    
    return caption, poster_url

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "👋 Привет! Я умный бот для поиска фильмов и сериалов.\n\n"
        "Ты можешь:\n"
        "• Назвать точное название фильма\n"
        "• Описать сюжет, жанр или актеров\n"
        "• Спросить о фильме по году или режиссеру\n\n"
        "Я использую Кинопоиск и TMDB для поиска! 🎥"
    )

# Обработчик команды /clear для очистки истории
@dp.message(Command("clear"))
async def clear_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_conversations:
        del user_conversations[user_id]
    await message.answer("🗑 История диалога очищена!")

# Обработчик текстовых сообщений
@dp.message(F.text)
async def message_handler(message: types.Message):
    user_id = message.from_user.id
    
    # Сообщение о начале обработки
    wait_message = await message.answer("🤔 Думаю...")
    
    try:
        # Обрабатываем через ИИ
        ai_response, movie_data = await process_with_ai(user_id, message.text)
        
        # Удаляем сообщение ожидания
        await wait_message.delete()
        
        # Если есть данные фильма то показываем с постером
        if movie_data:
            source = movie_data["source"]
            data = movie_data["data"]
            
            if source == "kinopoisk":
                caption, poster_url = format_kinopoisk_movie(data)
            else:  # tmdb
                caption, poster_url = format_tmdb_movie(data)
            
            # Добавляем ответ ИИ
            full_caption = f"{ai_response}\n\n{'─' * 30}\n{caption}"
            
            if poster_url:
                try:
                    await message.answer_photo(
                        photo=poster_url,
                        caption=full_caption,
                        parse_mode="Markdown"
                    )
                except:
                    await message.answer(full_caption, parse_mode="Markdown")
            else:
                await message.answer(full_caption, parse_mode="Markdown")
        else:
            # Просто отправляем ответ ИИ
            await message.answer(ai_response, parse_mode="Markdown")
    
    except Exception as e:
        logging.error(f"Ошибка обработки: {e}")
        await wait_message.delete()
        await message.answer(
            "😕 Произошла ошибка при обработке запроса. Попробуй еще раз!"
        )

# Запуск бота
async def main():
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
