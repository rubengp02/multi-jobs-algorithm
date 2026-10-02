# Raspberry Pi dedicada: LinkedIn con Chromium real

Este modo esta pensado para una Raspberry dedicada al bot. LinkedIn se carga
en una pestaña real de Chromium moderno en modo `--headless=new`; la extensión
envía las tarjetas al mismo proceso `main.py` que filtra, guarda
`seen_jobs.txt` y avisa por Telegram. Por eso no hay un segundo bridge ni un
segundo fichero de ofertas vistas y el ciclo no necesita que Chromium esté en
primer plano ni que haya un escritorio abierto.

No intenta automatizar el inicio de sesion de LinkedIn: se inicia una vez de
forma manual en el perfil persistente de Chromium.

## 1. Actualizar el proyecto sin sobrescribir secretos

Desde el PC, sube o sincroniza todo el proyecto, incluidos `extension/`,
`scripts/` y `deploy/`. No subas `.venv`, `data/` ni sustituyas el `.env` que
ya existe en la Raspberry. Si usas FileZilla, conserva especificamente el
`.env` remoto.

En la Raspberry:

```bash
cd ~/bot_multi_jobs
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
chmod +x scripts/raspberry/start_linkedin_chromium.sh
```

Usa una Raspberry Pi OS actual con una version de Python compatible con las
dependencias del proyecto. Si `pip` no encuentra la version de Playwright,
actualiza primero el sistema/Python; no cambies los pines de dependencias a
ciegas.

## 2. Activar el modo extension

Edita solamente estas claves en `~/bot_multi_jobs/.env`. No borres ni vuelvas a
escribir `TELEGRAM_BOT_TOKEN` ni `TELEGRAM_CHAT_ID`.

```dotenv
LINKEDIN_EXTENSION_ENABLED=true
LINKEDIN_EXTENSION_HOST=127.0.0.1
LINKEDIN_EXTENSION_PORT=8765
LINKEDIN_EXTENSION_REFRESH_SECONDS=900
# Cada URL base se consulta primero con 20 minutos y despues con una hora.
LINKEDIN_TIME_WINDOWS_SECONDS=1200,3600
# Pausa aleatoria entre consultas LinkedIn consecutivas.
LINKEDIN_INTER_SEARCH_MIN_SECONDS=3
LINKEDIN_INTER_SEARCH_MAX_SECONDS=6
```

Deja `linkedin` dentro de `ENABLED_PROVIDERS`: Chromium autenticado aporta el
inventario principal. La API pública no se consulta en lotes sanos; solo actúa como
respaldo tras dos intervalos sin un lote completo. El resto de proveedores mantiene
su flujo normal.

No hace falta duplicar las URLs de LinkedIn para estas ventanas: el bridge y el
respaldo API las expanden en el mismo orden, preservando los demas filtros de cada
URL base. Una pausa reduce las rafagas, pero LinkedIn puede seguir responder con
`429` o bloquear temporalmente una consulta.

## 3. Preparar Chromium

Instala Chromium si aun no esta disponible:

```bash
sudo apt update
sudo apt install -y chromium
```

En algunas imágenes de Raspberry Pi OS el comando es `chromium-browser`; el
script detecta ambos nombres. El servicio carga automáticamente la extensión
desde `~/bot_multi_jobs/extension`; no hace falta abrir `chrome://extensions`
ni cargarla manualmente. El perfil se guarda en
`data/linkedin_chromium_profile`, separado de cualquier Chrome personal.

El bot no automatiza el inicio de sesión. Si LinkedIn muestra un challenge o
exige iniciar sesión para una búsqueda concreta, resuélvelo manualmente en ese
perfil usando un entorno gráfico compatible; no borres el perfil porque eso
eliminaría la sesión persistente.

## 4. Arranque automatico de Chromium

Instala el servicio de usuario que abre ese mismo perfil tras cada inicio:

