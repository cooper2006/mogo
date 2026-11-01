import sys
sys.path.insert(0, 'services/chat-api')
from app.enterprise_capabilities.research.progressive.summary_messages import research_summary

# zh 正常
s1 = research_summary(accepted_count=3, provider_searches=5, budget_exhausted=False, language='zh')
assert '渐进式研究完成' in s1 and '3' in s1 and '5' in s1, s1
# zh budget_exhausted
s2 = research_summary(accepted_count=1, provider_searches=2, budget_exhausted=True, language='zh-CN')
assert '已达到最大研究轮次' in s2, s2
# en
s3 = research_summary(accepted_count=2, provider_searches=4, budget_exhausted=False, language='en')
assert 'Progressive research complete' in s3 and '2' in s3 and '4' in s3, s3
# en budget_exhausted
s4 = research_summary(accepted_count=0, provider_searches=1, budget_exhausted=True, language='en-US')
assert 'maximum number of research rounds' in s4, s4
# 默认 zh（空 language）
s5 = research_summary(accepted_count=1, provider_searches=1, budget_exhausted=False, language='')
assert '渐进式研究完成' in s5, s5
print('✅ summary_messages 全部断言通过')
print('  zh  :', s1)
print('  zhX :', s2)
print('  en  :', s3)
