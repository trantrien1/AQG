"""Run manifest — mọi thứ cần để dựng lại một lần chạy.

Một con số trong bài báo chỉ có nghĩa khi truy được về đúng phiên bản đã sinh
ra nó. Manifest ghi lại: seed, model, phiên bản prompt, hash tài liệu nguồn,
phiên bản verifier, commit code, bảng ngưỡng và bảng bật/tắt cơ chế.

Manifest KHÔNG chứa kết quả — nó chỉ mô tả điều kiện chạy. Ghép manifest với
metric (`pipeline.eval_metrics`) mới thành một dòng kết quả đầy đủ.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ablation
from . import config as cfg
from .independent_target import INDEPENDENT_PROMPT_VERSION
from .verification_status import VERIFIER_VERSION

MANIFEST_SCHEMA_VERSION = '1.0.0'


def document_hash(path: str | os.PathLike) -> Dict[str, Any]:
    """SHA-256 + kích thước của một tài liệu nguồn."""
    p = Path(path)
    entry: Dict[str, Any] = {'path': str(p), 'name': p.name}
    try:
        data = p.read_bytes()
    except OSError as exc:
        entry['error'] = str(exc)
        return entry
    entry['sha256'] = hashlib.sha256(data).hexdigest()
    entry['bytes'] = len(data)
    return entry


def git_commit() -> Dict[str, Any]:
    """Commit đang chạy + có thay đổi chưa commit hay không."""
    info: Dict[str, Any] = {}
    root = Path(__file__).resolve().parent.parent
    try:
        info['commit'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=str(root),
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        status = subprocess.check_output(
            ['git', 'status', '--porcelain'], cwd=str(root),
            stderr=subprocess.DEVNULL, text=True,
        )
        # Cây làm việc bẩn ⇒ commit KHÔNG mô tả đủ code đã chạy. Ghi rõ để
        # người đọc không tưởng là tái lập được chỉ bằng checkout commit đó.
        info['dirty'] = bool(status.strip())
        if info['dirty']:
            info['dirty_files'] = [
                line[3:] for line in status.splitlines()[:40] if line[3:]
            ]
    except Exception as exc:
        info['error'] = str(exc)
    return info


def _package_versions() -> Dict[str, str]:
    versions = {'python': sys.version.split()[0], 'platform': platform.platform()}
    for name in ('sympy', 'networkx', 'openai', 'fastapi'):
        try:
            module = __import__(name)
            versions[name] = str(getattr(module, '__version__', 'unknown'))
        except Exception:
            versions[name] = 'not installed'
    return versions


def thresholds_snapshot() -> Dict[str, Any]:
    return {
        name: getattr(cfg, name, None)
        for name in getattr(cfg, 'CALIBRATABLE_THRESHOLDS', {})
    }


def models_snapshot() -> Dict[str, Any]:
    return {
        'provider': cfg.LLM_PROVIDER,
        'base_url': cfg.active_llm_base_url(),
        'generator': cfg.GENERATOR_MODEL,
        'judge': cfg.JUDGE_MODEL,
        'independent_verifier': cfg.INDEPENDENT_VERIFIER_MODEL,
        'embedding': cfg.EMBEDDING_MODEL,
    }


def _document_handling() -> Dict[str, Any]:
    """Tài liệu thực sự tới tay mô hình dưới dạng nào (không raise)."""
    try:
        from .llm_client import assert_pdf_native_support, PdfNotNativeError
    except Exception:                                  # noqa: BLE001
        return {'document_handling': 'unknown'}
    try:
        return assert_pdf_native_support(cfg.GENERATOR_MODEL)
    except PdfNotNativeError as exc:
        return {'document_handling': 'would_fall_back_to_text_extraction',
                'error': str(exc)[:200]}
    except Exception:                                  # noqa: BLE001
        return {'document_handling': 'unknown'}


def generation_snapshot() -> Dict[str, Any]:
    return {
        'temperature': cfg.GEN_TEMPERATURE,
        'independent_verifier_temperature': cfg.INDEPENDENT_VERIFIER_TEMPERATURE,
        'max_tokens': cfg.GEN_MAX_TOKENS,
        'parallel_slots': cfg.DIRECT_PDF_PARALLEL_SLOTS,
        'max_slot_attempts': cfg.MAX_SLOT_ATTEMPTS,
        'pdf_attach_mode': getattr(cfg, 'PDF_ATTACH_MODE', ''),
        'pdf_image_dpi': getattr(cfg, 'PDF_IMAGE_DPI', None),
        'pdf_image_max_pages': getattr(cfg, 'PDF_IMAGE_MAX_PAGES', None),
        # Tài liệu tới tay mô hình dưới dạng nào: đọc nguyên trang, ảnh từng
        # trang, hay đã bị trích text. Bắt buộc ghi lại vì hai cách sau làm
        # thay đổi bản chất cơ chế bám tài liệu mà kết quả nhìn vẫn bình thường.
        'document_handling': _document_handling(),
        'multi_agent': getattr(cfg, 'DIRECT_PDF_MULTI_AGENT', None),
        'refuted_policy': getattr(cfg, 'REFUTED_POLICY', 'review'),
    }


@dataclass
class RunManifest:
    """Điều kiện chạy của một run. Ghi kèm mọi artifact kết quả."""

    run_id: str
    schema_version: str = MANIFEST_SCHEMA_VERSION
    started_at: str = ''
    finished_at: Optional[str] = None
    seed: int = 0
    label: str = ''
    ablation_arm: Optional[str] = None
    mechanisms: Dict[str, bool] = field(default_factory=dict)
    models: Dict[str, Any] = field(default_factory=dict)
    generation: Dict[str, Any] = field(default_factory=dict)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    prompt_version: str = ''
    independent_prompt_version: str = ''
    verifier_version: str = ''
    documents: List[Dict[str, Any]] = field(default_factory=list)
    code: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    notes: Dict[str, Any] = field(default_factory=dict)

    def finish(self) -> 'RunManifest':
        self.finished_at = dt.datetime.now(dt.timezone.utc).isoformat()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                     encoding='utf-8')
        return p


def build_manifest(
    *,
    run_id: str = '',
    documents: Optional[List[str]] = None,
    seed: Optional[int] = None,
    label: str = '',
    notes: Optional[Dict[str, Any]] = None,
) -> RunManifest:
    """Chụp lại toàn bộ điều kiện chạy ở thời điểm gọi."""
    now = dt.datetime.now(dt.timezone.utc)
    return RunManifest(
        run_id=run_id or now.strftime('%Y%m%d-%H%M%S'),
        started_at=now.isoformat(),
        seed=int(seed if seed is not None else cfg.DETERMINISTIC_SEED),
        label=label,
        ablation_arm=ablation.current_arm(),
        mechanisms=ablation.snapshot(),
        models=models_snapshot(),
        generation=generation_snapshot(),
        thresholds=thresholds_snapshot(),
        prompt_version=cfg.PROMPT_VERSION,
        independent_prompt_version=INDEPENDENT_PROMPT_VERSION,
        verifier_version=VERIFIER_VERSION,
        documents=[document_hash(d) for d in (documents or [])],
        code=git_commit(),
        environment=_package_versions(),
        notes=dict(notes or {}),
    )


def reproducibility_gaps(manifest: RunManifest | Dict[str, Any]) -> List[str]:
    """Liệt kê những thứ khiến run này CHƯA tái lập được chính xác.

    Dùng để không tuyên bố "reproducible" quá tay: nhiệt độ sinh > 0 và nhiều
    luồng song song là hai nguồn phi tất định thật sự, seed không xoá được.
    """
    data = manifest.to_dict() if isinstance(manifest, RunManifest) else dict(manifest)
    gaps: List[str] = []
    gen = data.get('generation') or {}
    if (gen.get('temperature') or 0) > 0:
        gaps.append(
            f"nhiệt độ sinh {gen['temperature']} > 0: model lấy mẫu ngẫu nhiên, "
            f"seed của pipeline không khống chế được phía provider"
        )
    if (gen.get('parallel_slots') or 1) > 1:
        gaps.append(
            f"chạy {gen['parallel_slots']} slot song song: thứ tự hoàn thành "
            f"đổi giữa các lần chạy nên tập câu được chấp nhận có thể khác"
        )
    if (data.get('code') or {}).get('dirty'):
        gaps.append('cây làm việc có thay đổi chưa commit')
    if not (data.get('code') or {}).get('commit'):
        gaps.append('không xác định được commit')
    if not data.get('documents'):
        gaps.append('không ghi hash tài liệu nguồn')
    return gaps
