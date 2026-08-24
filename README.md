# IMMA2 质控软件

ICOADS 海洋观测数据（IMMA 初步处理后的月度 CSV）的质量控制桌面程序：
**自动质控 + 可视化人工复核**。

程序自动执行删除/标记，然后在界面中按年份、按站点查看结果——
自动删除的点、待复核的点在地图和时间序列图上以不同颜色和形状显示，
通过**框选**可以恢复被误删的点，或删除程序未发现的离群点。
所有人工决定自动保存，导出时与自动规则一并生效。

## 安装

```bash
pip install -e .
# 或者只装依赖：
pip install -r requirements.txt
```

## 启动界面

```bash
python -m imma2_qc
# 或安装后：
imma2-qc
```

### 使用流程

1. **打开数据目录**：选择存放月度 CSV（如 `IMMA1_2003-01_VI1.csv`）的目录，
   程序读取全部文件并自动运行质控（输入始终只读）；
2. 左侧选择**年份**和**站点**（按“删除+复核数”降序排列，`<全部站点>` 可总览该年）；
3. 在**地图视图**（默认内置国界底图，含航迹连线，可切换 GSHHG 海岸线）或**时间序列**中检查异常点；
4. 打开**框选模式**，在图上拖拽矩形选择点（多次框选累加，底部表格中选行也会同步选中）：
   - **删除所选**：人工删除程序未发现的离群点；
   - **恢复所选**：推翻程序的自动删除；
   - **清除所选人工决定**：撤销之前的人工操作；
5. 人工决定自动保存到 `<输入目录>/_qc_workspace/manual_decisions.csv`，
   下次打开同一目录自动加载；
6. **导出结果**：输出清洗后的月度 CSV 和 `_qc_audit/` 审计文件
   （summary、deleted_records、review_records、manual_decisions、settings.json）。

“设置 → 质控参数”可修改全部阈值（JSON），改完点“重新运行质控”生效。
地图默认使用内置的国界底图（`imma2_qc/assets/basemap/country.shp`）；
“设置 → 选择 GSHHG 海岸线目录”可换用 GSHHG 海岸线（自动优先粗分辨率保证流畅），
“设置 → 恢复内置国界底图”切回默认。

## 命令行批处理（不开界面）

```bash
python -m imma2_qc.cli --input-dir <输入目录> --output-dir <输出目录> \
    [--config qc_config.json] \
    [--decisions <输入目录>/_qc_workspace/manual_decisions.csv] \
    [--overwrite]
```

适合界面中完成人工复核后，对全部年份批量重跑导出。

## 质控规则

处理顺序（对应 icoads_qc_v5 文档的规则体系）：

| 步骤 | 规则 | 标记 | 处理 |
|---|---|---|---|
| 1 | 基础字段：站号/日期/经纬度/观测值/质量码/航速档合法性，缺失值统一识别，经度归一化 [0,360) | `DELETE_INVALID_BASIC_FIELD` | 自动删除 |
| 2 | SHIP 占位站号 | `DELETE_SHIP` | 自动删除 |
| 2 | MASKSTID（`keep` 策略保留但不参与轨迹检查 / `drop` 删除） | `DELETE_MASKSTID` | 可配置 |
| 3 | 同站同刻位置冲突（30 km 聚簇 / 100 km 冲突，唯一可达簇保留） | `DELETE_SAME_TIME_OFF_TRAJECTORY` / `SAME_TIME_DISTANT_POSITIONS` | 自动删除 / 人工复核 |
| 4 | 三点单点漂移（按 VS_CODE 航速档上限 + 15 km 缓冲，跳距 ≥500 km、桥接 ≤100 km） | `DELETE_HIGH_CONFIDENCE_ISOLATED_SPIKE` | 自动删除 |
| 5 | 特殊零坐标：(0,0)、突跳到 0 后返回（零坐标点不自动删除） | `COORDINATE_0_0` / `SUDDEN_ZERO_AND_RETURN` | 人工复核 |
| 6 | 观测值时间序列尖峰（滑动中位数+MAD）与台阶突变 | `VALUE_SERIES_SPIKE` / `VALUE_SERIES_STEP` | 人工复核 |
| 7 | 严格去重（全部业务字段） | `DELETE_STRICT_DUPLICATE` | 自动删除 |
| 8 | 站点—年份记录数 < 30 | `DELETE_STATION_YEAR_LT_MIN` | 自动删除 |

原则：高置信异常自动删除（界面中仍可恢复）；低置信异常保留并进入复核清单；
人工决定优先于自动规则；每条删除/复核/人工操作均可追溯。

尚未纳入本版的原流程规则（后续可加）：单点/连续段镜像坐标修复、
GSHHG 海陆检查（`DELETE_DEEP_LAND`）、固定站迁移分段。

## 数据格式

输入 CSV 需包含列（列名可在质控参数中修改）：
`STATION, DATE, LATITUDE, LONGITUDE, VIS, Q_VIS, VS_CODE`。
空串、`NA`、`NAN`、`NULL`、`999999`、`-9999` 等统一视为缺失。

## 开发

```bash
python scripts/generate_sample_data.py   # 生成含注入异常的样例数据 sample_data/
python -m pytest tests/ -v               # 运行测试
```

代码结构：

```
imma2_qc/
├── config.py        # 全部阈值与航速档位表（QCConfig）
├── flags.py         # 质控标记常量
├── geo.py           # 大圆距离、经度归一化
├── io_utils.py      # CSV 读取、记录 UID
├── qc/
│   ├── basic.py     # 基础字段检查、特殊站号
│   ├── track.py     # 同刻冲突、单点漂移、零坐标
│   ├── timeseries.py# 观测值尖峰/台阶
│   └── engine.py    # 流水线编排与统计
├── decisions.py     # 人工决定持久化
├── status.py        # 自动结果+人工决定 → 显示状态
├── export.py        # 清洗结果与审计文件导出
├── cli.py           # 命令行批处理
└── gui/             # PySide6 界面（主窗口、地图/时序画布、海岸线底图）
```
