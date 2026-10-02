<div align="center">
  <img src="https://img.icons8.com/color/96/000000/bot.png" alt="Bot Logo"/>
  <h1>Multi-Jobs Algorithm & Autonomous Scraper</h1>
  <p><strong>Un orquestador asíncrono avanzado para la búsqueda de empleo automatizada e inteligente.</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/asyncio-Enabled-success.svg" alt="Asyncio" />
    <img src="https://img.shields.io/badge/Playwright-Stealth-orange.svg" alt="Playwright" />
    <img src="https://img.shields.io/badge/SQLite-Persistence-lightgrey.svg" alt="SQLite" />
    <img src="https://img.shields.io/badge/Telegram-Bot-blue.svg" alt="Telegram Bot" />
  </p>
</div>

<hr/>

Este repositorio alberga un **orquestador de scraping asíncrono y motor de emparejamiento (Match Engine)** diseñado para monitorear múltiples plataformas de empleo (LinkedIn, InfoJobs, Manfred, Indeed, Remotive, Tecnoempleo, WWR, etc.) de manera continua y desatendida, evadiendo sistemas antibot y evaluando las posiciones bajo reglas de negocio complejas antes de notificar por Telegram.

Desarrollado con una arquitectura **100% asíncrona** (`asyncio`), orientada a micro-proveedores y diseñada para operar 24/7 en un servidor Linux (Raspberry Pi 5).

## 🚀 Características Principales

*   ⚡ **Arquitectura Asíncrona Total:** Core construido sobre `asyncio` y `httpx`. Múltiples proveedores se ejecutan sin bloquear el hilo principal, reduciendo dramáticamente el consumo de red y CPU.
*   🛡️ **Evasión Antibot Avanzada:** 
    *   Integración con `Playwright Async` para resolución dinámica de JavaScript.
    *   Impersonación TLS nativa (vía `curl_cffi`) para enmascaramiento de huella digital (bypass de Cloudflare).
    *   Perfiles de navegador persistentes y gestión inteligente de cookies/sesiones (Tactical Retreats).
*   🧠 **Motor de Match Inteligente (`matcher.py`):** 
    *   Evaluación de relevancia (Machine Learning / IA / Data / Python).
    *   Filtros geográficos de alta precisión.
    *   Extracción paramétrica de Stack Tecnológico.
    *   Cálculo algorítmico de adecuación de banda salarial.
*   💾 **Persistencia Robusta (`aiosqlite`):** Migración completa a bases de datos relacionales locales para mantener historiales, análisis de métricas y evitar notificaciones duplicadas (*deduplicación*).
*   📱 **Interfaz Telegram Nativa:** Respuestas a comandos (`/status`, `/start`, `/logs`, `/revisar`) procesados concurrentemente gracias a `aiogram`, permitiendo pausar alertas o recibir métricas en tiempo real.

## 🏗️ Arquitectura de Software

El proyecto sigue patrones de diseño modernos, separando responsabilidades para garantizar la escalabilidad:

```text
multi-jobs-algorithm/
├── main.py                  # Orquestador asíncrono y bucle de eventos principal (Aiogram)
├── database.py              # Capa DAO asíncrona (aiosqlite) para telemetría y jobs vistos
├── matcher.py               # Lógica de emparejamiento, parsing salarial y reglas de negocio
├── models.py                # Definición estricta de estructuras de datos (Dataclasses / Protocols)
├── config.py                # Inyección de dependencias ambientales (.env)
├── utils_stealth.py         # Módulo de rotación de headers y mitigación de baneos
└── providers/               # Directorio de micro-proveedores (Plugins)
    ├── base.py
    ├── linkedin.py          # Extracción híbrida (API + Web)
    ├── infojobs.py          # Resolución con impersonación TLS
    ├── manfred.py           # Parsing de sitemaps XML y deducción de slugs
    └── ... (15+ fuentes adicionales)
```


## 🧠 Decisiones de Arquitectura (Design Document)

Durante el diseño de este orquestador, tomé varias decisiones arquitectónicas críticas para asegurar la escalabilidad, resiliencia y bajo consumo del sistema, pensando siempre en su despliegue continuo (24/7) en hardware limitado como una Raspberry Pi 5.

### 1. Asincronía Total (Event Loop vs. Threads)
* **Decisión:** Migrar todo el ecosistema (desde las peticiones HTTP hasta las consultas a la base de datos y la interfaz de Telegram) a un único bucle de eventos (`asyncio`).
* **Por qué:** Escanear más de 15 portales de empleo de forma secuencial tardaba demasiado, y usar multi-threading clásico disparaba el consumo de memoria RAM y CPU en la Raspberry Pi. Con `asyncio`, el bot de Telegram (Aiogram) jamás se bloquea mientras se esperan respuestas de red, logrando una concurrencia real y extremadamente eficiente.

