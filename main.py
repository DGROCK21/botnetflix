import os
import json
import logging
from flask import Flask, request
import imaplib
import email
from email.header import decode_header
import re
import requests
from bs4 import BeautifulSoup
import telebot
from telebot import types

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo (solo para validación de correos de usuario autorizados)
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. La validación de correo no funcionará.")
    cuentas = {} 
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json.")
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


# Inicializar Flask
app = Flask(__name__)

# Inicializar Telebot solo si el token está presente
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram inicializado.")
else:
    bot = None

# =================================================================
# FUNCIONES AUXILIARES (IMAP Y EXTRACCIÓN DE NETFLIX)
# =================================================================

def es_correo_autorizado(correo_usuario):
    """
    Verifica si el correo de usuario pertenece a una de las cuentas autorizadas en cuentas.json.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación.")
        return False
        
    for user_id, correos_list in cuentas.items():
        for entrada in correos_list:
            correo_en_lista = entrada.split("|")[0].lower()
            if correo_en_lista == correo_usuario.lower():
                return True
    return False


def buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_parte_clave, num_mensajes_revisar=50):
    """
    Busca el último correo que CONTIENE una parte del asunto clave.
    """
    if not usuario_imap or not contrasena_imap:
        return None, "❌ Error interno: Credenciales IMAP no configuradas."
    
    try:
        logging.info(f"Intentando conectar a IMAP para {usuario_imap}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario_imap, contrasena_imap) # <-- Aquí revisa la autenticación
        mail.select("inbox")
        logging.info("Conexión IMAP exitosa. Buscando correos.")
        
        _, mensajes = mail.search(None, "ALL") 
        mensajes = mensajes[0].split()

        mensajes_reversados = reversed(mensajes[-min(num_mensajes_revisar, len(mensajes)):])
        
        for num in mensajes_reversados:
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            try:
                # Decodificación segura del asunto
                asunto_parts = decode_header(mensaje["Subject"])
                asunto = "".join([
                    part.decode(encoding or "utf-8", errors='ignore') if isinstance(part, bytes) else part
                    for part, encoding in asunto_parts
                ])
            except Exception:
                asunto = mensaje.get("Subject", "Sin Asunto") 

            # Verificar si el asunto contiene la palabra clave
            if asunto_parte_clave.lower() in asunto.lower():
                logging.info(f"Asunto '{asunto_parte_clave}' encontrado en: {asunto}. Extrayendo HTML.")
                
                html_content = None
                
                if mensaje.is_multipart():
                    for parte in mensaje.walk():
                        ctype = parte.get_content_type()
                        # CORRECCIÓN: Línea de código completa y funcional
                        cdisp = str(parte.get('Content-Disposition')) 
                        
                        if ctype == 'text/html' and 'attachment' not in cdisp:
                            try:
                                html_content = parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8", errors='ignore')
                                break 
                            except Exception as e:
                                logging.warning(f"Error decodificando parte HTML: {e}")
                else:
                    try:
                        if mensaje.get_content_type() == 'text/html':
                            html_content = mensaje.get_payload(decode=True).decode(mensaje.get_content_charset() or "utf-8", errors='ignore')
                    except Exception as e:
                        logging.warning(f"Error decodificando mensaje no multipart: {e}")

                if html_content:
                    mail.logout()
                    return html_content, None
                else:
                    logging.warning(f"No se pudo extraer contenido HTML del correo: {asunto}")


        mail.logout()
        logging.info(f"No se encontró un correo reciente con el asunto '{asunto_parte_clave}'.")
        return None, f"❌ No se encontró un correo reciente de Netflix con la clave solicitada."

    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        logging.error(f"Error de IMAP al acceder al correo {usuario_imap}: {error_msg}. Verifica la contraseña de aplicación de Gmail.")
        return None, f"⚠️ Error de autenticación IMAP: {error_msg}. Asegúrate de usar la contraseña de aplicación de Gmail."
    except Exception as e:
        logging.exception(f"Error inesperado al buscar correo para {usuario_imap}")
        return None, f"⚠️ Error inesperado: {str(e)}"


def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """ Extrae el enlace relevante del HTML del correo de Netflix. """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    if es_hogar:
        # Busca el botón "Sí, la envié yo" para el primer paso de la confirmación de hogar
        boton_rojo = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE))
        if boton_rojo and 'href' in boton_rojo.attrs:
            return boton_rojo['href']
    
    # Busca enlaces con nftoken para el código de acceso temporal
    for a_tag in soup.find_all('a', href=True):
        if "nftoken=" in a_tag['href']:
            return a_tag['href']
            
    return None

def obtener_codigo_de_pagina(url_netflix):
    """ Visita la URL de Netflix y extrae el código de 4 dígitos de la página. """
    try:
        logging.info(f"Visitando URL de Netflix para obtener código: {url_netflix}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url_netflix, headers=headers, timeout=30) 
        response.raise_for_status() 

        html_pagina_codigo = response.text
        # Regex para buscar el código de 4 dígitos dentro del div de Netflix
        match = re.search(r'<div[^>]*class=["\']challenge-code["\'][^>]*>(\d{4})<\/div>', html_pagina_codigo) 
        if match:
            codigo = match.group(1)
            logging.info(f"Código encontrado: {codigo}")
            return codigo
        return None

    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al obtener el código de Netflix: {e}")
        return None

# =================================================================
# HANDLERS DEL BOT DE TELEGRAM
# =================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "¡Hola! Soy tu bot de Netflix. Usa /obtener_codigo <tu_correo> o /confirmar_hogar <tu_correo>.")

# Handler para el comando /obtener_codigo
@bot.message_handler(commands=['obtener_codigo'])
def handle_obtener_codigo(message):
    try:
        if len(message.text.split()) < 2:
            bot.reply_to(message, "Por favor, usa el formato: /obtener_codigo <tu_correo>")
            return
        
        # Usamos las credenciales globales (IMAP_USER, IMAP_PASS) para la prueba simple
        html_correo, error_msg = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Código de acceso temporal")
        
        if error_msg:
            bot.reply_to(message, error_msg)
            return
        
        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
        if link:
            codigo = obtener_codigo_de_pagina(link)
            if codigo:
                bot.reply_to(message, f"✅ Tu código de acceso es: {codigo}")
            else:
                bot.reply_to(message, "⚠️ El link del correo no contiene un código de acceso válido.")
        else:
            bot.reply_to(message, "⚠️ No se encontró un link con un token válido en el correo.")

    except Exception as e:
        logging.exception("Error en el handler de /obtener_codigo")
        bot.reply_to(message, f"❌ Ocurrió un error inesperado.")


@bot.message_handler(commands=['confirmar_hogar'])
def handle_confirmar_hogar(message):
    try:
        if len(message.text.split()) < 2:
            bot.reply_to(message, "Por favor, usa el formato: /confirmar_hogar <tu_correo>")
            return

        # Usamos las credenciales globales para la prueba simple
        html_correo, error_msg = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Actualiza tu hogar con un solo clic")

        if error_msg:
            bot.reply_to(message, error_msg)
            return
        
        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link_boton_rojo:
            # En este modo simplificado, solo se devuelve el link (la lógica de clic final es compleja)
            bot.reply_to(message, f"✅ Por favor, haz clic en el siguiente enlace para confirmar la actualización del hogar: {link_boton_rojo}")
        else:
            bot.reply_to(message, "❌ No se encontró un correo de Netflix para actualizar el hogar.")
            
    except Exception as e:
        logging.exception("Error en el handler de /confirmar_hogar")
        bot.reply_to(message, f"❌ Ocurrió un error inesperado.")

# =================================================================
# SERVIDOR WEBHOOK (CRÍTICO PARA RENDER)
# =================================================================

@app.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    # Recibe el mensaje de Telegram y lo procesa
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "!", 200
    return "Error de contenido", 403

@app.route('/')
def index():
    # Ruta de prueba para confirmar que el servidor Flask está activo
    return "Bot de Netflix (Solo) funcionando correctamente.", 200

if __name__ == '__main__':
    # La variable de entorno PORT es necesaria para Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
