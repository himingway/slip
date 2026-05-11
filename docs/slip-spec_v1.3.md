# Slip 开发者文档 v1.3

**全称**：Streamlined Integration Platform  
**状态**：草案  
**面向读者**：项目核心开发人员  
**最后更新**：2026-05-11

---

## 更新说明 (v1.3)

*   新增组合逻辑块 `comb` 语法，对应 `always_comb`。
*   完整定义实例化与正则端口映射机制，包含位宽自动推导、悬空标记、参数覆盖、`localparam` 支持、tie 常量 `'0`/`'1`（位宽由目标端口决定）。
*   明确常数连接位宽约束：仅允许带位宽常数或全位宽常量，禁止无位宽常数。
*   引入悬空标记 `_`。
*   新增 `localparam` 关键字，用于内部常量，不可被实例化覆盖。
*   增加有限常量求值器说明，用于参数化位宽推导。
*   **元编程增强**：`#for` 循环变量 `i` 在循环体内可参与任意常量表达式运算，支持算术、位运算、比较、与参数混合等，并在展开时进行常量折叠。增加了详细使用规则和限制。

---

## 1. 引言

Slip 是一个极简硬件描述语言 (DSL) 编译器。它定义了一组高度精简的直觉化语法糖，可将硬件设计意图自动编译为高质量、可综合的 SystemVerilog 代码，并利用 `slang` 引擎提供语义验证与 IP 集成。

### 1.1 设计目标
*   **极简源语言**：通过上下文自动推导端口方向、信号类型、实例化连线，只保留硬件本质描述。
*   **严谨代码生成**：采用“片段解析 + SyntaxRewriter”模式，通过 `pyslang` 构建语法树，确保输出代码语法与语义正确。
*   **可靠的元编程**：提供编译期 `#for` / `#if` 展开，支持循环变量在体内运算并自动常量折叠，严格限制条件为常量或 `param`/`localparam` 标识符。
*   **IP 自动集成**：利用 `slang` 反射外部模块的参数、`localparam` 和端口信息，支持正则批量端口映射、位宽自动推导、悬空标记和智能 tie 常数。
*   **清晰边界**：不涉及仿真脚本、综合脚本或 FPGA 项目文件生成。

### 1.2 技术选型
*   实现语言：Python 3.10+
*   词法分析：基于正则表达式的 Token 生成器
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
[词法分析器] → Token 流
      │
      ▼
[递归下降语法分析器] → 自定义 AST (带源码位置)
      │
      ▼
[语义分析 & IR 构建]
  ├─ 元编程展开 (含循环变量运算与常量折叠)
  ├─ 隐式端口/信号推导
  ├─ 驱动分析 (剔除内部自驱动)
  ├─ 时序块赋值强制纠正 (seq 块)
  ├─ 组合逻辑块识别 (comb 块保持阻塞赋值)
  └─ 实例化连接展开 (正则映射、悬空、tie、位宽推导)
      │
      ▼
设计 IR (与语法解耦)
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
| `lexer` | 将字符流转化为 Token 列表，记录行列号 |
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
*   **关键字**：`module`, `param`, `localparam`, `logic`, `signed`, `assign`, `seq`, `comb`, `pos`, `neg`, `if`, `else`, `for`, `#for`, `#if`, `#else`
*   **特殊标识**：`_`（悬空标记）
*   **字面量**：Verilog 风格整数常量（包括 `'0` 和 `'1`）、字符串（仅用于正则映射）
*   **运算符**：`=`, `<=`, `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `>=`, `&&`, `||`, `!`, `~`, `&`, `|`, `^`, `<<`, `>>`, `?:`, `'`, `{}`, `[]`, `()`, `#`, `.`, `,`, `;`, `:`, `=>`, `@`
*   **标识符**：`[a-zA-Z_][a-zA-Z0-9_]*`
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
PortItem      ::= IDENT [ "[" Expr "]" ]          (* 无方向声明 *)

Statement ::= SignalDecl
            | LocalparamDecl
            | AssignStmt
            | SeqBlock
            | CombBlock
            | IfStmt
            | ForStmt
            | GenForStmt
            | GenIfStmt
            | InstanceStmt
            | BlockStmt

SignalDecl ::= ["logic"] ["signed"] [ "[" Expr "]" ]
               IDENT [ "[" Expr ":" Expr "]" ] ";"

