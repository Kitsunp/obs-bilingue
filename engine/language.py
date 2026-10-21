"""Automatic language identification, with an explicit unknown fallback."""

import re

# Nemotron's out-of-the-box language families; regional variants share colours.
SUPPORTED_LANGUAGES = frozenset(
    "en es de ar bg cs zh ko hr da sk et fi fr hi nl hu it ja nb pl pt ro ru sv tr uk vi".split()
)

def parse_colors(rules: str, default: str):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", default):
        raise ValueError("Color predeterminado invalido; usa #RRGGBB")
    colors = {}
    for line in rules.replace(";", "\n").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*([a-z]{2,3}(?:-[A-Za-z]{2,4})?)\s*=\s*(#[0-9a-fA-F]{6})\s*", line)
        if not match:
            raise ValueError("Regla de color invalida; ejemplo: en=#7CC7FF")
        colors[match[1].split("-")[0]] = match[2].upper()
        if len(colors) > 64:
            raise ValueError("Maximo 64 reglas de color")
    return colors, default.upper()


class LanguageDetector:
    def __init__(self):
        from langid.langid import LanguageIdentifier, model

        self.classifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
        self.last_text = ""
        self.last_language = "und"

    def identify(self, text, raw_tags=""):
        tags = set(re.findall(r"<([a-z]{2,3})(?:-[A-Za-z]{2,4})?>", raw_tags))
        if len(tags) > 1:
            return "mixed"
        terminal_tag = re.search(r"<([a-z]{2,3})(?:-[A-Za-z]{2,4})?>\s*(?:</s>)?$", raw_tags)
        if terminal_tag:
            return terminal_tag[1]
        # Scripts without word separators must not be rejected by a word-count gate.
        unspaced = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text))
        if len(text.strip()) < (6 if unspaced else 12) or (not unspaced and len(text.split()) < 3):
            return "und"
        if text == self.last_text:
            return self.last_language
        recent = text[-48:] if unspaced else " ".join(text.split()[-12:])[-160:]
        code, confidence = self.classifier.classify(recent)
        code = "nb" if code == "no" else code
        if 0.75 <= confidence < 0.90:
            previous_code, previous_confidence = self.classifier.classify(text[-500:])
            previous_code = "nb" if previous_code == "no" else previous_code
            if previous_code == code:
                confidence = max(confidence, previous_confidence)
        self.last_text = text
        # Never fall back to the old language when the speaker has just switched.
        self.last_language = code if confidence >= 0.90 and code in SUPPORTED_LANGUAGES else "und"
        return self.last_language