```bash
mkdir -p ~/.config/systemd/user
cp ~/bot_multi_jobs/deploy/raspberry/linkedin-browser.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now linkedin-browser.service
loginctl enable-linger "$USER"
```

No uses `--no-sandbox` ni indicadores de automatización. Este servicio ejecuta
Chromium como el usuario normal de la Raspberry, no expone depuración remota y
no contiene credenciales.

## 5. Reiniciar el bot y verificar el flujo completo

El bridge se inicia dentro del servicio principal. No ejecutes
`python extension_bridge.py` por separado.

```bash
systemctl --user restart linkedin-browser.service
sudo systemctl restart bot-multi-jobs.service
curl -fsS http://127.0.0.1:8765/health
journalctl -u bot-multi-jobs.service -f -o cat
```

El primer comando debe devolver JSON con `"ok": true`. En el modo dedicado la
extensión se inicia sola; espera al intervalo configurado o reinicia únicamente
el navegador para disparar un ciclo nuevo:

```bash
systemctl --user restart linkedin-browser.service
```

En el journal deben aparecer, en este orden aproximado:

```text
LinkedIn extension bridge listening on http://127.0.0.1:8765
LinkedIn dual mode enabled: Chromium is primary; public API fallback starts after two incomplete intervals.
Extension batch | run_id=... searches=4 complete=4
LinkedIn inventory audit coverage correct | run_id=...
```

Los números son un ejemplo: la extensión conserva todas las tarjetas que llegan a
estar visibles en la primera página estable; no hay límite de alertas. `saved` y `sent` pueden ser menores por filtros,
ofertas ya vistas o pausa. `/status` muestra antigüedad de extensión/API,
parcialidad, discrepancias y si el respaldo está activo. `/scan` sigue escaneando
los proveedores Python; para forzar LinkedIn usa el botón **Escanear ahora** de la
extensión.

## Diagnostico y mantenimiento

```bash
# Estado y log de Chromium dedicado (servicio del usuario)
systemctl --user status linkedin-browser.service
journalctl --user -u linkedin-browser.service -f -o cat

# Reiniciar solo Chromium si se cerro o perdio la sesion
systemctl --user restart linkedin-browser.service

# Estado del bot y sus ingresos de LinkedIn
sudo systemctl status bot-multi-jobs.service
journalctl -u bot-multi-jobs.service -f -o cat
tail -f ~/bot_multi_jobs/data/linkedin_runs.jsonl
cat ~/bot_multi_jobs/data/linkedin_inventory_audit/latest.json
```

Si la extensión no informa de actividad, comprueba primero que el servicio
principal esté activo y que `LINKEDIN_EXTENSION_PORT` siga siendo `8765`. Si
LinkedIn exige inicio de sesión o muestra un challenge, resuélvelo manualmente
en el perfil dedicado: no borres `data/linkedin_chromium_profile` porque
perderías la sesión existente.

## Auditoria operativa diaria

La auditoria diaria no realiza scraping adicional. Lee las metricas de los ciclos
normales y los informes duales de LinkedIn, sin tocar `seen_jobs.txt` ni enviar alertas
de ofertas. Genera `data/daily_coverage/YYYY-MM-DD.json` y actualiza
`data/daily_coverage/latest.json`.

Prueba manual sin Telegram antes de instalar el timer:

```bash
cd /home/[TU_USUARIO]/bots/bot_multi_jobs
./.venv/bin/python daily_coverage_audit.py --no-telegram
```

Tambien se puede solicitar desde el chat de Telegram con `/auditoria` (o
`/coverage`). Genera el mismo informe de solo lectura y no lanza proveedores ni
modifica `seen_jobs.txt`.

Instala y activa el temporizador diario:

```bash
sudo install -m 644 deploy/raspberry/bot-daily-coverage.service /etc/systemd/system/
sudo install -m 644 deploy/raspberry/bot-daily-coverage.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bot-daily-coverage.timer
systemctl list-timers --all bot-daily-coverage.timer
```

