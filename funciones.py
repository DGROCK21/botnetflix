import imaplib
import email
from email.header import decode_header
import re
import json
import logging
from bs4 import BeautifulSoup 
import requests 

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_parte_clave, num_mensajes_revisar=50):
    """
    Busca el último correo que CONTIENE una parte del asunto clave para la cuenta IMAP especificada.
    Retorna el HTML del correo y None si tiene éxito, o None y un mensaje de error.
    """
    if not usuario_imap or not contrasena_imap:
        return None, "❌ Error interno: Credenciales IMAP no configuradas."
    
    try:
        logging.info(f"Intentando conectar a IMAP para {usuario_imap}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario_imap, contrasena_imap)
        mail.select("inbox")
        logging.info("Conexión IMAP exitosa. Buscando correos.")
        
        _, mensajes = mail.search(None, "ALL") 
        mensajes = mensajes[0].split()

        # Revisar un número limitado de mensajes recientes para eficiencia
        mensajes_reversados = reversed(mensajes[-min(num_mensajes_revisar, len(mensajes)):])
        
        for num in mensajes_reversados:
            _, data = mail.fetch(num, '(RFC822)')
            raw_email = data[0][1].decode('utf-8', 'ignore')
            msg = email.message_from_string(raw_email)
            
            asunto_decodificado, encoding = decode_header(msg['Subject'])[0]
            if isinstance(asunto_decodificado, bytes):
                asunto_decodificado = asunto_decodificado.decode(encoding if encoding else 'utf-8')

            if asunto_parte_clave in asunto_decodificado:
                logging.info(f"Correo encontrado con el asunto: '{asunto_decodificado}'")
                
                # Extraer el contenido HTML del correo
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get_content_disposition())
                        if content_type == 'text/html' and 'attachment' not in content_disposition:
                            html_content = part.get_payload(decode=True).decode('utf-8', 'ignore')
                            return html_content, None
                else:
                    html_content = msg.get_payload(decode=True).decode('utf-8', 'ignore')
                    return html_content, None

        logging.warning(f"No se encontró ningún correo con el asunto '{asunto_parte_clave}' en los últimos {num_mensajes_revisar} correos.")
        return None, "⚠️ No se encontró ningún correo reciente con la solicitud."

    except imaplib.IMAP4.error as e:
        logging.error(f"Error de IMAP: {e}")
        return None, f"❌ Error de conexión al correo: {e}"
    except Exception as e:
        logging.exception(f"Error inesperado al buscar correo: {e}")
        return None, "❌ Error inesperado al buscar en el correo. Contacta al administrador."

# --- Funciones para Netflix ---

def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """
    Extrae el primer enlace de un botón con texto específico para tokens o confirmación de hogar.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    link = None
    if es_hogar:
        # Para Hogar Netflix, buscamos el enlace del botón 'Sí, la envié yo'
        boton = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE))
        if boton:
            link = boton.get('href')
    else:
        # Para códigos, buscamos el enlace que dice "Ingresa el código"
        boton = soup.find('a', string=re.compile(r'Ingresa el código', re.IGNORECASE))
        if boton:
            link = boton.get('href')

    if link:
        logging.info(f"Enlace extraído con éxito: {link}")
        return link
    else:
        logging.warning("No se encontró el enlace del botón en el correo.")
        return None

def obtener_enlace_confirmacion_final_hogar(url_boton_rojo):
    """
    Visita la página del botón rojo de Netflix y extrae el enlace del botón de confirmación final.
    """
    try:
        logging.info(f"Visitando URL del botón rojo: {url_boton_rojo}")
        # Usamos una sesión para seguir los redirects si los hay
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url_boton_rojo, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status() # Lanza un error para códigos de estado HTTP malos

        soup_pagina_intermedia = BeautifulSoup(response.text, 'html.parser')
        
        # Buscamos el enlace del botón negro con el texto "Confirmar" o similar
        link_boton_negro = soup_pagina_intermedia.find('a', href=True, string=re.compile(r'Confirmar|Actualizar hogar', re.IGNORECASE))
        
        if link_boton_negro:
            enlace_final = link_boton_negro.get('href')
            logging.info(f"Enlace de confirmación final encontrado: {enlace_final}")
            return enlace_final
        else:
            logging.warning("No se encontró el enlace del botón de confirmación final en la página intermedia.")
            return None

    except requests.exceptions.Timeout:
        logging.error(f"Tiempo de espera agotado al visitar {url_boton_rojo}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al intentar obtener el enlace de confirmación: {e}")
        return None
    except Exception as e:
        logging.exception(f"Error inesperado al obtener el enlace final de la página: {e}")
        return None


def obtener_codigo_de_pagina(url_netflix):
    """
    Visita la página de Netflix y extrae el código de 4 dígitos.
    """
    try:
        logging.info(f"Visitando URL para obtener código: {url_netflix}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url_netflix, headers=headers, allow_redirects=True, timeout=30) 
        response.raise_for_status() 

        html_pagina_codigo = response.text
        logging.info("Página de Netflix para código obtenida. Buscando el código...")
        
        # Este regex busca un div con la clase 'challenge-code' y extrae el número de 4 dígitos
        match = re.search(r'<div[^>]*class=[\"\\']challenge-code[\"\\'][^>]*>(\d{4})<\/div>', html_pagina_codigo) 

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

import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from keep_alive import mantener_vivo
# Importar funciones necesarias desde funciones.py
# Se ha corregido la forma de importar las funciones
from funciones import buscar_ultimo_correo, extraer_link_con_token_o_confirmacion, obtener_codigo_de_pagina, obtener_enlace_confirmacion_final_hogar, navegar_y_extraer_universal
import telebot # Importamos telebot para la funcionalidad del bot

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo (solo para validación de correos de usuario autorizados)
# Este archivo debe estar en la misma carpeta que main.py
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. La validación de correo no funcionará.")
    cuentas = {} # Inicializa como diccionario vacío para evitar errores posteriores
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json. La validación de correo podría ser inconsistente.")
    cuentas = {}

# Obtener credenciales IMAP y el token del bot desde las variables de entorno de Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID") # Asegúrate de definir esta variable en Render con tu ID de Telegram

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido en las variables de entorno de Render. La funcionalidad de Telegram NO ESTARÁ DISPONIBLE.")
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos en las variables de entorno de Render. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")
    # Si estas no están, el bot no podrá conectarse a Gmail, lo que es crítico.
if not ADMIN_TELEGRAM_ID:
    logging.warning("⚠️ ADMIN_TELEGRAM_ID no está definido. No se enviarán notificaciones al administrador.")


# Inicializar Flask
app = Flask(__name__)

# Inicializar Telebot solo si el token está presente
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram inicializado.")
else:
    bot = None # Establecemos bot a None para evitar errores si no hay token

# =====================
# Funciones auxiliares para la web y el bot de Telegram
# =====================

def es_correo_autorizado(correo_usuario, plataforma_requerida):
    """
    Verifica si el correo de usuario pertenece a una de las cuentas autorizadas y a la plataforma correcta.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados.")
        return False

    # Itera sobre los valores del diccionario (las listas de correos)
    for correos_list in cuentas.values():
        for entrada in correos_list:
            partes = entrada.split("|")
            correo_en_lista = partes[0].lower()
            etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
            
            # Compara el correo y la etiqueta de la plataforma
            if correo_en_lista == correo_usuario.lower() and etiqueta_plataforma == plataforma_requerida.lower():
                return True
    return False

