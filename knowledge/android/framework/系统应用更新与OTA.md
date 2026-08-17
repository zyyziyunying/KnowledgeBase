# 系统应用更新与 OTA：从 data override 到 staged 提交

## 一句话结论

更新一个系统应用（含 Home）通常不是在系统分区里替换 APK：常规路径是在 `/data/app` 安装新副本、由 PackageManager 覆盖系统副本生效（data override）；OTA 与原子批量更新则把 APK 先放入 staging 目录，在**下一次开机的 systemReady 阶段、第三方应用启动之前**由 PMS 统一应用。Home 是按 intent 解析的"角色"而不是写死的类名，所以只要包名和组件名不变，新版本就会被 Framework 无缝接管；真正的约束来自**签名延续**和 **privapp-permissions 白名单**，而不是 Framework 需要改任何配置。

> **适用边界**：本文以 AOSP 固定源码 revision 为事实源，核对日期为 2026-08-18。frameworks/base 统一钉在 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`（与启动、Home/SystemUI 证据包同一基线）；`android.app.role` 已移入 Permission 模块，钉在 `26231a7eac744c7d2a8fea4740926620f56b20c6`。关键结论、SHA-256 与可执行断言记录在 [系统应用更新与 OTA 证据包](../../../evidence/android/framework/system-app-update/manifest.json)。Home/Launcher 的角色模型以 [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 为事实源，本文不重复其结论。

> **版本边界**：本文钉住的 revision 中，默认 Home 由 RoleManager 的 `ROLE_HOME` 角色（经 `DefaultAppProvider`）维护，preferred activity 仅作为角色切换窗口期的回退；本文不声称任何旧版 PackageManager 持久化 API 是或曾是事实源。launcher 更新后无缝接管的结论以"解析入口 + 角色默认值不变"成立，不依赖特定版本的持久化实现。

## 先分清三个问题

"更新 Home APK"叠加了三类不同问题，分开讨论才不会混：

1. **安装通道**：新 APK 从哪来（OTA 包、PackageInstaller、自建商店）、怎样落盘（直接安装还是 staging）；
2. **生效者**：装完哪个副本生效、Home 角色如何解析、旧进程如何切换；
3. **硬件约束**：签名策略、priv-app 白名单、分区布局决定了哪些通道可用。

## 决策起点：包类别决定自由度

系统应用的更新自由度由**签名**和 **privileged 状态**锁死：

| 类别 | 例子 | 能否走商店/独立安装更新 |
| --- | --- | --- |
| platform 签名 + priv-app | AOSP Launcher3（system_ext） | 基本只能随系统 OTA |
| vendor 自有签名 + priv-app 或普通预装 | OEM 自研桌面 | 可以，走自家商店 |
| 普通签名预装 / 三方桌面 | 用户安装的 Launcher | 走 Play/商店，最自由 |

两条硬约束：

- **签名延续**：同包名覆盖安装要求新 APK 与已装版本签名一致，否则报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。普通应用从 Android 9（APK Signature Scheme v3）起支持签名 key 轮换，v3.1 在 Android 11 增强；系统应用更新不适用这条路。
- **特权权限白名单**：priv-app 能获得哪些 privileged permission 不由 APK 决定，而由系统分区里的 `privapp-permissions-*.xml` 白名单决定（`SystemConfig` 读取）。**新版本 Home 若要新增特权权限，白名单必须随系统镜像先行更新**，否则权限被拒绝，严格配置下可能导致系统启动失败。

## 更新路线与取舍

### 路线 A：随系统 OTA（最正统，兜底必选）

Home 位于 system_ext/system 分区，A/B 或 virtual A/B 更新中随 super 分区（dynamic partitions）整体替换，`update_engine` 保证原子性与可回滚。适合 platform 签名、变更低频、需要同步修改白名单的场景。缺点：发版节奏被系统 OTA 锁死，无法单独快速修 Home 的 bug。

### 路线 B：data override（OEM 自研桌面主流做法）

更新系统 APK 时**不替换系统分区副本**，而是在 `/data/app/` 安装新副本；PMS 把系统副本移入 disabled 集合（代码与资源路径保留，见 `Settings.disableSystemPackageLPw`），并把新副本标记为 updated system app，data 副本成为生效包（codePath 指向 `/data/app/` 下新生成的两段随机路径）。重启后依然生效——系统副本已持久化在 disabled 集合中，data 副本是生效包。前提：签名一致、白名单已预留。可用 `adb install -r`、PackageInstaller Session 或自建商店实现。

### 路线 C：staged install（原子批量更新正道）

`PackageInstaller` Session 配合 `setStaged(true)` 把会话标记为"重启时安装"；`StagingManager` 专门管理这类 staged 会话，PMS 在**开机 systemReady 末尾**（第三方应用启动之前）通过 `restoreAndApplyStagedSessionIfNeeded` 统一应用，`PHASE_BOOT_COMPLETED` 时标记成功。一次提交多个包（APK + APEX）时要么全部生效、要么全部不生效。系统 OTA 内的 APK/APEX 更新本质上也是这条路。

### 路线 D：普通签名应用 + 自家商店

Home 不需要特权权限时最省事：预装为普通应用，走标准覆盖安装更新。Framework 天然支持"换包"，因为 Home 由 intent 解析得出。

### 推荐组合（自研硬件场景）

priv-app 预装 + 白名单预留"权限预算" + **OTA 作为兜底通道** + 商店或 staged 作为快速通道 + RollbackManager（`pm rollback-app`，Android 10+）兜底回滚。通道可以并存，但签名策略必须全通道统一。

## Framework 内部链路

一次 Home 更新在 Framework 侧经过四个环节：

```text
安装：PackageInstaller Session → PMS commit/scan
      → 写入 Settings（packages.xml：新 PackageSetting 与 codePath）
      → 系统副本移入 disabled 集合（Settings.disableSystemPackageLPw）
      → 广播 ACTION_PACKAGE_REPLACED
        ↓
