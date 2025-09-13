import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from keep_alive import mantener_vivo
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

# Obtener credenciales IMAP desde las variables de entorno de Render
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")

if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")

app = Flask(__name__)

# =====================
# FUNCIONES AUXILIARES (integradas)
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
    Busca el último correo con un asunto específico, manejando la codificación de forma robusta.
    """
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(imap_user, imap_pass)
        imap.select('inbox')
        
        # Codificamos el asunto para que la búsqueda IMAP no falle con caracteres especiales
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
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(imap_user, imap_pass)
        imap.select('inbox')
        
        # Codificamos el asunto para que la búsqueda IMAP no falle con caracteres especiales
        search_criteria = f'(SUBJECT "{asunto_universal}")'.encode('utf-8')
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
            soup = BeautifulSoup(html_content, 'html.parser')
            code_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
            if code_div:
                codigo = code_div.text.strip()
                if re.fullmatch(r'[A-Z0-9]{6,7}', codigo):
                    return codigo, None
                else:
                    return None, "❌ Se encontró un texto en la etiqueta correcta, pero no coincide con el formato de código."
            else:
                return None, "❌ No se pudo encontrar el código de activación. El formato del correo puede haber cambiado."
        else:
            return None, "❌ No se pudo encontrar la parte HTML del correo."
    except Exception as e:
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
        logging.warning("WEB: Solicitud sin correo o plataforma.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    if not es_correo_autorizado(user_email_input, platform):
        return render_template('result.html', status="error", message=f"⚠️ Correo no autorizado para la plataforma {platform}.")

    if platform == 'netflix':
        if action == 'code':
            asunto_clave = "Código de acceso temporal de Netflix"
            logging.info(f"WEB: Solicitud de código para {user_email_input}. Buscando correo con asunto: '{asunto_clave}'")
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
                    return render_template('result.html', status="warning", message="No se pudo obtener el código activo para esta cuenta.")
            else:
                return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

        elif action == 'hogar':
            asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix"
            logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando correo que contenga: '{asunto_parte_clave}'")
            html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave)
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
        return render_template('result.html', status="warning", message="❌ La funcionalidad de Universal+ no está habilitada en esta versión del bot.")
            
    else:
        logging.warning(f"WEB: Plataforma no válida recibida: {platform}")
        return render_template('result.html', status="error", message="❌ Plataforma no válida. Por favor, selecciona una de las opciones.")

# =====================
# Inicio de la aplicación Flask
# =====================

if __name__ == "__main__":
    mantener_vivo()
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Iniciando Flask app en el puerto {port}")
    app.run(host="0.0.0.0", port=port)
