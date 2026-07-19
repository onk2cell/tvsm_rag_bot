"""Safe media download and Gemini-backed media interpretation adapters."""
from __future__ import annotations

import ipaddress
import io
import json
import socket
import wave
from urllib.parse import urljoin, urlparse

import certifi
import mutagen
import requests
import urllib3
from google.genai import types

import config
import voice
from client_processing import DocumentRecognition


class MediaFetchError(ValueError):
    pass


class _PinnedResponse:
    def __init__(self, response, pool):
        self.status_code = response.status
        self.headers = response.headers
        self._response = response
        self._pool = pool

    def iter_content(self, chunk_size: int):
        yield from self._response.stream(chunk_size)

    def close(self) -> None:
        self._response.close()
        self._pool.close()


def _resolve(hostname: str) -> list[str]:
    return list(
        {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    )


class SafeMediaFetcher:
    def __init__(
        self,
        *,
        timeout: float = 30,
        max_bytes: int = 10 * 1024 * 1024,
        trusted_test_hosts: set[str] | None = None,
        http=requests,
        resolver=_resolve,
    ):
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._trusted_test_hosts = trusted_test_hosts or set()
        self._http = http
        self._pin_connections = http is requests
        self._resolver = resolver

    def fetch(self, url: str, mime_type: str) -> bytes:
        current_url = url
        for _ in range(4):
            response = self._get(current_url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise MediaFetchError("Media redirect has no destination")
                current_url = urljoin(current_url, location)
                continue
            if not 200 <= response.status_code < 300:
                response.close()
                raise MediaFetchError(
                    f"Media server returned HTTP {response.status_code}"
                )
            try:
                self._validate_mime(response, mime_type)
                data = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    data.extend(chunk)
                    if len(data) > self._max_bytes:
                        raise MediaFetchError("Media file is too large")
                if not data:
                    raise MediaFetchError("Media file is empty")
                return bytes(data)
            finally:
                response.close()
        raise MediaFetchError("Too many media redirects")

    def _get(self, url: str):
        hostname, address, trusted = self._validate_destination(url)
        if not self._pin_connections or trusted:
            return self._http.get(
                url,
                stream=True,
                allow_redirects=False,
                timeout=self._timeout,
            )

        parsed = urlparse(url)
        port = parsed.port or 443
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        pool = urllib3.HTTPSConnectionPool(
            address,
            port=port,
            timeout=urllib3.Timeout(
                connect=self._timeout,
                read=self._timeout,
            ),
            maxsize=1,
            block=True,
            retries=False,
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
            assert_hostname=hostname,
            server_hostname=hostname,
        )
        try:
            response = pool.urlopen(
                "GET",
                target,
                headers={"Host": hostname},
                redirect=False,
                preload_content=False,
            )
        except Exception:
            pool.close()
            raise
        return _PinnedResponse(response, pool)

    def _validate_destination(self, url: str) -> tuple[str, str, bool]:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise MediaFetchError("Media URL has no hostname")
        trusted = hostname in self._trusted_test_hosts
        if parsed.scheme != "https" and not (trusted and parsed.scheme == "http"):
            raise MediaFetchError("Media URL must use HTTPS")
        if parsed.username or parsed.password:
            raise MediaFetchError("Media URL credentials are not allowed")
        if trusted:
            return hostname, hostname, True
        try:
            addresses = self._resolver(hostname)
        except OSError as error:
            raise MediaFetchError("Media hostname could not be resolved") from error
        if not addresses:
            raise MediaFetchError("Media hostname could not be resolved")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise MediaFetchError("Media URL resolves to a private network")
        return hostname, addresses[0], False

    @staticmethod
    def _validate_mime(response, expected: str) -> None:
        actual = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        declared = (expected or "").split(";", 1)[0].lower()
        if not actual or actual != declared:
            raise MediaFetchError(
                f"Media MIME mismatch: expected {declared}, received {actual or 'missing'}"
            )


class GeminiAudioTranscriber:
    def __init__(self, *, max_duration_seconds: float = 60):
        self._max_duration_seconds = max_duration_seconds

    def transcribe(self, data: bytes, mime_type: str, language: str) -> str:
        try:
            if mime_type.split(";", 1)[0].lower() in {"audio/wav", "audio/x-wav"}:
                with wave.open(io.BytesIO(data), "rb") as audio:
                    duration = audio.getnframes() / audio.getframerate()
            else:
                media = mutagen.File(io.BytesIO(data))
                duration = float(media.info.length) if media and media.info else 0
        except Exception as error:
            raise MediaFetchError("Audio duration could not be determined") from error
        if duration <= 0:
            raise MediaFetchError("Audio duration could not be determined")
        if duration > self._max_duration_seconds:
            raise MediaFetchError("Audio is longer than 60 seconds")
        return voice.transcribe_audio(
            data,
            mime_type,
            language_hint=language or None,
            max_bytes=config.CLIENT_MAX_MEDIA_BYTES,
        )


class GeminiDocumentRecognizer:
    """Identify document categories without extracting visible personal values."""

    _ALLOWED = {
        "driving_licence",
        "commercial_permit",
        "driver_badge",
        "aadhaar",
        "pan",
        "identity_document",
        "bank_statement",
        "payslip",
        "loan_document",
        "registration_certificate",
        "insurance",
        "pollution_certificate",
        "vehicle_document",
    }

    def recognize(self, data: bytes, mime_type: str) -> DocumentRecognition:
        from rag import get_client

        response = get_client().models.generate_content(
            model=config.MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=data, mime_type=mime_type),
                        types.Part.from_text(
                            text=(
                                "Classify only the document types visible in this image. "
                                "Do not transcribe names, numbers, addresses, financial "
                                "values, or any personal data. Return JSON only as "
                                '{"status":"recognized|unknown|not_document",'
                                '"document_types":["snake_case_type"]}.'
                            )
                        ),
                    ],
                )
            ],
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        try:
            payload = json.loads(response.text or "{}")
        except json.JSONDecodeError:
            return DocumentRecognition(["unknown"], "unknown")
        status = str(payload.get("status") or "unknown")
        if status not in {"recognized", "unknown", "not_document"}:
            status = "unknown"
        document_types = [
            str(item)
            for item in payload.get("document_types") or []
            if str(item) in self._ALLOWED
        ]
        if status == "recognized" and not document_types:
            status = "unknown"
        return DocumentRecognition(
            document_types=document_types or ([] if status == "not_document" else ["unknown"]),
            status=status,
        )


class DeterministicAudioTranscriber:
    def transcribe(self, data: bytes, mime_type: str, language: str) -> str:
        return "I am interested in King EV MAX"


class DeterministicDocumentRecognizer:
    def recognize(self, data: bytes, mime_type: str) -> DocumentRecognition:
        if b"unclear" in data:
            return DocumentRecognition(["unknown"], "unknown")
        if b"non-document" in data:
            return DocumentRecognition([], "not_document")
        if b"multiple" in data:
            return DocumentRecognition(
                ["driving_licence", "commercial_permit"],
                "recognized",
            )
        return DocumentRecognition(["driving_licence"], "recognized")
