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

# Configuración de Logging
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
    return link_tag['href'] if link_tag else None

def obtener_codigo_de_pagina(url):
    """Visita el enlace del correo de Netflix y extrae el código final."""
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
    """Visita el enlace del correo de hogar y extrae el enlace de confirmación final."""
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

def navegar_y_extraer_universal():
    """Busca el correo de Universal+ y extrae el código de activación."""
    asunto_universal = "Código de activación Universal+"
    logging.info(f"Buscando el correo de Universal+ con el asunto: '{asunto_universal}'")
    try:
        with MailBox('imap.gmail.com').login(IMAP_USER, IMAP_PASS, 'INBOX') as mailbox:
            for msg in mailbox.fetch(AND(subject=asunto_universal), reverse=True, limit=1):
                soup = BeautifulSoup(msg.html, 'html.parser')
                code_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
                if code_div:
                    codigo = code_div.text.strip()
                    if re.fullmatch(r'[A-Z0-9]{6,7}', codigo):
                        return codigo, None
                    else:
                        return None, "❌ Se encontró un texto en la etiqueta correcta, pero no coincide con el formato de código."
                else:
                    return None, "❌ No se pudo encontrar el código de activación. El formato del correo puede haber cambiado."
        return None, f"❌ No se encontró ningún correo con el asunto: '{asunto_universal}'"
    except Exception as e:
        logging.error(f"Error al conectar o buscar el correo de Universal+: {e}")
        return None, f"❌ Error en la conexión o búsqueda de correo: {str(e)}"

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
    platform = request.form.get('platform')

    if not user_email_input or not platform:
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    if not es_correo_autorizado(user_email_input, platform):
        return render_template('result.html', status="error", message=f"⚠️ Correo no autorizado para la plataforma {platform}.")

    if platform == 'netflix':
        if action == 'code':
            asunto_clave = "Código de acceso temporal de Netflix"
            html_correo, error = buscar_ultimo_correo(asunto_clave)
            if error:
                return render_template('result.html', status="error", message=error)
            link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
            if link:
                codigo_final = obtener_codigo_de_pagina(link)
                if codigo_final:
                    return render_template('result.html', status="success", message=f"✅ Tu código de Netflix es: <strong>{codigo_final}</strong>.<br>Úsalo en tu TV o dispositivo.")
                else:
                    return render_template('result.html', status="warning", message="No se pudo obtener el código activo para esta cuenta.")
            else:
                return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

        elif action == 'hogar':
            asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix"
            html_correo, error = buscar_ultimo_correo(asunto_parte_clave)
            if error:
                return render_template('result.html', status="error", message=error)
            link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
            if link:
                enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link)
                if enlace_final_confirmacion:
                    mensaje_web = f"✅ Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace para confirmar la actualización:<br><br><strong><a href='{enlace_final_confirmacion}' target='_blank'>{enlace_final_confirmacion}</a></strong><br><br>⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                    return render_template('result.html', status="success", message=mensaje_web)
                else:
                    return render_template('result.html', status="warning", message="❌ No se pudo obtener el enlace de confirmación final. Contacta al administrador si persiste.")
            else:
                return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

    elif platform == 'universal':
        codigo_universal, error = navegar_y_extraer_universal()
        if error:
            return render_template('result.html', status="error", message=error)
        if codigo_universal:
            return render_template('result.html', status="success", message=f"✅ Tu código de Universal+ es: <strong>{codigo_universal}</strong>.<br>Úsalo en la página de activación.")
        else:
            return render_template('result.html', status="warning", message="❌ No se pudo obtener un código de Universal+ reciente.")
    
    else:
        return render_template('result.html', status="error", message="❌ Plataforma no válida. Por favor, selecciona una de las opciones.")

# =====================
# FUNCIONALIDAD DEL BOT DE TELEGRAM
# =====================

