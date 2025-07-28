import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from keep_alive import mantener_vivo
# Importar funciones necesarias desde funciones.py
# Asegúrate de que estas funciones solo usen los parámetros que les pasas
from funciones import buscar_ultimo_correo, extraer_link_con_token_o_confirmacion, obtener_codigo_de_pagina, confirmar_hogar_netflix
import telebot # Importamos telebot para la funcionalidad del bot

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo (solo para validación de correos de usuario autorizados)
# Este archivo debe estar en la misma carpeta que main.py
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. La validación de correo no funcionará.")
    cuentas = {} # Inicializa como diccionario vacío para evitar errores posteriores
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json. La validación de correo podría ser inconsistente.")
    cuentas = {}

# Obtener credenciales IMAP y el token del bot desde las variables de entorno de Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido en las variables de entorno de Render. La funcionalidad de Telegram NO ESTARÁ DISPONIBLE.")
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos en las variables de entorno de Render. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")
    # Si estas no están, el bot no podrá conectarse a Gmail, lo que es crítico.

# Inicializar Flask
app = Flask(__name__)

# Inicializar Telebot solo si el token está presente
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram inicializado.")
else:
    bot = None # Establecemos bot a None para evitar errores si no hay token

# =====================
# Funciones auxiliares para la web y el bot de Telegram
# =====================

