"""Offline network proof for the source-restricted Gateway relay."""

import asyncio
import unittest
from contextlib import suppress

from tools.crow_ai_gateway_relay import GatewayRelay


class GatewayRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []
        self.connections = 0

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()

    async def start(self, callback):
        server = await asyncio.start_server(callback, "127.0.0.1", 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def upstream(self, reader, writer):
        self.connections += 1
        body = await reader.read()
        writer.write(body[::-1])
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def request(self, port, body):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(body)
        await writer.drain()
        writer.write_eof()
        result = await asyncio.wait_for(reader.read(), 2)
        writer.close()
        await writer.wait_closed()
        return result

    async def test_allowed_client_preserves_bytes_and_half_close(self):
        upstream_port = await self.start(self.upstream)
        relay = GatewayRelay("127.0.0.1", upstream_port, ["127.0.0.1"])
        port = await self.start(relay.handle)
        payload = b"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer private\r\n\x00\xff"
        self.assertEqual(await self.request(port, payload), payload[::-1])
        self.assertEqual(self.connections, 1)
        for _ in range(100):
            if relay.active == 0:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(relay.active, 0)

    async def test_denied_client_never_connects_upstream(self):
        upstream_port = await self.start(self.upstream)
        relay = GatewayRelay("127.0.0.1", upstream_port, ["192.0.2.1"])
        port = await self.start(relay.handle)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.connections, 0)

    async def test_connection_limit_does_not_open_upstream(self):
        upstream_port = await self.start(self.upstream)
        relay = GatewayRelay("127.0.0.1", upstream_port, ["127.0.0.1"], limit=1)
        relay.active = 1
        port = await self.start(relay.handle)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.connections, 0)

    async def test_unavailable_upstream_closes_client(self):
        upstream_port = await self.start(self.upstream)
        self.servers[-1].close()
        await self.servers[-1].wait_closed()
        relay = GatewayRelay(
            "127.0.0.1", upstream_port, ["127.0.0.1"], connect_timeout=0.1
        )
        port = await self.start(relay.handle)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
        self.assertEqual(relay.active, 0)

    def test_only_loopback_upstream_and_explicit_allowlist_are_accepted(self):
        for host, port, clients in [
            ("192.0.2.1", 4200, ["127.0.0.1"]),
            ("127.0.0.1", 0, ["127.0.0.1"]),
            ("127.0.0.1", 4200, []),
        ]:
            with (
                self.subTest(host=host, port=port, clients=clients),
                self.assertRaises(ValueError),
            ):
                GatewayRelay(host, port, clients)
