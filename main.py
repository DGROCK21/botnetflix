import telebot
import json
import os
import base64
import time
import requests
import re
from bs4 import BeautifulSoup
from email.header import decode_header

# Cargar configuración
with open("cuentas.json", "r") as file:
    cuentas = json.load(file)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN no está definido como variable de entorno.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

def get_token(usuario):
    datos = cuentas.get(usuario.lower())
    if not datos:
        return None
    return datos["token"]

def obtener_html(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get("https://api.mail.tm/messages", headers=headers)
    if resp.status_code != 200:
        return None

    mensajes = resp.json().get("hydra:member", [])
    if not mensajes:
        return None

    for msg in mensajes:
        id_mensaje = msg["id"]
        detalle = requests.get(f"https://api.mail.tm/messages/{id_mensaje}", headers=headers)
        if detalle.status_code == 200:
            contenido = detalle.json()
            if contenido.get("seen") == True:
                continue
            htmls = contenido.get("html", [])
            if htmls:
                return htmls[0]
    return None

def extraer_link(html):
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        if "nftoken=" in link["href"]:
            return link["href"]
    return None

@bot.message_handler(commands=["code", "hogar"])
def manejar_comando(message):
    partes = message.text.split()
    if len(partes) != 2:
        bot.reply_to(message, "❌ Uso incorrecto. Debes enviar: /code tu_correo")
        return

    correo = partes[1].lower()
    token = get_token(correo)
    if not token:
        bot.reply_to(message, "❌ Ese correo no está registrado en el sistema.")
        return

    html = obtener_html(token)
    if not html:
        bot.reply_to(message, "📭 No se encontró un correo reciente sin leer.")
        return

    link = extraer_link(html)
    if link:
        bot.reply_to(message, f"🔗 {link}")
    else:
        bot.reply_to(message, "❌ No se encontró ningún enlace con nftoken= en el correo.")

print("🤖 Bot iniciado...")
bot.polling()
