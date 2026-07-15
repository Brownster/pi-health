from unittest.mock import Mock

import metric_collector


def test_collect_once_records_current_system_stats(monkeypatch, tmp_path):
    stats = {"cpu_usage_percent": 12.5}
    system_service = Mock()
    system_service.stats.return_value = stats
    history_store = Mock()
    monkeypatch.setattr(metric_collector, "SystemService", Mock(return_value=system_service))
    monkeypatch.setattr(metric_collector, "MetricHistoryStore", Mock(return_value=history_store))
    database = tmp_path / "metrics.sqlite3"

    metric_collector.collect_once(database)

    metric_collector.MetricHistoryStore.assert_called_once_with(database)
    history_store.record.assert_called_once_with(stats)


def test_main_returns_nonzero_when_collection_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        metric_collector,
        "collect_once",
        Mock(side_effect=OSError("disk is read-only")),
    )

    assert metric_collector.main() == 1
    assert capsys.readouterr().err == "Metric collection failed: disk is read-only\n"
