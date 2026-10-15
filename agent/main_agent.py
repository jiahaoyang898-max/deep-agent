# [核心] 智能体组装与执行逻辑
import shutil
from functools import lru_cache
from pathlib import Path

from deepagents import create_deep_agent

from agent.llm import get_model
from agent.load_prompts import main_agent_config
from agent.sub_agents.rag_sub_agent import rag_sub_agent
from agent.sub_agents.db_sub_agent import db_sub_agent
from agent.sub_agents.network_search_agent import internet_sub_agent
from api.context import set_thread_context, set_session_context, reset_session_context
from api.monitor import monitor
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content
from utils.logger_utils import logger


# 惰性构建 + 进程内缓存：每次请求重建会丢会话状态且更慢，模型异常也要留到这里才报得准
@lru_cache(maxsize=1)
def get_main_agent():
    logger.info("初始化主智能体（首次调用时构建）")
    return create_deep_agent(
        model=get_model(),
        system_prompt=main_agent_config['system_prompt'],
        subagents=[rag_sub_agent, db_sub_agent, internet_sub_agent],
        tools=[read_file_content, generate_markdown, convert_md_to_pdf]
    )


def _root_cause(exc: BaseException) -> BaseException:
    """顺着 __cause__ / __context__ 找到最内层的真实根因（外层常只是包装）。"""
    root = exc
    seen = {id(exc)}
    while True:
        nxt = getattr(root, "__cause__", None) or getattr(root, "__context__", None)
        if not isinstance(nxt, BaseException) or id(nxt) in seen:
            return root
        seen.add(id(nxt))
        root = nxt


def describe_agent_failure(exc: BaseException) -> str:
    """把异常翻译成「类型 + 可读原因 + 针对性指引」，用于回传前端展示。"""
    root = _root_cause(exc)
    name = type(root).__name__
    text = str(root)
    lowered = text.lower()
    status = getattr(root, "status_code", None) or getattr(root, "code", None)

    if status == 401 or status == 403 or "invalid api-key" in lowered or "api key" in lowered \
            or name in ("AuthenticationError", "PermissionDeniedError"):
        reason = "模型 API Key 无效或已过期（401/403）"
        guide = "请更新 docker/.env.docker 中的 DASHSCOPE_API_KEY，然后执行 docker compose up -d backend 重启后端"
    elif status == 429 or "rate limit" in lowered or "insufficient" in lowered:
        reason = "模型服务限流或额度不足（429）"
        guide = "请检查阿里云百炼账户额度/限流，稍后重试"
    elif "ssl" in lowered or "certificate" in lowered:
        reason = "模型服务 SSL/HTTPS 证书校验失败"
        guide = "请检查网络代理与证书配置（常见于本地代理拦截 HTTPS）"
    elif "timeout" in lowered or "timed out" in lowered or name in ("APITimeoutError", "TimeoutError"):
        reason = "模型服务连接超时"
        guide = "请确认 DASHSCOPE_BASE_URL 可访问、本机代理/网络通畅"
    elif "connection" in lowered or "connect" in lowered or name in ("APIConnectionError", "ConnectionError"):
        reason = "无法连接模型服务"
        guide = "请检查 DASHSCOPE_BASE_URL 与网络/代理设置"
    elif status == 400 or name == "BadRequestError" or "context" in lowered and "length" in lowered:
        reason = "模型请求被拒绝（参数或上下文长度问题）"
        guide = "请缩短提问或减少上传文件后重试"
    else:
        reason = text or name
        guide = "请把本条时间与后端日志中的完整堆栈发给维护者"

    return f"智能体执行失败：{name}｜原因：{reason}｜指引：{guide}"


def _report_agent_process(chunk, thread_id: str):
    for key, value in chunk.items():
        if not value or "messages" not in value: continue
        message = value["messages"][-1]
        if key == "model":
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    # 区分子智能体和工具
                    if tool_call["name"] == "task":
                        monitor.report_assistant(tool_call['args']['subagent_type'], tool_call['args']['description'],
                                                 thread_id=thread_id)
                    else:
                        monitor.report_tool(tool_call['name'], tool_call['args'], thread_id=thread_id)
            elif message.content:
                monitor.report_task_result(message.content, thread_id=thread_id)


