# PVZAgent

PVZAgent 是一个面向《植物大战僵尸》我是僵尸无尽（I, Zombie, Endless / IZE）模式的计算机视觉项目。项目目前主要用于识别游戏窗口中的棋盘、植物阵型和 IZE 主题，并在识别结果基础上接入 IZE 算血器，实时估算不同僵尸类型通过每一行时的伤害 / 血量消耗参考。项目同时提供棋盘调试、算血调试、策略路由调试、训练数据采集、植物分类模型训练等工具。当前已经为 8 个 IZE 主题破阵逻辑预留统一接口，队友只需要在 `strategies/` 目录下实现对应主题的 `solve(context)`，即可接入识别结果、主题结果和算血结果。

本 README 主要用于项目交接，帮助队友快速了解仓库结构、各文件作用、调试入口和运行方式。

---

## 1. 当前项目状态

目前主要完成的工作包括：

* 自动查找 PVZ 游戏窗口，并获取游戏客户区截图；
* 根据配置好的棋盘参数，将游戏画面切分为 5 行 × 9 列棋盘格；
* 使用训练好的植物格子分类器识别每个格子的植物类别；
* 使用棋盘记忆机制提高连续帧识别稳定性；
* 支持暂停菜单、窗口遮挡、异常截图等情况下冻结识别，避免误更新棋盘；
* 支持 IZE 无尽新一关检测，并重新初始化棋盘记忆；
* 根据前 5 列初始阵型识别 IZE 主题；
* 根据主题先验修正部分容易混淆的植物识别结果，例如豌豆射手和双发射手；
* 新增 IZE 血量计算器，可根据前 5 列阵型计算撑杆、慢速、梯子、橄榄、撑杆梯子等模式的血量 / 伤害参考；
* 在棋盘识别调试入口中新增实时算血 Debug 窗口，识别和纠错后的棋盘会自动送入算血器；
* 新增独立命令行算血调试工具，方便脱离游戏画面验证单行或整板计算结果；
* 新增破阵策略统一接口，包括 `BreakContext`、`BreakPlan` 和 `BreakAction`；
* 新增主题破阵路由器，可根据识别出的 8 个主题自动调用对应策略文件；
* 新增 `strategies/` 目录，用于放置 8 个主题的破阵逻辑，队友主要只需要修改这个目录；
* 新增独立命令行策略路由调试工具，方便不打开游戏时测试策略接口；
* 当前真实调试链路已经串起：棋盘识别 → 主题识别 → 主题纠错 → 算血 → 主题策略路由 → 输出破阵计划；
* 提供训练集裁剪、植物分类器训练、窗口检测、资源清单生成等辅助脚本。

当前主要调试入口是：

```bash
python .\tools\debug_board_recognition.py
```

`main.py` 是早期自动操作入口，目前实际调试中基本没有使用，可以保留作为后续接入自动放僵尸逻辑的参考。

---

## 2. 运行环境

项目主要依赖 Windows 环境，因为窗口查找和客户区坐标获取使用了 Windows API / `win32gui`。

建议环境：

* Windows 10 / Windows 11
* Python 3.9 或以上
* 已打开《Plants vs. Zombies》游戏窗口
* 游戏窗口大小尽量保持和 `config/settings.yaml` 中棋盘参数匹配

安装依赖：

```bash
pip install -r requirements.txt
```

如果运行时报 `win32gui` 或 `win32con` 相关错误，需要额外安装：

```bash
pip install pywin32
```

建议后续将下面这一行补充到 `requirements.txt`：

```text
pywin32
```

---

## 3. 推荐运行方式

### 3.1 调试棋盘识别和主题识别

这是当前项目最主要、最推荐使用的入口。

```bash
python .\tools\debug_board_recognition.py
```

运行后脚本会：

1. 读取 `config/settings.yaml`；
2. 如果存在 `config/local_settings.yaml`，会用本地配置覆盖默认配置；
3. 自动查找 PVZ 窗口；
4. 截取游戏客户区画面；
5. 调用 `BoardRecognizer` 识别棋盘；
6. 调用 `ThemeRecognizer` 和 `StableThemeRecognizer` 识别并锁定 IZE 主题；
7. 调用 `ThemeBoardCorrector` 根据主题修正部分识别结果；
8. 从修正后的棋盘中提取 IZE 前 5 列阵型；
9. 调用 `IZEBloodCalculator` 计算每行在不同僵尸模式下的血量 / 伤害参考；
10. 构造 `BreakContext`，把主题、5×5 阵型、5×9 棋盘和算血结果传给策略层；
11. 调用 `ThemeBreakerRouter`，根据当前锁定主题路由到 `strategies/` 下对应破阵文件；
12. 在终端输出当前 `BreakPlan`，目前只打印计划，不执行自动点击；
13. 用 OpenCV 窗口显示棋盘识别、主题识别和算血结果。

快捷键：

```text
Q / ESC：退出调试窗口
R      ：重置已锁定主题
```

调试窗口中每个格子会显示：

```text
M：memory label，棋盘记忆中的最终标签
L：live label，当前帧分类器识别结果
R：raw label，KNN 原始最近类别
E：empty 连续确认帧数
V：空地视觉检查结果
```

同时会打开一个独立的算血器窗口：

```text
IZE Blood Calculator Debug
```

该窗口会显示 5 行在以下模式下的计算结果：

```text
撑杆 / 慢速 / 梯子 / 橄榄 / 撑杆梯子
```

显示规则：

```text
灰底加粗：当前推荐值
括号灰字：当前不推荐值
普通黑字：普通可参考值
梯子类 a+b：梯子血量 + 本体血量
```

如果暂时不想显示算血窗口，可以在 `config/local_settings.yaml` 中覆盖：

```yaml
blood_calculator:
  debug_window_enabled: false
```

---

### 3.2 独立调试 IZE 血量计算器

不打开游戏画面时，可以直接用命令行调试新增的算血器：

```bash
python .\tools\debug_ize_blood_calculator.py
```

默认会使用脚本内置的 `DEFAULT_BOARD` 输出 5 行算血表。

调试单行：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "snowpea,repeater,wallnut,empty,puffshroom"
```

调试整板，行之间用分号分隔，格子之间用逗号分隔：

```bash
python .\tools\debug_ize_blood_calculator.py --board "empty,empty,empty,empty,empty; peashooter,empty,empty,empty,empty; snowpea,repeater,wallnut,empty,puffshroom"
```

输出 JSON：

```bash
python .\tools\debug_ize_blood_calculator.py --json --lane "snowpea,repeater,wallnut,empty,puffshroom"
```

查看撑杆修正细节：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --explain
```

