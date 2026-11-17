"""Keep original layout and business values outside generated text."""

import re
from collections import Counter
from dataclasses import dataclass

from .exceptions import InvalidModelResponse

MARKER = re.compile(r"ZXQVAL\d{5}X")
PREFIX = re.compile(
    r"^[ \t]*(?:(?:[•●▪◦‣⁃][ \t]*|[-*+][ \t]+|\d+[.)][ \t]+|[A-Za-z][.)][ \t]+))?"
)
AMOUNT = r"[-+−]?\d+(?:[ \t\u00a0\u202f.,]\d+)*"
MEASURE = r"(?:mm|cm|m|kg|g|ml|l|W|kW|V|A)(?:[²³23])?"
PATTERNS = (
    re.compile(r"https?://[^\s<>\[\]()]+(?<![.,;:!?])", re.I),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[\w-]+[®™]"),
    re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4})\b"),
    re.compile(
        rf"(?<!\w)(?:(?:MAD|DHS?|EUR|USD|[$€£])[ \t]*{AMOUNT}|{AMOUNT}[ \t]*(?:MAD|DHS?|EUR|USD|[$€£]))(?!\w)",
        re.I,
    ),
    re.compile(
        rf"(?<!\w)\d+(?:[.,]\d+)?(?:[ \t]*[*×x][ \t]*\d+(?:[.,]\d+)?)+(?:[ \t]*{MEASURE})?(?!\w)",
        re.I,
    ),
    re.compile(rf"(?<!\w){AMOUNT}[ \t]*{MEASURE}(?!\w)", re.I),
    re.compile(rf"(?<!\w){AMOUNT}[ \t]*°(?:[CF])?", re.I),
    re.compile(
        r"\b(?=[\w/-]*[^\W\d_])(?=[\w/-]*[\d⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉])\w+(?:[-/]\w+)*\b"
    ),
    re.compile(rf"(?<!\w){AMOUNT}(?:[ \t]*%)?"),
    re.compile(r"\b(?:MAD|DHS?|EUR|USD)\b|[$€£%]|(?<![Nn])°", re.I),
    re.compile(r"\b(?:mm|cm|m)[²³23]\b", re.I),
    re.compile(r"\bSOFT[ -]+CLOSE\b", re.I),
    re.compile(r"\b(?:ISPM|ISO|DIN|ASTM|NF|EN)[ -]?\d+(?::\d{4})?\b", re.I),
    re.compile(r"\b(?:Blanc Europe|White Ceramic)\b"),
    re.compile(r"(?<!\w)\w{400,}(?!\w)"),
    re.compile(
        r"\b(?i:Villa|Résidence|Chantier)[ \t]+[A-ZÀ-ÖØ-Þ][\w’'-]+(?:[ \t]+[A-ZÀ-ÖØ-Þ][\w’'-]+)*"
    ),
)
UNITS = re.compile(
    r"(?<!['’])\b(?:cm|mm|kg|ml|kW|m|m[²³23]|EUR|USD|MAD|DH|DHS|euros?|dollars?|dirhams?)\b|[$€£%°]",
    re.I,
)
PASSTHROUGH = frozenset(
    ("m", "m²", "m³", "m2", "m3", "ml", "kg", "g", "l", "cm", "mm", "u", "pcs", "pc")
)


def value_spans(value, names=()):
    spans = [
        (m.start(), m.end()) for pattern in PATTERNS for m in pattern.finditer(value)
    ]
    for name in names:
        if isinstance(name, str) and name.strip() and len(name) > 1:
            spans.extend(
                (m.start(), m.end())
                for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", value, re.I)
            )
    merged = []
    for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
        if merged and (
            start < merged[-1][1]
            or (
                not any(c.isalnum() for c in value[merged[-1][1] : start])
                and "\n" not in value[merged[-1][1] : start]
                and "\r" not in value[merged[-1][1] : start]
            )
        ):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True)
