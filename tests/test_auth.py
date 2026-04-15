"""Tests for auth — registration, login, domain validation, and admin functions."""

import pytest

from auth import AuthError, authenticate, delete_user, list_users, register_user


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("auth.ALLOWED_DOMAIN", "gmail.com")


class TestRegistration:
    def test_register_and_authenticate(self, test_db):
        register_user("user@gmail.com", "password123")
        user = authenticate("user@gmail.com", "password123")
        assert user["email"] == "user@gmail.com"

    def test_first_user_gets_admin_role(self, test_db):
        register_user("admin@gmail.com", "password123")
        user = authenticate("admin@gmail.com", "password123")
        assert user["role"] == "admin"

    def test_second_user_gets_user_role(self, test_db):
        register_user("admin@gmail.com", "password123")
        register_user("user2@gmail.com", "password123")
        user = authenticate("user2@gmail.com", "password123")
        assert user["role"] == "user"

    def test_rejects_wrong_domain(self, test_db):
        with pytest.raises(AuthError, match="@gmail.com"):
            register_user("user@yahoo.com", "password123")

    def test_rejects_invalid_email(self, test_db):
        with pytest.raises(AuthError, match="有効なメールアドレス"):
            register_user("notanemail", "password123")

    def test_rejects_empty_email(self, test_db):
        with pytest.raises(AuthError, match="有効なメールアドレス"):
            register_user("", "password123")

    def test_rejects_short_password(self, test_db):
        with pytest.raises(AuthError, match="8文字以上"):
            register_user("user@gmail.com", "short")

    def test_rejects_duplicate_email(self, test_db):
        register_user("user@gmail.com", "password123")
        with pytest.raises(AuthError, match="既に登録"):
            register_user("user@gmail.com", "password456")

    def test_email_is_case_insensitive(self, test_db):
        register_user("User@Gmail.com", "password123")
        user = authenticate("user@gmail.com", "password123")
        assert user["email"] == "user@gmail.com"

    def test_allowed_domain_check_is_case_insensitive(self, test_db, monkeypatch):
        monkeypatch.setattr("auth.ALLOWED_DOMAIN", "Gmail.COM")
        register_user("user@gmail.com", "password123")
        assert authenticate("user@gmail.com", "password123")


class TestAuthentication:
    def test_wrong_password_rejected(self, test_db):
        register_user("user@gmail.com", "password123")
        with pytest.raises(AuthError, match="正しくありません"):
            authenticate("user@gmail.com", "wrongpassword")

    def test_nonexistent_user_rejected(self, test_db):
        with pytest.raises(AuthError, match="正しくありません"):
            authenticate("nobody@gmail.com", "password123")


class TestAdminFunctions:
    def test_list_users(self, test_db):
        register_user("a@gmail.com", "password123")
        register_user("b@gmail.com", "password123")
        users = list_users()
        assert len(users) == 2
        emails = {u["email"] for u in users}
        assert emails == {"a@gmail.com", "b@gmail.com"}

    def test_list_users_excludes_password(self, test_db):
        register_user("a@gmail.com", "password123")
        users = list_users()
        assert "password_hash" not in users[0]

    def test_delete_user(self, test_db):
        register_user("a@gmail.com", "password123")
        register_user("b@gmail.com", "password123")
        delete_user("b@gmail.com")
        users = list_users()
        assert len(users) == 1
        assert users[0]["email"] == "a@gmail.com"

    def test_delete_user_prevents_login(self, test_db):
        register_user("a@gmail.com", "password123")
        delete_user("a@gmail.com")
        with pytest.raises(AuthError, match="正しくありません"):
            authenticate("a@gmail.com", "password123")
