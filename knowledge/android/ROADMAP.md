# Android 知识建设路线

更新日期：2026-08-14

本文件是 Android 领域建设顺序与延期项的事实源。领域索引只链接本文件，不复制当前计划。

## 当前目标

先建立能支持跨层开发、源码阅读和问题定位的 Android 系统模型。现有 Framework 高频核心讲义作为第一份基础材料保留；后续内容是否拆分，以独立维护和交叉引用的实际需要为准。

## 建设顺序

### 第一阶段：Framework 主干

- 启动、进程、Zygote 与 SystemServer；
- Binder、AIDL、ServiceManager 与 System Service；
- Activity、Window、主线程消息循环与生命周期；
- ANR、进程优先级与系统诊断入口。

第一阶段优先复核并完善现有讲义，不创建表达相同内容的平行文档。

### 第二阶段：图形与显示链路

- View traversal、Choreographer 与 VSync；
- Surface、BufferQueue 与图形缓冲区生命周期；
- WMS、SurfaceFlinger、HWC 与显示设备；
- 帧时间线、卡顿、内存和图形问题的验证方法。

这一阶段将成为 Android 与未来 Flutter Engine、Android Embedding、Skia、Impeller 知识之间的系统侧连接点。

### 第三阶段：Runtime、安全与工程诊断

- ART、类加载、GC、JNI 与 native 边界；
- PackageManager、权限、签名、System API 与 SELinux；
- `adb`、`dumpsys`、logcat、Perfetto 和 bugreport 的证据边界；
- Android 版本和厂商差异的记录方法。

## 暂缓内容

Flutter Framework、Engine、Embedding、Skia 与 Impeller 目前只保留领域入口，不进入本阶段的内容建设。开始建设时，应在 Flutter 领域建立自己的路线和专题事实源。

## 下一步

对现有 Android Framework 核心讲义做一次内容审计：检查主题缺口、版本边界、来源质量和可验证性，再决定优先补充内容还是拆分文档。
