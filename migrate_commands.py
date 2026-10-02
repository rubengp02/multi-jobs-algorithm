import os
import re

def migrate_commands_to_async():
    with open('main.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # Make maybe_run_daily_seen_cleanup async
    code = re.sub(r'def maybe_run_daily_seen_cleanup\(', r'async def maybe_run_daily_seen_cleanup(', code)
    code = re.sub(r'last_cleanup_date = maybe_run_daily_seen_cleanup\(', r'last_cleanup_date = await maybe_run_daily_seen_cleanup(', code)

    # Make process_telegram_commands async
    code = re.sub(r'def process_telegram_commands\(', r'async def process_telegram_commands(', code)

    # Fix await in handle_message/handle_callback
    # Instead of await asyncio.to_thread(process_telegram_commands, ...), just await it!
    code = re.sub(r'await asyncio\.to_thread\(\s*process_telegram_commands,\s*', r'await process_telegram_commands(', code)

    # Add await to process_telegram_commands calls inside process_telegram_commands (recursive wait)
    # wait, process_telegram_commands isn't recursive, it just calls functions.
    
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(code)

if __name__ == "__main__":
    migrate_commands_to_async()