进程切换：安装期间被替换包由 PackageFreezer 冻结（REASON_PACKAGE_UPDATED）；
      是否杀旧进程由 INSTALL_DONT_KILL_APP 安装标志决定（桌面进程当场退出）
        ↓
Home 解析：ComputerEngine.getHomeActivitiesAsUser 解析
      ACTION_MAIN + CATEGORY_HOME；
      默认桌面 = getDefaultHomeActivity → ROLE_HOME 的 DefaultAppProvider，
      preferred activity 作为角色切换窗口期的回退
        ↓
重启 Home：需要桌面时由 Window 侧（RootWindowContainer，解析链路见
      Home/SystemUI 证据包）拉起新版本 Home Activity
```

关键结论：

- 包名/组件名不变 → 默认 Home（ROLE_HOME 角色）继续命中 → 新版本无缝接管，**无需重启整机、无需改 Framework 配置**；
- 默认组件已不存在（如换包名）→ 回退到重新解析候选列表；
- staged 场景下应用发生在 systemReady 末尾（第三方应用启动之前）→ 开机即新版本，无中间态。

## Framework 的设计支撑

- **包三层存储模型**：system copy（只读分区）+ data override（可写）+ staged 目录（待提交）；codePath 解析规则决定谁生效；
- **Home 角色抽象**：intent 解析 + `ROLE_HOME` 角色默认值，把"哪个包当桌面"与"哪个 APK 版本生效"解耦；
- **开机顺序保证**：staged 会话随 PMS systemReady 应用（第三方应用启动前），`StagingManager` 在 `PHASE_BOOT_COMPLETED` 标记成功；
- **校验点**：安装时校验签名延续（不兼容更新报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`）；privileged permission 由系统镜像白名单裁决（`SystemConfig` 读取 `privapp-permissions-*.xml`）。

## 源码入口（固定 revision）

frameworks/base 均为 `1cdfff555f4a21f71ccc978290e2e212e2f8b168`，SHA-256 与断言见证据包；仅 RoleManager 来自 Permission 模块（`26231a7eac744c7d2a8fea4740926620f56b20c6`）：

