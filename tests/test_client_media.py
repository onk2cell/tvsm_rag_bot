"""Client media download safety tests."""
from __future__ import annotations

import io
import wave

import pytest

from client_media import GeminiAudioTranscriber, MediaFetchError, SafeMediaFetcher


class FakeResponse:
    def __init__(self, *, status=200, mime="audio/mpeg", chunks=None, location=None):
        self.status_code = status
        self.headers = {"Content-Type": mime}
        if location:
            self.headers["Location"] = location
        self._chunks = chunks or [b"audio"]

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        pass


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_media_fetcher_rejects_plain_http_from_untrusted_host():
    fetcher = SafeMediaFetcher(http=FakeHttp([]), resolver=lambda _: ["203.0.113.10"])

    with pytest.raises(MediaFetchError, match="HTTPS"):
        fetcher.fetch("http://client.example/audio.mp3", "audio/mpeg")


def test_media_fetcher_rejects_private_network_destination():
    fetcher = SafeMediaFetcher(http=FakeHttp([]), resolver=lambda _: ["127.0.0.1"])

    with pytest.raises(MediaFetchError, match="private"):
        fetcher.fetch("https://client.example/audio.mp3", "audio/mpeg")


def test_media_fetcher_allows_explicit_test_host_and_validates_size():
    http = FakeHttp([FakeResponse(chunks=[b"1234", b"5678"])])
    fetcher = SafeMediaFetcher(
        http=http,
        resolver=lambda _: ["127.0.0.1"],
        trusted_test_hosts={"mock-client"},
        max_bytes=7,
    )

    with pytest.raises(MediaFetchError, match="10 MB|large"):
        fetcher.fetch("http://mock-client/audio.mp3", "audio/mpeg")


def test_media_fetcher_revalidates_redirect_destination():
    http = FakeHttp(
        [
            FakeResponse(
                status=302,
                location="https://127.0.0.1/private",
            )
        ]
    )
    fetcher = SafeMediaFetcher(
        http=http,
        resolver=lambda host: ["127.0.0.1"] if host == "127.0.0.1" else ["203.0.113.10"],
    )

    with pytest.raises(MediaFetchError, match="private"):
        fetcher.fetch("https://client.example/audio.mp3", "audio/mpeg")


def test_media_fetcher_rejects_mime_mismatch():
    http = FakeHttp([FakeResponse(mime="text/html")])
    fetcher = SafeMediaFetcher(http=http, resolver=lambda _: ["8.8.8.8"])

    with pytest.raises(MediaFetchError, match="MIME"):
        fetcher.fetch("https://client.example/audio.mp3", "audio/mpeg")


def test_audio_transcriber_rejects_audio_longer_than_sixty_seconds():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(b"\x80" * (61 * 8000))

    with pytest.raises(MediaFetchError, match="longer than 60"):
        GeminiAudioTranscriber().transcribe(
            output.getvalue(),
            "audio/wav",
            "English",
        )


def test_production_fetch_pins_the_validated_ip(monkeypatch):
    captured = {}

    class PoolResponse:
        status = 200
        headers = {"Content-Type": "audio/mpeg"}

        def stream(self, chunk_size):
            yield b"audio"

        def close(self):
            pass

    class FakePool:
        def __init__(self, host, **kwargs):
            captured["host"] = host
            captured["kwargs"] = kwargs

        def urlopen(self, method, target, **kwargs):
            captured["target"] = target
            return PoolResponse()

        def close(self):
            pass

    monkeypatch.setattr("client_media.urllib3.HTTPSConnectionPool", FakePool)
    fetcher = SafeMediaFetcher(resolver=lambda _: ["8.8.8.8"])

    assert fetcher.fetch(
        "https://client.example/audio.mp3?token=x",
        "audio/mpeg",
    ) == b"audio"
    assert captured["host"] == "8.8.8.8"
    assert captured["kwargs"]["server_hostname"] == "client.example"
    assert captured["kwargs"]["assert_hostname"] == "client.example"
    assert captured["target"] == "/audio.mp3?token=x"
