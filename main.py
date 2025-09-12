import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
# No importaremos 'keep_alive' para evitar problemas de reinicio
# Importar funciones necesarias desde funciones.py
from funciones import buscar_ultimo_correo, extraer_link_con_token_o_confirmacion, obtener_codigo_de_pagina, obtener_enlace_confirmacion_final_hogar, navegar_y_extraer_universal
import telebot # Importamos telebot para la funcionalidad del bot

# Configurar logging para ver mensajes en los logs de Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar cuentas desde archivo (solo para validación de correos de usuario autorizados)
try:
    with open("cuentas.json", "r") as file:
        cuentas = json.load(file)
    logging.info("Cuentas cargadas exitosamente desde cuentas.json")
except FileNotFoundError:
    logging.error("❌ Error: cuentas.json no encontrado. La validación de correo no funcionará.")
    cuentas = {}
except json.JSONDecodeError:
    logging.error("❌ Error: Formato JSON inválido en cuentas.json. La validación de correo podría ser inconsistente.")
    cuentas = {}

# Obtener credenciales IMAP y el token del bot desde las variables de entorno de Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
IMAP_USER = os.getenv("E-MAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")

if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN no está definido en las variables de entorno de Render.")
if not IMAP_USER or not IMAP_PASS:
    logging.error("❌ E-MAIL_USER o EMAIL_PASS no están definidos en las variables de entorno de Render.")
if not ADMIN_TELEGRAM_ID:
    logging.warning("⚠️ ADMIN_TELEGRAM_ID no está definido. No se enviarán notificaciones.")

# Inicializar Flask
app = Flask(__name__)

# Inicializar Telebot solo si el token está presente
if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram inicializado.")
else:
    bot = None

# =====================
# Funciones auxiliares para la web y el bot de Telegram
# =====================

