import os
import stat

import pytest

from pdf_unlock_engine import (
    NotAPdfError,
    NotEncryptedError,
    OutputExistsError,
    WrongPasswordError,
    find_password,
    inspect_pdf,
    output_path_for,
    unlock_pdf,
    verify_password,
)

# Revision 2 is RC4-40, 3 is RC4-128, 4 is AES-128, 6 is AES-256. Banks use all of them.
REVISIONS = [2, 3, 4, 6]


@pytest.mark.parametrize("revision", REVISIONS)
def test_unlock_every_revision_banks_use(make_pdf, tmp_path, revision):
    src = make_pdf(f"r{revision}.pdf", user="s3cret", revision=revision, pages=3)
    dest = tmp_path / "out" / "plain.pdf"

    result = unlock_pdf(src, dest, password="s3cret")

    assert result.output == dest
    assert dest.is_file()
    assert result.page_count == 3
    # The unlocked copy really is open now.
    assert inspect_pdf(dest).encrypted is False
    # And the encrypted original is untouched.
    assert inspect_pdf(src).needs_password is True


def test_inspect_reports_a_locked_file_without_the_password(make_pdf):
    info = inspect_pdf(make_pdf(user="pw"))
    assert info.encrypted and info.needs_password
    # Metadata stays hidden until it is open, which is why families match on filename.
    assert info.producer is None


def test_inspect_reads_metadata_when_the_file_is_open(make_pdf):
    info = inspect_pdf(make_pdf())
    assert info.encrypted is False
    assert info.producer == "Test Bank Statement Generator"
    assert info.author == "Test Bank"


def test_owner_password_only_opens_with_an_empty_password(make_pdf, tmp_path):
    src = make_pdf("restricted.pdf", user="", owner="ownerpw", revision=4)
    info = inspect_pdf(src)

    assert info.encrypted and not info.needs_password
    assert info.restrictions_only

    result = unlock_pdf(src, tmp_path / "free.pdf", password="")
    assert result.restrictions_only
    assert inspect_pdf(result.output).encrypted is False


def test_wrong_password_leaves_nothing_behind(make_pdf, tmp_path):
    src = make_pdf(user="right")
    dest = tmp_path / "out" / "plain.pdf"

    with pytest.raises(WrongPasswordError):
        unlock_pdf(src, dest, password="wrong")

    assert not dest.exists()
    assert list((tmp_path / "out").glob("*")) == []


def test_unlocking_a_plain_pdf_says_so(make_pdf, tmp_path):
    with pytest.raises(NotEncryptedError):
        unlock_pdf(make_pdf(), tmp_path / "out.pdf")


def test_output_is_owner_readable_only(make_pdf, tmp_path):
    result = unlock_pdf(make_pdf(user="pw"), tmp_path / "out.pdf", password="pw")
    mode = stat.S_IMODE(os.stat(result.output).st_mode)
    assert mode == 0o600


def test_verify_password(make_pdf):
    src = make_pdf(user="open-sesame")
    assert verify_password(src, "open-sesame") is True
    assert verify_password(src, "nope") is False


def test_find_password_returns_the_first_that_works(make_pdf):
    src = make_pdf(user="third")
    hit = find_password(src, [("first", "a"), ("second", "b"), ("third", "c")])
    assert hit == ("third", "c")


def test_find_password_tries_the_empty_password_but_not_duplicates(make_pdf):
    src = make_pdf(user="only")
    assert find_password(src, [("x", "a"), ("x", "b"), ("", "c")]) is None


def test_find_password_accepts_the_empty_password(make_pdf):
    # Owner-restrictions-only files open with no password at all.
    src = make_pdf("restricted.pdf", user="", owner="own", revision=4)
    assert find_password(src, [("wrong", "a"), ("", "empty")]) == ("", "empty")


def test_not_a_pdf(tmp_path):
    junk = tmp_path / "notes.pdf"
    junk.write_text("this is not a PDF")
    with pytest.raises(NotAPdfError):
        inspect_pdf(junk)


def test_missing_file(tmp_path):
    with pytest.raises(NotAPdfError, match="no such file"):
        inspect_pdf(tmp_path / "ghost.pdf")


def test_output_path_refuses_to_overwrite_the_original(make_pdf, tmp_path):
    src = make_pdf("statement.pdf", user="pw")
    with pytest.raises(OutputExistsError, match="encrypted original"):
        output_path_for(src, tmp_path)


def test_output_path_next_to_the_original_needs_a_suffix(make_pdf, tmp_path):
    src = make_pdf("statement.pdf", user="pw")
    assert output_path_for(src, tmp_path, suffix=".unlocked").name == "statement.unlocked.pdf"


def test_output_path_honours_overwrite(make_pdf, tmp_path):
    src = make_pdf("statement.pdf", user="pw")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "statement.pdf").write_text("stale")

    with pytest.raises(OutputExistsError, match="already exists"):
        output_path_for(src, out_dir, overwrite=False)
    assert output_path_for(src, out_dir, overwrite=True).name == "statement.pdf"