对比旧版撑杆逻辑：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --legacy-pole --explain
```

输出表格列含义：

```text
行      撑杆      慢速      梯子        橄榄      撑杆梯子
```

其中 `*value*` 表示推荐，`(value)` 表示不推荐。

---

### 3.3 独立调试主题破阵策略接口

不打开游戏画面时，可以直接测试策略接口是否能正常工作：

```bash
python .\tools\debug_breaker_router.py
```

该脚本会构造一份假的 5×5 棋盘和假的算血结果，然后依次测试 8 个主题：

```text
综合 / 控制 / 即死 / 输出 / 爆炸 / 倾斜 / 穿刺 / 回复
```

测试链路是：

```text
BreakContext
    ↓
ThemeBreakerRouter
    ↓
strategies/<theme>.py
    ↓
BreakPlan
```

这个脚本主要用于队友开发 `strategies/` 下的主题破阵逻辑。队友写完任意一个主题后，可以先运行该脚本确认 `solve(context)` 是否能正常返回 `BreakPlan`，不需要每次都打开 PVZ 游戏窗口。

---

### 3.4 采集植物格子训练样本

```bash
python .\tools\extract_plant_cells.py
```

该脚本用于从当前 PVZ 游戏画面中裁剪棋盘格子，生成训练样本或辅助标注数据。

运行后会：

1. 自动查找 PVZ 窗口；
2. 尝试识别并点击暂停菜单中的 `Resume Game`；
3. 截取完整游戏画面；
4. 根据 `settings.yaml` 中的棋盘参数绘制网格预览；
5. 在 OpenCV 窗口中按 `S` 保存当前棋盘格子；
6. 将裁剪结果保存到：

```text
assets/templates/plants_raw/batch_时间戳/
```

同时会生成：

```text
assets/templates/grid_preview.png
assets/templates/pvz_full_frame.png
assets/templates/resume_detection_debug.png
```

这些图片主要用于确认棋盘参数是否正确，以及检查自动恢复游戏的识别是否正常。

---

### 3.5 训练植物分类模型

```bash
python .\tools\train_plant_classifier.py
```

训练脚本会读取：

```text
assets/plants_labeled/
```

该目录下每个子文件夹代表一个类别，例如：

```text
chomper/
empty/
fumeshroom/
kernelpult/
magnetshroom/
peashooter/
potatomine/
puffshroom/
repeater/
scaredyshroom/
snowpea/
spikeweed/
splitpea/
squash/
starfruit/
sunflower/
threepeater/
torchwood/
umbrellaleaf/
wallnut/
```

每个类别文件夹中保存该植物或空地的格子截图，例如：

```text
spikeweed_001.png
spikeweed_002.png
spikeweed_003.png
...
```

训练完成后会生成模型文件：

```text
models/plant_cell_classifier.npz
```

该模型会被 `core/plant_classifier.py` 和 `core/board_recognizer.py` 使用。

---

### 3.6 测试窗口识别

```bash
python .\test_window.py
```

该脚本会枚举当前所有可见窗口，打印窗口句柄和标题。用于调试 `settings.yaml` 中的窗口标题关键字是否能匹配到 PVZ。

---

### 3.7 早期自动操作入口

```bash
python .\main.py
```

`main.py` 是早期保留下来的自动操作入口，包含窗口查找、截图、棋盘识别、卡牌识别、策略选择和鼠标点击控制逻辑。

不过目前调试主要不走这个文件。当前更完整、更稳定的识别链路在：

```text
core/board_recognizer.py
core/theme_recognizer.py
core/board_corrector.py
utils/debug_view.py
```

以及入口：

```text
tools/debug_board_recognition.py
```

因此交接时建议优先阅读和使用 `tools/debug_board_recognition.py`。

---

## 4. 仓库结构说明

当前仓库大致结构如下：

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
├─ zombieImages/
├─ asset_category_summary.csv
├─ asset_manifest.csv
├─ asset_manifest_categorized.csv
├─ main.py
├─ particles_names.txt
├─ README.md
├─ reanim_names.txt
├─ requirements.txt
├─ test_window.py
└─ zombieImages.zip
```

---

## 5. 目录和文件功能说明

### 5.1 `config/`

#### `config/settings.yaml`

项目主配置文件，包含窗口匹配、截图调试、棋盘坐标、卡槽位置、棋盘记忆、帧有效性检查、植物分类器、主题识别和棋盘修正规则等配置。

重要配置包括：

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
```

用于自动查找 PVZ 窗口。

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

用于定义棋盘区域和格子裁剪方式。窗口可以自动捕捉，但棋盘格子的坐标参数是人工调好的，所以如果游戏窗口大小或缩放发生变化，需要重新调整这些参数。

```yaml
plant_classifier:
  model_path: models/plant_cell_classifier.npz
  unknown_threshold: 0.55
  k: 5
```

用于配置植物分类模型路径和 KNN 参数。

```yaml
theme:
  enabled: true
  signatures_path: config/theme_signatures.yaml
  max_col: 4
```

用于配置 IZE 主题识别。`max_col: 4` 表示只看前 5 列，也就是 `c0-c4`。

```yaml
board_corrector:
  enabled: true
  signatures_path: config/theme_signatures.yaml
  max_col: 4
```

用于根据已锁定主题修正部分容易混淆的植物。

新增算血器调试窗口可用下面的本地配置开关控制。该字段在代码中默认开启，因此旧配置里没有这一项也可以运行：

```yaml
blood_calculator:
  debug_window_enabled: true
```

如果只想看棋盘识别窗口，可以在 `config/local_settings.yaml` 里设为 `false`。

新增策略接口相关配置：

```yaml
strategy:
  enabled: true
  log_plan: true
  require_locked_theme: true
  execute_actions: false
```

含义：

```text
enabled：是否启用主题破阵策略路由
log_plan：是否在终端输出 BreakPlan
require_locked_theme：是否必须等主题稳定锁定后才调用策略
execute_actions：是否执行自动点击；当前建议保持 false
```

目前 `execute_actions` 只作为预留开关。当前调试链路只输出破阵计划，不会自动点击。

---


#### `config/theme_signatures.yaml`

IZE 主题签名配置文件。

文件中定义了不同主题下前 5 列植物的可重集统计。例如：

```yaml
themes:
  综合:
    support_total: 8
    signature_total: 17
    plants:
      kernelpult: 1
      peashooter: 1
      snowpea: 1
      ...
```

主题识别时会统计前 5 列植物数量，并和这里配置的主题签名进行匹配。

目前支持的主题包括：

```text
综合
控制
即死
输出
爆炸
倾斜
穿刺
回复
```

其中：

```yaml
ignore_for_theme:
  - empty
  - unknown
  - invalid_frame
```

这些标签不会用于主题签名匹配。

```yaml
support_plants:
  - sunflower
  - puffshroom
```

这些植物作为辅助植物统计，不直接作为大多数主题的核心签名植物。

---

### 5.2 `core/`

`core/` 是项目核心逻辑目录。

#### `core/breaker_types.py`

破阵策略层的数据结构定义文件，也是队友实现 8 个主题破阵逻辑时最重要的接口文件。

主要数据结构：

```python
BreakContext
BreakPlan
BreakAction
```

`BreakContext` 是传给每个主题策略的输入对象，包含：

```python
context.theme                  # 当前锁定主题，例如 "综合"、"输出"
context.board_5x5              # IZE 前 5 列阵型，5 行 × 5 列
context.board_5x9              # 完整 5 行 × 9 列棋盘标签，可选
context.blood_table            # 算血器输出结果
context.theme_result           # 主题识别结果
context.correction_info        # 主题纠错信息
context.config                 # 项目配置
```

常用辅助方法：

```python
context.lane(row)              # 获取第 row 行的前 5 列植物
context.blood_values(row)      # 获取第 row 行所有算血值
context.blood_status(row)      # 获取第 row 行所有推荐状态
context.mode_value(row, mode)  # 获取某行某模式的算血值
context.mode_status(row, mode) # 获取某行某模式推荐状态，1 推荐，0 普通，-1 不推荐
context.recommended_modes(row) # 获取第 row 行所有推荐模式
context.plant_count(row)       # 统计第 row 行植物数量
```

`BreakPlan` 是策略输出对象，包含：

```python
theme       # 主题名
actions     # BreakAction 列表
confidence  # 策略置信度
reason      # 给人看的解释
debug       # 可选调试信息
```

`BreakAction` 表示一个计划动作，当前主要字段是：

```python
zombie      # 建议使用的僵尸，例如 "pole"、"football"
row         # 0-based 行号，0 表示第 1 行，4 表示第 5 行
col         # 可选列号，当前可以先不填
count       # 动作数量，默认 1
note        # 动作说明
```

队友写主题策略时，原则上只需要依赖这个文件，不需要直接依赖 OpenCV、识别器或算血器内部实现。

---

#### `core/breaker_router.py`

主题破阵策略路由器。

主要类：

```python
ThemeBreakerRouter
```

作用是根据 `BreakContext.theme` 自动找到对应的策略文件，并调用该文件的：

```python
solve(context)
```

当前主题到文件的映射关系：

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

如果某个主题没有对应文件、文件没有实现 `solve(context)`，或者返回值不是 `BreakPlan`，路由器会返回一个空的 `BreakPlan`，并在 `reason` 中说明问题。

---

#### `core/board_adapter.py`

棋盘标签适配器。该文件用于把识别结果转换成策略层更容易使用的普通字符串棋盘。

主要函数：

```python
extract_label_board
extract_ize_board
get_cell_label
normalize_strategy_label
board_signature
print_board
```

设计目标是把底层识别结果和策略逻辑解耦。策略层不应该关心 `cell_results` 或 `BoardRecognizer` 内部对象长什么样，而应该只接收类似下面的结果：

```python
[
    ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    ["peashooter", "empty", "empty", "empty", "empty"],
    ...
]
```

当前 `tools/debug_board_recognition.py` 内部也有同类提取逻辑，后续可以进一步整理为统一调用 `core/board_adapter.py`。

---

#### `core/window_finder.py`

负责自动寻找 PVZ 游戏窗口。

主要功能：

* 根据窗口标题关键字查找窗口；
* 如果窗口最小化，则尝试恢复；
* 将窗口置前；
* 获取窗口客户区在屏幕上的绝对坐标。

后续截图和点击都基于客户区坐标，不包含标题栏和边框。

---

#### `core/capture.py`

负责截取 PVZ 客户区画面。

主要类：

```python
PVZCapture
```

主要功能：

* 根据客户区坐标初始化截图区域；
* 窗口移动后更新截图区域；
* 使用 `mss` 截屏，并将 BGRA 转为 OpenCV 使用的 BGR 格式。

---

#### `core/grid.py`

负责管理棋盘网格坐标。

主要类和函数：

```python
PVZGrid
get_grid_config
get_grid_bboxes
crop_cell
crop_grid_cells_for_recognition
```

主要功能：

* 根据 `settings.yaml` 中的棋盘参数计算 5×9 格子位置；
* 获取单个格子的矩形区域和中心点；
* 将点击坐标转换为格子行列；
* 按格子裁剪图像，供植物识别模型使用。

---

#### `core/ize_blood_calculator.py`

新增的 IZE 血量计算核心模块。该文件负责把识别到的前 5 列植物阵型转换为算血结果，供调试窗口和后续策略模块使用。

主要类和函数：

```python
IZEBloodCalculator
Row
Pair
normalize_label
normalize_lane
format_result_table
format_lane_result
explain_pole
```

典型用法：

```python
from core.ize_blood_calculator import IZEBloodCalculator

calc = IZEBloodCalculator()

# 单行计算，只取前 5 列，多余列会被忽略，不足 5 列会补 empty
result = calc.calculate_lane([
    "snowpea",
    "repeater",
    "wallnut",
    "empty",
    "puffshroom",
])

# 整板计算，可以传 5×5，也可以传 5×9；只使用每行前 5 列
results = calc.calculate_board(board)
```

坐标约定：

```text
一行只看 IZE 植物区前 5 列：
[col1, col2, col3, col4, col5]

col1 是最左侧，col5 是最右侧，也就是最靠近僵尸入口的一列。
```

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

`status` 的含义：

```text
 1：推荐
 0：普通
-1：不推荐
```

当前实现的关键规则：

* 标签会先经过 `normalize_label()` 归一化，`empty`、`unknown`、`none`、`grass` 等都会按空地处理；
* `calculate_board()` 会自动检查目标行上下相邻行里的三线射手，并把相邻行三线射手的跨行伤害加入目标行；
* 同行三线射手沿用原分段计算器的简化逻辑，按豌豆射手处理；
* 胆小菇按豌豆级别伤害处理，但加入同一路僵尸靠近时的缩头规则；
* 磁力菇会影响梯子、橄榄等模式的推荐状态；
* 梯子类结果使用 `a+b` 格式，表示梯子血量 + 僵尸本体血量。

撑杆逻辑是本项目重点修改点：

* 普通非撑杆模式尽量保持原 converter 的分段计算行为；
* 撑杆结果 = 原跳后伤害 + 新增跳前伤害；
* 跳前伤害用橄榄速度的行走伤害估算，计算到第一个起跳目标前约 0.5 格；
* 如果第一个起跳目标就在第 5 列，则不额外加入跳前伤害；
* 土豆雷、窝瓜、大嘴花都视为有效撑杆起跳目标；
* 空地和地刺不视为撑杆起跳目标；
* `--legacy-pole` 或 `IZEBloodCalculator(use_modified_pole=False)` 可以关闭本项目的撑杆跳前修正，用于对比旧逻辑。

如果需要查看撑杆目标、跳后伤害、跳前伤害和修正后总值，可以使用：

```python
result = calc.calculate_lane(lane, explain=True)
print(explain_pole(result))
```

---

#### `core/plant_classifier.py`

植物格子分类器。

该模块使用训练好的 KNN 特征库进行分类。

特征包括：

1. HSV 颜色直方图，用于区分植物颜色；
2. HSV 小缩略图，用于保留大致空间布局；
3. HOG 特征，用于保留植物轮廓形状。

主要类和函数：

```python
PlantClassifier
extract_features
imread_unicode
create_hog_descriptor
```

模型文件路径：

```text
models/plant_cell_classifier.npz
```

预测输出示例：

```python
{
    "label": "sunflower",
    "confidence": 0.87,
    "raw_label": "sunflower"
}
```

如果置信度低于阈值，则最终标签会被置为 `unknown`。

---

#### `core/board_recognizer.py`

当前棋盘识别的核心模块。

主要类：

```python
BoardRecognizer
```

核心目标：

* 只在有效游戏画面上初始化和更新棋盘记忆；
* 暂停菜单、选项菜单、最小化、异常截图时冻结识别；
* 初始化后不允许 `plant -> another plant`；
* 只允许 `plant -> empty`；
* `plant -> empty` 必须连续多帧确认；
* `plant -> empty` 还必须通过空地视觉检查，避免被子弹、僵尸、菜单遮挡时误删植物；
* IZE 无尽进入新一关时自动重置棋盘记忆。

输出包括：

```python
cell_results, board = board_recognizer.recognize(frame)
```

其中 `cell_results` 是每个格子的详细识别信息，`board` 是当前棋盘记忆结果。

---

#### `core/board_debug.py`

棋盘识别结果可视化模块。

主要函数：

```python
draw_board_results(frame, cell_results, show_confidence=True)
```

会在截图上绘制每个格子的识别结果，包括：

* memory label；
* live label；
* raw label；
* empty streak；
* 空地视觉检查；
* 异常帧状态。

这是 `tools/debug_board_recognition.py` 调试窗口中主要使用的绘制函数。

---

#### `core/theme_recognizer.py`

IZE 主题识别模块。

主要类：

```python
ThemeRecognizer
StableThemeRecognizer
```

核心思路：

1. 只统计 IZE 初始植物区域，即 5 行 × 前 5 列 = 25 格；
2. 忽略 `empty`、`unknown`、`invalid_frame`；
3. 将 `sunflower`、`puffshroom` 作为 support plants；
4. 用 `Counter` 统计植物可重集；
5. 与 `theme_signatures.yaml` 中的主题签名计算距离；
6. 连续多帧稳定后锁定主题。

---

#### `core/board_corrector.py`

基于主题先验的棋盘纠错模块。

主要类：

```python
ThemeBoardCorrector
```

当前主要用于修正豌豆射手和双发射手这类容易混淆的情况。

例如：

```yaml
rules:
  综合:
    repeater: peashooter

  输出:
    peashooter: repeater

  控制:
    peashooter: repeater
```

纠错范围只看 IZE 初始化区域，即前 5 列 `c0-c4`。

---

#### `core/card_detector.py`

僵尸卡槽检测模块。

主要类：

```python
CardDetector
```

主要功能：

* 根据 `settings.yaml` 中的卡槽配置计算每张僵尸卡牌位置；
* 裁剪卡槽区域；
* 根据亮度和灰度标准差判断卡牌是否可用。

目前这是较简单的经验规则，主要服务于早期自动操作逻辑。

---

#### `core/controller.py`

PVZ 鼠标控制模块。

主要类：

```python
PVZController
```

主要功能：

* 将 PVZ 客户区内部坐标转换为屏幕绝对坐标；
* 点击卡牌；
* 点击棋盘格；
* 执行放置僵尸动作；
* 在暂停、退出或紧急停止时释放鼠标和键盘状态。

目前主要供 `main.py` 早期自动操作入口使用。

---

#### `core/decision.py`

早期策略规划模块。

主要类：

```python
IZombieDecisionMaker
```

第一版策略逻辑：

* 统计每一行植物强度；
* 选择防守最弱的一行；
* 根据该行强度选择僵尸卡牌。

该模块目前仍比较简单，主要作为后续自动决策扩展的起点。

---

#### `core/game_state.py`

游戏状态缓存模块。

主要类：

```python
GameState
```

用于保存当前识别到的棋盘、卡牌和阳光数量。

目前功能较轻，主要用于早期 `main.py` 自动操作链路。

---

#### `core/plant_detector.py`

早期模板匹配版植物识别模块。

主要类：

```python
PlantDetector
```

第一版识别策略：

* 对每个格子裁剪 cell image；
* 和 `assets/templates/plants` 中的模板做 `cv2.matchTemplate`；
* 选择分数最高且超过阈值的植物。

当前主要识别链路已经转向 `BoardRecognizer + PlantClassifier`，所以该文件可以视为早期版本或备用方案。

---

### 5.3 `tools/`

`tools/` 存放调试、数据采集、训练和资源处理脚本。

#### `tools/debug_board_recognition.py`

当前最重要的调试入口。

主要功能：

* 加载 `config/settings.yaml` 和可选的 `config/local_settings.yaml`；
* 查找 PVZ 窗口，并将窗口恢复 / 置前；
* 检测 PVZ 客户区是否被其他窗口遮挡，遮挡时冻结识别；
* 截取游戏客户区，优先使用 `mss`，失败时回退到 `pyautogui.screenshot`；
* 调用 `BoardRecognizer` 识别棋盘；
* 调用 `ThemeRecognizer` 识别主题；
* 多帧稳定后锁定主题；
* 根据主题调用 `ThemeBoardCorrector` 修正棋盘，并同步修正 `BoardRecognizer` 内部 memory；
* 检测新一关导致的棋盘大范围变化，并重置主题锁定；
* 从修正后的 board 中提取前 5 列，传入 `IZEBloodCalculator`；
* 构造 `BreakContext`，将主题、棋盘和算血结果传给策略层；
* 调用 `ThemeBreakerRouter`，根据主题自动路由到 `strategies/` 下对应主题文件；
* 在终端输出当前 `BreakPlan`，目前只打印计划，不执行自动点击；
* 在 `PVZ Board Recognition Debug` 窗口显示棋盘、主题和格子细节；
* 在 `IZE Blood Calculator Debug` 窗口显示每行算血结果。

该文件现在串起了当前项目最完整的识别 + 主题 + 纠错 + 算血 + 策略路由流程，交接时建议优先阅读。

算血相关辅助函数包括：

```python
extract_ize_board
calculate_blood_table
draw_blood_table_window
normalize_blood_label
get_blood_mode_value
get_blood_mode_status
```

注意：`IZEBloodCalculator` 是可选导入。如果 `core/ize_blood_calculator.py` 缺失或导入失败，棋盘识别窗口仍会运行，算血窗口会显示错误信息。

---

#### `tools/debug_breaker_router.py`

新增的主题破阵策略路由调试工具。它不依赖 PVZ 窗口、OpenCV 截图、棋盘识别和真实算血器，可以直接用假棋盘和假算血结果测试策略接口。

运行方式：

```bash
python .\tools\debug_breaker_router.py
```

测试内容：

```text
BreakContext
    ↓
