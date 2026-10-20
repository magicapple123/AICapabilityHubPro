# AICapabilityHub Pro · Python微服务模板

本模板提供配置、Result/异常、日志、服务发现、内部调用和独立数据库会话。它不是新的AI能力，也不会因注册服务就自动获得adapter、计量或前端入口。

扩展遵循[Pro开发指南](../../AICapabilityHubPro-开发指南.md)与[共享契约](../../docs/api-contract/pro-shared.md)。现有四服务已经有业务，不要用模板覆盖重建。

## 新模块接入

1. 在独立分支明确职责/负责人/服务名/数据库及接口契约。
2. 新服务使用独立venv和库，配置来自环境，不复制他人.env或真实密钥。
3. API→Service→Repository→Model/Schema单向职责，入口只装配，repository不控制跨服务事务。
4. Nacos注册实际可达host而非0.0.0.0；服务发现基于固定服务名，常规调用经call_internal /internal/**，不跨库。
5. 统一code/message/data/requestId，记录追踪但不打印凭据/输入；当前用户、状态和管理员授权均有明确检查。
6. 如需新增可执行code，交付受控adapter、内联Schema、目录价和拒绝模型前的负例；不执行任意URL。
7. 通过独立DB、网关、真实链和Review后交付，不能仅以import/health当业务完成。

## 运行与配置

已有服务使用根init_dev.py及start_pro_local.py，推荐Pro端口3307/8849/9849/8859。新模板自行配置服务名/端口/DB_URL并按其requirements安装；不要用示例root:root覆盖现有配置。

模型地址/Key/Mock和配置热更新只以本模板实际提供的字段为准，不表示所有未来执行器或配置都已实现。JWT签发、目录、计费应通过明确的领域接口接入，不复制其他服务数据库连接。

## 验证和交接

使用[契约模板](../../docs/api-contract/_template.md)，写已实现/待交接、权限、幂等、错误、兼容/迁移和测试。不删除旧数据或靠seed迁移。文案使用AICapabilityHub Pro，不更改既有兼容标识；历史搭建流程在归档中，不作为当前指令。
