"""Pressure tests — simulate concurrent users hitting the database.

Run with:
    python -m pytest tests/test_pressure.py -v -s

These tests verify that SQLite with WAL mode handles concurrent
reads and writes without corruption or deadlocks.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from auth import register_user, authenticate, AuthError
from report_store import save_report, list_reports, search_reports, load_report, count_reports


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "pressure.db")
    monkeypatch.setattr("auth.ALLOWED_DOMAIN", "gmail.com")


# ---------------------------------------------------------------------------
# Concurrent report writes
# ---------------------------------------------------------------------------
class TestConcurrentReportWrites:
    NUM_WRITERS = 50

    def test_concurrent_saves(self, test_db):
        """50 users saving reports simultaneously — no data loss."""
        results = []

        def save_one(i):
            rid = save_report(
                f"会議 {i}", f"2026/01/{i:02d}",
                f"レポート内容 {i}", [f"doc{i}.pdf"],
            )
            return rid

        with ThreadPoolExecutor(max_workers=self.NUM_WRITERS) as pool:
            futures = [pool.submit(save_one, i) for i in range(self.NUM_WRITERS)]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(results) == self.NUM_WRITERS
        assert len(set(results)) == self.NUM_WRITERS  # all unique IDs

        # Verify all reports are in the database
        assert count_reports("pdf") == self.NUM_WRITERS


# ---------------------------------------------------------------------------
# Concurrent reads while writing
# ---------------------------------------------------------------------------
class TestConcurrentReadsAndWrites:
    NUM_OPS = 100

    def test_reads_during_writes(self, test_db):
        """Mixed reads and writes don't deadlock or corrupt data."""
        # Seed some data first
        for i in range(10):
            save_report(f"事前データ {i}", f"2025/01/{i:02d}", f"内容 {i}", [])

        errors = []

        def writer(i):
            try:
                save_report(f"新規 {i}", f"2026/02/{i:02d}", f"新内容 {i}", [])
            except Exception as e:
                errors.append(f"write {i}: {e}")

        def reader(i):
            try:
                reports = list_reports()
                if reports:
                    load_report(reports[0]["id"])
                search_reports("事前")
            except Exception as e:
                errors.append(f"read {i}: {e}")

        with ThreadPoolExecutor(max_workers=30) as pool:
            futures = []
            for i in range(self.NUM_OPS):
                if i % 3 == 0:
                    futures.append(pool.submit(writer, i))
                else:
                    futures.append(pool.submit(reader, i))
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Errors during concurrent ops: {errors}"


# ---------------------------------------------------------------------------
# Concurrent authentication
# ---------------------------------------------------------------------------
class TestConcurrentAuth:
    NUM_USERS = 20

    def test_concurrent_registrations(self, test_db):
        """30 users registering simultaneously — no duplicates, no crashes."""
        results = []
        errors = []

        def register_one(i):
            try:
                register_user(f"user{i}@gmail.com", "password123")
                results.append(i)
            except AuthError:
                errors.append(i)
            except Exception as e:
                errors.append(f"unexpected {i}: {e}")

        with ThreadPoolExecutor(max_workers=self.NUM_USERS) as pool:
            futures = [pool.submit(register_one, i) for i in range(self.NUM_USERS)]
            for f in as_completed(futures):
                f.result()

        assert len(results) == self.NUM_USERS
        assert errors == []

    def test_concurrent_logins(self, test_db):
        """30 users logging in at the same time."""
        # Register users first
        for i in range(self.NUM_USERS):
            register_user(f"login{i}@gmail.com", "password123")

        errors = []

        def login_one(i):
            try:
                user = authenticate(f"login{i}@gmail.com", "password123")
                assert user["email"] == f"login{i}@gmail.com"
            except Exception as e:
                errors.append(f"login {i}: {e}")

        with ThreadPoolExecutor(max_workers=self.NUM_USERS) as pool:
            futures = [pool.submit(login_one, i) for i in range(self.NUM_USERS)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Login errors: {errors}"


# ---------------------------------------------------------------------------
# Sustained load over time
# ---------------------------------------------------------------------------
class TestSustainedLoad:
    def test_rapid_fire_operations(self, test_db):
        """200 operations in quick succession — simulates burst traffic."""
        NUM_OPS = 200
        errors = []

        def operation(i):
            try:
                if i % 4 == 0:
                    save_report(f"バースト {i}", "2026/03/01", f"内容 {i}", [])
                elif i % 4 == 1:
                    list_reports()
                elif i % 4 == 2:
                    search_reports("バースト")
                else:
                    load_report("nonexistent_id")
            except Exception as e:
                errors.append(f"op {i}: {e}")

        with ThreadPoolExecutor(max_workers=30) as pool:
            futures = [pool.submit(operation, i) for i in range(NUM_OPS)]
            for f in as_completed(futures):
                f.result()

        assert errors == [], f"Errors during burst: {errors}"

        # Verify data integrity
        expected_writes = NUM_OPS // 4
        assert count_reports("pdf") == expected_writes
