from dotenv import load_dotenv
import os
from functools import lru_cache

from langchain.chat_models import init_chat_model

load_dotenv(override=True)


# 惰性构造：import 期不再实例化模型。
# 否则 api.server -> agent.main_agent 的导入链会在此处执行，key 缺失/非法时整个后端起不来，
# 且报错点离真实原因（环境变量）很远。
@lru_cache(maxsize=1)
def get_model():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，请在 .env / docker/.env.docker 中填写")
    return init_chat_model(
        model=os.getenv("LLM_QWEN_PLUS"),
        model_provider="openai",
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL"),
    )
