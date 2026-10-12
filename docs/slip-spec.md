# Slip 语言规范

**全称**：Streamlined Language for IC Prototyping
**状态**：C++ 主实现
**面向读者**：Slip 语言用户与编译器开发者
**最后更新**：2026-10-12

---

## 1. 引言

Slip 是一个极简硬件描述语言 (DSL) 编译器。它定义了一组高度精简的直觉化语法糖，可将硬件设计意图自动编译为高质量、可综合的 SystemVerilog 代码，并利用 `slang` 引擎提供语义验证与 IP 集成。

### 1.1 设计目标

*   **极简源语言**：通过上下文自动推导端口方向、信号类型、实例化连线，只保留硬件本质描述。
*   **严谨代码生成**：从 IR 生成可读的 SystemVerilog 文本，再与外部 IP 一起通过 `slang::ast::Compilation` 校验。全部模块校验成功后才写出文件。
*   **可靠的元编程**：提供编译期 `` `for `` / `` `if `` 展开，循环变量可在体内参与任意常量表达式运算，展开时自动进行常量折叠。
*   **IP 自动集成**：利用 `slang` 反射外部模块的参数、`localparam` 和端口信息，支持正则批量端口映射、位宽自动推导、悬空标记和智能 tie 常数。
*   **清晰边界**：不涉及仿真脚本、综合脚本或 FPGA 项目文件生成。

### 1.2 技术选型

* 实现语言：C++20。
* 词法和语法分析：手写词法分析器、递归下降语句解析器、Pratt 表达式解析器。
* AST：`std::variant` 节点；表达式使用 `std::shared_ptr<const Expr>`。
* IR：具有值所有权的模块、信号、过程和实例容器。
* SV 集成：直接链接 slang 10，完成常量求值、IP 反射和完整设计校验。
* 正则映射：PCRE2；`defun` 由受限的 C++ 类型解释器执行。
* 构建和测试：CMake、CTest；硬件行为测试使用 Verilator。

