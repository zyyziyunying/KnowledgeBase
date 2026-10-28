# Flutter 裁剪展开转场与性能边界

卡片向全屏展开，可以让目标页面从一开始就按全屏尺寸布局，再逐渐扩大外层裁剪窗口。窗口负责位置、大小和圆角，内部页面保持稳定的尺寸与排布。对于先渲染到纹理的实时 3D 内容，外层窗口变小并不自动降低内部渲染分辨率；布局、场景渲染和最终裁剪需要分开理解。

本文以 Lantern Spirit 的固定开源实现解释可复用机制，覆盖卡片展开、返回衔接、同场景房间展开，以及相应性能边界。角色节点与动画混合另见 [Flutter Scene 的动画与交互叠加](Flutter-Scene动画与交互叠加.md)。这里不维护案例应用的功能清单、运行环境或设备性能记录。

## 源码基线与阅读入口

| 来源 | 固定 revision | 用途 |
| --- | --- | --- |
| [Lantern Spirit][app-repo] | `bc151089f4ecfeae6675ef98731b55f8770ed39b` | 转场、目标页占位、预热和房间展开 |
| [Flutter Scene][scene-repo] | `b8023c6261ed77ed4046d72c86496ed40c96b37b` | SceneView 更新与离屏渲染目标；由案例依赖固定 |
| [Flutter][flutter-repo] | `559ffa3f75e7402d65a8def9c28389a9b2e6fe42`，3.44.0 | Widget 复用、裁剪、透明度与路由语义的对照源码 |

核对日期：2026-10-28。Flutter 对照版本用于解释相关 API，不代表案例实际构建采用的 SDK；迁移时应复核目标 SDK。Flutter Scene 的渲染路径是固定库版本的实现，不能推广为所有 Flutter 页面或所有 3D 库的保证。来源哈希、关键断言和下文 claim 映射见 [证据包](../../../evidence/flutter/rendering/clipped-reveal-transitions/manifest.json)。

## 卡片展开时固定内部布局

`CardRevealRoute` 通过 `LayoutBuilder` 取得路由区域大小，并让内部页面始终收到该区域的完整宽高约束；在常规全屏路由中，这就是全屏尺寸。外层矩形在入口卡片与完整路由区域之间插值，内部页面居中放在这个窗口中。[转场实现][route]。对应证据：`clipped-reveal-001`。

```text
AnimatedBuilder                复用预先传入的目标页面 child
└── Stack
    ├── 背景遮罩               随展开进度变暗
    └── Positioned.fromRect    控制窗口位置与宽高
        └── Opacity            控制返回末段的淡出
            └── ClipRRect      控制可见区域与圆角
                └── OverflowBox
                    └── 目标页  保持完整路由区域的宽高
```

下面是说明性的参数关系，省略原实现的反向分段与回退逻辑：

```text
t = curve(animation.value)
窗口矩形 = Rect.lerp(入口卡片矩形, 完整路由矩形, t)
内部页面宽高 = 完整路由区域宽高
圆角 = lerp(卡片圆角, 0, easeIn(t))
背景黑色遮罩透明度 = 0.6 × t
```

例如，路由区域为 `400 × 800` 逻辑像素时，内部页面在开始、中间和结束阶段都按 `400 × 800` 布局，只是可见窗口不同。这是几何关系示例，不是设备实测值。内部内容不随窗口等比缩放；由于居中对齐，窗口中心移动时，内部页面在屏幕上的原点也会移动，不能把它理解为固定屏幕坐标上的一张大图只改变裁剪宽高。

`AnimatedBuilder.child` 让转场动画复用目标页面，而固定内部约束减少了由窗口缩放导致的内部布局变化。外层窗口仍有布局更新；目标页自己的状态变化也可以触发 build、layout 或 paint，因此不能推导成“整个动画期间绝不重新布局”。[AnimatedBuilder 源码说明][flutter-transitions]、[OverflowBox][flutter-overflow]

## 打开与返回的衔接

固定案例的打开与返回时长均为 **1150ms**。打开使用 `Cubic(0.2, 0.0, 0.0, 1.0)`：窗口扩大，圆角归零，背景逐渐变暗；目标页面外层的 `Opacity` 保持 1。

