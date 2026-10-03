# Flutter Engine

本专题维护 Flutter Engine 的可复用系统模型：Dart Runtime 与代码加载、Dart UI isolate、task runner、帧调度、rasterizer，以及它们与 Android Embedding 和 Android 图形栈之间的交界。

## 当前事实源

1. [线程模型与性能同步](线程模型与性能同步.md)：性能分析的前置模型；区分 native thread、task runner、Dart isolate、默认 platform/UI 合并、VSync、UI→raster 背压和传统 HC 的动态 raster/platform 合并。建议先读这一篇。
2. [对应证据包](../../../evidence/flutter/engine/thread-model-and-performance-synchronization/manifest.json)：固定 Engine revision、线程模型断言和官方文档元数据。
3. [Android 输入到 Flutter 路由首帧](Android-输入到路由首帧.md)：在上述模型上，从物理触摸到路由首帧的端到端链路、延迟归因和验证方法。
4. [对应证据包](../../../evidence/flutter/engine/android-input-to-route-first-frame/manifest.json)：固定 Flutter Framework/Engine revision、输入和首帧调用链的源码哈希、关键断言和官方文档元数据。
5. [运行时性能验证链](运行时性能验证链.md)：把静态模型转成一次可复跑的 profile/Perfetto/SQL 验证；定义应用 span、系统输入、Engine/UI/raster 与显示端点的证据边界。
6. [对应证据包](../../../evidence/flutter/engine/runtime-performance-validation/manifest.json)：固定 Flutter tool、Dart Timeline、Perfetto ATrace/CLI/trace processor 与 FrameTiming 的来源和断言。
7. [Shorebird 热更新机制](Shorebird-热更新机制.md)：独立阅读的代码加载专题；覆盖 Android/iOS 更新机制、编译器复用、生命周期和公开证据边界。
8. [对应证据包](../../../evidence/flutter/engine/shorebird-code-push/manifest.json)：Shorebird Engine、updater 与官方文档的固定来源，以及设计说明元数据。

## 阅读边界

本专题解释 Flutter 自己的运行时加载、线程、输入、帧与渲染接口；Android 的 InputReader/InputDispatcher、Surface、BufferQueue、SurfaceFlinger 和 HWC 只解释到交界处。系统侧的独立知识应归入 [Android 领域](../../android/README.md)，不要在本专题复制 Android Framework 正文。

原生控件与外部纹理的集成，以及各 Platform Views 模式的合成与同步边界，见 [Android Platform Views 与原生渲染](../rendering/Android-Platform-Views与原生渲染.md)。

当前正文是一个跨层切片，不代表已经完成 Engine、Android Embedding 或 Rendering 的全部内容。后续若生命周期/JNI、渲染后端或 Android 图形栈开始需要独立维护，应分别在其专题入口拆分，并由本页维护阅读顺序。
