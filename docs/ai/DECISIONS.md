# Decisiones Técnicas y de Arquitectura

## [2026-08-19] Desactivación Permanente de SILENT_ON_START

**Decisión:**
1. Se fija `should_send_alerts = True` en `main.py` para garantizar el envío de alertas desde el ciclo 1 de arranque.

## [2026-08-20] Detección de stack basada en evidencia directa

**Decisión:**
`extract_tech_stack` sólo muestra tecnologías, plataformas o familias técnicas
que aparezcan de forma explícita en título o descripción. Si no hay evidencia,
devuelve una lista vacía; no infiere Python, Machine Learning ni APIs a partir
del nombre genérico del puesto.

## [2026-08-20] Prompt de proyectos mediante botones nativos de Telegram

**Decisión:**
Cada alerta ofrece `copy_text` para copiar el prompt. Telegram exige una sola
acción por botón, por lo que no es posible copiar y abrir una URL con el mismo
botón nativo; por decisión de usuario no se muestra una acción adicional para
abrir ChatGPT. `CopyTextButton` admite de 1 a 256 caracteres; cuando conservar
el enlace completo excede ese máximo, un callback entrega el prompt completo
en el chat del bot en vez de truncarlo.

## [2026-08-20] Índice público de Experis

**Decisión:**
Experis se consulta una vez por ciclo mediante su índice HTML público, no con
Playwright. Las páginas individuales sólo se solicitan al enriquecer una oferta
que ya va a notificarse, para conservar el ciclo ligero y extraer la descripción
del bloque específico de la vacante.

## [2026-08-20] Portal público de Accessiway

**Decisión:**
Accessiway se consulta una vez por ciclo mediante su portal público Teamtailor,
sin navegador. El proveedor conserva todas las vacantes publicadas y deja que
los filtros comunes de ubicación y palabras del bot decidan cuáles alertar.

## [2026-08-20] Aislamiento de LinkedIn y equivalencia de `/scan`

**Decisión:**
LinkedIn se ejecuta al final del ciclo. Los ciclos ordinarios consultan sólo
las franjas de 30, 60 y 120 minutos y la paginación configurada; las franjas largas
se reservan para el arranque y la recuperación de las 08:00. Un HTTP 429 corta
la extracción y activa un cooldown de un intervalo, sin bloquear los demás
proveedores. `/scan` comparte la misma ruta de extracción y procesamiento y
queda excluido mientras el scheduler mantiene el lock de scraping.

Las consultas consecutivas de LinkedIn esperan de forma aleatoria entre 3 y 6
segundos para mantener moderado cada bloque de extracción.

## [2026-08-20] Métrica persistente de límites HTTP 429

**Decisión:**
Cada ciclo persiste en `data/rate_limit_metrics.jsonl` un registro JSONL compacto
con el total de respuestas HTTP 429 y el desglose por proveedor. LinkedIn mantiene
además contadores exactos por ciclo y por proceso. Esto permite diferenciar un
cooldown de una nueva respuesta 429 y conservar el seguimiento tras reiniciar el
servicio.

## [2026-08-20] LinkedIn mediante Chromium dedicado en Raspberry

**Decisión:**
Cuando `LINKEDIN_EXTENSION_ENABLED=true`, `main.py` no crea el proveedor
Playwright de LinkedIn. En su lugar aloja un receptor HTTP limitado a localhost
que recibe tarjetas de la extensión Manifest V3 de un perfil Chromium dedicado.
El receptor entrega los `JobItem` al mismo `process_jobs` y bajo el mismo lock
que el scheduler, por lo que no existe un segundo estado de `seen`, pausa o
notificador. Chromium conserva la sesión de LinkedIn en un perfil local y la
extensión usa una alarma para reintentar si el navegador aparece antes que el
proceso principal.

## [2026-08-20] Chromium moderno sin dependencia de escritorio

**Decisión:**
El servicio dedicado ejecuta Chromium con `--headless=new`, perfil persistente
y la extensión Manifest V3 declarada por flags. Esta modalidad conserva una
pestaña y el service worker de la extensión, pero no requiere foco, una ventana
visible ni X11, que en la Raspberry impedían cargar los renderers de Chromium.
La depuración remota sólo se habilita explícitamente para mantenimiento local y
permanece cerrada en el servicio normal.

Los IDs de ofertas que superan el límite de `callback_data` de Telegram se
normalizan a un hash corto y estable de la URL canónica. Así la deduplicación y
los botones siguen funcionando sin exponer datos adicionales ni fallar el envío.

