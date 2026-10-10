"""Command-line entry point for one-shot or interactive tutoring."""

import argparse
from pathlib import Path
import sys

from .agent import MathTutor, TutorError
from .prompts import MODES
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数学图片与文字辅导（Gemini）")
    parser.add_argument("text", nargs="?", default="", help="题目或问题")
    parser.add_argument("--image", type=Path, help="本地 PNG/JPEG/WebP 图片")
    parser.add_argument("--mode", choices=MODES, default="hint", help="hint 提示 / solve 解答 / check 检查 / read 识题")
    parser.add_argument("--grade", type=int, choices=range(1, 7), help="小学年级")
    parser.add_argument("--model", help="Gemini 模型名称；默认读取 GEMINI_MODEL")
    parser.add_argument("--chat", action="store_true", help="开启多轮对话")
    parser.add_argument("--analyze", action="store_true", help="输出知识点及关联解题步骤的 JSON")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="配置文件，默认当前目录 .env")
    args = parser.parse_args(argv)
    if args.analyze and (args.chat or args.mode != "hint"):
        parser.error("--analyze 是独立结构化分析，不能与 --chat 或其他 --mode 合用。")
    if not args.text.strip() and args.image is None and not args.chat:
        parser.error("请提供文字、--image，或使用 --chat。")
    try:
        overrides = {key: value for key, value in {"model": args.model, "grade": args.grade}.items() if value is not None}
        settings = Settings(_env_file=args.env_file, **overrides)
        with MathTutor(settings=settings) as tutor:
            if args.text.strip() or args.image:
                if args.analyze:
                    print(tutor.analyze_problem(args.text, image=args.image).model_dump_json(indent=2))
                else:
                    print(tutor.chat(args.text, image=args.image, mode=args.mode))
            if args.chat:
                print("输入问题继续；/reset 清除上下文，/quit 退出。")
                while True:
                    try:
                        text = input("你：").strip()
                    except EOFError:
                        break
                    if text == "/quit":
                        break
                    if text == "/reset":
                        tutor.reset()
                        print("已清除上下文。")
                    elif text:
                        try:
                            print("老师：" + tutor.chat(text, mode=args.mode))
                        except (TutorError, ValueError, OSError) as exc:
                            print(f"错误：{exc}", file=sys.stderr)
        return 0
    except (TutorError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
