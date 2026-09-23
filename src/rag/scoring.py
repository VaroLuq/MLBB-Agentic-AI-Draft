"""Relevance scoring over retrieval results.

Deliberately separate from `vectorstore.py`: this is pure arithmetic over
scores that have already been fetched, so it touches neither Chroma nor the
embedding model and stays testable without loading either.
"""

import re

# Calibrated 2026-09-23 against the Harrier embedder
# (microsoft/harrier-oss-v1-0.6b, l2 space) AND the specific query format
# retrieve_notes builds ("Draft advice for: <lane>, <enemies>, <allies>").
# Measured: that query style scores in the 0.17-0.41 band, where a draft with
# no applicable note tops out at 0.287 and the weakest true positive is 0.409,
# so 0.30 sits inside a 0.122-wide gap between noise and signal.
#
# This number is NOT portable. It depends on the embedding model, the distance
# space, and the query wording together. A structured/instructional query
# ("Find strategy notes relevant to this draft query: - Lane needed: ...") was
# tested and rejected on 2026-09-23: its constant boilerplate lifted the noise
# floor from 0.287 to 0.404 while barely moving true positives, collapsing the
# usable gap to 0.020 and producing false positives on drafts with no relevant
# note. Re-calibrate if any of the three change.
RAG_RELEVANCE_THRESHOLD = 0.30


def mentions_hero(text: str, hero: str) -> bool:
    """Whole-word, case-insensitive check that `text` names `hero`.

    Same rule `src/web/evidence.py` uses to attribute a note to a pick. It
    matters that this is a mention and not just a metadata match: the
    Lapu-Lapu note's value is that it names Esmeralda as the counter, so it
    is evidence *for Esmeralda* whenever Lapu-Lapu is in the draft.
    """
    return re.search(rf"(?<!\w){re.escape(hero)}(?!\w)", text, re.IGNORECASE) is not None


def aggregate_rag_scores(
    raw_similarity_scores: list[float],
    threshold: float = RAG_RELEVANCE_THRESHOLD,
) -> float:
    """Combine several note relevance scores via Noisy-OR (probabilistic union).

    Reads as "probability that at least one retrieved note is real evidence
    for this hero". Chosen over summing because it is bounded in [0, 1] and
    saturates: a second mediocre note helps less than the first, and no amount
    of weak evidence can run away to a large number the way a sum can.

    Scores at or below `threshold` are dropped as embedding noise; survivors
    are rescaled so the threshold maps to 0.0. Note this makes `threshold` do
    double duty as filter and as the zero point, so changing it rescales
    every score non-linearly rather than only filtering.

    Returns 0.0 for an empty list, which is the common case: a hero named in
    no note at all has nothing to aggregate, and scores 0.0 at any threshold.
    """
    if not raw_similarity_scores:
        return 0.0

    valid_probabilities = []
    for score in raw_similarity_scores:
        # Relevance can come back negative for distances beyond sqrt(2), so
        # this filter also keeps those out of the product below.
        if score > threshold:
            valid_probabilities.append((score - threshold) / (1.0 - threshold))

    if not valid_probabilities:
        return 0.0

    probability_of_none = 1.0
    for p in valid_probabilities:
        probability_of_none *= (1.0 - p)

    return round(1.0 - probability_of_none, 3)
