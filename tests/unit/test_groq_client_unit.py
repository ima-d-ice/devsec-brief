"""Unit tests for groq_client retry logic."""
import pytest
from unittest.mock import MagicMock, patch

def test_safe_groq_call_retries_on_429_then_succeeds(monkeypatch):
    import src.groq_client as gc

    mock_client = MagicMock()
    # First call raises 429, second succeeds
    mock_success = MagicMock()
    mock_success.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_client.chat.completions.create.side_effect = [
        Exception("429 rate_limit exceeded"),
        mock_success,
    ]
    monkeypatch.setattr(gc, "groq_client", mock_client)
    # Patch sleep to avoid delay
    with patch("src.groq_client.time.sleep") as mock_sleep:
        resp = gc.safe_groq_call(messages=[{"role": "user", "content": "hi"}], model="llama-3.1-8b-instant")
        assert resp == mock_success
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] == 12  # first retry 12*(0+1)

def test_safe_groq_call_max_retries_raises():
    import src.groq_client as gc
    with patch.object(gc, "groq_client") as mock_client:
        mock_client.chat.completions.create.side_effect = Exception("429 rate_limit")
        with patch("src.groq_client.time.sleep"):
            with pytest.raises(RuntimeError, match="max retries"):
                gc.safe_groq_call(messages=[], _retries=5)

def test_safe_groq_call_non_429_raises_immediately():
    import src.groq_client as gc
    with patch.object(gc, "groq_client") as mock_client:
        mock_client.chat.completions.create.side_effect = Exception("500 internal error")
        with pytest.raises(Exception, match="500"):
            gc.safe_groq_call(messages=[])

def test_safe_groq_call_stream_returns_directly():
    import src.groq_client as gc
    mock_stream = MagicMock()
    with patch.object(gc, "groq_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_stream
        resp = gc.safe_groq_call(messages=[], stream=True)
        assert resp == mock_stream
        mock_client.chat.completions.create.assert_called_once_with(
            model=gc.safe_groq_call.__defaults__[0] if gc.safe_groq_call.__defaults__ else "llama-3.1-8b-instant",
            messages=[],
            temperature=0.4,
            max_tokens=400,
            stream=True,
        )

def test_set_api_key_reinitializes():
    import src.groq_client as gc
    with patch("src.groq_client.Groq") as MockGroq:
        gc.set_api_key("gsk_test_123456")
        MockGroq.assert_called_once_with(api_key="gsk_test_123456")
