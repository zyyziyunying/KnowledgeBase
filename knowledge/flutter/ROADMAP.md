# Flutter 知识建设路线

更新日期：2026-09-04

本文件是 Flutter 领域的建设顺序、延期主题和完成标准的事实源。领域索引只提供入口，不复制这里的可变计划。

## 当前目标

当前优先级是“线程模型与性能同步”：先确认 native thread、task runner、Dart isolate、VSync、UI→raster 管线和 Platform View 动态合并的真实关系，再解释任一交互的耗时。

在上述前提确认后，再建立 Android 设备上 Flutter 交互性能的跨层模型：一次触摸怎样进入 Flutter、何时成为手势回调、路由状态何时改变、何时产生并光栅化首帧，以及 Flutter 计时的边界在哪里。目标是让“点了按钮、下个页面晚出现”成为可分段验证的问题，而不是把所有等待都归因于 `Navigator`。

## 建设顺序

### 第零阶段：线程模型与性能同步（当前优先）

- [线程模型与性能同步](engine/线程模型与性能同步.md)：native thread、task runner、Dart isolate 的边界；默认 Android platform/UI 合并；同 runner 直接执行；VSync；UI→raster 背压；Platform View 条件性 raster/platform 合并；
- 固定当前 Engine revision，并记录默认 Settings、AndroidShellHolder、DartIsolate、Shell、Animator、Rasterizer 与 AndroidExternalViewEmbedder 的可执行源码断言；
- 建立 trace 拓扑卡：runner 与 native thread 的映射、Platform View 状态、动态 merger 是否激活，以及输入到呈现的端点定义；
- 将“同 runner 串行”“跨 runner 投递”“帧节拍”“管线背压”“动态合并”作为五种独立的等待类别。

本阶段完成标准是：阅读者能在优化前先确认当前运行时拓扑，区分默认 platform/UI 合并和 Platform View 的 raster/platform 动态合并，并为每个延迟空洞提出可观测的等待关系。

### 第一阶段：输入到首帧（在线程模型之后）

- [Android 输入到 Flutter 路由首帧](engine/Android-输入到路由首帧.md)：Android 输入分发、Android Embedding、JNI、UI/raster task runner、手势竞技场、Navigator、VSync、渲染和系统合成的边界；
- 固定 Flutter Framework 与 Engine 源码 revision，并用 evidence claim 记录关键调用；
- 建立能把 Flutter Timeline / `FrameTiming` 与 Android 系统 trace 对齐的诊断方法；
- 明确“框架已完成一帧”“raster 已完成”“屏幕已呈现”三个不同观测点。

本阶段完成标准是：阅读者能给一次导航延迟设置测量点并定位到输入、UI、raster 或 Android 显示侧之一；不以某个具体应用或设备的测试结果作为通用结论。

### 第二阶段：Android Embedding 与运行时

- `embedding/android/`：`FlutterActivity` / `FlutterFragment`、`FlutterView`、Engine 生命周期、Surface、JNI 和插件边界；
- `engine/`：Dart isolate、任务队列、平台消息、GC 与调度可观测性；
- 记录多 Engine、Platform View、后台 isolate 等场景如何改变第一阶段的默认链路。

### 第三阶段：渲染与 Android 图形栈

- `rendering/`：Layer tree、Scene、rasterizer、资源缓存、首帧和持续动画的差异；
- `rendering/skia/` 与 `rendering/impeller/`：后端职责、着色器、管线深度和性能证据边界；
- 与 Android 的 Surface、BufferQueue、SurfaceFlinger、HWC、VSync 和帧时间线专题建立互链，而不在 Flutter 文档复制 Android 图形正文。

### 第四阶段：可重复诊断与基准

- profile/release 构建、DevTools、Timeline、Perfetto 与设备侧 trace 的证据边界；
- 导航、列表、Platform View、图片与 shader 首次使用等可比较场景的基准设计；
- 版本、刷新率、温控、SoC 与厂商图形栈差异的记录格式。

## 暂缓内容

- 具体产品的页面、路由表、插件、设备型号、trace、阈值和修复结论；这些属于项目事实源。
- Web、iOS、桌面端的输入和显示实现；除非未来出现需要独立维护的交叉问题，不把它们混入 Android 事实源。
- 以优化清单代替因果证据的内容；每一个“慢”的判断都应先说明测量端点与版本边界。
