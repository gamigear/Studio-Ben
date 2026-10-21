"""HTTP client dùng chung cho mọi lời gọi ra ngoài; test thay `transport` bằng httpx.MockTransport."""

import httpx

transport: httpx.BaseTransport | None = None


def client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)
