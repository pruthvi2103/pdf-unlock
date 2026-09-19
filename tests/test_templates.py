import pytest

from pdf_unlock_engine.templates import TemplateError, fields_used, render

IDENTITY = {
    "name": "Pruthvi Shetty",
    "surname": "Shetty",
    "dob": "1990-05-14",
    "card_last4": "4321",
    "customer_id": "CUST-009812",
}


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        # The recipe most Indian card issuers actually use.
        ("{name|alpha|lower|first:4}{dob|date:%d%m}", "prut1405"),
        # Shorthands should mean exactly the same thing.
        ("{name:4}{dob:%d%m}", "Prut1405"),
        ("{surname|upper|first:3}", "SHE"),
        ("{card_last4|last:4}", "4321"),
        ("{customer_id|digits}", "009812"),
        ("{dob|date:%d%m%Y}", "14051990"),
        ("{dob:-4}", "5-14"),
        # Literal text and escaped braces survive.
        ("stmt-{surname|lower}-{{x}}", "stmt-shetty-{x}"),
        ("no placeholders", "no placeholders"),
    ],
)
def test_render(template, expected):
    assert render(template, IDENTITY) == expected


def test_render_names_the_missing_field():
    with pytest.raises(TemplateError, match="'pan'"):
        render("{pan|first:4}", IDENTITY)


def test_empty_field_counts_as_missing():
    with pytest.raises(TemplateError, match="'name'"):
        render("{name:4}", {"name": ""})


def test_unknown_step_lists_the_real_ones():
    with pytest.raises(TemplateError, match="unknown step 'shout'"):
        render("{name|shout}", IDENTITY)


def test_date_step_rejects_a_non_date():
    with pytest.raises(TemplateError, match="not one"):
        render("{name|date:%d%m}", IDENTITY)


@pytest.mark.parametrize("written", ["1990-05-14", "14/05/1990", "14-05-1990", "14051990"])
def test_dob_accepts_the_formats_people_type(written):
    assert render("{dob|date:%d%m}", {"dob": written}) == "1405"


def test_first_needs_a_positive_number():
    with pytest.raises(TemplateError, match="positive number"):
        render("{name|first:0}", IDENTITY)


def test_fields_used_reports_in_order_without_duplicates():
    assert fields_used("{name:4}{dob:%d%m}{name|upper}") == ["name", "dob"]
