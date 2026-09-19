"""End-to-end tests through the CLI entry point.

`--no-open` everywhere, so nothing ever launches Preview during a test run.
"""

import json

import pytest

from pdf_unlock_cli.main import main
from pdf_unlock_engine import load_config
from pdf_unlock_engine.secrets import IDENTITY, PASSWORD, get_secret


def run(*argv):
    return main(list(argv))


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "unlocked"
    d.mkdir()
    return d


def test_bare_file_argument_means_unlock(make_pdf, out_dir, capsys):
    src = make_pdf("stmt.pdf", user="pw")
    assert run(str(src), "-p", "pw", "-o", str(out_dir), "--no-open") == 0
    assert (out_dir / "stmt.pdf").is_file()
    assert "stmt.pdf" in capsys.readouterr().out


def test_flags_before_the_filename_still_mean_unlock(make_pdf, out_dir):
    src = make_pdf("stmt.pdf", user="pw")
    assert run("-p", "pw", "-o", str(out_dir), "--no-open", str(src)) == 0
    assert (out_dir / "stmt.pdf").is_file()


def test_explicit_subcommand_is_left_alone(make_pdf, capsys):
    run("inspect", str(make_pdf("stmt.pdf", user="pw")))
    assert "locked" in capsys.readouterr().out


def test_wrong_password_exits_nonzero_and_writes_nothing(make_pdf, out_dir, capsys):
    src = make_pdf("stmt.pdf", user="right")
    code = run(str(src), "-p", "wrong", "-o", str(out_dir), "--no-open", "--no-prompt")
    assert code != 0
    assert list(out_dir.iterdir()) == []
    assert "rejected" in capsys.readouterr().err


def test_password_from_the_environment(make_pdf, out_dir, monkeypatch):
    monkeypatch.setenv("PDF_UNLOCK_PASSWORD", "pw")
    src = make_pdf("stmt.pdf", user="pw")
    assert run(str(src), "-o", str(out_dir), "--no-open") == 0
    assert (out_dir / "stmt.pdf").is_file()


def test_a_plain_pdf_is_reported_not_copied(make_pdf, out_dir, capsys):
    assert run(str(make_pdf("plain.pdf")), "-o", str(out_dir), "--no-open") == 0
    assert list(out_dir.iterdir()) == []
    assert "not encrypted" in capsys.readouterr().out


def test_json_output_is_machine_readable(make_pdf, out_dir, capsys):
    src = make_pdf("stmt.pdf", user="pw")
    run(str(src), "-p", "pw", "-o", str(out_dir), "--no-open", "--json")
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("[") :])
    assert payload[0]["status"] == "unlocked"
    assert payload[0]["password_source"] == "--password"


def test_several_files_in_one_run(make_pdf, out_dir):
    a = make_pdf("a.pdf", user="pw")
    b = make_pdf("b.pdf", user="pw")
    assert run(str(a), str(b), "-p", "pw", "-o", str(out_dir), "--no-open") == 0
    assert {p.name for p in out_dir.iterdir()} == {"a.pdf", "b.pdf"}


def test_one_bad_file_does_not_stop_the_rest(make_pdf, out_dir, tmp_path):
    good = make_pdf("good.pdf", user="pw")
    junk = tmp_path / "junk.pdf"
    junk.write_text("not a pdf")

    code = run(str(junk), str(good), "-p", "pw", "-o", str(out_dir), "--no-open")
    assert code != 0
    assert (out_dir / "good.pdf").is_file()


# --------------------------------------------------------------------------- #
# the family workflow, end to end
# --------------------------------------------------------------------------- #


def test_the_whole_family_workflow(make_pdf, out_dir, capsys):
    # The password an HDFC statement would really carry for this person.
    src = make_pdf("HDFC_Statement_Aug.pdf", user="PRUT1405")

    assert run("identity", "set", "name", "Pruthvi Shetty") == 0
    assert run("identity", "set", "dob", "1990-05-14") == 0
    assert run("family", "add", "--preset", "hdfc-cc") == 0
    capsys.readouterr()

    # No password on the command line at all.
    assert run(str(src), "-o", str(out_dir), "--no-open") == 0
    out = capsys.readouterr().out
    assert (out_dir / "HDFC_Statement_Aug.pdf").is_file()
    assert "family hdfc-cc" in out


def test_identity_values_go_to_the_keyring_not_the_config(isolated_config):
    run("identity", "set", "dob", "1990-05-14")
    assert get_secret(IDENTITY, "dob") == "1990-05-14"
    assert load_config().identity_fields == ["dob"]
    assert "1990-05-14" not in isolated_config.read_text()


def test_stored_passwords_go_to_the_keyring_not_the_config(isolated_config):
    run("password", "set", "hdfc-old", "hunter2")
    assert get_secret(PASSWORD, "hdfc-old") == "hunter2"
    assert "hunter2" not in isolated_config.read_text()


