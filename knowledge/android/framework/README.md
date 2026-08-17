# Android Framework

本专题聚焦 Android Framework 的系统模型、关键调用链、源码入口、验证方法与高频面试问题。

## 当前事实源

- [Android Framework 高频核心讲义](Android-Framework-%E9%AB%98%E9%A2%91%E6%A0%B8%E5%BF%83%E8%AE%B2%E4%B9%89.md)：Framework 主干与整体阅读入口，建议先读第 0–6 章，再读第 7–12 章，最后完成源码阅读与自测部分。
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：独立解释 Home 解析、Launcher/SystemUI APK、`system_server` 与 native UI 的边界；建议在讲义第 1 章后阅读。
- [Android 启动证据包](../../../evidence/android/framework/boot/manifest.json)：第 1 章关键结论的固定 AOSP revision、官方文档元数据、SHA-256 与可执行断言。
- [Home 与 SystemUI 证据包](../../../evidence/android/framework/home-system-ui/manifest.json)：Home/Launcher/SystemUI 独立文档的固定源码、SHA-256 与可执行断言。

当前采用选择性拆分：讲义继续维护 Framework 主干；已经需要独立阅读和验证的 Home/SystemUI 边界由独立文档维护，讲义只保留启动链概览和入口。新增内容应先判断事实归属，避免在讲义与独立文档重复维护同一结论。

## 未来拆分入口

除已独立维护的 Home/SystemUI 边界外，当讲义其他部分开始妨碍独立维护或交叉引用时，可按以下主题群继续拆分，并由本页维护最终阅读顺序：

1. 启动其余阶段、进程与组件调度；
2. Binder、AIDL 与跨进程通信；
3. 主线程、生命周期与进程优先级；
4. 渲染、输入与 ANR；
5. 包管理、权限与 SELinux；
6. System Service、源码阅读与练习。

这些其余主题群仍只是候选边界，不是已经存在的事实源。真正拆分时应移动正文、补齐互链，并确保每个结论只有一个维护位置。
