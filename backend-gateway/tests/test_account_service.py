"""Unit tests for AccountService — email/password registration, login, refresh token."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.account_service import (
    ACCESS_TOKEN_EXPIRY_SECONDS,
    AccountService,
    TokenPair,
    UserRole,
    _create_access_token,
    _hash_refresh_token,
    hash_password,
    validate_email,
    validate_password,
    validate_phone,
    verify_access_token,
    verify_password,
)

# ── Validation tests ────────────────────────────────────────────────────────


class TestValidatePassword:
    def test_valid_password(self):
        ok, msg = validate_password("Str0ng!Pass")
        assert ok is True
        assert msg == ""

    def test_too_short(self):
        ok, msg = validate_password("Ab1!xyz")
        assert ok is False
        assert "8 characters" in msg

    def test_no_uppercase(self):
        ok, msg = validate_password("str0ng!pass")
        assert ok is False
        assert "uppercase" in msg

    def test_no_lowercase(self):
        ok, msg = validate_password("STR0NG!PASS")
        assert ok is False
        assert "lowercase" in msg

    def test_no_digit(self):
        ok, msg = validate_password("Strong!Pass")
        assert ok is False
        assert "digit" in msg

    def test_no_special(self):
        ok, msg = validate_password("Str0ngPass1")
        assert ok is False
        assert "special" in msg

    def test_exactly_8_chars_valid(self):
        ok, _ = validate_password("Ab1!xxxx")
        assert ok is True

    def test_empty_password(self):
        ok, _ = validate_password("")
        assert ok is False


class TestValidateEmail:
    def test_valid_email(self):
        assert validate_email("user@example.com") is True

    def test_valid_email_with_dots(self):
        assert validate_email("first.last@domain.co.in") is True

    def test_invalid_no_at(self):
        assert validate_email("userexample.com") is False

    def test_invalid_no_domain(self):
        assert validate_email("user@") is False

    def test_empty(self):
        assert validate_email("") is False


class TestValidatePhone:
    def test_valid_10_digits(self):
        assert validate_phone("9876543210") is True

    def test_too_short(self):
        assert validate_phone("987654321") is False

    def test_too_long(self):
        assert validate_phone("98765432100") is False

    def test_with_letters(self):
        assert validate_phone("98765abcde") is False

    def test_with_country_code(self):
        assert validate_phone("+919876543210") is False


# ── Password hashing tests ──────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "MyP@ss123"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("Correct!1")
        assert verify_password("Wrong!1xx", hashed) is False

    def test_different_hashes_same_password(self):
        pw = "Same!Pass1"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # bcrypt uses random salt
        assert verify_password(pw, h1) is True
        assert verify_password(pw, h2) is True


# ── JWT token tests ─────────────────────────────────────────────────────────


class TestAccessToken:
    def test_create_and_verify(self):
        token = _create_access_token("user-123", "u@test.com", "TRADER")
        payload = verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "u@test.com"
        assert payload["role"] == "TRADER"
        assert payload["type"] == "access"

    def test_expired_token(self):
        import jwt as pyjwt
        from app.services.account_service import JWT_ALGORITHM, JWT_SECRET

        payload = {
            "sub": "user-123",
            "email": "u@test.com",
            "role": "TRADER",
            "type": "access",
            "iat": int(time.time()) - 3600,
            "exp": int(time.time()) - 1800,
        }
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        assert verify_access_token(token) is None

    def test_wrong_type_rejected(self):
        import jwt as pyjwt
        from app.services.account_service import JWT_ALGORITHM, JWT_SECRET

        payload = {
            "sub": "user-123",
            "email": "u@test.com",
            "role": "TRADER",
            "type": "refresh",  # wrong type
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        assert verify_access_token(token) is None

    def test_invalid_token_string(self):
        assert verify_access_token("not.a.valid.token") is None

    def test_token_contains_expiry(self):
        token = _create_access_token("u1", "e@t.com", "ADMIN")
        payload = verify_access_token(token)
        assert "exp" in payload
        # Expiry should be ~15 minutes from now
        expected_exp = int(time.time()) + ACCESS_TOKEN_EXPIRY_SECONDS
        assert abs(payload["exp"] - expected_exp) < 5


# ── AccountService with mocked DB pool ──────────────────────────────────────


def _make_mock_pool():
    """Create a mock asyncpg pool with acquire() context manager."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


