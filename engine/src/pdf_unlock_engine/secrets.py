"""Secret storage, backed by the OS keyring (macOS Keychain, on this machine).

The split that matters: the config file holds the *shape* of things -- which
identity fields exist, which password labels exist, what the families are -- and
the keyring holds the *values*. Nothing secret is ever written to disk by us, and
a config file can be read, diffed, or even committed without leaking anything.
"""

from __future__ import annotations

from .errors import SecretsError

SERVICE = "pdf-unlock"

IDENTITY = "identity"
PASSWORD = "password"


def key_for(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SecretsError(f"the keyring package is unavailable: {exc}") from exc

    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        raise SecretsError(
            "no OS keyring backend is available, so passwords cannot be stored securely. "
            "On macOS this should be Keychain -- check that the `keyring` install is intact."
        )
    return keyring


def set_secret(kind: str, name: str, value: str) -> None:
    if not value:
        raise SecretsError("refusing to store an empty secret")
    try:
        _keyring().set_password(SERVICE, key_for(kind, name), value)
    except SecretsError:
        raise
    except Exception as exc:
        raise SecretsError(f"could not write {kind} {name!r} to the keyring: {exc}") from exc


def get_secret(kind: str, name: str) -> str | None:
    try:
        return _keyring().get_password(SERVICE, key_for(kind, name))
    except SecretsError:
        raise
    except Exception as exc:
        raise SecretsError(f"could not read {kind} {name!r} from the keyring: {exc}") from exc


def delete_secret(kind: str, name: str) -> bool:
    """Returns True if something was deleted, False if there was nothing there."""
    keyring = _keyring()
    try:
        if keyring.get_password(SERVICE, key_for(kind, name)) is None:
            return False
        keyring.delete_password(SERVICE, key_for(kind, name))
        return True
    except Exception as exc:
        raise SecretsError(f"could not delete {kind} {name!r} from the keyring: {exc}") from exc


def load_identity(fields: list[str]) -> dict[str, str]:
    """Fetch every identity fragment the config knows about. Missing ones are skipped."""
    out: dict[str, str] = {}
    for name in fields:
        value = get_secret(IDENTITY, name)
        if value:
            out[name] = value
    return out