LocalparamDecl ::= "localparam" IDENT "=" Expr { "," IDENT "=" Expr } ";"

AssignStmt ::= "assign" Lvalue "=" Expr ";"

SeqBlock   ::= "seq" "(" IDENT [ "," ("pos" | "neg") ":" IDENT ] ")" BlockStmt
CombBlock  ::= "comb" BlockStmt

IfStmt ::= "if" "(" Expr ")" BlockStmt [ "else" BlockStmt ]

ForStmt ::= "for" "(" IDENT "=" Expr ";" Expr ";" IDENT "=" Expr ")" BlockStmt

GenForStmt ::= "#for" "(" IDENT "=" Expr ";" Expr ";" IDENT "=" Expr ")" BlockStmt

GenIfStmt ::= "#if" "(" Expr ")" BlockStmt [ "#else" BlockStmt ]

InstanceStmt ::= IDENT [ "#(" NamedParam { "," NamedParam } ")" ]
                 IDENT "{" { Connection } "}" ";"
NamedParam ::= "." IDENT "(" Expr ")"
Connection ::= "." IDENT [ "(" Expr ")" ]          (* Expr 可为 `'0'`, `'1'`, `_` 或带位宽常数 *)
             | STRING "=>" STRING                  (* 正则映射 *)

BlockStmt ::= "{" { Statement } "}"

Lvalue ::= IDENT { "[" Expr "]" | "[" Expr ":" Expr "]" }

Expr ::= (* 表达式：由 Pratt 解析器实现，涵盖所有支持运算符，
          `_` 作为悬空标记仅在连接中使用，`'0`, `'1` 为特殊常量 *)
```

### 3.3 语义说明
*   **端口推导**：若 `PortList` 缺失（括号也省略），模块内所有被使用且非内部声明的标识符均变为端口，方向由驱动分析决定；显式端口列表则只有列表中信号是端口，未声明使用报错。
*   **信号推导**：省略 `logic` 的信号统一为 `logic` 类型；未显式声明且未出现在端口列表的标识符，自动生成为隐式 `logic` 信号，位宽由上下文推断，无法确定时报错。
*   **`seq` 块**：`seq (clk, neg: rst_n) { … }` 生成 `always_ff @(posedge clk or negedge rst_n)`，块内顶层 `if(!rst_n)` 保留。**语义分析会将块内所有阻塞赋值 `=` 强制转换为 `<=`**（非 `assign` 语句），确保时序逻辑正确。
*   **`comb` 块**：`comb { … }` 生成 `always_comb begin … end`，块内保留阻塞赋值 `=`，**不进行**非阻塞转换。
*   **`localparam`**：模块内部常量，不能被实例化时的 `#(...)` 覆盖；可用于信号位宽、`#if` 条件等编译期表达式。生成 SystemVerilog 时直接输出 `localparam`。
*   **端口连接常数**：仅接受带位宽常数（如 `1'b0`、`8'hFF`）或全位宽常量 `'0`、`'1`。无位宽常量（如 `0`）将被拒绝。`'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定，Slip 编译器不对其进行位宽推导，直接透传给后端工具处理。
*   **悬空标记**：`_` 在端口连接中表示故意悬空，可用于输入或输出端口。
*   **元编程**：
    - `#for` / `#if` 条件 **仅支持纯整数常量、`param` / `localparam` 标识符的直接引用**。任何运算符或函数调用均禁止。
    - `#for` 循环变量在循环体内可作为整数常量使用，并参与任意合法的编译期表达式运算（算术、位运算、比较等），在展开阶段进行常量折叠。详见第 7.2.1 节。
*   **实例化与正则端口映射**：详见第 7.2.6 节。

---

## 4. 词法分析器

*   识别所有关键字、字面量 `'0` 和 `'1`、字符串。
*   `_` 作为特殊标识符，标记悬空。
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
| 1 | `?:` | 右 |
| 2 | `\|\|` | 左 |
| 3 | `&&` | 左 |
| 4 | `\|` | 左 |
| 5 | `^` | 左 |
| 6 | `&` | 左 |
| 7 | `<<`, `>>` | 左 |
| 8 | `<`, `>`, `<=`, `>=` | 左 |
| 9 | `==`, `!=` | 左 |
| 10 | `+`, `-` (二元) | 左 |
| 11 | `*`, `/`, `%` | 左 |
| 12 | 前缀 `+`, `-`, `!`, `~`, `&`, `\|`, `^`、`signed'()`、`unsigned'()` | 右 |
| 13 | `[]`, `[ : ]`、`'` 转换、函数调用 | 左 |