async def run_deep_agent(query: str, thread_id: str):
    # 在调用agent之前，保存thread_id, session_dir_str
    # 保存thread_id
    thread_token = set_thread_context(thread_id)
    # 生成session_dir_str， 再保存session_dir_str，, 并向前端发送session_dir_str
    project_dir = Path(__file__).parents[1].resolve()  # 项目根目录
    session_dir = project_dir / "output" / f"session_{thread_id}"  # 拼接生成sesion目录path对象
    session_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
    session_dir_str = str(session_dir).replace("\\", "/")  # 生成完整路径字符串
    session_token = set_session_context(session_dir_str)  # 保存session_dir_str
    monitor.report_session_dir(session_dir_str, thread_id=thread_id)  # 告诉前端当前会话的输出目录, 浏览器才能在右侧显示会话文件列表

    # 将upload中的文件拷贝到session目录中
    upload_dir = project_dir / "upload" / f"session_{thread_id}"
    uploaded_info = ''  # 关于要优先读取上传的文件的提示词
    if upload_dir.exists():
        # 得到所有文件的列表
        file_names = [item.name for item in upload_dir.iterdir() if item.is_file()]
        for name in file_names:
            shutil.copy2(upload_dir / name, session_dir / name)
        uploaded_info = (f"\n    [已上传文件] 已加载到工作目录:\n" +
                         "\n".join([f"    - {f}" for f in file_names]) +
                         "\n    请优先使用工具读取并参考这些文件。")

    # 得到工作区目录的相对路径
    relative_session_dir_str = str(session_dir.relative_to(project_dir)).replace("\\", "/")
    path_instruction = f"""
            【工作环境指令】
            工作目录: {relative_session_dir_str}

            {uploaded_info}

            规则：
            1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}'
            2. 读取已上传的文件时，请直接将文件名（例如：'开篇.txt'）作为 filename 参数传入（read_file_content）读取工具，不要带上任何目录前缀。
            3. 使用相对路径，禁止使用绝对路径
            4. 若存在上传文件，请先分析内容
            """

    try:
        # 执行agent,遍历过程数据，并将特定数据信息发送给前端
        result = get_main_agent().astream({
            "messages": [{
                "role": "user",
                "content": f"问题：{query}, 补充描述: {path_instruction}"
            }]
        })
        async for chunk in result:
            # 遍历每个chunk,向前端发送当前状态及数据
            _report_agent_process(chunk, thread_id)
    except Exception as e:
        # 堆栈进日志留细节，可读原因回传前端（否则用户只能看到无信息量的兜底文案）
        logger.exception(f"智能体执行失败 thread_id={thread_id}")
        monitor.report_error(describe_agent_failure(e), thread_id=thread_id)
    finally:  # 最终都要重置保存的thread_id和session_dir
        reset_session_context(session_token, thread_token)

if __name__ == "__main__":
    # =====================================================================
    # 本地冒烟测试入口：python -m agent.main_agent "你的测试问题"
    # 不启动 FastAPI，直接在当前进程运行主智能体，进度输出到控制台
    # =====================================================================
    import asyncio
    import builtins
    import sys
    import time
    import uuid

    # 1) 挂载"假运行时"，让 monitor 的进度事件打印到控制台
    #    （monitor._emit 检测到 builtins.runtime.stream_writer 就会调用它，
    #      这正是 deepagents 脚本模式的机制，无需 WebSocket）
    class _ConsoleRuntime:
        def __init__(self):
            self.stream_writer = lambda payload: print(
                f"  [monitor] {payload['event']:>14} | {payload['message']}"
            )

    builtins.runtime = _ConsoleRuntime()

    # 2) 测试问题：优先取命令行参数，否则用内置示例
    query = (sys.argv[1] if len(sys.argv) > 1
             else "请使用数据库查询助手查询库存最少的10种药品，列出药品名称、库存数量和规格，生成一份库存预警清单Markdown文件")
    thread_id = f"local_test_{uuid.uuid4().hex[:8]}"  # 随机线程号，避免污染正式会话

    print("=" * 60)
    print(f"测试问题 : {query}")
    print(f"线程 ID  : {thread_id}")
    print("=" * 60)

    # 3) 执行主智能体（内部会创建 output/session_<thread_id> 目录）
    start = time.perf_counter()
    asyncio.run(run_deep_agent(query=query, thread_id=thread_id))
    elapsed = time.perf_counter() - start

    # 4) 结束提示
    print("=" * 60)
    print(f"执行结束，耗时 {elapsed:.1f}s")
    print(f"输出目录: output/session_{thread_id}")
    print("=" * 60)
# 基于网络搜索到的沃华医药信息，生成一份调研报告：先创建Markdown文件，再转换为PDF
# 综合使用网络搜索助手和数据库查询助手，分析沃华医药主力产品与市场表现，生成完整分析报告PDF