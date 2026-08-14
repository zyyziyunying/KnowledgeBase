# Android Framework 高频核心讲义

这份讲义服务于两个目标：建立能读 AOSP 源码的系统模型，以及在 Framework 岗位面试中把关键问题讲清楚。它不是“背题答案库”：每个主题都要用 **结论 → 机制 → 证据/源码入口 → 边界** 的方式掌握。

阅读优先级：先完成 1–6，它们覆盖了绝大多数 Android Framework 面试的主干；7–12 再补图形、输入、性能、安装和安全。

## 0. 面试时怎样回答 Framework 问题

不要从类名堆砌开始。建议固定用四句结构：

1. **一句结论**：这个组件解决什么问题。
2. **主调用链**：说出 3–6 个关键节点和进程边界。
3. **关键机制**：挑一个真正决定行为的点，如 Binder 线程池、Copy-on-Write、VSync、`oom_adj`。
4. **边界与验证**：指出版本/厂商差异，或用 `dumpsys`、log、trace 说明如何验证。

例如被问“Binder 为什么快”，不要只答“用了内存映射”。更完整的回答是：Binder 是 Android 的本地 IPC 框架，接口两端通过内核 Binder driver 通信；数据只在用户态与内核态之间进行一次主要拷贝，且 Binder 能携带调用方 UID/PID 和对象引用，方便权限控制与服务管理。但它不适合大块数据传输，大数据应通过 fd、共享内存或文件描述符传递。

---

## 1. Android 开机过程、init、Zygote、SystemServer

### 一句话结论

Android 启动是从 bootloader 到 Kernel，再由 `init` 拉起 native 服务、Zygote 和 `system_server` 的链路；`system_server` 是 Java Framework 核心系统服务的宿主进程。

### 主链路

```text
Boot ROM → Bootloader → Linux Kernel
                         ↓
                       init（PID 1）
                         ↓ 解析 *.rc、挂载分区、启动 native daemon
                       Zygote
                         ↓ 预加载类/资源，fork
                       system_server
                         ↓
     AMS / ATMS / WMS / PMS / Power / Input / ...
```

