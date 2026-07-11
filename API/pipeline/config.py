"""Cấu hình pipeline sinh MCQ Toán (chung — không phân môn).

Tự động load API/.env (KEY=VALUE) nếu file tồn tại — không cần python-dotenv.
"""
import os
import pathlib


def _load_dotenv():
    """Đọc API/.env và set os.environ. Skip nếu key đã có sẵn trong env."""
    env_path = pathlib.Path(__file__).resolve().parent.parent / '.env'
    if not env_path.exists():
        return
    try:
        # utf-8-sig: bỏ qua BOM nếu editor (VS Code/PowerShell) lưu kèm —
        # BOM dính vào key của dòng đầu làm biến đó bị bỏ qua trong im lặng.
        for line in env_path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except Exception:
        pass


_load_dotenv()


# ==== PROVIDER ====
_RAW_LLM_PROVIDER = (
    os.getenv('AQG_LLM_PROVIDER')
    or os.getenv('LLM_PROVIDER')
    or os.getenv('API_PROVIDER')
    or 'openrouter'
).strip().lower()
_PROVIDER_ALIASES = {
    '9router': '9router',
    'ninerouter': '9router',
    'nine-router': '9router',
    'openai-compatible': 'openai_compatible',
    'openai_compatible': 'openai_compatible',
    'compatible': 'openai_compatible',
    'custom': 'openai_compatible',
}
LLM_PROVIDER = _PROVIDER_ALIASES.get(_RAW_LLM_PROVIDER, _RAW_LLM_PROVIDER)
if LLM_PROVIDER not in {'openrouter', 'openai', 'openai_compatible', '9router'}:
    LLM_PROVIDER = 'openrouter'
