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


def _solver_specs() -> List[Dict[str, str]]:
    from .direct_pdf.agents.pdf_independent_agent import parse_solver_specs
    specs = parse_solver_specs(getattr(cfg, 'INDEPENDENT_SOLVERS', []),
                               cfg.INDEPENDENT_VERIFIER_MODEL)
    return [{'model': s.model, 'base_url': s.base_url or cfg.active_llm_base_url()}
            for s in specs]


def _served_models(base_url: str, api_key: str) -> Optional[List[Dict[str, Any]]]:
    """Hỏi endpoint OpenAI-compatible nó THỰC SỰ đang phục vụ gì (không raise).

    Server vLLM trả `root` (repo trọng số) và `max_model_len` — thứ tên model
    trong config không nói được.
    """
    if not base_url:
        return None
    import urllib.request
    req = urllib.request.Request(base_url.rstrip('/') + '/models')
    if api_key:
        req.add_header('Authorization', f'Bearer {api_key}')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode('utf-8'))
    except Exception:                                  # noqa: BLE001
        return None
    out = []
    for m in (data.get('data') or []) if isinstance(data, dict) else []:
        if isinstance(m, dict):
            out.append({k: m.get(k) for k in ('id', 'root', 'max_model_len',
                                              'owned_by') if m.get(k) is not None})
    return out


def _model_revisions() -> Dict[str, str]:
    raw = getattr(cfg, 'MODEL_REVISIONS', '') or ''
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {'_unparsed': raw[:200]}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def models_snapshot() -> Dict[str, Any]:
    from .model_family import independence_level, model_family
    solvers = _solver_specs()
    for s in solvers:
        s['family'] = model_family(s['model'])
    snapshot: Dict[str, Any] = {
        'provider': cfg.LLM_PROVIDER,
        'base_url': cfg.active_llm_base_url(),
        'generator': cfg.GENERATOR_MODEL,
        'generator_family': model_family(cfg.GENERATOR_MODEL),
        'judge': cfg.JUDGE_MODEL,
        'judge_family': model_family(cfg.JUDGE_MODEL),
        'independent_verifier': cfg.INDEPENDENT_VERIFIER_MODEL,
        'independent_solvers': solvers,
        'independent_consensus': getattr(cfg, 'INDEPENDENT_CONSENSUS', 'all'),
        # cross_family | partly_same_family | same_family | unknown
        'independence': independence_level(
            cfg.GENERATOR_MODEL, [s['model'] for s in solvers]),
        'embedding': cfg.EMBEDDING_MODEL,
        'revisions': _model_revisions(),
    }
    if cfg.LLM_PROVIDER == 'openai_compatible':
        served: Dict[str, Any] = {}
        urls = {cfg.active_llm_base_url()} | {s['base_url'] for s in solvers}
        for url in sorted(u for u in urls if u):
            key = (cfg.active_llm_api_key() if url == cfg.active_llm_base_url()
                   else (getattr(cfg, 'INDEPENDENT_API_KEY', '')
                         or cfg.active_llm_api_key()))
            served[url] = _served_models(url, key)
        snapshot['served_models'] = served
    return snapshot


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
    models = data.get('models') or {}
    if models.get('generator') and not (models.get('revisions') or {}).get(
            models.get('generator')):
        gaps.append(
            f"model {models.get('generator')} không ghim snapshot trọng số: "
            f"nhà cung cấp có thể đổi model phía sau cùng một tên"
        )
    if (data.get('code') or {}).get('dirty'):
        gaps.append('cây làm việc có thay đổi chưa commit')
    if not (data.get('code') or {}).get('commit'):
        gaps.append('không xác định được commit')
    if not data.get('documents'):
        gaps.append('không ghi hash tài liệu nguồn')
    return gaps


def validity_warnings(manifest: RunManifest | Dict[str, Any]) -> List[str]:
    """Những điều kiện làm YẾU kết luận của run (khác với tái lập được hay không)."""
    data = manifest.to_dict() if isinstance(manifest, RunManifest) else dict(manifest)
    models = data.get('models') or {}
    warnings: List[str] = []
    mechanisms = data.get('mechanisms') or {}
    if mechanisms.get(ablation.INDEPENDENT_VERIFICATION, True):
        level = models.get('independence')
        if level == 'same_family':
            warnings.append(
                'mọi solver độc lập cùng họ với generator: sự trùng khớp không '
                'loại được lỗi tương quan giữa hai model')
        elif level == 'partly_same_family':
            warnings.append('một phần hội đồng solver cùng họ với generator')
        elif level == 'unknown':
            warnings.append('không xác định được họ của generator hoặc solver')
    if models.get('judge_family') and (
            models.get('judge_family') == models.get('generator_family')):
        warnings.append(
            'Critic cùng họ với generator: điểm chất lượng của nó có thể thiên '
            'vị câu do chính họ model đó viết')
    return warnings
