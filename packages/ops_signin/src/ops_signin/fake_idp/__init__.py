"""The local fake identity provider (`python -m ops_signin.fake_idp`); tests and the dev stack only."""

from .app import Idp, create_app, saml_response, self_signed, subject_of
from .dns import FakeDns

__all__ = ["FakeDns", "Idp", "create_app", "saml_response", "self_signed", "subject_of"]
