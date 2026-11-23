import json
import random
import time
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot
from telebot import types

TOKEN = "9182868414:AAGuB4M8xCr1o3Ws_s4dvgMrjc50j9rxWtQ"
bot = telebot.TeleBot(TOKEN)

# --- ФОНОВИЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Geodez Telegram Bot is running!".encode("utf-8"))

    def log_message(self, format, *args):
        pass

def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- ЗАВАНТАЖЕННЯ БАЗИ ПИТАНЬ ---
def load_questions():
    if os.path.exists("questions.json"):
        with open("questions.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

QUESTIONS = load_questions()
print(f"Успішно завантажено {len(QUESTIONS)} питань!")

user_states = {}
user_mistakes = {}

EXAM_QUESTIONS_COUNT = 50
EXAM_TIME_SECONDS = 45 * 60
PASS_SCORE = 40

def escape_md(text):
    if not text:
        return ""
    for ch in ['_', '*', '`', '[']:
        text = str(text).replace(ch, '\\' + ch)
    return text

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🎯 Іспит (50 питань / 45 хв)")
    markup.row("🎲 Випадкове питання", "📚 Тренування по порядку")
    markup.row("❌ Робота над помилками")
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    bot.send_message(
        message.chat.id,
        f"👋 Вітаю у тренажері геодезиста!\n"
        f"У базі доступно *{len(QUESTIONS)}* запитань.\n\n"
        f"Оберіть режим підготовки на клавіатурі нижче:",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )

@bot.message_handler(func=lambda m: m.text == "🎯 Іспит (50 питань / 45 хв)")
def start_exam(message):
    if not QUESTIONS:
        bot.send_message(message.chat.id, "⚠️ База питань порожня. Перевірте файл questions.json.")
        return
    user_id = message.from_user.id
    selected = random.sample(QUESTIONS, min(EXAM_QUESTIONS_COUNT, len(QUESTIONS)))
    user_states[user_id] = {
        "mode": "exam",
        "questions": selected,
        "index": 0,
        "score": 0,
        "start_time": time.time(),
        "wrong_list": []
    }
    bot.send_message(
        message.chat.id,
        f"⏱ *Іспит розпочато!*\n"
        f"Питань: *{len(selected)}* | Час: *45 хвилин*\n"
        f"Прохідний бал: *{PASS_SCORE}* правильних відповідей.\nУспіхів!",
        parse_mode="Markdown"
    )
    send_question(message.chat.id, user_id)

@bot.message_handler(func=lambda m: m.text == "🎲 Випадкове питання")
def random_q(message):
    if not QUESTIONS:
        return
    user_id = message.from_user.id
    q = random.choice(QUESTIONS)
    user_states[user_id] = {
        "mode": "practice",
        "questions": [q],
        "index": 0
    }
    send_question(message.chat.id, user_id)

@bot.message_handler(func=lambda m: m.text == "📚 Тренування по порядку")
def ordered_q(message):
    if not QUESTIONS:
        return
    user_id = message.from_user.id
    user_states[user_id] = {
        "mode": "ordered",
        "questions": QUESTIONS,
        "index": 0
    }
    send_question(message.chat.id, user_id)

@bot.message_handler(func=lambda m: m.text == "❌ Робота над помилками")
def mistakes_q(message):
    user_id = message.from_user.id
    mistakes_ids = user_mistakes.get(user_id, set())
    if not mistakes_ids:
        bot.send_message(message.chat.id, "🎉 У вас поки немає збережених помилок! Пройдіть іспит або тренування.")
        return
    m_questions = [q for q in QUESTIONS if q["id"] in mistakes_ids]
    random.shuffle(m_questions)
    user_states[user_id] = {
        "mode": "mistakes",
        "questions": m_questions,
        "index": 0
    }
    bot.send_message(message.chat.id, f"🔄 Знайдено *{len(m_questions)}* питань з помилками. Починаємо!", parse_mode="Markdown")
    send_question(message.chat.id, user_id)

def send_question(chat_id, user_id):
    state = user_states.get(user_id)
    if not state:
        return

    time_header = ""
    if state["mode"] == "exam":
        elapsed = time.time() - state["start_time"]
        remaining = EXAM_TIME_SECONDS - elapsed
        if remaining <= 0:
            finish_exam(chat_id, user_id, timeout=True)
            return
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        time_header = f"⏱ Залишилось часу: *{mins:02d}:{secs:02d}*\n"

    idx = state["index"]
    if idx >= len(state["questions"]):
        if state["mode"] == "exam":
            finish_exam(chat_id, user_id, timeout=False)
        else:
            bot.send_message(chat_id, "✅ Усі питання цього блоку пройдено!", reply_markup=get_main_menu())
            user_states.pop(user_id, None)
        return

    q = state["questions"][idx]
    total = len(state["questions"])

    letters = ["А", "Б", "В", "Г", "Д"]
    options_text = ""
    markup = types.InlineKeyboardMarkup()

    for i, ans in enumerate(q["answers"]):
        letter = letters[i] if i < len(letters) else str(i + 1)
        clean_ans = escape_md(ans)
        options_text += f"\n*{letter})* {clean_ans}"
        btn_label = f"{letter}) {ans[:42]}..." if len(ans) > 42 else f"{letter}) {ans}"
        markup.add(types.InlineKeyboardButton(text=btn_label, callback_data=f"ans_{i}"))

    header = f"Питання *{idx + 1} з {total}* (ID #{q['id']})\n" if state["mode"] != "practice" else f"Випадкове питання (ID #{q['id']})\n"
    full_msg = f"{time_header}{header}\n❓ *{escape_md(q['text'])}*\n{options_text}"

    bot.send_message(chat_id, full_msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def handle_answer(call):
    user_id = call.from_user.id
    state = user_states.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "Цей тест вже завершено. Натисніть /start або оберіть режим у меню.")
        return

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    chosen = int(call.data.split("_")[1])
    q = state["questions"][state["index"]]
    is_correct = (chosen == q["correct"])

    if user_id not in user_mistakes:
        user_mistakes[user_id] = set()

    if is_correct:
        user_mistakes[user_id].discard(q["id"])
    else:
        user_mistakes[user_id].add(q["id"])

    if state["mode"] == "exam":
        if is_correct:
            state["score"] += 1
        else:
            state["wrong_list"].append((q, chosen))
        bot.answer_callback_query(call.id, "Відповідь прийнято")
        state["index"] += 1
        send_question(call.message.chat.id, user_id)
    else:
        correct_text = escape_md(q["answers"][q["correct"]])
        expl_text = escape_md(q.get("explanation", ""))
        if is_correct:
            res = f"✅ *Правильно!*\n\n📖 _Пояснення:_ {expl_text}"
        else:
            res = f"❌ *Помилка!*\n✔ Правильна відповідь: *{correct_text}*\n\n📖 _Пояснення:_ {expl_text}"

        bot.send_message(call.message.chat.id, res, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

        if state["mode"] in ["ordered", "mistakes"]:
            state["index"] += 1
            send_question(call.message.chat.id, user_id)
        else:
            user_states.pop(user_id, None)

def finish_exam(chat_id, user_id, timeout=False):
    state = user_states.pop(user_id, None)
    if not state:
        return

    score = state["score"]
    total = len(state["questions"])
    elapsed = int(time.time() - state["start_time"])
    mins = elapsed // 60
    secs = elapsed % 60
    percent = round((score / total) * 100, 1) if total > 0 else 0

    status = "🎉 *ІСПИТ СКЛАДЕНО!*" if score >= PASS_SCORE else "😔 *ІСПИТ НЕ СКЛАДЕНО*"
    timeout_msg = "⏰ _Час вийшов (45 хвилин)!_\n\n" if timeout else ""

    summary = (
        f"{timeout_msg}{status}\n\n"
        f"📊 Результат: *{score} з {total}* ({percent}%)\n"
        f"🎯 Прохідний поріг: *{PASS_SCORE}* балів\n"
        f"⏱ Витрачено часу: *{mins} хв {secs} сек*"
    )
    bot.send_message(chat_id, summary, parse_mode="Markdown", reply_markup=get_main_menu())

    if state["wrong_list"]:
        bot.send_message(chat_id, f"📋 *Розбір ваших помилок ({len(state['wrong_list'])} шт.):*", parse_mode="Markdown")
        for q, chosen in state["wrong_list"][:15]:
            wrong_ans = escape_md(q["answers"][chosen]) if chosen < len(q["answers"]) else "—"
            right_ans = escape_md(q["answers"][q["correct"]])
            expl_text = escape_md(q.get("explanation", ""))
            msg = (
                f"❓ *{escape_md(q['text'])}*\n"
                f"❌ Ваша відповідь: {wrong_ans}\n"
                f"✅ Правильно: *{right_ans}*\n"
                f"📖 _{expl_text}_"
            )
            bot.send_message(chat_id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id, "Оберіть режим тестування на кнопках нижче 👇", reply_markup=get_main_menu())

if __name__ == "__main__":
    threading.Thread(target=start_web_server, daemon=True).start()
    print("Веб-сервер та бот запущені...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print("Помилка polling, перезапуск через 5 сек:", e)
            time.sleep(5)
