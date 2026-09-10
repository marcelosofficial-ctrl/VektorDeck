from __future__ import annotations

import socket

from vektordeck.runtime_probe import probe_llama_service, tcp_port_open


def _listening_socket() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, int(sock.getsockname()[1])


def test_tcp_port_open_detects_free_and_occupied_ports() -> None:
    sock, port = _listening_socket()
    try:
        assert tcp_port_open("127.0.0.1", port) is True
    finally:
        sock.close()

    assert tcp_port_open("127.0.0.1", port) is False


def test_probe_llama_service_marks_non_http_listener_as_blocked() -> None:
    sock, port = _listening_socket()
    try:
        result = probe_llama_service({"host": "127.0.0.1", "port": port}, timeout_seconds=0.05)
    finally:
        sock.close()

    assert result["occupied"] is True
    assert result["llama_compatible"] is False
    assert result["models"] == []
    assert "owner_pid" in result
    assert "owner_name" in result


def test_probe_llama_service_free_port_has_no_owner() -> None:
    sock, port = _listening_socket()
    sock.close()

    result = probe_llama_service({"host": "127.0.0.1", "port": port})
    assert result["occupied"] is False
    assert result["llama_compatible"] is False
    assert result["owner_pid"] is None
    assert result["owner_name"] is None
