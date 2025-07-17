import imaplib
import email
from email.header import decode_header
import re
import time

# Reemplaza con tu email y contraseña de aplicación
EMAIL = "dgarayrock@gmail.com"
PASSWORD = "tyzaiqthdsztrjle"

def buscar_codigo(correo):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    _, mensajes = mail.search(None, "ALL")
    mensajes = mensajes[0].split()

    for num in reversed(mensajes[-20:]):
        _, datos = mail.fetch(num, "(RFC822)")
        mensaje = email.message_from_bytes(datos[0][1])
        asunto = decode_header(mensaje["Subject"])[0][0]
        if isinstance(asunto, bytes):
            asunto = asunto.decode()
        cuerpo = mensaje.get_payload(decode=True).decode()
        if correo in cuerpo:
            codigos = re.findall(r"\d{6}", cuerpo)
            if codigos:
                return f"✅ Código encontrado: `{codigos[0]}`"
    return None

def buscar_link_actualizar_hogar(correo):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    _, mensajes = mail.search(None, "ALL")
    mensajes = mensajes[0].split()

    for num in reversed(mensajes[-20:]):
        _, datos = mail.fetch(num, "(RFC822)")
        mensaje = email.message_from_bytes(datos[0][1])
        cuerpo = mensaje.get_payload(decode=True).decode(errors='ignore')
        if correo in cuerpo:
            match = re.search(r"https://www\.netflix\.com/update/home\S+", cuerpo)
            if match:
                return match.group(0)
    return None
