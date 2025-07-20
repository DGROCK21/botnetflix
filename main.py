import os
import json
import logging
from telebot import TeleBot
from funciones import buscar_codigo, buscar_link_actualizar_hogar
from keep_alive import mantener_vivo

logging.basicConfig(level=logging.INFO)

# Token del bot
TOKEN = os.environ.get("BOT_TOKEN", "7654437554:AAGCoNqZxd8EBo_7d9yE5Llr06i24QAJmaY")
bot = TeleBot(TOKEN)

# === Función para cargar cuentas desde el archivo JSON ===
def cargar_cuentas():
    try:
        with open("cuentas.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error cargando cuentas.json: {e}")
        return {"usuarios": []}

# === Comando /code ===
@bot.message_handler(commands=["code"])
def code(update):
    partes = update.text.split(" ", 1)
    if len(partes) < 2:
        bot.reply_to(update, "❌ Usa el comando así:\n`/code correo@ejemplo.com`", parse_mode="Markdown")
        return

    correo = partes[1].strip()
    datos = cargar_cuentas()
    autorizado = False
    existe = False

    for usuario in datos["usuarios"]:
        if correo in usuario["correos"]:
            existe = True
            if usuario.get("autorizado", False):
                autorizado = True
            break

    if not existe:
        bot.reply_to(update, "❌ Ese correo no está registrado en el sistema.")
        return
    if not autorizado:
        bot.reply_to(update, "⛔ Ese correo existe pero no está autorizado.")
        return

    bot.reply_to(update, "🔍 Buscando código, por favor espera...")
    link = buscar_codigo(correo)
    bot.reply_to(update, link)

# === Comando /hogar ===
@bot.message_handler(commands=["hogar"])
def hogar(update):
    partes = update.text.split(" ", 1)
    if len(partes) < 2:
        bot.reply_to(update, "❌ Usa el comando así:\n`/hogar correo@ejemplo.com`", parse_mode="Markdown")
        return

    correo = partes[1].strip()
    datos = cargar_cuentas()
    autorizado = False
    existe = False

    for usuario in datos["usuarios"]:
        if correo in usuario["correos"]:
            existe = True
            if usuario.get("autorizado", False):
                autorizado = True
            break

    if not existe:
        bot.reply_to(update, "❌ Ese correo no está registrado en el sistema.")
        return
    if not autorizado:
        bot.reply_to(update, "⛔ Ese correo existe pero no está autorizado.")
        return

    bot.reply_to(update, "🔵 Buscando link de hogar, por favor espera...")
    link = buscar_link_actualizar_hogar(correo)
    bot.reply_to(update, link)

# === Comando /cuentas ===
@bot.message_handler(commands=["cuentas"])
def cuentas(update):
    datos = cargar_cuentas()
    user_id = str(update.from_user.id)

    for usuario in datos["usuarios"]:
        if usuario.get("id") == user_id:
            correos = usuario.get("correos", [])
            if correos:
                lista = "\n".join(f"📧 {c}" for c in correos)
                bot.reply_to(update, f"📂 Tus correos autorizados:\n\n{lista}")
            else:
                bot.reply_to(update, "🔍 No tienes correos registrados.")
            return

    bot.reply_to(update, "❌ No estás registrado como usuario.")

# === Comando /id ===
@bot.message_handler(commands=["id"])
def mostrar_id(update):
    bot.reply_to(update, f"🆔 Tu ID de Telegram es: `{update.from_user.id}`", parse_mode="Markdown")

# === Iniciar bot ===
print("🤖 Bot activo y funcionando.")
mantener_vivo()
bot.remove_webhook()
bot.infinity_polling()
