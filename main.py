import telebot
import os
import json
import imaplib
import email
import re
import logging
from email.header import decode_header
from keep_alive import mantener_vivo

# Cargar archivo de cuentas
with open("cuentas.json", "r") as file:
    cuentas = json.load(file)

# Token del bot desde variable de entorno
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN no está definido.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Obtener credenciales del correo basado en cuentas.json
def obtener_credenciales(correo):
    for user_id, correos in cuentas.items():
        for entrada in correos:
            if entrada.startswith(correo):
                partes = entrada.split("|")
                if len(partes) == 3:
                    return partes[1], partes[2]
    return None, None

# Buscar el último correo con un asunto específico
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

        for num in reversed(mensajes[-20:]):  # revisar últimos 20 mensajes
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])
