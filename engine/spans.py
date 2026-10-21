"""Text language spans for presentation; never changes recognized words."""

import re
from collections import OrderedDict

from .language import SUPPORTED_LANGUAGES


class SpanDetector:
    def __init__(self, config):
        from lingua import IsoCode639_1, LanguageDetectorBuilder

        codes = [getattr(IsoCode639_1, code.upper()) for code in sorted(SUPPORTED_LANGUAGES)]
        self.detector = LanguageDetectorBuilder.from_iso_codes_639_1(*codes).build()
        self.minimum = config["span_language_min_confidence"]
        self.minimum_posterior = config["span_language_min_posterior"]
        self.margin_ratio = config["span_language_margin_ratio"]
        self.minimum_letters = config["span_language_min_letters"]
        self.minimum_unspaced_letters = config["span_language_min_unspaced_letters"]
        self.cache = OrderedDict()

    def identify(self, text):
        return self.analyze(text)[0]

    def analyze(self, text, acoustic_language="und", final=False):
        spans = []
        # Sentence boundaries prevent evidence from one sentence colouring the next.
        for match in re.finditer(r"[^.!?。！？]+[.!?。！？]*\s*|[.!?。！？]+\s*", text):
            clause = match[0]
            if clause not in self.cache:
                parts, cursor = [], 0
                for result in self.detector.detect_multiple_languages_of(clause):
                    start, end = result.start_index, result.end_index
                    if start > cursor:
                        parts.append({"text": clause[cursor:start], "language": "und"})
                    value = clause[start:end]
                    values = self.detector.compute_language_confidence_values(value)
                    confidence = next(item.value for item in values if item.language == result.language)
                    runner_up = max((item.value for item in values if item.language != result.language),
                                    default=0)
                    code = result.language.iso_code_639_1.name.lower()
                    letters = sum(char.isalpha() for char in value)
                    unspaced = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", value))
                    enough_text = (letters >= self.minimum_unspaced_letters if unspaced else
                                   letters >= self.minimum_letters and len(value.split()) >= 2)
                    decisive = (confidence >= self.minimum or
                                (confidence >= self.minimum_posterior
                                 and confidence >= self.margin_ratio * runner_up))
                    parts.append({"text": value, "language": code if enough_text and decisive else "und",
                                  "candidate": code})
                    cursor = end
                if cursor < len(clause):
                    parts.append({"text": clause[cursor:], "language": "und"})
                self.cache[clause] = parts
                while len(self.cache) > 16:
                    self.cache.popitem(last=False)
            spans.extend(dict(part) for part in self.cache[clause])
        known = {part["language"] for part in spans if part["language"] != "und"}
        acoustic_known = acoustic_language in SUPPORTED_LANGUAGES
        for part in spans:
            if part["language"] != "und" or not acoustic_known:
                continue
            # Agreeing independent evidence may resolve a weak text decision.
            agreement = part.get("candidate") == acoustic_language
            # A final acoustic tag may resolve an otherwise unclassified utterance.
            # Never spread its colour across an already detected language switch.
            if agreement or (final and not known - {acoustic_language}):
                part["language"] = acoustic_language
        spans = [{"text": part["text"], "language": part["language"]} for part in spans]
        languages = {part["language"] for part in spans if part["language"] != "und"}
        language = next(iter(languages)) if len(languages) == 1 else "mixed" if languages else "und"
        return spans, language
