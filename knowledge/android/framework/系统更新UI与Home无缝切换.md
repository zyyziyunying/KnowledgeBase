# 系统更新UI与Home无缝切换

## 一句话结论

A/B OTA 更新 Home 时，新 APK 已在重启前写入新槽位/快照，重启后随新系统正常扫描；PackageInstaller staged session 则在 PMS `systemReady` 末尾恢复会话并安装 APK 部分。正常 AOSP 开机路径会等待必要系统窗口绘制后显式结束 bootanimation，因而能避免在已显示的旧 Home 上原地换包；但 WMS 保留 boot timeout 后强制亮屏的失败分支，所以这是防闪设计而不是"绝对无黑屏"的设备级保证。运行态 `pm install -r` + 重启 Home 没有开机覆盖层，才需要额外的更新幕布或首帧交接。

> **适用边界**：本文以 AOSP 固定源码 revision 为事实源，最新核对日期为 2026-08-20。frameworks/base 统一钉在 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`（与启动、Home/SystemUI、系统应用更新证据包同一基线）；recovery 钉在 `9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c`。关键结论、SHA-256 与可执行断言记录在 [系统更新UI与Home无缝切换证据包](../../../evidence/android/framework/update-ui/manifest.json)。GMS 的更新屏（`com.google.android.gms`）是闭源实现，只作行业惯例观察，不构成 AOSP 事实源。A/B OTA、PackageInstaller staged session 和 recovery 安装的边界见 [系统应用更新与 OTA](%E7%B3%BB%E7%BB%9F%E5%BA%94%E7%94%A8%E6%9B%B4%E6%96%B0%E4%B8%8EOTA.md)，本文只维护视觉交接和回退机制。

## 先纠正前提：黑屏不是 OTA 的必然产物

两条换包路径的视觉结果完全不同：

- **A/B OTA 路径**：`update_engine` 在重启前写好非当前槽位/快照，设备重启后从新系统启动，PMS 在开机扫描时看到新 Home；它不经过 `restoreAndApplyStagedSessionIfNeeded`。
- **PackageInstaller staged 路径**：重启后在 PMS `systemReady` 末尾恢复 staged 会话，并由 `StagingManager` 安装其中的 APK 部分（见系统应用更新证据包 claim upd-004/upd-013；若会话含 APEX，APEX 已由 `apexd` 更早激活）。正常路径下 bootanim 等待必要系统窗口绘制后退出；若超过 boot timeout，WMS 会强制亮屏，因此仍需目标设备验证实际过渡。
- **in-place 路径（运行态换包）**：旧 Home 进程被冻结/杀掉（见系统应用更新证据包 claim upd-006/upd-007），home task 区域没有任何窗口接管，直到新 launcher 首帧绘制前就是"黑一下"。注意 SystemUI 是独立进程仍在绘制，所以通常只黑 home task 区域而非全屏；若 SystemUI 也被替换，才会全屏黑。

## 开机动画何时退场（核心机制）

bootanim 的退场是系统显式触发的，链条在固定 revision 中完整可见：

```text
bootanim.rc：service bootanim /system/bin/bootanimation（core/animation class、disabled、oneshot）
        ↓
BootAnimation::checkExit()：轮询属性 service.bootanim.exit
        ↓ 属性置 1 后 requestExit()
WMS.enableScreenAfterBoot()                 (WindowManagerService.java:3847)
  → performEnableScreen
      → SystemProperties.set("service.bootanim.exit", "1")   (:3952)
      → SurfaceControl.bootFinished()                        (:3961)
      → mActivityManager.bootAnimationComplete()             (:3976)
        ↓
AMS.bootAnimationComplete()                 (ActivityManagerService.java:5321)
  → mBootAnimationComplete = true → finishBooting()
AMS.ensureBootCompleted()                   (:5414)
  → finishBooting()（仍在 booting 时）
  → mAtmInternal.enableScreenAfterBoot(mBooted)              (:5429)

失败兜底：WMS.enableScreenAfterBoot() 安排名义 30s × Build.HW_TIMEOUT_MULTIPLIER 的 BOOT_TIMEOUT
  → performBootTimeout() 将 mForceDisplayEnabled = true
  → performEnableScreen() 跳过窗口与 bootanim 完成等待
