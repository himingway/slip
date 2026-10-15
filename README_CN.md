# Slip

**S**treamlined **L**anguage for **I**C **P**rototyping — 一个极简的 HDL DSL 编译器，将 `.slip` 源文件编译为可综合的 SystemVerilog。

> *Slip* — 顺滑流动。让硬件描述从意图到实现，一气呵成。

**[English](README.md)** | 中文 | **[用户手册 (PDF)](docs/tex/user-manual.pdf)**

> 开发过程中参考的 IEEE 标准文档（1364-2005、1800-2017）不再随仓库分发，请从 [IEEE Xplore](https://ieeexplore.ieee.org/) 获取。

[工程构建、配置组合、告警策略与调试](docs/practical-projects.md) · [VS Code 与 LSP](editors/vscode/README.md) · [Vim / Neovim](editors/vim/README_CN.md) · [SV 互操作示例](examples/interop/slip.conf)

## 概述

Slip 是一种简洁的硬件描述语言，本质上是 SystemVerilog 的语法糖。它为常见的硬件设计模式提供了精简的语法——信号声明、组合与时序逻辑、带有正则端口映射的模块实例化、编译时元编程——同时生成干净、可读的 SystemVerilog 输出。

Slip 的主实现是 C++20 编译器，直接链接 [slang](https://github.com/MikePopoloski/slang) 完成常量求值、IP 反射及完整设计校验。Python 实现保留在 [`python-reference` 分支](https://github.com/himingway/slip/tree/python-reference)。架构与兼容边界见 [开发说明](docs/development.md)。

## 特性

- **端口方向自动推断** — 无需 `input`/`output` 关键字，方向根据信号使用方式推导
- **隐式信号声明** — 自动创建的端口和内部信号标记 `implicit port` / `implicit logic`，同时注明推断方向、默认类型和位宽来源
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

## RTL 功能扩展

支持拼接赋值、`+:` / `-:` 取片、多维非压缩数组、下降沿时钟、枚举与 packed 结构体、
按实例参数特化、按需 IP 反射、带主从角色的总线分组、可综合函数及编译时/运行时断言。
完整语法、边界及组合示例见 [RTL 功能说明](docs/rtl-features.md) 和
[功能示例项目](examples/features/slip.conf)。

支持原生 SystemVerilog interface 的参数化实例、modport 端口、整组连接及字段访问，
并保留方向、位宽与驱动检查。见 [原生 interface 说明](docs/native-interfaces.md) 和
[参数化示例](examples/native-interface/slip.conf)。

### 生成声明的注释

生成的 SV 使用 `implicit port` / `implicit logic` 标记自动创建的端口和内部信号。
已列出名称、但方向由编译器推断的端口标记 `inferred direction: input/output/inout`；
省略基本类型的声明标记 `inferred type: logic`，并保留 `no width` 和
`width from module.port` 信息。注释放在对应声明前，非 ANSI 端口也在实际声明处标注。
`inspect` 同步显示来源，JSON 增加 `direction_inferred`、`type_inferred` 字段。
端口列表中的名称仍视为显式声明，严格检查规则保持原有含义。

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

### 发布安装包

[GitHub Releases](https://github.com/himingway/slip/releases) 提供 Linux x86_64
安装包，包含 `bin/slip`、可选的 Python `bin/slip-lsp`，以及 `share/slip`
下的编辑器源码、文档和示例。解压后将 `bin` 加入 PATH 即可。
编辑器也提供单独附件：VS Code 安装 `.vsix`；Vim/Neovim 将编辑器压缩包中的
`vim` 目录加入运行时路径，具体配置见包内 README。
LSP 和格式化需要 Python 3.10+。PDF 用户手册及 `SHA256SUMS.txt` 可独立下载。

## 使用方法

### 项目配置

在项目目录保存 `slip.conf`，即可使用 `slip build`、`slip check` 或 `slip inspect`：

```ini
entry = rtl/top.slip
out_dir = build/rtl
filelist = ip.f
ip_dir = "external ip"
strict = true
```

配置是一行一个 `key = value`，支持 `#` 注释。路径可以不加引号，也可以用双引号
或单引号；含 `#` 的路径必须加引号。双引号内支持 `\"` 和 `\\`，单引号内的
反斜杠保持原样。所有配置路径相对于 `slip.conf` 所在目录解析。

支持的键为 `entry`、`out_dir`、`filelist`、`ip_dir`、`strict`、`no_implicit` 和
`widths_as_errors`。`filelist` 和 `ip_dir` 可重复；其他键重复或未知键会报
`E_CONFIG`。布尔值为 `true` / `false`。未设置 `out_dir` 时输出到配置目录下的
`build`；未设置 `entry` 时需从命令行提供输入文件。

`strict = true` 同时启用隐式声明和位宽检查；独立的 `no_implicit`、
`widths_as_errors` 设置优先于 `strict`，不受配置键顺序影响。

```bash
slip build                                  # 读取当前目录的 slip.conf
slip check --project path/to/slip.conf       # 从任意目录使用项目配置
slip inspect --project slip.conf --format=json
slip build --project slip.conf other.slip -o output
slip check --project slip.conf --widths-as-warnings
slip check --project slip.conf --allow-implicit
```

省略输入文件时自动读取当前目录的 `slip.conf`，不搜索父目录。显式指定输入文件时，
只有传入 `--project` 才读取配置。命令行输入和 `-o` 覆盖配置值，命令行 `-ip` / `-f`
追加到配置列表，路径相对于当前工作目录。检查开关按命令行顺序生效：`--strict`
启用两项检查，`--no-strict` 关闭两项，`--allow-implicit` 和 `--widths-as-warnings`
分别关闭对应检查。

可直接使用 [示例项目](examples/project/slip.conf)：
`slip check --project examples/project/slip.conf`。

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
slip check --no-implicit design.slip      # 仅禁止隐式声明，保留位宽警告
slip check --widths-as-errors design.slip # 仅将位宽不匹配视为错误
slip check -ip ip_dir design.slip         # 含 IP 目录
slip check -f ip.f design.slip            # 含 filelist
```

### 查看推断和连接结果

```bash
slip inspect design.slip                 # 查看端口方向、位宽、信号和实例连接
slip inspect -f ip.f design.slip          # 包含外部 IP
slip inspect --format=json design.slip   # 结构化结果写到 stdout
```

`inspect` 执行与 `check` 相同的完整设计校验，不写出 SV 文件。结果按模块名排序，
包含隐式信号、位宽来源、固定的元编程参数，以及每个实例端口的最终连接。
连接来源区分显式连接、同名简写和正则规则；有意悬空的 `_` 与未连接端口分别显示。
JSON 包含信号的 `type` 和分组的 `bundles`；logic/bit 单比特信号的 `width` 为空字符串，
自定义类型和 int 的大小由 SV 类型决定。未连接端口的 `signal` 为空字符串，
有意悬空端口的 `signal` 为 `_`。诊断始终写到 stderr，可组合 `--diagnostics=json`。

### 诊断

默认模式下，隐式信号和隐式端口会产生 `W_IMPLICIT` 警告，显示首次使用位置、
最终推断位宽及可能的拼写建议。`--no-implicit` 将其视为错误；`--strict` 同时启用
`--no-implicit` 和 `--widths-as-errors` 的检查。端口列表中的名称视为显式声明。

生成 SV 的校验错误和位宽警告会映射回原始 `.slip` 语句或声明。文本诊断附带
源码行和指示符；元编程循环展开时还会显示变量绑定，例如 `i=2`。JSON 诊断的
`file`、`line`、`column` 使用原始位置，有展开上下文时增加 `expansion` 字段。
位置映射以生成代码行为单位，不保证定位到表达式内部的具体字符。

完整校验后还会报告以下警告，它们不会被 `--strict` 升级为错误：

- `W_UNDRIVEN`：内部信号被读取，却没有赋值或实例端口驱动。
- `W_LATCH`：`comb` 中赋值不完整，可能推断出锁存器；优先在块开头给出默认值。
- `W_REGEX_UNUSED`：正则连接规则未连接任何端口，包括被显式连接或前面的规则覆盖。
- `W_UNCONNECTED`：实例端口遗漏连接；有意悬空可写 `.port(_)`。

未驱动和锁存器检查由 slang 对展开后的设计进行数据流分析，识别完整 `case`、
部分位赋值、循环、初始化和实例驱动。仅报告 Slip 生成模块中的分析警告，外部
IP 仍参与驱动分析和编译校验。它们不能替代仿真；大规模分支和循环的分析有资源上限。

### 编译正确性与严格模式

- 所有生成模块与外部 IP 一起交给 slang 展开、校验；反射与校验共用解析后的 IP、宏定义和 include 路径。错误端口名、参数名和未解析标识符会报错。
- 所有模块校验成功后才写出文件。编译错误不会覆盖旧产物或留下部分新产物。
- 接口信息按依赖顺序跨多层封装传播；参数化维度会结合实例参数覆盖和 localparam 依赖转换到父模块作用域。
- 电路表达式保留字面量位宽、符号、四态值与赋值上下文。循环展开只替换循环变量，不使用 Python 运算改写电路表达式。
- 参与生成控制的参数可在 Slip 实例上覆盖，不同参数组合生成独立模块，相同组合复用。生成模块中的结构参数固定为该次生成值，并在下游 SV 展开时检查；父参数影响子模块生成结构时也传播该约束。普通 RTL 参数继续保留 SV 覆盖。
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

主实现位于 `src/` 和 `include/slip/`；C++ 测试及共享 HDL 用例位于 `tests/`。Python 实现保留在 [`python-reference` 分支](https://github.com/himingway/slip/tree/python-reference)。

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

安装 Verilator 后，CTest 会加入与独立参考 RTL 比较的 128 周期仿真。

## 许可证

本项目基于 MIT 许可证发布。详见 [LICENSE](LICENSE) 文件。
