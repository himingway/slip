# Slip 语言规范

**全称**：Streamlined Integration Platform
**状态**：正式发布
**面向读者**：Slip 语言用户与编译器开发者
**最后更新**：2026-05-11

---

## 1. 引言

Slip 是一个极简硬件描述语言 (DSL) 编译器。它定义了一组高度精简的直觉化语法糖，可将硬件设计意图自动编译为高质量、可综合的 SystemVerilog 代码，并利用 `slang` 引擎提供语义验证与 IP 集成。

### 1.1 设计目标

*   **极简源语言**：通过上下文自动推导端口方向、信号类型、实例化连线，只保留硬件本质描述。
*   **严谨代码生成**：采用"片段解析 + SyntaxRewriter"模式，通过 `pyslang` 构建语法树，确保输出代码语法与语义正确。
*   **可靠的元编程**：提供编译期 `` `for `` / `` `if `` 展开，循环变量可在体内参与任意常量表达式运算，展开时自动进行常量折叠。
*   **IP 自动集成**：利用 `slang` 反射外部模块的参数、`localparam` 和端口信息，支持正则批量端口映射、位宽自动推导、悬空标记和智能 tie 常数。
*   **清晰边界**：不涉及仿真脚本、综合脚本或 FPGA 项目文件生成。

### 1.2 技术选型

*   实现语言：Python 3.10+
*   词法分析：基于正则表达式的 Token 生成器，含后处理合并（复合运算符、模板标识符）
*   语法分析：手写递归下降解析器 + Pratt 表达式解析器
*   中间表示：自定义 Python 数据类
*   代码生成：`pyslang` 片段解析 + `SyntaxRewriter` 组合语法树
*   外部 Verilog 处理：`pyslang` 编译、反射、诊断
*   CLI 框架：`click`

---

## 2. 系统架构

编译器采用经典三阶段流水线。

```
源文件 (.slip)
      │
      ▼
[词法分析器] → Token 流（含模板标识符合并）
      │
      ▼
[递归下降语法分析器 + Pratt 表达式解析器] → 自定义 AST (带源码位置)
      │
      ▼
[语义分析 & IR 构建]
  ├─ 元编程展开（循环变量运算与常量折叠）
  ├─ 隐式端口/信号推导
  ├─ 驱动分析（剔除内部自驱动）
  ├─ 多驱动检测
  ├─ 组合逻辑环路检测
  ├─ 时序块赋值强制纠正（seq 块）
  ├─ 组合逻辑块识别（comb 块保持阻塞赋值）
  ├─ 位宽不匹配检查（赋值和实例端口）
  └─ 实例化连接展开（正则映射、悬空、tie、位宽推导、必连端口检查）
      │
      ▼
设计 IR（与语法解耦）
      │
      ├─→ [代码生成器] 片段解析 → pyslang SyntaxTree
      └─→ [slang 反射] 获取外部模块端口、参数、localparam
      │
      ▼
SystemVerilog 源码
      │
      ▼  (可选)
[slang 二次诊断]
```

### 2.1 模块划分

| 模块 | 职责 |
|------|------|
| `lexer` | 将字符流转化为 Token 列表，含复合 Token 合并与模板标识符合并，记录行列号 |
| `parser` | 语法分析，输出自定义 AST |
| `ast` | AST 节点定义 |
| `ir` | 中间表示数据结构 |
| `semantic` | 语义分析：元编程展开、信号/端口推导、驱动分析、赋值纠正、实例化处理 |
| `codegen` | 遍历 IR，使用 pyslang 片段生成语法树并序列化为文本 |
| `slang_integration` | 封装 pyslang 进行 IP 反射、诊断 |
| `cli` | 命令行接口 |
| `errors` | 错误/警告定义与格式化 |

---

## 3. 源语言规范 (Slip Grammar)

### 3.1 词法元素

