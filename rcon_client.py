#!/usr/bin/env python3
"""Small Factorio RCON client shared by the bridge and web API."""

import logging
import socket
import struct
import threading
import time


class RCONClient:
    """Small RCON client for talking to a Factorio server over TCP."""

    def __init__(self, host="127.0.0.1", port=27015, password="", response_timeout=10.0, logger=None):
        self.host = host
        self.port = port
        self.password = password
        self.sock: socket.socket | None = None
        self.request_id = 0
        self.lock = threading.RLock()
        self.response_timeout = response_timeout
        self.last_error = ""
        self.last_success_at = None
        self.logger = logger or logging.getLogger(__name__)

    def _parse_packet(self, packet_data):
        """Parse a raw RCON packet into request id, response type, and payload."""
        if len(packet_data) < 8:
            raise socket.error("Incomplete RCON response header.")
        request_id = struct.unpack("<i", packet_data[:4])[0]
        response_type = struct.unpack("<i", packet_data[4:8])[0]
        payload = packet_data[8:]
        if payload.endswith(b"\x00\x00"):
            payload = payload[:-2]
        return request_id, response_type, payload

    def _is_successful_response_type(self, response_type):
        """Factorio uses response type 0 for ordinary command output and 2 for auth responses."""
        return response_type in {0, 2}

    def connect(self):
        """Connect to the Factorio RCON service and authenticate."""
        with self.lock:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.response_timeout)
                self.sock.connect((self.host, self.port))
                self.logger.info("Connected to Factorio RCON TCP port %s:%s", self.host, self.port)
                if self.password:
                    auth_packet = self._send_packet(3, self.password)
                    if auth_packet is None:
                        self.logger.warning("RCON authentication did not receive a response.")
                        self.sock = None
                        return False
                    _, response_type, payload = self._parse_packet(auth_packet)
                    if not self._is_successful_response_type(response_type):
                        self.logger.warning("RCON authentication returned unexpected response type %s", response_type)
                        self.sock = None
                        return False
                    if payload.lower().startswith(b"failed") or payload.lower().startswith(b"authentication"):
                        self.logger.warning("RCON authentication failed")
                        self.sock = None
                        return False
                    self.logger.info("RCON authentication succeeded")
                self.last_error = ""
                return True
            except Exception as exc:
                self.logger.warning("RCON connection failed for %s:%s: %s", self.host, self.port, exc)
                self._close_socket()
                self.last_error = str(exc)
                return False

    def _recv_exact(self, size):
        """Read a fixed-size payload from the socket."""
        sock = self.sock
        if sock is None:
            raise socket.error("RCON socket is not connected")
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = sock.recv(size - len(chunks))
            except socket.timeout as exc:
                raise TimeoutError(f"RCON response timed out after {self.response_timeout}s") from exc
            if not chunk:
                raise socket.error("Connection closed while reading RCON response")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_packet(self, out_type, payload):
        """Send a packet and return the raw response body bytes."""
        sock = self.sock
        if sock is None:
            raise socket.error("RCON socket is not connected")
        self.request_id += 1
        request_id = self.request_id
        data = struct.pack("<ii", request_id, out_type) + payload.encode("utf-8") + b"\x00\x00"
        sock.sendall(struct.pack("<i", len(data)) + data)
        response_length = struct.unpack("<i", self._recv_exact(4))[0]
        if response_length < 8 or response_length > 16 * 1024 * 1024:
            raise socket.error("Invalid RCON response length")
        return self._recv_exact(response_length)

    def send_command(self, command):
        """Send a command and decode the RCON reply."""
        with self.lock:
            if not self.sock and not self.connect():
                return None
            try:
                response = self._send_packet(2, command)
                _, response_type, payload_bytes = self._parse_packet(response)
                payload = payload_bytes.decode("utf-8", errors="replace")
                if not self._is_successful_response_type(response_type):
                    self.logger.warning("RCON command returned unexpected response type %s", response_type)
                self.last_error = ""
                self.last_success_at = time.time()
                return payload
            except Exception as exc:
                self.logger.warning("RCON command failed: %s", exc)
                self._close_socket()
                self.last_error = str(exc)
                return None

    def _close_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def close(self):
        """Close the socket."""
        with self.lock:
            self._close_socket()
