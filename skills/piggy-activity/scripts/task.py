#!/usr/bin/env python3
"""Local task files for 小猪在干嘛. Does not call an image service."""

import argparse
import hashlib
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def prepare(args):
    text = args.text_file.read_text(encoding="utf-8")
    prompt = args.prompt_file.read_text(encoding="utf-8")
    references = [p.expanduser().resolve() for p in args.reference]
    if not text.strip() or not prompt.strip():
        raise ValueError("原文和提示词不能为空。")
    for path in references:
        if not path.is_file() or path.suffix.lower() != ".png":
            raise ValueError("参考图必须是现有PNG文件：" + str(path))
    root = args.output_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    task = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:10])
    task.mkdir(mode=0o700)
    try:
        (task / "references").mkdir(mode=0o700)
        selected = []
        for index, source in enumerate(references, 1):
            target = task / "references" / (str(index).zfill(2) + "-" + source.name)
            shutil.copyfile(source, target)
            target.chmod(0o600)
            selected.append(str(target))
        for name, content in [("message.txt", text), ("prompt.txt", prompt)]:
            path = task / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
        manifest = task / "request.json"
        write_json(manifest, {
            "schema_version": 1, "status": "prepared", "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "references": selected, "prompt_file": str(task / "prompt.txt"),
            "output": str(task / "piggy.png"),
        })
    except Exception:
        shutil.rmtree(task)
        raise
    return {"status": "prepared", "request": str(manifest), "references": selected}


def save(args):
    manifest = args.request.expanduser().resolve()
    info = json.loads(manifest.read_text(encoding="utf-8"))
    if info.get("schema_version") != 1 or info.get("status") != "prepared":
        raise ValueError("任务必须处于prepared状态。")
    target = manifest.parent / "piggy.png"
    if info.get("output") != str(target):
        raise ValueError("输出路径与任务目录不一致。")
    source = args.image.expanduser().resolve()
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("图片超过50MiB。")
    data = source.read_bytes()
    if (len(data) < 45 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or data[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        raise ValueError("请选择生图工具返回的PNG原文件。")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height:
        raise ValueError("PNG尺寸无效。")
    handle = target.open("xb")
    temporary = manifest.with_name("request-" + uuid4().hex + ".tmp")
    try:
        with handle:
            target.chmod(0o600)
            handle.write(data)
        info.update({"status": "saved", "backend": "codex_builtin_image_gen",
                     "saved_at": datetime.now(timezone.utc).isoformat(),
                     "sha256": hashlib.sha256(data).hexdigest(),
                     "width": width, "height": height,
                     "text_verified_automatically": False})
        write_json(temporary, info)
        temporary.replace(manifest)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "saved", "image": str(target), "prompt_file": info["prompt_file"]}


def main():
    parser = argparse.ArgumentParser(description="准备小猪任务或保存内置生图结果；本脚本不生成图片。")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--text-file", type=Path, required=True)
    create.add_argument("--prompt-file", type=Path, required=True)
    create.add_argument("--reference", type=Path, action="append", required=True)
    create.add_argument("--output-dir", type=Path, default=Path("output/imagegen"))
    store = commands.add_parser("save")
    store.add_argument("--request", type=Path, required=True)
    store.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else save(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
