# AICapabilityHub Pro 实施任务区

本目录只保存已确认升级方案的执行记录和三位成员的任务槽位。三位成员负责的业务代码暂不代写；领取任务后，在对应文件中补充分支、PR、实现路径、测试结果和剩余风险。

## 使用顺序

1. 先阅读 `docs/项目计划书.md`，确认 P0、P1 和不做范围。
2. 再阅读 `docs/升级实施看板.md`，认领对应成员任务。
3. 接口字段、错误码、权限、幂等或数据库结构发生变化时，先更新 `docs/api-contract/`，再改实现。
4. 每个任务必须留下可复现的测试命令和结果；“代码已写”不作为完成证据。
5. 跨成员依赖必须在任务文件和 PR 中写明调用方、被调用方、兼容方案和恢复方式。

## 成员任务槽位

- `member-黄岑果.md`：Gateway、ai-chat、Chat、E2E 与发布。
- `member-黄禹菲.md`：user、billing、API Key、积分与 Settings。
- `member-夏思凯.md`：capability、市场、运营和 Schema。

## 公共任务已由项目侧完成的部分

- Pro 工作区和 `develop` 基线建立。
- 新 GitHub 仓库 `magicapple123/AICapabilityHubPro` 的 `main` 与 `develop` 基线分支已建立；CI 工作流在两个分支均成功运行。
- 原项目 GitHub 中的 5 个远程分支全部保留；此次迁移未删除或覆盖原仓库分支。
- 原项目只读来源配置，避免将升级提交推回原项目。
- 旧项目基线测试和工具链检查。
- 任务看板、验收矩阵、风险记录和质量门禁脚本。
- GitHub Actions 质量门禁工作流骨架。

公共质量门禁不会替代成员对自己服务、契约、SQL 和页面的实现责任。

## D1 需要组长核实的 GitHub 设置

- 新仓库当前有 `main` 和 `develop` 两个分支，默认分支为 `main`。
- 添加其余成员协作者后，配置 PR Review、必需 CI 检查和禁止直接推送的 branch protection。成员 GitHub 登录名尚未提供，暂不能代为邀请。
- `CONTRIBUTING.md` 说明 `main` 受保护；GitHub 仓库目前尚未配置该保护规则。由黄岑果在成员加入后配置并验证。
