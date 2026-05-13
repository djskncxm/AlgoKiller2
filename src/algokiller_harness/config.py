from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class TraceFiles:
    code: Path | None = None
    rw: Path | None = None
    bl: Path | None = None
    arg: Path | None = None


@dataclass(frozen=True)
class HarnessConfig:
    env_file: Path | None
    provider: str
    model_name: str
    model: str
    api_key: str
    api_base: str
    trace_file: Path
    mode: str
    artifacts_dir: Path
    max_tokens: int
    max_iterations: int
    model_retries: int
    system_reinjection_interval: int
    context_compaction_threshold_chars: int
    temperature: float
    reasoning_effort: str
    trace_dir: Path | None = None
    trace_files: TraceFiles | None = None


PROVIDER_ALIASES = {
    "openai": "openai",
    "openai-compatible": "openai",
    "openai_compatible": "openai",
    "custom-openai": "openai",
    "custom_openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "gemini": "gemini",
}


def _require_trace_file(path_text: str | None) -> Path:
    if not path_text:
        raise ValueError("Missing trace file. Start with --trace-file /path/to/trace.log or --trace-dir /path/to/dir/.")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.exists():
        raise ValueError(f"Trace file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Trace path is not a file: {path}")
    return path


def _discover_trace_dir(path_text: str) -> tuple[Path, TraceFiles]:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.exists():
        raise ValueError(f"Trace directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Trace path is not a directory: {path}")
    code = path / "code.log"
    if not code.is_file():
        raise ValueError(f"Trace directory must contain code.log: {path}")
    rw = path / "rw.log"
    bl = path / "bl.log"
    arg = path / "arg.log"
    return path, TraceFiles(
        code=code,
        rw=rw if rw.is_file() else None,
        bl=bl if bl.is_file() else None,
        arg=arg if arg.is_file() else None,
    )


def _require_mode(mode: str | None) -> str:
    if not mode:
        raise ValueError("Missing analysis mode. Start with --mode ciphertext or general.")
    if mode not in {"ciphertext", "general"}:
        raise ValueError(f"Unsupported analysis mode: {mode}. Use ciphertext or general.")
    return mode


def _model_provider_prefix(provider: str) -> str:
    provider_name = _normalize_provider(provider)
    provider_prefixes = {
        "openai": "openai",
        "anthropic": "anthropic",
        "google": "gemini",
        "gemini": "gemini",
    }
    return provider_prefixes[provider_name]


def _normalize_provider(provider: str) -> str:
    provider_name = provider.strip().lower()
    if provider_name not in PROVIDER_ALIASES:
        supported = ", ".join(sorted(PROVIDER_ALIASES))
        raise ValueError(f"Unsupported model provider: {provider}. Supported providers: {supported}.")
    return PROVIDER_ALIASES[provider_name]


def _model_from_provider_and_name(*, provider: str, model_name: str) -> str:
    name = model_name.strip()
    if not name:
        raise ValueError("Missing model name. Set LITELLM_MODEL_NAME, for example gpt-5.4.")
    if "/" in name:
        return name
    return f"{_model_provider_prefix(provider)}/{name}"


def _provider_from_model(model: str) -> str:
    if "/" not in model:
        return "openai"
    provider, _ = model.split("/", 1)
    return provider


def _load_model_settings() -> tuple[str, str, str]:
    provider = _normalize_provider(os.getenv("LITELLM_PROVIDER", "").strip() or "openai")
    model_name = os.getenv("LITELLM_MODEL_NAME", "").strip()
    if not model_name:
        model_name = "gpt-5.4"
    model = _model_from_provider_and_name(provider=provider, model_name=model_name)
    if "/" in model_name:
        provider = _provider_from_model(model)
        model_name = model.split("/", 1)[1]
    return provider, model_name, model


def _load_api_settings() -> tuple[str, str]:
    return os.getenv("API_KEY", "").strip(), os.getenv("API_BASE", "").strip()


def _load_environment() -> Path | None:
    env_file = os.getenv("HARNESS_ENV_FILE")
    if env_file:
        path = Path(env_file).expanduser().resolve()
        load_dotenv(dotenv_path=path, override=True)
        return path

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(dotenv_path=cwd_env, override=True)
        return cwd_env

    return None


def load_config(*, trace_file: str | None = None, trace_dir: str | None = None, mode: str | None = None) -> HarnessConfig:
    env_file = _load_environment()
    provider, model_name, model = _load_model_settings()
    api_key, api_base = _load_api_settings()

    if trace_file and trace_dir:
        raise ValueError("--trace-file and --trace-dir are mutually exclusive.")

    resolved_trace_dir: Path | None = None
    trace_files: TraceFiles | None = None
    if trace_dir:
        resolved_trace_dir, trace_files = _discover_trace_dir(trace_dir)
        resolved_trace_file = trace_files.code
    else:
        resolved_trace_file = _require_trace_file(trace_file)

    return HarnessConfig(
        env_file=env_file,
        provider=provider,
        model_name=model_name,
        model=model,
        api_key=api_key,
        api_base=api_base,
        trace_file=resolved_trace_file,
        mode=_require_mode(mode),
        artifacts_dir=Path(os.getenv("HARNESS_ARTIFACTS_DIR", "artifacts")),
        max_tokens=int(os.getenv("HARNESS_MAX_TOKENS", "99999")),
        max_iterations=int(os.getenv("HARNESS_MAX_ITERATIONS", "99999")),
        model_retries=max(1, int(os.getenv("HARNESS_MODEL_RETRIES", "5"))),
        system_reinjection_interval=max(1, int(os.getenv("HARNESS_SYSTEM_REINJECTION_INTERVAL", "50"))),
        context_compaction_threshold_chars=max(0, int(os.getenv("HARNESS_CONTEXT_COMPACTION_THRESHOLD_CHARS", "100000"))),
        temperature=float(os.getenv("HARNESS_TEMPERATURE", "0")),
        reasoning_effort=os.getenv("HARNESS_REASONING_EFFORT", "medium"),
        trace_dir=resolved_trace_dir,
        trace_files=trace_files,
    )
