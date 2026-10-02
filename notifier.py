from __future__ import annotations

import json
import logging
from typing import Any

import requests

from config import BotConfig


class TelegramNotifier:
    def __init__(self, config: BotConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    def send_message(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> bool:
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            self.logger.warning(
                "Telegram token/chat_id missing. Message skipped: %s", text[:120]
            )
            return False

        url = (
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        )

        # 1. Intentar enviar con formato Markdown para que las negritas queden limpias
        try:
            params: dict[str, Any] = {
                "chat_id": self.config.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                params["reply_markup"] = json.dumps(reply_markup)
            if reply_to_message_id:
                params["reply_to_message_id"] = reply_to_message_id

            response = requests.post(
                url, data=params, timeout=self.config.timeout_seconds
            )
            if response.status_code == 200:
                return True
            self.logger.warning(
                "Telegram Markdown send rejected (%s). Fallback to clean plain text.",
                self._response_detail(response),
            )
        except Exception as exc:
            self.logger.warning(
                "Telegram Markdown send failed: %s", self._exception_detail(exc)
            )

        # 2. Fallback en texto plano limpio
        try:
            clean_text = text.replace("*", "")
            params = {
                "chat_id": self.config.telegram_chat_id,
                "text": clean_text,
                "disable_web_page_preview": True,
            }
            if reply_markup:
                params["reply_markup"] = json.dumps(reply_markup)
            if reply_to_message_id:
                params["reply_to_message_id"] = reply_to_message_id

            response = requests.post(
                url, data=params, timeout=self.config.timeout_seconds
            )
            if response.status_code == 200:
                return True
            self.logger.error(
                "Telegram fallback rejected: %s", self._response_detail(response)
            )
        except Exception as exc:
            self.logger.error(
                "Telegram fallback error: %s", self._exception_detail(exc)
            )
        return False

    @staticmethod
    def _response_detail(response: requests.Response) -> str:
        """Return Telegram's useful error without ever logging the tokenized URL."""
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            payload = None
        description = ""
        if isinstance(payload, dict):
            description = str(payload.get("description") or "").strip()
        if not description:
            description = (
                str(getattr(response, "text", "") or "")
                .strip()
                .replace("\n", " ")[:300]
            )
        return f"HTTP {response.status_code}" + (
            f": {description}" if description else ""
        )

    @staticmethod
    def _exception_detail(exc: Exception) -> str:
        """Keep request exceptions informative while excluding request URLs/tokens."""
        response = getattr(exc, "response", None)
        if isinstance(response, requests.Response):
            return TelegramNotifier._response_detail(response)
        return f"{type(exc).__name__}: {str(exc)[:300]}"

    def send_document(self, file_path: str, caption: str = "") -> bool:
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            self.logger.warning(
                "Telegram token/chat_id missing. Document skipped: %s", file_path
            )
            return False

        url = (
            f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendDocument"
        )
        try:
            with open(file_path, "rb") as doc_file:
                files = {"document": doc_file}
                data = {
                    "chat_id": self.config.telegram_chat_id,
                    "caption": caption,
                    "parse_mode": "Markdown",
                }
                response = requests.post(url, data=data, files=files, timeout=30)
                if response.status_code == 200:
                    return True
                self.logger.warning(
                    "Telegram sendDocument failed (HTTP %d): %s",
                    response.status_code,
                    response.text[:200],
                )
        except Exception as exc:
            self.logger.error("Telegram sendDocument error: %s", exc)
        return False

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        if not self.config.telegram_bot_token:
            return
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/answerCallbackQuery"
        try:
            data = {"callback_query_id": callback_query_id}
            if text:
                data["text"] = text
            requests.post(url, data=data, timeout=5)
        except Exception as exc:
            self.logger.warning("answerCallbackQuery failed: %s", exc)

    def fetch_command_messages(
        self,
        allowed_chat_id: str,
        offset: int | None,
        long_poll: bool = True,
    ) -> tuple[list[tuple[int, str, int | None]], int | None]:
        """Return Telegram commands and the next update offset.

        ``long_poll=False`` is reserved for the listener bootstrap, which drains
        pending commands without delaying startup. All regular calls long-poll.
        """
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            return [], offset
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/getUpdates"
            # Telegram holds this request until a command arrives or the timeout expires.
            poll_timeout = max(
                1,
                min(int(getattr(self.config, "telegram_poll_timeout_seconds", 20)), 50),
            )
            telegram_timeout = poll_timeout if long_poll else 0
            import json

            params: dict[str, Any] = {
                "timeout": telegram_timeout,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }
            if offset is not None:
                params["offset"] = offset
            request_timeout = max(self.config.timeout_seconds, telegram_timeout + 5)
            response = requests.get(url, params=params, timeout=request_timeout)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                return [], offset
            results = payload.get("result") or []
            commands: list[tuple[int, str, int | None]] = []
            next_offset = offset
            for item in results:
                upd_id = int(item.get("update_id"))
                if next_offset is None or upd_id + 1 > next_offset:
                    next_offset = upd_id + 1

                # 1. Handle Inline Button Clicks (callback_query)
                if "callback_query" in item:
                    cq = item["callback_query"]
                    cq_id = str(cq.get("id", ""))
                    cq_data = (cq.get("data") or "").strip()
                    cq_from = cq.get("from") or {}
                    cq_chat_id = str(cq_from.get("id", ""))
                    self.logger.info(
                        f"Callback received: data={cq_data}, user_id={cq_chat_id}, allowed={allowed_chat_id}"
                    )
                    if cq_data:
                        self.answer_callback_query(cq_id, "⏳ Procesando...")
                        msg_id = cq.get("message", {}).get("message_id")
                        commands.append((upd_id, cq_data, msg_id))
                    continue

                # 2. Handle Text Slash Commands (message)
                msg = item.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = (msg.get("text") or "").strip()
                if not text or chat_id != str(allowed_chat_id):
                    continue
                if not text.startswith("/"):
                    continue
                msg_id = msg.get("message_id")
                commands.append((upd_id, text, msg_id))
            return commands, next_offset
        except Exception as exc:
            self.logger.error("Telegram getUpdates error: %s", exc)
            return [], offset
