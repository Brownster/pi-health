from pathlib import Path

from scripts.migrate_runtime_state import ensure_helper_restart_coupling


def test_helper_restart_coupling_skips_when_helper_is_not_installed(tmp_path: Path):
    dropin, changed = ensure_helper_restart_coupling(tmp_path)

    assert dropin is None
    assert changed is False


def test_helper_restart_coupling_is_created_and_idempotent(tmp_path: Path):
    (tmp_path / "pihealth-helper.service").write_text("[Unit]\n", encoding="utf-8")

    dropin, changed = ensure_helper_restart_coupling(tmp_path)

    assert changed is True
    assert dropin == (
        tmp_path
        / "pihealth-helper.service.d"
        / "restart-with-pi-health.conf"
    )
    assert dropin.read_text(encoding="utf-8") == "[Unit]\nPartOf=pi-health.service\n"
    assert dropin.stat().st_mode & 0o777 == 0o644

    same_dropin, changed = ensure_helper_restart_coupling(tmp_path)
    assert same_dropin == dropin
    assert changed is False
