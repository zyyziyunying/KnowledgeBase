# Evidence 证据包

`knowledge/` 负责解释知识，`evidence/` 负责保存支撑关键结论的可追溯证据。证据包不能替代正文，也不在多个位置重复维护同一结论。

## 来源等级

按以下顺序选取能够直接支持结论的最窄来源：

1. **官方源码或规范**：优先固定 repository revision、文件路径与 SHA-256，并配置关键字符串断言。
2. **官方文档**：记录发布机构、最后更新时间、检索日期、许可与 URL；动态网页不使用内容哈希冒充固定快照。
3. **权威博客或技术演讲**：只用于补充设计动机、历史和实践经验。必须记录作者/机构、发布日期、适用版本、采用理由，并与事实和个人推断分开。
4. 普通社区文章只能作为线索，不能单独支撑系统模型中的关键结论。

“较新”不使用固定年限机械判断：必须记录发布日期或最后更新时间，并说明它覆盖的 Android/Flutter/组件版本。历史机制可以使用旧的一手资料，但要与当前实现证据配对。

## 证据包结构

```text
evidence/
├── schema/evidence-manifest.schema.json
└── <domain>/<topic>/<slug>/manifest.json
```

每个 manifest 至少包含：

- 正文路径和核对日期；
- 可稳定引用的 claim ID；
- claim 到 source 的映射；
- 官方源码的 revision、path、SHA-256、license 和 assertions；
- 官方文档或权威博客的作者/机构、日期、URL 与适用边界。

不批量复制网页或博客正文。确需保存本地附件、截图、trace、PDF 或小段源码时，放在对应证据包目录，记录来源、许可、生成方式和 SHA-256；无法确认再分发许可时只保存元数据和链接。

## 验证

离线检查 manifest 结构、claim/source 引用和正文路径：

```bash
python3 tools/verify_evidence.py
```

联网复核固定源码内容、SHA-256、关键断言和文档可访问性：

```bash
python3 tools/verify_evidence.py --online
```

联网校验只接受 HTTPS URL，并在每次重定向时重新检查；拒绝 IP 字面量形式的非公网地址以及解析到私网、回环、链路本地等地址的域名。为兼容本机代理，域名解析到 `198.18.0.0/15` Fake-IP 段时允许交给 HTTPS 代理继续处理，但直接使用该网段的 IP URL 仍会被拒绝。单个响应上限为 16 MiB。修改 schema 或校验器时运行其标准库回归测试：

```bash
python3 -m unittest discover -s tools -p 'test_*.py' -v
```

来源更新时应创建新的核对基线并重新计算哈希，不要直接把旧 revision 改成 `main`。当前样例是 [Android 启动证据包](android/framework/boot/manifest.json)。