import uuid


class TestRegisterEmail:
    @pytest.mark.asyncio
    async def test_successful_registration(self):
        pool, conn = _make_mock_pool()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        conn.fetchval = AsyncMock(return_value=None)  # no duplicate
        conn.fetchrow = AsyncMock(
            return_value={
                "id": user_id,
                "email": "new@test.com",
                "phone": "9876543210",
                "name": "Test User",
                "role": "TRADER",
                "is_onboarded": False,
                "created_at": now,
            }
        )

        svc = AccountService(pool)
        result = await svc.register_email("new@test.com", "Str0ng!Pass", "9876543210", "Test User")

        assert result["user"].email == "new@test.com"
        assert result["user"].role == UserRole.TRADER
        assert len(result["otp"]) == 6
        assert result["otp_expires_at"] > time.time()
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_email_rejected(self):
        pool, _ = _make_mock_pool()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Invalid email"):
            await svc.register_email("bad-email", "Str0ng!Pass", "9876543210", "Name")

    @pytest.mark.asyncio
    async def test_weak_password_rejected(self):
        pool, _ = _make_mock_pool()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="uppercase"):
            await svc.register_email("a@b.com", "weakpass1!", "9876543210", "Name")

    @pytest.mark.asyncio
    async def test_invalid_phone_rejected(self):
        pool, _ = _make_mock_pool()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="10-digit"):
            await svc.register_email("a@b.com", "Str0ng!Pass", "123", "Name")

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self):
        pool, conn = _make_mock_pool()
        conn.fetchval = AsyncMock(return_value=uuid.uuid4())  # existing user

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="already exists"):
            await svc.register_email("dup@test.com", "Str0ng!Pass", "9876543210", "Name")