*   `<=` 在表达式上下文中为关系运算符；非阻塞赋值由语法层面区分。
*   原子项包括数字常量、`'0`、`'1`、括号、标识符、`_`（限制在连接中）。

---

## 6. AST 设计

节点继承 `ASTNode`，含位置 `loc`。核心节点：

```python
class Module(ASTNode):
    name: str
    params: list[Param]
    localparams: list[LocalparamDecl]
    ports: list[PortItem]          # 空列表为隐式
    body: list[Statement]

class LocalparamDecl(ASTNode):
    name: str
    value: Expr

class SeqBlock(ASTNode):
    clock: str
    async_reset: Optional[tuple[str, str]]   # ('pos'|'neg', signal)
    body: BlockStmt

class CombBlock(ASTNode):
    body: BlockStmt

class InstanceStmt(ASTNode):
    module_name: str
    params: list[NamedParam]
    inst_name: str
    connections: list[Connection]

class Connection(ASTNode):
    port: Optional[str]              # 显式连接
    signal: Optional[Expr]           # 含 `_` 或 `'0/1` 或带位宽常数
    port_regex: Optional[str]        # 正则映射
    signal_regex: Optional[str]
```

---

## 7. 语义分析与 IR

### 7.1 IR 数据结构
```python
@dataclass
class HDLModule:
    name: str
    params: list[HDLParam]
    localparams: list[HDLLocalparam]
    ports: list[HDLPort]
    signals: list[HDLSignal]     # 包含隐式
    logic_blocks: list[LogicBlock]
    instances: list[HDLInstance]

@dataclass
class HDLPort:
    name: str
    direction: str   # 'input','output','inout'
    width: Optional[WidthExpr]
    is_signed: bool

@dataclass
class HDLInstance:
    inst_name: str
    target: str
    param_map: dict[str, Expression]
    port_map: dict[str, Expression | None]   # None 表示悬空
```

### 7.2 语义分析流程

#### 7.2.1 元编程展开（增强：循环变量运算）

*   **条件限制**：`#for` 的起始、终止、步长表达式及 `#if` 条件**必须为纯整数常量或 `param`/`localparam` 标识符的直接引用**。不允许任何运算符或函数调用，以确保在展开阶段无需复杂求值即可确定循环次数和分支。
*   **循环变量处理**：
    - 循环变量（如 `i`）在循环体内被视为 **编译期整数常量**，其值等于当前迭代索引（从起始值开始，依次增加步长，直到小于终止值）。
    - 循环体内任何合法的表达式均可使用循环变量，包括但不限于：
        *   算术运算：`+`, `-`, `*`, `/`, `%`
        *   位运算：`~`, `&`, `|`, `^`, `<<`, `>>`
        *   关系/比较运算：`==`, `!=`, `<`, `>`, `<=`, `>=`（通常用于内联 `if` 或 `#if`）
        *   位选/部分选索引：`data[i]`, `vec[i*2 +: 4]`
        *   与参数/`localparam` 混合：`W - i - 1`, `(i + 1) * STEP`
    - 展开引擎会在每次迭代时用**当前常量值替换循环变量**，并尝试对整个表达式进行**常量折叠**（如 `W - i - 1` 会变为 `W - 0 - 1 = W - 1`）。折叠后的表达式生成到 AST 中，最终作为常量节点参与后续推导。
    - 如果表达式中因包含未展开的系统函数或非常量导致无法折叠，编译报错。
*   **禁止行为**：
    - 循环体内不允许对循环变量进行赋值（如 `i = i + 1`），循环变量由展开引擎控制。
    - 循环变量的值在每个迭代中为常数，不可修改。
*   **循环变量声明**：
    - 推荐在模块体内预先声明 `integer i;`。若用户未声明，语义分析阶段自动创建隐式 `integer` 变量，作用域限于该 `#for` 块，并在展开后丢弃。

