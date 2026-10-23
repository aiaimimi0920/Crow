"""Allowlisted TCP access to a local-only AI Gateway, without credential logging."""

import argparse
import asyncio
import ipaddress
import logging
from contextlib import suppress

LOGGER = logging.getLogger(__name__)


class GatewayRelay:
    def __init__(
        self,
        upstream_host,
        upstream_port,
        allowed_clients,
        *,
        limit=64,
        idle_timeout=650,
        connect_timeout=10,
    ):
        address = ipaddress.ip_address(upstream_host)
        if not address.is_loopback or not 1 <= upstream_port <= 65535:
            raise ValueError(
                "Gateway upstream must be an explicit loopback address and valid port"
            )
        self.upstream = (str(address), upstream_port)
        self.allowed = frozenset(
            ipaddress.ip_address(value) for value in allowed_clients
        )
        if not self.allowed or limit < 1 or idle_timeout <= 0 or connect_timeout <= 0:
            raise ValueError("An allowlist and positive relay limits are required")
        self.limit, self.idle_timeout = limit, idle_timeout
        self.connect_timeout = connect_timeout
        self.active = 0

    async def pipe(self, reader, writer):
        while data := await asyncio.wait_for(reader.read(65536), self.idle_timeout):
            writer.write(data)
            await asyncio.wait_for(writer.drain(), self.idle_timeout)
        if writer.can_write_eof():
            writer.write_eof()

    @staticmethod
    async def close(writer):
        writer.close()
        with suppress(OSError, asyncio.TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), 5)

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        try:
            allowed = peer and ipaddress.ip_address(peer[0]) in self.allowed
        except ValueError:
            allowed = False
        if not allowed or self.active >= self.limit:
            await self.close(writer)
            return
        self.active += 1
        upstream_writer = None
        tasks = []
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(*self.upstream), self.connect_timeout
            )
            tasks = [
                asyncio.create_task(self.pipe(reader, upstream_writer)),
                asyncio.create_task(self.pipe(upstream_reader, writer)),
            ]
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                task.result()
            await asyncio.gather(*pending)
        except (OSError, asyncio.TimeoutError):
            LOGGER.warning("Gateway connection unavailable")
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if upstream_writer is not None:
                await self.close(upstream_writer)
            await self.close(writer)
            self.active -= 1


async def serve(args):
    address = ipaddress.ip_address(args.listen_host)
    if address.is_unspecified or not 1 <= args.listen_port <= 65535:
        raise ValueError("Relay requires a specific local address and valid port")
    relay = GatewayRelay(args.upstream_host, args.upstream_port, args.allow_client)
    server = await asyncio.start_server(relay.handle, str(address), args.listen_port)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, default=4200)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=4200)
    parser.add_argument("--allow-client", action="append", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
