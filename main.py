import os
import json
import logging
from flask import Flask, request, render_template_string
import imaplib
import email
from email.header import decode_header
import re
import requests
from bs4 import BeautifulSoup
import telebot
from telebot import types 

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas (para validación)
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente.")
except Exception:
    logging.warning("No se pudo cargar cuentas.json.")
    cuentas = {}

# Obtener credenciales
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN") 

# Inicializar Flask
app = Flask(__name__)

# Inicializar Telebot (Respaldo)
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram (Respaldo) inicializado.")
else:
    bot = None

# =================================================================
# LÓGICA DE EXTRACCIÓN (NETFLIX) - NO SE MODIFICA
# =================================================================

def buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_parte_clave, num_mensajes_revisar=50):
    """ Busca el último correo que CONTIENE una parte del asunto clave. Retorna HTML, mensaje, status_clase """
    if not usuario_imap or not contrasena_imap:
        return None, "❌ Error: Credenciales IMAP no configuradas en Render.", "error"
    
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(usuario_imap, contrasena_imap) 
        mail.select("inbox")
        _, mensajes = mail.search(None, "ALL") 
        mensajes = mensajes[0].split()

        mensajes_reversados = reversed(mensajes[-min(num_mensajes_revisar, len(mensajes)):])
        
        for num in mensajes_reversados:
            _, datos = mail.fetch(num, "(RFC822)")
            mensaje = email.message_from_bytes(datos[0][1])
            
            asunto_parts = decode_header(mensaje["Subject"])
            asunto = "".join([
                part.decode(encoding or "utf-8", errors='ignore') if isinstance(part, bytes) else part
                for part, encoding in asunto_parts
            ])

            if asunto_parte_clave.lower() in asunto.lower():
                html_content = None
                if mensaje.is_multipart():
                    for parte in mensaje.walk():
                        ctype = parte.get_content_type()
                        cdisp = str(parte.get('Content-Disposition')) 
                        if ctype == 'text/html' and 'attachment' not in cdisp:
                            html_content = parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8", errors='ignore')
                            break
                
                if html_content:
                    mail.logout()
                    return html_content, None, None
        
        mail.logout()
        return None, f"❌ No se encontró un correo de Netflix con la clave: {asunto_parte_clave}", "warning"

    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        return None, f"⚠️ Error de autenticación: {error_msg}. Verifica la Contraseña de Aplicación.", "error"
    except Exception as e:
        return None, f"⚠️ Error inesperado: {str(e)}", "error"

def extraer_link_con_token_o_confirmacion(html_content, es_hogar=False):
    """ Extrae el enlace relevante del HTML del correo. """
    soup = BeautifulSoup(html_content, 'html.parser')
    if es_hogar:
        boton_rojo = soup.find('a', string=re.compile(r'Sí, la envié yo', re.IGNORECASE))
        if boton_rojo and 'href' in boton_rojo.attrs:
            return boton_rojo['href']
    
    for a_tag in soup.find_all('a', href=True):
        if "nftoken=" in a_tag['href']:
            return a_tag['href']
    return None

def obtener_codigo_de_pagina(url_netflix):
    """ Visita la URL de Netflix y extrae el código de 4 dígitos. """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url_netflix, headers=headers, timeout=30) 
        response.raise_for_status() 
        match = re.search(r'<div[^>]*class=["\']challenge-code["\'][^>]*>(\d{4})<\/div>', response.text) 
        if match:
            return match.group(1)
        return None
    except requests.exceptions.RequestException:
        return None

# =================================================================
# HANDLERS DEL BOT DE TELEGRAM (Respaldo) - Mismos comandos /code y /hogar
# =================================================================

