"""How much a draft may take at a time, by the machine's memory (本人 2026-09-16:
每次可以处理不止 3000 字；上下文大小按用户内存决定).

The draft model runs with a context sized to the passage; the KV cache of a
Qwen3-4B (36 layers, 8 KV heads of 128) costs about 150 MB per 1,000 tokens
in f16 (推算), so 32k of context is ~4.8 GB beside the 4.3 GB model. A
chapter of N characters costs roughly N × 1.1 prompt tokens plus 26 answer
tokens per quoted unit. The tiers below leave that room and keep the answer
under the output limit."""
import os

TIERS = (                # least memory first; (GB, chars, units, context, answer tokens, segments per project)
    (0, 3000, 80, 16384, 4096, 500),
    (32, 6000, 160, 32768, 8192, 1000),
    (64, 12000, 320, 65536, 12288, 2000),
)


def memory_gb():
    try:
        return os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0


def draft_limits(gb=None):
    """{'chars', 'units', 'context', 'max_tokens', 'segments', 'memory_gb'} for this machine,
    or for `gb` gigabytes. VOXSTAGE_DRAFT_CHARS caps the characters (testing, or a
    machine that shares its memory with other work)."""
    gb = memory_gb() if gb is None else gb
    chosen = TIERS[0]
    for tier in TIERS:
        if gb >= tier[0] - 0.5:          # 31.9 GB reported for a 32 GB machine still counts
            chosen = tier
    _, chars, units, context, max_tokens, segments = chosen
    cap = os.environ.get('VOXSTAGE_DRAFT_CHARS')
    if cap and cap.isdigit() and int(cap) < chars:
        scale = int(cap) / chars
        chars, units = int(cap), max(80, int(units * scale))
    return {'chars': chars, 'units': units, 'context': context, 'max_tokens': max_tokens, 'segments': segments, 'memory_gb': round(gb, 1)}


# 最后更新：2026-09-16 · Claude Hera
