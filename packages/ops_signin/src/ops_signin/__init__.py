"""Sign-in protocols with no service rules. Each returns a `VerifiedIdentity` or raises `SignInRefused`; which
provider a workspace uses, its secrets, and what happens to the person afterwards are the calling service's."""

from .identity import CertificateExpired, SignInRefused, VerifiedIdentity
from .oidc import OidcClient, OidcConfig, OidcStart
from .password import PasswordHasher
from .saml import SamlConfig, SamlServiceProvider, SamlStart

__all__ = [
    "CertificateExpired",
    "OidcClient",
    "OidcConfig",
    "OidcStart",
    "PasswordHasher",
    "SamlConfig",
    "SamlServiceProvider",
    "SamlStart",
    "SignInRefused",
    "VerifiedIdentity",
]
