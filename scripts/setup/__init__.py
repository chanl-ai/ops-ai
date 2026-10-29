"""`make setup` (c-545): asks what a person has, tests each answer live, and writes settings only for what passed.
Every check uses the standard library except the database driver, so it runs before `make install`."""

import os
import ssl
from pathlib import Path


def trust_store() -> None:
    """python.org's macOS Python ships no CA bundle until its Install Certificates step runs, so every HTTPS check
    fails there while curl works; certifi's bundle stands in when the default one is missing."""
    if os.environ.get("SSL_CERT_FILE") or Path(ssl.get_default_verify_paths().openssl_cafile).exists():
        return
    try:
        import certifi  # noqa: PLC0415 - optional, and setup starts before make install
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()
