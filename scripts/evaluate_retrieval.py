#!/usr/bin/env python
"""Deterministic retrieval evaluation (no LLM generation).

Computes Recall@k, Precision@k and MRR using the extended evaluation set
against the demo document. Can run in two modes:
- Unit/offline: only validates the evaluation file structure (no services).
- Integration: indexes the demo PDF with real Ollama+Postgres and measures retrieval.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "demo" / "evaluation_extended.json"
DEMO_PDF = ROOT / "demo" / "document.pdf"


def load_eval() -> dict:
    with EVAL_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def validate_eval(data: dict) -> list[str]:
    errors = []
    if not data.get("cases"):
        errors.append("no cases found")
    ids = [c["id"] for c in data.get("cases", [])]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case ids")
    for case in data.get("cases", []):
        if "id" not in case or "question" not in case:
            errors.append(f"case missing required fields: {case}")
            continue
        if case.get("should_abstain") and case.get("relevant_pages"):
            errors.append(f"{case['id']}: should_abstain but has relevant_pages")
        if not case.get("should_abstain") and not case.get("relevant_pages"):
            errors.append(f"{case['id']}: should have relevant_pages")
    return errors


def compute_metrics(results: list[dict], k_values: list[int] = None) -> dict:
    if k_values is None:
        k_values = [1, 3, 5]
    relevant_cases = [r for r in results if r.get("relevant_pages")]
    if not relevant_cases:
        return {"note": "no relevant cases with ground truth"}

    metrics = {}
    for k in k_values:
        hits = 0
        total_retrieved = 0
        total_relevant_found = 0
        for case in relevant_cases:
            retrieved_pages = case.get("retrieved_pages", [])[:k]
            rel_set = set(case["relevant_pages"])
            if rel_set.intersection(retrieved_pages):
                hits += 1
            total_retrieved += len(retrieved_pages)
            total_relevant_found += len(rel_set.intersection(retrieved_pages))
        recall = hits / len(relevant_cases) if relevant_cases else 0
        precision = total_relevant_found / total_retrieved if total_retrieved else 0
        metrics[f"Recall@{k}"] = round(recall, 4)
        metrics[f"Precision@{k}"] = round(precision, 4)

    reciprocal_ranks = []
    for case in relevant_cases:
        rel_set = set(case["relevant_pages"])
        pages = case.get("retrieved_pages", [])
        rank = None
        for i, p in enumerate(pages):
            if p in rel_set:
                rank = i + 1
                break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    metrics["MRR"] = round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
    metrics["num_relevant_cases"] = len(relevant_cases)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--k", nargs="+", type=int, default=[1, 3, 5])
    args = parser.parse_args()

    data = load_eval()
    errors = validate_eval(data)
    print(f"Evaluation file: {EVAL_FILE}")
    print(f"Cases: {len(data.get('cases', []))}")
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Validation: OK")

    if args.validate_only:
        return 0

    if os.environ.get("RUN_DB_TESTS") != "1" or os.environ.get("RUN_OLLAMA_TESTS") != "1":
        print("Skipping live retrieval evaluation (set RUN_DB_TESTS=1 RUN_OLLAMA_TESTS=1)")
        print("Use --validate-only for structural checks.")
        return 0

    from app.config.settings import settings
    from app.db import repositories
    from app.db.connection import connect
    from app.services.embeddings import EmbeddingService
    from app.services.indexing import IndexingConfig, index_pdf
    from app.services.ollama import OllamaClient
    from app.services.retrieval import RetrievalConfig, RetrievalService

    client = OllamaClient(
        base_url=settings.ollama_base_url,
        llm_model=settings.ollama_llm_model,
        embedding_model=settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    if not client.is_available():
        print("Ollama not available")
        return 1
    client.ensure_model(settings.ollama_embedding_model)
    embeddings = EmbeddingService(
        client,
        model=settings.ollama_embedding_model,
        version=settings.embedding_version,
        expected_dimension=settings.embedding_dimension,
    )

    try:
        conn = connect()
    except Exception as exc:
        print(f"DB not available: {exc}")
        return 1

    config = IndexingConfig(
        max_size_bytes=settings.max_upload_size_bytes,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        embedding_batch_size=settings.embedding_batch_size,
    )
    data_pdf = DEMO_PDF.read_bytes()
    result = index_pdf(conn, data_pdf, DEMO_PDF.name, embeddings=embeddings, config=config)
    retrieval = RetrievalService(
        conn,
        embeddings,
        config=RetrievalConfig(top_k=max(args.k), min_score=settings.retrieval_min_score),
    )

    results = []
    for case in data["cases"]:
        if case.get("relevant_pages"):
            found = retrieval.retrieve(case["question"], document_ids=[result.document_id])
            pages = [c.page_number for c in found.chunks]
            results.append({**case, "retrieved_pages": pages, "has_evidence": found.has_evidence})
        else:
            found = retrieval.retrieve(case["question"], document_ids=[result.document_id])
            results.append({**case, "retrieved_pages": [], "has_evidence": found.has_evidence})

    metrics = compute_metrics(results, args.k)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "timestamp": ts,
        "models": {
            "llm": settings.ollama_llm_model,
            "embedding": settings.ollama_embedding_model,
            "embedding_dimension": settings.embedding_dimension,
        },
        "params": {
            "chunk_size_chars": settings.chunk_size_chars,
            "chunk_overlap_chars": settings.chunk_overlap_chars,
            "retrieval_top_k": settings.retrieval_top_k,
            "retrieval_min_score": settings.retrieval_min_score,
        },
        "metrics": metrics,
        "results": results,
    }
    json_path = out / f"retrieval_eval_{ts}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {json_path}")

    md_path = out / f"retrieval_eval_{ts}.md"
    lines = ["# Retrieval Evaluation Report", "", f"Date: {ts}", "", "## Models & Params", ""]
    for k, v in report["models"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    for k, v in metrics.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Results by case")
    lines.append("")
    lines.append("| ID | Category | Relevant | Retrieved | Hit |")
    lines.append("|---|----------|----------|-----------|-----|")
    for r in results:
        rel = r.get("relevant_pages", [])
        ret = r.get("retrieved_pages", [])[:5]
        hit = "yes" if set(rel).intersection(ret) else ("n/a" if not rel else "no")
        lines.append(f"| {r['id']} | {r['category']} | {rel} | {ret} | {hit} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {md_path}")

    conn.rollback()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
