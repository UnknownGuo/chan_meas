# UI 进度备份说明（2026-06-14）

## 目的
记录 `chan_meas` Web UI 当前相对稳定的一版，便于后续继续迭代时回滚、比对和排错。

## 当前页面结构
- 左侧：数据导入 / 分析选项 / 回放控制
- 右侧主内容区：
  1. 第一行：
     - `CIR 瀑布图 / 时延-功率`
     - `Doppler 谱瀑布图 / Delay 平均`
  2. 第二行：
     - `MUSIC/SAGE 多径参数`
  3. 第三行：
     - `GPS 轨迹与 Tx/Rx 位置`
     - `当前帧 CIR/PDP 曲线`
     - `统计参数`

## 当前关键行为

### 1. 时间轴与帧率
- UI 时间轴按窗口秒级显示：
  - `currentTimeLabel` 按 `frameStats[*].timeSec` 显示
  - `durationLabel` 按 `meta.frameRateHz = 1.0` 计算总时长
- 回放控制中的“帧率”显示原始帧率：
  - 优先显示 `meta.rawFrameRateHz`
  - 当前默认数据为 `100.0 Hz`

### 2. Doppler 瀑布图
- 数据加载时绘制一次 `Doppler 谱瀑布图 / Delay 平均`
- 切换帧时不重绘 Doppler 瀑布图
- 只更新：
  - 地图
  - 当前帧 CIR/PDP
  - 统计参数

### 3. 统计参数
当前显示：
- 路径数
- 最大功率
- 平均功率
- 峰值时延
- 均方根时延
- Tx-Rx 距离

### 4. 地图
- 使用 Leaflet
- 底图通过本地代理接口：
  - `/tiles/base/{z}/{x}/{y}.jpg`
- 后端代理下载 Esri Imagery 瓦片并缓存

## 当前布局比例

### 主分析区
在 `web/static/styles.css` 中：
- `.analysis-grid`
  - `grid-template-columns: repeat(2, minmax(0, 1fr))`
  - `grid-template-rows: 300px 260px`

含义：
- 第一行两个热力图各半宽，高度 300px
- 第二行 MUSIC/SAGE 独占整行，高度 260px

### 第三行
- `.bottom-grid`
  - `grid-template-columns: 1.55fr 1.15fr 0.85fr`
  - `height: 220px`

含义：
- GPS 最宽
- PDP 次之
- 统计参数最窄，但比更早版本已放宽

## 当前数据与语义
- 默认数据集：`zjk_last_measurement_max15_full.json`
- `frameRateHz = 1.0`
- `rawFrameRateHz = 100.0`
- CIR/PDP 时延显示截断到 `6000 ns`
- Doppler 图为 delay 平均后的 Doppler-Time 瀑布图
- MUSIC/SAGE 图为：
  - 上：Delay-Time
  - 下：Doppler-Time

## 本版已确认修复的问题
1. 默认数据不再是旧的 95/96 帧样例
2. UI 总时长不再错误显示为 6.810 s
3. CIR/PDP 已限制到 6000 ns
4. Doppler 图已改为正确的 Doppler-Time 瀑布图
5. 工程接口区域已删除
6. 地图已改为可正常显示的联网瓦片代理
7. 第三行已重新放大
8. 统计参数中的“均方根时延”已恢复
9. 切换帧时 Doppler 图不再刷新
10. Doppler 图首次加载不显示的问题已修复

## 当前涉及的主要文件
- `src/frontend_app.py`
- `web/index.html`
- `web/static/styles.css`
- `web/static/app.js`
- `data/ui_samples/zjk_last_measurement_max15_full.json`
- `memory.md`

## 回滚建议
如果后续 UI 改坏，优先检查并回滚：
1. `web/static/styles.css`
2. `web/static/app.js`
3. 如涉及数据语义，再检查 `src/ui_dataset.py` 与导出脚本

## 验证方式
### 测试
```bash
cd /home/guo/桌面/project/chan_meas
.venv/bin/python -m pytest tests/test_frontend_app.py -q
```

### 页面
建议刷新：
```text
http://127.0.0.1:8765/?v=ratio-final-3
```
必要时使用 `Ctrl + F5` 强制刷新静态资源。

## 备注
这不是最终定稿，只是 2026-06-14 的阶段性稳定备份。后续若继续优化布局，建议每次在这个文件末尾追加“变更记录”。
