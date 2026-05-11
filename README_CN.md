# Slip

一个极简的 HDL DSL 编译器，将 `.slip` 源文件编译为可综合的 SystemVerilog。

**[English](README.md)** | 中文

## 概述

Slip 是一种简洁的硬件描述语言，本质上是 SystemVerilog 的语法糖。它为常见的硬件设计模式提供了精简的语法——信号声明、组合与时序逻辑、带有正则端口映射的模块实例化、编译时元编程——同时生成干净、可读的 SystemVerilog 输出。

每个 Slip 构造都直接映射到对应的 SystemVerilog 等价形式。生成的输出通过 [pyslang](https://github.com/MikePopoloski/slang)（[slang](https://github.com/MikePopoloski/slang) 编译器的 Python 绑定）按照 IEEE 1800-2017 标准进行验证。

## 特性

- **端口方向自动推断** — 无需 `input`/`output` 关键字，方向根据信号使用方式推导
- **隐式信号声明** — 被引用但未声明为端口或实例的名称自动成为 `logic` 信号
- **时序逻辑块** — `seq (clk, neg: rst_n) { ... }` 生成 `always_ff`，自动将阻塞赋值转为非阻塞
- **组合逻辑块** — `comb { ... }` 生成 `always_comb`
- **编译时元编程** — `` `for `` 循环和 `` `if `` 条件编译，支持常量折叠
- **模板标识符** — `` `for `` 循环变量可在标识符名称中展开（如 `data_`i` → `data_0`）
- **模块实例化** — 简洁语法，支持同名简写（`.clk`）、显式连接和正则端口映射
- **IP 集成** — 通过 pyslang 自动反射外部 SystemVerilog IP 的端口和参数
- **参数与局部参数** — 模块级 `param` 可覆盖，模块体内 `localparam` 不可覆盖
- **常量校验** — 端口连接中禁止裸整数，必须使用宽度前缀（`1'b0`）或填充常量（`'0`、`'1`）
- **悬空端口标记** — `.rst_n(_)` 将端口标记为有意不连接

## 快速示例

```slip
module pipeline #(param STAGES = 3, param WIDTH = 8) (clk, rst_n, din, dout) {
    logic clk;
    logic rst_n;
    logic [WIDTH-1:0] din;
    logic [WIDTH-1:0] dout;

    // 编译时循环展开，带模板标识符
    `for (`i = 0; `i < STAGES; `i = `i + 1) {
        logic [WIDTH-1:0] stage_`i;
    }

    seq (clk, neg: rst_n) {
        if (!rst_n) {
            `for (`i = 0; `i < STAGES; `i = `i + 1) {
                stage_`i = 0;
            }
        } else {
            stage_0 = din;
            `for (`i = 1; `i < STAGES; `i = `i + 1) {
                stage_`i = stage_`i - 1;
            }
        }
    }

    assign dout = stage_2;
}
```

生成：

```systemverilog
module pipeline
    #(
        parameter STAGES = 3,
        parameter WIDTH = 8
    )
(
    input logic clk,
    input logic rst_n,
    input logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout
);

    logic [WIDTH-1:0] stage_0;
    logic [WIDTH-1:0] stage_1;
    logic [WIDTH-1:0] stage_2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage_0 <= 0;
            stage_1 <= 0;
            stage_2 <= 0;
        end else begin
            stage_0 <= din;
            stage_1 <= stage_0;
            stage_2 <= stage_1;
        end
    end

    assign dout = stage_2;

endmodule
```

## 语法参考

### 模块声明

```slip
module name #(param W = 8, param DEPTH = 16) (clk, rst_n, data_in, data_out) {
    // 模块体
}
```

参数使用 `param` 关键字。端口仅列出名称——方向自动推断。

### 信号

```slip
logic [7:0] data;          // 显式宽度
logic flag;                // 1 位
signed [15:0] val;         // 有符号
data;                      // 裸声明（默认为 logic）
logic [7:0] mem [0:15];    // 数组
```

### 赋值

```slip
assign y = a & b;          // 带关键字
y = a + b;                 // 裸赋值
```

### 时序逻辑

```slip
seq (clk, neg: rst_n) {
    if (!rst_n) begin
        counter <= 0;
    end else begin
        counter <= counter + 1;
    end
}
```

`seq` 块中的阻塞赋值 `=` 会自动转换为非阻塞赋值 `<=`。

### 组合逻辑

```slip
comb {
    if (sel) { y = a; }
    else { y = b; }
}
```

### 元编程

```slip
// 编译时循环，带模板标识符
`for (`i = 0; `i < N; `i = `i + 1) {
    logic [7:0] data_`i;
    assign data_`i = `i;
}

// 条件编译
`if (ENABLE_FIFO) {
    fifo #(.DEPTH(16)) u_fifo { .clk, .din, .dout };
}
`else {
    assign dout = din;
}
```

### 模块实例化

```slip
// 同名简写：.clk 等价于 .clk(clk)
inner #(.W(16)) u1 { .clk, .data_in, .data_out(result) };

// 悬空端口（不连接）
inner u2 { .clk, .rst_n(_), .data };

// 正则端口映射
child u3 { .clk, "data_(.*)" => "prefix_\1" };
```

### 特殊常量

```slip
'0    // 零填充（所有位为 0）
'1    // 一填充（所有位为 1）
1'b0  // 带宽度前缀（端口连接中必须使用）
```

## 安装

```bash
# 克隆
git clone https://github.com/user/slip.git
cd slip

# 安装依赖（需要 uv）
uv sync

# 或使用 pip
pip install -e .
```

需要 Python >= 3.10。

## 使用方法

### 编译

```bash
slip build design.slip                    # 输出到 ./build
slip build -o output design.slip          # 输出到 ./output
slip build -ip ip_dir design.slip         # 包含外部 IP 目录
```

### 检查

```bash
slip check design.slip                    # 仅验证，不生成输出
slip check -ip ip_dir design.slip         # 含 IP 目录
```

## 架构

```
源文件 (.slip)
    │
    ▼
┌─────────┐    ┌─────────┐    ┌───────────────────┐    ┌──────────┐
│  词法分析│───▶│  语法分析│───▶│   语义分析         │───▶│  代码生成 │
└─────────┘    └─────────┘    └───────────────────┘    └──────────┘
                                   │
                                   ├── 元编程展开
                                   ├── 符号收集
                                   ├── 驱动分析
                                   ├── 赋值修正
                                   └── 实例解析
                                                │
                                                ▼
                                       SystemVerilog (.sv)
```

1. **词法分析** — 基于正则的词法分析器，带后处理合并
2. **语法分析** — 语句使用递归下降，表达式使用 Pratt 解析器
3. **语义分析** — 元编程展开、符号收集、驱动分析、赋值修正、IR 构建、实例解析
4. **代码生成** — IR 转换为 SystemVerilog，通过 pyslang 验证

## 运行测试

```bash
# 运行所有测试
uv run pytest tests/ -v

# 带覆盖率
uv run pytest tests/ --cov=slip --cov-report=term-missing
```

## 许可证

MIT
