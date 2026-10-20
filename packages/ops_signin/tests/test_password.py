"""The password hasher, by failure mode: a stored password, a wrong password accepted, a foreign hash crashing."""

from __future__ import annotations

from ops_signin import PasswordHasher

H = PasswordHasher(iterations=1_000)


def test_the_hash_keeps_no_password_and_differs_per_salt() -> None:
    first, second = H.hash("correct horse battery"), H.hash("correct horse battery")
    assert "correct horse" not in first
    assert first != second
    assert H.verify("correct horse battery", first) and H.verify("correct horse battery", second)


def test_a_wrong_password_or_a_foreign_hash_does_not_verify() -> None:
    encoded = H.hash("correct horse battery")
    assert not H.verify("correct horse batterY", encoded)
    for foreign in ("", "plain", "bcrypt$12$x$y", "pbkdf2_sha256$x$y$z", "pbkdf2_sha256$10$!!$!!"):
        assert not H.verify("correct horse battery", foreign)


def test_a_hash_made_with_fewer_iterations_still_verifies_and_asks_for_a_rehash() -> None:
    old = PasswordHasher(iterations=500).hash("correct horse battery")
    assert H.verify("correct horse battery", old)
    assert H.needs_rehash(old) and not H.needs_rehash(H.hash("correct horse battery"))
