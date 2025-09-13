import os
import json
import logging
import threading
from flask import Flask, render_template, request, redirect, url_for
import imaplib
import email
from email.header import decode_header
import re
import requests
from bs4 import BeautifulSoup
from imap_tools import MailBox, AND
import telebot
from telebot import types

# Configuración de Logging para un mejor seguimiento de errores
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas autorizadas desde archivo
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

# Obtener credenciales desde las variables de entorno de Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")

if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")

app = Flask(__name__)

# =====================
# FUNCIONES AUXILIARES
# =====================

def es_correo_autorizado(correo_usuario, plataforma_requerida, user_id=None):
    """
    Verifica si el correo de usuario está autorizado para una plataforma específica.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación.")
        return False
    
    if user_id and user_id in cuentas:
        for entrada in cuentas[user_id]:
            partes = entrada.split("|")
            correo_en_lista = partes[0].lower()
            etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
            
            if correo_en_lista == correo_usuario.lower() and etiqueta_plataforma == plataforma_requerida.lower():
                return True
    
    if user_id is None:
        for user_data in cuentas.values():
            for entrada in user_data:
                partes = entrada.split("|")
                correo_en_lista = partes[0].lower()
                etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
                
                if correo_en_lista == correo_usuario.lower() and etiqueta_plataforma == plataforma_requerida.lower():
                    return True
    
    return False

def buscar_ultimo_correo(asunto_clave):
    """
    Busca el último correo con un asunto específico, manejando la codificación.
    """
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select('inbox')
        
        search_criteria = f'(SUBJECT "{asunto_clave}")'.encode('utf-8')
        status, messages = imap.search(None, search_criteria)
        
        if not messages[0]:
            return None, f"❌ No se encontró ningún correo con el asunto: '{asunto_clave}'"
        
        mail_id = messages[0].split()[-1]
        status, data = imap.fetch(mail_id, '(RFC822)')
        
        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)
        
        html_content = ""
        for part in email_message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                charset = part.get_content_charset() or 'utf-8'
                html_content = part.get_payload(decode=True).decode(charset, errors='ignore')
                break
        
        imap.close()
        imap.logout()
        
        if html_content:
            return html_content, None
        else:
            return None, "❌ No se pudo encontrar la parte HTML del correo."
    except Exception as e:
        logging.error(f"Error en la conexión o búsqueda de correo: {str(e)}")
        return None, f"❌ Error en la conexión o búsqueda de correo: {str(e)}"

def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """Extrae el enlace de un botón específico del correo de Netflix."""
    soup = BeautifulSoup(html_content, 'html.parser')
    if es_hogar:
        link_tag = soup.find('a', href=lambda href: href and 'confirm-home-membership' in href)
    else:
        link_tag = soup.find('a', href=lambda href: href and 'code-request' in href)
    return link_tag['href'] if link_tag
