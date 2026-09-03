"""Unit tests for DB keyword/semantic helpers — mocks pool."""
from unittest.mock import MagicMock, patch

class TestSearchKeywordLogic:
    def test_cve_extracted_as_exact_term(self):
        from src.db import search_keyword
        # Mock pool connection to capture SQL params
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = False
            mock_get_conn.return_value = mock_conn

            result = search_keyword("CVE-2024-1234 exploit analysis", limit=5)
            # CVE should be kept as exact term "'CVE-2024-1234'" not prefix
            # Check that execute was called with match_query containing CVE
            assert mock_cur.execute.called
            # psycopg style: cur.execute(sql, params)
            # params is dict with match_query
            # Actually call is cur.execute(sql, params) where params dict
            sql, param_dict = mock_cur.execute.call_args[0]
            assert "'CVE-2024-1234'" in param_dict["match_query"]
            assert "'exploit':*" in param_dict["match_query"]
            assert result == []

    def test_stop_words_filtered(self):
        from src.db import search_keyword
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            search_keyword("What is the vulnerability in Linux?", limit=5)
            sql, param_dict = mock_cur.execute.call_args[0]
            # "what","is","the","in" are stop words, should not appear
            mq = param_dict["match_query"]
            assert "'vulnerability':*" in mq
            assert "'linux':*" in mq
            assert "'what':*" not in mq
            assert "'the':*" not in mq

    def test_empty_after_filter_returns_early_no_db_call(self):
        from src.db import search_keyword
        with patch("src.db.get_conn") as mock_get_conn:
            result = search_keyword("the a an in", limit=5)
            assert result == []
            mock_get_conn.assert_not_called()

    def test_topic_adds_category_filter(self):
        from src.db import search_keyword
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = [["title"], ["url"], ["source"], ["category"], ["published_at"], ["content"], ["summary"]]
            mock_cur.fetchall.return_value = []
            mock_cur.description = []
            # Need description for dict_rows mapping but empty rows ok
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            search_keyword("ransomware", limit=5, topic="cybersec")
            sql, param_dict = mock_cur.execute.call_args[0]
            assert "category = %(topic)s" in sql
            assert param_dict["topic"] == "cybersec"

    def test_hyphen_replaced_and_lowercased(self):
        from src.db import search_keyword
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            search_keyword("Zero-Day Vulnerability", limit=5)
            sql, param_dict = mock_cur.execute.call_args[0]
            mq = param_dict["match_query"]
            # hyphen -> space, lowercased
            assert "'zero':*" in mq
            assert "'day':*" in mq
            assert "'vulnerability':*" in mq


class TestSearchSemantic:
    def test_search_semantic_builds_query_embs_param(self):
        from src.db import search_semantic
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            q_embs = [[0.1]*1024, [0.2]*1024]
            result = search_semantic(q_embs, k=3, topic=None)
            assert "documents" in result and "metadatas" in result
            # Check that q_emb_strs are '[0.1,0.1,...]'
            sql, param_dict = mock_cur.execute.call_args[0]
            assert "q_embs" in param_dict
            assert len(param_dict["q_embs"]) == 2
            assert param_dict["q_embs"][0].startswith("[0.1")
            assert param_dict["limit"] == 3
            assert "WHERE" not in sql  # no topic

    def test_search_semantic_with_topic_adds_where(self):
        from src.db import search_semantic
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            search_semantic([[0.1]*1024], k=2, topic="webdev")
            sql, param_dict = mock_cur.execute.call_args[0]
            assert "WHERE a.category = %(topic)s" in sql
            assert param_dict["topic"] == "webdev"

    def test_save_article_if_new_returns_bool(self):
        from src.db import save_article_if_new
        with patch("src.db.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            # Simulate conflict (fetchone None) vs inserted (not None)
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            mock_get_conn.return_value = mock_conn

            res = save_article_if_new(title="t", url="http://x", source="s", category="c", summary="sum", content="con", published_at="2026-09-01")
            assert res is False

            mock_cur.fetchone.return_value = (1,)
            res2 = save_article_if_new(title="t", url="http://y", source="s", category="c", summary="sum", content="con", published_at="2026-09-01")
            assert res2 is True
