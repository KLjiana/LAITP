"""测试用工作进程：输出非协议行后退出。"""

print("this is not a protocol message")
raise SystemExit(0)