class Line:
    prefix: str
    body: str
    suffix: str
    ending: str
    replacements: dict
    original: str

    @classmethod
    def create(cls, value, ending, names, marker_index):
        prefix = PREFIX.match(value).group()
        rest = value[len(prefix) :]
        suffix = rest[len(rest.rstrip(" \t")) :]
        body = rest[: len(rest) - len(suffix)] if suffix else rest
        if MARKER.search(body):
            raise InvalidModelResponse("Le texte contient un marqueur réservé.")
        parts, replacements, cursor = [], {}, 0
        for start, end in value_spans(body, names):
            marker = f"ZXQVAL{marker_index:05d}X"
            marker_index += 1
            replacements[marker] = body[start:end]
            parts.extend((body[cursor:start], marker))
            cursor = end
        parts.append(body[cursor:])
        return (
            cls(prefix, "".join(parts), suffix, ending, replacements, body),
            marker_index,
        )

    def restore(self, generated):
        if not isinstance(generated, str) or "\n" in generated or "\r" in generated:
            raise InvalidModelResponse(
                "La réponse IA a modifié la structure des lignes."
            )
        expected = list(MARKER.findall(self.body))
        actual = list(MARKER.findall(generated))
        if actual != expected:
            raise InvalidModelResponse("La réponse IA a modifié une valeur protégée.")
        for match in MARKER.finditer(generated):
            original = self.body.find(match.group())
            for adjacent, original_adjacent in (
                (match.start() - 1, original - 1),
                (match.end(), original + len(match.group())),
            ):
                if 0 <= adjacent < len(generated) and generated[adjacent].isalnum():
                    if not (
                        0 <= original_adjacent < len(self.body)
                        and self.body[original_adjacent].isalnum()
                    ):
                        raise InvalidModelResponse(
                            "La réponse IA a modifié une valeur protégée."
                        )
        plain_source = MARKER.sub("", self.body)
        plain_target = MARKER.sub("", generated)
        if re.findall(r"\d", plain_source) != re.findall(r"\d", plain_target):
            raise InvalidModelResponse("La réponse IA a ajouté une quantité.")
        if Counter(
            m.group().casefold() for m in UNITS.finditer(plain_target)
        ) - Counter(m.group().casefold() for m in UNITS.finditer(plain_source)):
            raise InvalidModelResponse("La réponse IA a ajouté une unité.")
        if PREFIX.match(generated).group().strip():
            raise InvalidModelResponse("La réponse IA a ajouté une liste.")
        generated = generated.strip(" \t")
        if self.body.strip() and not generated:
            raise InvalidModelResponse()
        for marker, original in self.replacements.items():
            generated = generated.replace(marker, original)
        return self.prefix + generated + self.suffix + self.ending

    @property
    def hints(self):
        return {
            marker: (
                "dimension; includes any original unit"
                if re.search(r"\d[ \t]*[*×x][ \t]*\d", value)
                else "immutable business value; includes any original unit or currency"
            )
            for marker, value in self.replacements.items()
        }

    @property
    def needs_model(self):
        return self.original.strip().casefold() not in PASSTHROUGH and any(
            c.isalpha() for c in MARKER.sub("", self.body)
        )


class Document:
    def __init__(self, text, names=()):
        self.text = text
        self.lines = []
        marker_index = 0
        for raw in text.splitlines(keepends=True):
            ending_match = re.search(r"(\r\n|\n|\r)$", raw)
            ending = ending_match.group() if ending_match else ""
            content = raw[: -len(ending)] if ending else raw
            line, marker_index = Line.create(content, ending, names, marker_index)
            self.lines.append(line)

    @property
    def model_lines(self):
        return [
            {"id": str(index), "text": line.body, "value_hints": line.hints}
            for index, line in enumerate(self.lines)
            if line.needs_model
        ]

    def restore(self, generated, language, action):
        if not isinstance(generated, list):
            raise InvalidModelResponse()
        mapped = {}
        for entry in generated:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"id", "text"}
                or not isinstance(entry["id"], str)
                or entry["id"] in mapped
            ):
                raise InvalidModelResponse()
            mapped[entry["id"]] = entry["text"]
        expected = {entry["id"] for entry in self.model_lines}
        if set(mapped) != expected:
            raise InvalidModelResponse("La réponse IA a modifié le nombre de lignes.")
        result = "".join(
            (
                line.restore(mapped[str(index)])
                if line.needs_model
                else line.prefix + line.original + line.suffix + line.ending
            )
            for index, line in enumerate(self.lines)
        )
        validate_meaning(
            "\n".join(line.body for line in self.lines),
            "\n".join(mapped.values()),
            language,
            action,
        )
        if re.findall(r"\r\n|\n|\r", result) != re.findall(r"\r\n|\n|\r", self.text):
            raise InvalidModelResponse(
                "La réponse IA a modifié les retours à la ligne."
            )
        return result


