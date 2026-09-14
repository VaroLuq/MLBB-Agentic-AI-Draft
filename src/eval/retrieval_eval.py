"""
Metrics, against src/eval/retrieval_golden_set.py:
- Hit@k: did the expected note appear anywhere in the top-k results?
- Mean Reciprocal Rank (MRR): if it hit, how high up was it (1/rank),
  0 if it missed. Distinguishes "retrieved but buried at position 4"
  from "retrieved first" — both count as a hit, but rank matters for
  a k=4 window feeding a small model's limited context.

"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.rag.vectorstore import get_vectorstore
from src.eval.retrieval_golden_set import GOLDEN_SET

RESULTS_DIR = Path("data/eval_results")
LOG_PATH = RESULTS_DIR / "eval_log.txt"

TOP_K = 4  # matches retrieve_notes()'s search_kwargs in draft_agent.py


def _matches(doc, expected_hero: str, expected_keyword) -> bool:
    hero_match = doc.metadata.get("hero_name", "").lower() == expected_hero.lower()

    # Normalize whitespace before substring matching: source .md notes
    # are hand-wrapped at ~78 chars, so a keyword phrase can legitimately
    # span a literal newline in the raw text (e.g. "burst-heavy\ndive")
    # even though it reads as one phrase to a human. A naive substring
    # check would report a false MISS here — found the hard way, this
    # eval's own first run flagged a real retrieval hit as a miss.
    normalized_content = " ".join(doc.page_content.split()).lower()
    keywords = expected_keyword if isinstance(expected_keyword, list) else [expected_keyword]
    content_match = any(" ".join(kw.split()).lower() in normalized_content for kw in keywords)

    return hero_match and content_match


def run_retrieval_eval() -> list[dict]:
    retriever = get_vectorstore().as_retriever(search_kwargs={"k": TOP_K})
    results = []

    for entry in GOLDEN_SET:
        docs = retriever.invoke(entry["query"])
        rank = None
        for i, doc in enumerate(docs, start=1):
            if _matches(doc, entry["expected_hero"], entry["expected_keyword"]):
                rank = i
                break

        results.append({
            "name": entry["name"],
            "query": entry["query"],
            "expected_hero": entry["expected_hero"],
            "hit": rank is not None,
            "rank": rank,
            "retrieved_heroes": [d.metadata.get("hero_name") for d in docs],
        })

    return results


def summarize(results: list[dict]) -> dict:
    n = len(results)
    hits = sum(1 for r in results if r["hit"])
    mrr = sum((1 / r["rank"]) if r["hit"] else 0 for r in results) / n if n else 0

    return {
        "total_queries": n,
        "hits": hits,
        "hit_rate": round(hits / n, 3) if n else None,
        "mrr": round(mrr, 3),
        "misses": [r["name"] for r in results if not r["hit"]],
    }


def format_report(summary: dict, results: list[dict]) -> str:
    lines = [
        f"Retrieval hit@{TOP_K}: {summary['hits']}/{summary['total_queries']} "
        f"({summary['hit_rate']:.1%})",
        f"Mean Reciprocal Rank: {summary['mrr']}",
    ]
    if summary["misses"]:
        lines.append(f"Missed queries: {', '.join(summary['misses'])}")
    lines.append("")
    lines.append("Per-query detail:")
    for r in results:
        status = f"HIT (rank {r['rank']})" if r["hit"] else "MISS"
        lines.append(
            f"  [{status}] {r['name']} (expected: {r['expected_hero']}) "
            f"-> retrieved: {r['retrieved_heroes']}"
        )
    return "\n".join(lines)


def main():
    print(f"Running retrieval eval: {len(GOLDEN_SET)} golden queries against top-{TOP_K}.\n")
    results = run_retrieval_eval()
    summary = summarize(results)
    report = format_report(summary, results)

    print(report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result_path = RESULTS_DIR / f"retrieval_{timestamp}.json"
    result_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")
    print(f"\nFull results saved to: {result_path}")

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.now(timezone.utc).isoformat()} (retrieval) ---\n{report}\n")


if __name__ == "__main__":
    main()
