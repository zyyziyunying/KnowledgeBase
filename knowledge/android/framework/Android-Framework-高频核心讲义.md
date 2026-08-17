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

Android 启动不是一个进程从头执行到尾，而是一条跨越固件、内核和用户空间的接力链：Bootloader 校验并加载启动镜像，Linux Kernel 启动 PID 1 的 `init`，`init` 完成早期挂载与 SELinux 初始化后启动 native 服务和 Zygote，Zygote 再 fork 出 `system_server`；`system_server` 是大部分 Java Framework 核心系统服务的宿主进程。

> **适用边界**：本节以 AOSP `refs/heads/main` 为主要事实源，核对日期为 2026-08-14。Bootloader、分区、服务清单、Home 应用和启动耗时会随 Android 版本、设备形态与厂商实现变化；文中的稳定主线不等于所有设备拥有完全相同的启动细节。

本节的关键结论、固定 AOSP revision、源文件 SHA-256 和机器可执行断言记录在 [Android 启动证据包](../../../evidence/android/framework/boot/manifest.json)。正文负责解释机制，证据包负责证明“依据是什么、核对的是哪个版本”。

### 主链路

```text
SoC Boot ROM / 固件
        ↓
Bootloader：选择启动目标、Verified Boot、加载 Kernel 与 ramdisk/bootconfig
        ↓
Linux Kernel：驱动、调度、内存、根文件系统，启动 /init（PID 1）
        ↓
init：first stage → SELinux setup → second stage
        ├── 启动 servicemanager、surfaceflinger、netd 等 native 进程
        └── 根据 zygote rc 启动 app_process
                          ↓
                AndroidRuntime → ZygoteInit.main()
                          ↓ 预加载类/资源/共享库
                    fork system_server
                          ↓
          SystemServer → SystemServiceManager
                          ↓
   bootstrap / core / other / APEX system services
                          ↓
   systemReady → SystemUI + 当前用户/显示的 Home → boot completed
```

