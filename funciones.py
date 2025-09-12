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

# --- Función corregida para extraer el código de Universal+ ---

def extraer_codigo_universal(html_content):
    """
    Extrae el código de 6 dígitos del correo de activación de Universal+.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Buscamos un div que contenga el código. El código de Universal+ suele ser de 6 caracteres (letras y números).
    # Un patrón común es una celda con un estilo de font-size grande y centrado.
    codigo_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
    
    if codigo_div:
        codigo = codigo_div.text.strip()
        # Verificamos si el código tiene 6 caracteres y es alfanumérico
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado: {codigo}")
            return codigo
    
    # Fallback: Si no lo encontramos en la etiqueta div, buscamos el código con una expresión regular más amplia
    match = re.search(r'[\s](([A-Z0-9]{6}))[\s]', html_content)
    if match:
        codigo = match.group(1).strip()
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado (regex): {codigo}")
            return codigo

    logging.warning("No se pudo encontrar el código de Universal+ en el correo.")
    return None
    
def navegar_y_extraer_universal(usuario_imap, contrasena_imap):
    """
    Busca el correo de Universal+ y extrae el código.
    """
    asunto_clave = "Universal+ código de activación"
    html_correo, error = buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_clave)
    
    if error:
        return None, error
    
    if not html_correo:
        return None, "❌ No se encontró ningún correo de Universal+ reciente."
    
    codigo = extraer_codigo_universal(html_correo)
    
    if codigo:
        return codigo, None
    else:
        return None, "⚠️ Se encontró el correo, pero no se pudo extraer el código de Universal+. El formato del correo puede haber cambiado."