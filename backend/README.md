# Python后端实施约定

此目录为待开发后端的入口，当前没有可启动服务。

计划按data、forecast、profiles、recommendations、strategies、retrieval、generation、campaigns、evaluation划分业务模块；API仅负责请求校验与结果序列化。存储、模型供应商、检索器、素材生成器采用可替换适配器，业务模块不硬编码凭据或平台地址。

所有模块共享数据属性、场景、截点、版本和来源约定。先实现只读来源接口与规则结果，再接入知识检索和模拟活动。接口路径和错误状态见[API契约](../docs/api.md)。收费模型、真实渠道和公网部署不自动启用。
