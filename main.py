import os
import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from keep_alive import mantener_vivo
# Importar funciones necesarias desde funciones.py
# Se ha añadido la nueva función de Universal
from funciones import buscar_ultimo_correo, extraer_link_con_token_o_confirmacion, obtener_codigo_de_pagina, obtener_enlace_confirmacion_final_hogar, navegar_y_extraer_universal
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

def es_correo_autorizado(correo_usuario, plataforma_requerida):
    """
    Verifica si el correo de usuario pertenece a una de las cuentas autorizadas y a la plataforma correcta.
    """
    if not cuentas:
        logging.warning("No hay cuentas cargadas para validación. Todos los correos serán rechazados.")
        return False

    # Itera sobre los valores del diccionario (las listas de correos)
    for correos_list in cuentas.values():
        for entrada in correos_list:
            partes = entrada.split("|")
            correo_en_lista = partes[0].lower()
            etiqueta_plataforma = partes[1].lower() if len(partes) > 1 else "ninguna"
            
            # Compara el correo y la etiqueta de la plataforma
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
    action = request.form.get('action') # Esto viene del atributo 'name' y 'value' de los botones submit

    if not user_email_input:
        logging.warning("WEB: Solicitud sin correo electrónico.")
        return render_template('result.html', status="error", message="❌ Por favor, ingresa tu correo electrónico.")

    # Usamos la nueva función para verificar el correo y la plataforma
    if not es_correo_autorizado(user_email_input, "netflix"):
        logging.warning(f"WEB: Intento de correo no autorizado para Netflix: {user_email_input}")
        return render_template('result.html', status="error", message="⚠️ Correo no autorizado para Netflix. Por favor, usa un correo registrado en la cuenta @dgplayk.com.")

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
# RUTA NUEVA PARA UNIVERSAL+
# =====================

# --- Función corregida para extraer el código de Universal+ ---

def extraer_codigo_universal(html_content):
    """
    Extrae el código de 6 dígitos del correo de activación de Universal+.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Buscamos un div que contenga el código. El código de Universal+ suele ser de 6 caracteres (letras y números).
    # Vamos a buscar un div con un font-size grande, o que contenga el texto "Ingresa el código"
    # Un patrón común es una celda con un estilo de font-size grande y centrado.
    codigo_div = soup.find('div', style=lambda value: value and 'font-size: 32px' in value and 'font-weight: 700' in value)
    
    if codigo_div:
        codigo = codigo_div.text.strip()
        # Verificamos si el código tiene 6 caracteres y es alfanumérico
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado: {codigo}")
            return codigo
    
    # Fallback: Si no lo encontramos en la etiqueta div, buscamos el código con una expresión regular más amplia
    match = re.search(r'[\s](([A-Z0-9]{6}))[\s]', html_content)
    if match:
        codigo = match.group(1).strip()
        if re.fullmatch(r'[A-Z0-9]{6}', codigo):
            logging.info(f"Código de Universal+ encontrado (regex): {codigo}")
            return codigo

    logging.warning("No se pudo encontrar el código de Universal+ en el correo.")
    return None