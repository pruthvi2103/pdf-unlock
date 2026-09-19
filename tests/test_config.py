import pytest

from pdf_unlock_engine import Config, ConfigError, Family, MatchRules, load_config, save_config
from pdf_unlock_engine.config import dumps


def test_defaults_when_no_file_exists(isolated_config):
    cfg = load_config()
    assert cfg.path is None
    assert str(cfg.output_dir) == "~/Documents/unlocked"
    assert cfg.open_after is True
    # The output directory is derived data, so replacing it is safe by default.
    assert cfg.overwrite is True


def test_round_trip(isolated_config):
    cfg = Config(
        output_dir="~/statements",
        open_after=False,
        copy_path=True,
        suffix=".unlocked",
        identity_fields=["dob", "name"],
        password_labels=["old-hdfc"],
        families=[
            Family(
                name="hdfc-cc",
                match=MatchRules(filename=["*hdfc*", "*HDFC*"], producer="HDFC"),
                template="{name:4}{dob:%d%m}",
                note="name + DDMM",
            ),
            Family(name="amex", match=MatchRules(filename=["*amex*"]), secret="amex-pw"),
        ],
    )
    save_config(cfg, isolated_config)
    back = load_config(isolated_config)

    assert str(back.output_dir) == "~/statements"
    assert back.open_after is False and back.copy_path is True
    assert back.suffix == ".unlocked"
    assert back.identity_fields == ["dob", "name"]
    assert [f.name for f in back.families] == ["hdfc-cc", "amex"]
    assert back.family("hdfc-cc").template == "{name:4}{dob:%d%m}"
    assert back.family("hdfc-cc").match.producer == "HDFC"
    assert back.family("amex").secret == "amex-pw"


def test_the_config_file_never_contains_a_password(isolated_config):
    cfg = Config(password_labels=["amex-pw"], families=[
        Family(name="amex", match=MatchRules(filename=["*amex*"]), secret="amex-pw")
    ])
    text = dumps(cfg)
    # Only the label appears; the value lives in the keyring.
    assert "amex-pw" in text
    assert "secret =" in text and "password =" not in text


def test_quotes_and_backslashes_survive(isolated_config):
    cfg = Config(families=[
        Family(
            name="odd",
            match=MatchRules(filename_regex=[r"stmt\d{4}\.pdf"]),
            template='{name}"x"',
        )
    ])
    save_config(cfg, isolated_config)
    back = load_config(isolated_config)
    assert back.family("odd").match.filename_regex == [r"stmt\d{4}\.pdf"]
    assert back.family("odd").template == '{name}"x"'


def test_malformed_toml_is_reported_with_the_path(isolated_config):
    isolated_config.write_text("output_dir = [unclosed")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(isolated_config)


def test_duplicate_family_names_are_rejected(isolated_config):
    isolated_config.write_text(
        '[[family]]\nname = "a"\nsecret = "x"\n\n[[family]]\nname = "a"\nsecret = "y"\n'
    )
    with pytest.raises(ConfigError, match="duplicate family"):
        load_config(isolated_config)


def test_a_family_without_a_name_is_rejected(isolated_config):
    isolated_config.write_text('[[family]]\nsecret = "x"\n')
    with pytest.raises(ConfigError, match="needs a name"):
        load_config(isolated_config)


def test_env_overrides_the_output_dir(isolated_config, monkeypatch):
    save_config(Config(output_dir="~/from-file"), isolated_config)
    monkeypatch.setenv("PDF_UNLOCK_OUT", "/tmp/from-env")
    assert str(load_config(isolated_config).output_dir) == "/tmp/from-env"