if bot:
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        bot.reply_to(message, "¡Hola! Soy el bot de respaldo. Usa /code o /hogar.")

    @bot.message_handler(commands=['code'])
    def handle_obtener_codigo(message):
        html_correo, error_msg, error_status = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Código de acceso temporal")
        if error_msg:
            bot.reply_to(message, error_msg)
            return
        # ... (resto de la lógica de Telegram)
        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
        if link:
            codigo = obtener_codigo_de_pagina(link)
            if codigo:
                bot.reply_to(message, f"✅ CÓDIGO TEMPORAL: {codigo}\nLink: {link}")
            else:
                bot.reply_to(message, "⚠️ No se pudo extraer el código de la página de Netflix.")
        else:
            bot.reply_to(message, "⚠️ No se encontró un link con token válido en el correo.")

    @bot.message_handler(commands=['hogar'])
    def handle_confirmar_hogar(message):
        html_correo, error_msg, error_status = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Actualiza tu hogar con un solo clic")

        if error_msg:
            bot.reply_to(message, error_msg)
            return
        
        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link_boton_rojo:
            bot.reply_to(message, f"✅ ENLACE DE CONFIRMACIÓN: Por favor, haz clic aquí:\n{link_boton_rojo}")
        else:
            bot.reply_to(message, "❌ No se encontró un correo de Netflix para actualizar el hogar.")

# =================================================================
# RUTAS WEB (INTERFAZ CON TUS MÓDULOS)
# =================================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado = ""
    status_clase = ""
    
    if request.method == 'POST':
        accion = request.form.get('accion') # netflix_code, netflix_hogar, prime_code, etc.
        
        if not IMAP_USER or not IMAP_PASS:
            resultado = "❌ ERROR: Las credenciales de correo (E-MAIL_USER/EMAIL_PASS) no están configuradas en Render."
            status_clase = "error"
        
        elif 'netflix' in accion:
            # Lógica de NETFLIX
            asunto_clave = "Código de acceso temporal" if 'code' in accion else "Actualiza tu hogar con un solo clic"
            
            html_correo, error_msg, error_status = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave)
            
            if error_msg:
                resultado, status_clase = error_msg, error_status
            else:
                if 'code' in accion:
                    link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
                    codigo = obtener_codigo_de_pagina(link) if link else None
                    resultado = f"✅ **CÓDIGO TEMPORAL:** <code>{codigo}</code><br><strong>Link:</strong> <a href='{link}' target='_blank' class='text-red-400 underline'>Ver Enlace</a>" if codigo else "⚠️ No se pudo extraer el código/enlace de la página."
                    status_clase = 'success' if codigo else 'warning'
                else: # Confirmar Hogar
                    link_hogar = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
                    resultado = f"✅ **ENLACE HOGAR:** Por favor, haz clic aquí: <a href='{link_hogar}' target='_blank' class='text-red-400 underline'>Confirmar Actualización</a>" if link_hogar else "⚠️ No se encontró el enlace de 'Sí, la envié yo'."
                    status_clase = 'success' if link_hogar else 'warning'
        
        else:
            # Lógica de Disney y Prime (Deshabilitado)
            plataforma_nombre = accion.split('_')[0].capitalize()
            resultado = f"Módulo de {plataforma_nombre} no implementado aún. Trabajando en ello."
            status_clase = "warning"

    # Renderizamos la plantilla HTML
    return render_template_string(HTML_TEMPLATE_MODULOS, resultado=resultado, status_clase=status_clase, imap_user=IMAP_USER)

# =================================================================
# PLANTILLA HTML DE LOS MÓDULOS (TU DISEÑO)
# =================================================================

