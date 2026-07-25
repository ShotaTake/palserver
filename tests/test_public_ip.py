import pytest

from palworld_bot.services import public_ip


def test_parses_plain_ipv4() -> None:
    assert public_ip.parse_public_ip("93.184.216.34") == "93.184.216.34"


def test_tolerates_surrounding_whitespace() -> None:
    # checkip.amazonaws.com replies with a trailing newline.
    assert public_ip.parse_public_ip(" 8.8.8.8\n") == "8.8.8.8"


def test_parses_ipv6() -> None:
    assert public_ip.parse_public_ip("2001:db8::1") is None  # documentation range
    assert public_ip.parse_public_ip("2404:6800:4004:80a::200e") == "2404:6800:4004:80a::200e"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not-an-ip",
        "<html><body>error</body></html>",
        "93.184.216.34 extra",
        "999.999.999.999",
        "a" * 100,
    ],
)
def test_rejects_non_addresses(raw: str) -> None:
    assert public_ip.parse_public_ip(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "192.168.0.100",  # private
        "10.0.0.1",
        "127.0.0.1",  # loopback
        "169.254.1.1",  # link-local
        "203.0.113.5",  # TEST-NET-3 documentation range: not routable
    ],
)
def test_rejects_non_global_addresses(raw: str) -> None:
    assert public_ip.parse_public_ip(raw) is None


async def test_fetch_returns_first_valid_answer() -> None:
    calls: list[str] = []

    async def http_get(url: str, _timeout: float) -> str:
        calls.append(url)
        return "93.184.216.34"

    result = await public_ip.fetch_public_ip(
        endpoints=("https://first.example", "https://second.example"),
        http_get=http_get,
    )
    assert result == "93.184.216.34"
    assert calls == ["https://first.example"]  # stops at the first success


async def test_fetch_falls_back_when_endpoint_errors() -> None:
    async def http_get(url: str, _timeout: float) -> str:
        if "first" in url:
            raise TimeoutError("boom")
        return "8.8.8.8"

    result = await public_ip.fetch_public_ip(
        endpoints=("https://first.example", "https://second.example"),
        http_get=http_get,
    )
    assert result == "8.8.8.8"


async def test_fetch_falls_back_when_endpoint_returns_garbage() -> None:
    async def http_get(url: str, _timeout: float) -> str:
        return "<html>rate limited</html>" if "first" in url else "8.8.8.8"

    result = await public_ip.fetch_public_ip(
        endpoints=("https://first.example", "https://second.example"),
        http_get=http_get,
    )
    assert result == "8.8.8.8"


async def test_fetch_returns_none_when_all_fail() -> None:
    async def http_get(_url: str, _timeout: float) -> str:
        raise ConnectionError("offline")

    result = await public_ip.fetch_public_ip(
        endpoints=("https://first.example", "https://second.example"),
        http_get=http_get,
    )
    assert result is None
