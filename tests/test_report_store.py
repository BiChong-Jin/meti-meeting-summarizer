"""Tests for report_store — save, list, load, and search."""

import json

import pytest

from report_store import list_reports, load_report, save_report, search_reports


@pytest.fixture()
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("report_store.REPORTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def sample_reports(reports_dir):
    """Create 3 reports with different content for search tests."""
    ids = []
    ids.append(save_report("第5回 次世代基盤会議", "2026/03/27", "電力ガスの規制改革について議論", ["doc1.pdf", "doc2.pdf"]))
    ids.append(save_report("第4回 次世代基盤会議", "2025/12/17", "再生可能エネルギーの導入拡大", ["energy.pdf"]))
    ids.append(save_report("第1回 企画戦略会議", "2025/05/23", "来年度の予算と人員配置の検討", ["budget.pdf"]))
    return ids


class TestSaveAndLoad:
    def test_save_returns_id(self, reports_dir):
        rid = save_report("テスト会議", "2026/01/01", "内容", ["a.pdf"])
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_load_roundtrip(self, reports_dir):
        rid = save_report("テスト会議", "2026/01/01", "レポート内容です", ["a.pdf"])
        report = load_report(rid)
        assert report["title"] == "テスト会議"
        assert report["content"] == "レポート内容です"
        assert report["sources"] == ["a.pdf"]

    def test_load_nonexistent_returns_none(self, reports_dir):
        assert load_report("nonexistent_id") is None

    def test_empty_title_gets_default(self, reports_dir):
        rid = save_report("", "", "content", [])
        report = load_report(rid)
        assert report["title"] == "(タイトルなし)"


class TestListReports:
    def test_list_empty(self, reports_dir):
        assert list_reports() == []

    def test_list_returns_all(self, sample_reports):
        reports = list_reports()
        assert len(reports) == 3
        titles = {r["title"] for r in reports}
        assert titles == {"第5回 次世代基盤会議", "第4回 次世代基盤会議", "第1回 企画戦略会議"}

    def test_list_excludes_content(self, sample_reports):
        reports = list_reports()
        for r in reports:
            assert "content" not in r


class TestSearchReports:
    def test_search_by_title(self, sample_reports):
        results = search_reports("次世代基盤")
        assert len(results) == 2

    def test_search_by_content(self, sample_reports):
        results = search_reports("再生可能エネルギー")
        assert len(results) == 1
        assert "第4回" in results[0]["title"]

    def test_search_by_source_filename(self, sample_reports):
        results = search_reports("budget.pdf")
        assert len(results) == 1
        assert "企画戦略" in results[0]["title"]

    def test_search_by_date(self, sample_reports):
        results = search_reports("2026/03/27")
        assert len(results) == 1
        assert "第5回" in results[0]["title"]

    def test_search_case_insensitive(self, sample_reports):
        results = search_reports("DOC1.PDF")
        assert len(results) == 1

    def test_search_no_match(self, sample_reports):
        results = search_reports("存在しないキーワード")
        assert results == []

    def test_search_excludes_content_from_results(self, sample_reports):
        results = search_reports("電力")
        for r in results:
            assert "content" not in r