返回使用两个阶段，时间线动画值从 1 下降到 0：

| 动画值区间 | 窗口 | 目标页外层透明度 |
| --- | --- | --- |
| `1 → 0.3` | 用缓动曲线缩回入口卡片 | 保持 1 |
| `0.3 → 0` | 保持入口卡片矩形 | 逐渐淡出，露出下面的静态卡片 |

按控制器时长计算，约 805ms 用于收拢，345ms 用于淡出；这不是实际呈现帧数或设备延迟的测量。返回不只是把打开时的同一曲线倒放。[正反向分段][route]。对应证据：`clipped-reveal-002`。

有 `fromKey` 时，动画会重新取得入口卡片的可见矩形，尝试与所属滚动视口求交；无法取得时回退到最初的 `from`。这让返回可以跟随仍挂载、可定位的入口。卡片被移除或无法定位时，回退值不保证仍对应当前界面。

坐标也有适用条件：案例用 `localToGlobal` 得到卡片矩形，而路由完整矩形从局部 `Offset.zero` 开始。迁移到嵌套 Navigator、带偏移的宿主区域或额外变换中时，应先把两端矩形转换到同一坐标系，再插值。

## 静态封面与实时场景的接续

烟花目标页提供了另一层衔接：场景未准备好时展示与入口卡片相同的 `tonight.jpg`；加载与场景预热完成后，让封面在 **600ms** 内淡出，显露实时 3D 内容。窗口展开和“封面变为实时内容”是两个独立进度，不能认为点击后第一帧必然已经是完整 3D 画面。[入口封面][park-card]、[目标页加载与占位][show]。对应证据：`clipped-reveal-003`。

相同图片资源有助于视觉衔接，但不同容器尺寸、`BoxFit.cover` 裁切和对齐仍可能改变构图，不能据此保证首尾逐像素一致。该目标页创建自己的 `Scene` 并加载角色；视觉连续性不要求它与入口页共享同一个角色对象。

## 小窗口与全尺寸 3D 渲染

先区分三个层次：

| 层次 | 决定什么 | 外层窗口变小时的含义 |
| --- | --- | --- |
| Flutter 布局 | 页面和 SceneView 的逻辑尺寸 | 本例内部仍保持完整路由尺寸 |
| Flutter Scene 渲染 | 场景更新、渲染目标和 3D 图像生成 | 渲染目标尺寸没有直接跟随外层裁剪窗口 |
| Flutter 裁剪与合成 | 哪部分结果最终可见 | 只显示窗口覆盖的部分 |

固定版本的 `_ScenePainter.paint` 显式把 `Offset.zero & size` 作为 viewport 传给 `Scene.render`。随后 `renderViews` 优先采用传入 region；只有 region 未提供时才读取 Canvas 裁剪边界。单视图正常出图路径按这个完整区域建立离屏渲染目标，生成纹理后再通过 `canvas.drawImageRect` 交给 Flutter 合成。[SceneView 绘制][scene-view]、[region 选择][scene-region]、[纹理生成与合成][scene-target]。对应证据：`clipped-reveal-004`。

```text
完整尺寸的 SceneView
  → 把完整视图区域交给 Scene.render
  → 生成该区域对应的 3D 纹理
  → drawImageRect 交给 Flutter
  → 外层裁剪决定最终可见部分
```

实际纹理尺寸还由像素密度和渲染比例决定：

```text
scale = pixelRatio × (view.renderScale ?? scene.renderScale) × adaptiveRenderScale
纹理宽度 = ceil(完整视图逻辑宽度 × scale)
纹理高度 = ceil(完整视图逻辑高度 × scale)
```

这里的 `scene.renderScale` 是对源码内部 `_renderScale` 的解释性记法。假设逻辑尺寸为 `400 × 800`、像素密度为 3、其余比例为 1，则目标为 `1200 × 2400` 像素；外层只露出四分之一，并不会让上述公式自动变成四分之一大小。这个算例只解释像素规模，不估算帧耗时。

