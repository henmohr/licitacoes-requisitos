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
from dataclasses import asdict, dataclass
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


def extract_requirements_from_pdf(pdf_path: Path) -> list[Requirement]:
    pages = extract_pdf_pages(pdf_path)
    requirements: list[Requirement] = []
    seen: set[str] = set()
    section = ""

    for page_number, page_text in enumerate(pages, start=1):
        candidates: list[str] = []

        for raw_line in page_text.splitlines():
            line = cleanup_sentence(raw_line)
            if not line:
                continue
            if is_heading(line):
                section = line
                continue
            if matches_keyword(line) and len(line) >= 25 and candidate_score(line, section) >= 3:
                candidates.append(line)

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


def build_report(pdf_paths: list[Path]) -> dict:
    documents: list[dict] = []
    all_requirements: list[Requirement] = []

    for pdf_path in pdf_paths:
        requirements = extract_requirements_from_pdf(pdf_path)
        kind_counts = Counter(requirement.kind for requirement in requirements)
        documents.append(
            {
                "file": pdf_path.name,
                "relative_path": str(pdf_path),
                "requirement_count": len(requirements),
                "kind_counts": dict(kind_counts),
                "top_kinds": kind_counts.most_common(5),
            }
        )
        all_requirements.extend(requirements)

    requirements_dicts = [asdict(req) for req in all_requirements]
    comparison = build_comparison(documents, requirements_dicts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "requirement_count": len(requirements_dicts),
        "documents": documents,
        "requirements": requirements_dicts,
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

    print(f"Processed {report['document_count']} document(s), extracted {report['requirement_count']} requirement(s).")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