```

含义：正常路径会在必要系统窗口已绘制、bootanim 进程已退出后再正式启用屏幕和输入；Keyguard 与 Home 的实际可见顺序取决于设备状态。boot timeout 是为了不让设备无限卡在开机动画，也说明静态源码只能证明正常设计和失败分支，不能代替 OEM 配置与设备级视觉验证。

## Framework 的防闪机制：ThemeHomeDelay

系统内存在"等就绪信号再显示 Home"的成熟模式：AMS 的 ThemeHomeDelay 允许**推迟 Home 启动**，直到 `ThemeOverlayController` 报告主题就绪（`setThemeOverlayReady`），超时 `HOME_LAUNCH_TIMEOUT_MS = 15000` 兜底强启。运行态更新幕布（见下）本质上是把同一模式搬到更新场景。

## Windows 式更新屏的 Android 对应物

| Windows 现象 | Android 对应物 | 实现层 |
| --- | --- | --- |
| "Working on updates" 关机更新 | update_engine A/B 后台安装 + 重启切换槽位 | 系统层，无需 UI |
| non-A/B/recovery 安装路径中的"正在更新"屏 | recovery minui：`ScreenRecoveryUI::SetSystemUpdateText` 选择 `installing_text` / `installing_security_text` 位图 | recovery（minui 直接画 framebuffer） |
| 开机动画 | bootanimation + 上面的显式退场链 | 系统层 |

补充观察：Google 设备的模块更新屏（`com.google.android.gms.update.SystemUpdateActivity`）是闭源实现，其公开原理是：由特权应用在开机早期拉起全屏 Activity（`showWhenLocked`、`FLAG_KEEP_SCREEN_ON`），从 update_engine 状态读进度画进度条。厂商自研更新屏可以照此原理实现，但这是实现模式讨论，不是 AOSP 事实。

## 自研硬件的方案矩阵

按推荐度排序：

1. **A/B OTA 或 staged + 重启（推荐，但机制不同）**：A/B OTA 从新系统扫描 Home，staged session 在 PMS `systemReady` 恢复会话并安装 APK 部分；两者都避免对正在显示的旧 Home 原地换包。正常 AOSP 路径期望是"开机动画/锁屏 → 新 Home"，但仍要验证 boot timeout 和目标设备首帧。要更"Windows"，可在 boot 早期拉起自研更新屏直到新 Home 首帧。
2. **更新幕布（不重启的硬需求）**：顺序严格为——先盖全屏"正在更新"层（priv-app 或 WindowManager 加 Surface）→ `pm install -r` → 杀旧 Home → 显式拉起新 Home → 等首帧就绪信号 → 撤幕布。任何一步顺序颠倒都会露出黑屏。
3. **冻结帧快照手交（最顺滑）**：`SurfaceControl` 截下旧 Home 当前画面作幕布（或新 Home 的 SplashScreen 背景）→ 换包 → 新 Home 首帧后淡出快照。用户看到"画面定格 → 新桌面"。
4. **SplashScreen（最低成本）**：Android 12+ 让冷启动间隙显示品牌 splash，把黑屏换成有内容的过渡。
5. **熄屏/调暗兜底**：换包前亮度置 0 或熄屏，完成后恢复。体验一般，仅作兜底。

**反模式**：无覆盖的 `install -r` + 重启 Home，即"黑闪一下"的来源。

## 候选架构：最小权限的运行态交接

> **状态**：以下是自研硬件上的候选方案，不代表 AOSP 已提供完整实现，也尚未经过目标设备、Keyguard、多显示器、用户切换、异常重启和 crash-loop 验证。固定源码只能确认权限保护级别与既有组件边界，不能证明视觉连续性。

推荐把职责拆成三个独立安全边界，而不是让 Home 或一个万能 APK 同时持有安装、系统窗口和输入权限：

| 组件 | 建议身份与最小能力 | 明确不承担 |
| --- | --- | --- |
| Home | OEM 自有签名；继续作为同包名、同组件的 `ROLE_HOME` 持有者 | 不安装 APK，不管理角色，不持有全局窗口或输入权限 |
| `UpdateCoordinator` | `/product` 或 `/system_ext` 的独立 priv-app；优先只申请 `INSTALL_PACKAGE_UPDATES` 与 `MANAGE_ROLLBACKS`；通过受签名权限保护的窄 Binder 接口请求显示或撤销幕布 | 不持有 `INTERNAL_SYSTEM_WINDOW`、`FILTER_EVENTS`、`INJECT_EVENTS`；非确有安装任意包的需求，不申请更宽的 `INSTALL_PACKAGES` |
| `TransitionRenderer` | 优先作为 SystemUI 内模块；若做独立 APK，则必须按所用窗口 API 满足 platform/module 身份与隐藏 API 边界；只负责幕布、焦点和交接状态机 | 不下载、解析或安装不可信 APK，不决定更新包来源 |

候选运行顺序：

```text
UpdateCoordinator 校验更新包、签名与回滚条件
  → TransitionRenderer 盖住 Home 并消费幕布窗口内输入
  → Coordinator 提交 Home 更新
  → 重新解析并启动当前 ROLE_HOME（同包更新通常无需改角色持有者）
  → 等待 Home 自有 readiness + Window/Surface 首帧观测
  → Renderer 原子撤幕布并把焦点交给 Home
  → 任一步超时或健康检查失败：保留幕布并触发回滚/恢复系统副本
