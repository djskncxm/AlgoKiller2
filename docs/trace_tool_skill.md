# Trace Tool Skill

This project uses local tools to inspect ARM64 trace text:

- `trace_search`: case-insensitive exact substring search for large trace files. Every call must include `limit` and exactly one of `from_line` or `before_line`. `from_line` searches forward; `before_line` searches only lines before that anchor and returns nearest earlier matches first. `limit` must be at most 100. In multi-file mode, pass `file` (`code`, `rw`, or `bl`) to select which trace file to search; defaults to `code`.
- `trace_context`: line-based context around any trace file line. Every call must include explicit `before` and `after`; each line-count value must be at most 100. In multi-file mode, pass `file` to select which trace file; defaults to `code`.
- `trace_cross_ref`: (multi-file mode only) given a hex sequence ID, returns the correlated instruction from code.log, any memory read/write records from rw.log, and any external function call records from bl.log.

The trace file and analysis mode are selected once at harness startup with `--trace-file` or `--trace-dir` and `--mode`. Tool calls do not include a file path; the harness injects the session trace path internally.

## Single-File vs Multi-File Mode

**Single-file mode** (`--trace-file PATH`): all trace data is in one merged file. Tools have no `file` parameter.

**Multi-file mode** (`--trace-dir PATH`): the directory contains split trace files:
- `code.log` — ARM64 instruction execution. Each line: `<hex_seq>  : <abs_pc>  [<rel_offset>]  "<disasm>" <reg_annotations>`
- `rw.log` — memory read/write hexdumps. Each record: header `<hex_seq>: (r|w)(0x<base>+0x<offset>)` + hexdump lines + blank line separator.
- `bl.log` — external function call summaries. Each record: header `<hex_seq>: [0x<arg_ptr>][<arg_idx>]: <func_name>` + hexdump lines + blank line separator.
- `arg.log` — static request parameters (injected into system prompt automatically).

All files are correlated by the hex sequence ID (`hex_seq`) that prefixes header lines. A single code.log instruction can have 0+ rw.log records and 0+ bl.log records.

Supported modes:

- `ciphertext`: recover encryption/signing/encoding pipeline and plaintext from a ciphertext.
- `general`: handle open-ended trace analysis such as field semantics, execution flow, detection points, and call/buffer evidence.

## Trace Format

### Instruction lines (code.log or merged file)

Instruction lines start with `[` (merged) or a hex sequence number (split):

```text
[module] 0xABS!0xREL mnemonic operands; observed inputs -> observed outputs
```

or (split format):

```text
<hex_seq>  : <abs_pc>  [<rel_offset>]  "<disasm>" (r)reg=val (w)reg=val
```

`0xABS` is the runtime address. `0xREL` is the module-relative address. Register and memory facts such as `x0=0x...`, `mem_r=0x...`, and `mem_w=0x...` are concrete observations from that execution.

### External calls (bl.log or merged file)

```text
call func: __memcpy_aarch64_simd(0xDST, 0xSRC, 0xLEN)
hexdump at address 0xSRC with length 0xLEN:
SRC: ...hex bytes... |ASCII preview|
ret: 0xDST
```

In split format (bl.log):
```text
<hex_seq>: [0x<arg_ptr>][<arg_idx>]: <func_name>
<addr>: <hex bytes>  |ASCII|
<addr>: <hex bytes>  |ASCII|
<addr>: <hex bytes>  |ASCII|
```

### Memory read/write (rw.log)

```text
<hex_seq>: (r|w)(0x<base_addr>+0x<offset>)
<addr>: <hex bytes>  |ASCII|
<addr>: <hex bytes>  |ASCII|
<addr>: <hex bytes>  |ASCII|
```

The hexdump rows are sorted by increasing memory address. The ASCII preview is useful for searching, but strict reconstruction should use the hex bytes and the dump address/length because nonprintable bytes are rendered as dots.

## Workflow

1. Search for the target: a function name, register result, memory address, relative address, constant, or hexdump ASCII.
2. Expand context around promising hits. For calls, include setup instructions before `call func:`, the hexdump rows, `ret:`, and consuming instructions after the call.
3. Follow data flow with repeated search:
   - choose one purpose before each search: locate a target instance, find the nearest writer/producer, trace an input source, verify an algorithm hypothesis, or confirm a consumer;
   - search exact register values, memory addresses, return values, field names, and hexdump ASCII;
   - for hex/byte data, retry byte-reversed endian order when the original byte order has no hits;
   - when a byte sequence is longer than 4 bytes and the full sequence has no hits, search 2-4 distinctive 4-byte sliding windows in both original and reversed byte order before expanding to more windows or 5-8 byte sequences;
   - treat the earliest hit as a candidate only; verify it lies on a credible data-flow path before using it as producer or generation evidence;
   - use `from_line` to page forward after a known hit;
   - use `before_line` to find the nearest producer or writer before a known sink/generation line;
   - search memory write addresses (`mem_w=0x...`) and read addresses (`mem_r=0x...`) to connect producers and consumers.
4. In multi-file mode, use `trace_cross_ref` with a hex sequence ID to correlate an instruction with its memory operations and external calls across all files.
5. Inspect context around important line numbers. Context supplies call boundaries, hexdumps, branch choices, constants, and neighboring register/memory observations.
6. Keep an evidence ledger with line numbers, relative addresses, memory addresses, and observed values before writing recovered Python.

## Large Trace Discipline

For GB-scale traces, search output and context can still grow quickly. Use small `limit` values, continue with `from_line` after the last hit, search backward with `before_line` when looking for the closest earlier producer, and only expand context around lines that materially explain source, transformation, or sink behavior.
Every `trace_search` call must pass `limit` and exactly one of `from_line` or `before_line`; every `trace_context` call must pass explicit `before` and `after`. The maximum allowed value for any count parameter is 100.

## Multi-File Search Strategy

When working with split trace files:
- Default to searching `code.log` (file='code') for instruction-level evidence.
- Search `rw.log` (file='rw') when looking for memory read/write patterns, buffer contents, or specific byte sequences in memory dumps.
- Search `bl.log` (file='bl') when looking for external function calls (strlen, memcpy, free, etc.) and their argument hexdumps.
- Use `trace_cross_ref` to quickly correlate a sequence ID found in one file with records in all other files.