“每次实际出新帧按完整视图决定目标”也不等于“每个显示刷新都必然重绘整个场景”：加载门控、Ticker 状态、帧率限制和 GPU 在途帧控制都可能改变更新或出图频率；固定渲染器存在复用上一张纹理的分支。此外，3D 引擎自身仍有剔除等机制，不能把完整渲染目标理解为所有模型和所有像素都一定执行同样的计算。这里确认的是：外层卡片裁剪没有自动成为内部 3D 渲染区域的缩减参数。

## 性能成本与优化边界

窗口矩形插值只是整条链路的一部分。实际成本应按以下位置分开观察，而不能从动画看起来简单或窗口面积较小推断性能。

| 成本位置 | 源码支持的判断 | 不能直接推导的结论 |
| --- | --- | --- |
| 构建与布局 | 目标页作为 `AnimatedBuilder.child` 复用，内部尺寸固定 | 目标页状态更新、外层布局和场景 paint 都被免除 |
| 圆角裁剪 | `ClipRRect` 默认 `Clip.antiAlias`；区别于显式追加离屏层的 `antiAliasWithSaveLayer` | 整条渲染链没有离屏纹理或裁剪完全免费 |
| 透明度合成 | 路由返回末段进入部分透明；目标页封面也可独立淡出 | 每个后端的缓冲数量、合成耗时完全一致 |
| 场景更新与出图 | `appSceneView` 调用页面更新和 `scene.update`，场景视图请求重绘 | Widget 没重新 build，就没有 CPU/GPU 工作 |
| 背景页面 | 路由始终声明 `opaque = false`，不依赖不透明路由完成后的底页省略机制 | 铺满屏幕后底页自动停工，或两个页面的成本恰好翻倍 |

裁剪、透明度和路由语义见 [Clip 定义][flutter-clip]、[Opacity 说明][flutter-opacity]、[路由 opaque 语义][flutter-routes]；逐帧更新见 [应用封装][app-clock]和 [SceneView][scene-view-all]。对应证据：`clipped-reveal-005`。部分透明可能涉及中间缓冲与混合；实际分层和优化结果仍取决于运行时后端与子树结构。

资源预加载和管线预热解决的是另一类问题：把模型、材质等准备工作前移，减少首次进入时临时加载、编译造成的停顿。固定案例的 `Preload.run` 先加载资源，再预热各类场景。它不会自动免除之后每帧的场景更新、纹理渲染和合成成本；收益还要结合启动耗时与缓存占用评估。[预加载实现][preload]。对应证据：`clipped-reveal-006`。

针对已有测量结果，可选择不同的优化方向：

- **场景像素或后处理成本较高**：尝试降低 3D 渲染比例并检查画质。宽高各减半时目标像素数约为四分之一，但模型更新、提交和固定成本不会同比缩减；避免逐帧无节制改变尺寸造成资源重建。
- **底页动画贡献明显**：按路由可见性管理底页场景更新。返回露出底页前恢复，并明确暂停的是 Ticker、场景模拟还是其他任务，不能假设它们是同一开关。
- **只需要视觉过渡**：可以评估静态快照或封面承担转场、实时内容稍后接续的方案。需要同时评估捕获成本、过渡期间的交互与内容是否过时。
- **试图只渲染窗口区域**：需要把裁剪区域映射到 3D 相机投影、viewport 或渲染器的区域处理；直接把 SceneView 缩成卡片可能改变宽高比和构图，不能当成无损替换。

这些是由成本模型导出的选择，不是固定案例已经完成或验证有效的优化。

Scene 的离屏目标、尺寸缓存、提交背压与纹理合成接口可继续读 [Flutter Scene 的底层实现与性能边界](Flutter-Scene底层实现与性能边界.md)。该文固定独立的源码基线；本篇保持案例依赖版本，不能据新版本实现反推旧版本的资源回收行为。

## 同一场景展开为房间

房间展开使用同一页面中的 `AnimationController`，时长 **1100ms**，通过 `easeInOutCubic` 得到主进度。它保留原有角色和 Scene，把房间根节点加入场景，再协调多个参数。[房间开关][park-room]、[相机与角色受光][park-camera]、[房间部件动画][room]。对应证据：`clipped-reveal-007`。

