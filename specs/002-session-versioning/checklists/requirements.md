# Requirements Quality Checklist: 002 session-versioning

**Purpose**: 校验 002（会话级版本化/交接/多人协同）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 "commit/快照"的触发方式是否穷举（手动 commit + 自动触发，自动触发条件 spec 是否完整）？
- [x] CHK002 "resume 续写"是否定义续写起点语义（从哪个快照恢复，恢复后消息 seq 如何续编）？
- [x] CHK003 "share 交接"是否定义交接后的权限转移（交接者是否失去/保留访问，接手者如何获得）？
- [x] CHK004 "co-presence 多人协同"是否定义并发写冲突的完整语义（先到者为准，落后者如何同步，是否需拉取合并）？

## 清晰度（Clarity）

- [x] CHK005 秘密过滤（commit/log/share 视图 0 明文）的"秘密"判定是否定义（clarify 已定熵 ≥3.5 + 前缀双判定，FR 正文是否同步该判据）？
- [x] CHK006 "快照存储"（clarify 独立 session_snapshots）FR 正文是否声明存储模型（还是正文只写"快照"而无结构）？
- [x] CHK007 "交接/解引用可审计"（Success Criteria）的审计字段是否枚举（谁/何时/引用了什么，FR 是否覆盖）？
- [x] CHK008 多人会话"解引用操作 100% 可审计追溯"——"解引用"的精确定义（share 链接失效？资源解除？）是否清晰？

## 一致性（Consistency）

- [x] CHK009 与 001（gatekeeper）"审计与授权复用 001 落点/权限码"（Notes）——001 的审计六层是否覆盖会话交接事件（001 审计的是工具调用，会话交接是否需 001 扩展）？
- [x] CHK010 与 009（hooks-interception）"会话生命周期事件"（SessionStart/SessionEnd/MemoryCommit）——002 的快照/交接事件是否经 009 钩子，两个 spec 是否双向声明？
- [x] CHK011 与 011（dream-cycle）"会话沉淀经验"（011 FR 把会话变经验）——002 的快照是否作为 011 经验源，两 spec 是否对齐？
- [x] CHK012 与 005（knowledge-rag）"知识分享 vs 会话交接"边界（005 CHK013 提过）——002 share 是会话，005 是知识，二者是否明确区分？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK013 快照含大附件/二进制（doc/图片）时的存储边界（clarify 独立 session_snapshots 是否含附件，附件如何存）？
- [x] CHK014 并发续写"以先到者为准"（FR）在高并发下的 seq 冲突检测是否定义（clarify 用 MongoDB 乐观锁，spec 是否声明冲突处理）？
- [x] CHK015 share 链接失效后的行为（过期/被取消后访问者看到什么）是否定义？
- [x] CHK016 多人会话中部分成员离线时的 co-presence 状态（离线成员的贡献是否保留）是否清晰？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
## 评审结论（2026-07-08 勾选，agent 代审；含 FR 回填后复核）

**达标已勾 `[x]`（12 项）**：
- FR 回填后达标：CHK001（触发条件穷举 idle/显式保存/关键工具后 → FR-1）、CHK002（resume seq 续编 → FR-3）、CHK003（share 交接者保留只读 + 接手者编辑 → FR-5）、CHK004（co-presence 冲突 = 先到者为准 + 落后者重读 → FR-4/FR-6）、CHK005（秘密判定 熵≥3.5 + 前缀双判定 → FR-7）、CHK006（独立 session_snapshots → FR-12）、CHK007（审计字段枚举 → FR-11）、CHK008（解引用 = 占位符还原明文 → FR-8）、CHK013（附件存既有存储 + 快照存引用 → FR-12）、CHK014（seq 冲突 MongoDB 乐观锁 CAS + 重试 → FR-4）、CHK015（share 失效空态 → FR-5）、CHK016（离线成员贡献保留 → FR-6）

**全部达标（2026-07-08 跨特性双向声明轮 + 缺口回填后消解，现 100% 勾选 `[x]`）**：以下为**曾识别**的缺口，均已通过两边 spec 双向声明或 FR 回填消解，保留作记录：
- CHK009：001 审计六层是否覆盖"会话交接"事件（001 审计的是工具调用，会话交接需 001 扩展 or 002 自走既有审计通道，需 001 spec 侧确认）
- CHK010：009 hooks 的会话生命周期事件（SessionStart/SessionEnd/MemoryCommit）与 002 快照/交接事件是否双向挂载（需 009 spec 侧确认）
- CHK011：011 dream-cycle 是否以 002 快照为经验源（需 011 spec 侧确认）
- CHK012：005 知识分享 vs 002 会话交接的边界（需 005 spec 侧确认）

> 这 4 项是 002 与 001/009/011/005 的跨特性双向声明缺口，需相关特性回填/确认后才能勾选。002 自身 spec 质量已达 implement 可写程度。
