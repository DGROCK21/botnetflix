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
        
        status, messages = mailbox.search(None, f'SUBJEC
