#!/usr/bin/env python3
"""
辩论式研究 Agent - OpenClaw 主控集成

这个脚本实现了完整的自动运行流程：
1. 创建研究
2. 自动调用 sessions_spawn 运行 Researcher
3. 捕获结果
4. 自动调用 sessions_spawn 运行 Reviewer
5. 循环直到完成

用法：
    python3 run_debate.py "研究主题"

作者: winterswang
版本: 5.3.0
"""

import sys
import json
import subprocess
import time
from pathlib import Path

# 导入 orchestrator
sys.path.insert(0, str(Path(__file__).parent))
from debate_orchestrator import DebateOrchestrator, OUTPUT_BASE, CONFIG

# OpenClaw sessions_spawn 接口
def spawn_subagent(prompt: str, tools: list = None, timeout: int = 300) -> str:
    """
    调用 OpenClaw sessions_spawn 工具运行 subagent
    
    这个函数需要根据 OpenClaw 的实际接口实现
    当前是模拟版本
    """
    # 在实际 OpenClaw 环境中，应该使用 sessions_spawn 工具
    # 这里我们返回一个占位符，实际运行时会被 OpenClaw 主控替换
    
    print(f"\n{'='*60}")
    print(f"📤 SPAWN REQUEST")
    print(f"{'='*60}")
    print(f"Tools: {tools}")
    print(f"Timeout: {timeout}s")
    print(f"\nPrompt (first 500 chars):")
    print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
    print(f"{'='*60}\n")
    
    # 返回提示，让主控知道需要调用 sessions_spawn
    return {
        "need_spawn": True,
        "prompt": prompt,
        "tools": tools or ["web_search", "read", "write"],
        "timeout": timeout
    }


class DebateRunner:
    """
    辩论式研究 Runner
    
    职责：
    1. 接收研究主题
    2. 协调 Orchestrator 和 subagent
    3. 输出最终结果
    """
    
    def __init__(self, topic: str, output_dir: str = None):
        self.orchestrator = DebateOrchestrator(topic=topic, output_dir=output_dir)
        self.output_dir = self.orchestrator.output_dir
    
    def run(self) -> dict:
        """
        运行完整研究流程
        
        这个方法返回 SPAWN_REQUEST 或 COMPLETE
        在 OpenClaw 环境中，主控会自动处理 SPAWN_REQUEST
        """
        print(f"\n{'='*60}")
        print(f"🚀 开始辩论式研究")
        print(f"{'='*60}")
        print(f"主题: {self.orchestrator.state['topic']}")
        print(f"输出目录: {self.output_dir}")
        print(f"最大迭代: {CONFIG['max_iterations']}")
        print(f"满意阈值: {CONFIG['satisfaction_threshold']}")
        print(f"{'='*60}\n")
        
        while True:
            # 获取下一步请求
            request = self.orchestrator.get_spawn_request()
            
            if request["action"] == "COMPLETE":
                return self._finalize(request)
            
            if request["action"] == "SPAWN_REQUEST":
                # 返回 spawn 请求，让 OpenClaw 主控处理
                return self._format_spawn_request(request)
            
            if request["action"] == "AUTO_CONTINUE":
                # 继续循环
                print(f"⏳ {request.get('message', '继续...')}")
                continue
            
            # 未知 action
            return {"action": "ERROR", "message": f"未知 action: {request['action']}"}
    
    def submit_result(self, role: str, result: str) -> dict:
        """
        提交 subagent 结果并继续
        
        在 OpenClaw 环境中，主控调用此方法传递 subagent 输出
        """
        print(f"\n📥 收到 {role} 结果")
        
        # 提交结果
        self.orchestrator.submit_result(role, result)
        
        # 继续下一步
        return self.run()
    
    def _format_spawn_request(self, request: dict) -> dict:
        """格式化 spawn 请求供 OpenClaw 主控使用"""
        return {
            "action": "SPAWN_REQUEST",
            "role": request["role"],
            "prompt": request["prompt"],
            "tools": request.get("tools", ["web_search", "read", "write"]),
            "timeout": CONFIG["timeout_seconds"],
            "output_dir": str(self.output_dir),
            "instruction": f"""
请使用 sessions_spawn 工具调用 {request['role']} subagent。

**角色**: {request['role']}
**可用工具**: {', '.join(request.get('tools', []))}
**输出目录**: {self.output_dir}

完成后请调用:
```
python3 {Path(__file__).relative_to(Path.cwd())} --resume {self.output_dir} --action continue --role {request['role']} --result "<subagent输出>"
```
"""
        }
    
    def _finalize(self, request: dict) -> dict:
        """最终输出"""
        print(f"\n{'='*60}")
        print(f"✅ 研究完成")
        print(f"{'='*60}")
        print(f"原因: {request['reason']}")
        print(f"迭代轮次: {request['iterations']}")
        print(f"最终评分: {request['final_score']}/10")
        print(f"报告位置: {request['report_path']}")
        print(f"{'='*60}\n")
        
        return request


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="辩论式研究 Agent V5.3")
    parser.add_argument("topic", nargs="?", help="研究主题")
    parser.add_argument("--action", choices=["start", "continue", "status", "list"], 
                        default="start", help="执行动作")
    parser.add_argument("--resume", help="恢复研究目录")
    parser.add_argument("--role", choices=["researcher", "reviewer"], help="subagent 角色")
    parser.add_argument("--result", help="subagent 结果")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    
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
                        "phase": state.get("phase"),
                        "last_score": state.get("score_history", [None])[-1]
                    })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # status 动作
    if args.action == "status":
        if not args.resume:
            print("❌ 需要指定 --resume")
            return
        state_file = Path(args.resume) / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print("❌ 状态文件不存在")
        return
    
    # 确定输出目录
    output_dir = args.resume
    
    # start 动作
    if args.action == "start":
        if not args.topic and not output_dir:
            parser.error("需要提供 topic 或使用 --resume")
        
        runner = DebateRunner(topic=args.topic, output_dir=output_dir)
        result = runner.run()
    
    # continue 动作
    elif args.action == "continue":
        if not args.resume or not args.role:
            parser.error("continue 需要 --resume 和 --role")
        
        runner = DebateRunner(topic=None, output_dir=args.resume)
        
        if args.result:
            result = runner.submit_result(args.role, args.result)
        else:
            result = runner.run()
    
    else:
        result = {"error": "未知动作"}
    
    # 输出
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if "instruction" in result:
            print(result["instruction"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()