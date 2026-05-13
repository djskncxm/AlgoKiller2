from __future__ import annotations


RECOVERED_SOURCE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_recovered_source",
        "description": (
            "Write the final reconstructed Python source code for the user's task. "
            "Use this only when the recovered implementation is ready to deliver. "
            "Pass a stable relative .py path; the local harness automatically appends "
            "the current mode and datetime to the filename before writing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative .py path under the artifacts directory, for example recovered.py. "
                        "Do not add a mode or timestamp yourself; the harness adds them locally."
                    ),
                },
                "source": {
                    "type": "string",
                    "description": "Complete Python source code.",
                },
                "notes": {
                    "type": "string",
                    "description": "Short evidence/confidence note to store next to the source.",
                },
            },
            "required": ["path", "source"],
        },
    },
}


ASK_USER_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "Ask the user a detailed clarification question only when the current analysis mode "
            "allows it and the target itself is ambiguous or missing. Do not use this just because "
            "optional context, field names, samples, or semantic labels are unavailable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The concrete question to ask the user.",
                },
                "why_needed": {
                    "type": "string",
                    "description": "Why this answer is required to recover the Python source correctly.",
                },
                "needed_items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific function, register, memory address, sample, value, or context needed.",
                },
            },
            "required": ["question", "why_needed"],
        },
    },
}


TRACE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_search",
        "description": (
            "Case-insensitive exact substring search over the session trace file. "
            "Use this first to locate functions, registers, addresses, constants, call summaries, "
            "and hexdump ASCII text in very large traces. Every call must include exactly one "
            "of from_line or before_line, plus limit. before_line searches backward and returns "
            "nearest earlier matches first. Choose a search purpose before each call. For byte/hex "
            "data starting with 0x, if the original query has no matches the harness automatically "
            "tries byte-reversed endian order; if that misses and the hex value has leading zeroes, "
            "it then tries the leading-zero-trimmed value and the byte-reversed trimmed value. "
            "Fallback hits are returned as normal search matches without extra annotations. For "
            "values longer than 4 bytes, try 2-4 distinctive 4-byte windows in both original and "
            "reversed order before expanding. limit must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Exact substring to find. Matching is case-insensitive for ASCII.",
                },
                "from_line": {
                    "type": "integer",
                    "description": "Required 1-based file line to start searching from.",
                    "minimum": 1,
                },
                "before_line": {
                    "type": "integer",
                    "description": (
                        "Required instead of from_line when searching backward. "
                        "Only lines before this 1-based file line are searched; nearest matches are returned first."
                    ),
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Required maximum number of matching lines to return. Must be <= 100.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query", "limit"],
        },
    },
}


TRACE_SEARCH_TOOL_MULTIFILE = {
    "type": "function",
    "function": {
        "name": "trace_search",
        "description": (
            "Case-insensitive exact substring search over a session trace file. "
            "Use this first to locate functions, registers, addresses, constants, call summaries, "
            "and hexdump ASCII text in very large traces. Every call must include exactly one "
            "of from_line or before_line, plus limit. before_line searches backward and returns "
            "nearest earlier matches first. Choose a search purpose before each call. For byte/hex "
            "data starting with 0x, if the original query has no matches the harness automatically "
            "tries byte-reversed endian order; if that misses and the hex value has leading zeroes, "
            "it then tries the leading-zero-trimmed value and the byte-reversed trimmed value. "
            "Fallback hits are returned as normal search matches without extra annotations. For "
            "values longer than 4 bytes, try 2-4 distinctive 4-byte windows in both original and "
            "reversed order before expanding. limit must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Exact substring to find. Matching is case-insensitive for ASCII.",
                },
                "file": {
                    "type": "string",
                    "enum": ["code", "rw", "bl"],
                    "description": (
                        "Which trace file to search. "
                        "'code' is the instruction execution log (default), "
                        "'rw' is the memory read/write hexdump log, "
                        "'bl' is the external function call log."
                    ),
                },
                "from_line": {
                    "type": "integer",
                    "description": "Required 1-based file line to start searching from.",
                    "minimum": 1,
                },
                "before_line": {
                    "type": "integer",
                    "description": (
                        "Required instead of from_line when searching backward. "
                        "Only lines before this 1-based file line are searched; nearest matches are returned first."
                    ),
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Required maximum number of matching lines to return. Must be <= 100.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query", "limit"],
        },
    },
}


TRACE_CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_context",
        "description": (
            "Return neighboring trace text lines around a 1-based file line in the session trace. "
            "Use this after trace_search to inspect instruction, call, ret, and hexdump context. "
            "Every call must include explicit before and after line counts; each line-count "
            "argument must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "integer",
                    "description": "1-based target file line.",
                },
                "before": {
                    "type": "integer",
                    "description": "Required explicit number of lines before the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
                "after": {
                    "type": "integer",
                    "description": "Required explicit number of lines after the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["line", "before", "after"],
        },
    },
}


TRACE_CONTEXT_TOOL_MULTIFILE = {
    "type": "function",
    "function": {
        "name": "trace_context",
        "description": (
            "Return neighboring trace text lines around a 1-based file line in a session trace file. "
            "Use this after trace_search to inspect instruction, call, ret, and hexdump context. "
            "Every call must include explicit before and after line counts; each line-count "
            "argument must be no greater than 100."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "integer",
                    "description": "1-based target file line.",
                },
                "file": {
                    "type": "string",
                    "enum": ["code", "rw", "bl"],
                    "description": (
                        "Which trace file to read context from. "
                        "'code' is the instruction execution log (default), "
                        "'rw' is the memory read/write hexdump log, "
                        "'bl' is the external function call log."
                    ),
                },
                "before": {
                    "type": "integer",
                    "description": "Required explicit number of lines before the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
                "after": {
                    "type": "integer",
                    "description": "Required explicit number of lines after the target. Must be <= 100.",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["line", "before", "after"],
        },
    },
}


TRACE_CROSS_REF_TOOL = {
    "type": "function",
    "function": {
        "name": "trace_cross_ref",
        "description": (
            "Look up all trace records correlated to a given hex sequence ID across all trace files. "
            "Returns the code.log instruction line, any rw.log memory read/write records, and any "
            "bl.log external function call records for that sequence. Use this to correlate an "
            "instruction with its memory operations and external calls. The sequence ID is the hex "
            "number that appears before ':' at the start of lines in each trace file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seq_id": {
                    "type": "string",
                    "description": (
                        "The hex sequence ID (without 0x prefix) from trace file lines. "
                        "For example '942' or 'a8dc9f'."
                    ),
                },
            },
            "required": ["seq_id"],
        },
    },
}
