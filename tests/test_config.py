import pytest

from teams_notifier.config import DEFAULT_CLIENT_ID, load_config
from teams_notifier.errors import ConfigError


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "yok.toml")
    assert cfg.path is None
    assert cfg.auth.client_id == DEFAULT_CLIENT_ID
    assert cfg.reminders.thresholds_days == [3, 1, 0]
    assert cfg.assignments.enabled is False
    assert cfg.download.enabled is False
    assert str(cfg.tz) == "Europe/Istanbul"


def test_values_are_read(tmp_path):
    cfg = load_config(write(tmp_path, '[ntfy]\ntopic = "abc"\n[files]\nnotify_updates = true\n'))
    assert cfg.ntfy.topic == "abc"
    assert cfg.files.notify_updates is True


def test_explicit_client_id_wins(tmp_path):
    cfg = load_config(write(tmp_path, '[auth]\nclient_id = "my-id"\n'))
    assert cfg.auth.client_id == "my-id"


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="topik"):
        load_config(write(tmp_path, '[ntfy]\ntopik = "x"\n'))


def test_unknown_section_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[nope]\na = 1\n"))


def test_wrong_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, '[download]\nmax_size_mb = "200"\n'))


def test_bool_is_not_accepted_as_int(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[download]\nmax_size_mb = true\n"))


def test_bad_timezone_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, '[schedule]\ntimezone = "Mars/Base"\n'))


def test_negative_threshold_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[reminders]\nthresholds_days = [3, -1]\n"))


def test_ntfy_server_scheme_is_checked(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, '[ntfy]\nserver = "ntfy.sh"\n'))


def test_broken_toml_is_reported(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[ntfy\n"))
