"""Bounded in-memory state. No audio or transcript persistence."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .style import DEFAULT_STYLE

RATE = 16000


class Discontinuity(Exception):
    pass


class AudioInbox:
    def __init__(self, seconds: float = 2):
        self.limit = int(seconds * RATE)
        self.items: deque[tuple[int, np.ndarray]] = deque()
        self.samples = 0
        self.received = 0
        self.last_offset = 0
        self.epoch = 0
        self.dropped = 0
        self.closed = False
        self.condition = threading.Condition()

    def reset(self):
        with self.condition:
            self.items.clear()
            self.samples = 0
            self.received = 0
            self.epoch += 1
            self.condition.notify_all()

    def put(self, audio: np.ndarray):
        with self.condition:
            if self.closed:
                return
            if self.samples + audio.size > self.limit:
                self.items.clear()
                self.samples = 0
                self.epoch += 1
                self.dropped += 1
            audio = np.array(audio[-self.limit :], dtype=np.float32, copy=True)
            self.items.append((self.received, audio))
            self.received += audio.size
            self.samples += audio.size
            self.condition.notify()

    def get(self, epoch: int | None = None, timeout: float = 0.5):
        with self.condition:
            self.condition.wait_for(
                lambda: self.items or self.closed or (epoch is not None and epoch != self.epoch), timeout
            )
            if epoch is not None and epoch != self.epoch:
                raise Discontinuity
            if not self.items:
                return None
            self.last_offset, audio = self.items.popleft()
            self.samples -= audio.size
            return audio

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class CaptionState:
    def __init__(self, ttl: float):
        self.lock = threading.Lock()
        self.ttl = ttl
        self.source = ""
        self.source_language = "und"
        self.color_rules = {"en": "#7CC7FF", "es": "#FFD166"}
        self.default_color = "#FFFFFF"
        self.style = dict(DEFAULT_STYLE)
        self.rows = deque(maxlen=8)
        self.row_serial = 0
        self.last_hypothesis = ""
        self.expired_hypothesis = None
        self.translations = {"es": "", "en": ""}
        self.translation_source = ""
        self.translation_enabled = False
        self.segment = 0
        self.flow_group = 0
        self.segment_audio_start_seconds = 0.0
        self.revision = 0
        self.updated = 0.0
        self.status = "Cargando modelos"
        self.error = ""
        self.final = False
        self.metrics: dict = {}
        self.events: deque[dict] = deque(maxlen=256)
        self.record_events = False

    def begin(self, continuation=False):
        with self.lock:
            self._expire_rows()
            previous = self.segment
            self.segment += 1
            self.flow_group = (
                self.rows[-1].get("flow_group", previous)
                if continuation and self.rows and self.rows[-1]["id"] == previous else self.segment
            )
            self.source = ""
            self.source_language = "und"
            self.translations = {"es": "", "en": ""}
            self.translation_source = ""
            self.updated = 0.0
            self.last_hypothesis = ""
            self.expired_hypothesis = None
            self.final = False
            self.revision += 1
            return self.segment

    def partial(self, segment: int, text: str, final: bool = False, spans=None):
        with self.lock:
            if segment != self.segment:
                return
            self._expire_rows()
            original = text
            text = text[-800:]
            if self.expired_hypothesis is not None and text == self.expired_hypothesis:
                return
            fresh_words = text != self.last_hypothesis
            self.last_hypothesis = text
            skip = max(0, len(original) - 800)
            if self.expired_hypothesis and text.startswith(self.expired_hypothesis):
                start = len(self.expired_hypothesis)
                suffix = text[start:]
                text = suffix.lstrip()
                skip += start + len(suffix) - len(text)
                if not any(char.isalnum() for char in text):
                    return
            elif self.expired_hypothesis:
                # A genuine ASR retraction is not an append. Do not guess words
                # or globally deduplicate phrases across independent utterances.
                self.expired_hypothesis = None
            if spans is not None and "".join(part["text"] for part in spans) == original:
                clipped = []
                for part in spans:
                    length = len(part["text"])
                    if skip < length:
                        clipped.append({"text": part["text"][skip:], "language": part["language"]})
                    skip = max(0, skip - length)
                spans = clipped
                known = {part["language"] for part in spans if part["language"] != "und"}
                self.source_language = next(iter(known)) if len(known) == 1 else "mixed" if known else "und"
            if not any(row["id"] == segment for row in self.rows):
                self.translations = {"es": "", "en": ""}
                self.translation_source = ""
            previous_language = (
                self.rows[-1]["language"] if self.rows and self.rows[-1]["id"] == segment else "und"
            )
            changed = text != self.source or final != self.final or self.source_language != previous_language
            self.source = text[-800:]
            self.final = final
            if fresh_words:
                self.updated = time.monotonic()
            self._upsert_row(segment, text=self.source, language=self.source_language, spans=spans,
                             refresh=fresh_words)
            self.revision += int(changed)
            if changed and text and self.record_events:
                self.events.append({"at": self.updated, "kind": "source", "segment": segment, "final": final})
            return self.source

    def translation_token(self, segment: int):
        with self.lock:
            self._expire_rows()
            return next((row["epoch"] for row in self.rows if row["id"] == segment), None)

    def translation_is_current(self, segment: int, source: str, row_epoch=None):
        if not source:
            return False
        with self.lock:
            self._expire_rows()
            return any(row["id"] == segment and (row_epoch is None or row["epoch"] == row_epoch) and (
                row["source"] == source[-500:] or
                (segment == self.segment and row["source"].startswith(source[-500:]))
            ) for row in self.rows)

    def translated(self, segment: int, source: str, values: dict[str, str], row_epoch=None):
        with self.lock:
            self._expire_rows()
            row = next((row for row in self.rows if row["id"] == segment), None)
            if row is None or (row_epoch is not None and row["epoch"] != row_epoch) or not source or not (
                row["source"] == source[-500:] or
                (segment == self.segment and row["source"].startswith(source[-500:]))
            ):
                return False
            row.update({key: value[-500:] for key, value in values.items()})
            row["translation_source"] = source[-500:]
            if segment == self.segment:
                self.translations.update({k: v[-800:] for k, v in values.items()})
                self.translation_source = source[-800:]
            self.revision += 1
            # Keep source freshness separate: a late translation must not revive expired speech.
            if self.record_events:
                self.events.append({"at": time.monotonic(), "kind": "translation", "segment": segment})
            return True

    def translation_required(self, segment: int):
        with self.lock:
            row = next((row for row in self.rows if row["id"] == segment), None)
            if row is None:
                return False
            # Only skip when every text span carrying letters is Spanish. A global
            # acoustic label alone must not suppress translation of mixed/unknown text.
            languages = {part["language"] for part in row.get("spans", [])
                         if any(char.isalpha() for char in part["text"])}
            return languages != {"es"}

    def clear(self):
        with self.lock:
            self.segment += 1
            self.source = ""
            self.source_language = "und"
            self.translations = {"es": "", "en": ""}
            self.translation_source = ""
            self.updated = 0
            self.last_hypothesis = ""
            self.expired_hypothesis = None
            self.rows.clear()
            self.revision += 1

    def snapshot(self):
        with self.lock:
            self._expire()
            fresh = time.monotonic() - self.updated < self.ttl
            return {
                "segment": self.segment,
                "segment_audio_start_seconds": self.segment_audio_start_seconds,
                "revision": self.revision,
                "source": self.source if fresh else "",
                "source_language": self.source_language,
                "subtitle_color": self.color_rules.get(self.source_language, self.default_color),
                "style": dict(self.style),
                "translation_display_color": (
                    self.color_rules.get("es", self.default_color)
                    if self.style["translation_use_spanish_color"] else self.style["translation_color"]
                ),
                "rows": [
                    {**row, "color": self.color_rules.get(row["language"], self.default_color),
                     "spans": [{**span, "color": self.color_rules.get(span["language"], self.default_color)}
                               for span in row.get("spans", [])]}
                    for row in self.rows
                ],
                "es": self.translations["es"] if fresh else "",
                "en": self.translations["en"] if fresh else "",
                "final": self.final,
                "translation_source": self.translation_source if fresh else "",
                "translation_enabled": self.translation_enabled,
                "status": self.status,
                "error": self.error,
                "metrics": dict(self.metrics),
            }

    def expire(self):
        with self.lock:
            self._expire()

    def set_translation(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("translation_enabled debe ser booleano")
        with self.lock:
            if enabled == self.translation_enabled:
                return
            self.translation_enabled = enabled
            self.translations = {"es": "", "en": ""}
            self.translation_source = ""
            for row in self.rows:
                row["es"] = row["en"] = ""
            self.revision += 1

    def _expire(self):
        self._expire_rows()
        if time.monotonic() - self.updated >= self.ttl and (self.source or self.translation_source):
            self.source = ""
            self.translations = {"es": "", "en": ""}
            self.translation_source = ""
            self.source_language = "und"
            self.revision += 1

    def _expire_rows(self):
        cutoff = time.monotonic() - self.ttl
        while self.rows and self.rows[0]["updated"] <= cutoff:
            retired = self.rows.popleft()
            if retired["id"] == self.segment:
                self.expired_hypothesis = self.last_hypothesis
        limit = self.style["max_rows"] if self.style["stack"] else 1
        while len(self.rows) > limit:
            self.rows.popleft()

    def _upsert_row(self, segment, text=None, translations=None, language="und", spans=None, refresh=True):
        if not text and translations is None:
            return
        self._expire_rows()
        if not self.rows or self.rows[-1]["id"] != segment:
            self.row_serial += 1
            self.rows.append(
                {
                    "id": segment,
                    "flow_group": self.flow_group,
                    "epoch": self.row_serial,
                    "source": "",
                    "es": "",
                    "en": "",
                    "language": language,
                    "updated": time.monotonic(),
                }
            )
        row = self.rows[-1]
        row["language"] = language
        if text is not None:
            row["source"] = text[-500:]
            if spans is not None and "".join(part["text"] for part in spans) == text:
                skip = max(0, len(text) - 500)
                row["spans"] = []
                for part in spans:
                    length = len(part["text"])
                    if skip < length:
                        row["spans"].append({"text": part["text"][skip:], "language": part["language"]})
                    skip = max(0, skip - length)
            else:
                row["spans"] = [{"text": row["source"], "language": language}]
            if refresh:
                row["updated"] = time.monotonic()
        if translations:
            row.update({key: value[-500:] for key, value in translations.items()})
        self._expire_rows()


@dataclass(frozen=True)
class TranslationJob:
    segment: int
    text: str
    final: bool
    created: float
    language: str = "und"
    row_epoch: int | None = None


class TranslationMailbox:
    """At most one final and one partial; final survives the next utterance's onset."""

    def __init__(self):
        self.condition = threading.Condition()
        self.job: TranslationJob | None = None
        self.final_job: TranslationJob | None = None
        self.closed = False

    def put(self, job: TranslationJob):
        with self.condition:
            if job.final:
                self.final_job = job
                if self.job and self.job.segment == job.segment:
                    self.job = None
            else:
                self.job = job
            self.condition.notify()

    def get(self, timeout=0.5):
        with self.condition:
            self.condition.wait_for(lambda: self.job is not None or self.final_job is not None
                                    or self.closed, timeout)
            if self.final_job is not None:
                job, self.final_job = self.final_job, None
            else:
                job, self.job = self.job, None
            return job

    def clear(self):
        with self.condition:
            self.job = None
            self.final_job = None

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class Context:
    def __init__(self, ttl=45.0, max_chars=1600):
        self.ttl, self.max_chars = ttl, max_chars
        self.items = deque(maxlen=4)
        self.lock = threading.Lock()

    def add(self, text: str, now: float | None = None):
        with self.lock:
            self.items.append((time.monotonic() if now is None else now, text[-400:]))

    def text(self, now: float | None = None):
        now = time.monotonic() if now is None else now
        with self.lock:
            while self.items and now - self.items[0][0] >= self.ttl:
                self.items.popleft()
            return "\n".join(x[1] for x in self.items)[-self.max_chars :]

    def clear(self):
        with self.lock:
            self.items.clear()


def level_db(audio: np.ndarray):
    return 20 * math.log10(max(float(np.sqrt(np.mean(np.square(audio)))), 1e-8))
