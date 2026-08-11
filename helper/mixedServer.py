# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     mixedServer.py
   Description :   支持 HTTP 和 SOCKS5 协议的混合代理服务器
   Author :        JHao
   date：          2026/08/11
-------------------------------------------------
"""
__author__ = 'JHao'

import asyncio
import base64
import random
import socket
import struct
import threading
import urllib.parse

from handler.configHandler import ConfigHandler
from handler.logHandler import LogHandler
from handler.proxyHandler import ProxyHandler
from helper.proxyFilter import select_proxy

log = LogHandler('mixedServer')


def validate_auth(password):
    """ 校验密码/API Key 是否允许 """
    allowed_keys = ConfigHandler().mixedAuthKeys
    if not allowed_keys:
        return True
    return password in allowed_keys


async def relay(reader, writer):
    """ 单向数据转发 """
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            if hasattr(writer, 'wait_closed'):
                await writer.wait_closed()
        except Exception:
            pass


async def pipe_streams(client_reader, client_writer, upstream_reader, upstream_writer):
    """ 双向管道转发 """
    task1 = asyncio.create_task(relay(client_reader, upstream_writer))
    task2 = asyncio.create_task(relay(upstream_reader, client_writer))
    done, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


async def connect_upstream(username, target_host, target_port):
    """
    根据 username 筛选并连接上游代理，通过 HTTP CONNECT 建立隧道
    :return: (upstream_reader, upstream_writer, is_tunnel) 或 (None, None, False)
    """
    handler = ProxyHandler()
    all_proxies = handler.getAll()
    if not all_proxies:
        log.warning("MixedServer: Proxy pool is empty!")
        return None, None, False

    tried = set()
    for _ in range(3):
        proxy_obj = select_proxy(all_proxies, username)
        if not proxy_obj or proxy_obj.proxy in tried:
            remaining = [p for p in all_proxies if p.proxy not in tried]
            if not remaining:
                break
            proxy_obj = random.choice(remaining)

        tried.add(proxy_obj.proxy)

        try:
            ip, port_str = proxy_obj.proxy.split(":")
            port = int(port_str)

            u_reader, u_writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=3.0
            )

            # 发送 HTTP CONNECT 请求给上游代理
            connect_req = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" % (
                target_host, target_port, target_host, target_port
            )
            u_writer.write(connect_req.encode('utf-8'))
            await u_writer.drain()

            resp = await asyncio.wait_for(u_reader.read(4096), timeout=3.0)
            if b"200" in resp:
                log.info("MixedServer: Tunnel established via upstream %s (user: %s) -> %s:%d" % (
                    proxy_obj.proxy, username, target_host, target_port
                ))
                return u_reader, u_writer, True
            else:
                u_writer.close()
                if hasattr(u_writer, 'wait_closed'):
                    await u_writer.wait_closed()

                # 对 80 端口 HTTP 请求，若 CONNECT 不支持，尝试直接 TCP 连接
                if target_port == 80:
                    u_reader, u_writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, port),
                        timeout=3.0
                    )
                    return u_reader, u_writer, False
        except Exception as e:
            log.debug("MixedServer: Connect to upstream %s failed: %s" % (proxy_obj.proxy, str(e)))

    log.error("MixedServer: All upstream retries failed for user '%s' -> %s:%d" % (username, target_host, target_port))
    return None, None, False


async def handle_socks5(reader, writer, first_byte):
    """ 处理 SOCKS5 代理连接 """
    try:
        header = await reader.read(1)
        if not header:
            return
        nmethods = header[0]
        methods = await reader.read(nmethods)

        username = ""
        password = ""
        allowed_keys = ConfigHandler().mixedAuthKeys

        if 0x02 in methods:
            writer.write(b"\x05\x02")
            await writer.drain()

            auth_ver = await reader.read(1)
            if not auth_ver or auth_ver[0] != 1:
                return
            ulen_byte = await reader.read(1)
            if not ulen_byte:
                return
            ulen = ulen_byte[0]
            user_bytes = await reader.read(ulen)
            username = user_bytes.decode('utf-8', errors='ignore')

            plen_byte = await reader.read(1)
            if not plen_byte:
                return
            plen = plen_byte[0]
            pwd_bytes = await reader.read(plen)
            password = pwd_bytes.decode('utf-8', errors='ignore')

            if not validate_auth(password):
                log.warning("MixedServer: SOCKS5 auth failed for user '%s'" % username)
                writer.write(b"\x01\x01")
                await writer.drain()
                return

            writer.write(b"\x01\x00")
            await writer.drain()
        elif allowed_keys:
            log.warning("MixedServer: SOCKS5 auth required but client provided no 0x02 method")
            writer.write(b"\x05\xff")
            await writer.drain()
            return
        else:
            writer.write(b"\x05\x00")
            await writer.drain()

        req_header = await reader.read(4)
        if len(req_header) < 4:
            return
        ver, cmd, rsv, atyp = req_header
        if cmd != 1:
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        target_host = ""
        if atyp == 1:
            ip_bytes = await reader.read(4)
            target_host = socket.inet_ntoa(ip_bytes)
        elif atyp == 3:
            dlen_byte = await reader.read(1)
            if not dlen_byte:
                return
            dlen = dlen_byte[0]
            domain_bytes = await reader.read(dlen)
            target_host = domain_bytes.decode('utf-8', errors='ignore')
        elif atyp == 4:
            ip6_bytes = await reader.read(16)
            target_host = socket.inet_ntop(socket.AF_INET6, ip6_bytes)
        else:
            return

        port_bytes = await reader.read(2)
        if len(port_bytes) < 2:
            return
        target_port = struct.unpack("!H", port_bytes)[0]

        upstream_reader, upstream_writer, is_tunnel = await connect_upstream(username, target_host, target_port)
        if not upstream_reader:
            writer.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

        await pipe_streams(reader, writer, upstream_reader, upstream_writer)
    except Exception as e:
        log.debug("MixedServer SOCKS5 Exception: %s" % str(e))
    finally:
        try:
            writer.close()
        except Exception:
            pass
        try:
            if 'upstream_writer' in locals() and upstream_writer:
                upstream_writer.close()
        except Exception:
            pass


async def handle_http(reader, writer, first_byte):
    """ 处理 HTTP / HTTPS (CONNECT) 代理连接 """
    try:
        buffer = first_byte
        while b"\r\n\r\n" not in buffer:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer += chunk

        if not buffer:
            return

        header_end = buffer.find(b"\r\n\r\n")
        if header_end == -1:
            return

        header_text = buffer[:header_end].decode('latin1', errors='ignore')
        lines = header_text.split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            return

        method, url = parts[0], parts[1]

        username = ""
        password = ""
        for line in lines[1:]:
            if ":" in line:
                h_name, h_val = line.split(":", 1)
                h_name = h_name.strip().lower()
                h_val = h_val.strip()
                if h_name in ("proxy-authorization", "authorization"):
                    if h_val.lower().startswith("basic "):
                        try:
                            auth_str = base64.b64decode(h_val[6:]).decode('utf-8')
                            if ":" in auth_str:
                                username, password = auth_str.split(":", 1)
                            else:
                                username = auth_str
                        except Exception:
                            pass

        if method.upper() == "CONNECT":
            if ":" in url:
                target_host, target_port_str = url.split(":", 1)
                target_port = int(target_port_str)
            else:
                target_host = url
                target_port = 443
        else:
            parsed = urllib.parse.urlparse(url)
            target_host = parsed.hostname or ""
            target_port = parsed.port or 80
            if not username and parsed.username:
                username = parsed.username
            if not password and parsed.password:
                password = parsed.password

        if not validate_auth(password):
            log.warning("MixedServer: HTTP auth failed for user '%s'" % username)
            writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm=\"Proxy Pool\"\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return

        if not target_host:
            return

        upstream_reader, upstream_writer, is_tunnel = await connect_upstream(username, target_host, target_port)
        if not upstream_reader:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return

        if method.upper() == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await pipe_streams(reader, writer, upstream_reader, upstream_writer)
        else:
            if is_tunnel:
                parsed = urllib.parse.urlparse(url)
                rel_path = parsed.path if parsed.path else "/"
                if parsed.query:
                    rel_path += "?" + parsed.query
                http_version = parts[2] if len(parts) > 2 else "HTTP/1.1"
                new_request_line = "%s %s %s" % (method, rel_path, http_version)

                filtered_lines = [new_request_line]
                for line in lines[1:]:
                    if line.lower().startswith("proxy-authorization:"):
                        continue
                    filtered_lines.append(line)
                new_header_text = "\r\n".join(filtered_lines)
                out_buffer = new_header_text.encode('latin1') + buffer[header_end:]
            else:
                out_buffer = buffer

            upstream_writer.write(out_buffer)
            await upstream_writer.drain()
            await pipe_streams(reader, writer, upstream_reader, upstream_writer)
    except Exception as e:
        log.debug("MixedServer HTTP Exception: %s" % str(e))
    finally:
        try:
            writer.close()
        except Exception:
            pass
        try:
            if 'upstream_writer' in locals() and upstream_writer:
                upstream_writer.close()
        except Exception:
            pass


async def handle_client(reader, writer):
    """ 根据协议首字节自动分发 HTTP 或 SOCKS5 """
    try:
        first_byte = await reader.read(1)
        if not first_byte:
            writer.close()
            return

        if first_byte == b"\x05":
            await handle_socks5(reader, writer, first_byte)
        else:
            await handle_http(reader, writer, first_byte)
    except Exception as e:
        log.debug("MixedServer Client Exception: %s" % str(e))


def run_mixed_server(host=None, port=None):
    """ 阻塞式运行 Mixed 代理服务器 """
    conf = ConfigHandler()
    host = host or getattr(conf, 'mixedHost', conf.serverHost)
    port = port or getattr(conf, 'mixedPort', 5011)

    log.info("Starting Mixed Proxy Server (HTTP & SOCKS5) on %s:%d ..." % (host, port))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    server_coro = asyncio.start_server(handle_client, host, port, loop=loop)
    server = loop.run_until_complete(server_coro)
    log.info("Mixed Proxy Server is running on %s:%d" % (host, port))

    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()


def start_mixed_server_thread(host=None, port=None):
    """ 后台线程方式启动 Mixed 代理服务器 """
    t = threading.Thread(target=run_mixed_server, args=(host, port), daemon=True, name="MixedServerThread")
    t.start()
    return t
