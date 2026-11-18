"""Model adapters, and the deterministic stub the test suite runs against.

Every provider returns the same `Completion`, so the runner never branches on
which model produced an answer. The stub implements that interface without a
network call, which is what lets the whole pipeline -- prompt construction,
execution, comparison, scoring, reporting -- run in CI with no API key.

On `temperature`: it is deliberately absent. Sampling parameters were removed on
Claude Opus 5, Sonnet 5, and Opus 4.8/4.7 -- sending `temperature`, `top_p`, or
`top_k` returns a 400. Determinism is not available as a dial, which matters for
a benchmark: two runs of the same configuration can differ, so a small accuracy
gap between models is not automatically a real one.
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_MODEL = "claude-opus-5"

# Thinking counts against max_tokens on the same budget as the response, and a
# thinking model given a hard schema question can spend heavily before writing a
# short query. A tight cap here truncates mid-answer and scores as a failure that
# is really a harness bug.
DEFAULT_MAX_TOKENS = 16000

# USD per million tokens, at list price. Cache reads bill at ~0.1x input and
# 5-minute cache writes at ~1.25x, which the cost calculation below applies.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    # Sonnet 5 list price; introductory pricing ($2/$10) runs to 2026-08-31, so
    # a run before then costs less than reported here.
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Models that have no `effort` parameter. Sending `output_config.effort` to one
# of these is rejected, so the provider leaves it out.
NO_EFFORT_MODELS = frozenset({"claude-haiku-4-5"})


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def cost_usd(self, model: str) -> float:
        rates = PRICING.get(model)
        if rates is None:
            return 0.0
        input_rate, output_rate = rates
        return (
            self.input_tokens * input_rate
            + self.cache_read_tokens * input_rate * 0.1
            + self.cache_write_tokens * input_rate * 1.25
            + self.output_tokens * output_rate
        ) / 1_000_000


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    #  Set when the model declined or the call failed. The runner scores these
    #  as failures rather than crashing, so one bad question cannot end a sweep.
    refused: bool = False
    error: str | None = None


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str) -> Completion: ...


# ── SQL extraction ────────────────────────────────────────────────────────────

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    """Pull the query out of a model response.

    The prompt asks for bare SQL, and models mostly comply -- but a fenced block
    or a sentence of preamble is common enough that scoring it as a syntax error
    would measure formatting compliance rather than SQL ability.
    """
    fenced = _FENCE.search(text)
    candidate = fenced.group(1) if fenced else text

    lines = candidate.strip().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"\s*(select|with)\b", line, re.I)),
        None,
    )
    if start is None:
        return candidate.strip().rstrip(";").strip()
    return "\n".join(lines[start:]).strip().rstrip(";").strip()


# ── Deterministic stub ────────────────────────────────────────────────────────

_QUESTION_RE = re.compile(r"Question:\s*(.+?)\s*\n\s*SQL:", re.DOTALL)


class StubProvider:
    """A model substitute that answers from a lookup table, no network involved.

    Its point is not to imitate a model but to drive every branch of the runner
    deterministically: a correct answer, a wrong-but-valid answer, and a query
    that fails to execute. CI therefore exercises the scoring path end to end,
    and a regression in comparison or classification fails the build rather than
    waiting to be noticed during a paid sweep.
    """

    name = "stub"

    def __init__(
        self,
        answers: dict[str, str],
        model: str = "stub-v1",
        wrong_every: int = 4,
        broken_every: int = 7,
    ) -> None:
        self.answers = answers
        self.model = model
        self._wrong_every = wrong_every
        self._broken_every = broken_every

    def complete(self, system: str, prompt: str) -> Completion:
        match = _QUESTION_RE.search(prompt)
        question = match.group(1).strip() if match else ""
        reference = self.answers.get(question)

        if reference is None:
            return Completion(
                text="SELECT 1", model=self.model, usage=self._usage(system, prompt)
            )

        # Keyed on the question, not a counter, so a subset run produces the
        # same verdicts as a full run for the questions it shares.
        seed = sum(ord(c) for c in question)
        if seed % self._broken_every == 0:
            sql = reference.replace("FROM", "FROM nonexistent_table --", 1)
        elif seed % self._wrong_every == 0:
            sql = f"SELECT * FROM ({reference}) LIMIT 1"
        else:
            sql = reference

        return Completion(text=sql, model=self.model, usage=self._usage(system, prompt))

    @staticmethod
    def _usage(system: str, prompt: str) -> Usage:
        # Rough character-based estimate; the stub is never billed, and reporting
        # a plausible number keeps the cost columns exercised in tests.
        return Usage(input_tokens=(len(system) + len(prompt)) // 4, output_tokens=40)


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicProvider:
    """Claude via the Anthropic SDK.

    The runner puts the schema in the system prompt, and it is identical for
    every question in a prompt variant, so the system block is marked as a
    cached prefix: the first call of a variant pays to write it and the rest
    read it at roughly a tenth of the input rate.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cache_system_prompt: bool = True,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "The anthropic package is required for live runs: pip install anthropic"
            ) from exc

        self._anthropic = anthropic
        # A bare client resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an
        # `ant auth login` profile -- an unset env var does not mean no credential.
        self._client = anthropic.Anthropic()
        self.model = model
        # None when the model does not take the parameter; main.py records this
        # value in the run, so it reflects what was actually sent.
        self.effort = None if model in NO_EFFORT_MODELS else effort
        self._max_tokens = max_tokens
        self._cache = cache_system_prompt

    def complete(self, system: str, prompt: str) -> Completion:
        system_blocks: list[dict] = [{"type": "text", "text": system}]
        if self._cache:
            # The minimum cacheable prefix is model-dependent (512 tokens on
            # Opus 5, 1024 on Sonnet 5, 4096 on Haiku 4.5). Below it the marker
            # is ignored silently -- no error, just no cache hit -- so check
            # cache_read_tokens in the run JSON rather than assuming it worked.
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        request: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.effort is not None:
            request["output_config"] = {"effort": self.effort}

        started = time.perf_counter()
        try:
            response = self._client.messages.create(**request)
        except self._anthropic.APIStatusError as exc:
            return self._failure(f"API error {exc.status_code}: {exc.message}", started)
        except self._anthropic.APIConnectionError as exc:
            return self._failure(f"connection error: {exc}", started)

        latency_ms = (time.perf_counter() - started) * 1000
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        )

        # Check the stop reason before reading content: a declined request
        # returns HTTP 200 with empty or partial content, so indexing content[0]
        # unconditionally would raise on a refusal.
        if response.stop_reason == "refusal":
            return Completion(
                text="", model=self.model, usage=usage, latency_ms=latency_ms,
                refused=True, error="model declined the request",
            )

        text = "".join(b.text for b in response.content if b.type == "text")
        return Completion(text=text, model=self.model, usage=usage, latency_ms=latency_ms)

    def _failure(self, message: str, started: float) -> Completion:
        return Completion(
            text="", model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=message,
        )