# =====================
# Rutas de la aplicación web (Flask)
# =====================

@app.route('/')
def home():
    """Renderiza la página principal con el formulario."""
    return render_template('index.html')

@app.route('/consultar_accion', methods=['POST'])
def consultar_accion_web():
    user_email_input = request.form.get('email', '').strip()
    action = request.form.get('action') # Esto viene del atributo 'name' y 'value' de los botones submit

    if not user_email_input:
        logging.warning("WEB: Solicitud sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    # Usamos la nueva función para verificar el correo y la plataforma
    if not es_correo_autorizado(user_email_input, "netflix"):
        logging.warning(f"WEB: Intento de correo no autorizado para Netflix: {user_email_input}")
        return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Netflix. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")

    if not IMAP_USER or not IMAP_PASS:
        logging.error("WEB: E-MAIL_USER o EMAIL_PASS no definidos. La funcionalidad de lectura de correos no es válida.")
        return render_template('result.html', status="error", message="❌ Error interno del servidor: La configuración de lectura de correos no es válida. Contacta al administrador del servicio.")

    # Lógica para obtener el código o confirmar el hogar
    if action == 'code':
        asunto_clave = "Código de acceso temporal de Netflix" # Asunto para códigos
        logging.info(f"WEB: Solicitud de código para {user_email_input}. Buscando en {IMAP_USER} correo con asunto: '{asunto_clave}'")
        
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para código: {error}")
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
        # ASUNTO FLEXIBLE Y ACTUALIZADO: Buscamos una parte constante del asunto para "Actualizar Hogar"
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix" 
        logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando en {IMAP_USER} correo que contenga: '{asunto_parte_clave}'")
        
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para hogar: {error}")
            return render_template('result.html', status="error", message=error)

        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        
        if link_boton_rojo:
            logging.info(f"WEB: Enlace del botón rojo 'Sí, la envié yo' encontrado: {link_boton_rojo}. Intentando obtener enlace final de confirmación...")
            
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
                logging.warning("WEB: No se pudo extraer el enlace de confirmación final del botón negro.")
                return render_template('result.html', status="warning", message="❌ No se pudo obtener el enlace de confirmación final. El formato de la página de Netflix puede haber cambiado. Contacta al administrador si persiste.")
        else:
            logging.warning("WEB: No se encontró el enlace del botón 'Sí, la envié yo' en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")
    else:
        logging.warning(f"WEB: Acción no válida recibida: {action}")
        return render_template('result.html', status="error", message="❌ Acción no válida. Por favor, selecciona 'Consultar Código' o 'Actualizar Hogar'.")

# =====================
# RUTA NUEVA PARA UNIVERSAL+
# =====================

 # --- Función corregida para extraer el código de Universal+ ---
def extraer_codigo_universal(html_content):
    """
    Extrae el código de 6 dígitos del correo de activación de Universal+.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Buscamos la etiqueta que contiene el código
    # El código está en un div con un estilo específico
    codigo_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
    
    if codigo_div:
        codigo = codigo_div.text.strip()
        # Verificamos si el código tiene 6 caracteres y es alfanumérico
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado: {codigo}")
            return codigo
    
    # Fallback: Buscamos el código con una expresión regular más amplia
    match = re.search(r'[\s](([A-Z0-9]{6}))[\s]', html_content)
    if match:
        codigo = match.group(1).strip()
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado (regex): {codigo}")
            return codigo

    logging.warning("No se pudo encontrar el código de Universal+ en el correo.")
    return None
        return None, "⚠️ Se encontró el correo, pero no se pudo extraer el código de Universal+. El formato del correo puede haber cambiado."