```

### 权限高度与最小化边界

固定 AOSP revision 中的权限声明如下；`signature` 表示平台权限要求与定义者使用相同证书，核心平台权限通常就是 platform 签名；`signature|privileged` 是 OR 关系，既可由 platform 签名满足，也可由同分区 allowlist 中合格的 priv-app 满足。把 APK 放入 `priv-app` 本身不会获得 `signature` 权限，也不会绕过隐藏 API 与 SELinux。

| 能力 | 固定源码中的 protection level | 方案边界 |
| --- | --- | --- |
| 安装包更新 | `INSTALL_PACKAGE_UPDATES`：`signature|privileged` | 比完整安装能力更窄，是 `UpdateCoordinator` 的优先候选；固定源码仅在目标是现有包更新（`isUpdate`）时把它计入免用户确认的安装权限判定，其他版本、所有权与强制确认条件仍需验证；预装 manifest 与同分区 allowlist 必须在系统镜像中先建立权限基线 |
| 安装任意包 | `INSTALL_PACKAGES`：`signature|privileged` | 权限更宽，候选方案默认不申请 |
| APK 级回滚 | `MANAGE_ROLLBACKS`：`signature|privileged` | 可授给独立 coordinator，但仍需验证目标版本的 RollbackManager 策略与存储条件 |
| 静默变更角色持有者 | `MANAGE_ROLE_HOLDERS`：`signature|installer|module` | 同包、同组件更新通常不需要；切换成另一个 Home 包时才进入此边界，并仍受角色资格与版本实现约束 |
| 创建系统 UI 窗口 | `INTERNAL_SYSTEM_WINDOW`：`signature|module|recents` | 没有 `privileged` flag，普通 priv-app allowlist 不够；优先把 renderer 放进 SystemUI，而不是把 platform key 交给 updater |
| 冻结屏幕 | `FREEZE_SCREEN`：`signature` | 仅在证明确有必要时由系统 UI/窗口侧使用，不授给 coordinator 或 Home |
| 全局过滤输入 | `FILTER_EVENTS`：`signature` | 候选方案默认不用；普通路径由可聚焦幕布消费自身窗口输入 |
| 向任意窗口注入输入 | `INJECT_EVENTS`：`signature` | 无缝交接不需要，明确排除 |

`SYSTEM_ALERT_WINDOW` 只能提供应用 overlay，不等价于系统 UI 窗口身份；它不能作为 Keyguard、安全窗口、SystemUI 层级和多显示器交接的稳定保证。候选方案也不要求 `android.uid.system` 或 legacy shared UID：跨进程协作应由最窄 Binder API 在服务端按真实调用 UID 与自定义 `signature` 权限校验。

### 何时下沉到 Framework

按风险逐级升级，原型没有暴露下一级问题时不下沉：

1. **独立全屏 Activity**：无需系统窗口权限，可验证普通解锁、单显示器、前台触发场景；无法据此承诺 Keyguard 或异常窗口下连续。
2. **SystemUI `TransitionRenderer`（推荐候选）**：需要系统窗口、跨 Home 生命周期持有幕布或处理系统级焦点时使用；安装能力仍留在 coordinator。
3. **WM Shell / WMS / SurfaceControl 集成**：只有在必须跨 Home 进程死亡保留旧 Surface、原子交换图层/焦点/输入，或 SystemUI 原型仍存在可见空档时采用。新增 native Binder、SurfaceFlinger/InputFlinger 或设备节点访问时，还需独立设计 SELinux domain/type 规则；SELinux 不能替代 Framework permission。

这一分层的目标不是声称“绝对零黑帧”，而是让正常路径、超时路径、失败回滚和每项高权限都有明确所有者与验证入口。

## 兜底与回滚

data override 机制天然保留旧系统副本，给了回退后路：

- `adb shell pm uninstall <pkg>`：卸载 data override，删除路径调用 `enableSystemPackageLPw` 恢复系统副本生效（证据包 claim upd-ui-005）；
- Android 10+ 的 `pm rollback-app`（RollbackManager）整包回退；
- 对比：`pm install-existing` 的语义是"为（新）用户重新安装已装应用"，不恢复系统副本，勿混淆；
- 注意：新 Home crash-loop 时系统是否自动切换其他 Home 候选未验证（`ROLE_HOME` 默认值不变的模型不能直接推出切换行为，见待验证清单），因此自研硬件上"更新屏 + 可回退兜底"是刚需而非可选。

## 源码入口（固定 revision）

frameworks/base 均为 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`，SHA-256 与断言见证据包：