- [StagingManager.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/StagingManager.java)：staged 会话生命周期与 boot phase 回调；
- [PackageManagerService.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/PackageManagerService.java)：systemReady 末尾应用 staged 包；
- [InstallPackageHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/InstallPackageHelper.java)：更新路径上禁用系统副本、冻结被替换包；
- [BroadcastHelper.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/BroadcastHelper.java)：`ACTION_PACKAGE_REPLACED` 与杀进程决策；
- [Settings.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/Settings.java)：`disableSystemPackageLPw` 与 disabled 集合；
- [ScanPackageUtils.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/ScanPackageUtils.java)：updated system app 标记；
- [ComputerEngine.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/pm/ComputerEngine.java)：`getHomeActivitiesAsUser` / `getDefaultHomeActivity`；
- [PackageInstaller.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/content/pm/PackageInstaller.java)：`setStaged()` API；
- [PackageManager.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/core/java/android/content/pm/PackageManager.java)：`INSTALL_FAILED_UPDATE_INCOMPATIBLE` 与 `getHomeActivities`；默认 Home 的持久化不在此 API（见 ComputerEngine 与 RoleManager）。
- [SystemConfig.java](https://android.googlesource.com/platform/frameworks/base/+/1cdfff555f4a21f71ccc978290e2e212e2f8b168/services/core/java/com/android/server/SystemConfig.java)：privapp-permissions 白名单解析；
- [RoleManager.java](https://android.googlesource.com/platform/packages/modules/Permission/+/26231a7eac744c7d2a8fea4740926620f56b20c6/framework-s/java/android/app/role/RoleManager.java)：`ROLE_HOME` 角色常量。

## 设备上的只读验证

```bash
# 更新前/后：codePath、版本、是否系统包
adb shell pm path <pkg>                    # 出现 /data/app/... 说明存在 data override
adb shell dumpsys package <pkg> | grep -E 'codePath|versionName|versionCode'

# Home 解析：更新后是否仍为默认 Home
adb shell cmd package resolve-activity --brief \
  -a android.intent.action.MAIN \
  -c android.intent.category.HOME

# 指定/核对默认 Home（Android 10+）
adb shell cmd role add-role-holder android.app.role.HOME <pkg>

# 回滚兜底
adb shell pm rollback-app <pkg>

# staged 安装（示意，实际参数以当前版本文档为准）
adb install --staged <apk>
```

这些命令回答"装在哪、谁生效、谁是 Home"；"首帧已合成、可交互"仍需 Perfetto 与 SurfaceFlinger/输入观测，同 [Home/SystemUI 文档](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md) 的边界。

## 待验证清单

已由证据包断言的机制不在此列；以下仍待后续核对：

- [ ] 系统副本移入 `mDisabledSysPackages` 后，其组件级 disable 状态的确切设置时点；
- [ ] staged 会话从 commit/markReady 到重启后 restore 的完整中间链（已断言两端：`commitSession` 与 `restoreAndApplyStagedSessionIfNeeded`）；
- [ ] staging 目录的确切路径（当前 revision 的已断言文件中未出现该路径常量）；
- [ ] 开机扫描时 data override 相对 system copy 的优先级规则（"重启后依然生效"的推断依据，未直接断言）；
- [ ] privapp 白名单违规在严格配置下的确切失败行为（随版本差异大）；
- [ ] `ROLE_HOME` 默认值的持久化位置与 `DefaultAppProvider` 的实现细节；
- [ ] `INSTALL_DONT_KILL_APP` 未设置时杀旧进程的实际执行点（已断言 `killApp` 计算与 PackageFreezer 冻结两端）。

## 继续阅读

- [系统应用更新与 OTA 证据包](../../../evidence/android/framework/system-app-update/manifest.json)：本文关键结论的固定源码、SHA-256 与可执行断言；
- [Android Framework 高频核心讲义](Android-Framework-%E9%AB%98%E9%A2%91%E6%A0%B8%E5%BF%83%E8%AE%B2%E4%B9%89.md)：第 10 章（PackageManager 与安装）、第 11 章（权限、签名、SELinux）是本文的基础；
- [Home、Launcher 与 SystemUI：进程与 APK 边界](Home-Launcher-SystemUI-%E8%BF%9B%E7%A8%8B%E4%B8%8EAPK%E8%BE%B9%E7%95%8C.md)：Home 角色模型与 APK 边界的事实源；
- [Android 建设路线](../ROADMAP.md)：第三阶段「Runtime、安全与工程诊断」（其中包含包管理、权限、签名）与本主题的规划关系。
