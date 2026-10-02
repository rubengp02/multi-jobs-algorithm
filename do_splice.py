with open("main_rpi.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "/health" in line:
        start_idx = i
        break
for i in range(start_idx, len(lines)):
    if "continue" in lines[i]:
        end_idx = i
        break

lines[start_idx : end_idx + 1] = [
    '        if cmd in {"/health", "/salud", "/check"}:\n',
    '            health_lines = ["🩺 *ESTADO DE PORTALES (ÚLTIMO CICLO)*\\\\n"]\n',
    "            if not CYCLE_LOGS:\n",
    '                ctx.notifier.send_message("🩺 *Estado:* Esperando a que termine el primer ciclo de escaneo del bot...")\n',
    "                continue\n",
    "            last_log = CYCLE_LOGS[0]\n",
    '            cycle_num = last_log.get("cycle_num", 0)\n',
    '            timestamp = last_log.get("timestamp", "")\n',
    '            stats = last_log.get("by_provider", {})\n',
    '            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_\\\\n")\n',
    "            for name, data in stats.items():\n",
    '                detected = data.get("detected", 0)\n',
    '                http_429 = data.get("http_429", 0)\n',
    '                status_flag = data.get("validation_status")\n',
    '                blocked = data.get("blocked_reason")\n',
    "                if status_flag is False:\n",
    "                    health_lines.append(f\"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`\")\n",
    "                elif http_429 > 0:\n",
    '                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")\n',
    "                elif blocked:\n",
    '                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")\n',
    "                elif detected > 0:\n",
    '                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")\n',
    "                else:\n",
    '                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")\n',
    "            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)\n",
    "            skipped = 0\n",
    "            for source in CONSULTANCY_SOURCES:\n",
    "                if source.source in ctx.config.enabled_providers and source.source not in stats:\n",
    "                    val_state = validation_store.get(source.source)\n",
    '                    status_reason = val_state.get("reason", "Pendiente de validación")\n',
    '                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")\n',
    "                    skipped += 1\n",
    "            health_lines.append(f\"\\\\n_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_\")\n",
    '            ctx.notifier.send_message("\\\\n".join(health_lines))\n',
    "            continue\n",
]

with open("main_rpi.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
