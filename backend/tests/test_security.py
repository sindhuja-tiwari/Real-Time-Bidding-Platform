from app.core.security import hash_password, verify_password


def test_password_hash_round_trip():
    # Regression: with bcrypt>=4.1, passlib 1.7.4 raised on every hash, so
    # registration returned 500.
    hashed = hash_password("correct horse battery")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)
