import os
import json
import logging
from flask import Flask, render_template, request
from keep_alive import mantener_vivo
import telebot
import imaplib
import email
from email.header import decode_header
import re
import requests
from bs4 import BeautifulSoup
from imap_tools import MailBox, AND

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. La validación de correo no funcionará.")
    cuentas = {}
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json. La validación de correo podría ser inconsistente.")
    cuentas = {}

# Obtener credenciales IMAP y el token del bot desde las variables de entorno de Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido. La funcionalidad de Telegram NO ESTARÁ DISPONIBLE.")
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")
if not ADMIN_TELEGRAM_ID:
    logging.warning("⚠️ ADMIN_TELEGRAM_ID no está definido. No se enviarán notificaciones.")

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

# =====================
# FUNCIONES AUXILIARES (ahora integradas)
# =====================

def es_correo_autorizado(correo_usuario, plataforma_requerida):
    """
    Verifica si el correo de usuario pertenece a una cuenta autorizada y a la plataforma correcta.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados.")
        return False
    for correos_list in cuentas.values():
        for entrada in correos_list:
            partes = entrada.split("|")
            correo_en_lista = partes[0].lower()
            etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
            if correo_en_lista == correo_usuario.lower() and etiqueta_plataforma == plataforma_requerida.lower():
                return True
    return False

def buscar_ultimo_correo(imap_user, imap_pass, asunto_clave):
    """
    Busca el último correo con un asunto específico.
    """
    try:
        mailbox = imaplib.IMAP4_SSL('imap.gmail.com')
        mailbox.login(imap_user, imap_pass)
        mailbox.select('inbox')
        status, messages = mailbox.search(None, f'SUBJECT "{asunto_clave}"')
        if not messages[0]:
            return None, f"❌ No se encontró ningún correo con el asunto: '{asunto_clave}'"
        mail_id = messages[0].split()[-1]
        status, data = mailbox.fetch(mail_id, '(RFC822)')
        email_message = email.message_from_bytes(data[0][1])
        html_content = ""
        for part in email_message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                html_content = part.get_payload(decode=True).decode()
                break
        mailbox.close()
        mailbox.logout()
        return html_content, None if html_content else "❌ No se pudo encontrar la parte HTML del correo."
    except Exception as e:
        return None, f"❌ Error en la conexión o búsqueda de correo: {str(e)}"

def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """
    Extrae el enlace de un botón específico del correo de Netflix.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    if es_hogar:
        link_tag = soup.find('a', href=lambda href: href and 'confirm-home-membership' in href)
    else:
        link_tag = soup.find('a', href=lambda href: href and 'code-request' in href)
    return link_tag['href'] if link_tag else None

def obtener_codigo_de_pagina(url):
    """
    Visita el enlace del correo de Netflix y extrae el código final de la página.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        codigo_tag = soup.find('div', class_='code')
        return codigo_tag.text.strip() if codigo_tag else None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al acceder a la página de Netflix para obtener el código: {e}")
    except Exception as e:
        logging.error(f"Error inesperado al procesar la página de Netflix: {e}")
    return None

def obtener_enlace_confirmacion_final_hogar(url_boton_rojo):
    """
    Visita el enlace del correo de hogar y extrae el enlace del botón de confirmación final.
    """
    try:
        response = requests.get(url_boton_rojo, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        link_tag = soup.find('a', href=lambda href: href and 'confirm-home-update' in href)
        return link_tag['href'] if link_tag else None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al acceder a la página de Netflix para obtener el enlace de confirmación: {e}")
    except Exception as e:
        logging.error(f"Error inesperado al procesar la página de Netflix: {e}")
    return None

def navegar_y_extraer_universal(imap_user, imap_pass):
    """
    Busca el correo de Universal+ y extrae el código de activación de manera precisa.
    """
    asunto_universal = "Código de activación Universal+"
    logging.info(f"Buscando el correo de Universal+ con el asunto: '{asunto_universal}'")
    try:
