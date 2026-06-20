# PVZAgent / IZEAgent

PVZAgent 是一个面向《植物大战僵尸》我是僵尸无尽（I, Zombie, Endless / IZE）模式的计算机视觉与破阵辅助项目。

项目当前已经串起完整的实时调试链路：

```text
PVZ 窗口截图
  → 5×9 棋盘格裁剪
  → 植物分类识别
  → 棋盘记忆稳定化
  → IZE 主题识别
  → 主题先验纠错
  → IZE 算血
  → 全场状态检测
  → 主题破阵策略路由
  → BreakPlan 破阵计划输出
  → OpenCV 可视化调试
```

项目当前定位是 **识别、算血、全场状态判断和破阵策略输出**。目前不做自动点击控制，不接入 controller 自动下僵尸。

当前推荐入口是：

```bash
python .\tools\debug_board_recognition.py
```

---

## 1. 当前项目状态

当前已经完成的内容包括：

- 自动查找 PVZ 游戏窗口，并获取游戏客户区截图；
- 根据配置好的棋盘参数切分 5 行 × 9 列棋盘格；
- 使用训练好的植物格子分类器识别每个格子的植物类别；
- 使用棋盘记忆机制提高连续帧稳定性；
- 支持暂停菜单、窗口遮挡、异常截图时冻结识别，避免误更新棋盘；
- 支持 IZE 无尽新一关检测，并重新初始化棋盘记忆和主题锁定状态；
- 根据前 5 列初始阵型识别 IZE 主题；
- 使用主题先验修正部分容易混淆的植物，例如豌豆射手 / 双发射手；
- 接入 IZE 血量计算器，实时计算撑杆、慢速、梯子、橄榄、撑杆梯子等模式的参考数值；
- 新增算血 Debug 窗口，可实时显示每一路的算血结果；
- 新增破阵策略统一接口：`BreakContext`、`BreakPlan`、`BreakAction`；
- 新增主题破阵路由器：`ThemeBreakerRouter`；
- `strategies/` 目录下 8 个主题破阵策略已经全部完成；
- 新增全场状态检测：脑子是否存在、场上是否还有僵尸、是否允许重新破阵；
- 新增“格子识别变化 => 立刻认为场上有僵尸”的活动检测逻辑；
- 新增“棋盘植物状态 + 脑子状态连续稳定若干帧 => 认为场上无僵尸”的稳定判定逻辑；
- 新增策略安全过滤：只从仍有脑子的行中选择目标，避免继续攻击已经没有脑子的路；
- 新增自动重规划门控：只有“场上无僵尸 + 仍有脑子”时才重新调用破阵策略；
- 降低终端刷屏：FieldStatus 和 Breaker 日志只在关键状态变化或产生有效计划时输出；
- 提供独立算血调试工具、独立策略路由调试工具、训练数据采集工具、植物分类器训练工具等。

当前真实调试链路是：

```text
棋盘识别
  → 主题识别
  → 主题纠错
  → 算血
  → 全场状态检测
  → 主题破阵策略路由
  → 输出 BreakPlan
```

---

## 2. 运行环境

推荐环境：

- Windows 10 / Windows 11
- Python 3.9 或以上
- 已打开《Plants vs. Zombies》游戏窗口
- 游戏窗口大小尽量保持和 `config/settings.yaml` 中棋盘参数匹配

安装依赖：

```bash
pip install -r requirements.txt
```

如果运行时报 `win32gui` 或 `win32con` 相关错误，需要额外安装：

```bash
pip install pywin32
```

建议将 `pywin32` 补充到 `requirements.txt`。

---

## 3. 推荐运行方式

### 3.1 实时调试棋盘识别、主题识别、算血、状态检测和破阵策略

这是当前最重要、最推荐使用的入口：

```bash
python .\tools\debug_board_recognition.py
```

运行后脚本会：

1. 读取 `config/settings.yaml`；
2. 如果存在 `config/local_settings.yaml`，用本地配置覆盖默认配置；
3. 自动查找 PVZ 窗口；
4. 截取 PVZ 客户区画面；
5. 调用 `BoardRecognizer` 识别棋盘；
6. 调用 `ThemeRecognizer` 和 `StableThemeRecognizer` 识别并锁定主题；
7. 调用 `ThemeBoardCorrector` 根据主题修正棋盘；
8. 从修正后的棋盘中提取 IZE 前 5 列阵型；
9. 调用 `IZEBloodCalculator` 计算每行算血结果；
10. 调用 `FieldStatusDetector` 检测每一路脑子是否还在、全场是否还有僵尸；
11. 根据全场状态判断是否需要重新调用破阵策略；
12. 构造 `BreakContext`；
13. 调用 `ThemeBreakerRouter` 路由到对应主题策略；
14. 在终端输出当前有效 `BreakPlan`；
15. 在 OpenCV 窗口显示棋盘、主题、算血和全场状态。

快捷键：

```text
Q / ESC：退出调试窗口
R      ：重置已锁定主题和全场状态检测器
```

调试窗口中每个格子会显示：

```text
M：memory label，棋盘记忆中的最终标签
L：live label，当前帧分类器识别结果
R：raw label，KNN 原始最近类别
E：empty 连续确认帧数
V：空地视觉检查结果
```

同时会打开算血窗口：

```text
IZE Blood Calculator Debug
```

该窗口会显示每一路在以下模式下的计算结果：

```text
撑杆 / 慢速 / 梯子 / 橄榄 / 撑杆梯子
```

如果不想显示算血窗口，可以在 `config/local_settings.yaml` 中设置：

```yaml
blood_calculator:
  debug_window_enabled: false
```

---

### 3.2 独立调试 IZE 血量计算器

```bash
python .\tools\debug_ize_blood_calculator.py
```

调试单行：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "snowpea,repeater,wallnut,empty,puffshroom"
```

调试整板：

```bash
python .\tools\debug_ize_blood_calculator.py --board "empty,empty,empty,empty,empty; peashooter,empty,empty,empty,empty; snowpea,repeater,wallnut,empty,puffshroom"
```

查看撑杆修正细节：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --explain
```

输出 JSON：

```bash
python .\tools\debug_ize_blood_calculator.py --json --lane "snowpea,repeater,wallnut,empty,puffshroom"
```

---

### 3.3 独立调试主题破阵策略接口

```bash
python .\tools\debug_breaker_router.py
```

该脚本会构造测试用 `BreakContext`，依次测试：

```text
综合 / 控制 / 即死 / 输出 / 爆炸 / 倾斜 / 穿刺 / 回复
```

8 个主题策略均已实现，可以通过该脚本快速检查策略文件是否能正常返回 `BreakPlan`。

---

### 3.4 采集植物格子训练样本

```bash
python .\tools\extract_plant_cells.py
```

裁剪结果会保存到：

```text
assets/templates/plants_raw/batch_时间戳/
```

---

### 3.5 训练植物分类模型

```bash
python .\tools\train_plant_classifier.py
```

训练完成后会生成：

```text
models/plant_cell_classifier.npz
```

---

## 4. 仓库结构

```text
PVZAgent/
├─ assets/
│  ├─ plants_labeled/
│  ├─ templates/
│  └─ plants_labeled.zip
├─ config/
│  ├─ settings.yaml
│  └─ theme_signatures.yaml
├─ core/
│  ├─ board_adapter.py
│  ├─ board_corrector.py
│  ├─ board_debug.py
│  ├─ board_recognizer.py
│  ├─ breaker_router.py
│  ├─ breaker_types.py
│  ├─ capture.py
│  ├─ card_detector.py
│  ├─ controller.py
│  ├─ decision.py
│  ├─ field_status_detector.py
│  ├─ game_state.py
│  ├─ grid.py
│  ├─ ize_blood_calculator.py
│  ├─ plant_classifier.py
│  ├─ plant_detector.py
│  ├─ theme_recognizer.py
│  └─ window_finder.py
├─ models/
│  └─ plant_cell_classifier.npz
├─ tools/
│  ├─ debug_board_recognition.py
│  ├─ debug_breaker_router.py
│  ├─ debug_ize_blood_calculator.py
│  ├─ extract_plant_cells.py
│  ├─ picture_name.py
│  └─ train_plant_classifier.py
├─ strategies/
│  ├─ __init__.py
│  ├─ _template.py
│  ├─ hybrid.py
│  ├─ control.py
│  ├─ instant_kill.py
│  ├─ output.py
│  ├─ explosion.py
│  ├─ diagonal.py
│  ├─ piercing.py
│  └─ recovery.py
├─ utils/
│  └─ debug_view.py
├─ main.py
├─ README.md
├─ requirements.txt
└─ test_window.py
```

---

## 5. 核心模块说明

### 5.1 `core/board_recognizer.py`

棋盘识别核心模块。

主要职责：

- 裁剪 5×9 棋盘格；
- 调用植物分类器识别每个格子；
- 维护 `board_memory`；
- 多帧投票初始化棋盘；
- 冻结异常画面，不更新 memory；
- 不允许稳定阶段出现 `plant -> another plant`；
- 只允许 `plant -> empty`，且必须连续多帧确认；
- 使用空地视觉检查避免因僵尸、子弹、菜单遮挡误删植物；
- 检测 IZE 新一关并重置棋盘记忆。

输出：

```python
cell_results, board = board_recognizer.recognize(frame)
```

---

### 5.2 `core/theme_recognizer.py`

IZE 主题识别模块。

主要类：

```python
ThemeRecognizer
StableThemeRecognizer
```

主题识别只统计前 5 列：

```text
5 行 × 5 列 = 25 格
```

当前支持主题：

```text
综合 / 控制 / 即死 / 输出 / 爆炸 / 倾斜 / 穿刺 / 回复
```

---

### 5.3 `core/board_corrector.py`

基于主题先验的棋盘纠错模块，用于在主题锁定后修正容易混淆的植物识别结果，例如：

```text
peashooter / repeater
```

纠错范围主要是 IZE 初始区域，即前 5 列。

---

### 5.4 `core/ize_blood_calculator.py`

IZE 血量计算核心模块。

计算模式：

```text
pole        撑杆
slow        慢速
ladder      梯子
football    橄榄
pole_ladder 撑杆梯子
```

输出结构示例：

```python
{
    "lane": ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    "values": {
        "pole": 240,
        "slow": 282,
        "ladder": "17+36",
        "football": 237,
        "pole_ladder": "",
    },
    "status": {
        "pole": -1,
        "slow": -1,
        "ladder": -1,
        "football": -1,
        "pole_ladder": 0,
    },
    "has_magnet": False,
}
```

`status` 含义：

```text
 1：推荐
 0：普通
-1：不推荐
```

当前实现的关键规则：

- 标签会先经过 `normalize_label()` 归一化；
- `calculate_board()` 会自动处理相邻行三线射手跨行伤害；
- 同行三线射手按简化规则处理；
- 胆小菇按豌豆级别伤害处理，并加入同一路僵尸靠近时缩头规则；
- 磁力菇影响梯子、橄榄等模式的推荐状态；
- 梯子类结果使用 `a+b` 格式表示梯子血量 + 僵尸本体血量；
- 撑杆逻辑加入跳前行走伤害修正。

---

### 5.5 `core/field_status_detector.py`

全场状态检测模块，用于回答三个问题：

```text
1. 每一路脑子是否还存在？
2. 场上是否还有任意活僵尸？
3. 当前是否应该重新调用破阵策略？
```

输出示例：

```python
{
    "brain_alive_rows": [True, True, False, True, False],
    "alive_brain_rows": [0, 1, 3],
    "has_alive_brain": True,
    "any_zombie_present": False,
    "should_replan": True,
    "reason": "全场无僵尸，且仍有脑子，允许重新调用破阵策略",
}
```

核心逻辑：

```python
should_replan = (
    has_alive_brain
    and not any_zombie_present
    and not in_place_grace
    and replan_cooldown_passed
)
```

设计原则：

- 不做“每一路是否有僵尸”的复杂判断；
- 只判断“全场是否还有僵尸”；
- 因为当前策略大多是单路破阵，舞王可能影响多路，按全场有无僵尸判断更稳；
- 只要场上还有任意僵尸，就等待当前进攻结束；
- 场上没有僵尸且仍有脑子时，才允许重新调用破阵策略；
- 如果所有脑子都消失，则当前不再需要破阵。

脑子检测：

- 每一路有独立的脑子 ROI；
- 通过粉色 / 红色 HSV 像素比例判断脑子是否存在；
- 默认采用单向状态：`alive -> dead`；
- 脑子一旦判定消失，本关内不会自动恢复，除非手动或新关卡 reset。

全场僵尸检测由三类信号共同决定：

```text
1. 格子识别变化：
   只要任意格子的识别签名发生变化，立即认为场上有僵尸。
   在 IZE 中，格子变化通常来自僵尸运动、植物子弹、爆炸、植物被吃等。

2. 原始视觉检测：
   使用背景差分、运动差分和连通域过滤判断场上是否可能存在僵尸。

3. 稳定无僵尸判定：
   如果“所有格子植物判定 + 所有脑子判定”连续若干帧不变化，
   则认为场上没有活僵尸。
```

当前用于测试的推荐参数是：

```yaml
field_status:
  zombie:
    activity_present_hold_frames: 0
    stability_absence_frames: 4
```

也就是说：

```text
格子一变化，立刻判定有僵尸；
格子和脑子连续 4 帧稳定，判定无僵尸。
```

---

### 5.6 `core/breaker_types.py`

破阵策略层的数据结构定义文件。

主要数据结构：

```python
BreakContext
BreakPlan
BreakAction
```

`BreakContext` 是传给每个主题策略的输入对象，包含：

```python
context.theme
context.board_5x5
context.board_5x9
context.blood_table
context.theme_result
context.correction_info
context.field_state
context.brain_alive_rows
context.alive_brain_rows
context.any_zombie_present
context.should_replan
context.config
```

常用辅助方法：

```python
context.lane(row)
context.blood_values(row)
context.blood_status(row)
context.mode_value(row, mode)
context.mode_status(row, mode)
context.recommended_modes(row)
context.not_recommended_modes(row)
context.plant_count(row)
context.has_brain(row)
context.candidate_rows()
context.has_alive_brain()
context.is_row_allowed(row)
```

其中：

```python
context.candidate_rows()
```

会返回仍有脑子的行。策略应只从这些行中选择目标。

---

### 5.7 `core/breaker_router.py`

主题破阵策略路由器。

作用：

1. 根据 `BreakContext.theme` 找到对应策略文件；
2. 调用该文件的 `solve(context)`；
3. 检查返回值是否为 `BreakPlan`；
4. 根据全场状态过滤无效动作。

主题到策略文件映射：

```python
{
    "综合": "strategies.hybrid",
    "控制": "strategies.control",
    "即死": "strategies.instant_kill",
    "输出": "strategies.output",
    "爆炸": "strategies.explosion",
    "倾斜": "strategies.diagonal",
    "穿刺": "strategies.piercing",
    "回复": "strategies.recovery",
}
```

安全过滤：

- 已无脑子的行不会继续下僵尸；
- 自动重规划模式下可以只保留一个目标行，避免多路同时出僵尸；
- 如果策略返回的动作全部位于无脑子的行，router 会返回空计划并说明原因。

---

## 6. `tools/debug_board_recognition.py` 主流程

当前主调试入口会串起完整流程：

```text
加载配置
  → 查找 PVZ 窗口
  → 截图
  → 棋盘识别
  → 新关卡检测
  → FieldStatusDetector 更新全场状态
  → 主题识别与锁定
  → 主题纠错
  → 算血
  → 构造 BreakContext
  → should_replan 判断
  → ThemeBreakerRouter 调用策略
  → 终端输出 BreakPlan
  → 绘制棋盘、主题、算血、全场状态
```

策略调用门控：

```text
如果场上仍有僵尸：
    不重新调用破阵策略

如果场上无僵尸且仍有脑子：
    调用 ThemeBreakerRouter 重新生成 BreakPlan

如果没有脑子：
    不调用破阵策略
```

终端日志当前应该尽量保持克制：

- 不持续打印性能 profiler；
- 不打印冷却中状态；
- 不持续打印空 BreakPlan；
- 只在主题锁定、全场状态关键变化、产生有效破阵计划、纠错变化时输出。

---

## 7. `strategies/` 主题破阵策略

`strategies/` 是主题破阵逻辑目录。

文件对应关系：

```text
strategies/hybrid.py       综合
strategies/control.py      控制
strategies/instant_kill.py 即死
strategies/output.py       输出
strategies/explosion.py    爆炸
strategies/diagonal.py     倾斜
strategies/piercing.py     穿刺
strategies/recovery.py     回复
```

当前状态：

```text
8 个主题策略均已完成。
```

每个主题文件都应该实现：

```python
def solve(context: BreakContext) -> BreakPlan:
    ...
```

策略文件只依赖 `BreakContext`，不直接访问 OpenCV 图像、BoardRecognizer、截图器或鼠标控制器。

推荐策略基本结构：