class TestLoginEmail:
    @pytest.mark.asyncio
    async def test_successful_login(self):
        pool, conn = _make_mock_pool()
        pw_hash = hash_password("Str0ng!Pass")
        user_id = uuid.uuid4()

        conn.fetchrow = AsyncMock(
            return_value={
                "id": user_id,
                "email": "user@test.com",
                "password_hash": pw_hash,
                "role": "TRADER",
                "is_active": True,
                "name": "Test",
            }
        )
        conn.execute = AsyncMock()

        svc = AccountService(pool)
        tokens = await svc.login_email("user@test.com", "Str0ng!Pass")

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token
        assert tokens.refresh_token
        # Verify access token is valid
        payload = verify_access_token(tokens.access_token)
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "TRADER"

    @pytest.mark.asyncio
    async def test_wrong_password(self):
        pool, conn = _make_mock_pool()
        pw_hash = hash_password("Correct!1")

        conn.fetchrow = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "email": "user@test.com",
                "password_hash": pw_hash,
                "role": "TRADER",
                "is_active": True,
                "name": "Test",
            }
        )

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Invalid email or password"):
            await svc.login_email("user@test.com", "Wrong!Pass1")

    @pytest.mark.asyncio
    async def test_nonexistent_user(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Invalid email or password"):
            await svc.login_email("nobody@test.com", "Str0ng!Pass")

    @pytest.mark.asyncio
    async def test_social_only_account(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "email": "social@test.com",
                "password_hash": None,
                "role": "TRADER",
                "is_active": True,
                "name": "Social User",
            }
        )

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="social login"):
            await svc.login_email("social@test.com", "Any!Pass1")

    @pytest.mark.asyncio
    async def test_deactivated_account(self):
        pool, conn = _make_mock_pool()
        pw_hash = hash_password("Str0ng!Pass")

        conn.fetchrow = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "email": "inactive@test.com",
                "password_hash": pw_hash,
                "role": "TRADER",
                "is_active": False,
                "name": "Inactive",
            }
        )

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="deactivated"):
            await svc.login_email("inactive@test.com", "Str0ng!Pass")


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_successful_refresh(self):
        pool, conn = _make_mock_pool()
        user_id = uuid.uuid4()
        token_id = uuid.uuid4()
        raw_refresh = "test-refresh-token-string"
        token_hash = _hash_refresh_token(raw_refresh)
        future = datetime.now(timezone.utc) + timedelta(days=15)

        conn.fetchrow = AsyncMock(
            return_value={
                "token_id": token_id,
                "user_id": user_id,
                "expires_at": future,
                "email": "user@test.com",
                "role": "TRADER",
                "is_active": True,
            }
        )
        conn.execute = AsyncMock()

        svc = AccountService(pool)
        tokens = await svc.refresh_token(raw_refresh)

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token
        assert tokens.refresh_token
        assert tokens.refresh_token != raw_refresh  # rotated
        # Old token should be deleted
        conn.execute.assert_any_call("DELETE FROM refresh_tokens WHERE id = $1", token_id)

    @pytest.mark.asyncio
    async def test_invalid_refresh_token(self):
        pool, conn = _make_mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Invalid refresh token"):
            await svc.refresh_token("bogus-token")

    @pytest.mark.asyncio
    async def test_expired_refresh_token(self):
        pool, conn = _make_mock_pool()
        token_id = uuid.uuid4()
        past = datetime.now(timezone.utc) - timedelta(days=1)

        conn.fetchrow = AsyncMock(
            return_value={
                "token_id": token_id,
                "user_id": uuid.uuid4(),
                "expires_at": past,
                "email": "user@test.com",
                "role": "TRADER",
                "is_active": True,
            }
        )
        conn.execute = AsyncMock()

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="expired"):
            await svc.refresh_token("expired-token")

    @pytest.mark.asyncio
    async def test_deactivated_user_refresh(self):
        pool, conn = _make_mock_pool()
        future = datetime.now(timezone.utc) + timedelta(days=15)

        conn.fetchrow = AsyncMock(
            return_value={
                "token_id": uuid.uuid4(),
                "user_id": uuid.uuid4(),
                "expires_at": future,
                "email": "user@test.com",
                "role": "TRADER",
                "is_active": False,
            }
        )
        conn.execute = AsyncMock()

        svc = AccountService(pool)
        with pytest.raises(ValueError, match="deactivated"):
            await svc.refresh_token("some-token")


# ── Social login tests ──────────────────────────────────────────────────────

from unittest.mock import patch as sync_patch


