# Flutter Rendering

本专题维护 Flutter 绘制结果如何与原生图形内容组合，以及 Framework、Engine、平台视图和系统合成器之间的接口。线程调度的通用模型由 [Engine 专题](../engine/README.md)维护。

## 阅读顺序

1. [线程模型与性能同步](../engine/线程模型与性能同步.md)：先区分 UI、platform、raster 的执行归属与同步边界。
2. [Android Platform Views 与原生渲染](Android-Platform-Views与原生渲染.md)：原生控件与外部纹理的选择，VD、TLHC、HC、HCPP 的合成路径，以及创建、交互与验证边界。
3. [对应证据包](../../../evidence/flutter/rendering/android-platform-views/manifest.json)：固定源码版本、哈希、断言和官方文档元数据。

## 范围与拆分边界

当前内容以 Android 原生内容集成为独立阅读单元。iOS 只记录平台差异入口，不在这里展开 UIKit 合成实现。后续 Layer tree、Skia、Impeller 后端与资源管理形成独立内容时，再建立相应事实源；不把它们持续堆入 Platform Views 文档。

Android 的 Surface、BufferQueue、SurfaceFlinger 和 HWC 机制归入 [Android 领域](../../android/README.md)。本专题只解释 Flutter 与这些机制的交界，不保存具体应用、设备、trace 或一次运行的性能结论。
