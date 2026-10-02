filepath = "/home/rubengaona/bots/bot_multi_jobs/main.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

target = (
    "            filter_reason = job_filter_reason(job, ctx.config, job.description)"
)
injection = (
    target
    + """

            # --- GEMINI AI EVALUATOR FILTER ---
            if decision.status != "rejected" and not filter_reason:
                if not evaluate_job_with_gemini(job, job.description or ""):
                    stats.discarded_relevance += 1
                    outcomes[index] = "discarded_relevance:llm_rejected"
                    continue
            # ----------------------------------"""
)

if "# --- GEMINI AI EVALUATOR FILTER ---" not in text:
    text = text.replace(target, injection)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    print("Injected successfully!")
