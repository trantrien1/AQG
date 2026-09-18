import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks'))

from mcqft import data, infer, metrics, prompts, report  # noqa: E402


def _item(i, topic='Tích phân', level='Vận dụng', question=None, solution='Ta có $x=1$.',
          choices=None, answer='B'):
    return {'id': f'q{i:03d}', 'topic': topic, 'subtopic': 'Tích phân từng phần',
            'section': 'DẠNG 2: TÍCH PHÂN HÀM MŨ', 'difficulty': level,
            'question': question or f'Tính $\\int_0^{i} x^{i}\\sin(x)\\,dx$ với tham số {i}.',
            'choices': choices or [f'A. ${i}$', f'B. ${i + 1}$', f'C. ${i + 2}$', f'D. ${i + 3}$'],
            'answer': answer, 'solution': solution, 'usable': True}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def test_same_problem_with_different_wording_is_grouped():
    a = _item(1, question='Bạn Minh đi máy bay với vận tốc $v(t)=3t^{2}+5$. Tính quãng đường.',
              choices=['A. $246$ m', 'B. $252$ m', 'C. $1134$ m', 'D. $966$ m'])
    b = _item(2, question='Bạn An ngồi máy bay, biết $v\\left(t \\right)=3t^{2}+5$. Quãng đường là',
              choices=['A. $36$ m', 'B. $252$ m', 'C. $1134$ m', 'D. $966$ m'])
    c = _item(3, question='Tính diện tích hình phẳng giới hạn bởi $y=x^{2}$ và $y=2x$.',
              choices=['A. $1$', 'B. $2$', 'C. $3$', 'D. $4$'])
    groups = data.near_duplicate_groups([a, b, c])
    assert sorted(map(sorted, groups)) == [[0, 1], [2]]


def _distinct(i, **kw):
    rng = random.Random(i)
    expr = ''.join(rng.choice('abcdefghkmnpqrstuvwxyz') + rng.choice('+-*/^')
                   for _ in range(12))
    return _item(i, question=f'Bài {i}: tính ${expr}$.',
                 choices=[f'{k}. ${i * 1000 + j}$' for j, k in enumerate('ABCD')], **kw)


def test_split_is_deterministic_grouped_and_close_to_80_5_15():
    items = [_distinct(i, level=data.LEVELS[i % 4]) for i in range(200)]
    items.append(_item(500, question=items[0]['question'], choices=items[0]['choices']))
    s1 = data.split_items(items)
    s2 = data.split_items(list(items))
    assert s1 == s2
    assert s1['q000'] == s1['q500']
    counts = {k: list(s1.values()).count(k) for k in ('train', 'val', 'test')}
    assert abs(counts['test'] - 30) <= 3 and abs(counts['val'] - 10) <= 2


def test_load_items_requires_difficulty(tmp_path):
    path = tmp_path / 'q.jsonl'
    bad = _item(1, level=None)
    data.write_jsonl(str(path), [bad, dict(_item(2), usable=False)])
    with pytest.raises(ValueError):
        data.load_items(str(path))


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def test_clean_section():
    assert prompts.clean_section('DẠNG 2: ÁP DỤNG TRỰC TIẾP BẢNG NGUYÊN HÀM') == \
        'Áp dụng trực tiếp bảng nguyên hàm'
    assert prompts.clean_section('PHƯƠNG PHÁP') == ''
    assert prompts.clean_section('DẠNG 3') == ''
    assert prompts.clean_section(None) == ''


def test_gen_target_round_trips_through_parser():
    it = _item(7, solution='Đặt $u=x$ thì $\\frac{1}{2}$.\nVậy chọn đúng.')
    rec, errors = metrics.parse_generated(prompts.gen_target(it))
    assert errors == []
    assert rec['question'] == it['question']
    assert rec['choices'] == it['choices']
    assert rec['solution'] == it['solution']
    assert rec['answer'] == 'B'


def test_build_examples_skips_items_without_solution():
    items = [_item(1), _item(2, solution='  ')]
    ex = prompts.build_examples(items, ['gen', 'solve'])
    assert [(e['id'], e['task']) for e in ex] == [('q001', 'gen'), ('q001', 'solve')]
    assert ex[1]['target'].endswith('Đáp án: B')


def test_shuffled_copy_keeps_the_correct_option():
    it = _item(3, answer='C')
    cp = prompts.shuffled_copy(it, random.Random(0))
    old = prompts.strip_letter(it['choices'][2])
    new = cp['choices'][prompts.LETTERS.index(cp['answer'])]
    assert prompts.strip_letter(new) == old
    assert cp['choices'] != it['choices']


def test_shuffle_refused_when_options_refer_to_each_other():
    it = _item(4, choices=['A. $1$', 'B. $2$', 'C. Cả A và B', 'D. $0$'])
    assert prompts.shuffled_copy(it, random.Random(0)) is None
    it = _item(5, solution='Loại phương án A vì ...')
    assert prompts.shuffled_copy(it, random.Random(0)) is None


