# Android Framework

本专题聚焦 Android Framework 的系统模型、关键调用链、源码入口、验证方法与高频面试问题。

## 当前事实源

- [Android Framework 高频核心讲义](Android-Framework-%E9%AB%98%E9%A2%91%E6%A0%B8%E5%BF%83%E8%AE%B2%E4%B9%89.md)：Framework 主干与整体阅读入口，建议先读第 0–6 章，再读第 7–12 章，最后完成源码阅读与自测部分。
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：独立解释 Home 解析、Launcher/SystemUI APK、`system_server` 与 native UI 的边界；建议在讲义第 1 章后阅读。
- [系统应用更新与 OTA](%E7%B3%BB%E7%BB%9F%E5%BA%94%E7%94%A8%E6%9B%B4%E6%96%B0%E4%B8%8EOTA.md)：系统 APK 的 data override、staged 安装与 OTA 通道，以及 Home 角色在更新中的解析与进程切换；建议在讲义第 10–11 章后阅读。
- [系统应用更新与 OTA 证据包](../../../evidence/android/framework/system-app-update/manifest.json)：更新机制文档的固定源码、SHA-256 与可执行断言。
- [系统更新UI与Home无缝切换](%E7%B3%BB%E7%BB%9F%E6%9B%B4%E6%96%B0UI%E4%B8%8EHome%E6%97%A0%E7%BC%9D%E5%88%87%E6%8D%A2.md)：bootanim 退场链、Windows 式更新屏对应物、无黑屏换 Home 的方案矩阵与回滚兜底；建议在系统应用更新与 OTA 文档后阅读。
- [系统更新UI与Home无缝切换证据包](../../../evidence/android/framework/update-ui/manifest.json)：更新UI文档的固定源码、SHA-256 与可执行断言。
- [Android 启动证据包](../../../evidence/android/framework/boot/manifest.json)：第 1 章关键结论的固定 AOSP revision、官方文档元数据、SHA-256 与可执行断言。
- [Home 与 SystemUI 证据包](../../../evidence/android/framework/home-system-ui/manifest.json)：Home/Launcher/SystemUI 独立文档的固定源码、SHA-256 与可执行断言。

当前采用选择性拆分：讲义继续维护 Framework 主干；已经需要独立阅读和验证的主题（Home/SystemUI 边界、系统应用更新、更新UI）由独立文档维护，讲义只保留对应章节的概览和入口。新增内容应先判断事实归属，避免在讲义与独立文档重复维护同一结论。

## 未来拆分入口

除已独立维护的 Home/SystemUI 边界外，当讲义其他部分开始妨碍独立维护或交叉引用时，可按以下主题群继续拆分，并由本页维护最终阅读顺序：

1. 启动其余阶段、进程与组件调度；
2. Binder、AIDL 与跨进程通信；
3. 主线程、生命周期与进程优先级；
4. 渲染、输入与 ANR；
5. 包管理、权限与 SELinux；
6. System Service、源码阅读与练习。

这些其余主题群仍只是候选边界，不是已经存在的事实源。真正拆分时应移动正文、补齐互链，并确保每个结论只有一个维护位置。其中第 5 组（包管理、权限与 SELinux）将来建设时应引用「系统应用更新与 OTA」文档，第 4 组（渲染、输入与 ANR）应引用「系统更新UI与Home无缝切换」文档的 bootanim 退场链（也对应建设路线第二阶段「图形与显示链路」），均不重复其结论。
