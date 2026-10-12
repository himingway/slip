# Slip

**S**treamlined **L**anguage for **I**C **P**rototyping — 一个极简的 HDL DSL 编译器，将 `.slip` 源文件编译为可综合的 SystemVerilog。

> *Slip* — 顺滑流动。让硬件描述从意图到实现，一气呵成。

**[English](README.md)** | 中文 | **[用户手册 (PDF)](docs/tex/user-manual.pdf)**

> 开发过程中参考的 IEEE 标准文档（1364-2005、1800-2017）不再随仓库分发，请从 [IEEE Xplore](https://ieeexplore.ieee.org/) 获取。

## 概述

Slip 是一种简洁的硬件描述语言，本质上是 SystemVerilog 的语法糖。它为常见的硬件设计模式提供了精简的语法——信号声明、组合与时序逻辑、带有正则端口映射的模块实例化、编译时元编程——同时生成干净、可读的 SystemVerilog 输出。

Slip 的主实现是 C++20 编译器，直接链接 [slang](https://github.com/MikePopoloski/slang) 完成常量求值、IP 反射及完整设计校验。Python 仅保留为 [reference](reference/python/README.md)，不参与主程序运行。架构与兼容边界见 [开发说明](docs/development.md)。

## 特性

- **端口方向自动推断** — 无需 `input`/`output` 关键字，方向根据信号使用方式推导
- **隐式信号声明** — 被引用但未声明为端口或实例的名称自动成为 `logic` 信号，带 `// implicit, no width` 注释便于 review
- **Instance 端口位宽推断** — 连接到 instance 端口的信号自动继承目标端口位宽，生成 `// width from X.Y` 注释
- **时序逻辑块** — `seq (clk, neg: rst_n) { ... }` 生成 `always_ff`，自动将阻塞赋值转为非阻塞
- **组合逻辑块** — `comb { ... }` 生成 `always_comb`
- **初始化块** — `initial { ... }` 生成 `initial begin ... end`，用于测试平台和初始化
- **过程式 for 循环** — `seq`/`comb` 块内的 `for` 生成 SV `for` 语句，支持 `i++` 和 `i += expr` 步进
- **case 语句** — 支持 `case`/`casez`/`casex`，多模式、default 和 `?` 通配符
- **inside 运算符** — `x inside {1, 2, 3}` 集合成员测试
- **复合赋值** — `+=`、`-=`、`*=`、`/=`、`%=`、`&=`、`|=`、`^=`、`<<=`、`>>=`、`<<<=`、`>>>=` 在解析时脱糖
- **编译时元编程** — `` `for `` 循环和 `` `if `` 条件编译，采用 SystemVerilog 常量求值
- **模板标识符** — `` `for `` 循环变量可在标识符名称中展开（如 `data_`i` → `data_0`）
- **模块实例化** — 简洁语法，支持同名简写（`.clk`）、显式连接和正则端口映射
- **Include 指令** — `include "helpers.slip"` 引入其他 Slip 文件中的 `defun` 函数和模块，支持递归和循环检测
- **IP 集成** — 通过 slang 自动反射外部 SystemVerilog IP 的端口和参数，支持 VCS filelist（`-f`）和递归目录扫描
- **参数与局部参数** — 模块级 `param` 可覆盖，模块体内 `localparam` 不可覆盖
- **多驱动检测** — 信号被多个 `seq`/`comb` 块驱动时报错
- **组合逻辑环路检测** — `comb` 块内的反馈环路会被检测并报错
- **位宽不匹配警告** — 赋值和实例端口位宽不匹配时发出警告
- **模块拓扑排序** — 按依赖顺序解析接口；循环依赖报编译错误
- **常量校验** — 端口连接中禁止裸整数，必须使用宽度前缀（`1'b0`）或填充常量（`'0`、`'1`）
- **悬空端口标记** — `.rst_n(_)` 将端口标记为有意不连接

## 快速示例

```slip
module pipeline #(param STAGES = 3, param WIDTH = 8) (clk, rst_n, din, dout) {
    logic clk;
    logic rst_n;
    logic [WIDTH-1:0] din;
    logic [WIDTH-1:0] dout;
    logic [WIDTH-1:0] stage [0:STAGES-1];   // 非压缩数组表示各级流水线

    seq (clk, neg: rst_n) {
        if (!rst_n) {
            // 编译时循环展开，带模板标识符
            `for (`i = 0; `i < STAGES; `i = `i + 1) {
                stage[`i] = 0;
            }
        } else {
            stage[0] = din;
            `for (`i = 1; `i < STAGES; `i = `i + 1) {
                stage[`i] = stage[`i - 1];   // 模板变量出现在下标中
            }
        }
    }

    assign dout = stage[STAGES-1];
}
```

生成（`seq` 内的阻塞赋值自动转为非阻塞，因此每一级都采到时钟沿之前的值，构成真正的移位流水线）：

```systemverilog
module pipeline #(
    parameter STAGES = 3,
    parameter WIDTH = 8
) (
    input logic clk,
    input logic rst_n,
    input logic [WIDTH - 1:0] din,
    output logic [WIDTH - 1:0] dout
);

    if (STAGES !== (3)) begin : __slip_frozen_STAGES
        $error("STAGES controls Slip compile-time expansion and cannot be overridden");
    end

    logic [WIDTH - 1:0] stage [0:STAGES - 1];

    assign dout = stage[STAGES - 1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage[0] <= 0;
            stage[1] <= 0;
            stage[2] <= 0;
        end else begin
            stage[0] <= din;
            stage[1] <= stage[0];
            stage[2] <= stage[1];
        end
    end

endmodule
```

## 语法参考

### Include 指令

```slip
include "helpers.slip";       // 引入其他文件中的 defun 函数和模块
include "utils/common.slip";  // 相对路径从 include 所在文件解析

module top (clk, rst_n) {
    logic clk;
    logic rst_n;
    inner u1 { .clk, .rst_n, "data_(.*)" => "$prefix(\1)" };
}
```

Include 仅在顶层（模块外）使用。被引入文件的 `defun` 函数和模块定义合并到当前编译单元。支持递归 include，通过绝对路径去重检测循环引用。

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
`defun` 使用受限的 Python 风格表达式，由 C++ 解释器求值。支持：字符串拼接（`+`）、字符串方法（`.upper()`、`.lower()`、`.reverse()`、`.replace()`、`.strip()`、`.split()`、`.startswith()` 等）、算术运算（`+`、`-`、`*`、`/`、`%`）、方法链式调用、内置函数（`len()`、`int()`、`str()`）、索引切片（`s[0]`、`s[1:3]`、`s[3:]`、`s[:3]`、`s[-1]`）、三元表达式。

### 特殊常量

```slip
'0    // 零填充（所有位为 0）
'1    // 一填充（所有位为 1）
1'b0  // 带宽度前缀（端口连接中必须使用）
```

## 安装

### 原生 C++ 编译器

需要 C++20 编译器、CMake >= 3.24 和 PCRE2 开发库。CMake 优先使用安装好的 slang 10，否则下载固定版本及其依赖。构建 slang 时需要 Python；运行 Slip 不需要 Python 或 pyslang。

```bash
cmake --preset release
cmake --build --preset release --parallel 2
ctest --preset release
build/release/slip check tests/fixtures/simple.slip
```

原生版本增加 stdin 输入（`-`）、`build --stdout` 和 `--diagnostics=json`。每次编译独立保存状态，支持并发调用；循环、表达式和正则匹配设有资源限制。过程循环变量不会被导出为隐式输入端口。

离线构建、Sanitizer 检查、迁移测试及整数/字符串的兼容边界见 [docs/development.md](docs/development.md)。

安装命令行工具：

```sh
cmake --install build/release --prefix "$HOME/.local"
```

确保 `$HOME/.local/bin` 在 `PATH` 中，之后 `slip` 即为 C++ 主程序。

Python 对照实现的安装和测试方法见 [reference/python/README.md](reference/python/README.md)。

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
slip check design.slip                    # 运行完整编译校验，不写出文件
slip check --strict design.slip           # 要求显式声明，位宽不匹配时报错
slip check -ip ip_dir design.slip         # 含 IP 目录
slip check -f ip.f design.slip            # 含 filelist
```

### 编译正确性与严格模式

- 所有生成模块与外部 IP 一起交给 slang 展开、校验；反射与校验共用解析后的 IP、宏定义和 include 路径。错误端口名、参数名和未解析标识符会报错。
- 所有模块校验成功后才写出文件。编译错误不会覆盖旧产物或留下部分新产物。
- 接口信息按依赖顺序跨多层封装传播；参数化维度会结合实例参数覆盖和 localparam 依赖转换到父模块作用域。
- 电路表达式保留字面量位宽、符号、四态值与赋值上下文。循环展开只替换循环变量，不使用 Python 运算改写电路表达式。
- 直接或间接参与 Slip 元编程控制的参数，在生成模块中固定为默认值。Slip 内禁止覆盖；生成的 SV 也会在展开时拒绝不同的覆盖值。需要改变这些参数时，应修改源配置后重新生成。只参与普通 RTL 维度的参数仍可覆盖。
- 推荐在 CI 使用 `--strict`：要求显式声明信号和端口，并将赋值、端口位宽不匹配视为错误。默认模式仍支持带注释的隐式信号；显式单比特声明始终有效。

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
                                   ├── Include 解析
                                   ├── 元编程展开
                                   ├── 符号收集
                                   ├── 驱动分析
                                   ├── 赋值修正
                                   └── 实例解析（含位宽推断）
                                                │
                                                ▼
                                       SystemVerilog (.sv)
```

主实现位于 `src/` 和 `include/slip/`；C++ 测试及共享 HDL 用例位于 `tests/`；Python 对照实现独立放在 `reference/python/`。

1. **词法分析** — 识别 token、复合运算符、注释与模板标识符
2. **语法分析** — 语句使用递归下降，表达式使用 Pratt 解析器
3. **语义分析** — Include 解析、元编程展开、符号收集、驱动分析、组合逻辑环路检测、赋值修正、位宽不匹配检查、IR 构建、实例解析与端口位宽推断
4. **代码生成** — IR 转换为 SystemVerilog，通过 slang 验证，附带 review 注释（`// implicit`、`// no width`、`// width from X.Y`）

## 运行测试

```sh
ctest --preset release
cmake --preset sanitize
cmake --build --preset sanitize --parallel 2
ctest --preset sanitize
```

安装 Verilator 后，CTest 会加入与独立参考 RTL 比较的 128 周期仿真。Python 回归和迁移对照测试单独运行，见 [reference](reference/python/README.md)。

## 许可证

本项目基于 MIT 许可证发布。详见 [LICENSE](LICENSE) 文件。