def test_few_shot_prefers_same_subtopic_and_excludes_self():
    pool = [_item(i) for i in range(5)] + [dict(_item(9), subtopic='Khác')]
    shots = prompts.pick_shots(pool[0], pool, 3, seed=1)
    assert len(shots) == 3
    assert all(s['id'] != 'q000' and s['subtopic'] == pool[0]['subtopic'] for s in shots)
    msgs = prompts.gen_messages(pool[0], shots)
    assert [m['role'] for m in msgs] == ['system'] + ['user', 'assistant'] * 3 + ['user']


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_parse_generated_reports_format_errors():
    text = ('<think>\n\n</think>\n\n### Đề bài\nTính $x$.\n### Phương án\nA. $1\nB. 2\nC. 2\n'
            '### Lời giải\nTa có.\n### Đáp án\n**E**')
    rec, errors = metrics.parse_generated(text)
    assert 'bad_choices' in errors and 'bad_answer' in errors
    text = ('### Đề bài\nTính $x$.\n### Phương án\nA. $1\nB. 2\nC. 2\nD. 3\n'
            '### Lời giải\nTa có.\n### Đáp án\n**D**')
    rec, errors = metrics.parse_generated(text)
    assert rec['answer'] == 'D'
    assert set(errors) == {'duplicate_choices', 'unbalanced_math_choices'}


@pytest.mark.parametrize('text,expected', [
    ('... vậy $I=2$.\n\nĐáp án: C', 'C'),
    ('Đáp án đúng là **B**.', 'B'),
    ('Chọn A. Sau khi xét lại, Đáp án: D', 'D'),
    ('Chọn đáp án B', 'B'),
    ('Không rõ', None),
])
def test_extract_answer(text, expected):
    assert metrics.extract_answer(text) == expected


def test_novelty_index_finds_the_copied_item():
    train = [_item(i) for i in range(10)]
    idx = metrics.NoveltyIndex(train)
    sim, best = idx.nearest(train[4])
    assert best == 'q004' and sim == pytest.approx(1.0)


def test_statistics():
    lo, hi = metrics.wilson(50, 100)
    assert lo < 0.5 < hi
    bs = metrics.paired_bootstrap([0, 0, 1, 1] * 10, [1, 1, 1, 1] * 10, iters=500)
    assert bs['diff'] == pytest.approx(0.5) and bs['lo'] > 0
    mc = metrics.mcnemar_exact([True] * 5 + [False] * 10, [True] * 5 + [True] * 10)
    assert mc['only_b'] == 10 and mc['p'] < 0.01


# ---------------------------------------------------------------------------
# infer / report (không cần GPU)
# ---------------------------------------------------------------------------

def test_parse_systems():
    assert infer.parse_systems('base,base_fs3,lora', True) == [
        ('base', 0, False), ('base_fs3', 3, False), ('lora', 0, True)]
    assert infer.parse_systems('base,lora', False) == [('base', 0, False)]
    with pytest.raises(ValueError):
        infer.parse_systems('big', False)


class _FakeTokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kw):
        return '|'.join(m['content'][:20] for m in messages) + '|ASSISTANT'


class _FakeLLM:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeLLM.calls.append(kwargs)

    def get_tokenizer(self):
        return _FakeTokenizer()

    def generate(self, prompts, sp, lora_request=None):
        from types import SimpleNamespace as NS
        # tác vụ gen lấy nhiều mẫu (n > 1); giải thì greedy một mẫu
        text = prompts_mod_target() if sp.n > 1 else 'Lời giải...\nĐáp án: B'
        return [NS(outputs=[NS(text=text, token_ids=[1, 2, 3], finish_reason='stop')
                            for _ in range(sp.n)])
                for _ in prompts]


def prompts_mod_target():
    return prompts.gen_target(_item(777, question='Câu mới về $\\ln(x^2+4)$ hoàn toàn khác.'))


@pytest.fixture
def fake_vllm(monkeypatch):
    import types
    from types import SimpleNamespace as NS
    mod = types.ModuleType('vllm')
    mod.LLM = _FakeLLM
    mod.SamplingParams = lambda **kw: NS(n=kw.get('n', 1), **{k: v for k, v in kw.items() if k != 'n'})
    lora = types.ModuleType('vllm.lora')
    req = types.ModuleType('vllm.lora.request')
    req.LoRARequest = lambda *a: ('lora', a)
    monkeypatch.setitem(sys.modules, 'vllm', mod)
    monkeypatch.setitem(sys.modules, 'vllm.lora', lora)
    monkeypatch.setitem(sys.modules, 'vllm.lora.request', req)
    _FakeLLM.calls.clear()
    return _FakeLLM


