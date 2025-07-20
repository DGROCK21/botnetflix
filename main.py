import telebot
import json
import os
from funciones import obtener_link_mas_reciente
from keep_alive import keep_alive

# Cargar cuentas autorizadas
with open('cuentas.json', 'r') as f:
    cuentas = json.load(f)

BOT_TOKEN = os.environ.get('BOT_TOKEN') or 'TU_BOT_TOKEN_AQUI'
bot = telebot.TeleBot(BOT_TOKEN)

# Eliminar cualquier webhook anterior para evitar conflicto (error 409)
bot.remove_webhook()

# Comando /start
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "👋 Hola, envía el comando /code o /hogar seguido del correo.")

# Comando /code
@bot.message_handler(commands=['code'])
def cmd_code(message):
    try:
        partes = message.text.strip().split()
        if len(partes) != 2:
            bot.reply_to(message, "❗ Uso incorrecto. Ejemplo:\n/code usuario@ejemplo.com")
            return

        correo = partes[1].lower()

        # Validar si correo existe
        encontrado = False
        autorizado = False
        for usuario in cuentas['usuarios']:
            if correo in usuario['correos']:
                encontrado = True
                if usuario['autorizado']:
                    autorizado = True
                break

        if not encontrado:
            bot.reply_to(message, "📪 El correo ingresado no está en la lista.")
            return

        if not autorizado:
            bot.reply_to(message, "🔒 Este correo no está autorizado para usar el bot.")
            return

        bot.reply_to(message, "🔍 Buscando código, por favor espera...")

        link = obtener_link_mas_reciente(correo, tipo='code')
        if link:
            bot.send_message(message.chat.id, f"✅ Código encontrado:\n{link}")
        else:
            bot.send_message(message.chat.id, "❌ No se encontró un código reciente para ese correo.")

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Error: {str(e)}")

# Comando /hogar
@bot.message_handler(commands=['hogar'])
def cmd_hogar(message):
    try:
        partes = message.text.strip().split()
        if len(partes) != 2:
            bot.reply_to(message, "❗ Uso incorrecto. Ejemplo:\n/hogar usuario@ejemplo.com")
            return

        correo = partes[1].lower()

        # Validar si correo existe
        encontrado = False
        autorizado = False
        for usuario in cuentas['usuarios']:
            if correo in usuario['correos']:
                encontrado = True
                if usuario['autorizado']:
                    autorizado = True
                break

        if not encontrado:
            bot.reply_to(message, "📪 El correo ingresado no está en la lista.")
            return

        if not autorizado:
            bot.reply_to(message, "🔒 Este correo no está autorizado para usar el bot.")
            return

        bot.reply_to(message, "🏠 Buscando enlace de hogar, por favor espera...")

        link = obtener_link_mas_reciente(correo, tipo='hogar')
        if link:
            bot.send_message(message.chat.id, f"✅ Enlace de hogar encontrado:\n{link}")
        else:
            bot.send_message(message.chat.id, "❌ No se encontró un enlace de hogar reciente para ese correo.")

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Error: {str(e)}")

# Mantener vivo en Render
keep_alive()

# Iniciar el bot
bot.infinity_polling()
