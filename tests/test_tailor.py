from unittest.mock import Mock, patch

from jobbot import tailor


def test_gemini_fallback_is_used_when_primary_fails(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    gemini = Mock(return_value=None)
    fallback = Mock(return_value="tailored output")

    with patch.object(tailor, "call_gemini_tailor", gemini), patch.object(
        tailor, "call_gemini_fallback_tailor", fallback
    ):
        result = tailor.call_llm_tailor("prompt")

    assert result == "tailored output"
    gemini.assert_called_once_with("prompt")
    fallback.assert_called_once_with("prompt")


def test_gemini_fallback_can_be_configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-test-fallback")

    with patch.object(tailor, "_call_gemini_model", return_value="output") as call:
        result = tailor.call_gemini_fallback_tailor("prompt")

    assert result == "output"
    call.assert_called_once_with("prompt", "gemini-test-fallback")