def test_infer_and_judge_plumbing_with_fake_vllm(tmp_path, monkeypatch, fake_vllm):
    from mcqft import judge
    train = [_distinct(i) for i in range(5)]
    test = [_distinct(100 + i) for i in range(3)]
    ddir = tmp_path / 'data'
    ddir.mkdir()
    _write_data_dir(ddir, train + test, {**{t['id']: 'train' for t in train},
                                         **{t['id']: 'test' for t in test}})
    adapter = tmp_path / 'adapter'
    adapter.mkdir()
    (adapter / 'adapter_config.json').write_text('{"r": 32}', encoding='utf-8')
    preds = tmp_path / 'preds'
    monkeypatch.setattr(sys, 'argv', ['infer', '--model', 'm', '--data', str(ddir),
                                      '--adapter', str(adapter), '--out', str(preds)])
    infer.main()
    assert fake_vllm.calls[-1]['enable_lora'] and fake_vllm.calls[-1]['max_lora_rank'] == 32
    names = sorted(p.name for p in preds.iterdir())
    assert names == ['base.gen.jsonl', 'base.gen_ctx.jsonl', 'base.solve.jsonl',
                     'base_fs3.gen.jsonl', 'infer_summary.json', 'lora.gen.jsonl',
                     'lora.gen_ctx.jsonl', 'lora.solve.jsonl']
    assert len(data.read_jsonl(str(preds / 'lora.gen.jsonl'))) == 6   # 3 câu x 2 mẫu

    out = tmp_path / 'judge'
    monkeypatch.setattr(sys, 'argv', ['judge', '--data', str(ddir), '--preds', f'A={preds}',
                                      '--out', str(out)])
    judge.main()
    rows = data.read_jsonl(str(out / 'judge.jsonl'))
    gen_outputs = sum(len(data.read_jsonl(str(p))) for p in preds.glob('*.gen*.jsonl'))
    assert len(rows) == 3 + gen_outputs    # câu test thật + mọi câu sinh ra
    assert all(r['pred'] == 'B' for r in rows)
    assert json.loads((out / 'judge_meta.json').read_text())['real_accuracy'] == 1.0


def test_majority_vote_ties_are_undecided():
    from mcqft.judge import majority
    assert majority(['A', 'A', 'B']) == 'A'
    assert majority(['A', 'B', None]) is None
    assert majority([None]) is None


def _write_data_dir(root, items, split):
    data.write_jsonl(str(root / 'items.jsonl'), items)
    (root / 'split.json').write_text(json.dumps({'split': split}), encoding='utf-8')


def test_report_end_to_end_without_gpu(tmp_path, monkeypatch):
    train = [_item(i) for i in range(6)]
    test = [_item(100 + i, question=f'Tìm nguyên hàm của $e^{{{i}x}}\\cos x$ bằng từng phần.')
            for i in range(4)]
    split = {**{t['id']: 'train' for t in train}, **{t['id']: 'test' for t in test}}
    ddir = tmp_path / 'data'
    ddir.mkdir()
    _write_data_dir(ddir, train + test, split)

    exp = tmp_path / 'exp'
    (exp / 'preds').mkdir(parents=True)
    fresh = prompts.gen_target(_item(900, question='Một câu hoàn toàn mới về $\\ln(x^2+1)$ nhé.'))
    copied = prompts.gen_target(train[0])
    gen_rows = [
        {'id': test[0]['id'], 'sample': 0, 'text': fresh, 'output_tokens': 50, 'finish_reason': 'stop'},
        {'id': test[1]['id'], 'sample': 0, 'text': copied, 'output_tokens': 50, 'finish_reason': 'stop'},
        {'id': test[2]['id'], 'sample': 0, 'text': 'lan man', 'output_tokens': 5, 'finish_reason': 'length'},
        {'id': test[3]['id'], 'sample': 0, 'text': fresh, 'output_tokens': 50, 'finish_reason': 'stop'},
    ]
    data.write_jsonl(str(exp / 'preds' / 'lora.gen.jsonl'), gen_rows)
    solve_rows = [{'id': t['id'], 'sample': 0, 'text': f'Đáp án: {x}', 'output_tokens': 3}
                  for t, x in zip(test, 'BBAB')]
    data.write_jsonl(str(exp / 'preds' / 'lora.solve.jsonl'), solve_rows)

    judge = tmp_path / 'judge'
    judge.mkdir()
    data.write_jsonl(str(judge / 'judge.jsonl'), [
        {'key': f"A/lora.gen/{test[0]['id']}/0", 'pred': 'B', 'key_answer': 'B'},
        {'key': f"A/lora.gen/{test[1]['id']}/0", 'pred': 'B', 'key_answer': 'B'},
        {'key': f"A/lora.gen/{test[3]['id']}/0", 'pred': 'C', 'key_answer': 'B'},
        {'key': f"real/{test[0]['id']}", 'pred': 'B', 'key_answer': 'B'},
    ])
    out = tmp_path / 'report'
    monkeypatch.setattr(sys, 'argv', ['report', '--data', str(ddir), '--exp', f'A={exp}',
                                      '--judge', str(judge), '--out', str(out)])
    report.main()
    res = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    g = res['gen']['A.lora.gen']
    assert g['format_valid'] == pytest.approx(0.75)
    assert g['judge_agree_of_valid'] == pytest.approx(2 / 3)
    assert g['near_copy_rate'] == pytest.approx(1 / 3)
    assert g['usable_rate'] == pytest.approx(0.25)   # chỉ câu mới + giám khảo khớp
    assert g['truncated'] == pytest.approx(0.25)
    assert res['solve']['A.lora.solve']['accuracy'] == pytest.approx(0.75)
