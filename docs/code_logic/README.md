# chan_meas 代码导读 - 文档版本说明

## 📚 两个版本可选

本文档分为**详细版**和**脱水版**两套，适应不同的学习需求。

### 详细版 (完整理解)
- 文件 : `INDEX.md`, `paths.md`, `bin_reader.md`, `bin_reader_luoyang.md`, `cfo_estimator.md`
- 特点 : 每个步骤详细解释，包含代码示例、常见错误、使用场景
- 适合 : 新手、需要深入理解细节、实际开发调试
- 阅读时间 : 2-3小时

### 脱水版 (核心精要)
- 文件 : `INDEX_compact.md`, `paths_compact.md`, `bin_reader_compact.md`, `bin_reader_luoyang_compact.md`, `cfo_estimator_compact.md`
- 特点 : 只保留物理/数学本质、核心算法骨架，无冗余细节
- 适合 : 有基础的工程师、快速复习、论文写作参考
- 阅读时间 : 20-30分钟

## 🎯 快速导航

### 第一次接触 chan_meas？
1. 读 **INDEX_compact.md** (5分钟) → 整体认识
2. 读 **paths_compact.md** (2分钟) → 配置逻辑
3. 选择数据格式：
   - 标准格式 → **bin_reader_compact.md**
   - 洛阳格式 → **bin_reader_luoyang_compact.md** + **cfo_estimator_compact.md**

### 需要实现某个功能？
1. 在详细版中找对应函数
2. 理解数据契约(输入/输出形状)
3. 参考代码示例实现

### 调试/优化频偏估计？
→ **cfo_estimator_compact.md** 第"两种CFO估计方法的区别"表

### 理解频响校正？
→ **bin_reader_compact.md** 最后的频响校正公式

## 📊 文档对应关系

```
脱水版                              详细版
────────────────────────────────────────────────
INDEX_compact.md      ←→  INDEX.md (总览)
paths_compact.md      ←→  paths.md
bin_reader_compact.md ←→  bin_reader.md (核心)
bin_reader_luoyang_compact.md ←→  bin_reader_luoyang.md
cfo_estimator_compact.md ←→  cfo_estimator.md
```

## 💡 脱水版的"脱水"原则

### 详细版中的内容（已删除）
- ✂️ Docstring（文档字符串）
- ✂️ 错误处理（try-except）
- ✂️ 日志/打印语句
- ✂️ 代码注释（用符号变量替代）
- ✂️ 使用示例（详细版已有）

### 脱水版保留（核心）
- ✅ 物理/数学本质 (1-2句话)
- ✅ 核心算法骨架 (数学公式)
- ✅ 数据契约 (张量维度)
- ✅ 常见陷阱 (简表格)
- ✅ 符号定义 (物理参数)

## 📐 符号约定

脱水版统一使用的数学符号：

```
F_s                采样率 (Hz)
T_s = 1/F_s       采样间隔 (s)
BW                信号带宽 (Hz)
T_frame           帧周期 (s)
f_c               载波频率 (Hz)
Δf                载波频偏 (Hz)
φ                 相位 (rad)
τ                 时延 (s)
U                 LFM长度 (采样点数)
n_frames          帧总数
```

## 🚀 常见使用场景

### 场景1：快速理解项目
**推荐** : INDEX_compact.md (5min) + 脱水版相关模块

### 场景2：改进频偏估计算法
**推荐** : cfo_estimator_compact.md + cfo_estimator.md

### 场景3：支持新硬件格式
**推荐** : bin_reader_compact.md + bin_reader_luoyang.md

### 场景4：论文引用
**推荐** : 
- 流程图 : INDEX_compact.md
- 公式 : bin_reader_compact.md / cfo_estimator_compact.md

## ⚠️ 脱水版不包含

- ❌ 错误处理细节
- ❌ 边界条件检查
- ❌ 性能优化建议
- ❌ 具体参数值

**需要这些时** → 参考详细版

## 📖 推荐阅读顺序

### 路线A：快速上手 (30 min)
1. INDEX_compact.md
2. paths_compact.md
3. bin_reader_compact.md / bin_reader_luoyang_compact.md
4. cfo_estimator_compact.md

### 路线B：深度学习 (2-3 hours)
1. INDEX.md
2. paths.md
3. bin_reader.md
4. cfo_estimator.md
5. bin_reader_luoyang.md

### 路线C：问题解决 (15-30 min)
- 频响校正 → bin_reader.md `_fr_calibrate()`
- 频偏估计 → cfo_estimator_compact.md 表格
- 相位抵消 → INDEX_compact.md "问题2"
- B2B校准 → bin_reader_compact.md "陷阱"

---

文档维护 : 2026-04-08
对应代码版本 : chan_meas master