Android 官方把 Android 特有的启动主线概括为 `init → Zygote → system server`；SystemServer 是第一个 Java 系统组件，会启动核心系统服务。[官方启动说明](https://source.android.com/docs/automotive/power/boot_time)

### 关键点

- `init` 是用户空间的 PID 1，负责解析 `init.rc`，创建/挂载文件系统、设置属性、启动 service。它不是 Java Framework 服务。
- Zygote 运行在 ART/Dalvik Java 运行时中，预加载常用 class、资源等，然后通过 fork 产生 app 进程，也会 fork 出 `system_server`。
- `system_server` 不是“所有系统进程”。例如 `surfaceflinger`、`servicemanager`、`netd` 等是独立 native 进程；它主要承载 Java 系统服务。
- SystemServer 依赖顺序很重要：服务启动过早会拿不到依赖，过晚又会影响系统可用性。因此源码中常按 bootstrap、core、other services 分组启动。

### 高频追问：Zygote 为什么能加快应用启动？

它把运行时初始化与常用类/资源预加载提前到 fork 之前。fork 之后，父子进程先共享物理页；只有某一方写入时才复制（Copy-on-Write）。这样既减少冷启动初始化，也节省了可共享内存。代价是 Zygote 的预加载内容必须谨慎：预加载过多会延长开机、占用内存并增加写时复制。

### 常见误区

- “每启动一个 App 都重新启动虚拟机”：不准确。App 进程通常由 Zygote fork 出来，随后再执行 App 入口。
- “init 启动所有 Android 服务”：不准确。init 启动 Zygote，Java 系统服务主要由 SystemServer 再启动。

### 源码入口与验证

```text
system/core/rootdir/init*.rc
frameworks/base/core/java/com/android/internal/os/ZygoteInit.java
frameworks/base/services/java/com/android/server/SystemServer.java
```

```bash
adb shell ps -A | grep -E 'init|zygote|system_server|surfaceflinger'
adb shell getprop sys.boot_completed
adb logcat -b system -d | grep -i 'SystemServer'
```

### 面试回答练习

**问：Android 从开机到桌面可用，大致发生了什么？**  
答：Bootloader 加载 Kernel，Kernel 启动 init。init 根据 rc 脚本挂载和初始化系统，启动 Zygote 等关键进程。Zygote 预加载运行时资源并 fork SystemServer；SystemServer 顺序启动 AMS、WMS、PMS 等核心服务。之后 Launcher 作为普通应用被启动，系统才呈现桌面。不同 Android 版本和厂商的服务细节会不同，但这条进程主线不变。

---

## 2. AMS、ATMS、WMS：谁管理什么？

### 一句话结论

Activity/Task 的调度由 ActivityTaskManager（ATMS）主导，进程与内存级别等由 ActivityManager（AMS）承担；WindowManager（WMS）管理窗口的层级、焦点、尺寸、转场和 Surface 生命周期。

### 必须区分的职责

| 组件 | 主要职责 | 不负责什么 |
| --- | --- | --- |
| AMS | 进程记录、四大组件调度协作、进程优先级、ANR/内存管理协作 | 不直接合成屏幕像素 |
| ATMS | Activity、Task、TaskFragment、back stack、启动/切换协调 | 不直接管理 Linux 调度 |
| WMS | Window、焦点、层级、方向、动画、输入窗口信息、Surface 协调 | 不绘制 View 内容 |
| SurfaceFlinger | 合成各 Surface buffer，交给 HWC/显示设备 | 不决定 Activity back stack |

从 Android 10 起，Activity/Task 相关职责从 AMS 中拆分出 ATMS。因此面试中把“AMS 启动 Activity”说成历史上的简写可以，但应补充：现代版本中 Activity task 调度的中心是 ATMS，AMS 仍协作启动目标进程。

### Activity 启动（简化但正确的骨架）

```text
App 调 startActivity()
  ↓ Binder
ATMS：解析 intent、任务栈/启动模式/权限检查
  ↓
AMS：目标进程不存在则请求 Zygote fork
  ↓ Binder
目标应用 ActivityThread 收到 scheduleTransaction
  ↓
ActivityThread 创建 Activity、回调生命周期
  ↓
WMS 为窗口建立/管理 Surface，首帧提交后显示
```

这不是每个内部方法的精确名称，但已覆盖面试所需的进程边界和职责。深入时再追 `ActivityTaskManagerService`、`ActivityStarter`、`ClientTransaction`、`ActivityThread`。

### 高频追问：为什么启动 Activity 需要 WMS？

Activity 是应用组件，不等于屏幕上的窗口。它的 View 要附着到 `Window`，而 Window 需要与其他窗口竞争焦点、z-order、尺寸、旋转与动画；这些全局显示规则由 WMS 统一维护。随后 WMS 为应用关联可提交 buffer 的 Surface，内容合成由 SurfaceFlinger 完成。

### 高频追问：`onResume()` 后是否一定已经显示到屏幕？

不一定。生命周期回调描述组件状态；真正“看见首帧”还依赖 View traversal、buffer 提交、SurfaceFlinger 合成和显示刷新。不要把生命周期与像素呈现等同。

### 源码入口

```text
frameworks/base/services/core/java/com/android/server/am/ActivityManagerService.java
frameworks/base/services/core/java/com/android/server/wm/ActivityTaskManagerService.java
frameworks/base/services/core/java/com/android/server/wm/ActivityStarter.java
frameworks/base/core/java/android/app/ActivityThread.java
frameworks/base/services/core/java/com/android/server/wm/WindowManagerService.java
```

### 验证

```bash
adb shell dumpsys activity activities
adb shell dumpsys activity processes
adb shell dumpsys window windows
adb shell dumpsys window policy
```

---

## 3. Binder：Framework 最核心的 IPC

### 一句话结论

Binder 是 Android 的本地进程间通信机制。它由内核 Binder driver 负责传递 transaction，客户端拿到 Proxy，服务端暴露 Stub；ServiceManager 负责名字到服务 Binder 的查询。

### 调用链

```text
Client process                         Server process
Manager → IxxxService.Proxy  --Binder--> IxxxService.Stub → 实现类
                │                         │
                └── Binder driver /dev/binder ──┘
                         ↑
                 ServiceManager：服务注册/查找
```

### 必须理解的 8 个点

1. **Binder 是本机 IPC，不是网络 RPC。** 设备内不同进程经由 Binder driver 通信。
2. **Proxy/Stub 是接口两侧的代理。** AIDL 编译会生成相关样板；调用方像调用本地接口一样调用 Proxy，服务端 Stub 解包再转给实现。
3. **Parcel 是传输容器。** 参数会被 marshal/unmarshal；不要用 Binder 传大对象或高频大数据。
4. **Binder 对象可作为能力句柄传递。** 因而 callback、listener、death recipient 都成为可能。
5. **同步调用会占用调用线程。** 服务端慢、锁竞争或死锁会把等待传回客户端；不能把它想成“天然异步”。
6. **`oneway` 是异步投递，不保证立即完成。** 它仍会排队，且通常不适合需要返回值/强顺序语义的场景。
7. **服务端必须做权限校验。** 不能相信客户端传入的 package name；使用调用方 UID/PID 与系统权限模型判断。
8. **客户端要考虑服务死亡。** 长连接/关键服务可通过 `linkToDeath`、重连和状态恢复处理。

AIDL 使用 Binder driver 完成调用；官方文档也明确指出，可通过 `dumpsys` 和 `service` 命令检查、测试设备服务。[AIDL 官方说明](https://source.android.com/docs/core/architecture/aidl)

### 高频追问：Binder 为什么比传统 Socket IPC 更适合 Android Framework？

不是简单的“Binder 一定更快”。Android 选择 Binder 还因为它提供了面向对象的引用传递、调用方 UID/PID 身份、服务发现、死亡通知和较好的权限整合，适合系统服务模型。它的传输路径也避免了传统管道/Socket 常见的多次用户态拷贝。Socket 仍适合网络通信或某些 native 协议；选择取决于边界，不是性能口号。

### 高频追问：一次同步 Binder 调用发生了什么？

客户端 Proxy 将方法号和参数写入 Parcel，进入内核 Binder driver；driver 找到目标 Binder 实体并唤醒服务端 Binder 线程；Stub 读取 transaction 后调用本地实现；返回值再以 reply transaction 回到客户端。服务端可以通过 Binder API 取得真实调用 UID 来做权限检查。

### 高频追问：大数据为什么不应走 Binder？

Binder transaction 有大小限制和内存开销，过大会报 `TransactionTooLargeException` 或造成系统压力。图片、视频、连续传感器数据等应通过共享内存、文件描述符、Provider/文件、BufferQueue 等专用通道传递；Binder 只传控制命令或句柄。

### 实验

在前述 `CarMockService` 中加入：

```kotlin
val uid = Binder.getCallingUid()
```

分别从允许和不允许的客户端调用，并记录 UID、`SecurityException` 和服务端日志。然后让服务进程被杀，观察客户端回调和重连策略。

---

## 4. AIDL、Messenger、普通 Binder：怎样选？

### 一句话结论

先判断是否真的跨进程，再决定 IPC 复杂度。AIDL 适合多客户端并发、接口明确的跨进程调用；简单同进程绑定可直接用普通 Binder；需要串行消息处理时可考虑 Messenger。

| 方案 | 适用情形 | 特点与风险 |
| --- | --- | --- |
| 普通 `Binder` | 同应用、通常同进程的 bound service | 最简单，不自动跨进程代理 |
| Messenger | 消息模型、需要服务端串行处理 | 基于 Binder + Handler，吞吐/接口表达能力有限 |
| AIDL | 跨 App/跨进程、并发 IPC、强接口契约 | 要处理线程安全、版本兼容、死亡与权限 |
| ContentProvider | 以数据读写为主要模型 | 不是通用 RPC |

### 高频追问：AIDL 服务端方法跑在哪个线程？

默认不是 UI 主线程，而是 Binder 线程池中的线程。因此实现必须线程安全，不能假设调用顺序；若要更新 UI 或串行修改状态，应显式切到目标 Handler/Executor。只有你自己把调用转发到主线程时，才会在那里执行。

### 高频追问：AIDL 接口怎么演进？

已发布的跨应用接口不能随意删除或修改已有方法语义/参数，因为旧客户端仍可能调用。新增方法通常放在末尾，数据对象也需要兼容演进。平台模块或 HAL 的长期接口还要学习 Stable AIDL 的版本化约束；应用级 AIDL 与平台 Stable AIDL 不要混为一谈。

---

## 5. Handler、Looper、MessageQueue：线程通信为何不会一直轮询？

### 一句话结论

每个有 Looper 的线程用 MessageQueue 排队任务；Looper 在循环中取消息并分发给 Handler。主线程的 Looper 由系统创建，因而 UI 回调、生命周期和大部分 View 操作默认发生在主线程。

### 主线程骨架

```text
ActivityThread.main()
  ↓ prepareMainLooper()
Looper.loop()
  ↓ 不断从 MessageQueue.next() 取消息
Handler.dispatchMessage()
  ↓
Runnable / Handler.handleMessage() / framework 回调
```

### 关键点

- `Handler` 不是线程，只是投递与处理消息的对象。
- `Looper` 通常一线程一个；`MessageQueue` 是按执行时间排序的队列，不是简单 FIFO。
- 空闲时 MessageQueue 在 native 层等待事件（如 epoll），不会无意义地忙轮询。
- `postDelayed()` 只是指定“最早执行时间”，不承诺精确时刻；主线程繁忙时会延后。
- Message 持有外部对象可能造成泄漏。Activity 销毁后要移除回调/消息，或使用生命周期安全的协程等机制。

### 高频追问：为什么不能在子线程直接更新 View？

View 树、measure/layout/draw 和输入事件依赖单线程访问模型，以避免大量锁和状态竞争。Android 要求拥有 ViewRoot 的线程（通常主线程）更新 UI；跨线程应把任务投递回主线程。底层不是每个 View 都做全面同步保护。

### 高频追问：同步屏障是什么？

MessageQueue 可以插入同步屏障，临时阻塞普通同步消息，让异步消息（典型如与渲染相关的 choreographer 回调）优先处理。它是为了让帧调度更及时，业务代码不要随意使用或遗留屏障，否则可能导致消息“卡住”。

### 实验

在主线程连续执行 3 秒计算，观察点击无响应；改为后台线程计算后，通过主线程 Handler 更新结果。用 `adb shell dumpsys activity top` 和 Perfetto/Android Studio profiler 对比主线程状态。

---

## 6. Activity 生命周期、任务栈与进程优先级

### 一句话结论

生命周期描述 Activity 在用户可见性和交互上的状态；任务栈描述用户导航历史；进程优先级决定内存紧张时谁更可能被回收。这三者有关联，但绝不是同一件事。

### 必背但不要死背的状态关系

```text
创建：onCreate → onStart → onResume
被遮挡/失焦：onPause
完全不可见：onStop
销毁：onDestroy（正常销毁时回调；进程被直接杀死时不保证）
```

- `onPause()` 要短，不能做网络、数据库大任务或长动画清理。
- `onSaveInstanceState()` 用于保存可恢复 UI 状态，不能替代持久化业务数据。
- 配置变化可能重建 Activity；ViewModel 可跨配置变化存活，但不能抵抗进程死亡。
- 后台 Activity 不等于进程一定存在；系统可随时在内存压力下回收低优先级进程。

### 高频追问：进程优先级由什么决定？

主要由进程承载的组件和它与前台组件的关系决定，粗略可理解为：前台/正在交互 > 可见 > 前台服务/重要服务 > 后台服务 > cached。AMS 根据状态更新 `oom_adj`（实现细节会随版本变化）；`lmkd` 在内存压力下更倾向杀掉低重要性进程。`lmkd` 是用户空间守护进程，通过内存压力信息作出回收/杀进程决策。[官方 lmkd 文档](https://source.android.com/docs/core/perf/lmkd)

### 高频追问：为什么 Service 不一定“不被杀”？

Service 只是组件类型，不是永生符。后台 service、绑定关系、前台 service、可见 Activity 等会影响进程重要性；内存极端紧张时系统仍可能回收。正确做法是让业务具备恢复能力：持久化关键状态、使用合规的任务调度/前台服务、处理重启，而不是试图“锁死进程”。

### 验证

```bash
adb shell dumpsys activity processes
adb shell ps -A -o PID,PPID,NAME,ARGS
adb shell dumpsys meminfo <package>
```

---

## 7. View 绘制、Choreographer 与掉帧

### 一句话结论

一次 View traversal 的核心是 `measure → layout → draw`；Choreographer 把输入、动画和绘制工作对齐 VSync，应用产出 buffer 后由 SurfaceFlinger 在刷新节奏中合成显示。

### 渲染链路

```text
VSync
  ↓
Choreographer 回调（input / animation / traversal）
  ↓
ViewRootImpl.performTraversals()
  ↓
measure → layout → draw
  ↓
RenderThread / GPU 产出 buffer
  ↓
SurfaceFlinger 合成 → HWC → Display
```

### 高频追问：`invalidate()` 与 `requestLayout()` 的区别？

- `invalidate()`：标记需要重绘，主要触发 draw；适用于外观变化且尺寸/位置不变。
- `requestLayout()`：请求重新 measure/layout，通常后续也会 draw；适用于尺寸、位置或布局约束变化。

二者最终何时执行由下一次 traversal 决定，不能把它理解为“调用后立即画”。

### 高频追问：为什么会掉帧？

显示有 VSync 预算。如果主线程的输入/动画/布局绘制或 RenderThread/GPU 不能在合适时机交付下一帧，SurfaceFlinger 只能复用旧 buffer，用户看到卡顿。常见根因：主线程 I/O、复杂/重复布局、频繁 GC、过度绘制、bitmap 解码、锁竞争、Binder 调用阻塞，或者 GPU/HWC 负载。

### WMS 与 SurfaceFlinger 的分工

WMS 管理 Window 的生命周期、焦点、旋转、位置、z-order 等元数据；SurfaceFlinger 接收可见 layer 的 buffer 并进行合成、输出到显示。官方图形架构文档也明确了 WMS 提供窗口/Surface 元数据、SurfaceFlinger 收集并合成 buffer 的职责边界。[SurfaceFlinger 与 WMS](https://source.android.com/docs/core/graphics/surfaceflinger-windowmanager)

### 实验

用一个自定义 View 分别调用 `invalidate()` 和 `requestLayout()`，在 `onMeasure`、`onLayout`、`onDraw` 打日志。滑动列表时故意在 `onBindViewHolder` 做耗时操作，再用 Perfetto 观察帧与主线程调度。

---

## 8. 输入事件：从触摸屏到 View

### 一句话结论

原始触摸事件先被读取和解析，再由 InputDispatcher 根据 WMS 提供的窗口、焦点和触摸目标分发到对应应用；应用的 ViewRoot 再把事件分发到 View 树。

### 主链路

```text
Kernel input event
  ↓
EventHub → InputReader（解析设备/坐标）
  ↓
InputDispatcher（目标窗口、超时、分发）
  ↓ Binder/socket 到 App
ViewRootImpl → DecorView → ViewGroup.dispatchTouchEvent → View
```

### 高频追问：触摸事件为何先经过 WMS？

系统必须先知道当前哪个 Window 有焦点、谁在最上层、坐标落在哪个可触摸区域、是否有输入法/系统弹窗/分屏等。因此 WMS 提供窗口信息给输入系统；应用内部才由 ViewGroup 按拦截与消费规则把事件下发。

### 高频追问：`dispatchTouchEvent`、`onInterceptTouchEvent`、`onTouchEvent` 的关系？

`dispatchTouchEvent` 是事件进入当前 View/Group 的总入口。ViewGroup 可通过 `onInterceptTouchEvent` 决定是否截获后续处理权；未截获时事件继续传给子 View。最终由 `onTouchEvent` 或 listener 消费。一次手势中的 `DOWN` 是否被消费会影响后续 MOVE/UP 能否继续收到。

### 与 ANR 的关系

输入分发需要应用及时处理；前台主线程长期阻塞会造成输入超时。Android 官方面向 App 的说明以 5 秒未响应输入作为典型 ANR 条件，并提醒具体超时可因设备/OEM 而异。[ANR 官方指南](https://developer.android.com/topic/performance/anrs/keep-your-app-responsive)

---

## 9. ANR：不要只背“主线程不能耗时”

### 一句话结论

ANR 是系统认为应用在规定时间内没有完成关键响应的结果，常表现为主线程阻塞，但也可能是 Binder 服务慢、锁竞争、CPU 没被调度或系统整体压力导致。

### 常见类型

| 场景 | 常见原因 | 首先看什么 |
| --- | --- | --- |
| Input dispatch | 主线程 I/O、死锁、长计算、同步 Binder 阻塞 | `main` 线程堆栈、InputDispatcher/ANR 日志 |
| Broadcast | `onReceive` 执行过久、`goAsync()` 未及时 finish | receiver 堆栈、事件日志 |
| Service/Job | 生命周期回调或执行超时 | 系统日志、任务运行记录 |
| ContentProvider | 启动/查询阻塞且调用链卡住 | Binder 调用链、provider 线程 |

### 标准排查步骤

1. 取 ANR 时刻的 traces/bugreport/logcat，不要先改代码。
2. 看主线程处于 `RUNNING`、`RUNNABLE`、`BLOCKED`、`WAITING` 还是 Binder 等待。
3. 若卡在 Binder：继续找服务端线程和锁；若线程 Runnable 却不执行：看 CPU 调度/系统负载。
4. 使用 Perfetto 把 app 主线程、binder、sched、frame timeline 放到同一时间轴验证因果。
5. 修复后重复压测，不能只凭“偶尔没复现”结案。

### 高频追问：主线程卡在 Binder 算谁的问题？

不能武断归为客户端或服务端。客户端体验上发生 ANR，但根因可能是服务端慢、服务端锁死、依赖服务形成调用环，甚至系统负载使双方得不到 CPU。要沿 Binder transaction 追踪，并用 trace 区分“线程未被调度”和“线程执行很慢”。

---

## 10. PackageManager、安装与 APK 生命周期

### 一句话结论

PackageManagerService（PMS）维护已安装包、组件、权限、签名和 intent 解析等系统级包信息；安装不仅是复制 APK，还包含解析、校验、权限/用户状态处理、dex 优化等过程。

### 安装的高层过程

```text
PackageInstaller / adb install
  ↓
installd 与包管理流程：写入、校验、解析 Manifest
  ↓
PMS：登记包/组件/签名/权限/用户状态
  ↓
ART dexopt（按条件、可能延后）
  ↓
Launcher / Intent resolver 可发现组件
```

### 高频追问：安装路径在哪？

现代 Android 使用分区/用户隔离、增量安装和模块化机制，具体路径不能死记。应答重点是：APK code、每用户数据、包元数据分别处于不同受保护位置；PMS 维护逻辑包信息，`installd` 处理底层文件与 dex 相关工作。面试时可用 `adb shell pm path <package>` 验证具体设备上的 code path。

### 高频追问：Intent 如何找到目标 Activity？

显式 Intent 直接指定组件；隐式 Intent 由 PMS 根据 action、category、data 等匹配已注册的 intent-filter，并做权限、exported、用户等检查。多个候选时会走 resolver/默认处理规则。

### 验证

```bash
adb shell pm path <package>
adb shell dumpsys package <package>
adb shell cmd package resolve-activity --brief -a android.intent.action.VIEW -d https://example.com
```

---

## 11. 权限、签名、SELinux：三层边界不要混淆

### 一句话结论

Android 的访问控制不是一道门：应用 sandbox/UID、Manifest 权限及签名能力、System API/隐藏 API、SELinux MAC 等共同限制访问。Root 只能改变一部分条件，不能替代正确的平台集成。

### 分层理解

| 层 | 核心问题 | 典型失败表现 |
| --- | --- | --- |
| UID / sandbox | 这个进程天然能访问谁的数据？ | 文件权限、跨应用数据隔离 |
| Manifest / runtime permission | 用户或系统是否授予功能权限？ | `SecurityException` |
| signature / privileged | 是否由平台认可签名或白名单包持有？ | permission denied / install 解析限制 |
| Hidden API / SystemApi | 此 API 是否属于普通 SDK？ | 编译/运行时隐藏 API 限制 |
| SELinux | 此进程 domain 是否可对目标 type 做操作？ | `avc: denied` |

### 高频追问：把 APK 放进 `/system/priv-app` 就有所有权限吗？

不会。priv-app 只是预装应用的一种位置/身份条件；某些 privileged permission 还需要平台配置白名单，并可能受签名、用户、SELinux 和 API 边界共同限制。更不应把“Root 手机上的一次手工成功”误认为可交付产品方案。

### 高频追问：Java permission 和 SELinux 有何不同？

Java permission 是 Framework 层对调用者能力的声明和检查，常能看到 `SecurityException`；SELinux 是内核强制访问控制，按进程 domain 与资源 type 判断，通常在内核/audit 日志中显示 `avc: denied`。前者通过 Manifest/签名/授予等策略管理，后者通过 sepolicy 管理；两者要同时正确。

### 验证

```bash
adb logcat -b all -d | grep -E 'avc: denied|SecurityException'
adb shell dumpsys package <package> | grep -i permission
adb shell id
```

---

## 12. System Service：从 App IPC 升级到平台能力

### 一句话结论

真正的 System Service 是 Framework 的长期能力单元：由 SystemServer 或 native 进程启动，向 ServiceManager 注册 Binder 服务，对外暴露受控 API，并处理权限、生命周期、并发和系统状态。

### 典型结构

```text
SDK / @SystemApi API
  ↓
Manager（对调用者友好的封装）
  ↓
AIDL IxxxService
  ↓ Binder
XxxService（system_server）
  ↓
权限检查、状态机、线程模型、native/HAL 依赖
```

### 新增最小 System Service 的正确学习顺序

1. 在 AOSP `userdebug` Emulator 上做，不先碰 Root 真机。
2. 只做一个 read-only 方法，先让服务由 SystemServer 启动并可 `dumpsys`。
3. 加 AIDL 并从 shell/test app 调用，记录调用 UID。
4. 加明确的 signature 权限或限定测试 UID，验证拒绝路径。
5. 最后才加 Manager、`SystemServiceRegistry`、shell command、SELinux 与 HAL。

### 高频追问：为什么 ServiceManager 很重要？

Binder 对象本身只是句柄。ServiceManager 让服务端以名字注册、客户端按名字查询，建立系统服务发现机制；它也是权限和启动依赖分析时的重要观察点。`adb shell service list` 能列出服务，但“看见服务名”不代表普通 App 有权限调用其隐藏接口。

### 源码入口

```text
frameworks/base/core/java/android/os/ServiceManager.java
frameworks/base/core/java/android/app/SystemServiceRegistry.java
frameworks/base/services/core/java/com/android/server/SystemService.java
frameworks/base/services/java/com/android/server/SystemServer.java
```

---

## 13. 读源码的方法：从一条真实调用链开始

### 推荐的三条线

| 学习目标 | 从哪里开始 | 追到哪里为止 |
| --- | --- | --- |
| 启动 Activity | `Context.startActivity` | ATMS / `ActivityThread` / WMS |
| 获取系统服务 | `Context.getSystemService` | `SystemServiceRegistry` / Manager / AIDL / Service |
| 电源或属性服务 | 一个公开 Manager 方法 | Binder、权限检查、服务端状态更新 |

### 每次阅读只回答五个问题

1. 调用发生在哪个进程、哪个线程？
2. 这里是否穿过 Binder？接口是什么？
3. 状态存在哪个对象，谁负责并发？
4. 权限/调用 UID 在哪里检查？
5. 出错时日志、异常或 `dumpsys` 从哪里能看到？

不要第一天就打开 `frameworks/base` 从头读到尾。先选 `PowerManager`、`ActivityManager` 或你自己的 `CarMockService`，用 IDE 的 Find Usages 和调用栈向下追。

---

## 14. 高频问题速答清单

以下问题可以在不看资料时用 1–2 分钟回答；答不完整就回到对应章节和源码入口。

1. Android 开机后为什么先有 init、再有 Zygote、最后有 SystemServer？
2. Zygote fork 的收益和 Copy-on-Write 的代价是什么？
3. AMS、ATMS、WMS、SurfaceFlinger 各自的边界？
4. 启动一个不存在进程里的 Activity，系统怎样拉起它？
5. Binder 的 Proxy/Stub、Parcel、ServiceManager 分别做什么？
6. Binder 同步调用为什么可能导致 ANR？
7. AIDL 方法为什么必须线程安全？如何处理客户端死亡？
8. 普通 Binder、AIDL、Messenger 如何选择？
9. 主线程 Looper 为什么不会一直占 CPU 轮询？
10. `postDelayed` 为什么不精确？
11. `invalidate` 和 `requestLayout` 有何差别？
12. 从一次 VSync 到屏幕显示经历哪些阶段？
13. WMS 为什么要参与输入分发？
14. `onResume` 与首帧显示为何不是同一时刻？
15. Service 为什么仍会被杀？进程优先级大致怎么决定？
16. ANR 如何判断是自己代码、Binder 服务端还是系统调度问题？
17. 隐式 Intent 是谁解析的？为什么要有 `exported` 和权限检查？
18. signature permission、privileged permission、SELinux 分别在哪层生效？
19. 普通 App Service 与 SystemServer 中 System Service 的根本差别？
20. 新增 System Service 后如何验证“注册成功、权限正确、状态可观察”？

## 15. 两周后的自测任务

不用背诵，做一个 10 分钟讲解录音或文字稿，主题是：

> 点击 App 的“读取模拟车速”按钮后，从 View 的 click listener 开始，数据经过 Handler、Binder/AIDL、CarMockService，再返回 UI 的全过程；请标明进程、线程、权限检查点与服务死亡时的处理。

如果你能清楚回答这四件事，就已经从普通 Android 应用开发进入了 Framework 思维：

- 哪个对象只存在于本进程，哪个是跨进程代理；
- 系统服务和 App 服务的边界；
- 什么时候必须考虑线程、权限和生命周期；
- 每一个结论该用什么命令、日志或 trace 证明。