- [WindowManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/wm/WindowManagerService.java)：`enableScreenAfterBoot` / `performEnableScreen` 退场链与 `performBootTimeout` 强制亮屏兜底；
- [ActivityManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/am/ActivityManagerService.java)：`bootAnimationComplete` / `ensureBootCompleted` / `finishBooting` / ThemeHomeDelay；
- [SurfaceControl.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/view/SurfaceControl.java)：`bootFinished()`；
- [BootAnimation.cpp](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/cmds/bootanimation/BootAnimation.cpp)：`checkExit()` 轮询 `service.bootanim.exit`；
- [bootanim.rc](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/cmds/bootanimation/bootanim.rc)：bootanim 服务定义（core/animation class、disabled、oneshot）；
- [PackageManagerShellCommand.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageManagerShellCommand.java)：`uninstall` 命令与 `install-existing` 的真实语义；
- [InstallPackageHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/InstallPackageHelper.java)：删除路径 `restoreDisabledSystemPackageLIF` 恢复系统副本；
- [Settings.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/Settings.java)：`enableSystemPackageLPw` 回退路径（disable 侧见系统应用更新证据包）；
- [AndroidManifest.xml](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/res/AndroidManifest.xml)：候选架构涉及的安装、回滚、角色、系统窗口与输入权限 protection level；
- [PackageInstallerSession.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageInstallerSession.java)：`INSTALL_PACKAGE_UPDATES` 仅在 `isUpdate` 时计入安装权限判定的固定源码语义；
- [Permissions.md](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/permission/Permissions.md)：系统权限中 `signature`、`privileged` 与组合 flag 的授予关系；
- [screen_ui.cpp](https://android.googlesource.com/platform/bootable/recovery/+/9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c/recovery_ui/screen_ui.cpp)：recovery 更新屏位图选择（revision `9565b5ee790a4ae7acd0c6c04a2b3e0c7eeced3c`）。

## 设备上的只读验证

```bash
# bootanim 状态与退场属性
adb shell getprop init.svc.bootanim
adb shell getprop service.bootanim.exit

# 卸载 data override 恢复系统副本（更新 Home 后出问题的兜底）
adb shell pm uninstall <pkg>

# Home 解析是否仍正常
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME
```

这些命令回答"bootanim 是否还在跑、退场属性是否置位、能否回退、Home 解析是否正常"；"首帧已合成、用户可交互"仍需 Perfetto 与 SurfaceFlinger/输入观测，同 [Home/SystemUI 文档](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 的边界。

## 待验证清单

已由证据包断言的机制不在此列；以下仍待后续核对：

- [ ] GMS `SystemUpdateActivity` 的具体实现与启动时机（闭源，仅行业观察）；
- [ ] ThemeHomeDelay 的触发条件（哪些场景 Home 启动可延迟）与 `ThemeOverlayController` 的完整交互；
- [ ] `SurfaceControl.bootFinished()` 在 SurfaceFlinger 侧的完整行为；
- [ ] 快照手交（SurfaceControl 截图 + splash 注入）的设备级实现细节（z-order、输入屏蔽、多用户）；
- [ ] 候选 `UpdateCoordinator + SystemUI TransitionRenderer` 的目标版本 API 可用性、Binder 接口威胁模型与 platform key 暴露面；
- [ ] 候选架构在 Keyguard、多显示器、用户切换、后台启动限制、安装超时、Home crash-loop 和回滚失败下的状态机与真机视觉结果；
- [ ] 新 Home readiness 信号与 Window/Surface 首帧、焦点和实际输入可用之间的对应关系；
- [ ] 自研更新屏在目标设备上的最佳拉起时机（对应哪个 boot phase）；
- [ ] init 侧 `stop bootanim` 触发位置：已核对 core `a3b721a32242` 的 `rootdir/init.rc` 无该 trigger（仅有 `mkdir /data/misc/bootanim`），若存在于其他 rc 文件，其位置待定位；bootanim 退出本身以 `checkExit()` 轮询属性为准；
- [ ] 新 Home crash-loop 时系统是否自动切换 Home 候选（正文仅按 `ROLE_HOME` 解析模型说明，未验证实际切换行为）。

## 继续阅读

- [系统更新UI与Home无缝切换证据包](../../../evidence/android/framework/update-ui/manifest.json)：本文关键结论的固定源码、SHA-256 与可执行断言；
- [系统应用更新与 OTA](%E7%B3%BB%E7%BB%9F%E5%BA%94%E7%94%A8%E6%9B%B4%E6%96%B0%E4%B8%8EOTA.md)：换包安装机制（data override、staged、冻结/杀进程）；
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：Home 角色模型与 APK 边界的事实源；
- [Android 建设路线](../ROADMAP.md)：第二阶段（图形与显示链路）与本主题的规划关系。
