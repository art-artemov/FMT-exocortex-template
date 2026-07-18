"""
conftest.py — CI zero-upload guard for generator/ tests.

Any real (non-loopback) socket connection fails the entire test session.
This prevents PII from accidentally reaching external services in CI.
"""
import socket
import pytest


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_original_connect = socket.socket.connect


def _guard_connect(self, address, *args, **kwargs):
    host = address[0] if isinstance(address, (tuple, list)) else str(address)
    if host not in _LOOPBACK:
        raise AssertionError(
            f"ZERO-UPLOAD GUARD: non-loopback connect to {address!r} blocked "
            "(no real network calls are allowed in this test suite — mock the transport)"
        )
    return _original_connect(self, address, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def socket_guard():
    socket.socket.connect = _guard_connect
    yield
    socket.socket.connect = _original_connect