*   **关键字**：`module`, `param`, `localparam`, `logic`, `signed`, `assign`, `seq`, `comb`, `initial`, `pos`, `neg`, `if`, `else`, `for`, `case`, `casez`, `casex`, `default`, `inside`, `` `for ``, `` `if ``, `` `else ``
*   **特殊标识**：`_`（悬空标记）
*   **字面量**：Verilog 风格整数常量（包括 `'0` 和 `'1`）、字符串（仅用于正则映射）
*   **运算符**：`=`, `<=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `<<<=`, `>>>=`, `+`, `-`, `*`, `/`, `%`, `**`, `==`, `!=`, `===`, `!==`, `<`, `>`, `<=`, `>=`, `&&`, `||`, `!`, `~`, `&`, `|`, `^`, `<<`, `>>`, `<<<`, `>>>`, `inside`, `?:`, `'`, `{}`, `[]`, `()`, `#`, `.`, `,`, `;`, `:`, `=>`, `@`
*   **标识符**：`[a-zA-Z_][a-zA-Z0-9_]*`
*   **模板标识符**：`` ident`var `` — 标识符名中嵌入反引号循环变量（如 `data_`i`、`a`i_`j`），由词法分析器后处理合并为单一 Token
*   **注释**：`//` (行), `/* */` (块)，视为空白
*   **空白**：空格、制表、换行丢弃

### 3.2 语法 (EBNF)

```ebnf
CompilationUnit ::= { ModuleDecl }

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
*   **信号推导**：省略 `logic` 的信号统一为 `logic` 类型；未显式声明且未出现在端口列表的标识符，自动生成为隐式 `logic` 信号，位宽由上下文推断，无法确定时报错。
*   **`seq` 块**：`seq (clk, neg: rst_n) { … }` 生成 `always_ff @(posedge clk or negedge rst_n)`，块内顶层 `if(!rst_n)` 保留。**语义分析会将块内所有阻塞赋值 `=` 强制转换为 `<=`**（非 `assign` 语句），确保时序逻辑正确。
*   **`comb` 块**：`comb { … }` 生成 `always_comb begin … end`，块内保留阻塞赋值 `=`，**不进行**非阻塞转换。
*   **`localparam`**：模块内部常量，不能被实例化时的 `#(...)` 覆盖；可用于信号位宽、`` `if `` 条件等编译期表达式。生成 SystemVerilog 时直接输出 `localparam`。
*   **端口连接常数**：仅接受带位宽常数（如 `1'b0`、`8'hFF`）或全位宽常量 `'0`、`'1`。无位宽常量（如 `0`）将被拒绝。`'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定，Slip 编译器不对其进行位宽推导，直接透传给后端工具处理。
*   **悬空标记**：`_` 在端口连接中表示故意悬空，可用于输入或输出端口。
*   **元编程**：
    - `` `for `` 的起始、终止、步长表达式及 `` `if `` 条件必须可在编译期求值为整数常量。支持整数字面量、`param`/`localparam` 引用、以及全部算术/位/关系/逻辑运算符。
    - `` `for `` 循环变量（反引号标识符，如 `` `i ``）在循环体内被当前迭代值替换，并自动进行常量折叠。详见第 7.2.1 节。
*   **模板标识符**：标识符名中可嵌入反引号循环变量（如 `data_`i`），展开时变量替换为当前值（如 `data_3`）。
*   **实例化与正则端口映射**：详见第 7.2.6 节。

---

## 4. 词法分析器

