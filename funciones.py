import imaplib
import email
from email.header import decode_header
import re
import requests
from bs4 import BeautifulSoup
import logging
from imap_tools import MailBox, AND


def buscar_ultimo_correo(imap_user, imap_pass, asunto_clave):
    """
    Busca el último correo en el buzón con un asunto específico.
    Devuelve el contenido HTML del correo o un error.
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
    link = None
    
    if es_hogar:
        # Buscamos un enlace que contenga la palabra 'confirm-home-membership'
        link_tag = soup.find('a', href=lambda href: href and 'confirm-home-membership' in href)
    else:
        # Buscamos un enlace que contenga 'code-request'
        link_tag = soup.find('a', href=lambda href: href and 'code-request' in href)
        
    if link_tag:
        link = link_tag['href']
    return link

def obtener_codigo_de_pagina(url):
    """
    Visita el enlace del correo de Netflix y extrae el código final de la página.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Lanza un error para códigos de estado 4xx/5xx
        
        soup = BeautifulSoup(response.text, 'html.parser')
        # El código de 6 dígitos se encuentra dentro de la clase 'code'
        codigo_tag = soup.find('div', class_='code')
        
        if codigo_tag:
            return codigo_tag.text.strip()
            
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
        response.raise_for_status() # Lanza un error para códigos de estado 4xx/5xx
        
        soup = BeautifulSoup(response.text, 'html.parser')
        # Buscamos el enlace del botón negro "Confirmar actualización"
        link_tag = soup.find('a', href=lambda href: href and 'confirm-home-update' in href)
        
        if link_tag:
            return link_tag['href']
            
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al acceder a la página de Netflix para obtener el enlace de confirmación: {e}")
    except Exception as e:
        logging.error(f"Error inesperado al procesar la página de Netflix: {e}")
        
    return None


def navegar_y_extraer_universal(imap_user, imap_pass):
    """
    Busca el correo de Universal+ y extrae el código de activación.
    """
    asunto_universal = "Código de activación Universal+"
    logging.info(f"Buscando el correo de Universal+ con el asunto: '{asunto_universal}'")

    try:
        with MailBox('imap.gmail.com').login(imap_user, imap_pass, 'INBOX') as mailbox:
            # Buscar el correo más reciente con el asunto de Universal+
            for msg in mailbox.fetch(AND(subject=asunto_universal), reverse=True):
                # Usar BeautifulSoup para analizar el HTML del correo
                soup = BeautifulSoup(msg.html, 'html.parser')
                
                # Buscamos el código de activación con una expresión regular
                # Ahora busca exactamente 6 caracteres alfanuméricos
                code_pattern = re.compile(r'\b[A-Z0-9]{6}\b')
                code_element = soup.find(string=code_pattern)

                if code_element:
                    codigo = code_element.strip()
                    logging.info(f"✅ Código de Universal+ extraído: {codigo}")
                    return codigo, None
                else:
                    logging.warning("❌ No se encontró un código que coincida con el patrón en el correo de Universal+.")
                    return None, "❌ No se pudo encontrar un código de activación en el correo. El formato del correo puede haber cambiado."
    except Exception as e:
        logging.error(f"❌ Error al conectar o buscar el correo de Universal+: {e}")
        return None, f"❌ Error al conectar o buscar el correo: {str(e)}"

    return None, "❌ No se encontró ningún correo de activación de Universal+."