**示例**：
```slip
module reverse #(param W=8) (in[W-1:0], out[W-1:0]) {
    integer i;
    #for (i = 0; i < W; i = i + 1) {
        assign out[i] = in[W - 1 - i];        // 算术运算
        assign tmp[i*2] = in[i] ^ in[W-1];    // 位索引计算
    }
}
```
展开后（W=8）生成常量索引 `in[7-0]`, `in[7-1]` 等，均为编译期常量。

#### 7.2.2 符号收集与隐式声明
*   收集显式声明；确定端口候选；未声明且使用的标识符生成隐式 `logic`，位宽尽量从上下文推断。

#### 7.2.3 驱动分析
*   先标记所有内部驱动的信号；候选端口仅当无内部驱动时判定方向；内部信号可自由读写。

#### 7.2.4 赋值纠正
*   `seq` 块内阻塞 `=` 转为 `<=`，并警告。
*   `comb` 块保留阻塞赋值。

#### 7.2.5 组合逻辑块处理
*   `CombBlock` 转为 `LogicBlock` 类型 `always_comb`。

#### 7.2.6 实例化与正则端口映射（详细设计）

**常数与悬空约束**
*   显式连接表达式若为常数，必须是带位宽格式（如 `3'b101`）或全位宽常量 `'0`/`'1`。无位宽整数（如 `0`）报错。
*   `'0` 和 `'1` 是 SystemVerilog 原生的自适应宽度常量，其位宽由所连接的目标端口决定。Slip 编译器不对此类常量进行位宽推导，直接将它们透传到生成的 SystemVerilog 代码中，由下游工具根据目标端口的宽度自动扩展为全 0 或全 1。
*   `_` 作为悬空标记，可用于任何方向端口。

**连接展开与位宽推导**
*   **输入**：目标模块信息（通过同设计 IR 或 `slang` 反射），包括端口列表（方向、宽度表达式）、参数（含可覆盖与 `localparam`）及实例化覆盖值。
*   **有限常量求值器**：仅支持常量、参数引用和基本算术；失败则隐式信号需要用户显式声明。
*   **映射优先级**：显式连接 > 同名连接 > 正则映射（按书写顺序）。
*   **正则映射信号生成**：
    - 若生成的信号名已存在 → 直接使用，并检查位宽兼容。
    - 若不存在 → 创建隐式 `logic` 信号，位宽从目标端口宽度推导（使用求值器）。求值失败则报错。
*   **连接完成检查**：
    - 输入/双向端口未连接且非悬空 → 报错。
    - 输出端口未连接 → 警告（悬空允许）。
*   **`localparam` 覆盖检查**：若实例化 `#(...)` 中包含 `localparam`，报错。

---

## 8. 代码生成

*   基于片段解析 + SyntaxRewriter：
    *   `seq` → `always_ff @(...)`，赋值 `<=`
    *   `comb` → `always_comb`，保留 `=`
    *   实例化 → 根据 `port_map` 生成 `.port(signal)`，若为悬空则省略该连接。
*   `'0` 和 `'1` 直接输出为 Verilog 全位宽常量。

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

新增错误类：
*   `SlipSemanticError: constant in port connection must have explicit width (e.g. 1'b0) or use '0/'1`
*   `SlipSemanticError: cannot override localparam '...'`
*   `SlipSemanticError: unconnected input port '...'`
*   `SlipSemanticError: unable to infer width for implicit signal '...'`
*   `SlipSemanticError: assignment to loop variable 'i' is not allowed in #for body`
*   `SlipSemanticError: constant expression in #for body could not be folded`

---

## 12. 测试策略

重点测试：
*   `comb` 块及 `=` 保留。
*   `'0`/`'1` 与宽度限制。
*   悬空 `_` 行为。
*   正则映射的隐式信号位宽推导（含参数化）。
*   `localparam` 不可覆盖。
*   `#for` 循环变量参与各种运算、禁止赋值、常量折叠等。

---

## 13. 开发路线图

*   Phase 1：基础解析、隐式推导、`seq`/`comb`、端口推导、简单 SV 生成。
*   Phase 2：元编程（含循环变量运算）、实例化与正则映射、`localparam`、常数约束、悬空、`slang` 反射、位宽推导。
*   Phase 3：系统函数、模板定制、全面测试。

---

**附录**：略。

此文档整合了所有讨论特性，作为 Slip 编译器的最终开发凭据。
