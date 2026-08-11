# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     test_mixed_server.py
   Description :   MixedServer (HTTP & SOCKS5) 单元测试
   Author :        JHao
   date：          2026/08/11
-------------------------------------------------
"""
__author__ = 'JHao'

import asyncio
from unittest.mock import MagicMock, patch
from helper.mixedServer import validate_auth, handle_http, handle_socks5, connect_upstream


class DummyWriter:
    def __init__(self):
        self.data = b""
        self.is_closed = False

    def write(self, d):
        self.data += d

    async def drain(self):
        pass

    def close(self):
        self.is_closed = True


class DummyReader:
    def __init__(self, data=b""):
        self.data = data

    async def read(self, n=-1):
        if not self.data:
            return b""
        if n == -1 or n >= len(self.data):
            res = self.data
            self.data = b""
            return res
        res = self.data[:n]
        self.data = self.data[n:]
        return res


def test_validate_auth():
    with patch("helper.mixedServer.ConfigHandler") as mock_cfg:
        mock_cfg.return_value.mixedAuthKeys = set()
        assert validate_auth("any") is True

        mock_cfg.return_value.mixedAuthKeys = {"secret123"}
        assert validate_auth("secret123") is True
        assert validate_auth("wrong") is False


def test_handle_http_auth_failure():
    async def _test():
        with patch("helper.mixedServer.ConfigHandler") as mock_cfg:
            mock_cfg.return_value.mixedAuthKeys = {"secret123"}
            reader = DummyReader(b"GET http://httpbin.org/ip HTTP/1.1\r\n\r\n")
            writer = DummyWriter()

            await handle_http(reader, writer, b"G")
            assert b"407 Proxy Authentication Required" in writer.data
            assert writer.is_closed is True
    asyncio.run(_test())


def test_handle_http_connect_success():
    async def _test():
        with patch("helper.mixedServer.validate_auth", return_value=True), \
             patch("helper.mixedServer.connect_upstream") as mock_conn, \
             patch("helper.mixedServer.pipe_streams") as mock_pipe:
            u_reader, u_writer = DummyReader(), DummyWriter()
            mock_conn.return_value = (u_reader, u_writer, True)
            mock_pipe.return_value = None

            reader = DummyReader(b"ONNECT httpbin.org:443 HTTP/1.1\r\n\r\n")
            writer = DummyWriter()

            await handle_http(reader, writer, b"C")
            assert b"200 Connection Established" in writer.data
            mock_pipe.assert_called_once()
    asyncio.run(_test())


def test_handle_http_get_tunnel_rewrite():
    async def _test():
        with patch("helper.mixedServer.validate_auth", return_value=True), \
             patch("helper.mixedServer.connect_upstream") as mock_conn, \
             patch("helper.mixedServer.pipe_streams") as mock_pipe:
            u_reader, u_writer = DummyReader(), DummyWriter()
            mock_conn.return_value = (u_reader, u_writer, True)
            mock_pipe.return_value = None

            reader = DummyReader(b"ET http://httpbin.org/ip?a=1 HTTP/1.1\r\nHost: httpbin.org\r\n\r\n")
            writer = DummyWriter()

            await handle_http(reader, writer, b"G")
            assert b"GET /ip?a=1 HTTP/1.1" in u_writer.data
            assert b"http://httpbin.org" not in u_writer.data
            mock_pipe.assert_called_once()
    asyncio.run(_test())


def test_connect_upstream_empty_pool():
    async def _test():
        with patch("helper.mixedServer.ProxyHandler") as mock_handler:
            mock_handler.return_value.getAll.return_value = []
            r, w, is_t = await connect_upstream("", "example.com", 80)
            assert r is None
            assert w is None
            assert is_t is False
    asyncio.run(_test())
