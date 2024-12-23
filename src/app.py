import os
import io
import logging
import requests
import nltk
import chromadb
import chardet
from docx import Document
from dotenv import load_dotenv
from telebot import TeleBot
from sentence_transformers import SentenceTransformer
import spacy
from nltk.tokenize import sent_tokenize

# Загрузка переменных окружения
load_dotenv()

# Инициализация и подготовка NLTK ресурсов
nltk_modules = ['punkt', 'punkt_tab', 'averaged_perceptron_tagger', 'maxent_ne_chunker', 'words']
for module in nltk_modules:
    nltk.download(module)

# Настройка логирования
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("TextProcessorBot")

# Настройка ChromaDB для хранения текстовых данных
chromadb_client = chromadb.Client()
text_storage = chromadb_client.create_collection(name="text_storage")

# Инициализация текстовых моделей
text_model = SentenceTransformer('paraphrase-MiniLM-L12-v2')
nlp = spacy.load("en_core_web_sm")

def parse_file_content(file_bytes, file_name):
    """Извлекает текст из файла подходящего формата."""
    try:
        if file_name.endswith('.txt'):
            encoding = chardet.detect(file_bytes)['encoding']
            return file_bytes.decode(encoding)
        elif file_name.endswith('.docx'):
            document = Document(io.BytesIO(file_bytes))
            return "\n".join([p.text for p in document.paragraphs])
        else:
            logger.warning(f"Unsupported file format: {file_name}")
            return None
    except Exception as ex:
        logger.error(f"Error reading file {file_name}: {ex}")
        return None

def store_text_data(file_content, file_name):
    """Разбивает текст на предложения и сохраняет их в базу данных."""
    content = parse_file_content(file_content, file_name)
    if not content:
        return "Unable to process the file content."

    sentences = sent_tokenize(content)
    logger.info(f"File {file_name} split into {len(sentences)} sentences.")

    for idx, sentence in enumerate(sentences):
        try:
            embedding = text_model.encode(sentence)
            text_storage.add(
                ids=[str(idx)],
                embeddings=[embedding],
                documents=[sentence]
            )
            logger.debug(f"Stored sentence {idx + 1}: {sentence[:50]}...")
        except Exception as ex:
            logger.error(f"Error storing sentence {idx + 1}: {ex}")
            return f"Failed to store data from file {file_name}."

    return "File data successfully stored!"

def download_file(file_id, bot, file_name):
    """Загружает файл из Telegram и передаёт его для обработки."""
    try:
        file_info = bot.get_file(file_id)
        download_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
        response = requests.get(download_url)

        if response.status_code == 200:
            logger.info(f"File {file_name} successfully downloaded.")
            return store_text_data(response.content, file_name)
        else:
            logger.error(f"Failed to download {file_name}: HTTP {response.status_code}")
            return "Failed to download the file."
    except Exception as ex:
        logger.error(f"Error downloading file {file_id}: {ex}")
        return "An error occurred during file processing."

def identify_entities(text):
    """Извлекает именованные сущности из текста."""
    doc = nlp(text)
    return [(ent.text, ent.label_) for ent in doc.ents]

def perform_search(query, collection, top_results=5):
    """Выполняет поиск похожих текстов в базе данных."""
    try:
        query_vector = text_model.encode(query)
        search_results = collection.query(
            query_embeddings=[query_vector],
            n_results=top_results
        )

        if not search_results.get('documents', []):
            return "No matches found. Please refine your query."

        result_message = "Search results:\n"
        for idx, document in enumerate(search_results['documents'][0]):
            result_message += f"{idx + 1}. {document}\n"
        return result_message
    except Exception as ex:
        logger.error(f"Error during search: {ex}")
        return "An error occurred during the search."

def greet_user(message, bot):
    """Отправляет приветствие пользователю."""
    try:
        welcome_text = (
            "Hello! 👋\n"
            "I can process text files and help you find relevant information.\n"
            "Please send a .txt or .docx file to get started!"
        )
        bot.send_message(message.chat.id, welcome_text)
        logger.info(f"Welcome message sent to user {message.chat.id}.")
    except Exception as ex:
        logger.error(f"Error sending welcome message: {ex}")

def process_user_query(message, bot):
    """Обрабатывает текстовые запросы от пользователя."""
    try:
        user_input = message.text
        logger.info(f"Received query: {user_input}")
        response = perform_search(user_input, text_storage)
        bot.send_message(message.chat.id, response)
    except Exception as ex:
        logger.error(f"Error handling query: {ex}")
        bot.send_message(message.chat.id, "Failed to process your query.")

def process_uploaded_file(message, bot):
    """Обрабатывает файл, загруженный пользователем."""
    try:
        file = message.document
        file_name = file.file_name
        if file_name.endswith(('.txt', '.docx')):
            result = download_file(file.file_id, bot, file_name)
            bot.send_message(message.chat.id, result)
        else:
            bot.send_message(message.chat.id, "Please upload a .txt or .docx file.")
    except Exception as ex:
        logger.error(f"Error processing uploaded file: {ex}")
        bot.send_message(message.chat.id, "An error occurred while processing the file.")

# Настройка Telegram-бота
telegram_api_token = os.getenv("BOT_TOKEN")
bot = TeleBot(telegram_api_token)

@bot.message_handler(commands=['start'])
def start_handler(message):
    greet_user(message, bot)

@bot.message_handler(content_types=['document'])
def document_handler(message):
    process_uploaded_file(message, bot)

@bot.message_handler(func=lambda msg: True, content_types=['text'])
def text_handler(message):
    process_user_query(message, bot)

if __name__ == "__main__":
    try:
        logger.info("Bot is up and running.")
        bot.infinity_polling()
    except Exception as ex:
        logger.critical(f"Critical failure: {ex}")