ThemeBreakerRouter
    ↓
strategies/<theme>.py
    ↓
BreakPlan
```

该脚本会依次测试 8 个主题：

```text
综合 / 控制 / 即死 / 输出 / 爆炸 / 倾斜 / 穿刺 / 回复
```

输出内容包括：

```text
theme
confidence
reason
actions
debug
```

队友写完任意主题的 `solve(context)` 后，可以先运行该脚本确认策略文件能正常返回 `BreakPlan`。这比每次打开游戏窗口调试更快。

---

#### `tools/debug_ize_blood_calculator.py`

新增的 IZE 血量计算命令行调试工具。它不依赖游戏窗口和截图，可以直接输入一行或一整块棋盘，验证 `core/ize_blood_calculator.py` 的计算结果。

主要功能：

* 支持默认示例棋盘；
* 支持 `--lane` 输入单行，逗号分隔 5 个植物标签；
* 支持 `--board` 输入多行，分号分隔行，逗号分隔格子；
* 支持 `--json` 输出原始结构化结果；
* 支持 `--explain` 输出撑杆修正细节；
* 支持 `--legacy-pole` 关闭 PVZAgent 新撑杆逻辑，便于和旧版结果对比；
* 支持从项目根目录运行，也支持在部分场景下和 `ize_blood_calculator.py` 放在同一目录运行。

常用命令：

```bash
python .\tools\debug_ize_blood_calculator.py
python .\tools\debug_ize_blood_calculator.py --lane "snowpea,repeater,wallnut,empty,puffshroom"
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --explain
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --legacy-pole --explain
python .\tools\debug_ize_blood_calculator.py --json --lane "snowpea,repeater,wallnut,empty,puffshroom"
```

整板输入格式：

```text
row1_col1,row1_col2,row1_col3,row1_col4,row1_col5; row2_col1,row2_col2,...
```

示例：

```bash
python .\tools\debug_ize_blood_calculator.py --board "empty,empty,empty,empty,empty; peashooter,empty,empty,empty,empty; snowpea,repeater,wallnut,empty,puffshroom"
```

---

#### `tools/extract_plant_cells.py`

训练样本采集工具。

主要功能：

* 自动查找 PVZ 窗口；
* 截取 PVZ 游戏画面；
* 根据棋盘参数绘制网格预览；
* 按 `S` 后裁剪前 5 列格子；
* 保存到 `assets/templates/plants_raw/batch_时间戳/`。

该脚本适合用于制作或扩充 `assets/plants_labeled/` 训练集。

---

#### `tools/train_plant_classifier.py`

植物分类模型训练脚本。

主要流程：

1. 读取 `assets/plants_labeled/` 下的分类数据；
2. 按类别收集图片；
3. 划分训练集和验证集；
4. 对训练图片做轻微增强，包括变亮、变暗、轻微模糊；
5. 提取 HSV 直方图、HSV 缩略图、HOG 特征；
6. 标准化特征；
7. 使用 KNN 思路保存训练特征库；
8. 输出验证集准确率和混淆矩阵；
9. 保存模型到 `models/plant_cell_classifier.npz`。

---

#### `tools/picture_name.py`

游戏解包素材目录扫描工具。

主要功能：

* 遍历 `zombieImages/` 下的图片文件；
* 读取每张图片的宽、高、通道数和透明通道信息；
* 生成 `asset_manifest.csv`。

目前该脚本和游戏素材解包相关，当前棋盘识别流程暂时用不到。

---

### 5.4 `strategies/`

`strategies/` 是新增的主题破阵逻辑目录，也是队友接下来主要需要修改的地方。

当前计划是 8 个 IZE 主题分别对应 8 个 Python 文件：

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

除此之外：

```text
strategies/__init__.py     标记 strategies 为 Python 包
strategies/_template.py    给队友复制使用的策略模板
```

每个主题文件都应该实现同一个函数：

```python
def solve(context: BreakContext) -> BreakPlan:
    ...
```

最小模板：

```python
from core.breaker_types import BreakAction, BreakContext, BreakPlan

THEME_NAME = "输出"

