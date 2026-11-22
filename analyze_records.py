"""命令行入口：站点报告、家庭可见视图、教师下一步观察问题。

用法：
    python3 analyze_records.py data/records.json                 # 站点完整报告
    python3 analyze_records.py data/records.json --view teacher  # 教师观察问题
    python3 analyze_records.py data/records.json --view family --viewer 家庭芬
"""

import argparse
from pathlib import Path

from inspect_records import load_records
import speech_evidence as se


def main():
    parser = argparse.ArgumentParser(description="语言证据分析与下一次观察安排")
    parser.add_argument("path", type=Path, help="资料文件路径")
    parser.add_argument("--view", choices=["station", "family", "teacher"],
                        default="station", help="查看视角，默认站点完整报告")
    parser.add_argument("--viewer", help="家庭视图的查看人（须在授权名单中）")
    args = parser.parse_args()

    records = load_records(args.path)
    before = se.analyze(records, amend=False)
    after = se.analyze(records, amend=True)

    if args.view == "station":
        print(se.station_report(before, after))
    elif args.view == "teacher":
        for child, questions in after.questions.items():
            print(f"孩子 {child} 的下一次观察问题：")
            for question in questions:
                print(f"  - {question}")
    else:
        if not args.viewer:
            parser.error("--view family 需要同时给出 --viewer")
        print(se.family_view(after, args.viewer))


if __name__ == "__main__":
    main()
