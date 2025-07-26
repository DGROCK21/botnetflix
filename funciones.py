import imaplib
import email
from email.header import decode_header
import re
import json
import logging
from bs4 import BeautifulSoup # Importar aquí también
import requests # Importar aquí también

# La función cargar_cuentas() NO es necesaria en este funciones.py
# Ya que main.py carga las cuentas y las usa para es_correo_autorizado
# y las credenciales IMAP se pasan directamente.
# La remuevo para mantener este módulo más limpio.

def buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_clave, num_mensajes_revisar=50):
    """
    Busca el último correo con un asunto clave dado para la cuenta IMAP especificada.
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
        
        # Obtener todos los mensajes y revisar los más recientes
        # Considerar si se puede filtrar por remitente para mayor eficiencia:
        # status, mensajes = mail.search(None, '(FROM "netflix.com") ALL') # Si Netflix.com es siempre el remitente
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

            # Filtrar por asunto clave
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
        return None, f"❌ No se encontró un correo reciente con el asunto '{asunto_clave}'. Asegúrate de haber solicitado el código/actualización y que el correo haya llegado."

    except imaplib.IMAP4.error as e:
        logging.error(f"Error de IMAP al acceder al correo {usuario_imap}: {e}. Verifica la contraseña de aplicación de Gmail.")
        return None, f"⚠️ Error de autenticación o IMAP: {str(e)}. Asegúrate de usar una contraseña de aplicación de Gmail (si tienes 2FA) y que la configuración IMAP esté habilitada."
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
        # Intenta encontrar el botón de estilo o el que tiene el texto específico
        boton = soup.find('a', style=lambda value: value and 'background-color:#e50914' in value)
        if not boton:
             boton = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE)) # Confirmado que funciona
        
        if boton and 'href' in boton.attrs:
            link = boton['href']
            logging.info(f"Enlace de confirmación de Hogar encontrado: {link}")
            return link
    
    # Busca enlaces con nftoken para el código de acceso temporal
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
        
        # REGEX AJUSTADA CON CONTEXTO HTML (confirmado con tu captura)
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
        
        # Busca confirmación en el texto de la respuesta (puede variar ligeramente)
        if "hogar actualizado" in response.text.lower() or "confirmado" in response.text.lower() or "success" in response.text.lower() or "gracias" in response.text.lower():
            logging.info("Mensaje de confirmación de hogar encontrado en la respuesta.")
            return True
        else:
            logging.warning("No se encontró un mensaje de confirmación explícito en la respuesta del hogar, pero la solicitud HTTP fue exitosa (200 OK).")
            return True # Asumimos éxito si no hay errores HTTP ni mensajes de fallo
            
    except requests.exceptions.Timeout:
        logging.error(f"Tiempo de espera agotado al visitar {url_confirmacion}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Error de red al intentar confirmar Hogar de Netflix de {url_confirmacion}: {e}")
        return False
    except Exception as e:
        logging.exception(f"Error inesperado al confirmar Hogar: {e}")
        return False