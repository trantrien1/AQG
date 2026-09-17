"""Tài liệu phải tới mô hình nguyên trang, không bị trích text sau lưng.

OpenRouter tự chọn engine xử lý PDF nếu ta không ghim: model nào nhận đầu vào
file thì đọc nguyên trang, model nào không thì tụt xuống ``pdf-text`` — tức
trích xuất text, phá bố cục/ký hiệu toán/bảng/hình. Việc đó xảy ra âm thầm: run
vẫn ra câu hỏi, không cổng nào phát hiện, và cơ chế bám tài liệu được mô tả
trong paper không còn là cái đã thực sự chạy.
"""
from __future__ import annotations

import pytest

from pipeline import config as cfg
from pipeline import llm_client as lc


@pytest.fixture(autouse=True)
def _clear_cache():
    lc._OPENROUTER_MODEL_CACHE.clear()
    yield
    lc._OPENROUTER_MODEL_CACHE.clear()


def _fake_modalities(monkeypatch, mapping):
    monkeypatch.setattr(lc, '_openrouter_model_modalities',
                        lambda model: mapping.get(model))


def test_model_without_file_modality_is_rejected(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    monkeypatch.setattr(cfg, 'OPENROUTER_REQUIRE_NATIVE_PDF', True)
    _fake_modalities(monkeypatch, {'qwen/qwen3-vl-32b-instruct': ['text', 'image']})
    with pytest.raises(lc.PdfNotNativeError) as exc:
        lc.assert_pdf_native_support('qwen/qwen3-vl-32b-instruct')
    assert 'TRÍCH XUẤT TEXT' in str(exc.value)


def test_model_with_file_modality_passes(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    _fake_modalities(monkeypatch, {'openai/gpt-4o': ['text', 'image', 'file']})
    info = lc.assert_pdf_native_support('openai/gpt-4o')
    assert info['document_handling'] == 'raw_pdf_native'
    assert info['pdf_engine'] == cfg.OPENROUTER_PDF_ENGINE


def test_opt_out_downgrades_to_warning_not_error(monkeypatch):
    """Tắt cưỡng chế thì vẫn phải GHI LẠI là tài liệu sẽ bị trích text."""
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    monkeypatch.setattr(cfg, 'OPENROUTER_REQUIRE_NATIVE_PDF', False)
    _fake_modalities(monkeypatch, {'m': ['text', 'image']})
    info = lc.assert_pdf_native_support('m')
    assert info['document_handling'] == 'would_fall_back_to_text_extraction'


def test_image_mode_does_not_need_the_file_modality(monkeypatch):
    """Chế độ ảnh không đi qua file-parser nên không cần modality file."""
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'image')
    _fake_modalities(monkeypatch, {'m': ['text', 'image']})
    assert lc.assert_pdf_native_support('m')['document_handling'] == 'page_images'


def test_image_mode_rejects_a_model_that_cannot_see(monkeypatch):
    """Model chỉ có text nhận message toàn ảnh sẽ KHÔNG thấy tài liệu.

    Nó vẫn trả về câu hỏi — bịa từ prompt — nên không cổng nào ở sau phát hiện.
    Đây là cùng một cái bẫy im lặng như tụt xuống trích text, chỉ khác đường.
    """
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'image')
    monkeypatch.setattr(cfg, 'OPENROUTER_REQUIRE_NATIVE_PDF', True)
    _fake_modalities(monkeypatch, {'text-only': ['text']})
    with pytest.raises(lc.PdfNotNativeError) as exc:
        lc.assert_pdf_native_support('text-only')
    assert 'ảnh' in str(exc.value)


def test_image_mode_opt_out_records_blindness(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'image')
    monkeypatch.setattr(cfg, 'OPENROUTER_REQUIRE_NATIVE_PDF', False)
    _fake_modalities(monkeypatch, {'text-only': ['text']})
    info = lc.assert_pdf_native_support('text-only')
    assert info['document_handling'] == 'blind_to_page_images'


def test_image_mode_unreachable_catalogue_does_not_block(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'image')
    _fake_modalities(monkeypatch, {})
    assert lc.assert_pdf_native_support('x')['document_handling'] == 'page_images'


def test_non_openrouter_provider_is_not_checked(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file_url')
    assert lc.assert_pdf_native_support('gpt-4o')['document_handling'] == 'raw_pdf'


def test_unreachable_catalogue_does_not_block_the_run(monkeypatch):
    """Không tra được danh mục thì chạy tiếp, nhưng phải ghi là CHƯA kiểm chứng."""
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    _fake_modalities(monkeypatch, {})           # trả None cho mọi model
    info = lc.assert_pdf_native_support('whatever')
    assert info['document_handling'] == 'raw_pdf_unverified'


def test_plugins_pin_the_engine_only_for_openrouter_file_mode(monkeypatch):
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openrouter')
    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    monkeypatch.setattr(cfg, 'OPENROUTER_PDF_ENGINE', 'native')
    body = lc._openrouter_extra_body()
    assert body == {'plugins': [{'id': 'file-parser',
                                 'pdf': {'engine': 'native'}}]}

    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'image')
    assert lc._openrouter_extra_body() == {}

    monkeypatch.setattr(cfg, 'PDF_ATTACH_MODE', 'file')
    monkeypatch.setattr(cfg, 'LLM_PROVIDER', 'openai_compatible')
    assert lc._openrouter_extra_body() == {}