### 2. Patrón de Micro-Proveedores (Plugins)
* **Decisión:** Desacoplar el orquestador central (`main.py`) de la lógica de *scraping* específica de cada portal. Todos los portales heredan de un protocolo o clase base y viven aislados en la carpeta `providers/`.
* **Por qué:** Los portales de empleo cambian su estructura HTML/API constantemente. Si un portal falla, no debe tumbar el bot entero. Este diseño "Plug & Play" me permite encender, apagar o añadir nuevas fuentes (ej. crear `providers/nuevo_portal.py`) sin tocar ni una línea del código central ni del motor de matching.

### 3. Persistencia Relacional Asíncrona (aiosqlite)
* **Decisión:** Sustituir los archivos de texto planos (`seen_jobs.txt`) por una base de datos SQLite asíncrona local (`database.py`).
* **Por qué:** A medida que el bot procesaba decenas de miles de ofertas, los volcados en archivos de texto se volvieron ineficientes y propensos a condiciones de carrera (Race Conditions). SQLite me permite deduplicar ofertas al instante, hacer análisis SQL complejos de métricas y soportar lecturas/escrituras concurrentes y seguras.

### 4. Evasión Antibot Híbrida (TLS Impersonation + Playwright)
* **Decisión:** Usar `httpx` para portales amigables, `curl_cffi` para suplantar huellas TLS, y aislar `Playwright Async` exclusivamente para Single Page Applications (SPAs) complejas.
* **Por qué:** Usar navegadores Headless (Selenium/Playwright) para todo consumiría el 100% de la RAM del servidor. Reservo Playwright solo para plataformas altamente protegidas o dependientes de JavaScript. Para contrarrestar Firewalls (como Cloudflare en InfoJobs), utilizo *TLS impersonation*, simulando el tráfico de red exacto de un navegador Chrome nativo, logrando extracciones indetectables con el coste mínimo de CPU.

### 5. Motor de Decisión Centralizado
* **Decisión:** Extraer toda la lógica de validación de salarios, detección de tecnologías, palabras clave de Inteligencia Artificial / Data y modalidades remotas a un único módulo core (`matcher.py`).
* **Por qué:** Evita la duplicación de código en los 15 proveedores. El proveedor solo se encarga de extraer la "data bruta" y normalizarla al modelo `JobItem`. El `matcher.py` aplica la capa de inteligencia de negocio, garantizando que los criterios de filtrado sean matemáticamente consistentes sin importar de dónde provenga la oferta.

## ⚙️ Instalación y Configuración

El proyecto está diseñado para desplegarse fácilmente en entornos Linux (especialmente Raspberry Pi).

### Prerrequisitos
*   **Python 3.11+**
*   Google Chrome / Chromium instalado en el sistema.

### Despliegue Local
1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/rubengp02/multi-jobs-algorithm.git
   cd multi-jobs-algorithm
   ```

2. **Crear el entorno virtual:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # En Windows: .\.venv\Scripts\activate
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Variables de Entorno:**
   Copia los archivos de ejemplo para configurar tu entorno, credenciales de Telegram y reglas de Inteligencia Artificial (Stack tecnológico, localizaciones, salarios).
   ```bash
   cp .env.example .env
   cp config/rules.example.json config/rules.json
   ```

5. **Ejecutar el orquestador:**
   ```bash
   python main.py
   ```

### Despliegue en Servidor (systemd)
Para mantener el bot vivo 24/7 en una Raspberry Pi 5 frente a reinicios y cortes de red, se incluye soporte para demonización:
```bash
sudo cp systemd/bot-multi-jobs.service /etc/systemd/system/
sudo systemctl enable bot-multi-jobs
sudo systemctl start bot-multi-jobs
```

## 📊 Telemetría y Analíticas

El sistema incorpora un pipeline de auditoría (`analytics.py`) que recolecta continuamente:
*   Frecuencia de fallos por proveedor (HTTP 403, 429).
*   Tasa de descarte y motivos algorítmicos (Salario insuficiente, Tecnología no coincidente).
*   Tiempos de latencia de carga en resoluciones de Playwright.

Esta métrica puede ser consultada en tiempo real mediante el comando `/status` desde el chat de Telegram.

## 🤝 Contribuciones y Calidad de Código
Todo el núcleo del ecosistema está fuertemente documentado (estilo **Google Docstrings**) y validado contra errores de sintaxis o *typing*. Se aceptan PRs centrados en:
*   Añadir nuevos proveedores al directorio `providers/`.
*   Optimizar los heurísticos de extracción salarial en `matcher.py`.

## 📝 Licencia / Disclaimer
Este proyecto fue creado con un propósito estrictamente educativo y personal. Su uso en entornos de producción masiva puede contravenir los Términos de Servicio de las plataformas de empleo involucradas. Úsese con responsabilidad y siempre respetando el `robots.txt` y los límites de tráfico razonables.