HTML_TEMPLATE_MODULOS = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DGPPLAY ENTERTAINMENT</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700;900&display=swap');
        body { font-family: 'Roboto', sans-serif; background-color: #111111; }
        .card { transition: transform 0.3s ease, box-shadow 0.3s ease; }
        .card:hover { transform: translateY(-5px); box-shadow: 0 10px 20px rgba(0, 0, 0, 0.4); }
        .btn-netflix { background-color: #E50914; border: 1px solid #E50914; }
        .btn-netflix:hover { background-color: #F40A15; }
        .btn-prime { background-color: #00A8E1; border: 1px solid #00A8E1; }
        .btn-prime:hover { background-color: #00B9F2; }
        .btn-disney { background-color: #01509D; border: 1px solid #01509D; }
        .btn-disney:hover { background-color: #0261AE; }
    </style>
</head>
<body class="p-6">
    <div class="max-w-6xl mx-auto">
        <!-- Título principal y Área de Resultados -->
        <header class="text-center mb-10">
            <h1 class="text-4xl font-black text-green-500 mb-2 tracking-wider">DGPPLAY ENTERTAINMENT</h1>
            <h2 class="text-xl text-gray-300">Tu Centro de Acceso Rápido a Códigos de Streaming</h2>
        </header>

        <!-- Área de Resultados Flotante -->
        {% if resultado %}
        <div class="fixed top-0 left-0 right-0 z-50 p-4 flex justify-center">
            <div class="w-full max-w-xl p-4 rounded-lg shadow-2xl text-white text-center font-medium
                {% if status_clase == 'success' %}
                    bg-green-700 border border-green-400
                {% elif status_clase == 'error' %}
                    bg-red-700 border border-red-400
                {% else %}
                    bg-yellow-700 border border-yellow-400
                {% endif %}">
                {{ resultado | safe }}
            </div>
        </div>
        {% endif %}

        <!-- Contenedor de Módulos (3 Columnas) -->
        <main class="grid grid-cols-1 md:grid-cols-3 gap-8">
            
            <!-- MÓDULO 1: NETFLIX -->
            <div class="card bg-gray-900 p-6 rounded-xl shadow-xl border border-red-700">
                <h3 class="text-3xl font-extrabold text-red-600 mb-4 text-center tracking-widest">NETFLIX</h3>
                <p class="text-gray-400 mb-6 text-center text-sm">Haz clic para obtener código o actualizar hogar. Usa el correo que reenvía a {{ imap_user }}.</p>
                <form method="POST" class="space-y-4">
                    <!-- Campo de Correo del Cliente ELIMINADO para usar el IMAP_USER global -->
                    <button type="submit" name="accion" value="netflix_code" class="btn-netflix w-full py-3 font-bold rounded-lg shadow-md hover:shadow-lg transition duration-200">
                        Consultar Código
                    </button>
                    <button type="submit" name="accion" value="netflix_hogar" class="btn-netflix w-full py-3 font-bold rounded-lg shadow-md hover:shadow-lg transition duration-200">
                        Actualizar Hogar
                    </button>
                </form>
            </div>

            <!-- MÓDULO 2: PRIME VIDEO -->
            <div class="card bg-gray-900 p-6 rounded-xl shadow-xl border border-blue-700 opacity-60 pointer-events-none">
                <h3 class="text-3xl font-extrabold text-blue-600 mb-4 text-center tracking-widest">PRIME VIDEO</h3>
                <p class="text-gray-500 mb-6 text-center text-sm">Módulo en construcción. Usa el correo que reenvía a {{ imap_user }}.</p>
                <form method="POST" class="space-y-4">
                    <button type="submit" name="accion" value="prime_code" class="btn-prime w-full py-3 font-bold rounded-lg shadow-md">
                        Consultar Código
                    </button>
                    <button type="submit" name="accion" value="prime_hogar" class="btn-prime w-full py-3 font-bold rounded-lg shadow-md">
                        Actualizar Hogar
                    </button>
                </form>
            </div>

            <!-- MÓDULO 3: DISNEY+ -->
            <div class="card bg-gray-900 p-6 rounded-xl shadow-xl border border-blue-900 opacity-60 pointer-events-none">
                <h3 class="text-3xl font-extrabold text-blue-800 mb-4 text-center tracking-widest">DISNEY+</h3>
                <p class="text-gray-500 mb-6 text-center text-sm">Módulo en construcción. Usa el correo que reenvía a {{ imap_user }}.</p>
                <form method="POST" class="space-y-4">
                    <button type="submit" name="accion" value="disney_code" class="btn-disney w-full py-3 font-bold rounded-lg shadow-md">
                        Consultar Código
                    </button>
                    <button type="submit" name="accion" value="disney_hogar" class="btn-disney w-full py-3 font-bold rounded-lg shadow-md">
                        Actualizar Hogar
                    </button>
                </form>
            </div>
        </main>

        <footer class="text-center mt-12 text-gray-500 text-sm">
            <p>Conexión IMAP de Monitoreo: {{ imap_user if imap_user else 'Sin configurar' }}</p>
            <p>© 2025 DGPPLAY ENTERTAINMENT. Todos los derechos reservados.</p>
        </footer>
    </div>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
