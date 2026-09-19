# api (not built)

Reserved for an HTTP wrapper around `pdf_unlock_engine`: `POST /unlock` with a
file and an optional family name.

Worth building only once something other than a shell needs it. Note that the
engine's `unlock_pdf` writes to a path rather than returning bytes, so an API
would want a small in-memory variant alongside it.
