# Índice de Memoria Compartida (docs/ai)

Esta carpeta contiene la **memoria compartida canónica** del proyecto para cualquier agente de IA, IDE o modelo que trabaje en él.

## Estructura de la Memoria

| Archivo | Tipo | Propósito |
| :--- | :--- | :--- |
| [`CURRENT_TASK.md`](./CURRENT_TASK.md) | **Dinámico** | Estado exacto de la tarea en curso, bloqueos y siguiente paso. |
| [`HANDOFF.md`](./HANDOFF.md) | **Dinámico** | Punto de relevo inmediato entre agentes/sesiones. |
| [`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md) | **Estable** | Propósito, stack, comandos, convenciones y configuración. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | **Estable** | Componentes, flujo de datos, scraping y persistencia. |
| [`DECISIONS.md`](./DECISIONS.md) | **Histórico** | Registro de decisiones técnicas y arquitectónicas duraderas. |

---

## PARA RETOMAR RÁPIDAMENTE EL PROYECTO, LEER EN ESTE ORDEN:

1. Instrucciones y contrato del proyecto: [`AGENTS.md`](../../AGENTS.md)
2. Estado actual de la tarea: [`docs/ai/CURRENT_TASK.md`](./CURRENT_TASK.md)
3. Último punto de relevo: [`docs/ai/HANDOFF.md`](./HANDOFF.md)
4. Consultar [`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md) o [`ARCHITECTURE.md`](./ARCHITECTURE.md) únicamente si hace falta contexto técnico de fondo.
5. Comprobar archivos reales y estado de ejecución.