def validate_meaning(source, target, language, action="translate"):
    construction = bool(
        re.search(
            r"\b(?:pose|carrelage|travaux|céramique|chantier|isolation)\b", source, re.I
        )
    )
    owner = re.search(
        r"ma[iî]tre\s+d['’]ouvrage|project owner|opdrachtgever|bouwheer", source, re.I
    )
    if language == "fr" and owner:
        if not re.search(
            r"ma[iî]tre\s+d['’]ouvrage|propriétaire du projet|client|donneur d['’]ordre",
            target,
            re.I,
        ):
            raise InvalidModelResponse(
                "La réponse IA a modifié le responsable des travaux."
            )
        if re.search(r"entrepreneur", target, re.I) and not re.search(
            r"entrepreneur|contractor|aannemer", source, re.I
        ):
            raise InvalidModelResponse("La réponse IA a inversé une responsabilité.")
    if language == "en":
        if owner:
            if not re.search(
                r"\b(?:project owner|owner|client|employer)\b", target, re.I
            ):
                raise InvalidModelResponse(
                    "La réponse IA a modifié le responsable des travaux."
                )
            if re.search(r"contractor", target, re.I) and not re.search(
                r"entrepreneur|contractant|contractor|aannemer", source, re.I
            ):
                raise InvalidModelResponse(
                    "La réponse IA a inversé une responsabilité."
                )
        forbidden = []
        if construction and re.search(r"\bmétrage\b", source, re.I):
            forbidden.append(r"\bfilm\b")
        if re.search(r"\bmasticage\b", source, re.I):
            forbidden.append(r"\bmasticat")
        if re.search(r"\btrop[ -]plein\b", source, re.I):
            forbidden.append(r"\btoo full\b")
        if re.search(r"\bbonde\b", source, re.I):
            forbidden.append(r"\bbond\b")
        if re.search(r"\bpose de plinthe", source, re.I):
            forbidden.append(r"\bplating\b")
        if any(re.search(pattern, target, re.I) for pattern in forbidden):
            raise InvalidModelResponse(
                "La traduction utilise un terme technique incorrect."
            )
    if (
        language == "en"
        and re.search(r"toiture[ -]terrasse", source, re.I)
        and not re.search(r"jardin|végétalis", source, re.I)
    ):
        if re.search(r"roof garden", target, re.I):
            raise InvalidModelResponse(
                "La traduction a changé une toiture-terrasse en jardin."
            )
    if language == "nl":
        if re.search(r"origine préférentielle UE", source, re.I) and not re.search(
            r"preferenti[eë]le.{0,15}EU|EU.{0,15}preferenti[eë]le", target, re.I
        ):
            raise InvalidModelResponse(
                "La traduction a changé l’origine préférentielle."
            )
        if re.search(r"N[°º].*scellé", source, re.I) and not re.search(
            r"zegelnummer|nummer.{0,20}zegel", target, re.I
        ):
            raise InvalidModelResponse("La traduction a changé le numéro de scellé.")
        if re.search(r"trop[ -]plein", source, re.I) and re.search(
            r"\boverflow\b", target, re.I
        ):
            raise InvalidModelResponse(
                "Un terme technique n’a pas été traduit en néerlandais."
            )
        if re.search(r"toiture[ -]terrasse", source, re.I) and not re.search(
            r"jardin|végétalis", source, re.I
        ):
            if not re.search(r"dakterras", target, re.I):
                raise InvalidModelResponse(
                    "La traduction a changé le type de terrasse."
                )
        if re.search(r"monotrou", source, re.I) and re.search(r"eenpits", target, re.I):
            raise InvalidModelResponse("La traduction a changé le type de robinet.")
    if language == "nl" and owner:
        if not re.search(
            r"\b(?:opdrachtgever|bouwheer|projecteigenaar)\b", target, re.I
        ):
            raise InvalidModelResponse(
                "La réponse IA a modifié le responsable des travaux."
            )
    if re.search(
        r"\b(?:non compris|non inclus[e]?|pas inclus|not included|niet inbegrepen)\b",
        source,
        re.I,
    ):
        if language == "fr" and not re.search(
            r"\b(?:non compris|non inclus[e]?|pas inclus|exclu)", target, re.I
        ):
            raise InvalidModelResponse("La réponse IA a supprimé une exclusion.")
        if language == "en" and not re.search(
            r"\b(?:not\b.{0,30}\binclud|exclud)", target, re.I | re.S
        ):
            raise InvalidModelResponse("La réponse IA a supprimé une exclusion.")
        if language == "nl" and not re.search(
            r"\b(?:niet\b.{0,30}\binbegrepen|uitgesloten|exclusief)",
            target,
            re.I | re.S,
        ):
            raise InvalidModelResponse("La réponse IA a supprimé une exclusion.")
