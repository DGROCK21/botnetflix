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

def es_correo_autorizado(correo_usuario):
    """
    Verifica si el correo de usuario (ej. @dgplayk.com) pertenece a una de las cuentas autorizadas en cuentas.json.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados por el bot.")
        return False
        
    for user_id, correos_list in cuentas.items():
        for entrada in correos_list:
            # La entrada puede ser "correo@dominio.com" o "correo@dominio.com|user_imap|pass_imap"
            # Nos interesa solo la primera parte para comparar con el input del usuario
            correo_en_lista = entrada.split("|")[0].lower()
            if correo_en_lista == correo_usuario.lower():
                return True
    return False


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
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            try:
                asunto_parts = decode_header(mensaje["Subject"])
                asunto = ""
                for part, encoding in asunto_parts:
                    if isinstance(part, bytes):
                        asunto += part.decode(encoding or "utf-8", errors='ignore')
                    else:
                        asunto += part
            except Exception as e:
                asunto = mensaje.get("Subject", "Sin Asunto") 
                logging.warning(f"No se pudo decodificar el asunto: {e}. Usando asunto crudo: {asunto}")

            # CAMBIO CLAVE AQUÍ: Buscar si el asunto CONTIENE la parte clave
            if asunto_parte_clave.lower() in asunto.lower():
                logging.info(f"Parte del asunto '{asunto_parte_clave}' encontrada en '{asunto}'. Extrayendo HTML.")
                
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
        logging.info(f"No se encontró un correo reciente con el asunto que contiene '{asunto_parte_clave}' para {usuario_imap}.")
        return None, f"❌ No se encontró un correo reciente de Netflix para esta acción. Asegúrate de haberla solicitado y que el correo haya llegado."

    except imaplib.IMAP4.error as e:
        logging.error(f"Error de IMAP al acceder al correo {usuario_imap}: {e}. Verifica la contraseña de aplicación de Gmail.")
        return None, f"⚠️ Error de autenticación o IMAP: {str(e)}. Asegúrate de usar una contraseña de aplicación de Gmail (si tienes 2FA) y que la configuración IMAP esté habilitada."
    except Exception as e:
        logging.exception(f"Error inesperado al buscar correo para {usuario_imap}")
        return None, f"⚠️ Error inesperado al acceder al correo: {str(e)}"


def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """
    Extrae el enlace relevante del HTML del correo.
    Para "hogar", busca el botón rojo "Sí, la envié yo" del primer correo.
    Para "código", busca enlaces con 'nftoken='.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    if es_hogar:
        # Busca el botón rojo "Sí, la envié yo"
        boton_rojo = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE))
        if boton_rojo and 'href' in boton_rojo.attrs:
            link = boton_rojo['href']
            logging.info(f"Enlace del botón 'Sí, la envié yo' encontrado: {link}")
            return link
    
    # Busca enlaces con nftoken para el código de acceso temporal
    for a_tag in soup.find_all('a', href=True):
        link = a_tag['href']
        if "nftoken=" in link:
            logging.info(f"Enlace con nftoken encontrado: {link}")
            return link
            
    logging.info("No se encontró ningún enlace relevante en el HTML del correo inicial.")
    return None

def obtener_enlace_confirmacion_final_hogar(url_boton_rojo):
    """
    Visita la URL del botón rojo 'Sí, la envié yo' y extrae el enlace del botón negro 'Confirmar actualización'.
    """
    try: # <-- Inicio del bloque try
        logging.info(f"Visitando URL del botón rojo para obtener el enlace final de confirmación: {url_boton_rojo}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36', # User-Agent más actualizado
            'Referer': 'https://www.netflix.com/' 
        }
        # Usamos allow_redirects=True para seguir la redirección a la página del botón negro
        response = requests.get(url_boton_rojo, headers=headers, allow_redirects=True, timeout=30) 
        response.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)

        html_pagina_final_confirmacion = response.text
        logging.info("Página de confirmación final obtenida. Buscando el botón 'Confirmar actualización'...")
        
        soup = BeautifulSoup(html_pagina_final_confirmacion, 'html.parser')
        
        # Buscamos el botón negro por su texto y data-uia (el que estaba en la captura de pantalla)
        # Es vital que esta búsqueda sea precisa
        boton_confirmar = soup.find('button', attrs={'data-uia': 'set-primary-location-action'}, string=re.compile(r'Confirmar actualización', re.IGNORECASE))
        
        if not boton_confirmar:
            # Fallback si el data-uia o el texto cambian un poco, buscar por el <form> donde suele estar
            # O por alguna clase CSS distintiva del botón si es posible.
            logging.warning("No se encontró el botón de Confirmar actualización por data-uia o texto directo. Intentando buscar en formularios o enlaces si es posible.")
            # Si el botón negro es un submit de un form, podemos buscar la URL del action del form
            form = soup.find('form', action=True)
            if form and 'action' in form.attrs:
                # Esto es un placeholder, la URL exacta del action del form podría ser relativa
                # O la acción del botón es JS. Esta es la parte más compleja sin Selenium.
                logging.warning("Se encontró un formulario. Su acción podría ser la URL de confirmación.")
                return response.url # Retornamos la URL de la página si el botón es un submit JS
                
        # Si el botón es un <button> que activa una acción JavaScript, la URL a enviar es la de la página actual
        # porque el 'clic' real es una petición POST/GET activada por JS en esa página.
        # En la mayoría de los casos, la URL de la página donde se encuentra el botón es la que hay que "visitar" de nuevo (POST/GET).
        # Para el propósito de pasar un LINK al administrador, le pasamos la URL actual de la página.
        if boton_confirmar:
             logging.info("Botón 'Confirmar actualización' encontrado. Retornando la URL de la página.")
             return response.url # Devolvemos la URL actual de la página donde está el botón
            
        logging.warning("No se encontró el botón de 'Confirmar actualización' ni un formulario de acción para el hogar.")
        return None

    except requests.exceptions.Timeout: # <-- Bloque except del try principal
        logging.error(f"Tiempo de espera agotado al visitar {url_boton_rojo}")
        return None
    except requests.exceptions.RequestException as e: # <-- Bloque except del try principal
        logging.error(f"Error de red al intentar obtener el enlace de confirmación de {url_boton_rojo}: {e}")
        return None
    except Exception as e: # <-- Bloque except del try principal
        logging.exception(f"Error inesperado al obtener el enlace de confirmación final: {e}")
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
        
        match = re.search(r'<div[^>]*class=["\']challenge-code["\'][^>]*>(\d{4})<\/div>', html_pagina_codigo) 

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

# La función confirmar_hogar_netflix original se elimina porque la acción es asistida manualmente.
# Si el usuario quiere el enlace para el clic final, la nueva función `obtener_enlace_confirmacion_final_hogar` se encargará de eso.

}
Este es el funciones py ANTIGUO
