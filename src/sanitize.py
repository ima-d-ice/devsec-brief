import re
from typing import List

INJECTION_PATTERNS: List[str] = [
    r"(?i)ignore\s+(previous|above|all)\s+instructions",
    r"(?i)system\s*[:\-]\s*",
    r"(?i)you\s+are\s+now\s+a",
    r"###\s*system",
    r"<<<.*?>>>",
    r"\[INST\].*?\[/INST\]",
    r"(?i)disregard\s+(previous|above|all)\s+(instructions|prompts)",
    r"(?i)forget\s+(previous|above|all)\s+(instructions|context)",
    r"(?i)new\s+instructions\s*:",
    r"(?i)override\s+(previous|system)\s+(instructions|prompt)",
    r"(?i)act\s+as\s+(if\s+you\s+are|a\s+different)",
    r"(?i)pretend\s+to\s+be",
    r"(?i)roleplay\s+as",
    r"\{\{.*?\}\}",
    r"<%.*?%>",
]

COMPILED_PATTERNS = [re.compile(p) for p in INJECTION_PATTERNS]

def sanitize_text(text: str, max_length: int = None) -> str:
    if not text:
        return ""
    result = text
    for pattern in COMPILED_PATTERNS:
        result = pattern.sub("[filtered]", result)
    if max_length and len(result) > max_length:
        result = result[:max_length]
    return result

def sanitize_query(query: str) -> str:
    return sanitize_text(query, max_length=2000)

def sanitize_content(content: str) -> str:
    return sanitize_text(content, max_length=50000)

def sanitize_definition(definition: str) -> str:
    return sanitize_text(definition, max_length=500)

def sanitize_history(history: List[dict]) -> List[dict]:
    return [
        {"role": msg["role"], "content": sanitize_query(msg["content"])[:1000]}
        for msg in history
        if msg.get("content")
    ]

def contains_injection_pattern(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in COMPILED_PATTERNS)