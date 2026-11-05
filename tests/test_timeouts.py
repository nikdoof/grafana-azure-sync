import importlib
import os
import unittest
from unittest.mock import Mock, patch

import requests

sync = importlib.import_module("grafana_azure_sync.main")


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(
            os.environ,
            {
                "TENANT_ID": "test-tenant",
                "CLIENT_ID": "test-client",
                "CLIENT_SECRET": "test-secret",
                "GRAFANA_URL": "https://grafana.example.com",
                "GRAFANA_API_KEY": "test-key",
            },
            clear=True,
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_fetch_helpers_pass_connect_and_read_timeouts(self):
        cases = (
            (
                "token",
                lambda: sync.get_microsoft_token(),
                "post",
                {"access_token": "token"},
            ),
            ("groups", lambda: sync.get_azure_groups("token"), "get", {"value": []}),
            (
                "group members",
                lambda: sync.get_group_members("group-1", "token"),
                "get",
                {"value": []},
            ),
            ("Grafana users", lambda: sync.get_grafana_users(), "get", []),
            ("Grafana teams", lambda: sync.get_grafana_teams(), "get", {"teams": []}),
        )
        for name, call_helper, method, payload in cases:
            with self.subTest(helper=name):
                response = Mock(status_code=200)
                response.json.return_value = payload
                with patch.object(
                    sync.requests, method, return_value=response
                ) as request:
                    call_helper()
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs["timeout"], (5, 30))

    def test_membership_reads_and_addition_pass_timeouts(self):
        before = Mock(status_code=200)
        before.json.return_value = []
        after = Mock(status_code=200)
        after.json.return_value = [{"userId": 7}]
        with (
            patch.object(sync.requests, "get", side_effect=[before, after]) as get,
            patch.object(
                sync.requests, "post", return_value=Mock(status_code=200)
            ) as post,
        ):
            sync.update_grafana_team_members(
                10,
                [{"userPrincipalName": "member@example.com"}],
                [{"email": "member@example.com", "userId": 7}],
            )
        self.assertEqual(get.call_count, 2)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"], {"userId": 7})
        for call in get.call_args_list + post.call_args_list:
            self.assertEqual(call.kwargs["timeout"], (5, 30))

    def test_read_timeout_propagates_without_retry_or_mutation(self):
        for timeout_type in (requests.ConnectTimeout, requests.ReadTimeout):
            with (
                self.subTest(timeout=timeout_type.__name__),
                patch.object(sync.requests, "get", side_effect=timeout_type) as get,
                patch.object(sync.requests, "post") as post,
            ):
                with self.assertRaises(timeout_type):
                    sync.update_grafana_team_members(10, [], [])
                get.assert_called_once()
                post.assert_not_called()

    def test_addition_timeout_propagates_without_retry(self):
        response = Mock(status_code=200)
        response.json.return_value = []
        with (
            patch.object(sync.requests, "get", return_value=response) as get,
            patch.object(
                sync.requests, "post", side_effect=requests.ReadTimeout
            ) as post,
        ):
            with self.assertRaises(requests.ReadTimeout):
                sync.update_grafana_team_members(
                    10,
                    [{"userPrincipalName": "member@example.com"}],
                    [{"email": "member@example.com", "userId": 7}],
                )
            get.assert_called_once()
            post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
