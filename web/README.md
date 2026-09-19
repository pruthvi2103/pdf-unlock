# web (not built)

Reserved for a drag-and-drop page: drop a locked PDF, get a plain one back.

The catch worth thinking about before building it: the whole point of the engine
is that passwords stay in your own keyring. A hosted web version either asks for
the password every time (no families, no benefit) or holds your secrets on a
server. Local-only, served on `127.0.0.1`, is the version that makes sense.