```python
from core.breaker_types import BreakAction, BreakContext, BreakPlan

THEME_NAME = "输出"

def solve(context: BreakContext) -> BreakPlan:
    candidate_rows = context.candidate_rows()

    if not candidate_rows:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.0,
            reason="没有仍存在脑子的行",
        )

    best_row = None
    best_value = None

    for row in candidate_rows:
        value = context.mode_value(row, "football")

        if not isinstance(value, (int, float)):
            continue

        if best_value is None or value < best_value:
            best_row = row
            best_value = value

    if best_row is None:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.0,
            reason="没有找到合适的破阵行",
        )

    return BreakPlan(
        theme=THEME_NAME,
        actions=[
            BreakAction(
                zombie="football",
                row=best_row,
                note=f"橄榄参考值={best_value}",
            )
        ],
        confidence=0.8,
        reason=f"选择第 {best_row + 1} 行橄榄",
    )
```

坐标约定：

```text
row 使用 0-based：
0 = 第 1 行
1 = 第 2 行
2 = 第 3 行
3 = 第 4 行
4 = 第 5 行
```

常用僵尸标签：

```text
pole        撑杆
slow        慢速普通僵尸
ladder      梯子
football    橄榄
pole_ladder 撑杆梯子
dancer      舞王
```

---

## 8. 配置说明

### 8.1 窗口配置

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
    - "植物大战僵尸"
```

---

### 8.2 棋盘配置

```yaml
grid:
  rows: 5
  cols: 9
  board_left: 30
  board_top: 80
  board_width: 735
  board_height: 500
  crop_padding_ratio: 0.08
```

---

### 8.3 主题识别配置

```yaml
theme:
  enabled: true
  signatures_path: config/theme_signatures.yaml
  max_col: 4
  required_frames: 4
  min_score: 0.86
  min_margin: 0.06
```

`max_col: 4` 表示使用前 5 列，即 `c0-c4`。

---

### 8.4 算血配置

```yaml
blood_calculator:
  debug_window_enabled: true
  tilted_starfruit_themes:
    - "倾斜"
```

如果不想显示算血窗口：

```yaml
blood_calculator:
  debug_window_enabled: false
```

---

### 8.5 策略配置

```yaml
strategy:
  enabled: true
  log_plan: true
  require_locked_theme: true

  filter_dead_brain_rows: true
  single_replan_lane: true
```

含义：

```text
enabled：是否启用主题破阵策略路由
log_plan：是否在终端输出 BreakPlan
require_locked_theme：是否必须等主题锁定后才调用策略
filter_dead_brain_rows：是否过滤已经没有脑子的行
single_replan_lane：自动重规划时是否只保留一个目标行
```

---

### 8.6 全场状态检测配置

当前更适合测试的推荐配置如下，建议放入 `config/local_settings.yaml`：

```yaml
field_status:
  enabled: true

  # 重新规划冷却，防止重复生成计划。
  replan_cooldown_seconds: 1.5

  # 策略安全过滤。
  filter_dead_brain_rows: true
  single_replan_lane: true

  debug:
    enabled: true

  brain:
    # 如果默认 ROI 没有框准脑子，可以手动打开 x1/x2。
    # x1: 0
    # x2: 95

    y_margin_ratio: 0.22
    pink_ratio_threshold: 0.025

    # 脑子消失要连续确认，避免被动画或遮挡误判。
    dead_confirm_frames: 5
    alive_confirm_frames: 2

    # 脑子一旦消失，本关内不自动恢复。
    one_way_dead: true

  zombie:
    # 格子识别一变，立刻认为场上有僵尸。
    use_activity_presence: true

    # 测试配置：不额外保持有僵尸状态。
    # 只依赖下一帧是否继续变化，以及稳定无僵尸判定。
    activity_present_hold_frames: 0

    # 稳定无僵尸判定。
    use_stability_absence: true

    # 测试配置：连续 4 帧“植物判定 + 脑子判定”都不变，就认为场上无僵尸。
    stability_absence_frames: 4

    # 原有视觉僵尸检测参数。
    extend_left_ratio: 0.15
    extend_right_ratio: 0.75
    y_margin_ratio: 0.04

    bg_diff_threshold: 30
    motion_diff_threshold: 24

    min_component_area: 650
    min_component_width: 20
    min_component_height: 36
    min_motion_area: 120

    present_confirm_frames: 2
    absent_confirm_frames: 14

    background_update_alpha: 0.03

    # 当前不做自动点击，该字段主要作为内部状态保护。
    after_place_grace_seconds: 1.0
```

这组测试配置的含义是：

```text
activity_present_hold_frames: 0
    格子识别变化的那一帧立即认为有僵尸，但不额外延长保持时间。

stability_absence_frames: 4
    如果之后连续 4 帧格子和脑子状态稳定，就认为场上无僵尸。
