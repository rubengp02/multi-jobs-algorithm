# Usamos la imagen oficial de Playwright que ya incluye todas las dependencias
# de sistema operativo (libs de WebKit, Chromium, etc) necesarias para funcionar.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Establecer variables de entorno para Python y Playwright
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Asegurar que los binarios de Chromium de Playwright esten actualizados para el entorno Python
RUN playwright install chromium

# Copiar el codigo fuente de la aplicacion
COPY . .

# Crear el punto de montaje persistente
VOLUME ["/app/data"]

# Comando de inicio
CMD ["python", "main.py"]
