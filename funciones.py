import imaplib
import email
from email.header import decode_header
import re
import json
import logging

def cargar_cuentas():
    with open("cuentas.json", "r") as archivo:
        return json.load(archivo)

def obtener_credenciales(correo):
    cuentas = cargar_cuentas()
    for user_id, correos in cuentas.items():
        for entrada in correos:
            if entrada.startswith(correo):
                partes = entrada.split("|")
                if len(partes) == 3:
                    return partes[1], partes[2]
    return None, None

def buscar_ultimo_correo(correo, asunto_clave):
    usuario, contrasena = obtener_credenciales(correo)
    if not usuario or not contrasena:
        return None, "⚠️ No se encontraron credenciales para ese correo."

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario, contrasena)
        mail.select("inbox")

        _, mensajes = mail.search(None, 'ALL')
        mensajes = mensajes[0].split()

        for num in reversed(mensajes[-20:]):
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            asunto, codificacion = decode_header(mensaje["Subject"])[0]
            if isinstance(asunto, bytes):
                asunto = asunto.decode(codificacion or "utf-8")

            if asunto_clave.lower() in asunto.lower():
                if mensaje.is_multipart():
                    for parte in mensaje.walk():
                        tipo = parte.get_content_type()
                        if tipo == "text/html":
                            html = parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8")
                            mail.logout()
                            return html, None
                else:
                    html = mensaje.get_payload(decode=True).decode(mensaje.get_content_charset() or "utf-8")
                    mail.logout()
                    return html, None

        mail.logout()
        return None, "❌ No se encontró un correo reciente con ese asunto."

    except Exception as e:
        logging.exception("Error al buscar correo")
        return None, f"⚠️ Error al acceder al correo: {str(e)}"

def extraer_link_con_token(html):
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html)
    for link in links:
        if "nftoken=" in link:
            return link
    return None

def buscar_codigo(correo):
    html, error = buscar_ultimo_correo(correo, "Código de acceso")
    if error:
        return error

    link = extraer_link_con_token(html)
    return link if link else "❌ No se encontró enlace con código."

def buscar_link_actualizar_hogar(correo):
    html, error = buscar_ultimo_correo(correo, "actualizar hogar")
    if error:
        return error

    link = extraer_link_con_token(html)
    return link if link else "❌ No se encontró enlace de actualización de hogar."
