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