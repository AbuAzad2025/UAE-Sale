"""CPU BiGRU with masked attention for intent and token tagging."""

import json
from pathlib import Path

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from bot_core.neural_nlu import Prediction, feature, regex_entities, tokenize


class IntentNet(nn.Module):
    def __init__(self, vocabulary_size: int, intents: int, tags: int):
        super().__init__()
        self.embedding = nn.Embedding(vocabulary_size, 32, padding_idx=0)
        self.encoder = nn.GRU(32, 32, batch_first=True, bidirectional=True)
        self.attention = nn.Linear(64, 1)
        self.intents = nn.Linear(64, intents)
        self.tags = nn.Linear(64, tags)

    def forward(self, batch: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        mask = batch != 0
        packed = pack_padded_sequence(
            self.embedding(batch), mask.sum(1).cpu(), batch_first=True, enforce_sorted=False,
        )
        encoded, _ = self.encoder(packed)
        states, _ = pad_packed_sequence(encoded, batch_first=True, total_length=batch.shape[1])
        attention = self.attention(states).squeeze(-1).masked_fill(~mask, -torch.inf).softmax(1)
        return self.intents((states * attention.unsqueeze(-1)).sum(1)), self.tags(states)


class LocalNLU:
    def __init__(self, directory: Path):
        metadata = json.loads((directory / "vocab.json").read_text(encoding="utf-8"))
        self.vocab: dict[str, int] = metadata["vocab"]
        self.intents: list[str] = metadata["intents"]
        self.tags: list[str] = metadata["tags"]
        self.temperature = float(metadata["temperature"])
        self.feature_version = int(metadata.get("feature_version", 1))
        self.model = IntentNet(len(self.vocab), len(self.intents), len(self.tags))
        self.model.load_state_dict(torch.load(directory / "model.pt", map_location="cpu", weights_only=True))
        self.model.eval()

    @torch.no_grad()
    def predict(self, message: str) -> Prediction:
        tokens = tokenize(message)
        if not tokens:
            return Prediction("guide", 0.0, {}, {})
        batch = torch.tensor([[self.vocab.get(feature(token, self.feature_version), 1) for token in tokens]])
        intent, tags = self.model(batch)
        probability = (intent[0] / self.temperature).softmax(0)
        index = int(probability.argmax())
        entities: dict[str, list[str]] = {}
        active = None
        for token, score in zip(tokens, tags[0].softmax(-1)):
            tag = self.tags[int(score.argmax())]
            kind = tag[2:] if tag != "O" and float(score.max()) >= 0.65 else None
            if kind is not None:
                values = entities.setdefault(kind, [])
                if tag.startswith("I-") and kind == active:
                    values[-1] += " " + token
                else:
                    values.append(token)
            active = kind
        for key, values in regex_entities(tokens).items():
            entities.setdefault(key, values)
        return Prediction(
            self.intents[index], float(probability[index]),
            dict(zip(self.intents, probability.tolist())),
            entities,
        )
