"""Tests for Gemini speech-to-text helper."""
from __future__ import annotations

import pytest

import voice


def test_should_speak_policies():
    assert voice.should_speak("never", is_intro_turn=True, user_sent_voice=True) is False
    assert voice.should_speak("always", is_intro_turn=False, user_sent_voice=False) is True
    assert voice.should_speak("intro_only", is_intro_turn=True, user_sent_voice=False) is True
    assert voice.should_speak("intro_only", is_intro_turn=False, user_sent_voice=False) is False
    assert voice.should_speak("mirror_user", is_intro_turn=False, user_sent_voice=True) is True
    assert voice.should_speak("mirror_user", is_intro_turn=False, user_sent_voice=False) is False


def test_pcm_to_wav_wraps_bytes():
    wav = voice.pcm_to_wav(b"\x00\x01" * 100)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav


def test_synthesize_speech_returns_wav(monkeypatch):
    pcm = b"\x00\x01" * 120

    class Part:
        inline_data = type("D", (), {"data": pcm})()

    class Candidate:
        content = type("C", (), {"parts": [Part()]})()

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            assert model == "test-tts-model"
            assert config.response_modalities == ["AUDIO"]
            return type("R", (), {"candidates": [Candidate()]})()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("rag.get_client", lambda: FakeClient())
    monkeypatch.setattr("config.GEMINI_TTS_MODEL", "test-tts-model")

    out = voice.synthesize_speech("Hello from TVS", language="English")
    assert out.startswith(b"RIFF")


def test_normalize_mime_type_accepts_webm():
    assert voice.normalize_mime_type("audio/webm;codecs=opus") == "audio/webm"


def test_normalize_mime_type_rejects_non_audio():
    with pytest.raises(ValueError, match="Unsupported audio type"):
        voice.normalize_mime_type("video/webm")


def test_transcribe_audio_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        voice.transcribe_audio(b"", "audio/webm")


def test_transcribe_audio_rejects_oversized(monkeypatch):
    monkeypatch.setattr("config.MAX_AUDIO_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        voice.transcribe_audio(b"x" * 20, "audio/webm")


def test_transcribe_audio_calls_gemini(monkeypatch):
    captured: dict = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config

            class Resp:
                text = "  King EV MAX  "

            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("rag.get_client", lambda: FakeClient())

    out = voice.transcribe_audio(
        b"fake-audio",
        "audio/webm;codecs=opus",
        language_hint="Hindi",
    )
    assert out == "King EV MAX"
    assert captured["config"]["temperature"] == 0
    parts = captured["contents"][0].parts
    assert len(parts) == 2
    assert "Hindi" in parts[1].text
