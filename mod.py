import sys

def modify_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = [
        (
            '''def extract_salary(text: str) -> str:
    """
    Analiza el texto de la oferta y extrae el rango salarial si está publicado explícitamente.
    Normaliza y formatea el resultado a rangos anuales en euros.
    """
    """Return a conservative seniority label from explicitly stated years."""''',
            '''def extract_salary(text: str) -> str:
    """
    Analiza el texto de la oferta y extrae el rango salarial si está publicado explícitamente.
    Normaliza y formatea el resultado a rangos anuales en euros.
    
    Args:
        text (str): El texto a analizar.
        
    Returns:
        str: El rango salarial o el nivel de seniority extraído.
    """'''
        )
    ]
    
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
        elif old.replace('\n', '\r\n') in content:
            content = content.replace(old.replace('\n', '\r\n'), new.replace('\n', '\r\n'))
        else:
            print(f'Failed to find: {old[:50]}...')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

modify_file('matcher.py')
