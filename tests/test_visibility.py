import asyncio
import struct
import time

from engine.server import Engine, read_config


def test_managed_engine_only_exits_after_last_connection_and_grace():
    config = read_config()
    config["_managed"] = True
    engine = Engine(config)
    engine.ready = True
    engine.idle_since = 10
    assert not engine.should_idle_exit(12)
    assert engine.should_idle_exit(14)
    engine.connected = True
    assert not engine.should_idle_exit(100)
    engine.connected = False
    engine.ready = False
    assert not engine.should_idle_exit(100)


def test_heartbeat_keeps_visible_silent_source_connected_without_audio():
    async def run():
        engine = Engine(read_config())
        engine.ready = True

        class Context:
            def clear(self):
                pass

        class Translator:
            context = Context()

        engine.translator = Translator()
        server = await asyncio.start_server(engine.audio, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        for _ in range(2):
            writer.write(struct.pack("<4sIIII", b"BLCP", 0, 0, 0, 0))
            await writer.drain()
            await asyncio.sleep(0.01)
        assert engine.connected
        assert engine.inbox.samples == 0
        writer.close()
        await writer.wait_closed()
        assert await reader.read(1) == b""
        await asyncio.sleep(0.01)
        assert not engine.connected
        assert not engine.state.snapshot()["source"]
        assert time.monotonic() - engine.idle_since < 1
        server.close()
        await server.wait_closed()

    asyncio.run(run())
