import math
import re
from collections import Counter
from importlib.resources import files

STOP_WORDS = set("a an and are as at be by for from in is it of on or that the to with".split())


def _tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS]


class Retriever:
    def __init__(self, markdown: str | None = None) -> None:
        if markdown is None:
            markdown = files("iiot_agent").joinpath("manual/pump_P101.md").read_text(encoding="utf-8")
        self.sections: list[tuple[str, str]] = []
        heading, lines = None, []
        for line in markdown.splitlines():
            if re.match(r"^#{2,3} ", line):
                if heading is not None:
                    self.sections.append((heading, "\n".join(lines).strip()))
                heading, lines = line.lstrip("# "), []
            elif heading is not None:
                lines.append(line)
        if heading is not None:
            self.sections.append((heading, "\n".join(lines).strip()))
        self._terms = [Counter(_tokens(h + " " + t)) for h, t in self.sections]
        self._lengths = [sum(terms.values()) for terms in self._terms]

    def search(self, query: str, k: int = 3) -> list[tuple[float, str, str]]:
        if not self.sections or k <= 0:
            return []
        count = len(self.sections)
        average = sum(self._lengths) / count or 1
        scores = [0.0] * count
        for term in sorted(set(_tokens(query))):
            frequency = sum(term in terms for terms in self._terms)
            idf = math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for i, terms in enumerate(self._terms):
                tf = terms[term]
                scores[i] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * self._lengths[i] / average))
        order = sorted(range(count), key=lambda i: (-scores[i], i))[:k]
        return [(scores[i], *self.sections[i]) for i in order]
