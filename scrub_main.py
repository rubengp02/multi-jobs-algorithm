import re

with open("/home/rubengaona/bots/bot_multi_jobs/main.py", "r", encoding="utf-8") as f:
    text = f.read()

# Delete ALL occurrences of the broken blocks
# The block starts at `if cmd in {"/health"` and ends before `if cmd in {"/metrics"`
pattern = re.compile(
    r'        if cmd in \{"/health", "/salud", "/check"\}:.*?        if cmd in \{"/metrics", "/analytics", "/market", "/estudio"\}:',
    re.DOTALL,
)

clean_block = """        if cmd in {"/health", "/salud", "/check"}:
            health_lines = ["🩺 *ESTADO DE PORTALES (ÚLTIMO CICLO)*", ""]
            if not CYCLE_LOGS:
                ctx.notifier.send_message("🩺 *Estado:* Esperando a que termine el primer ciclo de escaneo del bot...")
                continue
            
            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})
            
            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_")
            health_lines.append("")
            
            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")
                
                if status_flag is False:
                    health_lines.append(f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`")
                elif http_429 > 0:
                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")
                    
            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if source.source in ctx.config.enabled_providers and source.source not in stats:
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")
                    skipped += 1
                    
            health_lines.append("")
            health_lines.append(f"_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_")
            ctx.notifier.send_message(chr(10).join(health_lines))
            continue

        if cmd in {"/metrics", "/analytics", "/market", "/estudio"}:"""

# Replace all of it with a SINGLE clean block
text = pattern.sub(clean_block, text)

with open("/home/rubengaona/bots/bot_multi_jobs/main.py", "w", encoding="utf-8") as f:
    f.write(text)
