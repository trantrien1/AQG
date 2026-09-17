"""Nhận diện HỌ model (nhà phát triển / dòng trọng số gốc) từ model id.

Mục tiêu kiểm chứng độc lập chỉ độc lập đến mức nguồn giải của nó khác nguồn
đã viết câu hỏi. Hai model cùng họ (vd gpt-4o và gpt-4o-mini) học từ dữ liệu và
quy trình huấn luyện gần nhau nên dễ sai CÙNG MỘT KIỂU — khi đó "hai nguồn cùng
ra một số" không còn là bằng chứng mạnh. Module này ghi lại họ của từng model để
run manifest nói rõ cặp generator/solver có khác họ hay không.

Nhận diện bằng mẫu tên nên chỉ là heuristic: tên không khớp mẫu nào trả
``'unknown'`` thay vì đoán.
"""
from __future__ import annotations

import re
from typing import Iterable, List

# Model chưng cất mang trọng số gốc của họ khác: DeepSeek-R1-Distill-Qwen là
# Qwen, DeepSeek-R1-Distill-Llama là Llama. Kiểm TRƯỚC bảng chính.
_DISTILL_BASES = (
    ('qwen', re.compile(r'distill[-_]?qwen', re.I)),
    ('llama', re.compile(r'distill[-_]?llama', re.I)),
)

# (họ, mẫu). Thứ tự có nghĩa: mẫu đầu tiên khớp thắng.
_FAMILIES = (
    ('openai', re.compile(r'(^|/)(gpt|chatgpt|o[1-9](-|$)|davinci|text-embedding)'
                          r'|(^|/)openai/', re.I)),
    ('qwen', re.compile(r'qwen|qwq', re.I)),
    ('microsoft-phi', re.compile(r'(^|/)phi-?\d|(^|/)microsoft/phi', re.I)),
    ('meta-llama', re.compile(r'llama|(^|/)meta-', re.I)),
    ('google', re.compile(r'gemma|gemini|palm', re.I)),
    ('mistral', re.compile(r'mistral|mixtral|ministral|magistral|codestral'
                           r'|pixtral|devstral', re.I)),
    ('deepseek', re.compile(r'deepseek', re.I)),
    ('zhipu-glm', re.compile(r'(^|/|-)glm|zhipu|z-ai/', re.I)),
    ('anthropic', re.compile(r'claude|anthropic', re.I)),
    ('xai', re.compile(r'grok|x-ai/', re.I)),
    ('internlm', re.compile(r'internlm|internvl', re.I)),
    ('ibm-granite', re.compile(r'granite', re.I)),
    ('nvidia', re.compile(r'nemotron', re.I)),
    ('allenai', re.compile(r'olmo|tulu', re.I)),
    ('moonshot', re.compile(r'kimi|moonshot', re.I)),
    ('minimax', re.compile(r'minimax', re.I)),
    ('cohere', re.compile(r'command-?r|cohere|aya', re.I)),
)

UNKNOWN = 'unknown'


def model_family(model_id: str) -> str:
    """Họ của ``model_id``; ``'unknown'`` nếu không nhận ra."""
    text = str(model_id or '').strip()
    if not text:
        return UNKNOWN
    for family, pattern in _DISTILL_BASES:
        if pattern.search(text):
            return family
    for family, pattern in _FAMILIES:
        if pattern.search(text):
            return family
    return UNKNOWN


def shared_families(generator: str, solvers: Iterable[str]) -> List[str]:
    """Các solver cùng họ với generator (bỏ qua họ không nhận ra)."""
    gen = model_family(generator)
    if gen == UNKNOWN:
        return []
    return [s for s in solvers if model_family(s) == gen]


def independence_level(generator: str, solvers: Iterable[str]) -> str:
    """``cross_family`` | ``partly_same_family`` | ``same_family`` | ``unknown``."""
    solvers = [s for s in solvers if str(s or '').strip()]
    if not solvers:
        return UNKNOWN
    gen = model_family(generator)
    fams = [model_family(s) for s in solvers]
    if gen == UNKNOWN or UNKNOWN in fams:
        return UNKNOWN
    same = sum(1 for f in fams if f == gen)
    if same == 0:
        return 'cross_family'
    if same == len(fams):
        return 'same_family'
    return 'partly_same_family'
