# IQ 平均程序分析报告

## 目标程序
**文件名**: `rt_aver_calc.v`
**路径**: 
- `/mnt/win_data/Viavado_doc/channel_air_v4/IP/SCFDE/xilinx.gpp.com_user_phy_demodulation_2.0/src/rt_aver_calc.v`
- `/mnt/win_data/Viavado_doc/channel_ground_v4/IP/SCFDE/xilinx.gpp.com_user_phy_demodulation_2.0/src/rt_aver_calc.v`

## 平均方式
**滑动窗口平均（Moving Average / 实时滑动窗口平均）**

## 详细分析

### 1. 窗口大小
- RAM 深度参数: `RAM_DEPT=2048`
- 实际使用窗口大小: **RAM_DEPT/2 = 1024 个采样点**
- 对应代码: `localparam ACC_BW=clogb2(RAM_DEPT/2-1);`

### 2. 核心算法
这是一个**滑动窗口累加器**实现：

**阶段一（前1024个样本）**:
```verilog
if((acc_din_sel == 1'd0) & rt_ram_wea)
    data_in_acc <= data_in_acc + rt_ram_dina;  // 直接累加新数据
```

**阶段二（1024个样本之后）**:
```verilog
else if((acc_din_sel == 1'd1) & rt_ram_wea)
    data_in_acc <= data_in_acc + din_dif;      // 累加差值（新数据 - 最旧数据）
```

**差值计算**:
```verilog
din_dif <= $signed(i_data_in) - rt_ram_doutb;  // 当前输入 - 从RAM读出的旧数据
```

**输出计算**:
```verilog
assign o_data_out = data_in_acc[IN_BW+ACC_BW-1:ACC_BW];  // 右移10位（除以1024）
```

### 3. 工作机制
1. 使用双端口RAM存储最近1024个历史数据
2. 当新数据到来时，同时从RAM读出最旧的数据（1024个时钟周期前的数据）
3. 计算差值: `新数据 - 最旧数据`
4. 更新累加器: `累加和 = 累加和 + 差值`
5. 输出平均值: `累加和 / 1024`

### 4. 结论
**这不是去掉首个IQ或最后一个IQ后求平均，也不是直接对所有数据求平均。**

而是采用**滑动窗口平均**的方式：
- 维护一个固定大小为1024的窗口
- 每个时钟周期输出当前窗口内1024个数据的平均值
- 新数据进入窗口的同时，最旧的数据被移出窗口
- 这是一种实时滑动平均，适用于连续数据流的平滑处理

## 数学表达
$$Output[n] = \frac{1}{N} \sum_{i=n-N+1}^{n} Input[i]$$

其中 $N = 1024$，每次输出都是最近1024个采样点的算术平均值。
