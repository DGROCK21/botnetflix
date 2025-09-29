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

# Inicializar Flask
app = Flask(__name__)

# =================================================================
# LÓGICA DE EXTRACCIÓN (NETFLIX)
# =================================================================

def buscar_ultimo_correo(usuario_imap, contrasena_imap, asunto_parte_clave, num_mensajes_revisar=50):
    """ Busca el último correo que CONTIENE una parte del asunto clave. """
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
# RUTAS WEB (La Interfaz de Trabajo)
# =================================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado_status = 'warning'
    resultado_msg = "Bienvenido al Panel de Módulos. Seleccione una acción."
    
    if request.method == 'POST':
        plataforma = request.form.get('plataforma')
        accion = request.form.get('accion')
        
        if not IMAP_USER or not IMAP_PASS:
            resultado_status = 'error'
            resultado_msg = "❌ ERROR: Las credenciales de correo (E-MAIL_USER/EMAIL_PASS) no están configuradas en Render."
        elif plataforma == 'netflix':
            if accion == 'obtener_codigo':
                html_correo, error_msg, error_status = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Código de acceso temporal")
                if error_msg:
                    resultado_msg, resultado_status = error_msg, error_status
                else:
                    link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False)
                    if link:
                        codigo = obtener_codigo_de_pagina(link)
                        resultado_msg = f"✅ **CÓDIGO TEMPORAL:** <code>{codigo}</code><br><strong>Link:</strong> <a href='{link}' target='_blank' class='text-red-400 underline'>Ver Enlace</a>" if codigo else "⚠️ No se pudo extraer el código de la página de Netflix."
                        resultado_status = 'success' if codigo else 'warning'
                    else:
                        resultado_msg = "⚠️ No se encontró un enlace con token en el correo."
                        resultado_status = 'warning'

            elif accion == 'confirmar_hogar':
                html_correo, error_msg, error_status = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, "Actualiza tu hogar con un solo clic")
                if error_msg:
                    resultado_msg, resultado_status = error_msg, error_status
                else:
                    link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
                    resultado_msg = f"✅ **ENLACE DE CONFIRMACIÓN:** Por favor, haz clic aquí: <a href='{link_boton_rojo}' target='_blank' class='text-red-400 underline'>Confirmar Actualización</a>" if link_boton_rojo else "⚠️ No se encontró el correo o el enlace de 'Sí, la envié yo'."
                    resultado_status = 'success' if link_boton_rojo else 'warning'
        
        elif plataforma in ['disney', 'prime']:
            resultado_msg = f"Módulo de {plataforma.capitalize()} no implementado aún. Trabajando en ello."
            resultado_status = 'warning'
    
    # Renderizamos la plantilla HTML con los resultados
    return render_template_string(HTML_TEMPLATE, status=resultado_status, message=resultado_msg, imap_user=IMAP_USER)

# =================================================================
# PLANTILLA HTML PRINCIPAL (Módulos y Formulario)
# =================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Panel de Módulos</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { font-family: 'Inter', sans-serif; }
        .result-box {
            min-height: 100px; 
            white-space: pre-wrap;
            word-wrap: break-word;
        }
    </style>
</head>
<body class="bg-gray-900 min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-lg bg-gray-800 p-8 rounded-xl shadow-2xl border border-red-700">
        <h1 class="text-3xl font-extrabold text-red-500 mb-6 text-center">
            Panel de Módulos (Web)
        </h1>
        
        <!-- Área de Resultados -->
        <div id="resultado" class="result-box p-4 mb-6 rounded-lg text-sm transition duration-300
            {% if status == 'success' %}
                bg-green-900 text-green-200 border-l-4 border-green-500
            {% elif status == 'error' %}
                bg-red-900 text-red-200 border-l-4 border-red-500
            {% else %}
                bg-gray-700 text-white border-l-4 border-gray-500
            {% endif %}">
            {{ message | safe }}
        </div>

        <!-- Formulario de Acción -->
        <form method="POST" class="space-y-4">
            <div>
                <label for="plataforma" class="block text-sm font-medium text-gray-300 mb-1">
                    Plataforma a Gestionar
                </label>
                <select 
                    id="plataforma" 
                    name="plataforma" 
                    class="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:ring-red-500 focus:border-red-500"
                >
                    <option value="netflix">Netflix</option>
                    <option value="disney" disabled>Disney+ (Próximamente)</option>
                    <option value="prime" disabled>Prime Video (Próximamente)</option>
                </select>
            </div>

            <div class="space-y-2 pt-4">
                <button 
                    type="submit" 
                    name="accion" 
                    value="obtener_codigo"
                    class="w-full flex items-center justify-center px-4 py-3 text-sm font-medium rounded-lg shadow-sm text-white bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition duration-150 ease-in-out"
                >
                    <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2v2m-4 0v2m-4-2h4m-4 0h.01M9 12h.01M19 12h.01M5 12h.01M15 17h.01M5 7h.01M19 7h.01M15 17a2 2 0 01-2 2H7a2 2 0 01-2-2v-4a2 2 0 012-2h6a2 2 0 012 2v4z"></path></svg>
                    Obtener Código Temporal
                </button>
                
                <button 
                    type="submit" 
                    name="accion" 
                    value="confirmar_hogar"
                    class="w-full flex items-center justify-center px-4 py-3 text-sm font-medium rounded-lg shadow-sm text-white bg-gray-600 hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 transition duration-150 ease-in-out"
                >
                    <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                    Confirmar Hogar
                </button>
            </div>
        </form>
        
        <p class="text-xs text-gray-500 mt-6 text-center">
            Conexión IMAP a: {{ imap_user if imap_user else 'Sin configurar' }}
        </p>
    </div>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # NOTA: EL BOT DE TELEGRAM HA SIDO ELIMINADO PARA ENFOCARNOS EN LA WEB
    app.run(host='0.0.0.0', port=port)