def es_correo_autorizado(correo_usuario, plataforma_requerida):
    """
    Verifica si el correo de usuario pertenece a una de las cuentas autorizadas y a la plataforma correcta.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados.")
        return False
    for correos_list in cuentas.values():
        for entrada in correos_list:
            partes = entrada.split("|")
            correo_en_lista = partes[0].lower()
            etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
            
            if correo_en_lista == correo_usuario.lower() and etiqueta_plataforma == plataforma_requerida.lower():
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
    action = request.form.get('action')

    if not user_email_input:
        logging.warning("WEB: Solicitud sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    if not es_correo_autorizado(user_email_input, "netflix"):
        logging.warning(f"WEB: Intento de correo no autorizado para Netflix: {user_email_input}")
        return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Netflix. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")

    if not IMAP_USER or not IMAP_PASS:
        logging.error("WEB: E-MAIL_USER o EMAIL_PASS no definidos. La funcionalidad de lectura de correos no es válida.")
        return render_template('result.html', status="error", message="❌ Error interno del servidor: La configuración de lectura de correos no es válida. Contacta al administrador del servicio.")

    if action == 'code':
        asunto_clave = "Código de acceso temporal de Netflix"
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
                logging.warning("WEB: No se pudo extraer el código de la página de Netflix.")
                return render_template('result.html', status="warning", message="No se pudo obtener el código activo para esta cuenta.")
        else:
            logging.warning("WEB: No se encontró enlace de código de Netflix en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")

    elif action == 'hogar':
        asunto_parte_clave = "Importante: Cómo actualizar tu Hogar con Netflix"
        logging.info(f"WEB: Solicitud de hogar para {user_email_input}. Buscando en {IMAP_USER} correo que contenga: '{asunto_parte_clave}'")
        
        html_correo, error = buscar_ultimo_correo(IMAP_USER, IMAP_PASS, asunto_parte_clave)
        
        if error:
            logging.error(f"WEB: Error al buscar correo para hogar: {error}")
            return render_template('result.html', status="error", message=error)

        link_boton_rojo = extraer_link_con_token_o_confirmacion(html_correo, es_hogar=True)
        
        if link_boton_rojo:
            logging.info(f"WEB: Enlace del botón rojo 'Sí, la envié yo' encontrado: {link_boton_rojo}. Intentando obtener enlace final de confirmación...")
            
            enlace_final_confirmacion = obtener_enlace_confirmacion_final_hogar(link_boton_rojo)

            if enlace_final_confirmacion:
                mensaje_web = f"✅ Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace para confirmar la actualización:<br><br><strong><a href='{enlace_final_confirmacion}' target='_blank'>{enlace_final_confirmacion}</a></strong><br><br>⚠️ Este enlace vence muy rápido. Si ya lo has usado o ha pasado mucho tiempo, es posible que debas solicitar una nueva actualización en tu TV."
                
                if bot and ADMIN_TELEGRAM_ID:
                    mensaje_telegram_admin = f"🚨 NOTIFICACIÓN DE HOGAR NETFLIX (WEB) 🚨\n\nEl usuario **{user_email_input}** ha solicitado actualizar el Hogar Netflix.\n\nEl enlace también se mostró en la web. Si el usuario no puede acceder, **HAZ CLIC INMEDIATAMENTE AQUÍ**:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                    try:
                        bot.send_message(ADMIN_TELEGRAM_ID, mensaje_telegram_admin, parse_mode='Markdown')
                        logging.info("WEB: Enlace de hogar final enviado al admin por Telegram.")
                    except Exception as e:
                        logging.error(f"WEB: Error al enviar notificación ADICIONAL por Telegram: {e}")
                
                return render_template('result.html', status="success", message=mensaje_web)
            else:
                logging.warning("WEB: No se pudo extraer el enlace de confirmación final.")
                return render_template('result.html', status="warning", message="❌ No se pudo obtener el enlace de confirmación final. El formato de la página de Netflix puede haber cambiado. Contacta al administrador si persiste.")
        else:
            logging.warning("WEB: No se encontró el enlace del botón 'Sí, la envié yo' en el correo principal.")
            return render_template('result.html', status="warning", message="No se encontró ninguna solicitud pendiente para esta cuenta.")
    else:
        logging.warning(f"WEB: Acción no válida recibida: {action}")
        return render_template('result.html', status="error", message="❌ Acción no válida.")

@app.route('/universal_code', methods=['POST'])
def consultar_universal_web():
    user_email_input = request.form.get('email', '').strip()
    
    if not user_email_input:
        logging.warning("WEB: Solicitud de Universal sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    if not es_correo_autorizado(user_email_input, "universal"):
        logging.warning(f"WEB: Intento de correo no autorizado para Universal: {user_email_input}")
        return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Universal. Por favor, usa un correo registrado.")

    if not IMAP_USER or not IMAP_PASS:
        logging.error("WEB: E-MAIL_USER o EMAIL_PASS no definidos.")
        return render_template('result.html', status="error", message="❌ Error interno del servidor.")

    codigo_universal, error = navegar_y_extraer_universal(IMAP_USER, IMAP_PASS)
    
    if error:
        logging.error(f"WEB: Error al obtener código de Universal: {error}")
        return render_template('result.html', status="error", message=error)
    
    if codigo_universal:
        logging.info(f"WEB: Código de Universal+ obtenido: {codigo_universal}")
        return render_template('result.html', status="success", message=f"✅ Tu código de Universal+ es: <strong>{codigo_universal}</strong>.<br>Úsalo en la página de activación.")
    else:
        logging.warning("WEB: No se pudo obtener el código de Universal+.")
        return render_template('result.html', status="warning", message="❌ No se pudo encontrar un código de Universal+ reciente. Asegúrate de haberlo solicitado y que el correo haya llegado.")

if BOT_TOKEN:
    bot = telebot.TeleBot(BOT_TOKEN)
    logging.info("Bot de Telegram inicializado.")
    
    @app.route(f"/{BOT_TOKEN}", methods=["POST"])
    def recibir_update():
        if request.headers.get('content-type') == 'application/json':
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
            return "", 200
        else:
            logging.warning("TELEGRAM: Encabezado Content-Type incorrecto en la solicitud.")
            return "Bad Request", 400

    @bot.message_handler(commands=["code"])
    def manejar_code_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada.")
            return

        bot.reply_to(message, "TELEGRAM: Buscando correo, espera...")
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: /code tu_correo_netflix@dgplayk.com")
            return

        correo_busqueda = partes[1].lower()
        if not es_correo_autorizado(correo_busqueda, "netflix"):
             bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
             return
        
        asunto_clave = "Código de acceso temporal de Netflix"
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
                bot.reply_to(message, "❌ TELEGRAM: No se pudo obtener el código activo.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró solicitud pendiente.")

    @bot.message_handler(commands=["hogar"])
    def manejar_hogar_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada.")
            return

        bot.reply_to(message, "TELEGRAM: Buscando correo de hogar, espera...")
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: /hogar tu_correo_netflix@dgplayk.com")
            return

        correo_busqueda = partes[1].lower()
        if not es_correo_autorizado(correo_busqueda, "netflix"):
            bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
            return

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
                mensaje_telegram_usuario = f"🏠 Solicitud de Hogar procesada. Por favor, **HAZ CLIC INMEDIATAMENTE** en este enlace:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                if ADMIN_TELEGRAM_ID and str(message.from_user.id) != ADMIN_TELEGRAM_ID:
                    mensaje_telegram_admin = f"🚨 NOTIFICACIÓN DE HOGAR NETFLIX (TELEGRAM) 🚨\n\nEl usuario **{correo_busqueda}** ha solicitado actualizar el Hogar Netflix.\n\nEl enlace también se mostró al usuario. Si el usuario no puede acceder, **HAZ CLIC INMEDIATAMENTE AQUÍ**:\n{enlace_final_confirmacion}\n\n⚠️ Este enlace vence muy rápido."
                    try:
                        bot.send_message(ADMIN_TELEGRAM_ID, mensaje_telegram_admin, parse_mode='Markdown')
                        logging.info("TELEGRAM: Enlace de hogar final enviado al admin por Telegram.")
                    except Exception as e:
                        logging.error(f"TELEGRAM: Error al enviar notificación ADICIONAL por Telegram: {e}")
                
                bot.reply_to(message, mensaje_telegram_usuario, parse_mode='Markdown')
            else:
                logging.warning("TELEGRAM: No se pudo extraer el enlace de confirmación final.")
                bot.reply_to(message, "❌ TELEGRAM: No se pudo obtener el enlace de confirmación final.")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se encontró solicitud pendiente.")
            
    @bot.message_handler(commands=["universal"])
    def manejar_universal_telegram(message):
        if not IMAP_USER or not IMAP_PASS:
            bot.reply_to(message, "❌ Error: La lectura de correos no está configurada.")
            return

        bot.reply_to(message, "TELEGRAM: Buscando correo de Universal+, espera...")
        partes = message.text.split()
        if len(partes) != 2:
            bot.reply_to(message, "❌ Uso: /universal tu_correo_universal@dgplays.com")
            return

        correo_busqueda = partes[1].lower()
        if not es_correo_autorizado(correo_busqueda, "universal"):
             bot.reply_to(message, "⚠️ Correo no autorizado o no asignado para esta plataforma.")
             return
        
        codigo_universal, error = navegar_y_extraer_universal(IMAP_USER, IMAP_PASS)
        
        if error:
            bot.reply_to(message, error)
            return
        
        if codigo_universal:
            bot.reply_to(message, f"✅ TELEGRAM: Tu código de Universal+ es: `{codigo_universal}`")
        else:
            bot.reply_to(message, "❌ TELEGRAM: No se pudo encontrar un código de Universal+ reciente.")

    @bot.message_handler(commands=["cuentas"])
    def mostrar_correos_telegram(message):
        todos = []
        user_id = str(message.from_user.id)
        if user_id in cuentas and isinstance(cuentas[user_id], list):
            for entrada in cuentas[user_id]:
                correo = entrada.split("|")[0] if "|" in entrada else entrada
                todos.append(correo)

        texto = "📋 Correos registrados para tu ID:\n" + "\n".join(sorted(list(set(todos)))) if todos else "⚠️ No hay correos registrados para tu ID."
        bot.reply_to(message, texto)

else:
    @app.route(f"/{os.getenv('BOT_TOKEN', 'dummy_token')}", methods=["POST"])
    def dummy_webhook_route():
        logging.warning("Webhook de Telegram llamado, pero BOT_TOKEN no está configurado.")
        return "", 200

# =====================
# Inicio de la aplicación Flask
# =====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Iniciando Flask app en el puerto {port}")
    app.run(host="0.0.0.0", port=port)