*   识别所有关键字、字面量 `'0` 和 `'1`、字符串。
*   `_` 作为特殊标识符，标记悬空。
*   **后处理合并**：
    - 复合 Token：`` ` `` + 关键字 → `` `for ``、`` `if ``、`` `else ``；`` ` `` + 标识符 → `TICK_IDENT`
    - 复合运算符：`===`、`!==`、`<<<`、`>>>`、`**` 等按最长匹配优先合并
    - **模板标识符合并**：将 `ident` + `` ` `` + `var` 合并为单一 `IDENT` Token（如 `data_`i`），支持多变量（如 `a`i_`j`）
*   Token 携带类型、值、行列号；类 `Lexer` 提供 `tokenize() -> List[Token]`。

---

## 5. 语法分析器

### 5.1 递归下降解析器

*   每个非终结符一个方法，使用 `peek()` / `consume(type)`。
*   `Parser` 持有 Token 流，入口 `parse_module()` 返回 `Module` AST。
*   上下文处理：
    *   模块头直接遇 `{` 则端口列表为空。
    *   `InstanceStmt` 连接列表中识别 `STRING "=>" STRING` 为正则映射。
    *   连接表达式中 `_` 解析为悬空标记；`'0`/`'1` 解析为特殊常量。

### 5.2 Pratt 表达式解析器

优先级严格遵循 **SystemVerilog IEEE 1800-2017**：

| 优先级 | 运算符 | 结合性 |
|--------|--------|--------|
| 1 (最低) | `?:` (三元) | 右 |
| 2 | `inside` (集合成员) | 左 |
| 3 | `\|\|` | 左 |
| 4 | `&&` | 左 |
| 5 | `\|` (按位或) | 左 |
| 6 | `^` (按位异或) | 左 |
| 7 | `&` (按位与) | 左 |
| 8 | `<<`, `>>`, `<<<`, `>>>` (移位) | 左 |
| 9 | `<`, `>`, `<=`, `>=` (关系) | 左 |
| 10 | `==`, `!=`, `===`, `!==` (相等) | 左 |
| 11 | `+`, `-` (二元加减) | 左 |
| 12 | `*`, `/`, `%` (乘除) | 左 |
| 13 | `**` (幂) | 右 |
| 14 | 前缀 `+`, `-`, `!`, `~`, `&`, `\|`, `^`；类型转换 `signed'()` / `unsigned'()` | 右 (前缀) |
| 15 (最高) | `[]`, `[ : ]` (索引)；`N'(expr)` (宽度转换)；`f()` (函数调用) | 左 (后缀) |

*   `<=` 在表达式上下文中为关系运算符；非阻塞赋值由语法层面区分。
*   `{n{expr}}` 复制由 Pratt 解析器的前缀 `{` 处理，检测后跟 `expr{expr}` 模式。
*   原子项包括数字常量、`'0`、`'1`、括号、标识符、`_`（限制在连接中）。

---

## 6. AST 设计

节点继承 `ASTNode`，含位置 `loc`。所有节点为 frozen dataclass。核心节点：

```python
class Module(ASTNode):
    name: str
    params: tuple[Param, ...]       # 模块参数
    ports: tuple[PortItem, ...]     # 空元组为隐式端口
    body: tuple[Statement, ...]     # 包含 LocalParamDecl、SignalDecl 等

class Param(ASTNode):
    name: str
    default: Expr                   # 默认值表达式

class PortItem(ASTNode):
    name: str
    width: Expr | None = None       # 可选端口位宽

class LocalParamDecl(Statement):
    name: str
    value: Expr

class SignalDecl(Statement):
    is_signed: bool
    width: Expr | None              # 信号位宽
    name: str
    array_range: tuple[Expr, Expr] | None  # 数组维度

class SeqBlock(Statement):
    clock: str                      # 时钟信号名
    reset: tuple[str, str] | None   # (极性, 信号名)，如 ('neg', 'rst_n')
    body: BlockStmt

class CombBlock(Statement):
    body: BlockStmt

class GenForStmt(Statement):
    var: str                        # 循环变量名（不含反引号前缀）
    init: Expr
    cond: Expr
    step_var: str                   # 必须与 var 相同
    step: Expr
    body: BlockStmt

class GenIfStmt(Statement):
    cond: Expr
    then_body: BlockStmt
    else_body: BlockStmt | None

class CaseStmt(Statement):
    kind: str                            # 'case', 'casez', 'casex'
    expr: Expr
    items: tuple[CaseItem, ...]

class CaseItem(ASTNode):
    patterns: tuple[Expr, ...]           # 空元组表示 default
    body: BlockStmt

class InstanceStmt(Statement):
    module_name: str
    params: tuple[NamedParam, ...]
    inst_name: str
    connections: tuple[Connection, ...]

class Connection(ASTNode):
    port: str | None                # 显式连接端口名
    signal: Expr | None             # 含 _、'0/'1 或带位宽常数
    port_regex: str | None          # 正则映射模式
    signal_regex: str | None
```

表达式节点包括：`IdentExpr`、`IntLiteralExpr`、`TickConstExpr`（`'0`/`'1`）、`TickIdentExpr`（`` `i ``）、`StringLiteralExpr`、`BinaryExpr`、`UnaryExpr`、`TernaryExpr`、`IndexExpr`、`ConcatExpr`、`ReplicationExpr`、`CastExpr`、`CallExpr`、`ParenExpr`。

---

## 7. 语义分析与 IR

### 7.1 IR 数据结构

```python
@dataclass
class HDLModule:
    name: str
    params: tuple[HDLParam, ...]
    localparams: tuple[HDLParam, ...]
    ports: tuple[HDLPort, ...]
    signals: tuple[HDLSignal, ...]      # 含隐式信号
    assigns: tuple[HDLAssignment, ...]
    logic_blocks: tuple[LogicBlock, ...]
    instances: tuple[HDLInstance, ...]

@dataclass
class HDLParam:
    name: str
    default: str                         # SV 表达式文本

@dataclass
class HDLPort:
    name: str
    direction: str                       # 'input', 'output', 'inout'
    type_: HDLType | None

@dataclass
class HDLSignal:
    name: str
    type_: HDLType | None
    array_dim: str | None                # SV 文本如 "[0:15]"

@dataclass
class HDLAssignment:
    target: str
    value: str                           # SV 表达式文本
    is_nonblocking: bool

@dataclass
class LogicBlock:
    sensitivity: str                     # 如 "posedge clk or negedge rst_n"
    body: tuple                          # HDLAssignment | HDLIfBlock | HDLForLoop | HDLCaseBlock
    kind: str                            # 'always_ff', 'always_comb', 'always_latch', 'initial'

@dataclass
class HDLForLoop:
    var: str
    init: str                            # SV 表达式文本
    cond: str
    step: str
    body: tuple

@dataclass
class HDLCaseBlock:
    kind: str                            # 'case', 'casez', 'casex'
    expr: str                            # SV 表达式文本
    items: tuple[HDLCaseItem, ...]

@dataclass
class HDLCaseItem:
    patterns: tuple[str, ...]            # SV 模式文本；空元组表示 default
    body: tuple

@dataclass
class HDLInstance:
    inst_name: str
    target: str
    param_map: tuple[tuple[str, str], ...]
    port_map: tuple[tuple[str, str], ...]
    regex_rules: tuple[tuple[str, str], ...]
```

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
*   替换后的表达式进行常量折叠：
    *   两操作数均为整数字面量的二元运算 → 计算为结果字面量
    *   操作数为整数字面量的一元运算 → 计算为结果字面量
    *   代数化简：`x + 0 → x`、`x - 0 → x`、`x * 1 → x`、`x * 0 → 0`、`x / 1 → x`
    *   三元表达式条件为常量 → 选择对应分支
    *   括号内为字面量 → 脱括号
*   包含非常量子表达式（如参数引用 `W`）的运算保持不变，仅折叠常量部分。

**模板标识符**：标识符中可包含反引号循环变量（如 `stage_`i`、`a`i_`j`）。词法分析器在合并阶段将其识别为单一 Token，展开时替换变量部分（`stage_`i → stage_0, stage_1, …）。

**循环变量不可赋值**：`` `i `` 为 `TickIdentExpr`，语法上不能出现在赋值左侧（`LValue` 仅接受普通标识符）。循环变量的值由展开引擎在每个迭代中确定，不可在体内修改。

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
*   `i=0`：`out[W - 1 - 0]` → 折叠为 `out[W - 1]`（`- 0` 消除）
*   `i=1`：`out[W - 1 - 1]` → 折叠为 `out[W - 2]`
*   `i=7`：`out[W - 1 - 7]` → 折叠为 `out[W - 8]`

所有索引表达式中的常量运算在编译期完成，仅保留含参数的子表达式。

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

*   `CombBlock` 转为 `LogicBlock` 类型 `always_comb`。
*   若检测到锁存器模式，使用 `always_latch`（无敏感列表）。

#### 7.2.6 实例化与正则端口映射

**常数与悬空约束**

*   显式连接表达式若为常数，必须是带位宽格式（如 `3'b101`）或全位宽常量 `'0`/`'1`。无位宽整数（如 `0`）报错。
*   `'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定。Slip 编译器不对此类常量进行位宽推导，直接将它们透传到生成的 SystemVerilog 代码中，由下游工具根据目标端口的宽度自动扩展。
*   `_` 作为悬空标记，可用于任何方向端口。

**连接展开与位宽推导**

*   **输入**：目标模块信息（通过同设计 IR 或 `slang` 反射），包括端口列表（方向、宽度表达式）、参数（含可覆盖与 `localparam`）及实例化覆盖值。
*   **有限常量求值器**：仅支持常量、参数引用和基本算术；失败则隐式信号需要用户显式声明。
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
*   **自定义正则函数**：通过 Python API 注册自定义函数：
    ```python
    from slip.semantic.regex_funcs import register
    register("my_func", lambda s: f"prefix_{s}")
    ```
    注册后可在替换字符串中使用 `$my_func(\1)`。自定义函数可覆盖内置函数。函数签名必须接受字符串参数并返回字符串。
*   **原生自定义函数（defun）**：在 Slip 中直接定义函数：
    ```slip
    defun prefix(s):
        return "bus_" + s

    defun to_upper(s):
        return s.upper()

    defun inc(n):
        return n + 1
    ```
    函数体支持完整 Python 表达式，包括：字符串拼接（`+`）、字符串方法（`.upper()`、`.lower()`、`.reverse()`、`.replace()`、`.strip()`、`.split()`、`.startswith()` 等）、算术运算（`+`、`-`、`*`、`/`、`%`）、方法链式调用、内置函数（`len()`、`int()`、`str()` 等）、索引切片（`s[0]`、`s[1:3]`、`s[3:]`、`s[:3]`、`s[-1]`）、三元表达式。函数可在顶层任意位置定义（模块前或后），所有 `defun` 在实例解析前注册。
*   **连接完成检查**：
    - 输入/双向端口未连接且非悬空 → 报错。
    - 输出端口未连接 → 警告（悬空允许）。
    - 外部 IP 模块跳过检查。
*   **`localparam` 覆盖检查**：若实例化 `#(...)` 中包含 `localparam`，报错。

---

## 8. 代码生成

*   基于片段解析 + SyntaxRewriter：
    *   `seq` → `always_ff @(...)`，赋值 `<=`
    *   `comb` → `always_comb`，保留 `=`
    *   `initial` → `initial begin ... end`，保留 `=`
    *   `case`/`casez`/`casex` → `case`/`casez`/`casex ... endcase`
    *   实例化 → 根据 `port_map` 生成 `.port(signal)`，若为悬空则省略该连接。
*   模块按拓扑排序输出（定义在实例化之前）。
*   `'0` 和 `'1` 直接输出为 Verilog 全位宽常量。
*   生成的 SystemVerilog 通过 pyslang 进行语法验证。

---

## 9. Slang 集成层

### 9.1 IP 反射

`slang_integration.reflect_module(sv_path, module_name)` 返回：

```python
@dataclass
class ExternalModuleInfo:
    name: str
    params: list[dict]      # 包含 is_local 标记
    ports: list[dict]       # 包含 width_expr 等
```

---

## 10. 命令行接口

```
slip build [-o <out_dir>] [-ip <ip_dirs>] <file.slip>
slip check [-ip <ip_dirs>] <file.slip>
```

---

## 11. 错误处理

错误类型：

*   `SlipSyntaxError`：语法错误（词法/语法分析阶段）
*   `SlipSemanticError`：语义错误（分析/展开阶段），包括：
    *   `constant in port connection must have explicit width (e.g. 1'b0) or use '0/'1`
    *   `cannot override localparam '...'`
    *   `unconnected input port '...'`
    *   `unable to infer width for implicit signal '...'`
    *   `cannot evaluate '...' at compile time`
    *   `unsupported operator '...' in compile-time expression`
    *   `#for step variable '...' must match loop variable '...'`
    *   `#for loop exceeded 1024 iterations`
    *   `signal '...' driven by multiple sequential/combinational blocks`
    *   `combinational loop detected: ...`
    *   `duplicate declaration of '...'`
    *   `reset polarity inconsistency: ...`
*   警告（通过 `warnings.warn()` 发出）：
    *   `width mismatch: '...' is N bits, but value is M bits`
    *   `port width mismatch: '...' expects N bits, but '...' is M bits`

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
*   代码生成正确性（pyslang 验证）
