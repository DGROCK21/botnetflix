from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    # Este es el endpoint que tu bot de ping llamará.
    # No tiene que hacer nada más allá de devolver 200 OK.
    return "Bot y Web activos", 200

def run():
    # Aquí se usa el puerto por defecto de Flask, pero Render redirigirá a 80
    app.run(host='0.0.0.0', port=8080)

def mantener_vivo():
    t = Thread(target=run)
    t.start()