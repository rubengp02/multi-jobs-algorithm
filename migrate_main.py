import os
import re

def migrate_main_to_async():
    with open('main.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # 1. Convert process_jobs to async def
    code = re.sub(r'def process_jobs\(', r'async def process_jobs(', code)
    
    # 2. Add awaits to ctx.storage
    code = re.sub(r'ctx\.storage\.is_seen_any\(', r'await ctx.storage.is_seen_any(', code)
    code = re.sub(r'ctx\.storage\.is_seen\(', r'await ctx.storage.is_seen(', code)
    code = re.sub(r'ctx\.storage\.add\(', r'await ctx.storage.add(', code)
    code = re.sub(r'ctx\.storage\.purge_older_than_days\(', r'await ctx.storage.purge_older_than_days(', code)
    code = re.sub(r'ctx\.storage\.count\(', r'await ctx.storage.count(', code)

    # 3. Add awaits to ctx.relevance_cache
    code = re.sub(r'ctx\.relevance_cache\.get\(', r'await ctx.relevance_cache.get(', code)
    code = re.sub(r'ctx\.relevance_cache\.put\(', r'await ctx.relevance_cache.put(', code)

    # 4. Add awaits to ctx.metrics
    code = re.sub(r'ctx\.metrics\.record_job\(', r'await ctx.metrics.record_job(', code)
    code = re.sub(r'ctx\.metrics\.generate_analytics_report\(', r'await ctx.metrics.generate_analytics_report(', code)

    # 5. Fix the loop in main where process_jobs is called
    # stats = process_jobs(...) -> stats = await process_jobs(...)
    code = re.sub(r'stats = process_jobs\(', r'stats = await process_jobs(', code)
    code = re.sub(r'report = ctx\.metrics\.generate_analytics_report\(', r'report = await ctx.metrics.generate_analytics_report(', code)

    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(code)

if __name__ == "__main__":
    migrate_main_to_async()