def test_identity_list_masks_values(capsys):
    run("identity", "set", "dob", "1990-05-14")
    capsys.readouterr()
    run("identity", "list")
    out = capsys.readouterr().out
    assert "1990-05-14" not in out
    assert "•" in out


def test_identity_rm(capsys):
    run("identity", "set", "dob", "1990-05-14")
    assert run("identity", "rm", "dob") == 0
    assert get_secret(IDENTITY, "dob") is None
    assert load_config().identity_fields == []


def test_family_test_masks_by_default_and_reveals_on_request(capsys):
    run("identity", "set", "name", "Pruthvi Shetty")
    run("identity", "set", "dob", "1990-05-14")
    run("family", "add", "--preset", "hdfc-cc")
    capsys.readouterr()

    run("family", "test", "hdfc-cc")
    assert "PRUT1405" not in capsys.readouterr().out

    run("family", "test", "hdfc-cc", "--show")
    assert "PRUT1405" in capsys.readouterr().out


def test_family_test_against_a_real_file(make_pdf, capsys):
    src = make_pdf("HDFC_Aug.pdf", user="PRUT1405")
    run("identity", "set", "name", "Pruthvi Shetty")
    run("identity", "set", "dob", "1990-05-14")
    run("family", "add", "--preset", "hdfc-cc")
    capsys.readouterr()

    assert run("family", "test", "hdfc-cc", str(src)) == 0
    assert "it opens" in capsys.readouterr().out


def test_family_test_reports_a_recipe_that_does_not_work(make_pdf, capsys):
    src = make_pdf("HDFC_Aug.pdf", user="something-else")
    run("identity", "set", "name", "Pruthvi Shetty")
    run("identity", "set", "dob", "1990-05-14")
    run("family", "add", "--preset", "hdfc-cc")
    capsys.readouterr()

    assert run("family", "test", "hdfc-cc", str(src)) != 0
    assert "does not open" in capsys.readouterr().err


def test_family_add_rejects_both_template_and_secret(capsys):
    code = run("family", "add", "x", "--template", "{name}", "--secret", "label")
    assert code != 0
    assert "exactly one" in capsys.readouterr().err


def test_family_add_will_not_silently_replace(capsys):
    run("family", "add", "--preset", "hdfc-cc")
    capsys.readouterr()
    assert run("family", "add", "--preset", "hdfc-cc") != 0
    assert "already exists" in capsys.readouterr().err
    assert run("family", "add", "--preset", "hdfc-cc", "--force") == 0


def test_dry_run_explains_itself_and_writes_nothing(make_pdf, out_dir, capsys):
    src = make_pdf("HDFC_Aug.pdf", user="PRUT1405")
    run("identity", "set", "name", "Pruthvi Shetty")
    run("identity", "set", "dob", "1990-05-14")
    run("family", "add", "--preset", "hdfc-cc")
    capsys.readouterr()

    assert run(str(src), "-o", str(out_dir), "--dry-run", "--no-open") == 0
    out = capsys.readouterr().out
    assert "hdfc-cc" in out
    assert list(out_dir.iterdir()) == []


def test_config_set_and_show(isolated_config, capsys, tmp_path):
    assert run("config", "set", "output_dir", str(tmp_path / "elsewhere")) == 0
    assert run("config", "set", "open_after", "false") == 0
    cfg = load_config()
    assert str(cfg.output_dir) == str(tmp_path / "elsewhere")
    assert cfg.open_after is False

    capsys.readouterr()
    run("config", "show")
    assert "output_dir" in capsys.readouterr().out


def test_config_output_dir_is_used_when_no_flag_is_given(make_pdf, tmp_path, capsys):
    dest = tmp_path / "configured"
    run("config", "set", "output_dir", str(dest))
    run("config", "set", "open_after", "false")
    capsys.readouterr()

    src = make_pdf("stmt.pdf", user="pw")
    assert run(str(src), "-p", "pw") == 0
    assert (dest / "stmt.pdf").is_file()


def test_shell_init_defines_the_output_dir_helper(capsys):
    assert run("shell-init") == 0
    out = capsys.readouterr().out
    # The binary is already called pdf-unlock, so the snippet must not shadow it.
    assert "pdf-unlocked()" in out
    assert "\nunlock()" not in out


def test_no_arguments_prints_help(capsys):
    assert run() != 0
    assert "usage" in capsys.readouterr().out.lower()


def test_shell_init_emits_valid_zsh():
    """The snippet is a raw string; a stray escape here silently breaks the shell."""
    import subprocess

    from pdf_unlock_cli.main import SHELL_SNIPPET

    result = subprocess.run(
        ["zsh", "-n"], input=SHELL_SNIPPET, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "\\~" in SHELL_SNIPPET, "the tilde must stay escaped for zsh"
