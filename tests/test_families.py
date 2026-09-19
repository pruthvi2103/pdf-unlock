import pytest

from pdf_unlock_engine import (
    Config,
    ConfigError,
    Family,
    MatchRules,
    build_plan,
    inspect_pdf,
    match_family,
    preset,
    rank_families,
)
from pdf_unlock_engine.secrets import IDENTITY, PASSWORD, set_secret

HDFC = Family(
    name="hdfc-cc",
    match=MatchRules(filename=["*hdfc*"]),
    template="{name|alpha|upper|first:4}{dob|date:%d%m}",
)
AMEX = Family(
    name="amex",
    match=MatchRules(filename=["*amex*"], producer="American Express"),
    secret="amex-pw",
)


def test_a_family_needs_exactly_one_of_template_or_secret():
    with pytest.raises(ConfigError, match="exactly one"):
        Family(name="broken", template="{name}", secret="label")
    with pytest.raises(ConfigError, match="exactly one"):
        Family(name="broken")


def test_a_bad_template_is_caught_when_the_family_is_built():
    with pytest.raises(Exception, match="unknown step"):
        Family(name="oops", template="{name|shout}")


def test_filename_matching_is_case_insensitive(make_pdf):
    info = inspect_pdf(make_pdf("HDFC_Statement_Aug.pdf", user="pw"))
    assert match_family(info, [AMEX, HDFC]) is HDFC


def test_no_match_returns_none(make_pdf):
    info = inspect_pdf(make_pdf("Kotak_July.pdf", user="pw"))
    assert match_family(info, [AMEX, HDFC]) is None


def test_metadata_rules_break_a_filename_tie(make_pdf):
    # This file is readable, so /Producer is visible and the more specific family wins.
    path = make_pdf("amex_statement.pdf")
    info = inspect_pdf(path)
    generic = Family(name="generic", match=MatchRules(filename=["*amex*"]), secret="x")
    specific = Family(
        name="specific",
        match=MatchRules(filename=["*amex*"], producer="Test Bank"),
        secret="x",
    )
    ranked = rank_families(info, [generic, specific])
    assert [f.name for f, _ in ranked] == ["specific", "generic"]


def test_presets_render_against_real_identity_fragments():
    fam = preset("hdfc-cc")
    assert fam.needs_fields == ["name", "dob"]
    assert fam.note


def test_plan_puts_the_matching_family_first(make_pdf):
    set_secret(IDENTITY, "name", "Pruthvi Shetty")
    set_secret(IDENTITY, "dob", "1990-05-14")
    set_secret(PASSWORD, "amex-pw", "amexsecret")

    cfg = Config(identity_fields=["name", "dob"], password_labels=[], families=[AMEX, HDFC])
    info = inspect_pdf(make_pdf("HDFC_Aug.pdf", user="PRUT1405"))
    plan = build_plan(info, cfg)

    assert [f.name for f in plan.matched] == ["hdfc-cc"]
    assert plan.candidates[0].password == "PRUT1405"
    assert plan.candidates[0].source == "family hdfc-cc"
    # The unmatched family is still worth a try, just later and labelled as such.
    assert "amexsecret" in [c.password for c in plan.candidates]
    assert any("fallback" in c.source for c in plan.candidates)


def test_no_fallback_keeps_only_matching_families(make_pdf):
    set_secret(IDENTITY, "name", "Pruthvi Shetty")
    set_secret(IDENTITY, "dob", "1990-05-14")
    set_secret(PASSWORD, "amex-pw", "amexsecret")

    cfg = Config(identity_fields=["name", "dob"], families=[AMEX, HDFC])
    info = inspect_pdf(make_pdf("HDFC_Aug.pdf", user="PRUT1405"))
    plan = build_plan(info, cfg, try_all=False)

    assert [c.password for c in plan.candidates] == ["PRUT1405"]


def test_a_missing_identity_field_warns_instead_of_exploding(make_pdf):
    cfg = Config(identity_fields=["name"], families=[HDFC])
    info = inspect_pdf(make_pdf("HDFC_Aug.pdf", user="pw"))
    plan = build_plan(info, cfg)

    assert plan.candidates == [] or all(c.source.startswith("no password") for c in plan.candidates)
    assert any("dob" in w for w in plan.warnings)


def test_plan_warns_when_a_stored_password_is_missing(make_pdf):
    cfg = Config(families=[AMEX])
    info = inspect_pdf(make_pdf("amex_bill.pdf", user="pw"))
    plan = build_plan(info, cfg)
    assert any("amex-pw" in w and "keyring" in w for w in plan.warnings)


def test_forcing_an_unknown_family_warns(make_pdf):
    cfg = Config(families=[HDFC])
    info = inspect_pdf(make_pdf("x.pdf", user="pw"))
    plan = build_plan(info, cfg, only_family="nope")
    assert plan.candidates == []
    assert any("no family named" in w for w in plan.warnings)


def test_plan_always_tries_the_empty_password_last(make_pdf):
    cfg = Config()
    info = inspect_pdf(make_pdf("restricted.pdf", user="", owner="own", revision=4))
    plan = build_plan(info, cfg)
    assert [c.password for c in plan.candidates] == [""]


# --------------------------------------------------------------------------- #
# preset regressions
# --------------------------------------------------------------------------- #


def test_hdfc_preset_uppercases_the_name():
    """Verified against a real HDFC credit card statement: the name is CAPS.

    The preset originally shipped `|lower` and silently failed on every file.
    """
    from pdf_unlock_engine.templates import render

    fam = preset("hdfc-cc")
    identity = {"name": "Pruthvi Shetty", "dob": "1990-05-14"}
    assert render(fam.template, identity) == "PRUT1405"


def test_name_case_does_not_leak_into_the_password():
    """However the name is stored, the rendered password is the same."""
    from pdf_unlock_engine.templates import render

    fam = preset("hdfc-cc")
    rendered = {
        render(fam.template, {"name": spelling, "dob": "1990-05-14"})
        for spelling in ("Pruthvi Shetty", "PRUTHVI SHETTY", "pruthvi shetty", "PRUTHVI")
    }
    assert rendered == {"PRUT1405"}


def test_every_preset_records_whether_it_was_verified():
    from pdf_unlock_engine.families import PRESETS

    assert all("verified" in spec for spec in PRESETS.values())
    # Exactly one has been checked against a real statement so far.
    assert [k for k, v in PRESETS.items() if v["verified"]] == ["hdfc-cc"]


def test_presets_do_not_claim_files_by_card_number():
    """A Visa number starts with 4 whoever issued it, so no preset may match on one."""
    from pdf_unlock_engine.families import PRESETS

    for key, spec in PRESETS.items():
        for pattern in spec["filename"]:
            assert not pattern[0].isdigit(), f"{key} claims files by card number: {pattern}"


def test_every_preset_builds_and_renders():
    from pdf_unlock_engine.families import PRESETS
    from pdf_unlock_engine.templates import render

    identity = {
        "name": "Pruthvi Shetty",
        "surname": "Shetty",
        "dob": "1990-05-14",
        "card_last4": "4321",
        "customer_id": "CUST-009812",
    }
    for key in PRESETS:
        fam = preset(key)
        assert render(fam.template, identity)
