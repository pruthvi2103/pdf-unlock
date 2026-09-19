# docker (not built)

Reserved for an on-prem container, for the case where unlocking has to happen on
a machine that is not a laptop.

Needs a real answer for secrets first: the OS keyring does not exist in a
container, so `secrets.py` would need a second backend (mounted file, or an
external secret store) before this is worth writing.
