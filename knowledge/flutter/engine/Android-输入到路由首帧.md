# Android 输入到 Flutter 路由首帧

前置阅读：[线程模型与性能同步](线程模型与性能同步.md)。本篇采用其中定义的 runner 拓扑和等待分类，不将 platform/UI 名称直接当作两条物理线程。

核对日期：2026-09-04
源码基线：Flutter Framework `abee5f5d5648fb6bb6ad55a5b153188e5dc9f055`、Flutter Engine `ae5c3603d013477d37ae301993fc0967d4ad7ed2`。这两个 `main` revision 用于源码阅读和 evidence 校验，不代表任一具体 Flutter SDK 或设备正在运行的精确组合。

线程前提：runner 拓扑、默认/非合并变体、Dart isolate 归属、VSync、UI→raster 背压和 Platform View 动态合并由[线程模型与性能同步](线程模型与性能同步.md)维护。本篇只把该模型应用到输入至路由首帧的测量点，不把 platform/UI 名称直接解释为跨线程等待。

## 范围

本文回答 Android 设备上的一个特定问题：用户完成一次触摸后，Flutter 路由的首个可见画面要经过哪些层，等待可能发生在哪里，怎样把“感觉慢”拆成可验证的时间段。

包含：Android 输入分发到 `FlutterView` 的边界、Android Embedding/JNI、Engine task runner、Dart 手势和 `Navigator`、VSync、Framework build/layout/paint、raster、Android 合成显示，以及相应的测量端点。

不包含：某个应用的页面、路由表、插件、设备、厂商驱动或 trace 结论；它们必须留在对应项目的事实源。也不把 Android Input、SurfaceFlinger 或 HWC 的系统机制全文复制到 Flutter 专题。

输入、手势、路由和首帧链路的可复查来源见[证据包](../../../evidence/flutter/engine/android-input-to-route-first-frame/manifest.json)；runner 模型的来源见[线程模型证据包](../../../evidence/flutter/engine/thread-model-and-performance-synchronization/manifest.json)。

## 先给结论

`Navigator.push` 不是一次 Android Activity 跳转，也不是“把下一页直接交给显示器”的系统调用。对于普通 Flutter 路由，它先在 Dart/UI 侧把 Route 插入 Navigator 历史并启动具体 Route 的过渡动画；下一页真正被看见还要等一个可服务的 VSync、Framework 生成 Scene、Engine raster、Android Surface/BufferQueue、SurfaceFlinger/HWC 合成和显示。

因此，“点击后路由慢”至少可能是五类不同问题：触摸尚未抵达 Dart、`onTap` 还在等待抬手或手势竞技场、回调/路由前后的 UI isolate 被同步工作占住、首帧 build 或 raster 错过预算、Flutter 已 raster 完但 Android 显示侧尚未呈现。没有时间点就不能把它们统称为路由性能问题。

还有两个经常被误判为卡顿的正常语义：

- `TapGestureRecognizer.onTap` 在成功的主按键 `PointerUpEvent` 后调用；用户按住 120 ms 再松手，路由在松手前没有开始并不表示慢。
- 若应用显式开启触摸重采样，Framework 的设计目标是以一部分延迟换取更平滑的触摸处理；本基线中该开关默认是关闭的，不能假定所有应用都相同。

## 一次交互的跨层链路

下图的箭头表示责任和数据的交接，不表示每段一定异步、也不表示所有队列在所有配置中都分离。

```text
手指接触 / 抬起
  │
  ├─ Android: kernel evdev → EventHub → InputReader → InputDispatcher
  │             → 获得焦点应用的 Window / View
  │
  ├─ Android Embedding（platform 侧）
  │     FlutterView.onTouchEvent(MotionEvent)
  │       → AndroidTouchProcessor
  │       → FlutterRenderer → FlutterJNI → JNI
  │
  ├─ Flutter Engine（默认与上面的 Android platform runner 合并）
  │     PlatformView::DispatchPointerDataPacket
  │       → Shell 交给 UI task runner（默认同一 runner，直接执行）
  │       → RuntimeController → Dart PlatformDispatcher
  │
  ├─ Flutter Framework（Dart UI isolate）
  │     GestureBinding: PointerDataPacket → 命中测试 → PointerRouter
  │       → gesture arena → TapGestureRecognizer.onTap
  │       → 业务回调 → Navigator.push / Route.didPush
  │
  ├─ 帧生产
  │     SchedulerBinding.scheduleFrame → Engine 等待 VSync
  │       → build → layout → compositing bits → paint → Scene
  │       → Engine layer-tree pipeline → raster task runner / GPU
  │
  └─ Android 显示
        Flutter Surface / BufferQueue → SurfaceFlinger → HWC → 面板呈现
```

