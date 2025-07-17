import json
import logging
from telebot import TeleBot
from funciones import buscar_codigo, buscar_link_actualizar_hogar
from keep_alive import mantener_vivo

# Token del bot
TOKEN = '7654437554:AAGCoNqZxd8EBo_7d9yE5Llr06i24QAJmaY'
bot = TeleBot(TOKEN)

# === COMANDOS ===

@bot.message_handler(commands=['code'])
def enviar_codigo(mensaje):
    partes = mensaje.text.split(" ", 1)
    if len(partes) < 2:
        bot.reply_to(mensaje, "❌ Escribe el comando así:\n`/code correo@dgplayk.com`", parse_mode="Markdown")
        return

    correo = partes[1].strip()
    bot.reply_to(mensaje, "🔍 Buscando código, por favor espera...")
    resultado = buscar_codigo(correo)

    if resultado:
        bot.reply_to(mensaje, resultado)
    else:
        bot.reply_to(mensaje, "❌ No se encontró un código reciente para ese correo.")

@bot.message_handler(commands=['hogar'])
def enviar_link_hogar(mensaje):
    partes = mensaje.text.split(" ", 1)
    if len(partes) < 2:
        bot.reply_to(mensaje, "❌ Escribe el comando así:\n`/hogar correo@dgplayk.com`", parse_mode="Markdown")
        return

    correo = partes[1].strip()
    bot.reply_to(mensaje, "🔵 Buscando link de hogar, por favor espera...")
    resultado = buscar_link_actualizar_hogar(correo)

    if resultado:
        bot.reply_to(mensaje, f"🏠 Link para actualizar hogar:\n\n{resultado}")
    else:
        bot.reply_to(mensaje, "❌ No se encontró link de hogar reciente.")

@bot.message_handler(commands=['cuentas'])
def comando_cuentas(mensaje):
    try:
        cuentas = cargar_cuentas()
        user_id = str(mensaje.from_user.id)
        if user_id in cuentas:
            lista = '\n'.join(f"📧 {c}" for c in cuentas[user_id])
            bot.reply_to(mensaje, f"📂 Tus cuentas autorizadas:\n\n{lista}")
        else:
            bot.reply_to(mensaje, "❌ No tienes cuentas registradas.")
    except Exception as e:
        logging.error(f"Error al leer cuentas.json: {e}")
        bot.reply_to(mensaje, f"⚠️ Error al leer las cuentas: {e}")

@bot.message_handler(commands=['id'])
def comando_id(mensaje):
    bot.reply_to(mensaje, f"🆔 Tu ID de Telegram es: `{mensaje.from_user.id}`", parse_mode="Markdown")

# === FUNCIONES AUXILIARES ===

def cargar_cuentas():
    with open("cuentas.json", "r") as archivo:
        return json.load(archivo)

# === INICIO ===
print("🤖 Bot en funcionamiento...")
mantener_vivo()
bot.infinity_polling()