API_PROVIDER = LLM_PROVIDER
OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_SITE_URL = os.getenv('OPENROUTER_SITE_URL', '')
OPENROUTER_SITE_NAME = os.getenv('OPENROUTER_SITE_NAME', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', '').strip()
OPENAI_COMPATIBLE_BASE_URL = os.getenv('OPENAI_COMPATIBLE_BASE_URL', '').strip()
NINEROUTER_API_KEY = os.getenv('NINEROUTER_API_KEY') or os.getenv('NINEROUTER_KEY', '')
NINEROUTER_URL = os.getenv('NINEROUTER_URL', '').strip().rstrip('/')
NINEROUTER_BASE_URL = (
    os.getenv('NINEROUTER_BASE_URL')
    or ((NINEROUTER_URL + '/v1') if NINEROUTER_URL else '')
    or 'http://127.0.0.1:20128/v1'
).strip().rstrip('/')


# ==== MODELS ====
OPENROUTER_GENERATOR_MODEL = os.getenv('OPENROUTER_GENERATOR_MODEL', 'openai/gpt-4o-mini')
OPENROUTER_JUDGE_MODEL = os.getenv('OPENROUTER_JUDGE_MODEL', 'openai/gpt-4o-mini')
OPENROUTER_EMBEDDING_MODEL = os.getenv('OPENROUTER_EMBEDDING_MODEL', 'openai/text-embedding-3-small')
OPENAI_GENERATOR_MODEL = os.getenv('OPENAI_GENERATOR_MODEL', 'gpt-4o-mini')
OPENAI_JUDGE_MODEL = os.getenv('OPENAI_JUDGE_MODEL', OPENAI_GENERATOR_MODEL)
OPENAI_EMBEDDING_MODEL = os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
NINEROUTER_GENERATOR_MODEL = (
    os.getenv('NINEROUTER_GENERATOR_MODEL')
    or os.getenv('OPENAI_GENERATOR_MODEL')
    or 'cx/gpt-5.4'
)
NINEROUTER_JUDGE_MODEL = (
    os.getenv('NINEROUTER_JUDGE_MODEL')
    or os.getenv('OPENAI_JUDGE_MODEL')
    or NINEROUTER_GENERATOR_MODEL
)
NINEROUTER_EMBEDDING_MODEL = (
    os.getenv('NINEROUTER_EMBEDDING_MODEL')
    or os.getenv('AQG_EMBEDDING_MODEL')
    or ''
)
GENERATOR_MODEL = (
    os.getenv('AQG_GENERATOR_MODEL')
    or (
        NINEROUTER_GENERATOR_MODEL
        if LLM_PROVIDER == '9router'
        else OPENAI_GENERATOR_MODEL
        if LLM_PROVIDER in {'openai', 'openai_compatible'}
        else OPENROUTER_GENERATOR_MODEL
    )
)
# JUDGE defaults to the same tier as generator. Avoid qwen3.6-flash here —
# it rate-limits aggressively upstream (429s) and bottlenecks the pipeline.
JUDGE_MODEL = (
    os.getenv('AQG_JUDGE_MODEL')
    or (
        NINEROUTER_JUDGE_MODEL
        if LLM_PROVIDER == '9router'
        else OPENAI_JUDGE_MODEL
        if LLM_PROVIDER in {'openai', 'openai_compatible'}
        else OPENROUTER_JUDGE_MODEL
    )
)
EMBEDDING_MODEL = (
    os.getenv('AQG_EMBEDDING_MODEL')
    or (
        NINEROUTER_EMBEDDING_MODEL
        if LLM_PROVIDER == '9router'
        else OPENAI_EMBEDDING_MODEL
        if LLM_PROVIDER in {'openai', 'openai_compatible'}
        else OPENROUTER_EMBEDDING_MODEL
    )
)

def active_llm_api_key() -> str:
    if LLM_PROVIDER == 'openrouter':
        return OPENROUTER_API_KEY
    if LLM_PROVIDER == '9router':
        return NINEROUTER_API_KEY or OPENAI_API_KEY
    return OPENAI_API_KEY

def active_llm_base_url() -> str:
    if LLM_PROVIDER == 'openai':
        return OPENAI_BASE_URL
    if LLM_PROVIDER == 'openai_compatible':
        return OPENAI_COMPATIBLE_BASE_URL or OPENAI_BASE_URL
    if LLM_PROVIDER == '9router':
        return NINEROUTER_BASE_URL or OPENAI_BASE_URL
    return OPENROUTER_BASE_URL

def has_llm_api_key() -> bool:
    return bool(active_llm_api_key())

def missing_llm_api_key_message() -> str:
    if LLM_PROVIDER == 'openrouter':
        env_name = 'OPENROUTER_API_KEY'
    elif LLM_PROVIDER == '9router':
        env_name = 'NINEROUTER_API_KEY or OPENAI_API_KEY'
    else:
        env_name = 'OPENAI_API_KEY'
    return f'{env_name} not set for AQG_LLM_PROVIDER={LLM_PROVIDER}'


# ==== GENERATION ====
GEN_TEMPERATURE = float(os.getenv('AQG_GEN_TEMPERATURE', '0.45'))
GEN_MAX_TOKENS = int(os.getenv('AQG_GEN_MAX_TOKENS', '1800'))
LLM_TIMEOUT_SECONDS = float(os.getenv('AQG_LLM_TIMEOUT_SECONDS', '180'))
LLM_RETRIES = int(os.getenv('AQG_LLM_RETRIES', '1'))
# Ngân sách retry RIÊNG cho lỗi throttle tạm thời (gateway trả 400/429 kèm
# '(reset after Ns)' khi rate-limit ảnh). Tách khỏi LLM_RETRIES để không nhầm
# với lỗi modality/config thật.
LLM_THROTTLE_RETRIES = int(os.getenv('AQG_LLM_THROTTLE_RETRIES', '6'))
DEFAULT_GENERATION_MODE = os.getenv('AQG_GENERATION_MODE', 'fast').strip().lower() or 'fast'
DEFAULT_SKILL_MODE = os.getenv(
    'AQG_SKILL_MODE',
    os.getenv('AQG_GENERATION_MODE', 'prompt'),
).strip().lower() or 'prompt'
if DEFAULT_SKILL_MODE in {'skills', 'skill', 'with-skills', 'with_skills', 'prompt+skills', 'advanced'}:
    DEFAULT_SKILL_MODE = 'skills'
else:
    DEFAULT_SKILL_MODE = 'prompt'
USE_SKILLS_DEFAULT = DEFAULT_SKILL_MODE == 'skills'


# ==== PIPELINE PARAMS ====
NUM_SAMPLES_PER_SLOT = 5
FAST_NUM_SAMPLES_PER_SLOT = int(os.getenv('AQG_FAST_NUM_SAMPLES_PER_SLOT', '1'))
NUM_REPAIR_ATTEMPTS = 2
QUALITY_THRESHOLD = 0.55
NLI_PROB_MARGIN = 0.1
DISTRACTOR_SIMILARITY_THRESHOLD = 0.7
QUESTION_DEDUP_THRESHOLD = 0.8
GROUNDING_THRESHOLD = 0.4
NUMERIC_TOLERANCE = 1e-6
NUMERIC_CROSSCHECK_POINTS = 5

# ==== QUOTE / GROUNDING STRICTNESS ====
# When strict (legacy), the rule validator hard-rejects a candidate whenever the
# source quote does not literally contain the exact formula family / concrete
# numbers used in the question (see rule_validator._missing_required_concept_support).
# On theory-only source chunks (definitions, general rules) this rejects almost
# every computational question the LLM writes from a legitimate worked example.
#
# Default is LENIENT: quote relevance is still enforced via token overlap
# (_quote_relevant_to_question), but the brittle formula-family gate is treated
# as a soft signal only. Set AQG_QUOTE_RELEVANCE_STRICT=1 to restore legacy gate.
QUOTE_RELEVANCE_STRICT = os.getenv('AQG_QUOTE_RELEVANCE_STRICT', '0').lower() in ('1', 'true', 'yes')
GENERATION_CONTEXT_MAX_CHARS = int(os.getenv('AQG_GENERATION_CONTEXT_MAX_CHARS', '1500'))
GENERATION_CONTEXT_EXPANDED_MAX_CHARS = int(os.getenv('AQG_GENERATION_CONTEXT_EXPANDED_MAX_CHARS', '3500'))
DISTRACTOR_CONTEXT_MAX_CHARS = 1500
DISTRACTOR_OPTION_MAX_CHARS = 80
CLEAN_CONTEXT_USE_LLM = os.getenv('AQG_CLEAN_CONTEXT_USE_LLM', '0').lower() in ('1', 'true', 'yes')
FAST_ACCEPT_VERIFIED_SHORT_ANSWER = True
FAST_ACCEPT_GROUNDED_UNVERIFIED = True
FAST_ACCEPT_ANSWER_MAX_CHARS = int(os.getenv('AQG_FAST_ACCEPT_ANSWER_MAX_CHARS', '80'))
FAST_ACCEPT_CONCEPTUAL_ANSWER_MAX_CHARS = int(os.getenv('AQG_FAST_ACCEPT_CONCEPTUAL_ANSWER_MAX_CHARS', '260'))
FAST_ACCEPT_HEURISTIC_QUALITY = 0.86
FAST_BATCH_ENABLED = os.getenv('AQG_FAST_BATCH_ENABLED', '1').lower() in ('1', 'true', 'yes')
FAST_BATCH_SIZE = int(os.getenv('AQG_FAST_BATCH_SIZE', '3'))
FAST_BATCH_CONTEXT_CHARS = int(os.getenv('AQG_FAST_BATCH_CONTEXT_CHARS', '700'))
FAST_BATCH_MAX_TOKENS = int(os.getenv('AQG_FAST_BATCH_MAX_TOKENS', '7000'))
FAST_PARALLEL_WORKERS = int(os.getenv('AQG_FAST_PARALLEL_WORKERS', '4'))

# Slots are independent, and each per-slot pipeline is dominated by LLM network
# I/O (writer → distractor → verifier → critic → refine). Processing several
# slots concurrently gives a near-linear latency reduction on the quality-first
# runtime without changing the per-slot pipeline or its quality gates.
#
# Default 1 = strictly sequential (byte-for-byte the previous behavior; fully
# deterministic). Set AQG_PARALLEL_SLOT_WORKERS>1 to trade run-to-run accepted-set
# determinism for wall-clock speed (recommended 3-4 for slow reasoning models).
PARALLEL_SLOT_WORKERS = max(1, int(os.getenv('AQG_PARALLEL_SLOT_WORKERS', '1')))
# Internal generation slot pool.  Default to the requested question count; set
# AQG_GENERATION_SLOT_POOL_MULTIPLIER or AQG_GENERATION_SLOT_POOL_MIN only when
# deliberately over-planning for difficult source documents.
GENERATION_SLOT_POOL_MIN = int(os.getenv('AQG_GENERATION_SLOT_POOL_MIN', '0'))
GENERATION_SLOT_POOL_MULTIPLIER = float(os.getenv(
    'AQG_GENERATION_SLOT_POOL_MULTIPLIER',
    os.getenv('AQG_FAST_PLAN_SLOT_MULTIPLIER', '1.0'),
))
# Backward-compatible alias for old internal callers/scripts.
FAST_PLAN_SLOT_MULTIPLIER = GENERATION_SLOT_POOL_MULTIPLIER

# Bound retry blast radius per slot.  The total job cap is optional: set
# AQG_MAX_JOB_ATTEMPT_MULTIPLIER > 0 to cap total slot-attempts at
# target * multiplier.  The default 0 means no global cap; generation stops
# when enough questions are accepted, all slots exhaust MAX_SLOT_ATTEMPTS, or
# the user cancels the job.
MAX_SLOT_ATTEMPTS = int(os.getenv('AQG_MAX_SLOT_ATTEMPTS', '2'))
MAX_JOB_ATTEMPT_MULTIPLIER = int(os.getenv('AQG_MAX_JOB_ATTEMPT_MULTIPLIER', '0'))


# ==== DETERMINISM ====
DETERMINISTIC_SEED = int(os.getenv('AQG_SEED', '42'))


# ==== DIRECT PDF MODE ====
# Direct_PDF_Mode gửi thẳng file PDF tới Generation_Model thay vì chia chunk.
DIRECT_PDF_MODE_DEFAULT = os.getenv('AQG_DIRECT_PDF_MODE', '0') in ('1', 'true', 'yes')
PDF_PAGE_LIMIT = int(os.getenv('AQG_PDF_PAGE_LIMIT', '30'))
PDF_SIZE_LIMIT = int(os.getenv('AQG_PDF_SIZE_LIMIT', str(20 * 1024 * 1024)))  # 20MB
# Chiến lược đính kèm PDF cho Direct_PDF_Mode:
#   'file'     — gửi PDF base64 dạng part file (cần provider hỗ trợ file input).
#   'file_url' — gửi nguyên file PDF base64 nhưng bọc trong part image_url
#                (data:application/pdf;base64,...). Format của gateway chat2api:
#                mọi loại file đều đi qua image_url với mime tương ứng.
#   'image'    — render mỗi trang PDF thành ảnh PNG, gửi dạng image_url (cần vision).
#                Dùng cho gateway chỉ hỗ trợ ảnh (vd 9router local chặn file PDF).
PDF_ATTACH_MODE = os.getenv('AQG_PDF_ATTACH_MODE', 'image').strip().lower() or 'image'
PDF_IMAGE_DPI = int(os.getenv('AQG_PDF_IMAGE_DPI', '120'))
# Số trang tối đa render thành ảnh và gửi trong MỘT request (tách khỏi
# PDF_PAGE_LIMIT dùng cho ingestion). Provider vision giới hạn số ảnh/request
# (Claude ~100). Với tài liệu dài, ~30 trang đầu đủ để sinh & kiểm 20 câu.
PDF_IMAGE_MAX_PAGES = int(os.getenv('AQG_PDF_IMAGE_MAX_PAGES', '30'))
# Ngân sách token cho mỗi MCQ khi sinh trực tiếp từ PDF (stem + 4 options +
# explanation + detailed_solution). Dùng để scale max_tokens theo số câu yêu cầu.
DIRECT_PDF_TOKENS_PER_QUESTION = int(os.getenv('AQG_DIRECT_PDF_TOKENS_PER_QUESTION', '2600'))
# Two-pass self-review: sau khi sinh nháp, cho model tự rà soát & sửa (số học,
# đáp án đúng nằm trong options, source_quote khớp đề) trước khi parse cuối.
DIRECT_PDF_SELF_REVIEW = os.getenv('AQG_DIRECT_PDF_SELF_REVIEW', '1') in ('1', 'true', 'yes')
DIRECT_PDF_REVIEW_ROUNDS = int(os.getenv('AQG_DIRECT_PDF_REVIEW_ROUNDS', '1'))
# Khi số câu yêu cầu lớn, sinh theo lô nhỏ (tránh model từ chối/cắt cụt khi phải
# sinh quá nhiều câu mới cùng lúc, nhất là tài liệu nhiều bài tập mẫu).
DIRECT_PDF_BATCH_SIZE = int(os.getenv('AQG_DIRECT_PDF_BATCH_SIZE', '6'))
# Kiểm chứng số học bằng SymPy (tái dùng pipeline.verifier): loại câu có
# verifier_payload chứng minh SAI. Câu không kiểm được (type=none) vẫn giữ.
DIRECT_PDF_VERIFY = os.getenv('AQG_DIRECT_PDF_VERIFY', '1') in ('1', 'true', 'yes')
# Kiến trúc multi-agent cho Direct_PDF_Mode (Writer -> Distractor -> Verifier ->
# Critic -> Formatter), mỗi agent gọi vision với các trang PDF làm context. Khi
# tắt (=0) dùng lại generator đơn khối cũ (một prompt lớn + self-review).
DIRECT_PDF_MULTI_AGENT = os.getenv('AQG_DIRECT_PDF_MULTI_AGENT', '1') in ('1', 'true', 'yes')
# Số slot đệm (mỗi slot có thể thử lại tối đa MAX_SLOT_ATTEMPTS lần).
DIRECT_PDF_MA_MAX_TOKENS = int(os.getenv('AQG_DIRECT_PDF_MA_MAX_TOKENS', '2600'))
# Số slot chạy SONG SONG mỗi wave trong Direct_PDF multi-agent (1 = tuần tự).
# chat2api throttle theo giờ; call_llm_with_pdf đã tự đợi khi 429 nên 3 luồng
# vẫn an toàn — nếu gặp 429 dày, hạ xuống 2 hoặc 1.
DIRECT_PDF_PARALLEL_SLOTS = int(os.getenv('AQG_DIRECT_PDF_PARALLEL_SLOTS', '3'))


# ==== SUBJECT ====
# Toán chung — không phân môn cho từng tài liệu.
DEFAULT_SUBJECT = 'Toán'


# ==== DIFFICULTY DISTRIBUTION ====
# Phân bố cho chế độ "mixed". Nghiêng về Vận dụng/Vận dụng cao vì phân bố cũ
# (25/35/30/10) cho ra đề quá dễ. Các preset easy/medium/hard riêng lẻ
# (web/jobs.py _DIFFICULTY_TARGETS) giữ nguyên.
DEFAULT_DIFFICULTY_DISTRIBUTION = [
    {'cognitive_level': 'Nhận biết',    'difficulty_target': 0.30, 'fraction': 0.10},
    {'cognitive_level': 'Thông hiểu',   'difficulty_target': 0.50, 'fraction': 0.25},
    {'cognitive_level': 'Vận dụng',     'difficulty_target': 0.70, 'fraction': 0.40},
    {'cognitive_level': 'Vận dụng cao', 'difficulty_target': 0.85, 'fraction': 0.25},
]


# ==== META-PATTERNS (4 trừu tượng — chỉ làm fallback khi LLM planner không
# infer được pattern_id). Direct_PDF_Mode tự rải Bloom theo yêu cầu đầu vào.
# sinh pattern_id specific từ context — KHÔNG hardcode list dạng bài.
QUESTION_PATTERNS = [
    {'id': 'computation', 'keywords': []},
    {'id': 'conceptual',  'keywords': []},
    {'id': 'reasoning',   'keywords': []},
    {'id': 'application', 'keywords': []},
]


def get_pattern_ids() -> list:
    return [p['id'] for p in QUESTION_PATTERNS]


# ==== PROMPTS ====
SYSTEM_PROMPT = (
    'Bạn là một chuyên gia ra đề Toán nhiều cấp độ (phổ thông và đại học). '
    'Bạn sinh đề trắc nghiệm bám sát ngữ cảnh được cung cấp, không bịa kiến thức ngoài. '
    'Đáp án và lời giải phải đúng về mặt toán học và có thể kiểm tra được bằng máy. '
    'Mọi công thức/biểu thức Toán trong phần hiển thị cho học sinh phải dùng LaTeX inline dạng \\(...\\).'
)


USER_PROMPT_TEMPLATE = (
    'Sinh một câu hỏi trắc nghiệm 4 phương án (1 đúng, 3 nhiễu) dựa trên ngữ cảnh và yêu cầu sau.\n\n'
    'Chủ đề ngữ cảnh: {topic}\n'
    'Mức nhận thức: {cognitive_level} (mục tiêu khó {difficulty_target})\n'
    'Mẫu câu hỏi gợi ý (question_pattern): {pattern}\n'
    'Sai lầm thường gặp (gợi ý cho distractor):\n{misconceptions}\n'
    'Quy ước hiển thị: công thức Toán trong stem, options và lời giải dùng LaTeX inline \\(...\\).\n'
    '\n\n\n\nClean context đã lọc từ tài liệu nguồn:\n{context}'
)


# ==== Stage 1: QuestionWriter — chỉ stem + answer + reasoning + verifier hint
WRITER_SYSTEM_PROMPT = (
    'Bạn là chuyên gia ra đề Toán. Nhiệm vụ: viết đề bài, đáp án đúng và giải '
    'thích. KHÔNG sinh distractor ở bước này — distractor sẽ được sinh riêng.'
)


WRITER_USER_PROMPT = (
    'Viết một câu hỏi Toán dạng trắc nghiệm theo yêu cầu (CHỈ stem + đáp án + giải thích).\n\n'
    'Chủ đề ngữ cảnh: {topic}\n'
    'Kỹ năng cần kiểm: {skill}\n'
    'Mức nhận thức: {cognitive_level} (mục tiêu khó {difficulty_target})\n'
    'Pattern gợi ý: {pattern}\n\n'
    'Clean context đã lọc từ tài liệu nguồn:\n{context}'
)


WRITER_OUTPUT_FORMAT = '''\
Trả về ĐÚNG định dạng (4 dòng trống giữa các phần lớn). Công thức/biểu thức Toán \
hiển thị phải dùng LaTeX inline, ví dụ \\(x^2+1\\), \\(\\frac{a}{b}\\), \\(\\sqrt{x}\\), \\(\\ln x\\). KHÔNG kèm danh sách phương án A/B/C/D.

Stem phải tự đầy đủ ngữ cảnh: nếu nhắc "Định lý 1", "Định lý 2", "Ví dụ 3" hoặc một ký hiệu theo số thứ tự, phải kèm tên/nội dung ngắn của định lý/khái niệm đó trong chính câu hỏi. Không hỏi kiểu "trường hợp nào" nếu người học cần nhìn lại tài liệu mới biết đối tượng đang nói đến là gì.

Question: <nội dung đề bài thuần — KHÔNG kèm phương án>




Answer explanation: <giải thích bám ngữ cảnh, KHÔNG in chain-of-thought nháp>




Answer: <đáp án đúng hiển thị bằng LaTeX inline nếu là công thức; verifier_payload mới dùng cú pháp máy đọc>




Source quote: <chép NGUYÊN VĂN 15–250 ký tự từ Ngữ cảnh làm chứng cứ; KHÔNG bọc dấu ngoặc kép>




Visual:
type: <none | truth_table | matrix | graph_network | tree | venn_diagram>
spec: <JSON một dòng; type=none thì spec={}>




Verifier hint:
type: <solve_equation | simplify_equiv | derivative | integral | limit |
       matrix_det | matrix_rank | matrix_eigenvalues | matrix_inverse | matrix_multiply |
       trig_identity | analytic_geometry | geometry_triangle |
       counting | probability | modular |
       logic_equivalence | logic_negation | truth_table |
       graph_property | tree_property | recurrence | numeric_eval | none>
payload: <JSON một dòng phù hợp type; type=none thì payload={}>

Ví dụ verifier hint cho Toán rời rạc:
- counting: {"formula": "binomial(13, 2)", "expected": 78}
- logic_equivalence: {"expr_a": "~(P >> Q)", "expr_b": "P & ~Q"}
- modular: {"operation": "mod_pow", "base": 2, "exp": 10, "mod": 7, "expected": 2}

Không thêm markdown/code fence.'''


# ==== Stage 2: Distractor — sinh 3 nhiễu gắn với misconception cụ thể
DISTRACTOR_SYSTEM_PROMPT = (
    'Bạn là tác nhân sinh distractor MCQ Toán. Tuân thủ skill '
    'distractor-generation được cung cấp trong prompt runtime.'
)


DISTRACTOR_USER_PROMPT = (
    'Sinh CHÍNH XÁC 3 distractor cho câu hỏi sau.\n\n'
    'Đề bài: {question}\n'
    'Đáp án ĐÚNG: {answer}\n'
    'Giải thích đáp án đúng: {explanation}\n\n'
    'Misconception khả dĩ:\n'
    '{misconceptions}\n\n'
    'Áp dụng đầy đủ skill distractor-generation được cung cấp ở runtime.'
)


DISTRACTOR_OUTPUT_FORMAT = '''\
Trả về ĐÚNG định dạng dưới (3 distractor, ngăn cách bằng dòng trống).
Text distractor phải CÙNG DẠNG với đáp án đúng: nếu answer là số thì distractor là số; nếu answer là biểu thức thì distractor là biểu thức; nếu answer là mệnh đề/cụm từ thì distractor là mệnh đề/cụm từ cùng kiểu.
Công thức/biểu thức Toán trong distractor text phải dùng LaTeX inline \\(...\\).

Distractor 1:
category: <id misconception đã chọn>
explanation: <vì sao distractor này sai — nêu cụ thể lỗi gì>
text: <nội dung distractor — dùng LaTeX inline nếu có công thức>

Distractor 2:
category: <id misconception khác>
explanation: <…>
text: <…>

Distractor 3:
category: <id misconception khác>
explanation: <…>
text: <…>

Không thêm markdown.'''


OUTPUT_FORMAT_INSTRUCTION = '''\
Trả về CHÍNH XÁC theo định dạng dưới đây (4 dòng trống giữa các phần lớn).

⚠ QUY TẮC BẮT BUỘC:
1. Question chỉ là đề bài thuần túy. KHÔNG liệt kê phương án A/B/C/D trong Question — phương án chỉ nằm trong Distractors.
2. Question, Answer, Distractor và Explanation (hiển thị cho học sinh): dùng LaTeX inline \\(...\\) cho mọi công thức/biểu thức Toán; ví dụ \\(x^2+1\\), \\(\\frac{a}{b}\\), \\(\\sqrt{x}\\), \\(\\binom{n}{k}\\), \\(\\int_a^b f(x)\\,dx\\).
3. Verifier hint payload là phần máy đọc: dùng cú pháp SymPy/JSON theo ví dụ, không cần LaTeX.
4. Biến trong logic dùng tên một chữ in hoa: P, Q, R.
5. Nếu câu hỏi là khái niệm/nhận định/tập hợp mà đáp án không kiểm được bằng SymPy/NetworkX, đặt Verifier hint type=none, payload={}. Không ép verifier cho câu khái niệm.

Question: <nội dung câu hỏi — KHÔNG có phương án A/B/C/D>




Answer explanation: <giải thích vì sao đáp án đúng — bám vào ngữ cảnh>




Answer: <đáp án đúng hiển thị; nếu là công thức dùng LaTeX inline \\(...\\). Dạng máy đọc đặt trong Verifier hint payload bên dưới>




Source quote: <chép NGUYÊN VĂN một câu/đoạn ngắn (15–250 ký tự) từ Ngữ cảnh ở trên làm chứng cứ. KHÔNG diễn đạt lại; KHÔNG bọc thêm dấu ngoặc kép; phải khớp ký tự với Ngữ cảnh.>




Visual:
type: <none | truth_table | matrix | graph_network | tree | venn_diagram>
spec: <JSON một dòng — xem ví dụ; nếu type=none thì spec={}>




Verifier hint:
type: <một trong: solve_equation | simplify_equiv | derivative | integral | limit |
       matrix_det | matrix_rank | matrix_eigenvalues | matrix_inverse | matrix_multiply |
       trig_identity | analytic_geometry | geometry_triangle |
       counting | probability | modular |
       logic_equivalence | logic_negation | truth_table |
       graph_property | tree_property | recurrence | numeric_eval | none>
payload: <JSON một dòng phù hợp với type — xem ví dụ>




Distractors:
Distractor category: <misconception id từ list 'Sai lầm thường gặp'; cố gắng phân loại, chỉ ghi null khi KHÔNG CÓ id nào khớp>
Distractor explanation: <vì sao phương án này sai — nêu cụ thể lỗi tính toán hay nhầm lẫn khái niệm gì>
Distractor: <nội dung phương án nhiễu — dùng LaTeX inline nếu có công thức, PHẢI sai về mặt toán>

Distractor category: <misconception id hoặc null>
Distractor explanation: <vì sao phương án này sai — nêu cụ thể>
Distractor: <nội dung phương án nhiễu>

Distractor category: <misconception id hoặc null>
Distractor explanation: <vì sao phương án này sai — nêu cụ thể>
Distractor: <nội dung phương án nhiễu>

Ví dụ payload theo type:
- derivative:
  {"function": "sin(x**2 + 1)", "variable": "x", "claimed_derivative": "2*x*cos(x**2 + 1)"}
- integral (xác định):
  {"function": "x*exp(x)", "variable": "x", "lower": 0, "upper": 1, "claimed_value": "1"}
- integral (bất định):
  {"function": "1/x", "variable": "x", "claimed_antiderivative": "log(x)"}
- limit:
  {"function": "sin(x)/x", "variable": "x", "point": 0, "claimed_value": 1}
- solve_equation:
  {"equation": "x**2 - 5*x + 6", "variable": "x", "claimed_roots": [2, 3]}
- simplify_equiv:
  {"expr_a": "(a+b)**2", "expr_b": "a**2 + 2*a*b + b**2"}
- matrix_det:
  {"matrix": [[1,2],[3,4]], "claimed": -2}
- matrix_eigenvalues:
  {"matrix": [[2,0],[0,3]], "claimed": [2, 3]}
- trig_identity:
  {"expr_a": "sin(x)**2 + cos(x)**2", "expr_b": "1"}
- counting (tổ hợp C(n,k)):
  {"formula": "binomial(10, 4)", "expected": 210}
- counting (chỉnh hợp P(n,k)):
  {"formula": "factorial(10)/factorial(10-4)", "expected": 5040}
- counting (hoán vị n!):
  {"formula": "factorial(5)", "expected": 120}
- counting (tổ hợp lặp):
  {"formula": "binomial(3+11-1, 11)", "expected": 78}
- modular:
  {"operation": "mod_pow", "base": 2, "exp": 6, "mod": 7, "expected": 1}
- logic_equivalence:
  {"expr_a": "~(P >> Q)", "expr_b": "P & ~Q"}
- graph_property:
  {"property": "edges_complete", "n": 5, "expected": 10}
- numeric_eval:
  {"expr": "sqrt(2) * sqrt(3)", "expected_numeric": 2.449489742783178, "tolerance": 1e-6}
- none: {}

QUY TẮC VISUAL:
- Nếu câu hỏi nhắc đến "bảng chân lý / hình / đồ thị / sơ đồ / ma trận đã cho" → BẮT BUỘC kèm Visual phù hợp.
- Nếu KHÔNG cần hình, đặt type=none và spec={}.

Ví dụ Visual spec:
- truth_table:
  {"variables": ["P","Q"], "expr_label": "P → Q",
   "rows": [{"P":true,"Q":true,"result":true},
            {"P":true,"Q":false,"result":false},
            {"P":false,"Q":true,"result":true},
            {"P":false,"Q":false,"result":true}]}
- matrix:
  {"name":"A", "rows":[[1,2,3],[4,5,6],[7,8,9]]}
- graph_network:
  {"directed": false, "vertices":["A","B","C","D"],
   "edges":[["A","B"],["B","C"],["C","D"],["D","A"]]}
- tree:
  {"root":"A", "edges":[["A","B"],["A","C"],["B","D"],["B","E"]]}
- venn_diagram:
  {"sets":[{"name":"A","elements":[1,2,3,4]},
           {"name":"B","elements":[3,4,5,6]}]}
- none:
  {}

Không thêm markdown, không bọc code fence.'''


# ==== PROMPT ENGINEERING ADDONS ====
# Các khối này được nối vào prompt sinh câu hỏi trước output format.
# Mục tiêu: role clarity, glossary grounding, one-shot format reference,
# internal chain-of-thought/self-review, nhưng không yêu cầu model in lý luận nháp.
PROMPT_ENGINEERING_GUIDE = '''\
KỸ THUẬT SINH CÂU HỎI:
- Role: hành xử như giảng viên Toán đang ra đề kiểm tra từ đúng tài liệu nguồn.
- Glossary use: ưu tiên dùng đúng thuật ngữ/ký hiệu trong glossary và ngữ cảnh; không tự đổi nghĩa thuật ngữ.
- One-shot use: tham khảo ví dụ format bên dưới, nhưng KHÔNG sao chép nội dung ví dụ.
- Internal reasoning: suy luận nháp trong đầu để kiểm tra đáp án và distractor, nhưng KHÔNG in chain-of-thought ra output.
- Self-review trước khi trả lời: tự kiểm tra format, tiếng Việt, ngữ pháp, grounding, và chỉ một đáp án đúng.
- LaTeX display: mọi công thức hiển thị cho học sinh dùng inline \\(...\\); không dùng plaintext kiểu sqrt(x), int_a^b, binomial(n,k) trong stem/options/explanation.
- Nếu ngữ cảnh không đủ thông tin để hỏi một phép tính cụ thể, hãy sinh câu hỏi khái niệm/nhận định bám sát quote.
'''


ONE_SHOT_FORMAT_EXAMPLE = '''\
ONE-SHOT FORMAT REFERENCE (chỉ minh họa cấu trúc, không sao chép nội dung):

Question: Theo quy tắc nhân trong tổ hợp, nếu bước thứ nhất có m cách chọn và bước thứ hai có n cách chọn độc lập, số cách thực hiện cả hai bước là bao nhiêu?




Answer explanation: Vì hai bước chọn độc lập nối tiếp nhau nên theo quy tắc nhân, tổng số cách bằng tích số cách của từng bước.




Answer: \\(m \\cdot n\\)




Source quote: Nếu một công việc được thực hiện qua hai bước, bước một có m cách và bước hai có n cách thì có m.n cách thực hiện công việc.




Visual:
type: none
spec: {}
alt_text:




Verifier hint:
type: none
payload: {}




Distractors:
Distractor category: add_when_multiply
Distractor explanation: Nhầm quy tắc nhân với quy tắc cộng.
Distractor: \\(m+n\\)

Distractor category: permutation_vs_combination
Distractor explanation: Nhầm bài toán đếm độc lập với chỉnh hợp.
Distractor: \\(P(m,n)\\)

Distractor category: off_by_one
Distractor explanation: Thêm một trường hợp không có trong quy tắc.
Distractor: \\(m \\cdot n+1\\)
'''


SELF_REVIEW_CRITERIA = '''\
SELF-REVIEW CRITERIA (kiểm tra nội bộ trước khi xuất):
1. Format đúng: đủ Question, Answer explanation, Answer, Source quote, Visual, Verifier hint, 3 Distractors.
2. Ngôn ngữ đúng tiếng Việt, rõ ràng, không lẫn markdown hoặc code fence; công thức hiển thị ở dạng LaTeX inline \\(...\\).
3. Ngữ pháp tự nhiên, không mơ hồ, không hỏi hai ý trong cùng một câu.
4. Liên quan trực tiếp đến ngữ cảnh; quote phải chép nguyên văn từ ngữ cảnh.
5. Có đúng một đáp án đúng và đúng ba distractor sai nhưng hợp lý theo misconception.
'''
