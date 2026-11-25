"""Bound one local inference call without accumulating pending model jobs."""

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from bot_core.neural_nlu import Prediction


class Interpreter(Protocol):
    def predict(self, message: str) -> Prediction: ...


class BoundedInference:
    def __init__(self, model: Interpreter, *, timeout_seconds: float = 0.35):
        if timeout_seconds <= 0:
            raise ValueError("Inference timeout must be positive.")
        self._model = model
        self._timeout = timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-nlu")
        self._lock = Lock()
        self._inflight: Future[Prediction] | None = None

    def predict(self, message: str) -> Prediction:
        with self._lock:
            if self._inflight is not None and not self._inflight.done():
                raise TimeoutError("Local inference is still busy.")
            future = self._executor.submit(self._model.predict, message)
            self._inflight = future
        return future.result(timeout=self._timeout)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
