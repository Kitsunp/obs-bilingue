import asyncio
import json
import struct

import numpy as np

from engine.core import AudioInbox, CaptionState, TranslationMailbox
from engine.server import Engine, read_config


class StubTranslator:
    class Context:
        def clear(self):
            pass

    context = Context()


def test_translation_style_arrives_through_native_configuration_frame():
    async def run():
        engine = Engine(read_config())
        engine.ready = True
        engine.translator = StubTranslator()
        server = await asyncio.start_server(engine.audio, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        options = {"color_rules": "es=#123456", "default_color": "#FFFFFF",
                   "translation_use_original_font": False, "translation_font_face": "Consolas",
                   "translation_font_size": 27, "translation_font_flags": 2,
                   "translation_use_spanish_color": True}
        payload = json.dumps(options).encode()
        writer.write(struct.pack("<4sIIII", b"BLCF", 0, len(payload), 0, 0) + payload)
        await writer.drain()
        await asyncio.sleep(0.05)
        snapshot = engine.state.snapshot()
        assert snapshot["translation_display_color"] == "#123456"
        assert snapshot["style"]["translation_font_face"] == "Consolas"
        assert snapshot["style"]["translation_font_size"] == 27
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
    asyncio.run(run())


def test_real_tcp_fragmentation_and_bad_frame_does_not_allocate():
    async def run():
        engine = Engine(read_config())
        engine.ready = True
        engine.translator = StubTranslator()
        server = await asyncio.start_server(engine.audio, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        packet = struct.pack("<4sIIII", b"BLC1", 16000, 1024, 0, 0)
        packet += np.zeros(1024, np.float32).tobytes()
        for index in range(0, len(packet), 19):
            writer.write(packet[index : index + 19])
            await writer.drain()
        await asyncio.sleep(0.05)
        assert 0 < engine.inbox.samples <= 1024
        writer.write(struct.pack("<4sIIII", b"BLC1", 16000, 0xFFFFFFFF, 1, 0))
        await writer.drain()
        await asyncio.sleep(0.05)
        assert engine.state.error == "Paquete de audio o configuracion invalido"
        assert engine.inbox.samples <= 1024
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_only_one_audio_client_accepted():
    async def run():
        engine = Engine(read_config())
        engine.ready = True
        engine.translator = StubTranslator()
        engine.inbox = AudioInbox()
        engine.state = CaptionState(9)
        engine.mailbox = TranslationMailbox()
        server = await asyncio.start_server(engine.audio, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _, first = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(0.01)
        reader, second = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(reader.read(1), 1) == b""
        first.close()
        second.close()
        await first.wait_closed()
        await second.wait_closed()
        await asyncio.sleep(0.01)
        server.close()
        await server.wait_closed()

    asyncio.run(run())
