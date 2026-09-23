# Requirements Quality Checklist: 002 session-versioning

**Purpose**: 校验 002（会话级版本化/交接/多人协同）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 "commit/快照"的触发方式是否穷举（手动 commit + 自动触发，自动触发条件 spec 是否完整）？
- [ ] CHK002 "resume 续写"是否定义续写起点语义（从哪个快照恢复，恢复后消息 seq 如何续编）？
- [ ] CHK003 "share 交接"是否定义交接后的权限转移（交接者是否失去/保留访问，接手者如何获得）？
- [ ] CHK004 "co-presence 多人协同"是否定义并发写冲突的完整语义（先到者为准，落后者如何同步，是否需拉取合并）？

## 清晰度（Clarity）

- [ ] CHK005 秘密过滤（commit/log/share 视图 0 明文）的"秘密"判定是否定义（clarify 已定熵 ≥3.5 + 前缀双判定，FR 正文是否同步该判据）？
- [ ] CHK006 "快照存储"（clarify 独立 session_snapshots）FR 正文是否声明存储模型（还是正文只写"快照"而无结构）？
- [ ] CHK007 "交接/解引用可审计"（Success Criteria）的审计字段是否枚举（谁/何时/引用了什么，FR 是否覆盖）？
- [ ] CHK008 多人会话"解引用操作 100% 可审计追溯"——"解引用"的精确定义（share 链接失效？资源解除？）是否清晰？

## 一致性（Consistency）

- [ ] CHK009 与 001（gatekeeper）"审计与授权复用 001 落点/权限码"（Notes）——001 的审计六层是否覆盖会话交接事件（001 审计的是工具调用，会话交接是否需 001 扩展）？
- [ ] CHK010 与 009（hooks-interception）"会话生命周期事件"（SessionStart/SessionEnd/MemoryCommit）——002 的快照/交接事件是否经 009 钩子，两个 spec 是否双向声明？
- [ ] CHK011 与 011（dream-cycle）"会话沉淀经验"（011 FR 把会话变经验）——002 的快照是否作为 011 经验源，两 spec 是否对齐？
- [ ] CHK012 与 005（knowledge-rag）"知识分享 vs 会话交接"边界（005 CHK013 提过）——002 share 是会话，005 是知识，二者是否明确区分？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK013 快照含大附件/二进制（doc/图片）时的存储边界（clarify 独立 session_snapshots 是否含附件，附件如何存）？
- [ ] CHK014 并发续写"以先到者为准"（FR）在高并发下的 seq 冲突检测是否定义（clarify 用 MongoDB 乐观锁，spec 是否声明冲突处理）？
- [ ] CHK015 share 链接失效后的行为（过期/被取消后访问者看到什么）是否定义？
- [ ] CHK016 多人会话中部分成员离线时的 co-presence 状态（离线成员的贡献是否保留）是否清晰？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- 与 001/009/011/005 的跨特性事件/存储对齐（CHK009–CHK012）建议在 clarify 或审阅时统一消解。
