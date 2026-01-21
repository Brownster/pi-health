from storage_plugins.snapraid_logtags import parse_log_tags


def test_parse_summary_and_exit():
    text = "\n".join([
        "summary:added:5",
        "summary:removed:2",
        "summary:exit:diff",
    ])
    result = parse_log_tags(text).to_dict()
    assert result["summary"]["added"] == 5
    assert result["summary"]["removed"] == 2
    assert result["summary"]["exit"] == "diff"


def test_parse_run_progress():
    text = "run:pos:10:20:300:40:120:15.5:3.2:900"
    result = parse_log_tags(text).to_dict()
    progress = result["run_progress"]
    assert progress["blockpos"] == 10
    assert progress["countpos"] == 20
    assert progress["countsize"] == 300
    assert progress["percent"] == 40
    assert progress["eta"] == 120
    assert progress["size_speed"] == 15.5
    assert progress["cpu"] == 3.2
    assert progress["elapsed"] == 900


def test_parse_scan_counts_and_messages():
    text = "\n".join([
        "scan:add:d1:Movies/Example.mkv",
        "scan:add:d1:Movies/Other.mkv",
        "scan:remove:d2:Old/Thing.mkv",
        "msg:status:hello\\dworld",
    ])
    result = parse_log_tags(text).to_dict()
    assert result["scan_counts"]["add"] == 2
    assert result["scan_counts"]["remove"] == 1
    assert result["messages"][0]["level"] == "status"
    assert result["messages"][0]["message"] == "hello:world"
