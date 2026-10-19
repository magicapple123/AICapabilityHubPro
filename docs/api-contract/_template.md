# AICapabilityHub Pro 接口契约：服务名

负责人：姓名；服务名 example-service；数据库 example_db；当前实现提交/日期：待填写。

## 实现状态

明确列出已实现接口、待实现约定和所需依赖，不把客户端、Gateway白名单或静态页面等同服务端完成。当前规范见 [Pro 开发指南](../../AICapabilityHubPro-开发指南.md)和[共享契约](pro-shared.md)。

## METHOD /api/domain/resource

- 当前状态：已实现并验收 / 已实现待联调 / 新增约定待实现。
- 请求方与身份：是否需JWT，管理是否实时授权，资源归属如何核对。
- 路径/查询/JSON请求体：字段、类型、必填、范围、默认、未知字段行为。
- 成功data：明确字段及敏感字段排除；外层统一code/message/data/requestId。
- 业务/HTTP错误：逐项写实际状态与code，不能复用已有不同含义的错误码。
- 幂等与事务：键、冲突字段、本地与远端提交边界、重试/对账。
- 兼容与迁移：旧调用方、旧数据、增量脚本及恢复。
- 测试：正常、越权、参数、状态变更、依赖故障、隔离数据库和真实链。

```json
{"code":0,"message":"success","data":{},"requestId":"same-id"}
```

## METHOD /internal/domain/resource

只由可信服务经call_internal调用，不对浏览器开放；列出链路身份与目标用户一致性、授权失败关闭及固定发现路径，不跨库。不增加任意URL代理。

## 证据与交接

列出提交、PR、测试/CI编号和报告；待实现端点写提供方与调用方。历史基线、Mock、HTTP替身与真实供应商验收分开，skipped不算DB通过，Review例外不等同人工审批。
