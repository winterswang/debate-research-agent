#!/usr/bin/env python3
"""
辩论式研究 V5.6.0 Wrapper

这是主入口，返回 SPAWN_SUBAGENT 请求让主 Agent 执行。

主 Agent 需要做的：
1. 收到 SPAWN_SUBAGENT 请求
2. 调用 sessions_spawn(
       task=prompt,
       runtime="subagent",
       agentId=agent_id,
       model=model,
       timeoutSeconds=timeout_seconds
   )
3. 收到 subagent 结果
4. 调用本脚本 --action submit_result --role <role> --result <result>
5. 收到下一个 SPAWN_SUBAGENT 请求或 COMPLETE

用法：
    # 开始新研究
    python3 run_debate_v560.py "研究主题"
    
    # 提交结果（由主 Agent 自动调用）
    python3 run_debate_v560.py --resume <output_dir> --action submit_result --role researcher --result "..."
"""

import sys
import json
import argparse
from pathlib import Path

# 添加当前目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from debate_runner_v560 import DebateRunnerV560, OUTPUT_BASE


def main():
    parser = argparse.ArgumentParser(description="辩论式研究 V5.6.0 - Session 隔离版")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--resume", help="恢复研究目录")
    parser.add_argument("--action", choices=["start", "submit_result", "list"],
                        default="start", help="执行动作")
    parser.add_argument("--role", choices=["researcher", "reviewer"], help="结果角色")
    parser.add_argument("--result", help="subagent 结果")
    parser.add_argument("--session-id", help="subagent session ID")
    parser.add_argument("--json", action="store_true", default=True, help="输出 JSON（默认启用）")
    
    args = parser.parse_args()
    
    # list 动作
    if args.action == "list":
        result = {"action": "LIST", "researches": []}
        if OUTPUT_BASE.exists():
            for d in sorted(OUTPUT_BASE.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and (d / "state.json").exists():
                    state = json.loads((d / "state.json").read_text())
                    result["researches"].append({
                        "path": str(d),
                        "topic": state.get("topic"),
                        "iteration": state.get("iteration"),
                        "phase": state.get("phase")
                    })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # 确定输出目录
    output_dir = args.resume
    
    # 创建 Runner
    if not output_dir and not args.topic:
        parser.error("需要提供 topic 或使用 --resume")
    
    runner = DebateRunnerV560(topic=args.topic, output_dir=output_dir)
    
    # 执行动作
    if args.action == "start":
        result = runner.run()
    elif args.action == "submit_result":
        if not args.role or args.result is None:
            parser.error("submit_result 需要 --role 和 --result")
        result = runner.submit_spawn_result(args.role, args.result, args.session_id)
    else:
        result = {"error": "未知动作"}
    
    # 输出 JSON（主 Agent 解析）
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()