def solve(context: BreakContext) -> BreakPlan:
    return BreakPlan(
        theme=THEME_NAME,
        actions=[
            BreakAction(
                zombie="football",
                row=2,
                note="示例：选择第 3 行橄榄",
            )
        ],
        confidence=0.8,
        reason="第 3 行橄榄收益最高",
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

当前 `BreakAction.zombie` 建议先使用下面这些字符串，方便和算血器模式对齐：

```text
pole        撑杆
slow        慢速普通僵尸
ladder      梯子
football    橄榄
pole_ladder 撑杆梯子
```

目前策略层只需要返回计划，不需要执行鼠标点击。真实自动点击后续再由 `controller.py` 或新的执行器统一接入。

---

### 5.5 `utils/`

#### `utils/debug_view.py`

早期调试视图模块。

主要类：

```python
DebugView
```

主要用于 `main.py` 中绘制棋盘格和卡槽可用状态。

当前主调试入口 `tools/debug_board_recognition.py` 使用的是 `core/board_debug.py` 中的可视化逻辑，因此 `debug_view.py` 更偏早期自动操作链路。

---

### 5.6 `assets/`

#### `assets/plants_labeled/`

植物分类模型训练集。

目录结构是：

```text
assets/plants_labeled/
├─ chomper/
├─ empty/
├─ fumeshroom/
├─ kernelpult/
├─ magnetshroom/
├─ peashooter/
├─ potatomine/
├─ puffshroom/
├─ repeater/
├─ scaredyshroom/
├─ snowpea/
├─ spikeweed/
├─ splitpea/
├─ squash/
├─ starfruit/
├─ sunflower/
├─ threepeater/
├─ torchwood/
├─ umbrellaleaf/
└─ wallnut/
```

每个子文件夹是一个类别，里面是对应类别的格子截图。该目录是 `tools/train_plant_classifier.py` 的输入数据。

---

#### `assets/templates/`

主要存放数据采集和调试过程中生成的图片。

常见内容：

```text
assets/templates/plants_raw/
assets/templates/grid_preview.png
assets/templates/pvz_full_frame.png
assets/templates/resume_detection_debug.png
```

其中：

* `plants_raw/`：由 `extract_plant_cells.py` 裁剪出的原始格子样本；
* `grid_preview.png`：棋盘网格预览图；
* `pvz_full_frame.png`：完整 PVZ 截图；
* `resume_detection_debug.png`：暂停菜单 Resume Game 识别调试图。

---

### 5.7 `models/`

#### `models/plant_cell_classifier.npz`

植物格子分类模型文件。

由下面命令生成：

```bash
python .\tools\train_plant_classifier.py
```

被下面模块加载：

```text
core/plant_classifier.py
core/board_recognizer.py
```

如果缺少该文件，运行棋盘识别时会报错，并提示先运行训练脚本。

---

### 5.8 游戏解包素材相关文件

以下内容来自游戏素材解包，目前对当前棋盘识别主流程不是必须的：

```text
zombieImages/
zombieImages.zip
asset_manifest.csv
asset_manifest_categorized.csv
asset_category_summary.csv
particles_names.txt
reanim_names.txt
```

其中 `zombieImages/` 是队友整理的 PVZ 游戏内图片素材包解包结果。当前识别流程主要依赖实时截图和训练集，不直接使用这些素材。

---

## 6. 当前主流程说明

当前推荐的识别调试流程是：

```text
打开 PVZ 游戏
        │
        ▼
运行 tools/debug_board_recognition.py
        │
        ▼
查找 PVZ 窗口并获取客户区坐标
        │
        ▼
截图当前游戏画面
        │
        ▼
根据 settings.yaml 中的 grid 参数裁剪 5×9 棋盘格
        │
        ▼
PlantClassifier 对每个格子分类
        │
        ▼
BoardRecognizer 更新棋盘记忆
        │
        ▼
ThemeRecognizer 根据前 5 列识别 IZE 主题
        │
        ▼
StableThemeRecognizer 多帧稳定后锁定主题
        │
        ▼
ThemeBoardCorrector 根据主题修正识别结果
        │
        ▼
提取 IZE 前 5 列阵型
        │
        ▼
IZEBloodCalculator 计算每行算血结果
        │
        ▼
构造 BreakContext
        │
        ▼
ThemeBreakerRouter 根据主题调用 strategies/<theme>.py
        │
        ▼
输出 BreakPlan 破阵计划
        │
        ▼
OpenCV 调试窗口显示棋盘、主题和算血结果
```

---

## 7. 棋盘识别机制说明

### 7.1 棋盘记忆

`BoardRecognizer` 不直接相信单帧识别结果，而是维护一个 `board_memory`。

原因是 PVZ 中会出现：

* 僵尸遮挡植物；
* 子弹遮挡格子；
* 暂停菜单遮挡棋盘；
* 游戏窗口被其他窗口盖住；
* 截图瞬间异常；
* 植物被吃掉时需要确认。

因此识别逻辑采用：

```text
初始化阶段：多帧投票确定初始棋盘
稳定阶段：不允许 plant -> another plant
消失判断：只允许 plant -> empty，并且必须连续多帧确认
异常画面：冻结识别，不更新 memory
新一关：检测到大量不一致后重置 memory
```

### 7.2 空地视觉检查

植物被吃掉后，格子会变为空地。但如果只是被僵尸、子弹、菜单遮挡，不能误判为空地。

因此项目增加了空地视觉检查，主要看：

* 边缘密度；
* 高亮比例；
* 中性灰比例。

只有当分类器认为是 `empty`，并且视觉上也像干净空地时，才会累计 empty streak。

### 7.3 新关卡检测

IZE 无尽每进入新一关时，红线左侧植物会重置。由于一关内部不允许 `empty -> plant`，所以需要单独检测新关卡。

当前逻辑是：

* 只检查红线左侧前几列；
* 只相信高置信度植物；
* 如果连续多帧发现大量 live 结果和 memory 不一致，就认为进入新一关；
* 调用 `reset_memory()` 重新初始化棋盘。

---

## 8. 主题识别和纠错说明

### 8.1 主题识别

IZE 主题识别只统计前 5 列，即：

```text
5 行 × 5 列 = 25 格
```

主题配置在：

```text
config/theme_signatures.yaml
```

识别时会统计植物可重集，并和每个主题的签名计算距离。多帧连续稳定后才锁定主题，避免单帧误判。

### 8.2 主题纠错

有些植物外观相似，分类器容易混淆，例如：

```text
peashooter / repeater
```

因此在主题锁定后，可以根据主题先验纠正结果。例如某个主题中理论上应该出现 repeater，但识别成了 peashooter，就可以按规则修正。

纠错配置在：

```text
config/settings.yaml
```

对应字段：

```yaml
board_corrector:
  rules:
    综合:
      repeater: peashooter

    输出:
      peashooter: repeater

    控制:
      peashooter: repeater
```

---

## 9. IZE 血量计算器说明

新增的算血器主要用于把视觉识别结果转成策略可用的数字参考。当前它不是自动决策器本身，而是为后续 `decision.py` 或自动放僵尸逻辑提供输入。

### 9.1 输入范围

算血器只关心 IZE 初始植物区前 5 列：

```text
5 行 × 5 列
```

如果传入的是完整 5×9 棋盘，`calculate_board()` 会自动忽略第 6 到第 9 列。

单行输入示例：

```python
["snowpea", "repeater", "wallnut", "empty", "puffshroom"]
```

整板输入示例：

```python
[
    ["empty", "empty", "empty", "empty", "empty"],
    ["peashooter", "empty", "empty", "empty", "empty"],
    ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    ["starfruit", "spikeweed", "kernelpult", "empty", "empty"],
    ["potatomine", "squash", "chomper", "magnetshroom", "umbrellaleaf"],
]
```

### 9.2 植物标签

`core/ize_blood_calculator.py` 内部维护了 `LABEL_TO_PLANT`，支持项目当前分类器中的常见标签，例如：

```text
peashooter / repeater / snowpea / wallnut / potatomine / chomper
puffshroom / fumeshroom / scaredyshroom / threepeater / spikeweed
torchwood / splitpea / starfruit / magnetshroom / kernelpult / umbrellaleaf
```

同时也兼容部分写法差异，例如 `wall_nut`、`wall-nut`、`snow_pea`、`snow-pea`。

如果后续分类器新增了植物类别，需要同步补充：

```python
LABEL_TO_PLANT
PLANT_TO_CANONICAL_LABEL
```

否则算血器遇到未知标签会抛出 `ValueError`。

### 9.3 撑杆修正

本项目对原 IZE 算血思路做了一个关键修正：

```text
撑杆伤害 = 原跳后分段伤害 + 跳前行走伤害
```

跳前部分用橄榄速度估算，并计算到第一个起跳目标前约半格。

当前规则：

* 第一个起跳目标在第 5 列时，不额外加入跳前伤害；
* 第一个起跳目标越靠左，跳前行走距离越长，额外伤害越多；
* 土豆雷、窝瓜、大嘴花都视为有效撑杆起跳目标；
* 空地和地刺不视为起跳目标；
* 可以用 `--legacy-pole` 或 `use_modified_pole=False` 对比旧逻辑。

查看撑杆解释：

```bash
python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --explain
```

解释信息会包含：

```text
起跳目标
是否使用新撑杆逻辑
原跳后伤害 raw / rounded
新增跳前伤害 raw / rounded
修正后撑杆总伤害 raw / rounded
```

### 9.4 三线射手和胆小菇

三线射手：

* 同一行三线射手仍沿用原 converter 行为，简化为豌豆射手；
* 相邻行三线射手会对目标行产生跨行支援伤害；
* `calculate_board()` 会自动把目标行上下相邻行传给 `calculate_lane()`；
* 如果只调用 `calculate_lane()`，可以手动传入 `adjacent_lanes=[upper_lane, lower_lane]`。

胆小菇：

* 伤害按豌豆射手级别处理；
* 僵尸靠近时会缩头，因此不是简单全程输出；
* 当前只建模同一路僵尸导致的缩头规则，没有建模其他路僵尸导致的复杂影响。

### 9.5 推荐值和不推荐值

算血器不仅输出数值，也会给每种模式一个推荐状态。

```text
 1：推荐
 0：普通
-1：不推荐
```

在命令行表格中：

```text
*value* 表示推荐
(value) 表示不推荐
```

在 OpenCV 算血窗口中：

```text
灰底加粗：推荐
灰色括号：不推荐
普通黑字：普通
```

这套推荐规则目前仍是经验规则，主要用于辅助调试和后续策略开发，不建议直接等同于最终最优解。

---

## 10. 主题破阵策略接口说明

当前已经为队友实现 8 个主题破阵逻辑预留了统一接口。

整体链路是：

```text
棋盘识别结果
    ↓
主题识别和锁定
    ↓
主题纠错
    ↓
IZE 算血器
    ↓
BreakContext
    ↓
ThemeBreakerRouter
    ↓
strategies/<theme>.py
    ↓
BreakPlan
```

### 11.1 队友需要写哪些文件

队友主要只需要修改：

```text
strategies/hybrid.py
strategies/control.py
strategies/instant_kill.py
strategies/output.py
strategies/explosion.py
strategies/diagonal.py
strategies/piercing.py
strategies/recovery.py
```

建议先从一个主题开始，例如 `strategies/output.py`。一个主题确认能输出合理 `BreakPlan` 后，再逐个写其他主题。

### 11.2 `solve(context)` 输入

每个主题文件只需要实现：

```python
def solve(context: BreakContext) -> BreakPlan:
    ...
```

常用输入：

```python
context.theme                  # 当前主题中文名
context.board_5x5              # IZE 前 5 列阵型
context.board_5x9              # 完整 5×9 棋盘，可选
context.blood_table            # 5 行算血结果
context.lane(row)              # 第 row 行前 5 列植物
context.mode_value(row, mode)  # 某行某僵尸模式的算血值
context.mode_status(row, mode) # 1 推荐，0 普通，-1 不推荐
context.recommended_modes(row) # 第 row 行推荐模式列表
context.plant_count(row)       # 第 row 行植物数量
```

`mode` 建议使用：

```text
pole
slow
ladder
football
pole_ladder
```

### 11.3 `BreakPlan` 输出

策略函数必须返回 `BreakPlan`。

示例：

```python
return BreakPlan(
    theme="输出",
    actions=[
        BreakAction(
            zombie="football",
            row=2,
            note="第 3 行橄榄推荐，伤害最低",
        )
    ],
    confidence=0.8,
    reason="输出主题：选择第 3 行橄榄",
)
```

当前 `debug_board_recognition.py` 只会把 `BreakPlan` 打印到终端，例如：

```text
[Breaker] theme=输出 | confidence=0.80 | actions=football@R3(...) | reason=输出主题：选择第 3 行橄榄
```

暂时不会自动点击，因为 `config/settings.yaml` 中保持：

```yaml
strategy:
  execute_actions: false
```

### 11.4 策略调试方式

不打开游戏，测试策略路由：

```bash
python .\tools\debug_breaker_router.py
```

打开游戏，测试真实识别链路：

```bash
python .\tools\debug_board_recognition.py
```

真实调试时，必须等主题稳定锁定后才会调用策略。当前配置是：

```yaml
strategy:
  require_locked_theme: true
```

### 11.5 队友开发注意事项

队友写策略时建议遵守：

* 不要直接调用 OpenCV；
* 不要直接调用 `BoardRecognizer`；
* 不要直接修改 `core/ize_blood_calculator.py`；
* 不要直接做鼠标点击；
* 只根据 `BreakContext` 判断阵型和算血结果；
* 只返回 `BreakPlan`；
* 一个主题一个文件，先写简单可跑版本，再逐步优化。

---

## 11. 常见问题

### 11.1 找不到 PVZ 窗口

检查：

1. 游戏是否已经打开；
2. 游戏窗口标题是否包含 `Plants vs. Zombies`；
3. `config/settings.yaml` 中的配置是否正确：

```yaml
window:
  title_keywords:
    - "Plants vs. Zombies"
```

也可以运行：

```bash
python .\test_window.py
```

查看当前系统中的窗口标题。

---

### 11.2 棋盘格子位置不对

窗口可以自动捕捉，但棋盘区域参数是人工调好的。如果游戏窗口大小、缩放、分辨率发生变化，可能需要重新调整：

```yaml
grid:
  board_left: 30
  board_top: 80
  board_width: 735
  board_height: 500
```

可以运行：

```bash
python .\tools\extract_plant_cells.py
```

查看 `grid_preview.png`，根据网格预览图调整参数。

---

### 11.3 缺少模型文件

如果出现类似错误：

```text
Plant classifier model not found: models/plant_cell_classifier.npz
```

说明还没有训练模型，运行：

```bash
python .\tools\train_plant_classifier.py
```

---

### 11.4 中文路径读取图片失败

项目中部分图片读取和保存使用了 `np.fromfile + cv2.imdecode` 或 `cv2.imencode + tofile`，是为了兼容 Windows 中文路径下 `cv2.imread` / `cv2.imwrite` 可能失败的问题。

---

### 11.5 暂停菜单或其他窗口遮挡导致识别异常

`tools/debug_board_recognition.py` 和 `BoardRecognizer` 中已经加入了窗口遮挡检测和菜单覆盖检测。

当检测到异常时，识别会冻结，不会更新棋盘记忆。

---

### 11.6 算血窗口不显示或显示不可用

检查：

1. 是否存在 `core/ize_blood_calculator.py`；
2. 是否从项目根目录运行 `tools/debug_board_recognition.py`；
3. 是否在本地配置里关闭了算血窗口：

```yaml
blood_calculator:
  debug_window_enabled: false
```

如果 `IZEBloodCalculator` 导入失败，主棋盘识别窗口仍会运行，算血窗口会显示错误文本。

如果中文显示异常，可以安装 Pillow，脚本会优先尝试用 Windows 中文字体绘制中文；如果不可用，会自动回退到英文文本。

---

### 11.7 主题锁定后没有输出 Breaker 策略

检查：

1. `config/settings.yaml` 中是否启用了策略：

```yaml
strategy:
  enabled: true
  log_plan: true
```

2. 是否已经稳定锁定主题。当前配置要求锁定主题后才调用策略：

```yaml
strategy:
  require_locked_theme: true
```

3. 对应主题文件是否存在，例如主题是 `输出` 时，需要存在：

```text
strategies/output.py
```

4. 主题文件中是否实现了：

```python
def solve(context):
    ...
```

5. `solve(context)` 是否返回 `BreakPlan`。

可以先运行：

```bash
python .\tools\debug_breaker_router.py
```

确认策略路由和单个主题文件没有问题。

---

## 12. 后续可继续完善的方向

后续如果继续开发，可以考虑：

1. 完善 `strategies/` 下 8 个主题的破阵逻辑；
2. 给每个主题策略增加独立测试用例；
3. 将 `debug_board_recognition.py` 中的新识别链路接回 `main.py`；
4. 统一旧版 `PlantDetector` 和新版 `BoardRecognizer` 的数据结构；
5. 在 8 个主题策略稳定后，再考虑是否整合或替代旧版 `decision.py`；
6. 接入更精确的僵尸卡牌识别；
7. 将主题识别、棋盘纠错、算血结果、主题策略和自动操作整合成完整 agent；
8. 给 `requirements.txt` 补充 `pywin32`；
9. 增加 `config/local_settings.yaml.example`，方便不同电脑单独配置棋盘坐标；
10. 增加更多训练样本，提高植物分类器泛化能力；
11. 对 `assets/` 和 `zombieImages/` 等大文件目录做 `.gitignore` 或压缩包管理；
12. 将调试图片、原始裁剪样本和模型文件区分为“源码必需”和“可再生成文件”；
13. 为 `core/ize_blood_calculator.py` 增加单元测试，覆盖撑杆修正、三线射手跨行支援、胆小菇缩头、磁力菇推荐状态等关键规则；
14. 后续可将 `BreakPlan` 接入 `controller.py`，从“识别 + 算血 + 输出计划”进一步推进到自动选僵尸和自动下僵尸。

## 13. 推荐阅读顺序

队友接手时建议按下面顺序阅读：

```text
1. config/settings.yaml
2. core/breaker_types.py
3. strategies/_template.py
4. strategies/output.py
5. tools/debug_breaker_router.py
6. tools/debug_board_recognition.py
7. core/breaker_router.py
8. core/board_recognizer.py
9. core/plant_classifier.py
10. core/theme_recognizer.py
11. core/board_corrector.py
12. core/ize_blood_calculator.py
13. tools/debug_ize_blood_calculator.py
14. core/grid.py
15. tools/train_plant_classifier.py
16. tools/extract_plant_cells.py
17. main.py
```

其中 `core/breaker_types.py`、`strategies/_template.py`、`tools/debug_breaker_router.py` 是队友实现主题破阵逻辑最应该先看的文件；`tools/debug_board_recognition.py` 是理解真实识别链路的关键入口。

---

## 14. 简短交接说明

当前项目的核心不是 `main.py`，而是 `tools/debug_board_recognition.py` 这条调试链路。

当前最重要的成果是：

```text
PVZ 窗口截图
→ 棋盘格子裁剪
→ KNN 植物分类
→ 棋盘记忆稳定识别
→ IZE 主题识别
→ 主题先验纠错
→ IZE 血量计算
→ ThemeBreakerRouter 主题策略路由
→ BreakPlan 破阵计划输出
→ OpenCV 可视化调试
```

`main.py` 中的自动点击和策略逻辑目前可以作为后续扩展方向，不建议作为当前主要入口。后续更合理的扩展路径是：先把 `tools/debug_board_recognition.py` 中已经稳定的识别、主题、纠错和算血链路封装成可复用状态，再接入 `decision.py` 和 `controller.py` 做自动策略。

---

## 15. 队友当前应该做什么

队友接手后的当前任务非常明确：**只实现 `strategies/` 目录下 8 个主题的破阵逻辑**。

### 15.1 不需要改的部分

队友暂时不需要修改：

```text
core/board_recognizer.py
core/theme_recognizer.py
core/board_corrector.py
core/ize_blood_calculator.py
tools/debug_board_recognition.py
core/controller.py
main.py
```

这些部分目前已经可以提供识别结果、主题结果、算血结果和策略调用入口。

### 15.2 需要改的部分

队友主要修改：

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

每个文件只实现：

```python
def solve(context: BreakContext) -> BreakPlan:
    ...
```

### 15.3 推荐开发顺序

建议不要 8 个主题同时写。推荐顺序：

```text
1. 先选一个主题，例如 output.py；
2. 根据 context.board_5x5 和 context.blood_table 写最简单的可运行规则；
3. 返回 BreakPlan；
4. 运行 python .\tools\debug_breaker_router.py；
5. 确认该主题能输出 actions；
6. 再运行 python .\tools\debug_board_recognition.py 做真实画面测试；
7. 一个主题稳定后，再复制经验到其他主题。
```

### 15.4 当前交付标准

每个主题文件完成后，至少应该做到：

* 不报错；
* `solve(context)` 一定返回 `BreakPlan`；
* 如果暂时没有合适动作，返回空 `actions=[]`，并写清楚 `reason`；
* 如果有动作，返回至少一个 `BreakAction`；
* `reason` 能解释为什么选择该行、该僵尸；
* 可以通过 `tools/debug_breaker_router.py` 测试；
* 可以在真实游戏调试中看到 `[Breaker]` 输出。

### 15.5 示例

```python
from core.breaker_types import BreakAction, BreakContext, BreakPlan

THEME_NAME = "输出"

def solve(context: BreakContext) -> BreakPlan:
    best_row = None
    best_value = None

    for row in range(5):
        if context.mode_status(row, "football") != 1:
            continue

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
            reason="没有找到推荐橄榄的行",
        )

    return BreakPlan(
        theme=THEME_NAME,
        actions=[
            BreakAction(
                zombie="football",
                row=best_row,
                note=f"橄榄推荐，伤害={best_value}",
            )
        ],
        confidence=0.8,
        reason=f"选择第 {best_row + 1} 行橄榄",
    )
```
