import telebot
import os
import json
import imaplib
import email
import re
import logging
import time
from email.header import decode_header
from flask import Flask, request
from keep_alive import mantener_vivo
import requests
from bs4 import BeautifulSoup

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo (ahora solo para los correos de Netflix asociados a user_id, no las credenciales IMAP)
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. Asegúrate de que el archivo existe.")
    cuentas = {}
    exit(1)
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json.")
    cuentas = {}
    exit(1)

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Ahora obtenemos las credenciales IMAP desde las variables de entorno
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido. El bot no puede iniciarse.")
    exit(1)
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos en las variables de entorno. El bot no puede leer correos.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# =====================
# Funciones auxiliares
# =====================

# La función obtener_credenciales ya no necesita buscar en cuentas.json para IMAP
# Simplemente devolverá las credenciales de las variables de entorno
def obtener_credenciales_imap():
    """Retorna las credenciales IMAP desde las variables de entorno."""
    return IMAP_USER, IMAP_PASS

def buscar_ultimo_correo(correo_a_buscar, asunto_clave, num_mensajes_revisar=50):
    """
    Busca el último correo con un asunto clave dado para un correo específico.
    Retorna el HTML del correo y None si tiene éxito, o None y un mensaje de error.
    """
    # Ahora obtenemos las credenciales IMAP directamente de las variables de entorno
    usuario_imap, contrasena_imap = obtener_credenciales_imap()
    
    if not usuario_imap or not contrasena_imap:
        return None, "❌ Error interno: Credenciales IMAP no configuradas en las variables de entorno del bot."

    try:
        logging.info(f"Intentando conectar a IMAP para {usuario_imap}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario_imap, contrasena_imap)
        mail.select("inbox")
        logging.info("Conexión IMAP exitosa. Buscando correos.")
        
        # Obtener todos los mensajes y revisar los más recientes
        _, mensajes = mail.search(None, "ALL") 
        mensajes = mensajes[0].split()

        # Revisar un número limitado de mensajes recientes para eficiencia
        mensajes_reversados = reversed(mensajes[-min(num_mensajes_revisar, len(mensajes)):])
        
        for num in mensajes_reversados:
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            try:
                # Decodificar el asunto
                asunto_parts = decode_header(mensaje["Subject"])
                asunto = ""
                for part, encoding in asunto_parts:
                    if isinstance(part, bytes):
                        asunto += part.decode(encoding or "utf-8", errors='ignore')
                    else:
                        asunto += part
            except Exception as e:
                asunto = mensaje.get("Subject", "Sin Asunto") # Fallback si hay error
                logging.warning(f"No se pudo decodificar el asunto: {e}. Usando asunto crudo: {asunto}")

            if asunto_clave.lower() in asunto.lower():
                logging.info(f"Asunto '{asunto_clave}' encontrado en '{asunto}'. Extrayendo HTML.")
                
                html_content = None
                if mensaje.is_multipart():
                    for parte in mensaje.walk():
                        ctype = parte.get_content_type()
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
                    logging.info("HTML del correo extraído con éxito.")
                    mail.logout()
                    return html_content, None
                else:
                    logging.warning(f"No se pudo extraer contenido HTML del correo con asunto: {asunto}")


        mail.logout()
        logging.info(f"No se encontró un correo reciente con el asunto '{asunto_clave}' para {usuario_imap}.")
        return None, f"❌ No se encontró un correo reciente con el asunto '{asunto_clave}'. Verifica el correo y el asunto."

    except imaplib.IMAP4.error as e:
        logging.error(f"Error de IMAP al acceder al correo {usuario_imap}: {e}. Verifica la contraseña de aplicación de Gmail.")
        return None, f"⚠️ Error de autenticación o IMAP: {str(e)}. Verifica tus credenciales y configuración de Gmail (especialmente la contraseña de aplicación)."
    except Exception as e:
        logging.exception(f"Error inesperado al buscar correo para {usuario_imap}")
        return None, f"⚠️ Error inesperado al acceder al correo: {str(e)}"

def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """
    Extrae el enlace relevante del HTML del correo.
    Para "hogar", busca el botón de confirmación.
    Para "código", busca enlaces con 'nftoken='.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    if es_hogar:
        boton = soup.find('a', style=lambda value: value and 'background-color:#e50914' in value)
        if not boton:
             boton = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE))
        
        if boton and 'href' in boton.attrs:
            link = boton['href']
            logging.info(f"Enlace de confirmación de Hogar encontrado: {link}")
            return link
    
    for a_tag in soup.find_all('a', href=True):
        link = a_tag['href']
        if "nftoken=" in link:
            logging.info(f"Enlace con nftoken encontrado: {link}")
            return link
            
    logging.info("No se encontró ningún enlace relevante en el HTML.")
    return None

def obtener_codigo_de_pagina(url_netflix):
    """
    Visita la URL de Netflix y extrae el código de acceso de la página resultante.
    """
    try:
        logging.info(f"Visitando URL de Netflix para obtener código: {url_netflix}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url_netflix, headers=headers, allow_redirects=True, timeout=30) 
        response.raise_for_status() 

        html_pagina_codigo = response.text
        logging.info("Página de Netflix para código obtenida. Buscando el código...")
        
        # --- AJUSTE AQUÍ: AHORA BUSCAMOS 4 DÍGITOS EN LUGAR DE 6 ---
        # Si la estructura HTML cambia, aún podrías necesitar ajustar el contexto (e.g., span, div, strong)
        match = re.search(r'\b(\d{4})\b', html_pagina_codigo) # CAMBIADO DE \d{6} a \d{4}

        if match:
            codigo = match.group(1)
            logging.info(f"Código encontrado: {codigo}")
            return codigo
            
        logging.warning("No se encontró el patrón de código en la página de Netflix con la regex actual.")
        return None

    except requests.exceptions.Timeout:
        logging.error(f"Tiempo de espera agotado al visitar {url_netflix}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al intentar obtener el código de Netflix de {url_netflix}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Error inesperado al obtener el código de la página: {e}")
        return None

def confirmar_hogar_netflix(url_confirmacion):
    """
    Visita la URL de confirmación de hogar para activarlo.
    """
    try:
        logging.info(f"Visitando URL para confirmar Hogar: {url_confirmacion}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/555.55 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.netflix.com/' 
        }
        response = requests.get(url_confirmacion, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status() 

        logging.info(f"Solicitud de confirmación de Hogar exitosa para {url_confirmacion}. Estado: {response.status_code}")
        
        if "hogar actualizado" in response.text.lower() or "confirmado" in response.text.lower() or "success" in response.text.lower():
            logging.info("Mensaje de confirmación de hogar encontrado en la respuesta.")
            return True
        else:
            logging.warning("No se encontró un mensaje de confirmación explícito en la respuesta del hogar, pero la solicitud HTTP fue exitosa (200 OK).")
            return True
            
    except requests.exceptions.Timeout:
        logging.error(f"Tiempo de espera agotado al visitar {url_confirmacion}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al intentar confirmar Hogar de Netflix de {url_confirmacion}: {e}")
        return False
    except Exception as e:
        logging.exception(f"Error inesperado al confirmar Hogar: {e}")
        return False

# =====================
# Comandos del bot
# =====================

@bot.message_handler(commands=["code"])
def manejar_code(message):
    bot.reply_to(message, "Buscando correo de código, por favor espera unos momentos...")
    partes = message.text.split()
    if len(partes) != 2:
        bot.reply_to(message, "❌ Uso: /code tu_correo_netflix@dgplayk.com")
        return

    correo_busqueda = partes[1].lower()
    # Asunto clave para código temporal de Netflix
    html_correo, error = buscar_ultimo_correo(correo_busqueda, "Código de acceso temporal") 

    if error:
        bot.reply_to(message, error)
        return

    link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False) 
    if link:
        codigo_final = obtener_codigo_de_pagina(link)
        if codigo_final:
            bot.reply_to(message, f"✅ Tu código de Netflix es: `{codigo_final}`")
        else:
            bot.reply_to(message, "❌ Se encontró el enlace de código, pero no se pudo extraer el código de la página de Netflix. Es posible que el formato de la página haya cambiado o que la regex necesite ajuste (ej: contexto HTML).")
    else:
        bot.reply_to(message, "❌ No se encontró ningún enlace de código de Netflix en el correo. Verifica que el correo haya llegado y contenga el botón 'Obtener código'.")

@bot.message_handler(commands=["hogar"])
def manejar_hogar(message):
    bot.reply_to(message, "Buscando correo de hogar, por favor espera unos momentos...")
    partes = message.text.split()
    if len(partes) != 2:
        bot.reply_to(message, "❌ Uso: /hogar tu_correo_netflix@dgplayk.com")
        return

    correo_busqueda = partes[1].lower()
    # Asunto clave para actualización de hogar de Netflix
    html_correo, error = buscar_ultimo_correo(correo_busqueda, "actualizar tu Hogar") 

    if error:
        bot.reply_to(message, error)
        return

    link_confirmacion = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
    if link_confirmacion:
        if confirmar_hogar_netflix(link_confirmacion):
            bot.reply_to(message, "🏠 Solicitud de hogar enviada/confirmada exitosamente. Revisa tu Netflix.")
        else:
            bot.reply_to(message, "❌ Se encontró el enlace de hogar, pero hubo un error al confirmarlo. Revisa los logs de Render.")
    else:
        bot.reply_to(message, "❌ No se encontró ningún enlace de confirmación de hogar en el correo. Verifica que el correo haya llegado y contenga el botón 'Sí, la envié yo'.")

@bot.message_handler(commands=["cuentas"])
def mostrar_correos(message):
    todos = []
    user_id = str(message.from_user.id)
    if user_id in cuentas and isinstance(cuentas[user_id], list):
        for entrada in cuentas[user_id]:
            correo = entrada.split("|")[0] if "|" in entrada else entrada
            todos.append(correo)

    texto = "📋 Correos registrados para tu ID:\n" + "\n".join(sorted(list(set(todos)))) if todos else "⚠️ No hay correos registrados para tu ID."
    bot.reply_to(message, texto)

# =====================
# Webhook
# =====================

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def recibir_update():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "", 200
    else:
        logging.warning("Encabezado Content-Type incorrecto en la solicitud del webhook.")
        return "Bad Request", 400

@app.route("/", methods=["GET"])
def index():
    return "✅ Bot Netflix activo vía Webhook", 200

# =====================
# Inicio
# =====================

if __name__ == "__main__":
    mantener_vivo()
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Iniciando Flask app en el puerto {port}")
    app.run(host="0.0.0.0", port=port)