from app.core.crypto import decrypt_token, encrypt_token


def test_encrypt_decrypt_roundtrip():
    token = "glpat-xxxxxxxxxxxxxxxxxxxx"
    encrypted = encrypt_token(token)
    assert encrypted != token
    assert decrypt_token(encrypted) == token


def test_encrypt_is_randomized():
    token = "same-token"
    assert encrypt_token(token) != encrypt_token(token)
