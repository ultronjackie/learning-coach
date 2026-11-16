# 状态接口、权威归属与迁移

通用技能在本仓库。学习者的档案在私人目录。可选的外部系统只提供信号，不自动成为第二份权威档案。本仓库不读取、不提交 `~/Self-Study`。

## 谁是唯一权威

每份课程档案只有一个 `authority`：

| `authority.role` | 何时使用 | 权威在哪 |
| --- | --- | --- |
| `local` | 默认 | 学习者指定的本地目录，否则是 `~/Self-Study`。规则见 [存储位置](storage.md) |
| `notion` | 学习者明确把该课程的权威改到 Notion | Notion 中由学习者指定的那一处页面或数据库 |

Notion 可以是团队的事实来源，但只有 `authority.role` 被写成 `notion` 之后才是。在此之前不创建 Notion 页，也不把本地文件同步上去。改成 Notion 之后，本地文件只是导出副本，不再平行维护另一份权威。两边不一致时，指出冲突，Notion 名下的字段以 Notion 为准，不取平均，不各记各的。

Canvas、JOJ、Git 只出现在 `signals` 里。它们不能变成 `authority`，也不能补全另一个系统的提交状态。不接这些系统也能上课。技能不保存令牌、页面 ID 或私人路径。

## v1 档案

```yaml
schema: learning-coach.state/v1
mode: self_study | formal_course
authority:
  role: local | notion
  store: filesystem | notion
course_id: 稳定 ID
policy: null | 见正式课程规则
sources: []
evidence_records: []
open_tasks: []
retests: []
signals:
  canvas: unknown
  joj: unknown
  git: unknown
preserved_sections: {}
```

`mode` 缺省是 `self_study`。`policy` 在自学迁移结果里是 `null`，不生成一条空的课程政策。证据对象的形状见 [证据记录](evidence.md)，schema 为 `learning-coach.evidence/v1`。

## 从 v0 迁移

v0 的 schema 名是 `learning-coach.state/v0`。它就是现在的 `STATE.md` / `ROADMAP.md` / `SESSIONS.md`，文件里没有 `schema: learning-coach.state/v1`。读取时：

- 不要求先改文件。缺 `模式` 就视为 `self_study`。
- 能力表里的五级原文保留，标成 `legacy_projection`。不用这些旧行去升一条新的独立完成或延迟保持；旧行没有未见迁移、帮助程度和带时区的时间戳。
- 自报却被写成辅助完成、独立完成或延迟保持时，保留原文并记下冲突，不默默改级，也不把它当成新的观察。
- 待答问题、待复测、阅读任务、两小时预算和无法识别的段落全部保留。`dropped_sections` 应为空。
- 不发明政策原文、页码或证据记录。`evidence_records` 从空列表开始，直到有新的观察。
- 权威写成唯一的 `local`，除非学习者当时已经明确指定 Notion。
- 继续上课并保存时，把 v1 字段加进去，不覆盖用户写的其他段落。

已经是 v1 的档案再次读取时，只保留一个 `authority`。输入里若同时列出多份权威，不原样保存成两份；已写明的 `notion` 或 `local` 留下那一个。正式课程里“已核实”但没有政策原文的，读入后改为未知，不能在下一次读取时变成已核实。已经核实的原文、`statement_present`，以及许可项里明确的允许或拒绝，再次读取后保持不变。来源记录保持原来的核实状态，未核实的页码不会变成可引用。提交信号按系统分开规范化。