## [2026-08-23] Reconciliación dual y auditable de LinkedIn

**Decisión:**
La extensión Chromium es el canal principal de LinkedIn, pero cada lote completo
se compara con una única consulta pública equivalente sobre la misma URL original.
Ambos inventarios se normalizan por ID canónico/URL canónica y su unión se entrega
una sola vez al flujo común; las diferencias se persisten en
`data/linkedin_runs.jsonl` y nunca generan avisos técnicos de Telegram. No se
reescribe `f_TPR` ni se recorren páginas adicionales: el alcance es la primera
página estable. Desde el 2026-08-25 el inventario estable no tiene un límite
técnico de tarjetas; cualquier recorte se consideraría una extracción parcial.

Los filtros de ubicación, inclusión y exclusión pertenecen a `main.py`, después
del enriquecimiento de descripción si hace falta. La señal de stack es
clasificación, no un descarte previo. Si la extensión no completa dos intervalos,
la API entrega como respaldo degradado; una pasada completa de extensión restaura
el modo dual. Las claves históricas de `seen` se conservan como alias del ID
canónico, sin migración masiva.

## [2026-08-21] Consultoras publicas con puerta de validacion

**Decision:**
Los adaptadores de consultoras se registran todos, pero el scheduler solo crea
uno si concurre la habilitacion manual en `ENABLED_PROVIDERS` y un estado
`validated` vigente. La validacion se realiza en un proceso aislado que compara
el extractor con tarjetas visibles de una sesion publica independiente, no usa
credenciales y no modifica `seen` ni Telegram. Un 403, 429, challenge,
paginacion incompleta o una ausencia elegible conserva el proveedor fuera del
ciclo normal con trazabilidad en `data/provider_validation/`.

## [2026-08-21] Orden temporal honesto para listados de consultoras

**Decision:**
Las ofertas de consultoras se ordenan de forma descendente solo cuando todas
las tarjetas publicas extraidas incluyen una fecha de publicacion parseable.
Una mezcla de tarjetas fechadas y sin fecha conserva el orden original del
portal, ya que no permite demostrar que las no fechadas sean mas antiguas. La
auditoria y las metricas persisten `publication_date_desc` o
`portal_order_unverified` para que cobertura y orden temporal no se confundan.

## [2026-08-23] Salud conservadora del endpoint público de LinkedIn

**Decisión:**
El endpoint público que devuelve exactamente un fragmento de diez tarjetas se
clasifica como `partial` cuando el alcance configurado permite hasta 25. No se
solicita una página adicional ni se reescribe la URL configurada; la extensión
es la única prueba de que se alcanzó la primera página completa. Chromium carga
la extensión desde una copia versionada por huella para que una actualización
del worker MV3 no requiera borrar el perfil persistente ni la sesión del usuario.

## [2026-08-23] Acuse inmediato para lotes de la extensión

**Decisión:**
`POST /ingest` acusa un lote válido con HTTP 202 tras aceptarlo una sola vez por
`run_id`; la reconciliación con la API pública continúa en un worker de fondo
serializado. Así la extensión Manifest V3 no mantiene su petición abierta
durante una consulta pública lenta ni reintenta un lote ya aceptado. El acuse
solo confirma recepción por el bridge, no una extracción correcta: el resultado
autoritativo sigue siendo el informe JSONL con los estados `complete`,
`partial`, `blocked`, `rate_limited` o `failed`.

## [2026-08-23] Caracteristicas de ofertas extraidas en un flujo comun

**Decision:**
Los proveedores entregan tarjetas publicas sin interpretar requisitos. El flujo
comun enriquece las tarjetas con descripcion insuficiente desde su ficha publica
y normaliza las caracteristicas en `JobItem.features` antes de aplicar filtros,
deduplicacion, analitica y Telegram. Asi la cobertura no depende de una
implementacion parcial de cada portal. La experiencia conserva sus anos, nivel,
obligatoriedad/valoracion, tecnologias cercanas y evidencia textual; las
afirmaciones sobre la experiencia de la empresa se excluyen. Un detalle publico
no disponible se mide, pero nunca descarta silenciosamente una oferta.

## [2026-08-24] Auditoria diaria basada en evidencia persistida

**Decision:**
La comprobacion diaria de salud consume exclusivamente los registros append-only
que deja el scheduler y el informe dual de LinkedIn. No ejecuta una segunda
busqueda, no modifica `seen` y no emite alertas de empleo; puede enviar solo un
resumen diagnostico diario de Telegram. El resultado es una puntuacion de
evidencia operativa, limitada explicitamente a lo que el bot registro, y nunca
se presenta como prueba de cobertura completa del mercado externo. Los informes
se guardan por fecha y como `latest.json`; el temporizador systemd persistente
los ejecuta cada noche, con pequena aleatorizacion para evitar una hora rigida.