# ── Ollama (local) ────────────────────────────────────────────────────────────

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Local generation is slow compared with a hosted API, and a hard question can
# take minutes on consumer hardware. This bounds a hung request, not a slow one.
OLLAMA_TIMEOUT_SECONDS = 300.0


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    """Minimal JSON POST over the standard library.

    Deliberately not `requests`: the base install is duckdb and pyyaml, and a
    local provider is not worth a third runtime dependency.
    """
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OllamaProvider:
    """A model served locally by Ollama.

    Included because it costs nothing to run, which makes a real sweep possible
    without API billing -- and because the frontier-versus-local gap is a more
    informative result than any single model's score. A small local model fails
    text-to-SQL in ways the taxonomy can name, which is exactly what the
    taxonomy is for.

    Unlike the Claude path, this one *can* be made deterministic: Ollama still
    accepts sampling parameters, so temperature is pinned to 0 and a seed is
    fixed. Two runs of the same local configuration produce the same answers,
    which the hosted path cannot promise.
    """

    name = "ollama"

    def __init__(
        self,
        model: str,
        host: str = OLLAMA_HOST,
        timeout: float = OLLAMA_TIMEOUT_SECONDS,
        post=_post_json,
        seed: int = 0,
    ) -> None:
        self.model = model
        self._url = f"{host.rstrip('/')}/api/chat"
        self._timeout = timeout
        self._post = post
        self._seed = seed

    def complete(self, system: str, prompt: str) -> Completion:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0, "seed": self._seed},
        }

        started = time.perf_counter()
        try:
            body = self._post(self._url, payload, self._timeout)
        except OSError as exc:
            # Connection refused is the overwhelmingly common case: the daemon
            # is not running. Say so rather than surfacing a bare errno.
            return Completion(
                text="", model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"could not reach Ollama at {self._url} ({exc}); is `ollama serve` running?",
            )
        except Exception as exc:  # noqa: BLE001 -- scored as a failure, not a crash
            return Completion(
                text="", model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"ollama error: {exc}",
            )

        latency_ms = (time.perf_counter() - started) * 1000
        if "error" in body:
            return Completion(
                text="", model=self.model, latency_ms=latency_ms,
                error=f"ollama error: {body['error']}",
            )

        return Completion(
            text=(body.get("message") or {}).get("content", ""),
            model=self.model,
            # Ollama reports prompt/completion counts under its own names. There
            # is no cache, so those fields stay zero, and cost stays zero because
            # a local model has no per-token price.
            usage=Usage(
                input_tokens=body.get("prompt_eval_count", 0) or 0,
                output_tokens=body.get("eval_count", 0) or 0,
            ),
            latency_ms=latency_ms,
        )


def build_provider(spec: str, answers: dict[str, str], effort: str = "high") -> Provider:
    """Resolve a `--model` argument to a provider.

    Three routes, kept unambiguous by an explicit prefix on the local one:
    `stub` (offline, what CI runs), `ollama:<model>` (local, free), and any
    Claude model id (hosted, billed).
    """
    if spec == "stub":
        return StubProvider(answers)
    if spec.startswith("ollama:"):
        local_model = spec.split(":", 1)[1]
        if not local_model:
            raise ValueError("expected a model after 'ollama:', e.g. ollama:llama3.1")
        return OllamaProvider(local_model)
    if spec not in PRICING:
        known = ", ".join(sorted(PRICING))
        raise ValueError(
            f"unknown model {spec!r}; expected 'stub', 'ollama:<model>', or one of: {known}"
        )
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        # Not fatal -- an `ant auth login` profile also works -- but the most
        # common cause of a failed sweep is no credential at all.
        print(f"Note: no ANTHROPIC_API_KEY set; relying on a stored profile for {spec}.")
    return AnthropicProvider(model=spec, effort=effort)