def es_correo_autorizado(correo_usuario):
    """
    Verifica si el correo de usuario (ej. @dgplayk.com) pertenece a una de las cuentas autorizadas en cuentas.json.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados por el bot.")
        return False
        
    for user_id, correos_list in cuentas.items():
        for entrada in correos_list:
            # La entrada puede ser "correo@dominio.com" o "correo@dominio.com|user_imap|pass_imap"
            # Nos interesa solo la primera parte para comparar con el input del usuario
            correo_en_lista = entrada.split("|")[0].lower()
            if correo_en_lista == correo_usuario.lower():
                return True
    return False

# =====================
# Rutas de la aplicación web (Flask)
# =====================

@app.route('/')
def home():
    """Renderiza la página principal con el formulario."""
    return render_template('index.html')

@app.route('/consultar_accion', methods=['POST'])
def consultar_accion_web():
    user_email_input = request.form.get('email', '').strip()
    action = request.form.get('action') # Esto viene del atributo 'name' y 'value' de los botones submit

    if not user_email_input:
        logging.warning("WEB: Solicitud sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    if not es_correo_autorizado(user_email_input):
        logging.warning(f"WEB: Intento de correo no autorizado: {user_email_input}")
        return render_template('result.html', status="error", message="⚠️ Correo no autorizado. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")

    if not IMAP_USER or not IMAP_PASS:
        logging.error("WEB: E-MAIL_USER o EMAIL_PASS no definidos. La funcionalidad de lectura de correos no es válida.")
        return render_template('result.html', status="error", message="❌ Error interno del servidor: La configuración de lectura de correos no es válida. Contacta al administrador del servicio.")

    # Lógica para obtener el código o confirmar el hogar
    if action == 'code':
        asunto_clave = "Código de acceso temporal de Netflix" # Ajusta el asunto si es diferente
        logging.info(f"WEB: Solicitud de código para {user_email_input}. Buscando en {IMAP_USER} correo con asunto: '{asunto_clave}'")
        
        # Llama a buscar_ultimo_correo con las credenciales IMAP del bot
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para código: {error}")
            return render_template('result.html', status="error", message=error)

        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False) 
        if link:
            logging.info(f"WEB: Enlace de token encontrado: {link}. Intentando obtener código de la página.")
            codigo_final = obtener_codigo_de_pagina(link)
            if codigo_final:
                logging.info(f"WEB: Código obtenido: {codigo_final}")
                return render_template('result.html', status="success", message=f"✅ Tu código de Netflix es: <strong>{codigo_final}</strong>.<br>Úsalo en tu TV o dispositivo.")
            else:
                logging.warning("WEB: Se encontró el enlace de código, pero no se pudo extraer el código de la página de Netflix.")
                return render_template('result.html', status="warning", message="❌ Se encontró el correo con enlace, pero no se pudo extraer el código de Netflix. El formato de la página puede haber cambiado. Contacta al administrador si persiste.")
        else:
            logging.warning("WEB: No se encontró enlace de código de Netflix en el correo principal.")
            # Este mensaje es clave cuando no hay un correo coincidente con el asunto.
            return render_template('result.html', status="warning", message="❌ No se encontró ningún correo con un enlace de código de Netflix reciente. Asegúrate de haber solicitado el código en tu TV o dispositivo Netflix y que el correo haya llegado a la cuenta principal.")

    elif action == 'hogar':
        asunto_clave = "actualizar tu Hogar Netflix" # Ajusta el asunto si es diferente
        logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando en {IMAP_USER} correo con asunto: '{asunto_clave}'")
        
        # Llama a buscar_ultimo_correo con las credenciales IMAP del bot
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para hogar: {error}")
            return render_template('result.html', status="error", message=error)

        link_confirmacion = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link_confirmacion:
            logging.info(f"WEB: Enlace de confirmación de Hogar encontrado: {link_confirmacion}. Intentando confirmar.")
            if confirmar_hogar_netflix(link_confirmacion):
                logging.info("WEB: Confirmación de hogar exitosa.")
                return render_template('result.html', status="success", message="🏠 Solicitud de Hogar confirmada exitosamente. Revisa tu Netflix en unos minutos.<br>Es posible que necesites reiniciar la app de Netflix en tu TV.")
            else:
                logging.error("WEB: Hubo un error al confirmar el hogar.")
                return render_template('result.html', status="error", message="❌ Se encontró el enlace de hogar, pero hubo un error al confirmarlo. Revisa los logs de Render o contacta al administrador.")
        else:
            logging.warning("WEB: No se encontró enlace de confirmación de Hogar en el correo principal.")
            return render_template('result.html', status="warning", message="❌ No se encontró ningún correo de actualización de Hogar reciente. Asegúrate de haber solicitado la actualización en tu TV o dispositivo Netflix y que el correo haya llegado a la cuenta principal.")
    else:
        logging.warning(f"WEB: Acción no válida recibida: {action}")
        return render_template('result.html', status="error", message="❌ Acción no válida. Por favor, selecciona 'Consultar Código' o 'Actualizar Hogar'.")

# =====================
# Comandos del bot de Telegram (Webhook)
# Solo si el BOT_TOKEN está inicializado
# =====================

if bot:
    @app.route(f"/{BOT_TOKEN}", methods=["POST"])
    def recibir_update():
        """
        Ruta para recibir actualizaciones del webhook de Telegram.
        """
        if request.headers.get('content-type') == 'application/json':
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
            return "", 200 # Respuesta exitosa para Telegram
        else:
            logging.warning("TELEGRAM: Encabezado Content-Type incorrecto en la solicitud del webhook.")
            return "Bad Request", 400

    @bot.message_handler(commands=["code"])
    def manejar_code_telegram(message):
        """
        Maneja el comando /code para obtener un código de Netflix vía Telegram.
        """
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada en el servidor. Contacta al administrador.")
            return

        bot.reply_to(message, "TELEGRAM: Buscando correo de código, por favor espera unos momentos...")
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: /code tu_correo_netflix@dgplayk.com")
            return

        correo_busqueda = partes[1].lower()
        if not es_correo_autorizado(correo_busqueda):
             bot.reply_to(message, "⚠️ Correo no autorizado para esta acción.")
             return
        
        asunto_clave = "Código de acceso temporal de Netflix" # Ajusta el asunto si es diferente
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 

        if error:
            bot.reply_to(message, error)
            return

        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False) 
        if link:
            codigo_final = obtener_codigo_de_pagina(link)
            if codigo_final:
                bot.reply_to(message, f"✅ TELEGRAM: Tu código de Netflix es: `{codigo_final}`")
            else:
                bot.reply_to(message, "❌ TELEGRAM: Se encontró el enlace de código, pero no se pudo extraer el código de la página de Netflix. Es posible que el formato de la página haya cambiado o que la regex necesite ajuste.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró ningún enlace de código de Netflix en el correo. Verifica que el correo haya llegado y contenga el botón 'Obtener código'.")

    @bot.message_handler(commands=["hogar"])
    def manejar_hogar_telegram(message):
        """
        Maneja el comando /hogar para actualizar el hogar Netflix vía Telegram.
        """
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada en el servidor. Contacta al administrador.")
            return

        bot.reply_to(message, "TELEGRAM: Buscando correo de hogar, por favor espera unos momentos...")
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: /hogar tu_correo_netflix@dgplayk.com")
            return

        correo_busqueda = partes[1].lower()
        if not es_correo_autorizado(correo_busqueda):
            bot.reply_to(message, "⚠️ Correo no autorizado para esta acción.")
            return

        asunto_clave = "actualizar tu Hogar Netflix" # Ajusta el asunto si es diferente
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 

        if error:
            bot.reply_to(message, error)
            return

        link_confirmacion = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        if link_confirmacion:
            if confirmar_hogar_netflix(link_confirmacion):
                bot.reply_to(message, "🏠 TELEGRAM: Solicitud de hogar enviada/confirmada exitosamente. Revisa tu Netflix.")
            else:
                bot.reply_to(message, "❌ TELEGRAM: Se encontró el enlace de hogar, pero hubo un error al confirmarlo. Revisa los logs de Render.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró ningún enlace de confirmación de hogar en el correo. Verifica que el correo haya llegado y contenga el botón 'Sí, la envié yo'.")

    @bot.message_handler(commands=["cuentas"])
    def mostrar_correos_telegram(message):
        """
        Maneja el comando /cuentas para mostrar los correos autorizados.
        """
        todos = []
        user_id = str(message.from_user.id)
        if user_id in cuentas and isinstance(cuentas[user_id], list):
            for entrada in cuentas[user_id]:
                correo = entrada.split("|")[0] if "|" in entrada else entrada
                todos.append(correo)

        texto = "📋 Correos registrados para tu ID:\n" + "\n".join(sorted(list(set(todos)))) if todos else "⚠️ No hay correos registrados para tu ID."
        bot.reply_to(message, texto)

else: # Si no hay BOT_TOKEN, la ruta del webhook debe devolver 200 OK para evitar errores de Render.
    @app.route(f"/{os.getenv('BOT_TOKEN', 'dummy_token')}", methods=["POST"])
    def dummy_webhook_route():
        logging.warning("Webhook de Telegram llamado, pero BOT_TOKEN no está configurado. Ignorando.")
        return "", 200

# =====================
# Inicio de la aplicación Flask
# =====================

if __name__ == "__main__":
    mantener_vivo() # Para asegurar que Render mantenga la app viva
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Iniciando Flask app en el puerto {port}")
    # Render se encarga de usar un servidor WSGI como Gunicorn en producción,
    # así que app.run() aquí es principalmente para desarrollo local.
    app.run(host="0.0.0.0", port=port)