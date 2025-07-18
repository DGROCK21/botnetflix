import imaplib
import email
import os

def buscar_codigo(correo_objetivo):
    EMAIL = os.getenv("EMAIL")
    PASSWORD = os.getenv("PASSWORD")
    SERVIDOR_IMAP = os.getenv("IMAP_SERVER", "imap.gmail.com")

    if not EMAIL or not PASSWORD:
        print("Credenciales no definidas en variables de entorno.")
        return None

    try:
        mail = imaplib.IMAP4_SSL(SERVIDOR_IMAP)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")

        typ, data = mail.search(None, 'UNSEEN')
        mail_ids = data[0].split()

        for num in reversed(mail_ids[-10:]):
            typ, data = mail.fetch(num, '(RFC822)')
            mensaje = email.message_from_bytes(data[0][1])
            asunto = mensaje["subject"]
            origen = mensaje["from"]

            if correo_objetivo.lower() in origen.lower():
                for parte in mensaje.walk():
                    if parte.get_content_type() == "text/plain":
                        payload = parte.get_payload(decode=True)
                        if payload is None:
                            continue
                        cuerpo = payload.decode()
                        lineas = cuerpo.split("\n")
                        for linea in lineas:
                            if "código" in linea.lower():
                                return linea.strip()
        return None
    except Exception as e:
        print(f"Error al buscar el código: {e}")
        return None