Bootloader 还可能处理 A/B slot、recovery、`boot`、`vendor_boot`、`init_boot` 等镜像，这些属于硬件和版本相关的启动前半段。AOSP 的 [Bootloader 概览](https://source.android.com/docs/core/architecture/bootloader) 给出了当前推荐流程。

### 1. Bootloader 与 Kernel 的边界

- Boot ROM 和 Bootloader 通常由 SoC/厂商实现，不属于 Android Framework。Bootloader 负责建立最低硬件环境、选择启动槽位或 recovery、执行 Verified Boot，并把 Kernel、ramdisk、设备树与 bootconfig 等放入内存。
- Kernel 解压并初始化 CPU、内存管理、调度器和驱动，然后启动用户空间的 `/init`。因此“Bootloader 加载 Kernel”是正确的高层概括，但真实设备并不只有单一 `boot.img`。
- Android 12 起，面向 Android 用户空间的部分 `androidboot.*` 参数可以通过 bootconfig 传递；Android 13 引入了用于通用 ramdisk 的 `init_boot` 分区，是否使用以及具体布局取决于 boot image header、GKI 和设备配置。阅读启动参数时需要同时考虑 Android 版本和启动镜像布局。

### 2. init 不是一个阶段，而是三段启动

现代 AOSP 的早期 init 分为三段，不能只概括成“解析 `init.rc`”：

1. **first-stage init**：建立继续启动所需的最小环境，挂载 `/dev`、`/proc` 和包含系统代码的 early-mount 分区；不同 ramdisk/system-as-root 配置还可能执行 switch root。
2. **SELinux setup**：加载或编译 SELinux policy，并通过重新执行 `init` 完成从 kernel domain 到 init domain 的切换。
3. **second-stage init**：初始化属性系统，解析系统、system_ext、vendor、odm 等分区中的 rc 文件，执行 action，管理 service，并进入持续的事件循环。

官方事实源：[init README：Early Init Boot Sequence](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/README.md#Early-Init-Boot-Sequence)。

second-stage init 的启动工作由 **event trigger + property trigger** 驱动，不是把所有 rc 文件简单地从上到下执行一遍。当前 AOSP 的核心事件顺序可以概括为：

```text
early-init → init → late-init
    → early-fs → fs → post-fs → late-fs → post-fs-data
    → post-fs-data-checkpointed → bpf-progs-loaded
    → zygote-start → early-boot → boot
```

具体 action 可能因加密状态、charger mode、OTA checkpoint、属性和厂商 rc 而跳过、延后或增加。完整语义见 [init trigger sequence](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/README.md#Trigger-Sequence)。

### 3. init 怎样启动 Zygote

以当前 64 位主 Zygote 为例，rc 中的关键定义是：

```text
service zygote /system/bin/app_process64 -Xzygote /system/bin \
    --zygote --start-system-server --socket-name=zygote
```

源码入口：[system/core/rootdir/init.zygote64.rc](https://android.googlesource.com/platform/system/core/+/refs/heads/main/rootdir/init.zygote64.rc)。这里说明两件容易混淆的事：

- `init` 直接创建的是 `app_process64`/Zygote 进程，不是 `system_server`。
- `--start-system-server` 参数告诉 `ZygoteInit` 在预加载之后 fork `system_server`。

`app_process` 的 native 入口创建 ART runtime，然后调用 `ZygoteInit.main()`；当前主链可写为：

```text
init rc
  → /system/bin/app_process[32|64]
  → AndroidRuntime.start("com.android.internal.os.ZygoteInit", ...)
  → ZygoteInit.main()
  → preload()
  → forkSystemServer()
  → ZygoteServer.runSelectLoop()
```

对应源码：[app_main.cpp](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/cmds/app_process/app_main.cpp)、[ZygoteInit.java](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/com/android/internal/os/ZygoteInit.java)。

当前 Android 使用 **ART**；Dalvik 是 Android 5.0 以前的历史实现。Zygote 会预加载常用类、资源、共享库和部分运行时状态，然后 fork 子进程。父子进程最初可以通过 Copy-on-Write 共享物理页，写入过的页才会产生私有副本。

应用进程通常也由 Zygote 创建：`system_server` 通过 Unix domain socket 向合适的 Zygote 请求进程，Zygote fork 后再设置 UID/GID、进程名、cgroup、SELinux 上下文及其他隔离参数。启用 USAP pool 时，可以先保留未特化的应用进程，再按请求完成 specialization。设备还可能同时存在主/次 32 位与 64 位 Zygote，以及专门的 WebView Zygote。见 [Zygote 官方说明](https://source.android.com/docs/core/runtime/zygote)。

### 4. system_server 怎样启动 Framework 服务

`system_server` 是 Zygote 的特殊子进程。子进程进入 `SystemServer.main()`/`run()` 后，会准备主 Looper、加载 `android_servers` native library、创建 System Context 和 `SystemServiceManager`，再按依赖顺序启动系统服务：

```text
startBootstrapServices()
  → 系统立足所需且依赖关系复杂的关键服务
startCoreServices()
  → 核心但不属于 bootstrap 的服务
startOtherServices()
  → WMS、网络、位置及大量其他平台服务
startApexServices()
  → 由可更新 APEX 模块定义的 System Service
```

分组不是安全级别，也不是所有服务严格完成后才进入下一组；部分初始化会并行或延迟。真正表达“依赖已经到达某个阶段”的机制还包括 `SystemServiceManager.startBootPhase()`，System Service 可通过 `onBootPhase()` 接收阶段通知。当前实现见 [SystemServer.java](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/java/com/android/server/SystemServer.java) 与 [SystemServiceManager.java](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/SystemServiceManager.java)。

`system_server` 也不是“所有系统服务的进程”。`servicemanager`、`surfaceflinger`、`netd`、`audioserver`、`cameraserver` 以及许多 HAL 服务仍是由 init 管理的独立 native 进程；SystemServer 中的 Java 服务会通过 Binder 与它们协作。

### 5. 从 systemReady 到用户可操作

“系统启动完成”不是单个瞬间，至少应区分以下里程碑。下面是理解用的阶段列表，不是所有设备、所有用户状态都严格一致的全序关系：

1. Zygote 已开始监听进程创建请求；
2. SystemServer 已创建并启动关键服务；
3. System Service 到达相应 boot phase，AMS/ATMS 进入 `systemReady`；
4. 系统解析并启动当前用户和显示对应的 Home Activity；
5. Home、SystemUI 或 Setup Wizard 等开始提交可见帧，WMS 再结合窗口绘制状态决定何时退出 Boot Animation、启用屏幕；
6. Framework 进入 `PHASE_BOOT_COMPLETED` 并设置全局属性 `sys.boot_completed=1`；
7. 用户生命周期再根据该用户是否处于 locked/unlocked、是否为 headless system user 等状态发送 `LOCKED_BOOT_COMPLETED`、`BOOT_COMPLETED` 等广播，较新版本还可能延迟向部分应用投递 boot-completed 广播；
8. 首屏真正完成绘制并能响应输入。

这些里程碑相互关联但不等价。`sys.boot_completed=1` 是 Framework 的启动完成标志，不能单独证明 Launcher 首帧已显示，也不能证明应用自己的初始化已经完成。Home 启动路径可从 [RootWindowContainer.startHomeOnAllDisplays()](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/wm/RootWindowContainer.java) 继续追踪；全局 boot completed 处理可从 [ActivityManagerService.finishBooting()](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/am/ActivityManagerService.java) 追踪，用户状态与广播则继续查看 [UserController](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/am/UserController.java)。[WindowManagerService.performEnableScreen()](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/wm/WindowManagerService.java) 则展示了另一条控制路径：等待必要窗口、请求退出 Boot Animation、通知 SurfaceControl boot finished、启用显示和输入分发。源码只能证明这些控制条件与调用关系；某台设备的首帧是否真正合成、输入是否及时响应，仍需 boot trace、SurfaceFlinger/窗口状态和实际输入观测。

“最后启动 Launcher，系统才呈现桌面”只适用于典型手机的简化回答。TV、Automotive、无屏设备、多显示设备、Setup Wizard、Keyguard 和厂商定制系统可能使用不同 Home 或拥有不同的“用户可用”终点。

Home 与 SystemUI 通常是两个独立 APK，也分别不同于 `system_server` 中的 AMS/ATMS/WMS 和 SurfaceFlinger 等 native 进程；其组件、进程、启动与替换边界见 [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)。

### 关键点

- `init` 是用户空间 PID 1，是 rc action/service、属性触发和子进程生命周期的管理者；它不是 Java Framework Service。
- `init` 启动 Zygote，Zygote fork `system_server`；不要把直接父子关系说反。
- 当前 Android Runtime 是 ART。Zygote 的价值既包括减少重复初始化，也包括通过 fork/COW 共享可共享的内存页。
- SystemServer 的服务启动顺序和 boot phase 都在表达依赖；只背 AMS/WMS/PMS 的类名无法解释启动问题。
- native daemon、HAL 服务、SystemServer 中的 Java Service 和普通应用分属不同进程边界，但主要通过 Binder 组成一个系统。
- “进程已存在”“服务已 ready”“boot completed”“首帧可见”“用户可交互”是不同的验证目标。

### 高频追问：Zygote 为什么能加快应用启动？

它把 ART runtime 的公共初始化以及常用类、资源和共享库的预加载提前到 fork 之前。fork 后父子进程先共享未修改的物理页，某一方写入时才发生 Copy-on-Write，因此既减少每个应用重复执行的初始化，也能共享一部分内存。代价是预加载内容必须按设备类型调优：预加载过多会增加开机工作和未使用内存，预加载过少则会把初始化和私有内存成本重新推给应用。官方配置入口见 [Configure ART：preloaded classes](https://source.android.com/docs/core/runtime/configure#boot_classpath_configuration)。

### 常见误区

- “init 直接启动 system_server”：不准确。init 启动带 `--start-system-server` 参数的 Zygote，再由 Zygote fork system_server。
- “每启动一个 App 都从零创建并初始化虚拟机”：不准确。App 进程通常由 Zygote/USAP fork 并 specialization，随后进入 `RuntimeInit`、`ActivityThread.main()` 等应用侧入口。
- “init 启动所有 Android 服务”：不准确。init 管理 native service 与 Zygote；大量 Java System Service 由 SystemServer/SystemServiceManager 创建。
- “SystemServer 启动完成就等于桌面已经显示”：不准确。Home 启动、Boot Animation、boot completed、首帧与可交互状态是不同里程碑。
- “所有设备只有一个 64 位 Zygote”：不准确。Zygote 数量取决于 ABI、产品配置和专用进程需求。
- “rc 文件就是一份顺序执行的 shell 脚本”：不准确。Android init language 由 action、service、event/property trigger 驱动，也不是通用 shell。

### 源码入口与验证

```text
system/core/init/README.md
system/core/init/first_stage_init.cpp
system/core/init/selinux.cpp
system/core/init/init.cpp
system/core/rootdir/init.rc
system/core/rootdir/init.zygote*.rc
frameworks/base/cmds/app_process/app_main.cpp
frameworks/base/core/java/com/android/internal/os/ZygoteInit.java
frameworks/base/services/java/com/android/server/SystemServer.java
frameworks/base/services/core/java/com/android/server/SystemServiceManager.java
frameworks/base/services/core/java/com/android/server/am/ActivityManagerService.java
frameworks/base/services/core/java/com/android/server/am/UserController.java
frameworks/base/services/core/java/com/android/server/wm/RootWindowContainer.java
frameworks/base/services/core/java/com/android/server/wm/WindowManagerService.java
```

先明确要验证哪个里程碑，再选择命令。以下命令只读，但不同 Android 版本或厂商 user build 可能限制字段、日志和 dumpsys 输出：

```bash
adb shell ps -A -o PID,PPID,USER,NAME | grep -E 'init|zygote|system_server|surfaceflinger|servicemanager'
adb shell getprop ro.zygote
adb shell getprop sys.boot_completed
adb shell getprop | grep -E 'ro\.boottime\.(init|zygote|system_server)'
adb shell dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'
adb shell dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'
adb logcat -b all -d | grep -Ei 'Zygote|SystemServer|boot_progress|boot_completed'
```

- `PID/PPID` 用于验证进程父子关系，但 Zygote 或 SystemServer 重启后需要结合日志判断本次启动链。
- `ro.boottime.init.first_stage`、`ro.boottime.init.selinux`、`ro.boottime.<service>` 可用于观察 init 记录的阶段和服务启动时间；单位与字段定义以当前 [init README 的 Boot timing](https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/README.md#Boot-timing) 为准。
- `dumpsys activity/window` 更接近“当前 Home/Activity 是否 resumed、有无焦点窗口”，但仍不等于首帧已由 SurfaceFlinger 合成或用户已经可以操作。
- 分析耗时时优先采集 boot trace/Perfetto，并把 Bootloader、Kernel、init、Zygote、SystemServer、Home 首帧分别设为测量区间；不要只比较一条 `sys.boot_completed` 时间。

### 面试回答练习

**问：Android 从开机到桌面可用，大致发生了什么？**  
答：Bootloader 完成启动校验、选择启动目标并加载 Kernel 和 ramdisk；Kernel 初始化后启动 PID 1 的 init。init 经历 first stage、SELinux setup 和 second stage，根据 rc trigger 挂载分区、建立属性系统、启动 native daemon 与 Zygote。Zygote 在 ART 中预加载公共类和资源，然后 fork system_server；SystemServer 创建 SystemServiceManager，按 bootstrap、core、other、APEX 等阶段启动 Framework 服务。AMS/ATMS 在系统 ready 后解析并启动当前设备的 Home，随后还要经历 Boot Animation 退出、boot completed 和首帧可交互等不同里程碑。手机上 Home 通常是 Launcher，但设备形态和厂商实现可能不同。

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
