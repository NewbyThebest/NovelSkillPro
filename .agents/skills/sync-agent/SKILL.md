---
name: sync-agent
description: 以 `.agents/skills/` 为唯一源头，将技能镜像同步到 `.claude/skills/` 和 `.codebuddy/skills/`。用于“同步技能”“同步到 Claude”“同步到 CodeBuddy”“检查镜像是否一致”。
---

# 同步智能体

`.agents/skills/` 是唯一源头，`.claude/skills/` 和 `.codebuddy/skills/` 是镜像。所有技能修改只改 `.agents/skills/`，不要直接改镜像目录，否则下次同步会覆盖。

项目文本规则统一维护在仓库根目录的 `AGENTS.md`，不再使用或同步任何 `rules/` 目录。

本技能只同步技能目录；`.DS_Store`、`__pycache__/`、`*.pyc` 等本机缓存不属于镜像范围。

## 执行流程

1. 切到项目根目录（能看到 `.agents/` 和 `.git/`）。
2. 先执行预览，不写入：

   ```bash
   python .agents/skills/sync-agent/scripts/sync.py
   ```

3. 根据预览汇总说明会新增、更新和删除哪些镜像文件。预览无改动即结束。
4. 只有用户明确要求同步或确认预览结果后，才执行：

   ```bash
   python .agents/skills/sync-agent/scripts/sync.py --apply
   ```

5. 应用后再次执行预览；仅当显示“无改动，已一致”才报告同步完成。

## 同步规则

- 同步范围：`.agents/skills/` → `.claude/skills/`、`.codebuddy/skills/`。
- 真镜像：源头新增→[新增]，改动→[更新]，源头已删→[删除]。
- 不为镜像目录保留专属技能文件。确有共享之外的本机配置时，放在同步范围之外。
