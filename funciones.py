import imaplib
import email
import re
import os
from email.header import decode_header

EMAIL = os.getenv("EMAIL_USER")
PASSWORD = os.getenv("EMAIL_PASS")

def buscar_codigo(correo):
    try:
        print(f"📥 Conectando a Gmail como {EMAIL}")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")

        _, mensajes = mail.search(None, "ALL")
        mensajes = mensajes[0].split()

        for num in reversed(mensajes[-20:]):
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            cuerpo = ""
            if mensaje.is_multipart():
                for parte in mensaje.walk():
                    if parte.get_content_type() == "text/plain":
                        payload = parte.get_payload(decode=True)
                        if payload:
                            cuerpo += payload.decode(errors="ignore")
            else:
                payload = mensaje.get_payload(decode=True)
                if payload:
                    cuerpo += payload.decode(errors="ignore")

            if correo in cuerpo:
                codigos = re.findall(r"\d{6}", cuerpo)
                if codigos:
                    print(f"✅ Código encontrado: {codigos[0]}")
                    return f"✅ Código encontrado: `{codigos[0]}`"

        print("❌ No se encontró ningún código")
        return None

    except Exception as e:
        print("❌ ERROR buscar_codigo:", e)
        return None


def buscar_link_actualizar_hogar(correo):
    try:
        print(f"📥 Conectando a Gmail como {EMAIL}")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")

        _, mensajes = mail.search(None, "ALL")
        mensajes = mensajes[0].split()

        for num in reversed(mensajes[-20:]):
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])

            cuerpo = ""
            if mensaje.is_multipart():
                for parte in mensaje.walk():
                    if parte.get_content_type() == "text/plain":
                        payload = parte.get_payload(decode=True)
                        if payload:
                            cuerpo += payload.decode(errors="ignore")
            else:
                payload = mensaje.get_payload(decode=True)
                if payload:
                    cuerpo += payload.decode(errors="ignore")

            if correo in cuerpo:
                match = re.search(r"https://www\.netflix\.com/update/home\S+", cuerpo)
                if match:
                    print(f"✅ Enlace hogar encontrado: {match.group(0)}")
                    return match.group(0)

        print("❌ No se encontró ningún enlace de hogar")
        return None

    except Exception as e:
        print("❌ ERROR buscar_link_actualizar_hogar:", e)
        return None