```

---

### 8.7 Debug UI 和性能日志配置

```yaml
debug_ui:
  board_fps: 12
  blood_fps: 5

debug_performance:
  enabled: false
  log_interval: 1.0
```

`debug_performance.enabled` 默认建议保持 `false`，避免终端刷屏。需要定位性能瓶颈时再临时打开。

---

## 9. 常见问题

### 9.1 找不到 PVZ 窗口

检查游戏是否打开，并确认窗口标题包含配置中的关键字：

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
```

也可以运行：

```bash
python .\test_window.py
```

---

### 9.2 棋盘格子位置不对

调整：

```yaml
grid:
  board_left: 30
  board_top: 80
  board_width: 735
  board_height: 500
```

可以通过 `tools/extract_plant_cells.py` 生成网格预览图辅助调参。

---

### 9.3 缺少模型文件

如果报错：

```text
Plant classifier model not found: models/plant_cell_classifier.npz
```

运行：

```bash
python .\tools\train_plant_classifier.py
```

---

### 9.4 算血窗口不显示或显示不可用

检查：

1. 是否存在 `core/ize_blood_calculator.py`；
2. 是否从项目根目录运行；
3. 是否关闭了算血窗口：

```yaml
blood_calculator:
  debug_window_enabled: false
```

---

### 9.5 主题锁定后没有 Breaker 输出

检查：

```yaml
strategy:
  enabled: true
  log_plan: true
  require_locked_theme: true
```

并确认当前主题对应策略文件存在，例如主题是 `输出` 时，需要：

```text
strategies/output.py
```

且该文件中实现：

```python
def solve(context):
    ...
```

可以先运行：

```bash
python .\tools\debug_breaker_router.py
```

确认策略路由是否正常。

---

### 9.6 明明没有僵尸，却一直判断有僵尸

检查：

```yaml
field_status:
  zombie:
    use_stability_absence: true
    stability_absence_frames: 4
```

如果仍然误判，可以继续观察 FieldStatus 调试窗口中的稳定帧计数是否增长。

---

### 9.7 放下僵尸后系统没有及时认为有僵尸

检查：

```yaml
field_status:
  zombie:
    use_activity_presence: true
    activity_present_hold_frames: 0
```

并观察 FieldStatus 调试窗口中是否出现：

```text
Activity present: Y
```

如果活动信号没有触发，说明当前 `make_board_activity_signature()` 读取到的格子字段变化不明显，需要继续调整 activity signature 包含的字段。

---

## 10. 推荐阅读顺序

```text
1. README.md
2. config/settings.yaml
3. config/local_settings.yaml
4. core/breaker_types.py
5. core/field_status_detector.py
6. core/breaker_router.py
7. strategies/hybrid.py
8. strategies/control.py
9. strategies/instant_kill.py
10. strategies/output.py
11. strategies/explosion.py
12. strategies/diagonal.py
13. strategies/piercing.py
14. strategies/recovery.py
15. tools/debug_breaker_router.py
16. tools/debug_board_recognition.py
17. core/board_recognizer.py
18. core/theme_recognizer.py
19. core/board_corrector.py
20. core/ize_blood_calculator.py
21. tools/debug_ize_blood_calculator.py
22. core/grid.py
23. tools/train_plant_classifier.py
24. tools/extract_plant_cells.py
```

---

## 11. 简短交接说明

当前项目已经从“单纯棋盘识别”扩展为：

```text
识别 + 主题 + 纠错 + 算血 + 全场状态检测 + 8 主题破阵策略
```

当前最重要的代码链路是：

```text
tools/debug_board_recognition.py
  → BoardRecognizer
  → ThemeRecognizer / StableThemeRecognizer
  → ThemeBoardCorrector
  → IZEBloodCalculator
  → FieldStatusDetector
  → BreakContext
  → ThemeBreakerRouter
  → strategies/<theme>.py
  → BreakPlan
```

当前策略执行逻辑是：

```text
场上有僵尸：
    等待当前进攻结束，不重新破阵

场上无僵尸 + 仍有脑子：
    重新调用当前主题策略，生成 BreakPlan

没有脑子：
    不再破阵
```

当前状态总结：

- `debug_board_recognition.py` 用于真实游戏画面调试；
- `debug_breaker_router.py` 用于脱离游戏快速测试策略；
- 8 个主题策略均已完成；
- 项目当前不做自动点击控制；
- 主要输出是识别状态、算血结果和 BreakPlan。