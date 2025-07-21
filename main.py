import telebot
import os
import json
import imaplib
import email
import re
import logging
from email.header import decode_header
from flask import Flask, request
from keep_alive import mantener_vivo

# Cargar cuentas desde archivo
with open("cuentas.json", "r") as file:
    cuentas = json.load(file)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN no está definido.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# =====================
# Funciones auxiliares
# =====================

def obtener_credenciales(correo):
    for user_id, correos in cuentas.items():
        for entrada in correos:
            if entrada.startswith(correo):
                partes = entrada.split("|")
                if len(partes) == 3:
                    return partes[1], partes[2]
    return None, None

def buscar_ultimo_correo(correo, asunto_clave):
    usuario, contrasena = obtener_credenciales(correo)
    if not usuario or not contrasena:
        return None, "❌ No se encontraron credenciales para ese correo."

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario, contrasena)
        mail.select("inbox")
        _, mensajes = mail.search(None, "ALL")
        mensajes = mensajes[0].split()

        for num in reversed(mensajes[-20:]):
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            asunto, codificacion = decode_header(mensaje["Subject"])[0]
            if isinstance(asunto, bytes):
                asunto = asunto.decode(codificacion or "utf-8")

            if asunto_clave.lower() in asunto.lower():
                if mensaje.is_multipart():
                    for parte in mensaje.walk():
                        if parte.get_content_type() == "text/html":
                            html = parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8")
                            mail.logout()
                            return html, None
                else:
                    html = mensaje.get_payload(decode=True).decode(mensaje.get_content_charset() or "utf-8")
                    mail.logout()
                    return html, None

        mail.logout()
        return None, "❌ No se encontró un correo reciente con ese asunto."

    except Exception as e:
        logging.exception("Error al buscar correo")
        return None, f"⚠️ Error al acceder al correo: {str(e)}"

def extraer_link_con_token(html):
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html)
    for link in links:
        if "nftoken=" in link:
            return link
    return None

# =====================
# Comandos del bot
# =====================

@bot.message_handler(commands=["code"])
def manejar_code(message):
    partes = message.text.split()
    if len(partes) != 2:
        bot.reply_to(message, "❌ Uso: /code tu_correo@dgplayk.com")
        return

    correo = partes[1].lower()
    html, error = buscar_ultimo_correo(correo, "Código de acceso")
    if error:
        bot.reply_to(message, error)
        return

    link = extraer_link_con_token(html)
    bot.reply_to(message, f"🔗 {link}" if link else "❌ No se encontró ningún enlace con nftoken=.")

@bot.message_handler(commands=["hogar"])
def manejar_hogar(message):
    partes = message.text.split()
    if len(partes) != 2:
        bot.reply_to(message, "❌ Uso: /hogar tu_correo@dgplayk.com")
        return

    correo = partes[1].lower()
    html, error = buscar_ultimo_correo(correo, "actualizar hogar")
    if error:
        bot.reply_to(message, error)
        return

    link = extraer_link_con_token(html)
    bot.reply_to(message, f"🏠 {link}" if link else "❌ No se encontró ningún enlace con nftoken=.")

@bot.message_handler(commands=["cuentas"])
def mostrar_correos(message):
    todos = []
    for lista in cuentas.values():
        for entrada in lista:
            correo = entrada.split("|")[0] if "|" in entrada else entrada
            todos.append(correo)
    texto = "📋 Correos registrados:\n" + "\n".join(todos) if todos else "⚠️ No hay correos registrados."
    bot.reply_to(message, texto)

# =====================
# Webhook
# =====================

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def recibir_update():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "", 200

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot Netflix activo vía Webhook", 200

# =====================
# Inicio
# =====================

if __name__ == "__main__":
    mantener_vivo()
    app.run(host="0.0.0.0", port=8080)