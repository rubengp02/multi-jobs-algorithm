import os

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

def get_block(start, end):
    return "".join(lines[start-1:end])

telegram_imports = '''from __future__ import annotations
import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Any
import json

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery

from shared_state import CURRENT_STATUS, CYCLE_LOGS
import shared_state
'''

with open('telegram_bot.py', 'w', encoding='utf-8') as f:
    f.write(telegram_imports + '\n')
    f.write(get_block(601, 1470))

print("Created telegram_bot.py")
