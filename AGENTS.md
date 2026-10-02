# SHARED PROJECT CONTRACT & INSTRUCTIONS

## Shared Project Memory

Before substantial work, inspect:
- [`docs/ai/CURRENT_TASK.md`](./docs/ai/CURRENT_TASK.md)
- [`docs/ai/HANDOFF.md`](./docs/ai/HANDOFF.md)

Consult when needed:
- [`docs/ai/INDEX.md`](./docs/ai/INDEX.md)
- [`docs/ai/PROJECT_CONTEXT.md`](./docs/ai/PROJECT_CONTEXT.md)
- [`docs/ai/ARCHITECTURE.md`](./docs/ai/ARCHITECTURE.md)
- [`docs/ai/DECISIONS.md`](./docs/ai/DECISIONS.md)

---

## Directrices Operativas para Agentes de IA

1. **Fuente de Verdad:**
   - El estado real de los archivos, Git, tests y validaciones son la fuente primordial de verdad.
   - No asumas que dispones del historial de chat de sesiones anteriores.

2. **Mantenimiento de la Memoria:**
   - Antes de completar una etapa sustancial:
     - Actualiza [`docs/ai/CURRENT_TASK.md`](./docs/ai/CURRENT_TASK.md).
     - Actualiza [`docs/ai/HANDOFF.md`](./docs/ai/HANDOFF.md).
     - Registra únicamente decisiones duraderas en [`docs/ai/DECISIONS.md`](./docs/ai/DECISIONS.md).
   - Mantén los archivos de memoria concisos. No vuelques logs extensos, respuestas completas ni código redundante.

3. **Buenas Prácticas del Proyecto:**
   - No subir ni versionar tokens o credenciales reales de `.env`.
   - Modificaciones en scraping deben preservar la robustez defensiva y evitar patrones de detección.
   - Respetar la modularidad en `providers/` y el desacoplamiento con `storage.py` y `notifier.py`.
