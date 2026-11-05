import importlib
import logging
import os
import unittest
from unittest.mock import Mock, patch

sync = importlib.import_module("grafana_azure_sync.main")


class LoggingTests(unittest.TestCase):
    def test_main_configures_logging_after_loading_dotenv(self):
        for configured_level, expected_level in ((None, "INFO"), ("debug", "DEBUG")):
            with (
                self.subTest(level=configured_level),
                patch.dict(os.environ, {}, clear=True),
            ):

                def load_environment(configured_level=configured_level):
                    if configured_level is not None:
                        os.environ["LOG_LEVEL"] = configured_level

                with (
                    patch.object(sync, "load_dotenv", side_effect=load_environment),
                    patch.object(sync.logging, "basicConfig") as configure,
                    patch.object(sync, "sync_teams") as run_sync,
                ):
                    run_sync.side_effect = lambda expected_level=expected_level: (
                        configure.assert_called_once_with(
                            level=expected_level,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        )
                    )
                    sync.main()
                    run_sync.assert_called_once_with()

    def test_api_failure_logs_error(self):
        response = Mock(status_code=500, text="Service unavailable")
        with (
            patch.object(sync.requests, "get", return_value=response),
            self.assertLogs(sync.logger, level="ERROR") as logs,
        ):
            self.assertEqual(sync.get_grafana_users(), [])
        self.assertEqual(logs.records[0].levelno, logging.ERROR)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Error fetching Grafana users: Service unavailable",
        )

    def test_api_success_logs_info(self):
        groups = [{"id": "group-1"}]
        response = Mock(status_code=200)
        response.json.return_value = {"value": groups}
        with (
            patch.object(sync.requests, "get", return_value=response),
            self.assertLogs(sync.logger, level="INFO") as logs,
        ):
            self.assertEqual(sync.get_azure_groups("token"), groups)
        self.assertEqual(logs.records[0].levelno, logging.INFO)
        self.assertEqual(
            logs.records[0].getMessage(), "Successfully fetched Azure AD groups."
        )

    def test_membership_details_are_debug_only(self):
        response = Mock(status_code=200)
        response.json.return_value = [{"userId": 1, "email": "member@example.com"}]
        with (
            patch.object(sync.requests, "get", return_value=response),
            self.assertLogs(sync.logger, level="DEBUG") as logs,
        ):
            sync.update_grafana_team_members(10, [], [])
        self.assertTrue(all(record.levelno == logging.DEBUG for record in logs.records))
        self.assertIn("member@example.com", logs.records[0].getMessage())

        with (
            patch.object(sync.requests, "get", return_value=response),
            self.assertNoLogs(sync.logger, level="INFO"),
        ):
            sync.update_grafana_team_members(10, [], [])

    def test_no_groups_logs_warning(self):
        with (
            patch.dict(
                os.environ,
                {
                    "GRAFANA_URL": "https://grafana.example.com",
                    "GRAFANA_API_KEY": "test-key",
                    "SYNC_GROUPS": "test-group",
                },
            ),
            patch.object(sync, "get_microsoft_token", return_value="token"),
            patch.object(sync, "get_azure_groups", return_value=[]),
            self.assertLogs(sync.logger, level="WARNING") as logs,
        ):
            sync.sync_teams()
        self.assertEqual(logs.records[0].levelno, logging.WARNING)
        self.assertEqual(logs.records[0].getMessage(), "No Azure AD groups found.")


if __name__ == "__main__":
    unittest.main()
