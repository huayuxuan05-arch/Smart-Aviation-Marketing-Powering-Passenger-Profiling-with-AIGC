# RAG知识库组织

此目录保存知识结构约定，当前未建立向量索引，也未接入生成模型。

知识类型为destination、route_product、holiday和marketing_policy。每条记录登记document_id、chunk_id、source_url、发布及有效日期、主题、地域、用途、版本和审核状态。公开事实引用现有台账，原文及许可不清的图片不直接上传。

实现时先准备小型人工核验问答集，做关键词检索基线，再比较向量与混合检索；检索结果进入事实卡后才能生成内容。知识不足、过期和冲突均需返回明确状态。完整规则见[RAG设计](../docs/aigc.md)。