Python 实现保留在 [`python-reference` 分支](https://github.com/himingway/slip/tree/python-reference)。构建说明和兼容边界见 [development.md](development.md)。

---

## 2. 系统架构

```text
.slip → 词法/语法分析 → AST → include 合并和元编程展开
      → 依赖排序、符号/驱动/接口解析 → IR → SV 生成
      → 与外部 IP 一起通过 slang 完整设计校验 → 写出文件
```

每次编译拥有独立的源码管理器、IP 语法树、常量缓存和函数定义。独立编译可并发执行。

### 2.1 模块划分

| 文件 | 职责 |
|------|------|
| `include/slip/ast.hpp` | 源码位置、错误、类型化 AST 和解析接口 |
| `include/slip/ir.hpp` | 解析后的接口、信号、过程和实例 |
| `include/slip/compiler.hpp` | 编译选项、结果、诊断和公共编译 API |
| `src/frontend.cpp` | 词法、Pratt 解析、表达式序列化 |
| `src/functions.cpp` | `defun` 和正则替换函数解释器 |
| `src/pattern.cpp` | 有匹配资源限制的 PCRE2 封装 |
| `src/slang_backend.cpp` | filelist、IP 反射、常量求值、设计校验 |
| `src/compiler.cpp` | 语义分析、依赖排序、接口推断和代码生成 |
| `src/main.cpp` | C++ CLI 和文本/JSON 诊断 |

---

## 3. 源语言规范 (Slip Grammar)

### 3.1 词法元素

*   **关键字**：`module`, `param`, `localparam`, `logic`, `signed`, `assign`, `seq`, `comb`, `initial`, `pos`, `neg`, `if`, `else`, `for`, `case`, `casez`, `casex`, `default`, `inside`, `include`, `` `for ``, `` `if ``, `` `else ``
*   **特殊标识**：`_`（悬空标记）
*   **字面量**：Verilog 风格整数常量（包括 `'0` 和 `'1`）、字符串（仅用于正则映射）
*   **运算符**：`=`, `<=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `<<<=`, `>>>=`, `+`, `-`, `*`, `/`, `%`, `**`, `==`, `!=`, `===`, `!==`, `<`, `>`, `<=`, `>=`, `&&`, `||`, `!`, `~`, `&`, `|`, `^`, `<<`, `>>`, `<<<`, `>>>`, `inside`, `?:`, `'`, `{}`, `[]`, `()`, `#`, `.`, `,`, `;`, `:`, `=>`, `@`
*   **标识符**：`[a-zA-Z_][a-zA-Z0-9_]*`
*   **模板标识符**：`` ident`var `` — 标识符名中嵌入反引号循环变量（如 `data_`i`、`a`i_`j`），由词法分析器后处理合并为单一 Token
*   **注释**：`//` (行), `/* */` (块)，视为空白
*   **空白**：空格、制表、换行丢弃

### 3.2 语法 (EBNF)

```ebnf
CompilationUnit ::= { TopLevelItem }

TopLevelItem ::= ModuleDecl | FuncDef | IncludeDirective

IncludeDirective ::= "include" STRING ";"

ModuleDecl ::= "module" IDENT
               [ "#(" ParameterList ")" ]
               [ "(" PortList ")" ]
               "{" { Statement } "}"

ParameterList ::= ParameterDecl { "," ParameterDecl }
ParameterDecl ::= "param" IDENT "=" Expr

PortList      ::= PortItem { "," PortItem }
PortItem      ::= IDENT [ "[" Expr [ ":" Expr ] "]" ]  (* 无方向声明，支持 [high:low] 或 [width] *)

Statement ::= SignalDecl
            | LocalparamDecl
            | AssignStmt
            | SeqBlock
            | CombBlock
            | InitialBlock
            | IfStmt
            | ForStmt
            | CaseStmt
            | GenForStmt
            | GenIfStmt
            | InstanceStmt
            | BlockStmt

SignalDecl ::= ["logic"] ["signed"] [ "[" Expr "]" ]
               IDENT [ "[" Expr ":" Expr "]" ] ";"

LocalparamDecl ::= "localparam" IDENT "=" Expr ";"

AssignStmt ::= ["assign"] Lvalue "=" Expr ";"
            | "assign" Lvalue "<=" Expr ";"       (* 连续赋值，"<=" 为非阻塞 *)
            | ["assign"] Lvalue ("+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=" | "<<<=" | ">>>=") Expr ";"
                                                                         (* 复合赋值，在解析时脱糖 *)

SeqBlock     ::= "seq" "(" IDENT [ "," ("pos" | "neg") ":" IDENT ] ")" BlockStmt
CombBlock    ::= "comb" BlockStmt
InitialBlock ::= "initial" BlockStmt

IfStmt ::= "if" "(" Expr ")" BlockStmt [ "else" BlockStmt ]

ForStmt ::= "for" "(" IDENT "=" Expr ";" Expr ";" ForStep ")" BlockStmt
ForStep ::= IDENT "=" Expr
          | IDENT ("+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=" | "<<<=" | ">>>=") Expr
          | IDENT "++"

CaseStmt ::= ("case" | "casez" | "casex") "(" Expr ")"
             "{" { CaseItem } "}"
CaseItem ::= PatternList ":" Statement
           | "default" ":" Statement
PatternList ::= Expr { "," Expr }

GenForStmt ::= "`for" "(" TICK_IDENT "=" Expr ";" Expr ";"
                           TICK_IDENT "=" Expr ")" BlockStmt

GenIfStmt ::= "`if" "(" Expr ")" BlockStmt [ "`else" BlockStmt ]

InstanceStmt ::= IDENT [ "#(" NamedParam { "," NamedParam } ")" ]
                 IDENT "{" { Connection } "}" [";"]
NamedParam ::= "." IDENT "(" Expr ")"
Connection ::= "." IDENT [ "(" Expr ")" ]          (* Expr 可为 '0, '1, _ 或带位宽常数 *)
             | STRING "=>" STRING                  (* 正则映射 *)

BlockStmt ::= "{" { Statement } "}"

Lvalue ::= IDENT { "[" Expr "]" | "[" Expr ":" Expr "]" }

Expr ::= (* 表达式：由 Pratt 解析器实现，涵盖所有运算符。
           特殊构造：
           - 复制：{n{expr}}
           - 宽度转换：N'(expr)，如 8'(x)
           - 函数调用：func(args)
           - 集合成员：x inside {v1, v2, ...}
           - _ 仅在连接中使用，'0/'1 为特殊常量 *)
```

### 3.3 语义说明

*   **端口推导**：若 `PortList` 缺失（括号也省略），模块内所有被使用且非内部声明的标识符均变为端口，方向由驱动分析决定；显式端口列表则只有列表中信号是端口，未声明使用报错。
*   **信号推导**：省略 `logic` 的信号统一为 `logic` 类型；未显式声明且未出现在端口列表的标识符，自动生成为隐式 `logic` 信号（1-bit）。生成的 SV 中带 `// implicit, no width` 注释标记，方便 review 时补全位宽。Instance 端口连接可从目标端口自动继承位宽（标注 `// width from X.Y`）。
*   **`seq` 块**：`seq (clk, neg: rst_n) { … }` 生成 `always_ff @(posedge clk or negedge rst_n)`，块内顶层 `if(!rst_n)` 保留。**语义分析会将块内所有阻塞赋值 `=` 强制转换为 `<=`**（非 `assign` 语句），确保时序逻辑正确。
*   **`comb` 块**：`comb { … }` 生成 `always_comb begin … end`，块内保留阻塞赋值 `=`，**不进行**非阻塞转换。
*   **`localparam`**：模块内部常量，不能被实例化时的 `#(...)` 覆盖；可用于信号位宽、`` `if `` 条件等编译期表达式。生成 SystemVerilog 时直接输出 `localparam`。
*   **端口连接常数**：仅接受带位宽常数（如 `1'b0`、`8'hFF`）或全位宽常量 `'0`、`'1`。无位宽常量（如 `0`）将被拒绝。`'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定，Slip 编译器不对其进行位宽推导，直接透传给后端工具处理。
*   **悬空标记**：`_` 在端口连接中表示故意悬空，可用于输入或输出端口。
*   **元编程**：
    - `` `for `` 的起始、终止、步长表达式及 `` `if `` 条件必须可在编译期求值为整数常量。支持整数字面量、`param`/`localparam` 引用、以及全部算术/位/关系/逻辑运算符。
    - `` `for `` 循环变量（反引号标识符，如 `` `i ``）在循环体内被当前迭代值替换，并自动进行常量折叠。详见第 7.2.1 节。
*   **模板标识符**：标识符名中可嵌入反引号循环变量（如 `data_`i`），展开时变量替换为当前值（如 `data_3`）。
*   **Include 指令**：`include "file.slip"` 在顶层（模块外）引入另一个 `.slip` 文件，将其中的 `defun` 函数定义和模块定义合并到当前编译单元。支持递归 include，通过绝对路径做循环检测。Include 仅用于函数库复用，不支持在模块体内部使用。
*   **实例化与正则端口映射**：详见第 7.2.6 节。

---

## 4. 词法分析器

*   识别所有关键字、字面量 `'0` 和 `'1`、字符串。
*   `_` 作为特殊标识符，标记悬空。
*   **后处理合并**：
    - 复合 Token：`` ` `` + 关键字 → `` `for ``、`` `if ``、`` `else ``；`` ` `` + 标识符 → `TICK_IDENT`
    - 复合运算符：`===`、`!==`、`<<<`、`>>>`、`**` 等按最长匹配优先合并
    - **模板标识符合并**：将 `ident` + `` ` `` + `var` 合并为单一 `IDENT` Token（如 `data_`i`），支持多变量（如 `a`i_`j`）
* Token 携带类型、值和源码位置；通过公共 `slip::parse()` 接口取得 AST。

---

## 5. 语法分析器

### 5.1 递归下降解析器

*   每个非终结符一个方法，使用 `peek()` / `consume(type)`。
* 内部解析器持有 Token 流；公共 `slip::parse()` 返回包含模块、函数和 include 指令的 `Unit`。
*   上下文处理：
    *   模块头直接遇 `{` 则端口列表为空。
    *   `InstanceStmt` 连接列表中识别 `STRING "=>" STRING` 为正则映射。
    *   连接表达式中 `_` 解析为悬空标记；`'0`/`'1` 解析为特殊常量。

### 5.2 Pratt 表达式解析器

优先级严格遵循 **SystemVerilog IEEE 1800-2017**：

| 优先级 | 运算符 | 结合性 |
|--------|--------|--------|
| 1 (最低) | `?:` (三元) | 右 |
| 2 | `\|\|` | 左 |
| 3 | `&&` | 左 |
| 4 | `\|` (按位或) | 左 |
| 5 | `^` (按位异或) | 左 |
| 6 | `&` (按位与) | 左 |
| 7 | `==`, `!=`, `===`, `!==` (相等) | 左 |
| 8 | `<`, `>`, `<=`, `>=`, `inside` | 左 |
| 9 | `<<`, `>>`, `<<<`, `>>>` (移位) | 左 |
| 10 | `+`, `-` (二元加减) | 左 |
| 11 | `*`, `/`, `%` (乘除) | 左 |
| 12 | `**` (幂) | 左 |
| 13 | 前缀 `+`, `-`, `!`, `~`, `&`, `\|`, `^`；类型转换 | 右 (前缀) |
| 14 (最高) | `[]`, `[ : ]`, `N'(expr)`, `f()` | 左 (后缀) |

*   `<=` 在表达式上下文中为关系运算符；非阻塞赋值由语法层面区分。
*   `{n{expr}}` 复制由 Pratt 解析器的前缀 `{` 处理，检测后跟 `expr{expr}` 模式。
*   原子项包括数字常量、`'0`、`'1`、括号、标识符、`_`（限制在连接中）。

---

## 6. AST 设计

`Expr` 包含 `Location` 和 `std::variant` 表达式节点。节点类型包括
`Identifier`、`Literal`、`Unary`、`Binary`、`Ternary`、`Select`、`Concat`、
`Repeat`、`Call`、`Method`、`Paren` 和 `Cast`。子表达式通过不可变的 `ExprPtr`
共享。表达式构造时检查深度，默认上限为 256。

`Statement` 使用 `std::variant` 表示 `SignalDecl`、`LocalParam`、`Assignment`、
`Process`、`If`、`For`、`Case`、`Instance` 和 `Group`。语句体以值容器保存。
`Unit` 保存模块、函数和 include 指令；所有节点保留源码位置用于诊断。
完整定义以 `include/slip/ast.hpp` 为准。

---

## 7. 语义分析与 IR

### 7.1 IR 数据结构

`IRModule` 保存模块名、位置、参数、局部参数、端口、内部信号、连续赋值、
过程、实例及固定的元编程参数。

* `IRSignal`：名称、位宽、数组维度、有符号标记、方向、声明来源和推断来源。
* `IRInstance`：目标模块、实例名、源码位置、参数和端口连接。
* 过程和赋值保留类型化表达式；硬件表达式在输出前保留 SV 位宽和四态语义。

定义见 `include/slip/ir.hpp`。

### 7.2 语义分析流程

#### 7.2.1 元编程展开（常量折叠）

**语法**：`` `for `` / `` `if `` / `` `else `` 关键字用于编译期展开。循环变量使用反引号前缀（`` `i ``）。

**条件求值**：`` `for `` 的起始、终止、步长表达式及 `` `if `` 条件必须可在编译期求值为整数常量。支持的操作包括：

*   整数字面量、`param` / `localparam` 标识符的直接引用
*   算术运算：`+`, `-`, `*`, `/`, `%`, `**`
*   关系/比较：`<`, `>`, `<=`, `>=`, `==`, `!=`, `===`, `!==`
*   逻辑运算：`&&`, `||`
*   位运算：`&`, `|`, `^`, `~`, `<<`, `>>`, `<<<`, `>>>`
*   括号表达式

**循环变量替换与常量折叠**：

*   循环变量（如 `` `i ``）在循环体内被当前迭代值替换为整数字面量。
*   元编程控制表达式由 slang 按 SystemVerilog 常量语义求值，保留参数默认表达式的位宽和声明顺序。
*   位宽、索引中的纯十进制常量运算可以折叠；含参数的表达式保留。不会进行 `x * 0 → 0` 等改变四态语义的代数化简。
*   电路赋值、条件、端口连接中的表达式只替换循环变量，保留原来的类型、位宽和赋值上下文，由 SystemVerilog 工具计算。
*   参与元编程控制的参数及其参数依赖固定为生成时默认值，禁止在实例化时覆盖。生成的 SV 带展开期 `$error` 检查，防止下游覆盖不同的值。普通 RTL 参数仍可覆盖。

**模板标识符**：标识符中可包含反引号循环变量（如 `stage_`i`、`a`i_`j`）。词法分析器在合并阶段将其识别为单一 Token，展开时替换变量部分（`stage_`i → stage_0, stage_1, …）。

**循环变量不可赋值**：`` `i `` 是带 `meta` 标记的 `Identifier`，不能在循环体内用作赋值目标。循环变量的值由展开引擎在每次迭代中确定。

**示例**：

```slip
module reverse #(param W=8) (clk, in, out) {
    logic clk;
    logic [W-1:0] in;
    logic [W-1:0] out;

    `for (`i = 0; `i < W; `i = `i + 1) {
        assign out[W - 1 - `i] = in[`i];
    }
}
```

展开后（W=8）：
*   `i=0`：`out[W - 1 - 0] = in[0]`
*   `i=1`：`out[W - 1 - 1] = in[1]`
*   `i=7`：`out[W - 1 - 7] = in[7]`

含参数的索引表达式由下游工具求值；纯十进制循环索引（如 `` `i - 1 ``）可直接折叠。

#### 7.2.2 符号收集与隐式声明

*   收集显式声明（`SignalDecl`、`LocalParamDecl`）；确定端口候选；未声明且使用的标识符生成隐式 `logic`，位宽尽量从上下文推断。

#### 7.2.3 驱动分析

*   先标记所有内部驱动的信号；候选端口仅当无内部驱动时判定方向；内部信号可自由读写。多驱动检测：同一信号被多个 `seq`/`comb` 块驱动时报错。
*   组合逻辑环路检测：`comb` 块内通过 DFS 检测信号依赖环路，发现循环时报错。

#### 7.2.4 赋值纠正

*   `seq` 块内阻塞 `=` 转为 `<=`。
*   `comb` 块保留阻塞赋值。
*   `initial` 块保留阻塞赋值。

#### 7.2.4a 位宽不匹配检查

*   赋值语句中，左侧信号与右侧值的位宽不匹配时发出警告。
*   实例化端口连接中，端口期望位宽与连接信号位宽不匹配时发出警告。
*   仅当两侧均为具体整数位宽时才报告——参数化位宽（使用默认值可求值时）会参与检查，无法求值时跳过。
*   整数字面量的位宽：有宽度前缀的使用声明宽度（如 `8'hFF` → 8 位），无前缀的默认 32 位。

#### 7.2.5 组合逻辑块处理

* `comb` 解析为组合类型的 `Process`，输出为 `always_comb`。
*   若检测到锁存器模式，使用 `always_latch`（无敏感列表）。

#### 7.2.6 实例化与正则端口映射

**常数与悬空约束**

*   显式连接表达式若为常数，必须是带位宽格式（如 `3'b101`）或全位宽常量 `'0`/`'1`。无位宽整数（如 `0`）报错。
*   `'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定。Slip 编译器不对此类常量进行位宽推导，直接将它们透传到生成的 SystemVerilog 代码中，由下游工具根据目标端口的宽度自动扩展。
*   `_` 作为悬空标记，可用于任何方向端口。

**连接展开与位宽推导**

*   **输入**：目标模块信息（通过同设计 IR 或 `slang` 反射），包括端口列表（方向、宽度表达式）、参数（含可覆盖与 `localparam`）及实例化覆盖值。
* **参数上下文**：位宽中的子模块参数、默认值和局部参数被转换到调用方作用域；硬件表达式保持符号形式，由 slang 在完整设计中校验。
*   **映射优先级**：
    1. 显式连接（最高优先级）
    2. 同名连接
    3. 正则映射（按书写顺序，第一个匹配的规则生效）
*   **正则映射信号生成**：
    - 若生成的信号名已存在 → 直接使用，并检查位宽兼容。
    - 若不存在 → 创建隐式 `logic` 信号，位宽从目标端口宽度推导（使用求值器）。求值失败则报错。
*   **正则函数**：替换字符串中可使用 `$func(...)` 语法对捕获组进行变换：
    - `$upper(\1)` / `$lower(\1)` — 大小写转换
    - `$reverse(\1)` — 字符串反转
    - `$add(\1, 1)` / `$sub(\1, 1)` — 算术运算
    - `$bit_reverse(\1)` / `$bit_select(\1, high, low)` — 位操作
    - 支持多个函数调用和前后缀文本：`"pre_$upper(\1)_post"`
*   **原生自定义函数（defun）**：在 Slip 中直接定义函数：
    ```slip
    defun prefix(s):
        return "bus_" + s

    defun to_upper(s):
        return s.upper()

    defun inc(n):
        return n + 1
    ```
    函数体支持受限的 Python 风格表达式，由 C++ 解释器求值，包括：字符串拼接（`+`）、字符串方法（`.upper()`、`.lower()`、`.reverse()`、`.replace()`、`.strip()`、`.split()`、`.startswith()` 等）、算术运算（`+`、`-`、`*`、`/`、`%`）、方法链式调用、内置函数（`len()`、`int()`、`str()` 等）、索引切片（`s[0]`、`s[1:3]`、`s[3:]`、`s[:3]`、`s[-1]`）、三元表达式。函数可在顶层任意位置定义（模块前或后），所有 `defun` 在实例解析前注册。
*   **连接完成检查**：
    - 输入/双向端口未连接且非悬空 → 报错。
    - 输出端口未连接 → 警告（悬空允许）。
    - 外部 IP 也参与完整设计校验。
*   **`localparam` 覆盖检查**：若实例化 `#(...)` 中包含 `localparam`，报错。

---

## 8. 代码生成

* 从 IR 直接生成 SV 文本：
    *   `seq` → `always_ff @(...)`，赋值 `<=`
    *   `comb` → `always_comb`，保留 `=`
    *   `initial` → `initial begin ... end`，保留 `=`
    *   `case`/`casez`/`casex` → `case`/`casez`/`casex ... endcase`
    * 实例化 → 根据 `IRInstance::connections` 生成 `.port(signal)`，若为悬空则省略该连接。
* 接口解析按依赖拓扑排序；输出模块按名称保持确定顺序。循环实例化依赖报 `E_MODULE_CYCLE`（硬件中非法）。
*   `'0` 和 `'1` 直接输出为 Verilog 全位宽常量。
* 生成的 SystemVerilog 与全部 IP 一起通过 slang 语法及语义校验。
*   **生成代码注释标注**：为便于 review，生成的 SV 附带以下注释：
    - `// implicit` — 该信号/端口为编译器自动生成（非用户显式声明）
    - `// no width` — 该信号/端口未指定位宽，默认为 1-bit
    - `// width from X.Y` — 位宽从 instance 目标端口推断而来

---

## 9. Slang 集成层

### 9.1 IP 反射

内部 `Backend` 保留 IP 的源码管理器和语法树，从统一的 slang 编译上下文中
提取模块参数、`localparam`、端口方向、位宽和数组维度。非顶层模块也可反射。
外部 SV 接口端口和类型参数会明确报错。

### 9.2 Filelist 解析

通过 `slip::Options::filelists` 或 CLI `-f` 指定 VCS 格式 filelist，
收集源文件、include 路径和宏定义。

支持的格式：
- `+incdir+路径` — include 搜索目录，多个路径用 `+` 分隔
- `+define+宏名=值` 或 `+define+宏名` — 宏定义
- `-f 子文件.f` — 递归解析子 filelist（支持循环引用检测）
- `//` 注释和空行被忽略
- 文件路径相对于 filelist 所在目录解析，绝对路径保持不变
- 重复文件自动去重

### 9.3 两遍 IP 扫描

内部 `Backend` 根据 `Options::filelists` 和 `Options::ip_dirs` 构建 IP 模块索引：

**Pass 1 — 收集**：
- 解析所有 filelist 文件，收集源文件、incdir、define
- 递归扫描 IP 目录（`*.sv`、`*.v`），合并去重

**Pass 2 — 反射**：
- 使用 `slang::syntax::SyntaxTree::fromFiles()` 一次性解析所有 IP 文件，共享预处理器上下文
- define 跨文件自动传播，解决 define 顺序问题
- 从统一 `Compilation` 中提取所有模块信息，构建本次编译的接口索引

---

## 10. 命令行接口

```
slip build [-o <out_dir>] [-ip <ip_dirs>] [-f <filelists>] <file.slip>
slip check [-ip <ip_dirs>] [-f <filelists>] <file.slip>
```

参数：
- `-o <out_dir>` — 输出目录（默认 `./build`）
- `-ip <ip_dir>` — IP 源目录，可多次指定，递归扫描 `*.sv`/`*.v`
- `-f <file.f>` — VCS 格式 filelist 文件，可多次指定
- `--strict` — 显式声明信号，位宽不匹配视为错误
- `--stdout` — `build` 的生成结果写到标准输出
- `--diagnostics=json` — 逐行 JSON 诊断
- 输入文件 `-` — 从标准输入读取

文件加载优先级：
1. `-f filelist.f`（最高优先级，按文件内顺序）
2. `-ip dir`（递归扫描，两遍处理）
3. 本地 `.slip` 模块

---

## 11. 错误处理

公共 API 抛出 `slip::Error`，包含源码位置、稳定的错误代码和原始消息。
例如 `E_PARSE`、`E_CONSTANT`、`E_CONNECTION`、`E_MULTIPLE_DRIVERS`、`E_SV`。
警告保存在 `slip::Result::warnings`；CLI 统一输出到 stderr。

退出码：成功为 0，编译失败为 1，CLI 参数错误为 2。
`--diagnostics=json` 输出包含 `severity`、`code`、`file`、`line`、`column`
和 `message` 字段的逐行 JSON。

默认资源限制为每模块 10,000 次元编程循环迭代、100,000 条展开语句、
128 层 include、每源码 1,000,000 个 token。循环值重复、整数溢出或达到
资源上限会报错。元编程控制结果和 `defun` 整数使用有符号 64 位整数；
硬件字面量仍保留完整 SV 位宽。`defun` 字符串按字节处理。

---

## 12. 测试策略

重点测试：

*   词法：Token 合并、模板标识符、复合运算符、整数字面量校验（含 `?` 通配符）
*   语法：各语句类型、表达式优先级、边界情况、case 语句、for 循环步进变体
*   元编程：`` `for ``/`` `if `` 展开、循环变量运算、常量折叠、嵌套展开、模板标识符
*   `seq`/`comb`/`initial` 块及赋值转换
*   `case`/`casez`/`casex` 语句（多模式、default、通配符）
*   `inside` 运算符
*   复合赋值运算符脱糖
*   `'0`/`'1` 与宽度限制
*   悬空 `_` 行为
*   正则映射的隐式信号位宽推导（含参数化）
*   `localparam` 不可覆盖
*   多驱动检测
*   组合逻辑环路检测
*   位宽不匹配警告（赋值和实例端口）
*   实例化与 IP 反射
*   模块拓扑排序
*   代码生成正确性（slang 完整设计验证）

## 编译校验与严格模式

`slip build` 与 `slip check` 使用相同的完整设计校验。IP 预处理或解析错误、未知端口/参数、重复参数覆盖、递归模块依赖、过程块内不支持的语句均为编译错误。实例输出也参与多驱动检查；组合环路分析包括 if/case 的控制依赖与重叠位选。

`--strict` 要求显式信号/端口声明，并将赋值及端口位宽不匹配提升为错误。默认模式保留隐式信号功能。校验失败时不写出任何新文件。

默认 `ctest --preset release` 运行 C++ API、共享用例和 CLI 测试；安装 Verilator 后还运行独立参考 RTL 仿真。
