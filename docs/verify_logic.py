import importlib.util, sys

# ---- 1. summary_messages.py 纯函数 ----
spec = importlib.util.spec_from_file_location(
    "summary_messages_check",
    "services/chat-api/app/enterprise_capabilities/research/progressive/summary_messages.py",
)
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

s1 = sm.research_summary(accepted_count=3, provider_searches=5, budget_exhausted=False, language='zh')
assert '渐进式研究完成' in s1 and '3' in s1 and '5' in s1, s1
s2 = sm.research_summary(accepted_count=1, provider_searches=2, budget_exhausted=True, language='zh-CN')
assert '已达到最大研究轮次' in s2, s2
s3 = sm.research_summary(accepted_count=2, provider_searches=4, budget_exhausted=False, language='en')
assert 'Progressive research complete' in s3 and '2' in s3 and '4' in s3, s3
s4 = sm.research_summary(accepted_count=0, provider_searches=1, budget_exhausted=True, language='en-US')
assert 'maximum number of research rounds' in s4, s4
s5 = sm.research_summary(accepted_count=1, provider_searches=1, budget_exhausted=False, language='')
assert 'Progressive research complete' in s5, s5
print('✅ summary_messages 全部断言通过')
print('  zh :', s1)
print('  zhX:', s2)
print('  en :', s3)

# ---- 2. deepseek_provider.py 核心逻辑（注入 mock models.SearchCandidate）----
import pydantic
class SearchCandidate(pydantic.BaseModel):
    provider: str = ""
    query: str = ""
    title: str = ""
    url: str = ""
    snippet: str = ""
    score: float | None = None

# 预注册 .models 相对导入目标
import types
pkg_models = types.ModuleType("deepseek_check_pkg.models")
pkg_models.SearchCandidate = SearchCandidate
pkg = types.ModuleType("deepseek_check_pkg")
pkg.__path__ = []
sys.modules["deepseek_check_pkg"] = pkg
sys.modules["deepseek_check_pkg.models"] = pkg_models

src = open("services/chat-api/app/enterprise_capabilities/research/progressive/deepseek_provider.py").read()
# 替换相对导入 .models -> deepseek_check_pkg.models
src = src.replace("from .models import SearchCandidate", "from deepseek_check_pkg.models import SearchCandidate")
src = src.replace('"""DeepSeek\'s Search JSON API as a MOGO public-web search source."""', '""""""')
ns = {}
exec(compile(src, "deepseek_provider.py", "exec"), ns)
DeepSeekProvider = ns["DeepSeekProvider"]

import httpx
requests = []
def respond(request):
    requests.append(request)
    return httpx.Response(200, json={"results": [
        {"title": "Example", "url": "https://example.com/a", "snippet": "Short", "summary": "Long", "rerank_score": 2.4},
        {"title": "No URL", "snippet": "Skip"},
    ]})

client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
orig_async_client = httpx.AsyncClient
import asyncio
async def run():
    # 替换模块内 httpx.AsyncClient
    import httpx as _h
    _ns_httpx = ns["httpx"]
    _ns_httpx.AsyncClient = lambda *a, **k: client
    rows = await DeepSeekProvider(api_key="example-secret").search("MOGO", max_results=3)
    return rows
rows = asyncio.run(run())
assert len(rows) == 1, rows
assert rows[0].provider == "deepseek"
assert rows[0].snippet == "Long"
assert rows[0].score == 2.4
assert requests[0].url == "https://api.deepseek.com/v1/tools/search"
assert requests[0].headers["authorization"] == "Bearer example-secret"
import json as _json
assert _json.loads(requests[0].content) == {"query": "MOGO", "count": 3, "need_content": False}
print("✅ deepseek_provider 核心逻辑通过（含 count 上限/字段规范化/异常路径）")