| 参数 | 随展开进度发生的变化 |
| --- | --- |
| 头部视口 | 高度从头部高度增加到页面高度 |
| 窗口边缘 | 底部圆角从 28 归零 |
| 相机 | 位置后退并抬高，target 改变，垂直视场角从 27° 增至 38° |
| 房间部件 | 依据原始进度与各自 delay，用 `elasticOut` 缩放出现 |
| 光照 | 房间灯光逐渐增强，角色增加房间方向的暖色受光 |

“同一个角色”指对象与场景关系连续，并不保证它在屏幕上的位置或尺寸不变；相机与视口正在同时变化。此路径中 SceneView 的视口尺寸也会变化，不能直接套用卡片展开时“内部尺寸固定”的判断。关闭时反向播放，控制器回到 dismissed 后移除房间节点。

## 运行时验证方法

性能结论需要在目标设备与目标构建上区分冷首次进入、已预热展开、全屏稳态和返回淡出。对比时固定场景内容、输入、渲染比例和刷新率，并分别记录 UI/layout、raster、GPU、渲染目标尺寸与内存；不能把某个线程时间单独当成最终呈现延迟。

可用以下受控对照帮助定位成本，实验结果保留在具体项目的事实源中：

| 对照 | 要回答的问题 |
| --- | --- |
| 相同窗口动画，实时场景与静态占位对照 | 场景模拟、3D 出图相对转场外壳贡献多少 |
| 相同目标场景，底页动画开启与暂停对照 | 背景页面贡献多少持续工作 |
| 固定逻辑布局，改变场景渲染比例 | 成本是否主要随像素数量变化 |
| 首次进入与预热后进入对照 | 资源准备与稳定逐帧成本如何分布 |

Android 的端点、trace 与呈现证据按 [运行时性能验证链](../engine/运行时性能验证链.md)执行；Web 和其他平台应采用各自后端的观测工具，不能把 Android 工具链直接外推。固定源码与字符串断言只能核对机制和入口，不能证明目标 SDK/设备实际采用了相同分支，也不能给出该转场的帧率、功耗或掉帧结论。

[app-repo]: https://github.com/bdero/lantern_spirit/tree/bc151089f4ecfeae6675ef98731b55f8770ed39b
[scene-repo]: https://github.com/bdero/flutter_scene/tree/b8023c6261ed77ed4046d72c86496ed40c96b37b
[flutter-repo]: https://github.com/flutter/flutter/tree/559ffa3f75e7402d65a8def9c28389a9b2e6fe42
[route]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/show_route.dart
[park-card]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L1763-L1795
[show]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/show/show_screen.dart
[preload]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/preload.dart
[app-clock]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/app/scene_clock.dart
[park-room]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L113-L151
[park-camera]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/ui/park_screen.dart#L239-L263
[room]: https://github.com/bdero/lantern_spirit/blob/bc151089f4ecfeae6675ef98731b55f8770ed39b/lib/room/room.dart#L624-L667
[scene-view]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/widgets/scene_view.dart#L929-L966
[scene-view-all]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/widgets/scene_view.dart
[scene-region]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/scene.dart#L2141-L2180
[scene-target]: https://github.com/bdero/flutter_scene/blob/b8023c6261ed77ed4046d72c86496ed40c96b37b/packages/flutter_scene/lib/src/scene.dart#L2842-L2946
[flutter-transitions]: https://github.com/flutter/flutter/blob/559ffa3f75e7402d65a8def9c28389a9b2e6fe42/packages/flutter/lib/src/widgets/transitions.dart#L1194-L1206
[flutter-overflow]: https://github.com/flutter/flutter/blob/559ffa3f75e7402d65a8def9c28389a9b2e6fe42/packages/flutter/lib/src/widgets/basic.dart#L3385-L3420
[flutter-opacity]: https://github.com/flutter/flutter/blob/559ffa3f75e7402d65a8def9c28389a9b2e6fe42/packages/flutter/lib/src/widgets/basic.dart#L233-L243
[flutter-clip]: https://github.com/flutter/flutter/blob/559ffa3f75e7402d65a8def9c28389a9b2e6fe42/engine/src/flutter/lib/ui/painting.dart#L1212-L1286
[flutter-routes]: https://github.com/flutter/flutter/blob/559ffa3f75e7402d65a8def9c28389a9b2e6fe42/packages/flutter/lib/src/widgets/routes.dart#L151-L156
