def update_readme():
    with open('README.md', 'r', encoding='utf-8') as f:
        content = f.read()

    new_section = """
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
"""

    parts = content.split("## ⚙️ Instalación y Configuración")
    
    final_content = parts[0] + new_section + "\n## ⚙️ Instalación y Configuración" + parts[1]
    
    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(final_content)

if __name__ == '__main__':
    update_readme()