if os.getenv("BOT_TOKEN"):
    bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))

    def mantener_vivo_thread():
        def run():
            app_keep_alive = Flask(__name__)
            @app_keep_alive.route('/')
            def home():
                return "Bot y Web activos", 200
            
            app_keep_alive.run(host='0.0.0.0', port=8080, use_reloader=False)

        t = threading.Thread(target=run)
        t.start()

    @app.route(f"/{os.getenv('BOT_TOKEN')}", methods=['POST'])
    def webhook():
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        else:
            logging.warning("Webhook de Telegram llamado con tipo de contenido no válido.")
            return '', 403

    @bot.message_handler(commands=["start", "help"])
    def bienvenida_telegram(message):
        keyboard = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        btn_netflix = types.KeyboardButton('/netflix')
        btn_universal = types.KeyboardButton('/universal')
        keyboard.add(btn_netflix, btn_universal)
        
        texto_bienvenida = "Hola! Soy el bot de DGPLAY. Puedes usar los siguientes comandos:\n\n" \
                          "➡️ `/netflix` - Para obtener el código o actualizar hogar de Netflix.\n" \
                          "➡️ `/universal` - Para obtener el código de Universal+."
        bot.reply_to(message, texto_bienvenida, reply_markup=keyboard)

    @bot.message_handler(commands=["netflix"])
    def manejar_menu_netflix(message):
        texto_menu = "Selecciona una opción de Netflix:\n\n" \
                     "➡️ `/code` - Obtener código de acceso temporal.\n" \
                     "➡️ `/hogar` - Obtener enlace de confirmación de hogar."
        bot.reply_to(message, texto_menu)

    @bot.message_handler(commands=["code"])
    def manejar_codigo_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada. Contacta al administrador.")
            return
        
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: `/code tu_correo_netflix@dgplayk.com`")
            return
            
        correo_busqueda = partes[1].lower()
        user_id = str(message.from_user.id)
        
        if not es_correo_autorizado(correo_busqueda, "netflix", user_id):
            bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
            return
        
        bot.reply_to(message, f"Buscando el código para {correo_busqueda}, por favor espera un momento...")
        asunto_clave = "Código de acceso temporal de Netflix"
        html_correo, error = buscar_ultimo_correo(asunto_clave)
        
        if error:
            bot.reply_to(message, error)
            return
            
        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
        if link:
            codigo_final = obtener_codigo_de_pagina(link)
            if codigo_final:
                bot.reply_to(message, f"✅ Tu código de Netflix es: `{codigo_final}`")
            else:
                bot.reply_to(message, "❌ No se pudo obtener el código activo para esta cuenta.")
        else:
            bot.reply_to(message, "❌ No se encontró ninguna solicitud pendiente para esta cuenta.")

    @bot.message_handler(commands=["hogar"])
    def manejar_hogar_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada. Contacta al administrador.")
            return
        
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: `/hogar tu_correo_netflix@dgplayk.com`")
            return
        
        correo_busqueda = partes[1].lower()
        user_id = str(message.from_user.id)
        
        if not es_correo_autorizado(correo_busqueda, "netflix", user_id):
            bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
            return

        bot.reply_to(message, f"Buscando correo de hogar para {correo_busqueda}, por favor espera un momento...")
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix"
        html_correo, error = buscar_ultimo_correo(asunto_parte_clave)

        if error:
            bot.reply_to(message, error)
            return
            
        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link:
            enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link)
            if enlace_final_confirmacion:
                mensaje_telegram_usuario = f"✅ Tu solicitud de hogar ha sido procesada. **HAZ CLIC INMEDIATAMENTE** en el siguiente enlace:\n\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                bot.reply_to(message, mensaje_telegram_usuario, parse_mode='Markdown')
            else:
                bot.reply_to(message, "❌ No se pudo obtener el enlace de confirmación final. El formato de la página puede haber cambiado.")
        else:
            bot.reply_to(message, "❌ No se encontró ninguna solicitud pendiente para esta cuenta.")

    @bot.message_handler(commands=["universal"])
    def manejar_universal_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada. Contacta al administrador.")
            return
        
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: `/universal tu_correo_universal@dgplayk.com`")
            return
        
        correo_busqueda = partes[1].lower()
        user_id = str(message.from_user.id)
        
        if not es_correo_autorizado(correo_busqueda, "universal", user_id):
            bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
            return

        bot.reply_to(message, "Buscando el código de Universal+, por favor espera un momento...")
        codigo_universal, error = navegar_y_extraer_universal()
        
        if error:
            bot.reply_to(message, error)
            return
            
        if codigo_universal:
            bot.reply_to(message, f"✅ Tu código de Universal+ es: `{codigo_universal}`")
        else:
            bot.reply_to(message, "❌ No se pudo obtener un código de Universal+ reciente.")

    @bot.message_handler(commands=["cuentas"])
    def mostrar_correos_telegram(message):
        todos = []
        user_id = str(message.from_user.id)
        if user_id in cuentas and isinstance(cuentas[user_id], list):
            for entrada in cuentas[user_id]:
                correo = entrada.split("|")[0] if "|" in entrada else entrada
                todos.append(correo)

        texto = "📋 Correos registrados para tu ID:\n" + "\n".join(sorted(list(set(todos)))) if todos else "⚠️ No hay correos registrados para tu ID."
        bot.reply_to(message, texto)

    # Lógica para mantener el bot activo
    def mantener_vivo_web_thread():
        def run():
            app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080), use_reloader=False)

        thread = threading.Thread(target=run)
        thread.start()
    
    mantener_vivo_web_thread()
    bot.set_webhook(url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{os.getenv('BOT_TOKEN')}")
    logging.info("Webhook de Telegram configurado exitosamente.")