## [2026-08-24] Auditoria operativa bajo demanda

**Decision:**
El comando Telegram `/auditoria` (alias `/coverage`) reutiliza exactamente la
auditoria diaria sobre los JSONL ya persistidos. No lanza proveedores, no toca
`seen` y no puede generar alertas de empleo; solo actualiza el informe de ese
dia y envia el resumen tecnico solicitado. Asi permite comprobar el estado en
cualquier momento sin alterar la evidencia que se esta evaluando.

## [2026-08-24] Contabilidad terminal por oferta y retencion acotada

Los ciclos normales registran por proveedor un lote diario con una clave hash de cada
tarjeta recibida y su resultado terminal. La auditoria diaria reconcilia ese ledger
con los detectados del ciclo y considera critico un lote ausente, una diferencia de
conteos o una tarjeta sin resultado terminal. Se excluyen los `/scan` manuales de esa
comparacion para no confundir la evidencia del scheduler.

El ledger no persiste titulo, URL ni descripcion. La limpieza diaria solo elimina
telemetria generada con retencion configurable; `data/seen_jobs.txt` no se toca para
preservar la deduplicacion historica.

La reconciliacion individual comienza en el instante de la primera evidencia del
ledger. Las metricas anteriores se mantienen para la salud historica del proveedor,
pero no se presentan como tarjetas sin traza: no existia un ledger antes de esta
decision. Desde ese limite, una ausencia de lote, diferencia de conteo o resultado no
terminal es un fallo critico verificable.

## [2026-08-24] Alias historico limitado a la reconciliacion de Greenhouse

`greenhouse_spain` conserva `greenhouse` como nombre de fuente dentro de los IDs
historicos. La auditoria acepta ambos nombres exclusivamente al comparar el lote de
ese proveedor con las metricas del scheduler. No se reescriben IDs, URLs ni
`seen_jobs.txt`, para preservar la deduplicacion existente.

## [2026-08-24] Historicos operativos con memoria y retencion acotadas

**Decision:**
Los historicos que pueden crecer se recorren en streaming y los resumentes
recientes se leen desde el final, con una ventana temporal y un maximo de 300
ofertas unicas. Las listas residentes del bot tienen limites explicitos y el
acumulador diario se reinicia al cambiar de fecha. La limpieza diaria elimina
solo telemetria generada caducada (ledger 35 dias, metricas/cobertura 90 y
validaciones 180); la deduplicacion `seen` conserva su propia retencion corta
de dos dias. Asi la memoria y el espacio no dependen indefinidamente de los
ciclos ejecutados.

## [2026-08-24] Limpieza conservadora de perfiles de navegador

**Decision:**
Los perfiles persistentes conservan credenciales de sesion, cookies y
almacenamiento local. La limpieza automatica solo elimina directorios de cache
regenerables y backups de sesion identificados por nombre y antiguedad; nunca
elimina un perfil activo, cookies, `Local Storage` ni `seen_jobs.txt`. Se aplica
antes de arrancar Chromium y diariamente a las sesiones Playwright, con 14 dias
para backups de sesion y 30 para copias antiguas de la extension por defecto.

## [2026-08-24] Ventana de resultados LinkedIn de 20 minutos

**Decision:**
Las URLs configuradas de LinkedIn usan `f_TPR=r1200` y `sortBy=DD`, por peticion
del usuario. La extension y el respaldo API deben preservar la consulta exactamente,
sin reescribir ese filtro temporal. Las comparaciones entre ventanas son diagnostico
de inventario, no una prueba de cobertura, mientras el endpoint publico devuelva
resultados parciales.

## [2026-08-24] Cascada de ventanas recientes por URL base de LinkedIn

**Decision:**
Se sustituye la politica de una unica ventana de 20 minutos por dos consultas
lineales por cada URL base: `f_TPR=r1200` y despues `f_TPR=r3600`. La expansion
solo modifica `f_TPR`; todos los demas parametros configurados se conservan. La
extension y el respaldo API usan la misma lista expandida para que su comparacion
siga siendo interpretable. Se espera aleatoriamente entre 3 y 6 segundos entre
consultas consecutivas, configurable mediante entorno. La deduplicacion canonica
se mantiene aguas abajo, por lo que el solapamiento temporal no multiplica alertas.

