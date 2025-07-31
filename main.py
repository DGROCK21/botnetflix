import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from keep_alive import mantener_vivo
# Importar funciones necesarias desde funciones.py
# Asegúrate de que estas funciones solo usen los parámetros que les pasas
from funciones import buscar_ultimo_correo, extraer_link_con_token_o_confirmacion, obtener_codigo_de_pagina, obtener_enlace_confirmacion_final_hogar 
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
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID") # Asegúrate de definir esta variable en Render con tu ID de Telegram

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido en las variables de entorno de Render. La funcionalidad de Telegram NO ESTARÁ DISPONIBLE.")
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos en las variables de entorno de Render. La funcionalidad de lectura de correos NO ESTARÁ DISPONIBLE.")
    # Si estas no están, el bot no podrá conectarse a Gmail, lo que es crítico.
if not ADMIN_TELEGRAM_ID:
    logging.warning("⚠️ ADMIN_TELEGRAM_ID no está definido. No se enviarán notificaciones al administrador.")


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
        asunto_clave = "Código de acceso temporal de Netflix" # Asunto para códigos
        logging.info(f"WEB: Solicitud de código para {user_email_input}. Buscando en {IMAP_USER} correo con asunto: '{asunto_clave}'")
        
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para código: {error}")
            return render_template('result.html', status="error", message=error)

        link = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=False) 
        if link:
            codigo_final = obtener_codigo_de_pagina(link)
            if codigo_final:
                logging.info(f"WEB: Código obtenido: {codigo_final}")
                return render_template('result.html', status="success", message=f"✅ Tu código de Netflix es: <strong>{codigo_final}</strong>.<br>Úsalo en tu TV o dispositivo.")
            else:
                logging.warning("WEB: Se encontró el enlace de código, pero no se pudo extraer el código de la página de Netflix.")
                return render_template('result.html', status="warning", message="No se pudo obtener el código activo para esta cuenta.")
        else:
            logging.warning("WEB: No se encontró enlace de código de Netflix en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

    elif action == 'hogar':
        # ASUNTO FLEXIBLE Y ACTUALIZADO: Buscamos una parte constante del asunto para "Actualizar Hogar"
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix" 
        logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando en {IMAP_USER} correo que contenga: '{asunto_parte_clave}'")
        
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave) 
        
        if error:
            logging.error(f"WEB: Error al buscar correo para hogar: {error}")
            return render_template('result.html', status="error", message=error)

        # Primero extraemos el enlace del botón rojo "Sí, la envié yo" del correo inicial
        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        
        if link_boton_rojo:
            logging.info(f"WEB: Enlace del botón rojo 'Sí, la envié yo' encontrado: {link_boton_rojo}. Intentando obtener enlace final de confirmación...")
            
            # NUEVA LLAMADA: Visitamos el enlace del botón rojo y extraemos el enlace del botón negro "Confirmar actualización"
            enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link_boton_rojo)

            if enlace_final_confirmacion:
                # *** CAMBIO CLAVE AQUÍ: MUESTRA EL ENLACE DIRECTAMENTE EN LA WEB ***
                mensaje_web = f"✅ Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace para confirmar la actualización:<br><br><strong><a href='{enlace_final_confirmacion}' target='_blank'>{enlace_final_confirmacion}</a></strong><br><br>⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                
                # Opcional: También enviamos a Telegram como backup o notificación extra
                if bot and ADMIN_TELEGRAM_ID:
                    mensaje_telegram_admin = f"🚨 NOTIFICACIÓN DE HOGAR NETFLIX (WEB) 🚨\n\nEl usuario **{user_email_input}** ha solicitado actualizar el Hogar Netflix.\n\nEl enlace también se mostró en la web. Si el usuario no puede acceder, **HAZ CLIC INMEDIATAMENTE AQUÍ**:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                    try:
                        bot.send_message(ADMIN_TELEGRAM_ID, mensaje_telegram_admin, parse_mode='Markdown')
                        logging.info(f"WEB: Enlace de hogar final enviado al admin por Telegram (adicional) para {user_email_input}.")
                    except Exception as e:
                        logging.error(f"WEB: Error al enviar notificación ADICIONAL por Telegram: {e}")
                
                return render_template('result.html', status="success", message=mensaje_web)

            else:
                logging.warning("WEB: No se pudo extraer el enlace de confirmación final del botón negro.")
                return render_template('result.html', status="warning", message="❌ No se pudo obtener el enlace de confirmación final. El formato de la página de Netflix puede haber cambiado. Contacta al administrador si persiste.")
        else:
            logging.warning("WEB: No se encontró el enlace del botón 'Sí, la envié yo' en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")
    else:
        logging.warning(f"WEB: Acción no válida recibida: {action}")
        return render_template('result.html', status="error", message="❌ Acción no válida. Por favor, selecciona 'Consultar Código' o 'Actualizar Hogar'.")

