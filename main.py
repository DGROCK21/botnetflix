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
        with MailBox('imap.gmail.com').login(imap_user, imap_pass, 'INBOX') as mailbox:
            for msg in mailbox.fetch(AND(subject=asunto_universal), reverse=True):
                soup = BeautifulSoup(msg.html, 'html.parser')
                code_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
                if code_div:
                    codigo = code_div.text.strip()
                    if re.fullmatch(r'[A-Z0-9]{6,7}', codigo):
                        logging.info(f"✅ Código de Universal+ extraído: {codigo}")
                        return codigo, None
                    else:
                        logging.warning("❌ Se encontró un texto en la etiqueta correcta, pero no coincide con el formato de código (6 o 7 caracteres alfanuméricos).")
                        return None, "❌ No se pudo extraer el código. El formato no es válido."
                else:
                    logging.warning("❌ No se encontró la etiqueta div con el estilo del código.")
                    return None, "❌ No se pudo encontrar el código de activación. El formato del correo puede haber cambiado."
    except Exception as e:
        logging.error(f"❌ Error al conectar o buscar el correo de Universal+: {e}")
        return None, f"❌ Error al conectar o buscar el correo: {str(e)}"
    return None, "❌ No se encontró ningún correo de activación de Universal+."

# =====================
# RUTAS WEB (FLASK)
# =====================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/consultar_accion', methods=['POST'])
def consultar_accion_web():
    user_email_input = request.form.get('email', '').strip()
    action = request.form.get('action')

    if not user_email_input:
        logging.warning("WEB: Solicitud sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    # A partir de aquí, la lógica se ejecuta para cualquier plataforma
    if action == 'code':
        if not es_correo_autorizado(user_email_input, "netflix"):
            return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Netflix. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")
        
        # Lógica de Netflix code
        asunto_clave = "Código de acceso temporal de Netflix"
        logging.info(f"WEB: Solicitud de código para {user_email_input}. Buscando en {IMAP_USER} correo con asunto: '{asunto_clave}'")
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave)
        if error:
            return render_template('result.html', status="error", message=error)
        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
        if link:
            codigo_final = obtener_codigo_de_pagina(link)
            if codigo_final:
                logging.info(f"WEB: Código obtenido: {codigo_final}")
                return render_template('result.html', status="success", message=f"✅ Tu código de Netflix es: <strong>{codigo_final}</strong>.<br>Úsalo en tu TV o dispositivo.")
            else:
                logging.warning("WEB: Se encontró el enlace de código, pero no se pudo extraer el código de la página de Netflix.")
                return render_template('result.html', status="warning", message="No se pudo obtener el código activo para esta cuenta.")
        else:
            logging.warning("WEB: No se encontró enlace de código de Netflix en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

    elif action == 'hogar':
        if not es_correo_autorizado(user_email_input, "netflix"):
            return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Netflix. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")
        
        # Lógica de Netflix hogar
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix"
        logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando en {IMAP_USER} correo que contenga: '{asunto_parte_clave}'")
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave)
        if error:
            return render_template('result.html', status="error", message=error)
        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link_boton_rojo:
            enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link_boton_rojo)
            if enlace_final_confirmacion:
                mensaje_web = f"✅ Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace para confirmar la actualización:<br><br><strong><a href='{enlace_final_confirmacion}' target='_blank'>{enlace_final_confirmacion}</a></strong><br><br>⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                if bot and ADMIN_TELEGRAM_ID:
                    mensaje_telegram_admin = f"🚨 NOTIFICACIÓN DE HOGAR NETFLIX (WEB) 🚨\n\nEl usuario **{user_email_input}** ha solicitado actualizar el Hogar Netflix.\n\nEl enlace también se mostró en la web. Si el usuario no puede acceder, **HAZ CLIC INMEDIATAMENTE AQUÍ**:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                    try:
                        bot.send_message(ADMIN_TELEGRAM_ID, mensaje_telegram_admin, parse_mode='Markdown')
                        logging.info(f"WEB: Enlace de hogar final enviado al admin por Telegram (adicional) para {user_email_input}.")
                    except Exception as e:
                        logging.error(f"WEB: Error al enviar notificación ADICIONAL por Telegram: {e}")
                return render_template('result.html', status="success", message=mensaje_web)
            else:
                return render_template('result.html', status="warning", message="❌ No se pudo obtener el enlace de confirmación final. Contacta al administrador si persiste.")
        else:
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

    elif action == 'universal':
        if not es_correo_autorizado(user_email_input, "universal"):
            return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Universal. Por favor, usa un correo registrado.")
        
        # Lógica de Universal
        codigo_universal, error = navegar_y_extraer_universal(IMAP_USER, IMAP_PASS)
        if error:
            return render_template('result.html', status="error", message=error)
        if codigo_universal:
            return render_template('result.html', status="success", message=f"✅ Tu código de Universal+ es: <strong>{codigo_universal}</strong>.<br>Úsalo en la página de activación.")
        else:
            return render_template('result.html', status="warning", message="❌ No se pudo obtener un código de Universal+ reciente. Asegúrate de haberlo solicitado y que el correo haya llegado.")

    else:
        logging.warning(f"WEB: Acción no válida recibida: {action}")
        return render_template('result.html', status="error", message="❌ Acción no válida. Por favor, selecciona una de las opciones.")

# =====================
# COMANDOS DE TELEGRAM
# =====================

if bot:
    @app.route(f"/{BOT_TOKEN}", methods=["POST"])
    def recibir_update():
        if request.headers.get('content-type') == 'application/json':
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
            return
