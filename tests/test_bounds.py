import time

import numpy as np
import pytest

from engine.core import AudioInbox, CaptionState, Context, Discontinuity, TranslationJob, TranslationMailbox


def test_audio_overload_discards_backlog_and_signals_discontinuity():
    inbox = AudioInbox(0.1)
    epoch = inbox.epoch
    for _ in range(100_000):
        inbox.put(np.zeros(320, np.float32))
        assert inbox.samples <= 1600
    assert inbox.dropped > 0
    with pytest.raises(Discontinuity):
        inbox.get(epoch)


def test_context_cannot_grow_over_hours():
    context = Context(ttl=45)
    for step in range(72_000):
        context.add("x" * 5000, now=step)
        assert len(context.text(now=step)) <= 1600
        assert len(context.items) <= 4
    assert context.text(now=73_000) == ""


def test_new_segment_rejects_late_translation():
    state = CaptionState(9)
    old = state.begin()
    state.partial(old, "old")
    new = state.begin()
    state.partial(new, "new")
    state.translated(old, "old", {"es": "viejo"})
    assert state.snapshot()["es"] == ""


def test_translation_does_not_revive_expired_caption():
    state = CaptionState(0.001)
    segment = state.begin()
    state.partial(segment, "Hello")
    state.updated -= 1
    for row in state.rows:
        row["updated"] -= 1
    state.translated(segment, "Hello", {"es": "Hola"})
    assert state.snapshot()["es"] == ""
    assert state.snapshot()["rows"] == []


def test_mailbox_has_only_one_latest_revision():
    box = TranslationMailbox()
    for revision in range(10_000):
        box.put(TranslationJob(1, str(revision), False, time.monotonic()))
    assert box.get().text == "9999"
    assert box.get(timeout=0) is None


def test_close_wakes_reader():
    inbox = AudioInbox()
    inbox.close()
    assert inbox.get() is None


def test_state_event_buffer_bounded_and_disabled_by_default():
    state = CaptionState(9)
    segment = state.begin()
    state.partial(segment, "hello")
    assert not state.events
    state.record_events = True
    for n in range(10_000):
        state.partial(segment, str(n))
    assert len(state.events) == 256
