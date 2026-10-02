import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from notifier import TelegramNotifier


class _Response:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"ok": True, "result": []}


class TelegramLongPollingTests(unittest.TestCase):
    def test_message_without_credentials_reports_a_failed_delivery(self) -> None:
        config = SimpleNamespace(
            telegram_bot_token="",
            telegram_chat_id="",
            timeout_seconds=5,
        )
        notifier = TelegramNotifier(config, logging.getLogger("test-notifier"))

        self.assertFalse(notifier.send_message("test"))

    @patch("notifier.requests.get", return_value=_Response())
    def test_regular_command_read_uses_long_polling(self, get: object) -> None:
        config = SimpleNamespace(
            telegram_bot_token="test-token",
            telegram_chat_id="123",
            timeout_seconds=5,
            telegram_poll_timeout_seconds=20,
        )
        notifier = TelegramNotifier(config, logging.getLogger("test-notifier"))

        commands, next_offset = notifier.fetch_command_messages("123", 42)

        self.assertEqual(commands, [])
        self.assertEqual(next_offset, 42)
        kwargs = get.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual(kwargs["params"]["timeout"], 20)
        self.assertEqual(kwargs["params"]["offset"], 42)
        self.assertEqual(kwargs["timeout"], 25)

    @patch("notifier.requests.get", return_value=_Response())
    def test_bootstrap_drains_pending_updates_without_waiting(
        self, get: object
    ) -> None:
        config = SimpleNamespace(
            telegram_bot_token="test-token",
            telegram_chat_id="123",
            timeout_seconds=25,
            telegram_poll_timeout_seconds=20,
        )
        notifier = TelegramNotifier(config, logging.getLogger("test-notifier"))

        notifier.fetch_command_messages("123", None, long_poll=False)

        kwargs = get.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual(kwargs["params"]["timeout"], 0)
        self.assertEqual(kwargs["timeout"], 25)

    @patch("notifier.requests.post")
    def test_message_retries_plain_text_and_logs_telegram_description_without_url(
        self, post: object
    ) -> None:
        class RejectedResponse:
            status_code = 400
            text = '{"ok":false,"description":"Bad Request: BUTTON_DATA_INVALID"}'

            def json(self) -> dict[str, object]:
                return {"ok": False, "description": "Bad Request: BUTTON_DATA_INVALID"}

        config = SimpleNamespace(
            telegram_bot_token="test-token",
            telegram_chat_id="123",
            timeout_seconds=5,
        )
        notifier = TelegramNotifier(config, logging.getLogger("test-notifier"))
        post.return_value = RejectedResponse()  # type: ignore[attr-defined]

        with self.assertLogs("test-notifier", level="ERROR") as logs:
            self.assertFalse(notifier.send_message("*test*", {"inline_keyboard": []}))

        self.assertEqual(post.call_count, 2)  # type: ignore[attr-defined]
        self.assertNotIn("https://", "\n".join(logs.output))
        self.assertIn("BUTTON_DATA_INVALID", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
