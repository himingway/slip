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
- **初始化块** — `initial { ... }` 生成 `initial begin ... end`，用于测试平台和初始化
- **过程式 for 循环** — `seq`/`comb` 块内的 `for` 生成 SV `for` 语句，支持 `i++` 和 `i += expr` 步进
- **case 语句** — 支持 `case`/`casez`/`casex`，多模式、default 和 `?` 通配符
- **inside 运算符** — `x inside {1, 2, 3}` 集合成员测试
- **复合赋值** — `+=`、`-=`、`*=`、`/=`、`%=`、`&=`、`|=`、`^=`、`<<=`、`>>=`、`<<<=`、`>>>=` 在解析时脱糖
- **编译时元编程** — `` `for `` 循环和 `` `if `` 条件编译，支持常量折叠
- **模板标识符** — `` `for `` 循环变量可在标识符名称中展开（如 `data_`i` → `data_0`）
- **模块实例化** — 简洁语法，支持同名简写（`.clk`）、显式连接和正则端口映射
- **IP 集成** — 通过 pyslang 自动反射外部 SystemVerilog IP 的端口和参数，支持 VCS filelist（`-f`）和递归目录扫描
- **参数与局部参数** — 模块级 `param` 可覆盖，模块体内 `localparam` 不可覆盖
- **多驱动检测** — 信号被多个 `seq`/`comb` 块驱动时报错
- **组合逻辑环路检测** — `comb` 块内的反馈环路会被检测并报错
- **位宽不匹配警告** — 赋值和实例端口位宽不匹配时发出警告
- **模块拓扑排序** — 按依赖顺序输出模块（定义在实例化之前）
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

### case 语句

```slip
case (sel) {
    2'b00: y = a;
    2'b01: y = b;
    2'b10, 2'b11: y = c;
    default: y = 0;
}

// casez 带 ? 通配符
casez (opcode) {
    4'b1???: y = a;
    4'b01??: y = b;
    default: y = 0;
}
```

### inside 运算符

```slip
if (state inside {IDLE, RUN, DONE}) {
    // ...
}
```

### 初始化块

```slip
initial {
    clk = 0;
    forever #5 clk = ~clk;
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

// 多个正则规则：第一个匹配的规则生效
child u4 { .clk, "data_(.*)" => "bus_\1", "out_(.*)" => "result_\1" };

// 正则函数：对捕获组进行变换
child u5 { .clk, "data_(.*)" => "bus_$upper(\1)" };     // 转大写
child u6 { .clk, "ch_(.*)" => "port_$add(\1, 1)" };     // 算术运算
child u7 { .clk, "a_(.*)" => "pre_$upper(\1)_post" };   // 前缀 + 后缀
```

**正则端口映射优先级：**
1. 显式连接（最高优先级）
2. 同名简写
3. 正则表达式（按书写顺序，第一个匹配的规则生效）

**内置正则函数：**
- 字符串：`$upper`、`$lower`、`$reverse`、`$substr`、`$replace`、`$concat`
- 算术：`$add`、`$sub`、`$mul`、`$div`、`$mod`
- 位操作：`$bit_reverse`、`$bit_select`

**自定义函数（Python API）：**
```python
from slip.semantic.regex_funcs import register

def my_func(s: str) -> str:
    return f"prefix_{s}"

register("my_func", my_func)
```
然后在 Slip 中使用 `$my_func(\1)`。自定义函数可以覆盖内置函数。

**原生自定义函数（defun）：**
```slip
defun prefix(s):
    return "bus_" + s

defun to_upper(s):
    return s.upper()

defun inc(n):
    return n + 1

child u1 {
    .clk,
    "data_(.*)" => "$prefix(\1)",
    "name_(.*)" => "$to_upper(\1)",
    "ch_(.*)" => "$inc(\1)"
};
```
支持完整 Python 表达式，包括：字符串拼接（`+`）、字符串方法（`.upper()`、`.lower()`、`.reverse()`、`.replace()`、`.strip()`、`.split()`、`.startswith()` 等）、算术运算（`+`、`-`、`*`、`/`、`%`）、方法链式调用、内置函数（`len()`、`int()`、`str()`）、索引切片（`s[0]`、`s[1:3]`、`s[3:]`、`s[:3]`、`s[-1]`）、三元表达式。

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
slip build -ip ip_dir design.slip         # 包含外部 IP 目录（递归扫描）
slip build -f ip.f design.slip            # 使用 VCS 格式 filelist
slip build -f ip.f -ip ip_dir design.slip # filelist + 目录（组合使用）
```

### 检查

```bash
slip check design.slip                    # 仅验证，不生成输出
slip check -ip ip_dir design.slip         # 含 IP 目录
slip check -f ip.f design.slip            # 含 filelist
```

### Filelist 格式

Slip 支持 VCS 格式的 filelist（`.f`）文件：

```
// 注释
+incdir+./include
+define+DATA_WIDTH=32
./rtl/fifo.sv
./rtl/arbiter.sv
-f sub_filelist.f
```

- `+incdir+路径` — include 搜索目录
- `+define+宏名=值` — 宏定义
- `-f 子文件.f` — 嵌套 filelist 引用
- 文件路径相对于 filelist 所在目录解析
- 重复文件自动去重

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
3. **语义分析** — 元编程展开、符号收集、驱动分析、组合逻辑环路检测、赋值修正、位宽不匹配检查、IR 构建、实例解析
4. **代码生成** — IR 转换为 SystemVerilog，通过 pyslang 验证

## 运行测试

```bash
# 运行所有测试
uv run pytest tests/ -v

# 带覆盖率
uv run pytest tests/ --cov=slip --cov-report=term-missing
```

## 许可证

本项目基于 MIT 许可证发布。详见 [LICENSE](LICENSE) 文件。
