"""Trust primitives shared by the services that grant and check approvals. Mechanism only: which calls need an
approval, a step-up or two approvers is decided by the caller."""

from .cipher import AesGcmCipher, Cipher, CipherError, context_of
from .credentials import CredentialStore, CredentialUnreadable, InMemoryVault, RowSealed
from .jcs import CanonicalJsonError, canonicalize, input_hash
from .step_up import STEP_UP_TTL_S, StepUp, mint_step_up, verify_step_up
from .tokens import (
    Ed25519Signer,
    Ed25519Verifier,
    HmacSigner,
    Signer,
    TokenError,
    claims_of,
    header_of,
    mint,
    verify,
)

__all__ = [
    "STEP_UP_TTL_S",
    "AesGcmCipher",
    "CanonicalJsonError",
    "Cipher",
    "CipherError",
    "CredentialStore",
    "CredentialUnreadable",
    "Ed25519Signer",
    "Ed25519Verifier",
    "HmacSigner",
    "InMemoryVault",
    "RowSealed",
    "Signer",
    "StepUp",
    "TokenError",
    "canonicalize",
    "claims_of",
    "context_of",
    "header_of",
    "input_hash",
    "mint",
    "mint_step_up",
    "verify",
    "verify_step_up",
]
