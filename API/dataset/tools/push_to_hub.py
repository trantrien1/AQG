"""Đẩy dataset đã dựng lên Hugging Face Hub.

    set HF_TOKEN=hf_...            (hoặc truyền --token)
    python dataset/tools/push_to_hub.py --repo <user>/<tên-dataset>

Mặc định tạo repo RIÊNG TƯ. Chỉ thêm --public khi đã chắc chắn có quyền phát
hành nội dung tài liệu gốc.
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', required=True, help='vd trantrien1/vi-math12-integral-mcq')
    ap.add_argument('--export', default=str(HERE.parent / 'export'))
    ap.add_argument('--card', default=str(HERE.parent / 'README.md'))
    ap.add_argument('--token', default=os.environ.get('HF_TOKEN'))
    ap.add_argument('--public', action='store_true')
    args = ap.parse_args()
    if not args.token:
        raise SystemExit('Thiếu token: đặt biến HF_TOKEN hoặc truyền --token')

    from huggingface_hub import HfApi

    export = Path(args.export)
    if not (export / 'questions.jsonl').exists():
        raise SystemExit(f'Chưa có {export / "questions.jsonl"}: chạy build_dataset.py trước')

    api = HfApi(token=args.token)
    api.create_repo(args.repo, repo_type='dataset', private=not args.public,
                    exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copy(export / 'questions.jsonl', stage / 'questions.jsonl')
        shutil.copy(export / 'build_report.json', stage / 'build_report.json')
        shutil.copytree(export / 'images', stage / 'images')
        shutil.copy(args.card, stage / 'README.md')
        api.upload_folder(folder_path=str(stage), repo_id=args.repo,
                          repo_type='dataset',
                          commit_message='Upload dataset')
    visibility = 'công khai' if args.public else 'riêng tư'
    print(f'Đã đẩy lên https://huggingface.co/datasets/{args.repo} ({visibility})')


if __name__ == '__main__':
    main()
