"""Speech-to-text and text-to-speech via Gemini."""
from __future__ import annotations

import base64
import io
import wave

from google.genai import types

import config

ALLOWED_AUDIO_MIME_PREFIXES = (
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp3",
)

LANGUAGE_TTS_CODES = {
    "English": "en-in",
    "Hindi": "hi-in",
    "Marathi": "mr-in",
    "Tamil": "ta-in",
}


def normalize_mime_type(mime_type: str | None) -> str:
    raw = (mime_type or "audio/webm").split(";")[0].strip().lower()
    if not raw.startswith("audio/"):
        raise ValueError(f"Unsupported audio type: {mime_type or 'unknown'}")
    if not any(raw.startswith(prefix) for prefix in ALLOWED_AUDIO_MIME_PREFIXES):
        raise ValueError(f"Unsupported audio type: {raw}")
    return raw


def should_speak(
    voice_policy: str,
    *,
    is_intro_turn: bool,
    user_sent_voice: bool,
) -> bool:
    if voice_policy == "never":
        return False
    if voice_policy == "always":
        return True
    if voice_policy == "intro_only":
        return is_intro_turn
    if voice_policy == "mirror_user":
        return user_sent_voice
    return False


def tts_language_code(language: str | None) -> str:
    return LANGUAGE_TTS_CODES.get(language or "", "en-in")


def pcm_to_wav(
    pcm: bytes,
    *,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _extract_pcm(resp) -> bytes:
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        raise ValueError("No audio in TTS response")
    parts = candidates[0].content.parts or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if not inline or not inline.data:
            continue
        data = inline.data
        if isinstance(data, str):
            return base64.b64decode(data)
        return bytes(data)
    raise ValueError("No audio in TTS response")


def synthesize_speech(text: str, *, language: str | None = None) -> bytes:
    """Return WAV bytes for the given reply text."""
    spoken = (text or "").strip()
    if not spoken:
        raise ValueError("Nothing to speak")
    if len(spoken) > config.MAX_TTS_CHARS:
        spoken = spoken[: config.MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"

    from rag import get_client

    client = get_client()
    lang_code = tts_language_code(language)
    prompt = (
        f"Read the following customer-facing message clearly and naturally "
        f"in {language or 'the appropriate language'}:\n\n{spoken}"
    )

    resp = client.models.generate_content(
        model=config.GEMINI_TTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code=lang_code,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=config.GEMINI_TTS_VOICE,
                    )
                ),
            ),
        ),
    )
    return pcm_to_wav(_extract_pcm(resp))


def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str,
    *,
    language_hint: str | None = None,
) -> str:
    """Transcribe short user speech to plain text using Gemini."""
    if not audio_bytes:
        raise ValueError("Audio file is empty")
    if len(audio_bytes) > config.MAX_AUDIO_BYTES:
        raise ValueError(
            f"Audio too large (max {config.MAX_AUDIO_BYTES // (1024 * 1024)} MB)"
        )

    from rag import get_client

    client = get_client()
    normalized = normalize_mime_type(mime_type)
    lang_line = (
        f"The speaker is using {language_hint}."
        if language_hint
        else "Detect the spoken language."
    )
    prompt = (
        f"{lang_line} Transcribe the speech exactly as spoken words. "
        "Return only the transcript with no quotes, labels, or commentary. "
        "If nothing is audible, return an empty string."
    )

    resp = client.models.generate_content(
        model=config.MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=normalized),
                    types.Part.from_text(text=prompt),
                ],
            )
        ],
        config={"temperature": 0},
    )
    return (resp.text or "").strip()
