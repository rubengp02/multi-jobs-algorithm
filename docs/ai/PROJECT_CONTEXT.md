# Project Context

## Propósito
`bot_multi_jobs` es un bot en Python para la monitorización automatizada de ofertas de empleo en múltiples plataformas (LinkedIn, Indeed, InfoJobs) con notificaciones a través de Telegram y control de deduplicación y filtros de palabras clave. Diseñado para ejecutarse en entornos Linux (p. ej. Raspberry Pi 5, Oracle Cloud) o localmente en Windows.

## Stack Tecnológico
- **Lenguaje:** Python 3.10+
- **Automatización / Scraping:** Playwright (Chromium sync), Requests, BeautifulSoup4
- **Configuración & Env:** `python-dotenv` (`.env`)
- **Notificaciones:** API Bot de Telegram (vía requests / bot polling)
- **Extensión auxiliar:** JavaScript / extensión Chromium (Manifest v3) + receptor HTTP local alojado por `main.py` (`extension_bridge.py`)

## Estructura Principal
```text
bot_multi_jobs/
├── main.py                   # Loop principal de polling, orquestación y comandos Telegram
├── config.py                 # Configuración tipada (BotConfig) leída de .env
├── notifier.py               # Envío de notificaciones y recepción de comandos vía Telegram
├── storage.py                # Persistencia de IDs vistos (seen_jobs.txt)
├── extension_bridge.py       # Receptor HTTP local, iniciado dentro de main.py en modo extensión
├── requirements.txt          # Dependencias core de Python
├── .env / .env.example       # Variables de entorno y credenciales
├── providers/                # Módulos de extracción por plataforma
│   ├── base.py               # Protocolo base JobProvider y dataclass JobItem
│   ├── linkedin.py           # Extracción directa opcional de LinkedIn (Playwright)
│   ├── indeed.py             # Extracción de Indeed (HTML / Playwright)
│   └── infojobs.py           # Extracción de InfoJobs (Playwright / cookies / paginación)
├── extension/                # Extensión de Chrome para captura pasiva en navegador
└── data/                     # Sesiones de navegador, métricas y estado
    ├── seen_jobs.txt         # Historial de ofertas notificadas/vistas (source:id)
    ├── runtime_filters.json  # Filtros dinámicos de exclusión
    └── provider_metrics.csv  # Registro de rendimiento y métricas de scraping
```

## Comandos Esenciales
- **Instalación:**
  ```bash
  pip install -r requirements.txt
  python -m playwright install chromium
  ```
- **Ejecutar bot principal:**
  ```bash
  python main.py
  ```
- **Modo Raspberry con extensión:** activa `LINKEDIN_EXTENSION_ENABLED=true`, inicia
  `main.py` normalmente y arranca el perfil dedicado con
  `scripts/raspberry/start_linkedin_chromium.sh`. No se ejecuta
  `extension_bridge.py` por separado.
- **Prueba manual de login/sesión:**
  ```bash
  python login_manual.py
  python infojobs_manual_check.py
  ```

## Restricciones y Convenciones
- No subir ni versionar tokens de Telegram, contraseñas o cookies en archivos de código (`.env` local).
- Las sesiones de Playwright se almacenan en `data/*_session` para evitar logins repetitivos.
- Formato único de clave en almacenamiento: `{source}:{job_id}`.
- Manejo defensivo: si un proveedor falla o no tiene URL configurada, se registra el fallo sin detener el ciclo global.
