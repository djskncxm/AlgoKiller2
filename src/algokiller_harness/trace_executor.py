from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import TraceFiles


class LocalTraceToolExecutor:
    def __init__(
        self,
        artifacts_dir: Path,
        trace_file: Path,
        trace_files: TraceFiles | None = None,
        repo_root: Path | None = None,
    ):
        self.artifacts_dir = artifacts_dir.resolve()
        self.trace_file = trace_file.resolve()
        self.trace_files = trace_files
        self.repo_root = repo_root.resolve() if repo_root is not None else self._discover_repo_root()
        self.search_dir = self.repo_root / "tools" / "search"
        self.search_bin = self.search_dir / "ak_search"
        self.search_daemons: dict[str, subprocess.Popen[str]] = {}
        self._file_paths: dict[str, Path] = self._build_file_paths()

    def _build_file_paths(self) -> dict[str, Path]:
        if self.trace_files is None:
            return {"code": self.trace_file}
        paths: dict[str, Path] = {}
        if self.trace_files.code:
            paths["code"] = self.trace_files.code
        if self.trace_files.rw:
            paths["rw"] = self.trace_files.rw
        if self.trace_files.bl:
            paths["bl"] = self.trace_files.bl
        return paths

    def _indexed_prefix_keys(self) -> set[str]:
        return {"rw", "bl"} & set(self._file_paths.keys())

    def _discover_repo_root(self) -> Path:
        candidates = []
        env_root = os.getenv("HARNESS_REPO_ROOT")
        if env_root:
            candidates.append(Path(env_root).expanduser())
        candidates.extend(
            [
                Path.cwd(),
                Path(__file__).resolve().parents[2],
            ]
        )
        for candidate in candidates:
            root = candidate.resolve()
            if (root / "tools" / "search").is_dir():
                return root
        return Path.cwd().resolve()

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "trace_search":
                return self._trace_search(arguments)
            if name == "trace_context":
                return self._trace_context(arguments)
            if name == "trace_cross_ref":
                return self._trace_cross_ref(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return f"Unknown tool: {name}"

    def close(self) -> None:
        for key in list(self.search_daemons):
            self._close_search_daemon(key)

    def _ensure_search_bin(self) -> None:
        if self.search_bin.exists():
            return
        if not self.search_dir.is_dir():
            raise FileNotFoundError(
                f"Trace search tool directory not found: {self.search_dir}. "
                "Run algokiller from the repository root or set HARNESS_REPO_ROOT=/path/to/AlgoKiller."
            )
        subprocess.run(["make"], cwd=self.search_dir, check=True, capture_output=True, text=True)

    def _close_search_daemon(self, file_key: str) -> None:
        daemon = self.search_daemons.pop(file_key, None)
        if daemon is None:
            return
        if daemon.poll() is None:
            try:
                if daemon.stdin is not None:
                    daemon.stdin.write("quit\n")
                    daemon.stdin.flush()
            except Exception:
                pass
            try:
                daemon.wait(timeout=1)
            except subprocess.TimeoutExpired:
                daemon.terminate()
                try:
                    daemon.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    daemon.kill()

    def _ensure_search_daemon(self, file_key: str) -> subprocess.Popen[str]:
        existing = self.search_daemons.get(file_key)
        if existing is not None and existing.poll() is None:
            return existing

        self._close_search_daemon(file_key)
        self._ensure_search_bin()

        file_path = self._file_paths.get(file_key)
        if file_path is None:
            raise ValueError(f"Trace file '{file_key}' is not available. Available: {', '.join(self._file_paths)}")

        cmd = [str(self.search_bin), "daemon", "--file", str(file_path)]
        if file_key in self._indexed_prefix_keys():
            cmd.append("--indexed-prefix")

        daemon = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        if daemon.stdout is None:
            daemon.kill()
            raise RuntimeError(f"Trace search daemon ({file_key}) did not expose stdout")

        ready_line = daemon.stdout.readline()
        if not ready_line:
            stderr = daemon.stderr.read() if daemon.stderr is not None else ""
            daemon.wait(timeout=1)
            raise RuntimeError(f"Trace search daemon ({file_key}) failed to start: {stderr.strip()}")
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            daemon.kill()
            raise RuntimeError(f"Trace search daemon ({file_key}) returned invalid ready message: {ready_line!r}") from exc
        if ready.get("type") != "daemon_ready" or ready.get("status") != "ok":
            daemon.kill()
            raise RuntimeError(f"Trace search daemon ({file_key}) refused to start: {ready}")

        self.search_daemons[file_key] = daemon
        return daemon

    def _daemon_request(self, file_key: str, command: str, *, max_output_chars: int = 30000, retry: bool = True) -> str:
        daemon = self._ensure_search_daemon(file_key)
        if daemon.stdin is None or daemon.stdout is None:
            self._close_search_daemon(file_key)
            raise RuntimeError(f"Trace search daemon ({file_key}) pipes are unavailable")

        try:
            daemon.stdin.write(command + "\n")
            daemon.stdin.flush()
        except (BrokenPipeError, OSError):
            self._close_search_daemon(file_key)
            if retry:
                return self._daemon_request(file_key, command, max_output_chars=max_output_chars, retry=False)
            raise

        stdout_parts: list[str] = []
        stdout_chars = 0
        truncated = False
        while True:
            line = daemon.stdout.readline()
            if not line:
                stderr = daemon.stderr.read() if daemon.stderr is not None else ""
                self._close_search_daemon(file_key)
                if retry:
                    return self._daemon_request(file_key, command, max_output_chars=max_output_chars, retry=False)
                raise RuntimeError(f"Trace search daemon exited unexpectedly: {stderr.strip()}")
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("type") == "daemon_end":
                return json.dumps(
                    {
                        "status": "ok" if data.get("status") == "ok" else "error",
                        "returncode": 0 if data.get("status") == "ok" else 1,
                        "stdout": "".join(stdout_parts),
                        "stderr": str(data.get("error") or ""),
                        "truncated": truncated,
                    },
                    ensure_ascii=False,
                )
            if stdout_chars + len(line) <= max_output_chars:
                stdout_parts.append(line)
                stdout_chars += len(line)
            else:
                truncated = True

    def _run(self, argv: list[str], *, cwd: Path | None = None, max_output_chars: int = 20000) -> str:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        truncated = False
        if len(stdout) > max_output_chars:
            stdout = stdout[:max_output_chars]
            truncated = True
        return json.dumps(
            {
                "status": "ok" if completed.returncode == 0 else "error",
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr[-4000:],
                "truncated": truncated,
            },
            ensure_ascii=False,
        )

    def _positive_int(self, value: Any, default: int, name: str) -> int:
        if value is None:
            return default
        result = int(value)
        if result < 1:
            raise ValueError(f"{name} must be >= 1")
        return result

    def _required_positive_int(self, arguments: dict[str, Any], name: str, maximum: int | None = None) -> int:
        if name not in arguments:
            raise ValueError(f"{name} is required")
        result = self._positive_int(arguments.get(name), 1, name)
        if maximum is not None and result > maximum:
            raise ValueError(f"{name} must be <= {maximum}")
        return result

    def _non_negative_int(self, value: Any, default: int, name: str) -> int:
        if value is None:
            return default
        result = int(value)
        if result < 0:
            raise ValueError(f"{name} must be >= 0")
        return result

    def _bounded_non_negative_int(self, value: Any, default: int, name: str, maximum: int) -> int:
        result = self._non_negative_int(value, default, name)
        if result > maximum:
            raise ValueError(f"{name} must be <= {maximum}")
        return result

    def _trace_search_once(self, file_key: str, query: str, *, from_line: int = 0, before_line: int = 0, limit: int) -> str:
        query_hex = query.encode("utf-8").hex()
        return self._daemon_request(file_key, f"match\t{from_line}\t{before_line}\t{limit}\t{query_hex}", max_output_chars=30000)

    def _search_result_has_matches(self, result_json: str) -> bool:
        result = json.loads(result_json)
        return result.get("status") == "ok" and bool(str(result.get("stdout") or "").strip())

    def _search_result_is_empty_success(self, result_json: str) -> bool:
        result = json.loads(result_json)
        return result.get("status") == "ok" and not str(result.get("stdout") or "").strip()

    def _byte_reverse_hex_query(self, hex_digits: str) -> str:
        padded_hex = hex_digits if len(hex_digits) % 2 == 0 else "0" + hex_digits
        return "0x" + "".join(reversed([padded_hex[i : i + 2] for i in range(0, len(padded_hex), 2)]))

    def _hex_search_fallback_queries(self, query: str) -> list[str]:
        if not query.lower().startswith("0x"):
            return []

        hex_digits = query[2:]
        if not re.fullmatch(r"[0-9a-fA-F]+", hex_digits):
            return []

        fallbacks = [self._byte_reverse_hex_query(hex_digits)]

        trimmed_hex = hex_digits.lstrip("0")
        if trimmed_hex and trimmed_hex != hex_digits:
            fallbacks.append("0x" + trimmed_hex)
            fallbacks.append(self._byte_reverse_hex_query(trimmed_hex))

        unique_fallbacks: list[str] = []
        seen = {query.lower()}
        for fallback_query in fallbacks:
            normalized = fallback_query.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_fallbacks.append(fallback_query)
        return unique_fallbacks

    def _trace_search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments["query"])
        if not query:
            raise ValueError("query must not be empty")
        file_key = str(arguments.get("file", "code"))
        if file_key not in self._file_paths:
            raise ValueError(f"file must be one of: {', '.join(sorted(self._file_paths))}")
        has_from_line = "from_line" in arguments
        has_before_line = "before_line" in arguments
        if has_from_line == has_before_line:
            raise ValueError("exactly one of from_line or before_line is required")
        limit = self._required_positive_int(arguments, "limit", 100)
        if has_before_line:
            before_line = self._required_positive_int(arguments, "before_line")
            result = self._trace_search_once(file_key, query, before_line=before_line, limit=limit)
            if not self._search_result_is_empty_success(result):
                return result
            for fallback_query in self._hex_search_fallback_queries(query):
                fallback_result = self._trace_search_once(file_key, fallback_query, before_line=before_line, limit=limit)
                if self._search_result_has_matches(fallback_result):
                    return fallback_result
            return result

        from_line = self._required_positive_int(arguments, "from_line")
        result = self._trace_search_once(file_key, query, from_line=from_line, limit=limit)
        if not self._search_result_is_empty_success(result):
            return result
        for fallback_query in self._hex_search_fallback_queries(query):
            fallback_result = self._trace_search_once(file_key, fallback_query, from_line=from_line, limit=limit)
            if self._search_result_has_matches(fallback_result):
                return fallback_result
        return result

    def _trace_context(self, arguments: dict[str, Any]) -> str:
        if "context" in arguments:
            raise ValueError("context is no longer supported; use before and after")
        file_key = str(arguments.get("file", "code"))
        if file_key not in self._file_paths:
            raise ValueError(f"file must be one of: {', '.join(sorted(self._file_paths))}")
        line = self._required_positive_int(arguments, "line")
        if "before" not in arguments:
            raise ValueError("before is required")
        if "after" not in arguments:
            raise ValueError("after is required")
        before_count = self._bounded_non_negative_int(arguments.get("before"), 0, "before", 100)
        after_count = self._bounded_non_negative_int(arguments.get("after"), 0, "after", 100)
        return self._daemon_request(file_key, f"context\t{line}\t{before_count}\t{after_count}", max_output_chars=30000)

    def _trace_cross_ref(self, arguments: dict[str, Any]) -> str:
        seq_id = str(arguments.get("seq_id", "")).strip().lower()
        if not seq_id or not re.fullmatch(r"[0-9a-f]+", seq_id):
            raise ValueError("seq_id must be a non-empty hex string (without 0x prefix)")

        seq_decimal = int(seq_id, 16)
        result: dict[str, Any] = {"status": "ok", "seq_id": seq_id}

        # code.log: seq N is at line N+2 (line 1 is blank, line 2 is seq 0)
        if "code" in self._file_paths:
            code_line = seq_decimal + 2
            code_result = json.loads(
                self._daemon_request("code", f"context\t{code_line}\t0\t0", max_output_chars=5000)
            )
            if code_result.get("status") == "ok" and code_result.get("stdout", "").strip():
                raw_stdout = code_result["stdout"].strip()
                try:
                    line_data = json.loads(raw_stdout.split("\n")[0])
                    result["code"] = {"line": code_line, "text": line_data.get("text", "")}
                except (json.JSONDecodeError, IndexError):
                    result["code"] = {"line": code_line, "text": raw_stdout}
            else:
                result["code"] = {"line": code_line, "text": None, "note": "line not found"}

        # rw.log: use seq_lookup (binary search, O(log n))
        if "rw" in self._file_paths:
            result["rw"] = self._seq_lookup_records("rw", seq_decimal)

        # bl.log: use seq_lookup (binary search, O(log n))
        if "bl" in self._file_paths:
            result["bl"] = self._seq_lookup_records("bl", seq_decimal)

        return json.dumps(result, ensure_ascii=False)

    def _seq_lookup_records(self, file_key: str, seq_decimal: int) -> list[dict[str, Any]]:
        lookup_result = json.loads(
            self._daemon_request(file_key, f"seq_lookup\t{seq_decimal}\t10", max_output_chars=10000)
        )
        if lookup_result.get("status") != "ok":
            return []
        stdout = lookup_result.get("stdout", "")
        if not stdout.strip():
            return []

        records: list[dict[str, Any]] = []
        current_record_lines: list[str] = []
        current_line_no: int | None = None

        for json_line in stdout.strip().split("\n"):
            try:
                data = json.loads(json_line)
            except json.JSONDecodeError:
                continue
            if data.get("type") != "seq_match":
                continue
            text = data.get("text", "")
            is_target = data.get("target", False)

            if is_target:
                if current_record_lines and current_line_no is not None:
                    records.append({"line": current_line_no, "raw": "\n".join(current_record_lines)})
                current_record_lines = [text]
                current_line_no = data.get("line")
            else:
                current_record_lines.append(text)

        if current_record_lines and current_line_no is not None:
            records.append({"line": current_line_no, "raw": "\n".join(current_record_lines)})

        return records
