"""Unprivileged repair-job target and output boundaries."""

import json

import plugin_manager
import agent_actions.repair_job as repair_job

from agent_actions.repair_job import inspect_extension, main


def _configure_extension(tmp_path, monkeypatch, *, enabled=True):
    config = tmp_path / "plugins.json"
    config.write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "id": "weather",
                        "type": "github",
                        "source": "https://example.test/weather.git",
                        "entry": "plugin.py",
                        "class_name": "WeatherPlugin",
                        "enabled": enabled,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(plugin_manager, "CONFIG_FILE", str(config))
    monkeypatch.setattr(plugin_manager, "PLUGIN_DIR", str(tmp_path / "plugins"))


def test_extension_status_can_repair_a_missing_configured_checkout(
    tmp_path, monkeypatch
):
    _configure_extension(tmp_path, monkeypatch)

    status = inspect_extension("weather")

    assert status == {
        "name": "weather",
        "type": "github",
        "enabled": True,
        "installed": False,
        "source_configured": True,
        "repairable": True,
        "registered": False,
        "status": "missing",
    }
    assert "source" not in status


def test_extension_status_rejects_unconfigured_and_path_targets(
    tmp_path, monkeypatch, capsys
):
    _configure_extension(tmp_path, monkeypatch, enabled=False)

    status = inspect_extension("weather")
    result = main(["extension-status", "--name", "."])

    assert status["repairable"] is False
    assert result == 1
    assert "invalid" in capsys.readouterr().err.lower()


def test_mattermost_status_drops_private_fields_and_repair_uses_service(monkeypatch):
    class Service:
        repaired = False

        def status(self):
            return {
                "state": "connected",
                "installed": True,
                "stack_name": "mattermost",
                "webhook_configured": True,
                "admin_email": "private@example.test",
                "services": {
                    "limeos-mattermost": {
                        "state": "running",
                        "health": "healthy",
                        "container_id": "private-id",
                    }
                },
            }

        def repair(self):
            self.repaired = True

    service = Service()
    monkeypatch.setattr(repair_job, "_mattermost_service", lambda: service)

    result = repair_job.repair_mattermost()

    assert service.repaired is True
    assert result["services"] == [
        {
            "name": "limeos-mattermost",
            "state": "running",
            "health": "healthy",
        }
    ]
    assert "admin_email" not in result
    assert "container_id" not in result["services"][0]
