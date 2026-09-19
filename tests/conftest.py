"""Shared fixtures.

Every test runs against PDFs generated on the spot and an in-memory keyring, so
no real statement and no real password is ever involved.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    """Swap the OS keyring for a dict, so tests never touch the real Keychain."""
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self.store: dict[tuple[str, str], str] = {}

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def get_password(self, service, username):
            return self.store.get((service, username))

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the config at a throwaway file and clear the env overrides."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv("PDF_UNLOCK_CONFIG", str(path))
    monkeypatch.delenv("PDF_UNLOCK_OUT", raising=False)
    monkeypatch.delenv("PDF_UNLOCK_PASSWORD", raising=False)
    return path


@pytest.fixture
def make_pdf(tmp_path):
    """Build a PDF, optionally encrypted at a given security-handler revision."""
    import pikepdf

    def _make(name="doc.pdf", user=None, owner=None, revision=6, pages=1):
        path = tmp_path / name
        pdf = pikepdf.new()
        for _ in range(pages):
            pdf.add_blank_page(page_size=(612, 792))
        pdf.docinfo["/Producer"] = "Test Bank Statement Generator"
        pdf.docinfo["/Author"] = "Test Bank"

        if user is None and owner is None:
            pdf.save(path)
        else:
            pdf.save(
                path,
                encryption=pikepdf.Encryption(
                    user=user or "",
                    owner=owner or user or "",
                    R=revision,
                    # R < 4 is RC4: no AES, and the metadata stream stays in the clear.
                    aes=revision >= 4,
                    metadata=revision >= 4,
                ),
            )
        pdf.close()
        return path

    return _make
