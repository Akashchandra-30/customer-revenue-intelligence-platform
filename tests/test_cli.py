from unittest import mock

import pytest

from revintel import cli


def test_parser_defaults():
    args = cli.build_parser().parse_args(["run", "--generate"])
    assert (args.target, args.load_mode, args.generate) == ("local", "direct", True)


def test_rejects_unknown_target():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["ingest", "--target", "staging"])


def test_failure_returns_nonzero_and_alerts(settings):
    settings.alert_webhook_url = None
    with (
        mock.patch.object(cli, "get_settings", return_value=settings),
        mock.patch.object(cli, "ingest", side_effect=RuntimeError("source missing")),
        mock.patch.object(cli, "send_alert") as alert,
    ):
        assert cli.main(["ingest", "--run-id", "r-1"]) == 1
    title, detail = alert.call_args.args[1:]
    assert "ingest failed" in title and "source missing" in detail
