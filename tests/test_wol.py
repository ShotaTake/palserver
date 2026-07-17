import pytest

from palworld_bot.services.wol import build_magic_packet


def test_magic_packet_layout() -> None:
    packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
    mac_bytes = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == mac_bytes * 16


def test_hyphen_separator_accepted() -> None:
    assert build_magic_packet("aa-bb-cc-dd-ee-ff") == build_magic_packet("AA:BB:CC:DD:EE:FF")


@pytest.mark.parametrize(
    "mac",
    ["", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:FF:00", "GG:BB:CC:DD:EE:FF", "AABBCCDDEEFF"],
)
def test_invalid_mac_rejected(mac: str) -> None:
    with pytest.raises(ValueError, match="invalid MAC address"):
        build_magic_packet(mac)
