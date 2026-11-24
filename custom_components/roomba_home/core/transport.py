"""HTTP adapter: validated TLS, bounded bodies, no redirects and no payload logging."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import aiohttp

from .errors import ProtocolError

GZIP_JSON_ACCEPT = "application/gzip,application/json"


@dataclass(repr=False)
class HttpResponse:
    status: int
    data: Any = field(repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)


class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse: ...


class AiohttpTransport:
    """The caller owns the supplied ClientSession and its lifecycle."""

    def __init__(self, session: aiohttp.ClientSession, max_body_bytes: int = 8 * 1024 * 1024):
        if max_body_bytes < 1:
            raise ValueError("A positive response size limit is required.")
        self.session = session
        self.max_body_bytes = max_body_bytes

    async def request(self, method, url, *, headers=None, body=None) -> HttpResponse:
        import json

        async with self.session.request(
            method,
            url,
            headers=headers,
            data=body,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            chunks = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                chunks.extend(chunk)
                if len(chunks) > self.max_body_bytes:
                    raise ProtocolError("Provider response exceeded the configured size limit.")
            if (
                headers
                and headers.get("Accept") == GZIP_JSON_ACCEPT
                and response.content_type == "application/gzip"
            ):
                return HttpResponse(response.status, bytes(chunks), dict(response.headers))
            try:
                data = json.loads(chunks) if chunks else None
            except ValueError, UnicodeDecodeError:
                data = None
            return HttpResponse(response.status, data, dict(response.headers))