Se ejecuta cada dia a las 23:45, con hasta cinco minutos de retraso aleatorio para no
coincidir siempre con un ciclo. `Persistent=true` recupera una ejecucion perdida al
volver a arrancar la Raspberry. El resumen diario de Telegram se controla con
`DAILY_COVERAGE_TELEGRAM_SUMMARY`; deja `true` para recibir el diagnostico.

Una puntuacion alta demuestra que hay evidencia reciente y completa de los ciclos
programados. No prueba que los portales hayan mostrado todas las vacantes existentes;
para eso se mantiene la validacion independiente de proveedores.

Cada ciclo normal tambien deja un lote compacto en `data/job_audit/`: para cada
tarjeta recibida guarda solo un hash estable y el resultado terminal (enviada, vista,
descartada, pausada, limitada o fallo de entrega). La auditoria reconcilia esos lotes
con las metricas por proveedor. Si falta un lote esperado o queda una tarjeta sin
resultado terminal, el proveedor pasa a critico. Esta comprobacion cubre todo lo que
entro en el pipeline, pero no puede probar que un portal no ocultara una vacante antes
de que el bot la recibiera.

La limpieza diaria conserva un historial finito: ledger por oferta 35 dias, metricas
90 dias, informes diarios 90 dias y validaciones 180 dias. Los valores se pueden
ajustar con `JOB_AUDIT_RETENTION_DAYS`, `OPERATIONAL_METRICS_RETENTION_DAYS`,
`DAILY_COVERAGE_RETENTION_DAYS` y `PROVIDER_VALIDATION_RETENTION_DAYS`. Nunca borra
`data/seen_jobs.txt`.

Los perfiles del navegador conservan cookies, almacenamiento local y sesiones. Al
iniciar el bot se eliminan unicamente sus caches regenerables y las copias de sesion
con mas de 14 dias; el arranque de Chromium aplica la misma regla a su perfil y borra
copias antiguas de la extension. Los limites se ajustan con
`BROWSER_SESSION_BACKUP_RETENTION_DAYS` y
`BROWSER_EXTENSION_RUNTIME_RETENTION_DAYS`. Para una limpieza manual segura, con el
bot y Chromium detenidos, usa:

```bash
./.venv/bin/python browser_profile_cleanup.py \
  --data-dir data \
  --profile data/linkedin_session \
  --profile data/infojobs_session \
  --profile data/indeed_session
```

## Consultoras publicas: auditoria y activacion manual

Las 28 consultoras del registro permanecen desactivadas hasta que su auditoria
publique el estado `validated`. La auditoria compara el extractor con un
navegador independiente en las tarjetas publicas visibles; no envia Telegram,
no modifica `data/seen_jobs.txt` y no guarda HTML ni credenciales.

```bash
cd ~/bot_multi_jobs
./.venv/bin/python provider_validation.py --provider bo_growth
./.venv/bin/python provider_validation.py --provider all
```

Los informes estan en `data/provider_validation/runs/` y el estado actual en
`data/provider_validation/status.json`. Revisa el ultimo informe antes de cada
activacion: debe ser `validated` y no contener `eligible_missing`. Solo entonces
anade el identificador concreto a `ENABLED_PROVIDERS` en `.env`; por ejemplo:

```dotenv
ENABLED_PROVIDERS=linkedin,bo_growth
```

El ciclo ordinario consulta las consultoras activadas cada 15 minutos, una por
una, esperando aleatoriamente 3--6 segundos entre portales y hasta dos paginas
o 50 ofertas por fuente. Tras cambiar `.env`, aplica la configuracion con:

```bash
sudo systemctl restart bot-multi-jobs.service
```

Los estados `pending_validation`, `degraded` y `blocked` se mantienen fuera del
ciclo normal. Si una fuente previamente correcta recibe 403/429, un challenge,
cero resultados o una caida fuerte de volumen, el bot deja la metrica y lanza
una revalidacion aislada para investigarla.