def _make_mock_pool_with_conn():
    """Create a mock asyncpg pool returning a single shared mock connection."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool, conn


class TestLoginGoogle:
    """Tests for AccountService.login_google()."""

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Google ID token is required"):
            await svc.login_google("")

    @pytest.mark.asyncio
    async def test_invalid_google_token(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_token"}

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="Invalid Google ID token"):
                await svc.login_google("bad-token")

    @pytest.mark.asyncio
    async def test_google_unverified_email_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-123",
            "email": "user@gmail.com",
            "email_verified": "false",
            "name": "Test User",
            "aud": "",
        }

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="not verified"):
                await svc.login_google("some-token")

    @pytest.mark.asyncio
    async def test_google_no_email_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-123",
            "email_verified": "true",
            "name": "Test User",
            "aud": "",
        }

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="no email"):
                await svc.login_google("some-token")

    @pytest.mark.asyncio
    async def test_google_new_user_created(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-456",
            "email": "newuser@gmail.com",
            "email_verified": "true",
            "name": "New User",
            "aud": "",
        }

        # No existing social login, no existing user → create new
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,  # social_logins lookup
                None,  # users email lookup
                {"id": user_id, "email": "newuser@gmail.com", "role": "TRADER"},  # INSERT user
            ]
        )
        conn.execute = AsyncMock()

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            tokens = await svc.login_google("valid-google-token")

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token
        assert tokens.refresh_token
        payload = verify_access_token(tokens.access_token)
        assert payload["sub"] == str(user_id)

    @pytest.mark.asyncio
    async def test_google_existing_social_link(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-789",
            "email": "existing@gmail.com",
            "email_verified": "true",
            "name": "Existing",
            "aud": "",
        }

        # Existing social login found
        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": user_id,
                "email": "existing@gmail.com",
                "role": "TRADER",
                "is_active": True,
            }
        )
        conn.execute = AsyncMock()

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            tokens = await svc.login_google("valid-token")

        assert isinstance(tokens, TokenPair)
        payload = verify_access_token(tokens.access_token)
        assert payload["sub"] == str(user_id)

    @pytest.mark.asyncio
    async def test_google_links_to_existing_email_account(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-new-link",
            "email": "emailuser@test.com",
            "email_verified": "true",
            "name": "Email User",
            "aud": "",
        }

        # No social login, but user with same email exists
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,  # social_logins lookup
                {
                    "id": user_id,
                    "email": "emailuser@test.com",
                    "role": "TRADER",
                    "is_active": True,
                },  # users lookup
            ]
        )
        conn.execute = AsyncMock()

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            tokens = await svc.login_google("valid-token")

        assert isinstance(tokens, TokenPair)
        payload = verify_access_token(tokens.access_token)
        assert payload["sub"] == str(user_id)

    @pytest.mark.asyncio
    async def test_google_deactivated_account_rejected(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-deactivated",
            "email": "deactivated@gmail.com",
            "email_verified": "true",
            "name": "Deactivated",
            "aud": "",
        }

        conn.fetchrow = AsyncMock(
            return_value={
                "user_id": uuid.uuid4(),
                "email": "deactivated@gmail.com",
                "role": "TRADER",
                "is_active": False,
            }
        )

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="deactivated"):
                await svc.login_google("valid-token")


class TestLoginApple:
    """Tests for AccountService.login_apple()."""

    @pytest.mark.asyncio
    async def test_empty_auth_code_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Apple authorization code is required"):
            await svc.login_apple("")

    @pytest.mark.asyncio
    async def test_invalid_apple_auth_code(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        mock_resp = MagicMock()
        mock_resp.status_code = 400

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with sync_patch.object(svc, "_build_apple_client_secret", return_value="fake-secret"):
                with pytest.raises(ValueError, match="Invalid Apple authorization code"):
                    await svc.login_apple("bad-code")

    @pytest.mark.asyncio
    async def test_apple_new_user_with_email(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        # Mock Apple token exchange
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"id_token": "fake.apple.id_token"}

        # No existing social login, no existing user → create new
        conn.fetchrow = AsyncMock(
            side_effect=[
                None,  # social_logins lookup
                None,  # users email lookup
                {"id": user_id, "email": "apple@icloud.com", "role": "TRADER"},  # INSERT user
            ]
        )
        conn.execute = AsyncMock()

        apple_claims = {
            "sub": "apple-sub-123",
            "email": "apple@icloud.com",
            "email_verified": True,
        }

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client_cls.return_value = mock_client

            with sync_patch.object(svc, "_build_apple_client_secret", return_value="fake-secret"):
                with sync_patch.object(svc, "_verify_apple_id_token", return_value=apple_claims):
                    tokens = await svc.login_apple("valid-apple-code", user_name="Apple User")

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token
        payload = verify_access_token(tokens.access_token)
        assert payload["sub"] == str(user_id)

    @pytest.mark.asyncio
    async def test_apple_email_hidden_existing_link(self):
        """When Apple hides email but user already has a linked account."""
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"id_token": "fake.apple.id_token"}

        # Apple claims with no email (hidden)
        apple_claims = {"sub": "apple-hidden-123"}

        # First pool.acquire: lookup existing email for this provider
        # We need separate conn mocks for the two pool.acquire calls
        conn1 = AsyncMock()
        conn2 = AsyncMock()
        ctx1 = AsyncMock()
        ctx1.__aenter__ = AsyncMock(return_value=conn1)
        ctx1.__aexit__ = AsyncMock(return_value=False)
        ctx2 = AsyncMock()
        ctx2.__aenter__ = AsyncMock(return_value=conn2)
        ctx2.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.side_effect = [ctx1, ctx2]

        # conn1: lookup existing email from social_logins
        conn1.fetchrow = AsyncMock(return_value={"email": "hidden@privaterelay.appleid.com"})

        # conn2: _find_or_create_social_user → existing social login found
        conn2.fetchrow = AsyncMock(
            return_value={
                "user_id": user_id,
                "email": "hidden@privaterelay.appleid.com",
                "role": "TRADER",
                "is_active": True,
            }
        )
        conn2.execute = AsyncMock()

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client_cls.return_value = mock_client

            with sync_patch.object(svc, "_build_apple_client_secret", return_value="fake-secret"):
                with sync_patch.object(svc, "_verify_apple_id_token", return_value=apple_claims):
                    tokens = await svc.login_apple("valid-code")

        assert isinstance(tokens, TokenPair)

    @pytest.mark.asyncio
    async def test_apple_email_hidden_no_existing_account(self):
        """When Apple hides email and no existing account → error."""
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"id_token": "fake.apple.id_token"}

        apple_claims = {"sub": "apple-new-hidden"}

        # No existing social login for this provider_id
        conn.fetchrow = AsyncMock(return_value=None)

        with sync_patch("app.services.account_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client_cls.return_value = mock_client

            with sync_patch.object(svc, "_build_apple_client_secret", return_value="fake-secret"):
                with sync_patch.object(svc, "_verify_apple_id_token", return_value=apple_claims):
                    with pytest.raises(ValueError, match="Apple did not share email"):
                        await svc.login_apple("valid-code")


class TestLinkSocialProvider:
    """Tests for AccountService.link_social_provider()."""

    @pytest.mark.asyncio
    async def test_unsupported_provider_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Unsupported provider"):
            await svc.link_social_provider("user-id", "facebook", "fb-123")

    @pytest.mark.asyncio
    async def test_empty_provider_id_rejected(self):
        pool, _ = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        with pytest.raises(ValueError, match="Provider ID is required"):
            await svc.link_social_provider("user-id", "google", "")

    @pytest.mark.asyncio
    async def test_already_linked_to_another_user(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        other_user_id = uuid.uuid4()

        conn.fetchrow = AsyncMock(return_value={"user_id": other_user_id})

        with pytest.raises(ValueError, match="already linked to another user"):
            await svc.link_social_provider(str(uuid.uuid4()), "google", "google-123")

    @pytest.mark.asyncio
    async def test_already_linked_to_same_user_noop(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        conn.fetchrow = AsyncMock(return_value={"user_id": user_id})

        # Should not raise — it's a no-op
        await svc.link_social_provider(str(user_id), "google", "google-123")

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)

        conn.fetchrow = AsyncMock(return_value=None)  # no existing link
        conn.fetchval = AsyncMock(return_value=None)  # user not found

        with pytest.raises(ValueError, match="User not found"):
            await svc.link_social_provider(str(uuid.uuid4()), "google", "google-new")

    @pytest.mark.asyncio
    async def test_successful_link(self):
        pool, conn = _make_mock_pool_with_conn()
        svc = AccountService(pool)
        user_id = uuid.uuid4()

        conn.fetchrow = AsyncMock(return_value=None)  # no existing link
        conn.fetchval = AsyncMock(return_value=user_id)  # user exists
        conn.execute = AsyncMock()

        await svc.link_social_provider(str(user_id), "apple", "apple-sub-456")

        # Verify INSERT was called
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "INSERT INTO social_logins" in call_args[0][0]