# =====================
# Comandos del bot de Telegram (Webhook)
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
        
        asunto_clave = "Código de acceso temporal de Netflix" # Asunto para códigos
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
                bot.reply_to(message, "❌ TELEGRAM: No se pudo obtener el código activo para esta cuenta.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró ninguna solicitud pendiente para esta cuenta.")

    @bot.message_handler(commands=["hogar"])
    def manejar_hogar_telegram(message):
        """
        Maneja el comando /hogar para notificar al administrador con el enlace de confirmación.
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

        # ASUNTO FLEXIBLE Y ACTUALIZADO: Buscamos una parte constante del asunto para "Actualizar Hogar"
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix" 
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave) 

        if error:
            bot.reply_to(message, error)
            return

        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        
        if link_boton_rojo:
            logging.info(f"TELEGRAM: Enlace del botón rojo 'Sí, la envié yo' encontrado: {link_boton_rojo}. Intentando obtener enlace final de confirmación...")
            
            enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link_boton_rojo)

            if enlace_final_confirmacion:
                # *** CAMBIO CLAVE AQUÍ: EN EL COMANDO TELEGRAM, MUESTRA EL ENLACE DIRECTAMENTE EN EL CHAT ***
                mensaje_telegram_usuario = f"🏠 Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace para confirmar la actualización:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                
                # Opcional: También enviamos a Telegram del admin como backup o notificación extra (si es diferente al usuario que inició el comando)
                # Si el usuario que usa el comando /hogar es el ADMIN_TELEGRAM_ID, no hace falta enviar dos veces.
                # Considerar si quieres que el ADMIN_TELEGRAM_ID sea diferente al ID de los usuarios autorizados.
                if ADMIN_TELEGRAM_ID and str(message.from_user.id) != ADMIN_TELEGRAM_ID:
                    mensaje_telegram_admin = f"🚨 NOTIFICACIÓN DE HOGAR NETFLIX (TELEGRAM) 🚨\n\nEl usuario **{correo_busqueda}** ha solicitado actualizar el Hogar Netflix.\n\nEl enlace también se mostró al usuario. Si el usuario no puede acceder, **HAZ CLIC INMEDIATAMENTE AQUÍ**:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                    try:
                        bot.send_message(ADMIN_TELEGRAM_ID, mensaje_telegram_admin, parse_mode='Markdown')
                        logging.info(f"TELEGRAM: Enlace de hogar final enviado al admin por Telegram (adicional) para {correo_busqueda}.")
                    except Exception as e:
                        logging.error(f"TELEGRAM: Error al enviar notificación ADICIONAL por Telegram: {e}")
                
                bot.reply_to(message, mensaje_telegram_usuario, parse_mode='Markdown')

            else:
                logging.warning("TELEGRAM: No se pudo extraer el enlace de confirmación final del botón negro.")
                bot.reply_to(message, "❌ TELEGRAM: No se pudo obtener el enlace de confirmación final. El formato de la página puede haber cambiado.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró ninguna solicitud pendiente para esta cuenta.")

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
    app.run(host="0.0.0.0", port=port)