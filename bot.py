import json
import random
import time
import os
from flask import Flask, request
import telebot
from telebot import types

TOKEN = "9182868414:AAGuB4M8xCr1o3Ws_s4dvgMrjc50j9rxWtQ"
WEBHOOK_URL = "https://onrender.com"

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

print(f"Успішно завантажено {len(QUESTIONS)} питань!", flush=True)

user_states = {}
user_mistakes = {}

EXAM_COUNT = 50
EXAM_SECONDS = 45 * 60
PASS_SCORE = 40

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🎯 Іспит (50 питань / 45 хв)")
    markup.row("🎲 Випадкове питання", "📚 Тренування по порядку")
    markup.row("❌ Робота над помилками")
    return markup

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        f"👋 Вітаю у тренажері геодезиста!\n"
        f"У базі доступно {len(QUESTIONS)} запитань.\n\n"
        f"Оберіть режим на клавіатурі нижче:",
        reply_markup=main_menu()
    )

@bot.message_handler(func=lambda m: m.text == "🎯 Іспит (50 питань / 45 хв)")
def start_exam(message):
    uid = message.from_user.id
    selected = random.sample(QUESTIONS, min(EXAM_COUNT, len(QUESTIONS)))
    user_states[uid] = {
        "mode": "exam",
        "questions": selected,
        "index": 0,
        "score": 0,
        "start_time": time.time(),
        "wrong": []
    }
    bot.send_message(
        message.chat.id,
        f"⏱ Іспит розпочато!\nПитань: {EXAM_COUNT} | Час: 45 хвилин\nПрохідний бал: {PASS_SCORE}. Успіхів!"
    )
    send_q(message.chat.id, uid)

@bot.message_handler(func=lambda m: m.text == "🎲 Випадкове питання")
def random_q(message):
    uid = message.from_user.id
    user_states[uid] = {"mode": "practice", "questions": [random.choice(QUESTIONS)], "index": 0}
    send_q(message.chat.id, uid)

@bot.message_handler(func=lambda m: m.text == "📚 Тренування по порядку")
def ordered_q(message):
    uid = message.from_user.id
    user_states[uid] = {"mode": "ordered", "questions": QUESTIONS, "index": 0}
    send_q(message.chat.id, uid)

@bot.message_handler(func=lambda m: m.text == "❌ Робота над помилками")
def mistakes_q(message):
    uid = message.from_user.id
    m_ids = user_mistakes.get(uid, set())
    if not m_ids:
        bot.send_message(message.chat.id, "🎉 У вас поки немає збережених помилок!")
        return
    m_list = [q for q in QUESTIONS if q["id"] in m_ids]
    random.shuffle(m_list)
    user_states[uid] = {"mode": "mistakes", "questions": m_list, "index": 0}
    bot.send_message(message.chat.id, f"🔄 Знайдено {len(m_list)} питань з помилками. Починаємо!")
    send_q(message.chat.id, uid)

def send_q(chat_id, uid):
    st = user_states.get(uid)
    if not st:
        return

    time_str = ""
    if st["mode"] == "exam":
        rem = EXAM_SECONDS - (time.time() - st["start_time"])
        if rem <= 0:
            finish_exam(chat_id, uid, timeout=True)
            return
        time_str = f"⏱ Залишилось часу: {int(rem // 60):02d}:{int(rem % 60):02d}\n"

    idx = st["index"]
    if idx >= len(st["questions"]):
        if st["mode"] == "exam":
            finish_exam(chat_id, uid, timeout=False)
        else:
            bot.send_message(chat_id, "✅ Усі питання цього блоку пройдено!", reply_markup=main_menu())
            user_states.pop(uid, None)
        return

    q = st["questions"][idx]
    letters = ["А", "Б", "В", "Г"]
    opts_text = ""
    markup = types.InlineKeyboardMarkup()

    for i, ans in enumerate(q["answers"]):
        ltr = letters[i] if i < len(letters) else str(i + 1)
        opts_text += f"\n{ltr}) {ans}"
        btn_label = f"{ltr}) {ans[:42]}..." if len(ans) > 42 else f"{ltr}) {ans}"
        markup.add(types.InlineKeyboardButton(text=btn_label, callback_data=f"ans_{i}"))

    header = f"Питання {idx + 1} з {len(st['questions'])} (ID #{q['id']})\n"
    bot.send_message(chat_id, f"{time_str}{header}\n❓ {q['text']}\n{opts_text}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def on_answer(call):
    uid = call.from_user.id
    st = user_states.get(uid)
    if not st:
        bot.answer_callback_query(call.id, "Цей тест вже завершено. Почніть новий!")
        return

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    chosen = int(call.data.split("_"))
    q = st["questions"][st["index"]]
    is_ok = (chosen == q["correct"])

    user_mistakes.setdefault(uid, set())
    if is_ok:
        user_mistakes[uid].discard(q["id"])
    else:
        user_mistakes[uid].add(q["id"])

    if st["mode"] == "exam":
        if is_ok:
            st["score"] += 1
        else:
            st["wrong"].append((q, chosen))
        bot.answer_callback_query(call.id, "Відповідь прийнято")
        st["index"] += 1
        send_q(call.message.chat.id, uid)
    else:
        right_txt = q["answers"][q["correct"]]
        if is_ok:
            res = f"✅ Правильно!\n\n📖 Пояснення: {q['explanation']}"
        else:
            res = f"❌ Помилка!\n✔ Правильна відповідь: {right_txt}\n\n📖 Пояснення: {q['explanation']}"
        bot.send_message(call.message.chat.id, res)
        bot.answer_callback_query(call.id)
        if st["mode"] in ["ordered", "mistakes"]:
            st["index"] += 1
            send_q(call.message.chat.id, uid)
        else:
            user_states.pop(uid, None)

def finish_exam(chat_id, uid, timeout=False):
    st = user_states.pop(uid, None)
    if not st:
        return
    score = st["score"]
    total = len(st["questions"])
    elapsed = int(time.time() - st["start_time"])
    status = "🎉 ІСПИТ СКЛАДЕНО!" if score >= PASS_SCORE else "😔 ІСПИТ НЕ СКЛАДЕНО"
    prefix = "⏰ Час вийшов (45 хвилин)!\n\n" if timeout else ""
    summary = (
        f"{prefix}{status}\n\n"
        f"📊 Результат: {score} з {total} ({round(score / total * 100, 1)}%)\n"
        f"🎯 Прохідний поріг: {PASS_SCORE} балів\n"
        f"⏱ Витрачено часу: {elapsed // 60} хв {elapsed % 60} сек"
    )
    bot.send_message(chat_id, summary, reply_markup=main_menu())

    if st["wrong"]:
        bot.send_message(chat_id, f"📋 Розбір помилок (показано до 15 з {len(st['wrong'])}):")
        for q, chosen in st["wrong"][:15]:
            wrong_ans = q["answers"][chosen] if chosen < len(q["answers"]) else "—"
            right_ans = q["answers"][q["correct"]]
            bot.send_message(
                chat_id,
                f"❓ {q['text']}\n❌ Ваша відповідь: {wrong_ans}\n✅ Правильно: {right_ans}\n📖 {q['explanation']}"
            )

@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id, "Оберіть режим на клавіатурі нижче або натисніть /start:", reply_markup=main_menu())

@app.route(f"/{TOKEN}", methods=["POST"])
def receive_update():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "Geodez Bot is active!", 200

if __name__ == "__main__":
    time.sleep(2)
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
        print("Webhook успішно встановлено!", flush=True)
    except Exception as e:
        print("Помилка встановлення webhook:", e, flush=True)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