Los valores predeterminados son `LINKEDIN_TIME_WINDOWS_SECONDS=1200,3600`,
`LINKEDIN_INTER_SEARCH_MIN_SECONDS=3` y
`LINKEDIN_INTER_SEARCH_MAX_SECONDS=6`. La pausa reduce las rafagas, pero no
garantiza que LinkedIn no aplique limites: los HTTP 429 y lotes parciales deben
seguir tratandose como senales operativas.

## [2026-08-24] Conciliacion de lotes por cierre de ciclo

**Decision:**
La auditoria asocia cada lote normal del ledger al primer registro de metricas
posterior del mismo proveedor dentro de dos intervalos de sondeo. Si ese cierre
todavia no existe, el lote queda `in_progress` y no degrada la evidencia. Para
LinkedIn, `run_id` es la asociacion primaria y la hora solo es un respaldo para
historiales sin identificador. Esto evita interpretar como ausencias las ofertas
que aun se estan enriqueciendo o notificando, sin rebajar la deteccion de lotes
realmente omitidos.

## [2026-08-25] Inventario LinkedIn limitado a la primera pagina util

**Decision:**
El alcance solicitado son las 25 ofertas mas recientes de cada URL de LinkedIn,
que debe conservar `sortBy=DD`. Extension, extractor HTTP e inventario de
referencia se recortan al mismo limite de 25 para que la auditoria compare el
mismo universo. El valor heredado `LINKEDIN_MAX_JOBS=0` se normaliza a 25 y un
valor positivo nunca puede superar 25. La entrega de alertas sigue sin limite
por ciclo (`MAX_NOTIFS_PER_CYCLE=0`).

La cascada exclusiva de LinkedIn usa un bloqueo propio para extensión y respaldo
API. El scheduler y `/scan` conservan su bloqueo general entre proveedores, pero
los portales no LinkedIn no esperan a que Chromium termine su lote.

## [2026-08-25] Completitud verificable de las 25 ofertas recientes

**Decision:**
Un listado de LinkedIn es completo cuando llega a 25 tarjetas, o al total
anunciado si es menor de 25, sin challenge. Al alcanzar el objetivo la extension
termina; la estabilizacion del DOM se reserva para determinar que un listado
menor esta agotado. Si no llega al objetivo, expone un lote `partial` con
diagnostico y el inventario BOT vs referencia queda invalidado. Esta regla
prueba cobertura del alcance pactado, no del total del mercado anunciado por
LinkedIn.

La extension limita el recorrido DOM antes del parseo: extractor productivo e
inventario independiente usan solo las primeras 25 tarjetas encontradas. Es
posible que LinkedIn informe o precargue mas tarjetas en el DOM; ese dato queda
como diagnostico, pero las tarjetas posteriores a la 25 no se leen ni afectan
la conciliacion.

## [2026-08-27] Verificacion por tarjeta de la ventana temporal de LinkedIn

**Decision:**
`f_TPR` se conserva como URL original de consulta, pero no se considera prueba
suficiente de antiguedad: LinkedIn puede devolver una tarjeta que no corresponda
a esa ventana. Cada tarjeta conserva las URLs de busqueda y las evidencias
visibles de fecha. Antes de persistirla en `seen` o enviarla a Telegram, se
compara la edad comprobable con la ventana menor de sus origenes. Las tarjetas
fuera de ventana o sin evidencia temporal verificable se descartan de forma
conservadora y se contabilizan por separado. Esta regla puede omitir una tarjeta
si LinkedIn no expone su fecha, pero evita afirmar o enviar como reciente una
oferta cuya antiguedad no se puede demostrar.

Una fecha de calendario sin componente horario no se convierte en una hora de
publicacion: LinkedIn la muestra como metadato auxiliar y se requiere tambien
el texto relativo visible o una marca temporal completa.

## [2026-08-28] LinkedIn como fuente candidata y exclusiones precisas

**Decision:**
Las URLs de búsqueda configuradas de LinkedIn representan candidatas, no un
filtro adicional de elegibilidad. Las palabras genéricas de inclusión no se
aplican a esas tarjetas y la falta de evidencia concreta se clasifica como
advertencia notificable, no como rechazo. Se reservan los rechazos para familias
claramente ajenas y documentadas.

Las exclusiones manuales deben ser frases precisas de título o empresa. Los
términos genéricos heredados (`data`, `python`, `senior`, `qa`, `power`, etc.)
se conservan solo como historial, porque su coincidencia por subcadena ocultaba
ofertas pertinentes. Esta migración cambia el fingerprint de evaluación para
que la caché no prolongue decisiones anteriores.
