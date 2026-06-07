#!/usr/bin/env python3
"""Extract requirement-like statements from edital PDFs.

This MVP supports:
- text extraction via pdftotext
- OCR fallback for scanned pages
- heuristic requirement classification
- JSON and CSV output
- cross-document comparison data for the static site
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


KEYWORD_PATTERNS: list[tuple[str, str]] = [
    (r"\bdever[áo]?\b", "dever"),
    (r"\bobrigat[óo]ri[oa]s?\b", "obrigatorio"),
    (r"\bm[ií]nimo de\b", "minimo"),
    (r"\bn[aã]o ser[aá] aceito\b", "nao_aceito"),
    (r"\bvedad[ao]\b", "vedado"),
    (r"\bprazo\b", "prazo"),
    (r"\bdias?\s+úteis?\b", "prazo"),
    (r"\bdias?\b", "prazo"),
    (r"\bhabilita", "habilitacao"),
    (r"\bcertid[aã]o", "habilitacao"),
    (r"\bdocument", "documentacao"),
    (r"\batestado", "atestados"),
    (r"\bdeclara", "declaracao"),
    (r"\bsicaf\b", "sicaf"),
    (r"\bprova de conceito\b", "prova_conceito"),
    (r"\bm[oó]dulo\b", "modulo"),
    (r"\bsistema\b", "sistema"),
    (r"\bsoftware\b", "software"),
    (r"\bseguran", "seguranca"),
    (r"\bimplant", "implantacao"),
    (r"\btrein", "treinamento"),
    (r"\bhosped", "hospedagem"),
    (r"\bnuvem\b", "nuvem"),
    (r"\blicita", "licitacao"),
]


HEADING_PATTERNS = [
    re.compile(r"^(CAP[IÍ]TULO|ANEXO)\b", re.IGNORECASE),
    re.compile(r"^\d+(?:\.\d+)*\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ].{4,}$"),
    re.compile(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 ,;:\-–/()\.]{10,}$"),
]

SECTION_NUMBER_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\b")
SECTION_TITLE_CANDIDATE_RE = re.compile(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 ,;:\-–/()\.]{4,}$")


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")

NOISE_TRAIL_PATTERNS = [
    re.compile(r"\s+Tratamento Diferenciado:.*$", re.IGNORECASE),
    re.compile(r"\s+Aplicabilidade Decreto.*$", re.IGNORECASE),
    re.compile(r"\s+Quantidade Total:.*$", re.IGNORECASE),
    re.compile(r"\s+Crit[ée]rio de Julgamento:.*$", re.IGNORECASE),
    re.compile(r"\s+Valor Total \(R\$\):.*$", re.IGNORECASE),
    re.compile(r"\s+Unidade de Fornecimento:.*$", re.IGNORECASE),
    re.compile(r"\s+Crit[ée]rio de Valor:.*$", re.IGNORECASE),
    re.compile(r"\s+Intervalo M[ií]nimo entre Lances.*$", re.IGNORECASE),
    re.compile(r"\s+Local de Entrega.*$", re.IGNORECASE),
]

NOISE_EXACT = {
    "Tratamento Diferenciado:",
    "Aplicabilidade Decreto 7174/2010:",
    "Quantidade Total:",
    "Critério de Julgamento:",
    "Valor Total (R$):",
    "Unidade de Fornecimento:",
    "Critério de Valor:",
    "Intervalo Mínimo entre Lances (R$):",
    "Local de Entrega (Quantidade):",
    "Descrição Detalhada:",
}

NOISE_SECTION_PATTERNS = [
    re.compile(r"rela[cç][aã]o de itens", re.IGNORECASE),
    re.compile(r"itens da licita[cç][aã]o", re.IGNORECASE),
    re.compile(r"relat[oó]rio de itens", re.IGNORECASE),
]

SECTION_HINTS: list[tuple[str, str, int]] = [
    (r"habilita", "habilitacao", 3),
    (r"document", "habilitacao", 2),
    (r"declara", "habilitacao", 2),
    (r"atestado", "habilitacao", 2),
    (r"sicaf", "habilitacao", 2),
    (r"prova de conceito", "tecnico", 3),
    (r"caracter[ií]sticas? t[eé]cnicas?", "tecnico", 3),
    (r"m[oó]dulo", "tecnico", 1),
    (r"seguran", "tecnico", 2),
    (r"praz", "prazo", 2),
    (r"contrat", "geral", 1),
]

LOT_HEADER_RE = re.compile(r"^LOTE\s+(?P<number>\d+)\s+-\s+(?P<title>.+)$", re.IGNORECASE)
LOT_TOTAL_RE = re.compile(r"^LOTE\s+(?P<number>\d+)\s+R\$\s*(?P<total>[\d\.\,]+)$", re.IGNORECASE)
LOT_ITEM_RE = re.compile(
    r"^\s*(?P<item>\d+)(?:\s+(?P<prefix>.*?))?\s+(?P<unit>Unid\.|Mês|Hora)\s+(?P<qty>\d+)\s+R\$\s*(?P<unit_price>[\d\.\,]+)(?:\s+R\$\s*(?P<total_price>[\d\.\,]+))?\s*$",
    re.IGNORECASE,
)
LOT_PRICE_RE = re.compile(r"R\$\s*[\d\.\,]+")
MUNICIPALITY_RE = re.compile(
    r"\b(?:O\s+)?(?:MUNIC[ÍI]PIO|PREFEITURA\s+MUNICIPAL|C[ÂA]MARA\s+MUNICIPAL)\s+DE\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9 \-']{2,}?)"
    r"(?:,|\s+Estado\s+do|\s+Estado\s+da|\s+Estado\s+de|\s+PR\b|\s+Paran[aá]\b|\s+SC\b|\s+RS\b|\s+SP\b|\s+MG\b|$)",
    re.IGNORECASE,
)
STATE_HEADER_RE = re.compile(r"^(?:ESTADO\s+DO|ESTADO\s+DA|ESTADO\s+DE)\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ \-']+)$", re.IGNORECASE)
MUNICIPALITY_HEADER_RE = re.compile(
    r"^(?:PREFEITURA\s+MUNICIPAL\s+DE|MUNIC[IÍ]PIO\s+DE|C[ÂA]MARA\s+MUNICIPAL\s+DE)\s+"
    r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ \-']+)$",
    re.IGNORECASE,
)
STATE_HINT_RE = re.compile(r"Estado\s+do\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-Za-zÁÀÂÃÉÊÍÓÔÕÚÇç \-]+)", re.IGNORECASE)
STATE_ABBR_RE = re.compile(r"\b(PR|SC|RS|SP|MG|RJ|ES|BA|GO|MT|MS|DF|CE|RN|PB|PE|AL|SE|MA|PI|PA|AP|AM|RR|AC|RO|TO)\b", re.IGNORECASE)
SOFTWARE_PREFIX_RE = re.compile(
    r"^(?:Implanta[cç][aã]o, Convers[aã]o e Treinamento do M[oó]dulo|Licen[cç]a e Loca[cç][aã]o do M[oó]dulo)\s+",
    re.IGNORECASE,
)
CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
SUPPLIER_BLOCK_RE = re.compile(
    r"de outro,\s+a empresa\s+(?P<name>.+?),\s+pessoa jurídica de\s+direito privado.*?"
    r"inscrita.*?CNPJ.*?sob o n[º°]\s*(?P<cnpj>[A-Z0-9\.\-/]+)",
    re.IGNORECASE | re.DOTALL,
)
SUPPLIER_NAME_RE = re.compile(r"de outro,\s+a empresa\s+(?P<name>.+?),\s+pessoa jurídica de", re.IGNORECASE | re.DOTALL)

STATE_NAME_TO_ABBR = {
    "Acre": "AC",
    "Alagoas": "AL",
    "Amapá": "AP",
    "Amazonas": "AM",
    "Bahia": "BA",
    "Ceará": "CE",
    "Distrito Federal": "DF",
    "Espírito Santo": "ES",
    "Goiás": "GO",
    "Maranhão": "MA",
    "Mato Grosso": "MT",
    "Mato Grosso do Sul": "MS",
    "Minas Gerais": "MG",
    "Pará": "PA",
    "Paraíba": "PB",
    "Paraná": "PR",
    "Pernambuco": "PE",
    "Piauí": "PI",
    "Rio de Janeiro": "RJ",
    "Rio Grande do Norte": "RN",
    "Rio Grande do Sul": "RS",
    "Rondônia": "RO",
    "Roraima": "RR",
    "Santa Catarina": "SC",
    "São Paulo": "SP",
    "Sergipe": "SE",
    "Tocantins": "TO",
}


@dataclass
class Requirement:
    id: str
    source_file: str
    page: int
    section: str
    kind: str
    keyword: str
    text: str
    normalized_key: str
    confidence: float


@dataclass
class SectionBlock:
    source_file: str
    page: int
    title: str
    content: str
    is_table_like: bool
    line_count: int
    row_count: int


@dataclass
class LotItem:
    item: str
    description: str
    unit: str
    qty: str
    unit_price: str
    total_price: str


@dataclass
class LotBlock:
    source_file: str
    page: int
    number: str
    title: str
    total_value: str
    items: list[LotItem]


@dataclass
class MunicipalityRecord:
    source_file: str
    municipality: str
    state: str
    cod_municipio: str = ""
    uf: str = ""
    population: str = ""
    population_range: str = ""
    region: str = ""
    atendimento_website: str = ""
    atendimento_whatsapp: str = ""
    atendimento_telefone: str = ""
    nao_disponibiliza_atendimento_distancia: str = ""
    software_internal: str = ""
    software_sociedade: str = ""
    nao_desenvolveu_software: str = ""
    supplier_name: str = ""
    supplier_cnpj: str = ""
    software_modules: list[str] = field(default_factory=list)
    lot_count: int = 0
    item_count: int = 0
    total_value: str = ""
    source_files: list[str] = field(default_factory=list)


def command_exists(name: str) -> bool:
    return subprocess.run(
        ["bash", "-lc", f"command -v {name!s} >/dev/null 2>&1"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=True)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_for_key(text: str) -> str:
    text = remove_accents(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return normalize_spaces(text)


def cleanup_sentence(text: str) -> str:
    cleaned = normalize_spaces(text)
    if cleaned in NOISE_EXACT:
        return ""
    for pattern in NOISE_TRAIL_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()
    return cleaned


def pdf_page_count(pdf_path: Path) -> int:
    if not command_exists("pdfinfo"):
        return 0
    result = run_command(["pdfinfo", str(pdf_path)])
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def pdftotext_page(pdf_path: Path, page: int) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        run_command(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path), str(tmp_path)])
        return tmp_path.read_text(encoding="utf-8", errors="ignore")
    finally:
        tmp_path.unlink(missing_ok=True)


def ocr_page(pdf_path: Path, page: int) -> str:
    if not (command_exists("pdftoppm") and command_exists("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / f"page-{page}"
        run_command(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                "-png",
                str(pdf_path),
                str(prefix),
            ]
        )
        image_path = prefix.with_suffix(".png")
        if not image_path.exists():
            return ""
        result = run_command(["tesseract", str(image_path), "stdout", "-l", "por"])
        return result.stdout


def extract_page_text(pdf_path: Path, page: int) -> str:
    text = pdftotext_page(pdf_path, page)
    if len(normalize_spaces(text)) >= 80:
        return text
    ocr_text = ocr_page(pdf_path, page)
    return ocr_text if len(normalize_spaces(ocr_text)) > len(normalize_spaces(text)) else text


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    page_count = pdf_page_count(pdf_path)
    if page_count > 0:
        return [extract_page_text(pdf_path, page) for page in range(1, page_count + 1)]

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        run_command(["pdftotext", "-layout", str(pdf_path), str(tmp_path)])
        raw = tmp_path.read_text(encoding="utf-8", errors="ignore")
        return [page.strip() for page in raw.split("\f") if page.strip()]
    finally:
        tmp_path.unlink(missing_ok=True)


def split_blocks(page_text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n+", page_text)
    cleaned = []
    for block in blocks:
        block = normalize_spaces(block.replace("\n", " "))
        if block:
            cleaned.append(block)
    return cleaned


def is_heading(block: str) -> bool:
    return any(pattern.match(block) for pattern in HEADING_PATTERNS)


def matches_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern, _ in KEYWORD_PATTERNS)


def is_table_row(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "\t" in stripped:
        return True
    if re.search(r"\s{2,}", stripped):
        return True
    return bool(re.match(r"^\d+\s+\S+", stripped))


def looks_like_heading_continuation(text: str) -> bool:
    stripped = normalize_spaces(text)
    if not stripped or len(stripped) > 140:
        return False
    if stripped.endswith(".") and not stripped.endswith(":"):
        return False
    letters = [char for char in stripped if char.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(char.isupper() for char in letters) / len(letters)
    return upper_ratio >= 0.6


def detect_heading(lines: list[str], index: int) -> tuple[str, int]:
    first = normalize_spaces(lines[index].replace("\t", " "))
    if not first:
        return "", 0

    if not SECTION_NUMBER_PREFIX_RE.match(first):
        if any(pattern.match(first) for pattern in HEADING_PATTERNS):
            return first, 1
        return "", 0

    combined = first
    consumed = 1

    for offset in (1, 2):
        if index + offset >= len(lines):
            break
        next_line = normalize_spaces(lines[index + offset].replace("\t", " "))
        if not next_line or not looks_like_heading_continuation(next_line):
            break
        combined = f"{combined} {next_line}"
        consumed += 1
        if combined.endswith(":") or any(pattern.match(combined) for pattern in HEADING_PATTERNS):
            return combined, consumed

    if SECTION_TITLE_CANDIDATE_RE.match(combined) and len(combined) >= 15:
        return combined, consumed

    if any(pattern.match(first) for pattern in HEADING_PATTERNS):
        return first, 1

    return "", 0


def candidate_score(text: str, section: str) -> int:
    text_lower = text.lower()
    section_lower = section.lower()
    score = 0

    for pattern, keyword in KEYWORD_PATTERNS:
        if re.search(pattern, text_lower):
            if keyword in {"dever", "obrigatorio", "nao_aceito", "vedado"}:
                score += 3
            elif keyword in {"prazo", "minimo", "habilitacao", "documentacao", "atestados", "declaracao", "sicaf", "prova_conceito"}:
                score += 2
            else:
                score += 1

    for pattern, kind, boost in SECTION_HINTS:
        if re.search(pattern, section_lower):
            score += 1 if boost <= 1 else 2

    if "dever" in text_lower or "obrigat" in text_lower or "vedad" in text_lower:
        score += 2
    if "prazo" in text_lower or "dias úteis" in text_lower or "dias uteis" in text_lower or "vigência" in text_lower:
        score += 1
    if "descrição detalhada:" in text_lower:
        score -= 2
    if any(pattern.search(section_lower) for pattern in NOISE_SECTION_PATTERNS):
        score -= 2
    if re.match(r"^\d+\s*-\s*servi[cç]os de hospedagem de sistemas\b", text_lower):
        score -= 2
    if re.match(r"^\d+\s*-\s*servi[cç]os de hospedagem\b", text_lower):
        score -= 1
    if re.match(r"^\d+\s+-\s+$", text_lower):
        score -= 2

    return score


def classify(text: str, section: str) -> tuple[str, str, float]:
    text_lower = text.lower()
    section_lower = section.lower()
    kind_scores: dict[str, int] = {
        "habilitacao": 0,
        "prazo": 0,
        "tecnico": 0,
        "documentacao": 0,
        "restricao": 0,
        "funcional": 0,
        "geral": 0,
    }
    keyword_hit = "outro"

    for pattern, keyword in KEYWORD_PATTERNS:
        if re.search(pattern, text_lower):
            keyword_hit = keyword
            if keyword in {"habilitacao", "documentacao", "atestados", "declaracao", "sicaf"}:
                kind_scores["habilitacao"] += 3
                kind_scores["documentacao"] += 2
            elif keyword in {"prazo", "minimo"}:
                kind_scores["prazo"] += 3
            elif keyword in {"nao_aceito", "vedado"}:
                kind_scores["restricao"] += 3
            elif keyword in {"prova_conceito", "seguranca", "software", "sistema", "modulo", "implantacao", "treinamento", "hospedagem", "nuvem"}:
                kind_scores["tecnico"] += 3
                kind_scores["funcional"] += 1
            elif keyword == "licitacao":
                kind_scores["geral"] += 1

    for pattern, kind, boost in SECTION_HINTS:
        if re.search(pattern, section_lower):
            kind_scores[kind] += boost

    if re.search(r"\bdever[áo]?\b", text_lower):
        kind_scores["tecnico"] += 1
        kind_scores["funcional"] += 1
    if re.search(r"\b(?:não será aceito|nao sera aceito|vedado|proibido|impedid)\b", text_lower):
        kind_scores["restricao"] += 2
    if re.search(r"\b(?:prazos?|dias? úteis?|vig[êe]ncia|até \d+)\b", text_lower):
        kind_scores["prazo"] += 2
    if re.search(r"\b(?:habilita|document|certid|sicaf|declara|atestado)\b", text_lower):
        kind_scores["habilitacao"] += 1
    if re.search(r"\b(?:funcionalidade|m[oó]dulo|sistema|software|implant|trein|hospedagem|nuvem|web|seguran)\b", text_lower):
        kind_scores["tecnico"] += 1
        kind_scores["funcional"] += 1

    kind = max(kind_scores, key=kind_scores.get)
    score = 0.52
    score += min(0.34, 0.04 * sum(v > 0 for v in kind_scores.values()))
    if kind != "geral":
        score += 0.08
    return kind, keyword_hit, round(min(score, 0.97), 2)


def iter_pdfs(input_dir: Path) -> Iterable[Path]:
    for path in sorted(input_dir.rglob("*.pdf")):
        if path.is_file():
            yield path


def extract_sections_from_pages(pdf_path: Path, pages: list[str]) -> list[SectionBlock]:
    sections: list[SectionBlock] = []
    current: dict | None = None

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        content_lines = current["content_lines"]
        content = "\n".join(content_lines).strip()
        row_count = sum(1 for line in content_lines if is_table_row(line))
        sections.append(
            SectionBlock(
                source_file=pdf_path.name,
                page=current["page"],
                title=current["title"],
                content=content,
                is_table_like=row_count >= 2 or any(is_table_row(line) for line in content_lines[:6]),
                line_count=len([line for line in content_lines if line.strip()]),
                row_count=row_count,
            )
        )
        current = None

    for page_number, page_text in enumerate(pages, start=1):
        lines = page_text.splitlines()
        index = 0

        while index < len(lines):
            raw_line = normalize_spaces(lines[index].replace("\t", " "))
            if not raw_line:
                if current and current["content_lines"] and current["content_lines"][-1] != "":
                    current["content_lines"].append("")
                index += 1
                continue

            if current is not None and is_table_row(raw_line):
                current["content_lines"].append(raw_line)
                index += 1
                continue

            heading, consumed = detect_heading(lines, index)
            if heading:
                flush_current()
                current = {
                    "page": page_number,
                    "title": heading,
                    "content_lines": [],
                }
                index += consumed
                continue

            if current is not None:
                if raw_line not in NOISE_EXACT and not any(pattern.search(raw_line) for pattern in NOISE_TRAIL_PATTERNS):
                    current["content_lines"].append(raw_line)

            index += 1

    flush_current()
    return sections


def extract_requirements_from_pages(pdf_path: Path, pages: list[str]) -> list[Requirement]:
    requirements: list[Requirement] = []
    seen: set[str] = set()
    section = ""

    for page_number, page_text in enumerate(pages, start=1):
        candidates: list[str] = []
        lines = page_text.splitlines()

        line_index = 0
        while line_index < len(lines):
            raw_line = lines[line_index]
            line = cleanup_sentence(raw_line)
            if not line:
                line_index += 1
                continue
            heading, consumed = detect_heading(lines, line_index)
            if heading:
                section = heading
                line_index += consumed
                continue
            if matches_keyword(line) and len(line) >= 25 and candidate_score(line, section) >= 3:
                candidates.append(line)
            line_index += 1

        for block in split_blocks(page_text):
            if is_heading(block):
                section = block
                continue
            if not matches_keyword(block):
                continue
            for sentence in SENTENCE_SPLIT_RE.split(block):
                sentence = cleanup_sentence(sentence)
                if len(sentence) >= 25 and matches_keyword(sentence) and candidate_score(sentence, section) >= 3:
                    candidates.append(sentence)

        for sentence in candidates:
            normalized_key = normalize_for_key(sentence)
            dedupe_key = f"{pdf_path.name}|{page_number}|{normalized_key}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            kind, keyword, confidence = classify(sentence, section)
            requirements.append(
                Requirement(
                    id=f"{pdf_path.stem}-{len(requirements) + 1:04d}",
                    source_file=pdf_path.name,
                    page=page_number,
                    section=section or "Sem seção identificada",
                    kind=kind,
                    keyword=keyword,
                    text=sentence,
                    normalized_key=normalized_key,
                    confidence=confidence,
                )
            )

    return requirements


def extract_requirements_from_pdf(pdf_path: Path) -> list[Requirement]:
    pages = extract_pdf_pages(pdf_path)
    return extract_requirements_from_pages(pdf_path, pages)


def strip_price_tokens(text: str) -> str:
    if not text:
        return ""
    return LOT_PRICE_RE.sub("", text).replace("R$", "").strip()


def normalize_display_name(text: str) -> str:
    cleaned = normalize_spaces(text)
    if not cleaned:
        return ""
    result = cleaned.title()
    for word in (" De ", " Da ", " Do ", " Das ", " Dos "):
        result = result.replace(word, word.lower())
    return result


def state_abbr_from_name(state: str) -> str:
    normalized = normalize_display_name(state)
    return STATE_NAME_TO_ABBR.get(normalized, state.upper() if len(state) == 2 else "")


def extract_cnpjs_from_pages(pages: list[str]) -> list[str]:
    haystack = "\n".join(pages)
    return sorted(set(CNPJ_RE.findall(haystack)))


def normalize_supplier_name(text: str) -> str:
    cleaned = normalize_spaces(text)
    cleaned = cleaned.strip(" ,.;")
    cleaned = re.sub(r"^\((.+)\)$", r"\1", cleaned)
    if cleaned.upper() in {"RAZÃO SOCIAL DA EMPRESA", "RAZAO SOCIAL DA EMPRESA", "EMPRESA", "FORNECEDOR"}:
        return ""
    return cleaned


def extract_supplier_info(pages: list[str]) -> tuple[str, str]:
    haystack = "\n".join(pages[-8:])
    block_match = SUPPLIER_BLOCK_RE.search(haystack)
    if block_match:
        name = normalize_supplier_name(block_match.group("name"))
        cnpj = normalize_spaces(block_match.group("cnpj"))
        if not re.search(r"\d", cnpj):
            cnpj = ""
        if "X" in cnpj.upper():
            cnpj = ""
        return name, cnpj
    name_match = SUPPLIER_NAME_RE.search(haystack)
    supplier_name = normalize_supplier_name(name_match.group("name")) if name_match else ""
    return supplier_name, ""


def normalize_csv_value(value: str) -> str:
    if value is None:
        return ""
    value = value.strip()
    return "" if value in {"-", "—"} else value


def load_municipality_reference(csv_path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not csv_path.exists():
        return {}

    reference: dict[tuple[str, str], dict[str, str]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            municipality = normalize_display_name(row.get("municipio", ""))
            uf = normalize_display_name(row.get("UF", "")).upper()
            key = (normalize_for_key(municipality), uf)
            reference[key] = {
                "cod_municipio": normalize_csv_value(row.get("cod_municipio", "")),
                "uf": uf,
                "population": normalize_csv_value(row.get("populacao", "")),
                "population_range": normalize_csv_value(row.get("faixa_populacao", "")),
                "region": normalize_csv_value(row.get("regiao", "")),
                "atendimento_website": normalize_csv_value(row.get("atendimento_website", "")),
                "atendimento_whatsapp": normalize_csv_value(row.get("atendimento_whatsapp", "")),
                "atendimento_telefone": normalize_csv_value(row.get("atendimento_telefone", "")),
                "nao_disponibiliza_atendimento_distancia": normalize_csv_value(row.get("nao_disponibiliza_atendimento_distancia", "")),
                "software_internal": normalize_csv_value(row.get("software_interno", "")),
                "software_sociedade": normalize_csv_value(row.get("software_sociedade", "")),
                "nao_desenvolveu_software": normalize_csv_value(row.get("nao_desenvolveu_software", "")),
            }

    return reference


def extract_municipality_and_state(pages: list[str], pdf_path: Path) -> tuple[str, str]:
    municipality = ""
    state = ""

    for page_text in pages[:4]:
        for raw_line in page_text.splitlines():
            line = normalize_spaces(raw_line.replace("\t", " "))
            if not line:
                continue

            if not state:
                state_match = STATE_HEADER_RE.match(line)
                if state_match:
                    state = normalize_display_name(state_match.group(1))
                    continue

            if not municipality:
                municipality_match = MUNICIPALITY_HEADER_RE.match(line)
                if municipality_match:
                    municipality = normalize_display_name(municipality_match.group(1))
                    continue

            if municipality and not state:
                state_hint = STATE_HINT_RE.search(line)
                if state_hint:
                    state = normalize_display_name(state_hint.group(1))
                    continue
                abbr_match = STATE_ABBR_RE.search(line)
                if abbr_match:
                    state = abbr_match.group(1).upper()
                    continue

    if not municipality:
        haystack = "\n".join(pages[:4])
        match = MUNICIPALITY_RE.search(haystack)
        if match:
            municipality = normalize_display_name(match.group(1))
            snippet = haystack[match.end() : match.end() + 80]
            state_match = STATE_HINT_RE.search(snippet)
            if state_match:
                state = normalize_display_name(state_match.group(1))
            else:
                abbr_match = STATE_ABBR_RE.search(snippet)
                if abbr_match:
                    state = abbr_match.group(1).upper()

    if not municipality:
        name_guess = pdf_path.stem
        municipality = normalize_display_name(name_guess.split(" - ")[0].split("–")[0].split("—")[0])

    return municipality, state


def extract_software_modules(lots: list[LotBlock]) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()

    def is_module_candidate(description: str) -> bool:
        if not description or len(description) > 100:
            return False
        if re.search(r"\d", description):
            return False
        if re.search(
            r"\b(?:infraestrutura|consultoria|horas?|usu[aá]rios simult[aâ]neos|atendimento presencial|remoto|"
            r"cloud|hospedagem|instala[cç][aã]o|implanta[cç][aã]o|migra[cç][aã]o|customiza[cç][aã]o|treinamento|"
            r"suporte|disponibilizado|conforme a necessidade)\b",
            description,
            re.IGNORECASE,
        ):
            return False
        if re.match(r"^(?:implantação|instalação|hospedagem|infraestrutura|horas|serviços|suporte|configurações|migração|customização|treinamentos?)\b", description, re.IGNORECASE):
            return False
        return True

    for lot in lots:
        for item in lot.items:
            description = SOFTWARE_PREFIX_RE.sub("", item.description).strip(" -–")
            description = normalize_spaces(description)
            description = re.sub(
                r"\s+(?:Implanta[cç][aã]o, Convers[aã]o e Treinamento do M[oó]dulo|Licen[cç]a e Loca[cç][aã]o do M[oó]dulo)$",
                "",
                description,
                flags=re.IGNORECASE,
            )
            description = re.sub(r"^(?:de|da|do|das|dos|e)\s+", "", description, flags=re.IGNORECASE)
            description = re.sub(r"^M[oó]dulo\s+", "", description, flags=re.IGNORECASE)
            if not description or not is_module_candidate(description):
                continue
            key = normalize_for_key(description)
            if key in seen:
                continue
            seen.add(key)
            modules.append(description)

    return modules


def extract_document_modules(sections: list[SectionBlock], lots: list[LotBlock]) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()

    def add_module(name: str) -> None:
        cleaned = normalize_spaces(name)
        if not cleaned:
            return
        key = normalize_for_key(cleaned)
        if key in seen:
            return
        seen.add(key)
        modules.append(cleaned)

    for section in sections:
        title = section.title
        if not re.search(r"\b(M[oó]dulo|PORTAL)\b", title, re.IGNORECASE):
            continue
        if re.search(r"\b(anexo|caracter[ií]sticas?\s+t[eé]cnicas?)\b", title, re.IGNORECASE):
            continue

        cleaned = re.sub(r"^\s*[A-Z]\s*-\s*", "", title)
        cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", cleaned)
        cleaned = re.sub(r"^M[oó]dulo\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = normalize_display_name(cleaned)
        if cleaned and len(cleaned) <= 80:
            add_module(cleaned)

    if modules:
        return modules

    for module in extract_software_modules(lots):
        add_module(module)

    return modules


def aggregate_municipalities(records: list[MunicipalityRecord]) -> list[MunicipalityRecord]:
    grouped: dict[tuple[str, str], MunicipalityRecord] = {}

    for record in records:
        key = (record.municipality.lower(), record.state.lower())
        if key not in grouped:
            grouped[key] = MunicipalityRecord(
                source_file=record.source_file,
                municipality=record.municipality,
                state=record.state,
                cod_municipio=record.cod_municipio,
                uf=record.uf,
                population=record.population,
                population_range=record.population_range,
                region=record.region,
                atendimento_website=record.atendimento_website,
                atendimento_whatsapp=record.atendimento_whatsapp,
                atendimento_telefone=record.atendimento_telefone,
                nao_disponibiliza_atendimento_distancia=record.nao_disponibiliza_atendimento_distancia,
                software_internal=record.software_internal,
                software_sociedade=record.software_sociedade,
                nao_desenvolveu_software=record.nao_desenvolveu_software,
                supplier_name=record.supplier_name,
                supplier_cnpj=record.supplier_cnpj,
                software_modules=list(record.software_modules),
                lot_count=record.lot_count,
                item_count=record.item_count,
                total_value=record.total_value,
                source_files=[record.source_file],
            )
            continue

        existing = grouped[key]
        existing.source_files.append(record.source_file)
        existing.lot_count += record.lot_count
        existing.item_count += record.item_count
        total_values = [value.strip() for value in existing.total_value.split(",") if value.strip()]
        if record.total_value and record.total_value not in total_values:
            total_values.append(record.total_value)
            existing.total_value = ", ".join(total_values)

        for module in record.software_modules:
            if module not in existing.software_modules:
                existing.software_modules.append(module)

    return list(grouped.values())


def extract_lots_from_pages(pdf_path: Path, pages: list[str]) -> list[LotBlock]:
    lines: list[tuple[int, int, str]] = []
    for page_number, page_text in enumerate(pages, start=1):
        for raw_line in page_text.splitlines():
            line = normalize_spaces(raw_line.replace("\t", " "))
            if line:
                lines.append((page_number, len(lines), line))

    lots: list[LotBlock] = []
    current_start = None
    current_header = None

    for index, (_, _, line) in enumerate(lines):
        header_match = LOT_HEADER_RE.match(line)
        if header_match:
            if current_start is not None and current_header is not None:
                lots.append(
                    build_lot_block(pdf_path.name, lines, current_start, index, current_header)
                )
            current_start = index
            current_header = header_match

    if current_start is not None and current_header is not None:
        lots.append(build_lot_block(pdf_path.name, lines, current_start, len(lines), current_header))

    return lots


def build_lot_block(
    source_file: str,
    lines: list[tuple[int, int, str]],
    start_index: int,
    end_index: int,
    header_match: re.Match[str],
) -> LotBlock:
    subset = lines[start_index:end_index]
    page = subset[0][0] if subset else 0
    number = header_match.group("number")
    title = f"LOTE {number} - {header_match.group('title').strip()}"
    total_value = ""
    item_rows: list[tuple[int, re.Match[str]]] = []

    for idx, (_, _, line) in enumerate(subset):
        total_match = LOT_TOTAL_RE.match(line)
        if total_match and total_match.group("number") == number:
            total_value = total_match.group("total")
            continue

        item_match = LOT_ITEM_RE.match(line)
        if item_match:
            item_rows.append((idx, item_match))

    items: list[LotItem] = []
    for item_pos, item_match in item_rows:
        prefix = strip_price_tokens(item_match.group("prefix"))
        inferred_total = item_match.group("total_price") or ""
        prev_text = ""
        next_text = ""

        for back_index in range(item_pos - 1, max(-1, item_pos - 3), -1):
            line = subset[back_index][2]
            if LOT_HEADER_RE.match(line) or LOT_TOTAL_RE.match(line) or LOT_ITEM_RE.match(line):
                break
            cleaned = strip_price_tokens(line)
            if cleaned and not re.match(r"^(Item\s+Descrição|Unid\.|Mês|Hora|\d+)$", cleaned, re.IGNORECASE):
                prev_text = cleaned
                break

        for forward_index in range(item_pos + 1, min(len(subset), item_pos + 3)):
            line = subset[forward_index][2]
            if LOT_HEADER_RE.match(line) or LOT_TOTAL_RE.match(line) or LOT_ITEM_RE.match(line):
                break
            cleaned = strip_price_tokens(line)
            if cleaned and not re.match(r"^(Item\s+Descrição|Unid\.|Mês|Hora|\d+)$", cleaned, re.IGNORECASE):
                if not inferred_total and re.match(r"^[\d\.\,]+$", cleaned):
                    inferred_total = cleaned
                    continue
                next_text = cleaned
                break

        description_parts: list[str] = []
        if prefix:
            if prev_text and re.match(r"^(de|da|do|das|dos|e|em|no|na)\b", prefix, re.IGNORECASE):
                description_parts.append(prev_text)
            description_parts.append(prefix)
            if next_text:
                description_parts.append(next_text)
        else:
            if prev_text:
                description_parts.append(prev_text)
            if next_text:
                description_parts.append(next_text)
        description = normalize_spaces(" ".join(description_parts))
        items.append(
            LotItem(
                item=item_match.group("item"),
                description=description,
                unit=item_match.group("unit"),
                qty=item_match.group("qty"),
                unit_price=item_match.group("unit_price"),
                total_price=inferred_total,
            )
        )

    return LotBlock(
        source_file=source_file,
        page=page,
        number=number,
        title=title,
        total_value=total_value,
        items=items,
    )


def build_comparison(documents: list[dict], requirements: list[dict]) -> dict:
    by_doc: dict[str, list[dict]] = defaultdict(list)
    groups: dict[str, list[dict]] = defaultdict(list)

    for requirement in requirements:
        by_doc[requirement["source_file"]].append(requirement)
        groups[requirement["normalized_key"]].append(requirement)

    kinds = sorted({requirement["kind"] for requirement in requirements})
    shared_groups = [group for group in groups.values() if len({item["source_file"] for item in group}) > 1]
    shared_keys = {group[0]["normalized_key"] for group in shared_groups}
    unique_keys = {key for key, group in groups.items() if len(group) == 1}

    doc_summaries = []
    unique_examples_by_doc: dict[str, list[dict]] = {}
    duplicate_groups = []
    repeated_within_doc_groups = []

    for document in documents:
        doc_reqs = by_doc.get(document["file"], [])
        kind_counts = Counter(req["kind"] for req in doc_reqs)
        section_counts = Counter(normalize_spaces(req["section"]) for req in doc_reqs)
        unique_examples = [req for req in doc_reqs if req["normalized_key"] in unique_keys]
        shared_examples = [req for req in doc_reqs if req["normalized_key"] in shared_keys]

        doc_summaries.append(
            {
                "file": document["file"],
                "requirement_count": len(doc_reqs),
                "unique_count": len(unique_examples),
                "shared_count": len(shared_examples),
                "kind_counts": dict(kind_counts),
                "section_counts": dict(section_counts),
                "top_sections": section_counts.most_common(4),
                "top_kinds": kind_counts.most_common(3),
            }
        )
        unique_examples_by_doc[document["file"]] = unique_examples[:8]

    shared_examples = []
    for group in shared_groups[:12]:
        docs = sorted({item["source_file"] for item in group})
        representative = group[0]
        pages = sorted({f"{item['source_file']} p.{item['page']}" for item in group})
        shared_examples.append(
            {
                "text": representative["text"],
                "docs": docs,
                "pages": pages,
                "kind": representative["kind"],
                "section": representative["section"],
            }
        )

    for key, group in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True):
        if len(group) < 2:
            continue
        docs = sorted({item["source_file"] for item in group})
        pages = sorted({f"{item['source_file']} p.{item['page']}" for item in group})
        representative = group[0]
        entry = {
            "text": representative["text"],
            "normalized_key": key,
            "docs": docs,
            "pages": pages,
            "occurrences": len(group),
            "kind": representative["kind"],
            "section": representative["section"],
        }
        if len(docs) > 1:
            duplicate_groups.append(entry)
        else:
            repeated_within_doc_groups.append(entry)

    return {
        "kinds": kinds,
        "document_summaries": doc_summaries,
        "shared_requirement_count": len(shared_keys),
        "unique_requirement_count": len(unique_keys),
        "shared_examples": shared_examples,
        "duplicate_groups": duplicate_groups[:20],
        "repeated_within_doc_groups": repeated_within_doc_groups[:20],
        "unique_examples_by_doc": unique_examples_by_doc,
    }


def write_csv(report: dict, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "source_file",
        "page",
        "section",
        "kind",
        "keyword",
        "confidence",
        "normalized_key",
        "text",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for requirement in report["requirements"]:
            writer.writerow({key: requirement.get(key, "") for key in fieldnames})


def write_municipality_catalog(catalog: list[dict], csv_path: Path, json_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "source_file",
        "municipality",
        "state",
        "cod_municipio",
        "uf",
        "population",
        "population_range",
        "region",
        "atendimento_website",
        "atendimento_whatsapp",
        "atendimento_telefone",
        "nao_disponibiliza_atendimento_distancia",
        "software_internal",
        "software_sociedade",
        "nao_desenvolveu_software",
        "supplier_name",
        "supplier_cnpj",
        "software_modules",
        "lot_count",
        "item_count",
        "total_value",
        "source_files",
    ]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for record in catalog:
            row = dict(record)
            row["software_modules"] = " | ".join(record.get("software_modules", []))
            row["source_files"] = " | ".join(record.get("source_files", []))
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_report(pdf_paths: list[Path]) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    municipality_reference = load_municipality_reference(repo_root / "data" / "raw" / "munic_informatica.csv")
    documents: list[dict] = []
    all_requirements: list[Requirement] = []
    all_sections: list[SectionBlock] = []
    all_lots: list[LotBlock] = []
    municipalities: list[MunicipalityRecord] = []

    for pdf_path in pdf_paths:
        pages = extract_pdf_pages(pdf_path)
        requirements = extract_requirements_from_pages(pdf_path, pages)
        sections = extract_sections_from_pages(pdf_path, pages)
        lots = extract_lots_from_pages(pdf_path, pages)
        municipality, state = extract_municipality_and_state(pages, pdf_path)
        document_modules = extract_document_modules(sections, lots)
        supplier_name, supplier_cnpj = extract_supplier_info(pages)
        state_abbr = state_abbr_from_name(state)
        reference = municipality_reference.get((normalize_for_key(municipality), state_abbr), {})
        if not reference:
            for (ref_municipality, _ref_state), ref_value in municipality_reference.items():
                if ref_municipality == normalize_for_key(municipality):
                    reference = ref_value
                    break
        kind_counts = Counter(requirement.kind for requirement in requirements)
        total_value = next((lot.total_value for lot in lots if lot.total_value), "")
        documents.append(
            {
                "file": pdf_path.name,
                "relative_path": str(pdf_path),
                "requirement_count": len(requirements),
                "kind_counts": dict(kind_counts),
                "municipality": municipality,
                "state": state,
                "supplier_name": supplier_name,
                "supplier_cnpj": supplier_cnpj,
                "lot_count": len(lots),
                "item_count": sum(len(lot.items) for lot in lots),
                "total_value": total_value,
                "software_modules": document_modules,
                "top_kinds": kind_counts.most_common(5),
            }
        )
        all_requirements.extend(requirements)
        all_sections.extend(sections)
        all_lots.extend(lots)
        municipalities.append(
            MunicipalityRecord(
                source_file=pdf_path.name,
                municipality=municipality,
                state=state,
                cod_municipio=reference.get("cod_municipio", ""),
                uf=reference.get("uf", state_abbr),
                population=reference.get("population", ""),
                population_range=reference.get("population_range", ""),
                region=reference.get("region", ""),
                atendimento_website=reference.get("atendimento_website", ""),
                atendimento_whatsapp=reference.get("atendimento_whatsapp", ""),
                atendimento_telefone=reference.get("atendimento_telefone", ""),
                nao_disponibiliza_atendimento_distancia=reference.get("nao_disponibiliza_atendimento_distancia", ""),
                software_internal=reference.get("software_internal", ""),
                software_sociedade=reference.get("software_sociedade", ""),
                nao_desenvolveu_software=reference.get("nao_desenvolveu_software", ""),
                supplier_name=supplier_name,
                supplier_cnpj=supplier_cnpj,
                software_modules=document_modules[:20],
                lot_count=len(lots),
                item_count=sum(len(lot.items) for lot in lots),
                total_value=total_value,
                source_files=[pdf_path.name],
            )
        )

    requirements_dicts = [asdict(req) for req in all_requirements]
    sections_dicts = [asdict(section) for section in all_sections]
    lots_dicts = [asdict(lot) for lot in all_lots]
    municipalities_dicts = [asdict(entry) for entry in aggregate_municipalities(municipalities)]
    comparison = build_comparison(documents, requirements_dicts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "requirement_count": len(requirements_dicts),
        "section_count": len(sections_dicts),
        "lot_count": len(lots_dicts),
        "municipality_count": len(municipalities_dicts),
        "documents": documents,
        "requirements": requirements_dicts,
        "sections": sections_dicts,
        "lots": lots_dicts,
        "municipalities": municipalities_dicts,
        "municipality_catalog": municipalities_dicts,
        "comparison": comparison,
    }


def ensure_minimal_site(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract requirement-like statements from edital PDFs.")
    parser.add_argument("--input-dir", type=Path, default=Path("inputs"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--json-name", default="data/requirements.json")
    parser.add_argument("--csv-name", default="data/requirements.csv")
    args = parser.parse_args()

    pdf_paths = list(iter_pdfs(args.input_dir))
    report = build_report(pdf_paths)
    ensure_minimal_site(args.output_dir)

    json_path = args.output_dir / args.json_name
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = args.output_dir / args.csv_name
    write_csv(report, csv_path)

    repo_root = Path(__file__).resolve().parents[1]
    processed_dir = repo_root / "data" / "processed"
    processed_json_path = processed_dir / "municipality_catalog.json"
    processed_csv_path = processed_dir / "municipality_catalog.csv"
    write_municipality_catalog(report["municipality_catalog"], processed_csv_path, processed_json_path)

    published_catalog_json = args.output_dir / "data" / "municipality_catalog.json"
    published_catalog_csv = args.output_dir / "data" / "municipality_catalog.csv"
    write_municipality_catalog(report["municipality_catalog"], published_catalog_csv, published_catalog_json)

    print(f"Processed {report['document_count']} document(s), extracted {report['requirement_count']} requirement(s).")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {processed_json_path}")
    print(f"Wrote {processed_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
