"""Compare local bot models on the same labeled commands and confidence threshold."""

from argparse import ArgumentParser
from collections import Counter
from json import dumps, loads
from pathlib import Path

from bot_core.neural_nlu.model import LocalNLU
from bot_core.neural_nlu.train_nlu import _dataset


def evaluate(model: LocalNLU, examples: list[tuple[str, str]], threshold: float) -> dict:
    confusions = Counter()
    accepted = accepted_errors = 0
    for message, expected in examples:
        prediction = model.predict(message)
        wrong = prediction.intent != expected
        if wrong:
            confusions[f"{expected} -> {prediction.intent}"] += 1
        if prediction.confidence >= threshold:
            accepted += 1
            accepted_errors += wrong
    return {
        "examples": len(examples),
        "correct": len(examples) - confusions.total(),
        "accepted": accepted,
        "accepted_errors": accepted_errors,
        "confusions": dict(confusions.most_common()),
    }


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("models", type=Path, nargs="+")
    parser.add_argument("--challenge", type=Path)
    parser.add_argument("--threshold", type=float, default=0.75)
    opts = parser.parse_args()
    if not 0 < opts.threshold <= 1:
        parser.error("--threshold must be in (0, 1]")
    sets = {"original_synthetic": [(" ".join(words), intent) for words, intent, _ in _dataset(2)]}
    if opts.challenge:
        rows = [loads(line) for line in opts.challenge.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        sets["challenge"] = [(row["text"], row["intent"]) for row in rows if row.get("split", "evaluation") == "evaluation"]
    for directory in opts.models:
        model = LocalNLU(directory)
        print(dumps({"artifact": directory.name, "threshold": opts.threshold,
                     "sets": {name: evaluate(model, examples, opts.threshold) for name, examples in sets.items()}}))


if __name__ == "__main__":
    main()