Android 的系统输入模型中，EventHub 从 kernel 的 `evdev` 读取事件，InputReader 解码并生成 Android 输入事件，InputDispatcher 再转发给合适窗口。[AOSP Input 文档](https://source.android.com/docs/core/interaction/input?hl=en)只定义到应用窗口的系统边界；随后 `MotionEvent` 怎样进入 Flutter，由 Android Embedding 与 Engine 决定。

### 1. Android `MotionEvent` 到 Dart 指针包

当前 Engine 源码中，`FlutterView.onTouchEvent` 将附着 Engine 后的 `MotionEvent` 交给 `AndroidTouchProcessor`；后者写入 pointer data packet，依次经 `FlutterRenderer`、`FlutterJNI` 与 JNI native 方法送进 `PlatformView`。`PlatformView` 把包交给 Shell；Shell 以 UI task runner 运行 `Engine::DispatchPointerDataPacket`，最终由 RuntimeController 进入 Dart。

类和方法的交接不等于跨线程排队。该判断依赖前置专题中的实际 runner 拓扑；本篇在 T0→T1 归因时只把它落实为“先确认合并/非合并配置，再选择共享 runner 占用或独立 runner 交接”的测量分支。

### 2. 指针包到 `onTap`

`GestureBinding` 在 `PlatformDispatcher.onPointerDataPacket` 回调中用 `PointerEventConverter` 把原始 packet 转换为逻辑像素事件。`PointerDownEvent` 会做命中测试并让识别器进入 gesture arena；后续 `PointerUpEvent` 会 sweep arena。成功的 `TapGestureRecognizer` 在处理 up 时先调用 `onTapUp`，再调用 `onTap`。

用于 T0→T1 的“输入已到 Dart/Framework”端点，应在上述 pointer packet/down 处理入口记录（例如定制 Binding 或 Framework trace marker），而不是用 `onTapDown` 替代。`onTapDown` 只会在 down 后短暂 timeout 到期或该 recognizer 赢得 gesture arena 后触发；它可作为“tap 候选反馈”的附加标记，但不是原始输入抵达 Dart 的标记。将它与实际导航回调（通常是 `onTap` 或 `onPressed`）一起记录，能分离按压持续时间、手势竞争和 Framework 处理；只有在 `onTap` 已开始后再讨论 `Navigator` 才有明确起点。

触摸重采样也应作为一个显式变量检查。`GestureBinding` 注释说明，开启 `resamplingEnabled` 会让触摸更平滑，但会增加一些延迟；不要在未确认开关、输入频率和刷新率之前，把这部分等待归因于设备或路由。

### 3. `onTap` 到 Route 状态

`NavigatorState.push` 立即创建 `_RouteEntry`、加入 history 并执行 `_flushHistoryUpdates`；其中会安装 Route 并调用 `didPush`。对 `TransitionRoute`，安装阶段创建 `AnimationController`，`didPush` 将控制器向前推进。具体页面何时 build、首帧多大、是否有复杂 transition，仍取决于 Route 和应用代码。

`Navigator.push` 返回的是 `route.popped`，不是“首帧已显示”的 future。因此用 `await Navigator.push(...)` 作为导航起点到首帧的计时终点是错误的：它通常会等到用户从新页返回。

### 4. Route 状态到 Scene

视觉更新需要帧。`SchedulerBinding.scheduleFrame` 调用 `PlatformDispatcher.scheduleFrame`，Engine 最终通过 VSync waiter 等待系统 VSync。收到帧后，Framework 在 UI isolate 依次执行 transient callback、microtask、persistent callback；`WidgetsBinding.drawFrame` 重建 dirty Element，`RendererBinding.drawFrame` 刷新 layout、compositing bits 和 paint，并让 `RenderView.compositeFrame` 把 Scene 送进 Engine。

这解释了为什么“回调已经进入、`push` 也已经返回”仍可能没有画面：它只说明路由状态发生了变化，还未说明新的 Scene 已构建，更未说明它已经被显示。

### 5. Scene 到屏幕

Scene 交给 Engine 后，VSync、FramePipeline 与 raster 的 runner 语义由[线程模型与性能同步](线程模型与性能同步.md)维护；本篇只把 `FrameTiming` 的 build/raster 端点作为输入到首帧链路的测量边界。

但 raster 完成不是像素已经进入面板。Android 图形栈中，Surface 是 BufferQueue 的生产端，SurfaceFlinger 消费可见 Surface 的 buffer、合成并交给 HWC；实际实现还受设备 SoC、驱动和显示刷新节奏影响。详见 [AOSP Graphics](https://source.android.com/docs/core/graphics?hl=en)。因此需要用系统 trace 才能把 Flutter 的 `rasterFinishWallTime` 与 SurfaceFlinger/HWC 侧事件对齐。

## 在本链路中应用线程模型

完整的 runner 拓扑、同 runner 直接执行、VSync、FramePipeline 背压和 Platform View 动态合并由[线程模型与性能同步](线程模型与性能同步.md)维护。本篇只将它们映射到本链路的端点：

- T0→T1 很晚时，先从实际拓扑判断是共享 platform/UI runner 的前序同步占用，还是非合并配置中的 runner 交接；
- T3→T4 很晚时，区分 frame request、VSync 节拍和 UI 侧 build/layout/paint；
- T4→T5 很晚时，检查 UI→raster 的生产消费关系；`PipelineFull` 只是下游未及时消费的线索，不是独立根因；
- 含 Platform View 的帧需要先确认实际合成模式，再回到前置专题判断动态 raster/platform merger 是否适用；不能仅凭存在原生控件就假定合并。各模式的缓冲与事务同步见 [Android Platform Views 与原生渲染](../rendering/Android-Platform-Views与原生渲染.md)。

## 帧预算与端到端延迟不是同一个数

| 刷新率 | 一帧周期 | 含义 |
| --- | ---: | --- |
| 60 Hz | 16.67 ms | UI 和 raster 任一关键阶段持续越过该周期，会产生掉帧风险 |
| 90 Hz | 11.11 ms | 同样的工作量更容易错过下一次刷新 |
| 120 Hz | 8.33 ms | 预算更紧，且输入到下一次可服务 VSync 的相位影响更明显 |

这些周期是刷新间隔，不是“点击到显示必然只需一帧”的承诺。输入可能刚好错过 VSync；一次错过通常会再增加一个完整刷新周期。build 与 raster 在管线中也可以重叠，不能简单把所有条形时间逐项相加。

适合建立的因果模型是：

```text
输入到可见首帧
≈ 输入系统 + 手势语义 + 回调前同步工作
  + {默认合并：platform/UI 前序串行占用；非合并：platform→UI 交接}
  + 等待可服务 VSync + UI build/layout/paint + 管线/光栅化
  + BufferQueue/SurfaceFlinger/HWC/面板
```

这是定位框架，不是可直接相加的单个性能公式。不同段可并发、可被队列隐藏，也可能跨越不同的时钟域。

## 诊断：先设置端点，再谈优化

### 记录条件

1. 用真机的 profile 或 release 构建复现；Flutter 官方文档明确指出 debug 的 frame timing 与 profile/release 可能显著不同。
2. 分开记录首次进入与热路径重复进入。首次 shader、图片解码/上传、缓存建立或延迟初始化造成的结果，不应和稳定导航混成一个均值。
3. 记录刷新率、系统负载与温控等测试条件，但把具体设备值留在项目事实源。
4. 在提出优化前，先保存同一次操作的 Flutter Timeline/FrameTiming 与必要的 Android 系统 trace。

### 最小测量点

以下编号是本专题的统一约定；具体采集、窗口查询、帧关联与时钟转换见[运行时性能验证链](运行时性能验证链.md)。T3 是同步区间，T5 是阶段时间戳集合，计算时必须指定所用端点。

| 标记 | 应记录的位置 | 能分离的等待 | 不能证明的事情 |
| --- | --- | --- | --- |
| T0 | Android 系统 trace 的 input 分发（可获取时） | 硬件/系统输入到应用窗口 | Flutter 的手势是否已识别 |
| T1 | `GestureBinding` 的 pointer packet/down 处理入口（定制 Binding 或 Framework trace marker） | Engine 已把原始输入 packet 交给 Dart/Framework，并开始处理该 down | 目标已命中、成功 tap 或导航已经开始 |
| T2 | `onTap` / `onPressed` 开头 | 按压、gesture arena 和回调到达 | `Navigator` 是否已变更 |
| T3 | `Navigator.push` 前后 | 同步的 route 创建、observer 和 history 更新 | 新 Scene 或首帧已经完成 |
| T4 | 目标页面首次相关 build 后的 post-frame callback | Framework 已走完该帧的 build/layout/paint 路径 | raster 或实际显示已完成 |
| T5 | `SchedulerBinding.addTimingsCallback` 的 `FrameTiming` | vsync→build、build、raster 与 Flutter total span | SurfaceFlinger/HWC 已把 buffer 呈现到面板 |
| T6 | Perfetto / Android 图形 trace 的 buffer、SurfaceFlinger、HWC 事件 | Flutter raster 后到系统呈现的部分 | 单凭一条系统轨道证明 Dart 侧根因 |

`FrameTiming` 的 `vsyncStart`、`buildStart`、`buildFinish`、`rasterStart`、`rasterFinish` 是最小的 Flutter 帧分段：

- `buildStart → buildFinish` 是 UI 线程 build 时长；
- `rasterStart → rasterFinish` 是 raster 线程时长；
- `vsyncStart → rasterFinish` 是 Flutter 的 `totalSpan`；
- `rasterFinishWallTime` 使用系统 wall-time；与系统 trace 比较前必须核对时钟域、单位和转换关系，不能直接与 Perfetto `ts` 相减。

优先通过 `SchedulerBinding.addTimingsCallback` 获取这些数据，而不是覆盖 `PlatformDispatcher.onReportTimings`；后者的源码也明确说明 `FrameTiming` 会批量上报。DevTools Performance view 能把 UI/raster frame bars、Timeline、widget build/layout/paint tracing 放在同一分析界面，但增强 tracing 本身会影响测量，需只在受控复现时开启。

### 用证据缩小范围

| 观察 | 优先怀疑的边界 | 下一步应取得的证据 |
| --- | --- | --- |
| T1 很晚，且 T0→T1 有大空洞 | 默认配置下先怀疑合并的 Android platform/UI runner 被占用；非合并变体才单独怀疑 UI runner 交接 | 先确认 runner 配置，再同时看 input、Android 主线程与 Flutter UI 轨道，而不是先改路由 |
| T1 正常、T2 很晚 | 手势语义、按压持续时间、gesture arena | 对比 raw `PointerDown`、`onTapDown`（可选）、pointer up 与 `onTap`；确认是否开启重采样 |
| T2 到 T3 很晚，或 T3 内部很长 | 同步业务工作、route 构造、observer/redirect 等 Dart 代码 | Dart Timeline/CPU profile；给同步边界加 marker |
| T3 很快、T4 很晚 | 等待 VSync，或 UI isolate 的 build/layout/paint 过重 | DevTools UI bar 与 build/layout/paint tracing |
| UI 很短而 raster 很长 | 复杂 Scene、shader、图片上传、clip/opacity/shadow 等 raster 负担 | DevTools raster bar、shader 标记、同一场景冷热对比 |
| T5 已完成但肉眼仍晚 | Surface、BufferQueue、SurfaceFlinger、HWC、显示刷新或厂商实现 | 按运行时验证链确认时钟转换及同一帧关联；检查系统图形轨道 |
| 只在第一次导航慢 | 仅首次发生的延迟初始化、shader 或资源工作 | 首次/热路径分组；不要用热路径结果否认冷路径体验 |

表中的“优先怀疑”是下一轮证据的方向，不是诊断结论。例如，raster 慢可能由 Dart 侧构造的 Scene 触发；系统呈现晚也可能是前面已经错过了多次 VSync。

## 常见错误归因

- 把按住按钮到松手的时间算进 `Navigator`。对 `onTap` 而言，这是预期手势语义；若希望更早给反馈，应把“按下反馈”和“完成导航”作为两个独立体验目标测量。
- 用 debug build、单次冷启动或模拟器条形图给硬件性能下结论。它们可以用于功能定位，不足以代表 release 体验。
- 把 `Navigator.push` 的返回 future 当作首帧完成信号。它关联 Route 被 pop 的结果，不是路由已显示。
- 把 post-frame callback 当作屏幕呈现。它只能说明 Framework 的该帧收尾已到达；raster 与 Android 合成仍在后面。
- 只看到一个慢的 UI/raster bar 就立即“优化 Widget”。先确认该 bar 是否对应目标交互、是否为首帧、是否在多次复现中稳定出现。
- 把当前 Android 的 platform runner 和 UI runner 默认当作两条独立线程。固定 Engine 基线中它们默认合并；应在 trace 中验证实际 runner，而不是预设 platform→UI 有一次跨线程等待。
- 认为把任何工作放到 isolate 都会解决交互延迟。Flutter UI 仍耦合 main isolate；isolate 只适合可消息化、确实占用 UI isolate 的大计算，且要计入消息传递与结果回到 UI 的成本。

## 源码阅读路线

| 目的 | 固定源码入口 |
| --- | --- |
| Android 输入到 Flutter Java bridge | [FlutterView](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/platform/android/io/flutter/embedding/android/FlutterView.java)、[AndroidTouchProcessor](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/platform/android/io/flutter/embedding/android/AndroidTouchProcessor.java)、[FlutterRenderer](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/platform/android/io/flutter/embedding/engine/renderer/FlutterRenderer.java)、[FlutterJNI](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/platform/android/io/flutter/embedding/engine/FlutterJNI.java) |
| JNI、PlatformView 与 UI runner 交接 | [platform_view_android_jni_impl.cc](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/platform/android/platform_view_android_jni_impl.cc)、[platform_view.cc](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/common/platform_view.cc)、[shell.cc](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/shell/common/shell.cc) |
| runner 拓扑、合并变体与性能同步 | [线程模型与性能同步](线程模型与性能同步.md) |
| VSync、FramePipeline 与 raster runner | [线程模型与性能同步](线程模型与性能同步.md) |
| Dart pointer/gesture 语义 | [gestures/binding.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/gestures/binding.dart)、[gestures/tap.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/gestures/tap.dart) |
| Route 入栈与 transition | [widgets/navigator.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/widgets/navigator.dart)、[widgets/routes.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/widgets/routes.dart) |
| 帧调度、构建与 Scene | [scheduler/binding.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/scheduler/binding.dart)、[widgets/binding.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/widgets/binding.dart)、[rendering/binding.dart](https://github.com/flutter/flutter/blob/abee5f5d5648fb6bb6ad55a5b153188e5dc9f055/packages/flutter/lib/src/rendering/binding.dart) |
| Flutter 计时接口与工具 | [platform_dispatcher.dart](https://github.com/flutter/engine/blob/ae5c3603d013477d37ae301993fc0967d4ad7ed2/lib/ui/platform_dispatcher.dart)、[DevTools Performance view](https://docs.flutter.dev/tools/devtools/performance)、[Flutter performance profiling](https://docs.flutter.dev/perf/ui-performance) |
| Android 系统输入与显示边界 | [AOSP Input](https://source.android.com/docs/core/interaction/input?hl=en)、[AOSP Graphics](https://source.android.com/docs/core/graphics?hl=en) |

## 版本与验证边界

- 上述 Flutter 源码是 2026-09-04 固定的 `main` revision；针对某个应用排查时，应记录该应用的 Flutter SDK、Engine revision、构建模式和 Android 版本，并以该项目事实源为准。
- runner 合并、非合并变体和 Platform View 动态 merger 的适用边界见[线程模型与性能同步](线程模型与性能同步.md)。项目采用自定义 embedder、启动参数或未来 Engine 版本时，应从实际 runner/trace 重新确认，不能把该专题的基线外推为永久 ABI 承诺。
- `FrameTiming` 覆盖 Flutter build/raster 生命周期，不是 Android compositor 的直接呈现回执；要主张“屏幕晚显示”，需要同一操作的系统侧证据。
- Android 输入和图形文档描述 AOSP 通用架构；触摸 IC、内核、GPU 驱动、HWC、面板和厂商调度会改变具体时序。
- 本文完成的是静态源码与官方文档核对，尚未对任一设备、Android 分支或运行时 trace 做验证。
