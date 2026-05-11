# Slip 开发者文档 v1.0

**全称**：Streamlined Integration Platform  
**状态**：草案  
**面向读者**：项目核心开发人员  
**最后更新**：2026-05-10

---

## 1. 引言

Slip 是一个极简硬件描述语言 (DSL) 编译器。它定义了一组高度精简的直觉化语法糖，可将硬件设计意图自动编译为高质量、可综合的 SystemVerilog 代码，并利用 `slang` 引擎提供语义验证与 IP 集成。

### 1.1 设计目标
*   **极简源语言**：通过上下文自动推导端口方向、信号类型、实例化连线，只保留硬件本质描述。
*   **严谨代码生成**：采用 “片段解析 + SyntaxRewriter” 模式，通过 `pyslang` 构建语法树，确保输出代码语法与语义正确。
*   **可靠的元编程**：提供编译期 `#for` / `#if` 展开，严格限制条件为常量或 `param` 标识符，避免前端的复杂求值。
*   **IP 自动集成**：利用 `slang` 反射外部模块端口，支持正则批量端口映射。
*   **清晰边界**：不涉及仿真脚本、综合脚本或 FPGA 项目文件生成。

### 1.2 技术选型
*   实现语言：Python 3.10+ (使用uv）
*   词法分析：基于正则表达式的 Token 生成器
*   语法分析：手写递归下降解析器 + Pratt 表达式解析器
*   中间表示：自定义 Python 数据类
*   代码生成：`pyslang` 片段解析 + `SyntaxRewriter` 组合语法树
*   外部 Verilog 处理：`pyslang` 编译、反射、诊断
*   CLI 框架：`click`

---

## 2. 系统架构

编译器采用经典三阶段流水线，并明确各模块职责。

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
  ├─ 元编程展开 (仅常量/param)
  ├─ 隐式端口/信号推导
  ├─ 驱动分析 (剔除内部自驱动)
  ├─ 时序块赋值强制纠正
  └─ 实例化连接展开
      │
      ▼
设计 IR (与语法解耦)
      │
      ├─→ [代码生成器] 片段解析 → pyslang SyntaxTree
      └─→ [slang 反射] 获取外部模块端口信息
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
| `semantic` | 元编程展开、信号/端口推导、驱动分析、赋值纠正、实例化连接展开 |
| `codegen` | 遍历 IR，使用 pyslang 片段生成语法树并序列化为文本 |
| `slang_integration` | 封装 pyslang 进行 IP 反射、诊断 |
| `cli` | 命令行接口 |
| `errors` | 错误/警告定义与格式化 |

---

## 3. 源语言规范 (Slip Grammar)

### 3.1 词法元素
*   **关键字**：`module`, `param`, `logic`, `signed`, `assign`, `seq`, `pos`, `neg`, `if`, `else`, `for`, `#for`, `#if`, `#else`
*   **运算符**：`=`, `<=`, `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `>=`, `&&`, `||`, `!`, `~`, `&`, `|`, `^`, `<<`, `>>`, `?:`, `'`, `{}`, `[]`, `()`, `#`, `.`, `,`, `;`, `:`, `=>`, `@`
*   **字面量**：Verilog 风格整数常量 (含位宽 `8'hFF`)、字符串 (仅用于正则实例化)
*   **标识符**：`[a-zA-Z_][a-zA-Z0-9_]*`
*   **注释**：`//` (行), `/* */` (块), 视为空白
*   **空白**：空格、制表、换行被丢弃

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
            | AssignStmt
            | SeqBlock
            | IfStmt
            | ForStmt
            | GenForStmt
            | GenIfStmt
            | InstanceStmt
            | BlockStmt

SignalDecl ::= ["logic"] ["signed"] [ "[" Expr "]" ]
               IDENT [ "[" Expr ":" Expr "]" ] ";"

AssignStmt ::= "assign" Lvalue "=" Expr ";"

SeqBlock ::= "seq" "(" IDENT [ "," ("pos" | "neg") ":" IDENT ] ")" BlockStmt

IfStmt ::= "if" "(" Expr ")" BlockStmt [ "else" BlockStmt ]

ForStmt ::= "for" "(" IDENT "=" Expr ";" Expr ";" IDENT "=" Expr ")" BlockStmt

GenForStmt ::= "#for" "(" IDENT "=" Expr ";" Expr ";" IDENT "=" Expr ")" BlockStmt

GenIfStmt ::= "#if" "(" Expr ")" BlockStmt [ "#else" BlockStmt ]

InstanceStmt ::= IDENT [ "#(" NamedParam { "," NamedParam } ")" ]
                 IDENT "{" { Connection } "}" ";"
NamedParam ::= "." IDENT "(" Expr ")"
Connection ::= "." IDENT [ "(" Expr ")" ]
             | STRING "=>" STRING

BlockStmt ::= "{" { Statement } "}"

Lvalue ::= IDENT { "[" Expr "]" | "[" Expr ":" Expr "]" }

Expr ::= (* 表达式：由 Pratt 解析器实现，涵盖所有支持运算符 *)
```

### 3.3 语义说明
*   **端口推导**：若 `PortList` 缺失（括号也省略），模块内所有被使用且非内部声明的标识符均变为端口，方向由驱动分析决定；显式端口列表则只有列表中信号是端口，未声明使用报错。
*   **信号推导**：省略 `logic` 的信号统一为 `logic` 类型；未显式声明且未出现在端口列表的标识符，自动生成为隐式 `logic` 信号，位宽由上下文推断，无法确定时报错。
*   **`seq` 块**：`seq (clk, neg: rst_n) { … }` 生成 `always_ff @(posedge clk or negedge rst_n)`，块内顶层 `if(!rst_n)` 保留。**语义分析会将块内所有阻塞赋值 `=` 强制转换为 `<=`**（非 `assign` 语句），确保时序逻辑正确。
*   **元编程**：`#for` / `#if` 条件 **仅支持纯整数常量或直接 `param` 引用**。任何运算符、函数调用均禁止，保持常量求值零成本。
*   **实例化正则映射**：正则连接依赖目标模块端口列表（IR 或 slang 反射），按顺序匹配，首个成功则映射，未匹配端口需有同名或显式连接，否则报错。

---

## 4. 词法分析器

*   实现正则扫描，采用最长匹配原则。
*   `Token` 携带类型、属性值、行列号。
*   类 `Lexer`，对外提供 `tokenize() -> List[Token]`。

---

## 5. 语法分析器

### 5.1 递归下降解析器
*   每个非终结符对应一个解析方法，通过 `peek()` 与 `consume(type)` 驱动。
*   `Parser` 持有 Token 流，入口 `parse_module()` 返回 `Module` AST 节点。
*   上下文处理：
    *   模块头解析时若直接遇到 `{` 而非 `(`，端口列表为空。
    *   实例化连接列表中识别 `STRING "=>" STRING` 为正则映射。

### 5.2 Pratt 表达式解析器
表达式解析采用 Pratt 算法，运算符优先级严格遵循 **SystemVerilog IEEE 1800-2017** 标准 (由低到高排列)：

| 优先级 | 运算符 | 结合性 |
|--------|--------|--------|
| 1 (最低) | `?:` (条件) | 右结合 |
| 2 | `\|\|` | 左结合 |
| 3 | `&&` | 左结合 |
| 4 | `\|` (按位或) | 左结合 |
| 5 | `^` (按位异或) | 左结合 |
| 6 | `&` (按位与) | 左结合 |
| 7 | `<<`, `>>` (移位) | 左结合 |
| 8 | `<`, `>`, `<=`, `>=` (关系) | 左结合 |
| 9 | `==`, `!=` (相等) | 左结合 |
| 10 | `+`, `-` (二元) | 左结合 |
| 11 | `*`, `/`, `%` | 左结合 |
| 12 | 前缀 `+`, `-`, `!`, `~`, `&`, `\|`, `^` 等 (一元)、`signed'()`、`unsigned'()` | 右结合 |
| 13 (最高) | 后缀 `[]`, `[ : ]`、`'` 转换、函数调用 | 左结合 |

**要点**：
*   `<=` 在表达式上下文始终解析为关系运算符；非阻塞赋值仅在过程语句左值后识别，由语法层面区分。
*   前缀运算符包括缩减运算 (如 `&a`, `|a`)；`signed'(expr)` 作为前缀特殊处理。
*   数字常量及括号 `(expr)` 作为基础原子项处理。

---

## 6. AST 设计

所有节点继承 `ASTNode`，包含 `loc` 位置属性。核心节点类型：

```python
class Module(ASTNode):
    name: str
    params: list[Param]
    ports: list[PortItem]   # 空列表代表隐式
    body: list[Statement]

class SeqBlock(ASTNode):
    clock: str
    async_reset: Optional[tuple[str, str]]  # ('pos'|'neg', signal_name)
    body: BlockStmt

class InstanceStmt(ASTNode):
    module_name: str
    params: list[NamedParam]
    inst_name: str
    connections: list[Connection]

class Connection(ASTNode):
    port: Optional[str]          # 显式连接时有效
    signal: Optional[Expr]       # 显式连接时有效
    port_regex: Optional[str]    # 正则映射
    signal_regex: Optional[str]
```

---

## 7. 语义分析与 IR

### 7.1 IR 数据结构 (与语法解耦)
```python
@dataclass
class HDLModule:
    name: str
    params: list[HDLParam]
    ports: list[HDLPort]
    signals: list[HDLSignal]        # 包含隐式声明的信号
    logic_blocks: list[LogicBlock]
    instances: list[HDLInstance]

@dataclass
class HDLPort:
    name: str
    direction: str   # 'input','output','inout'
    width: Optional[WidthExpr]
    is_signed: bool

@dataclass
class HDLSignal:
    name: str
    width: Optional[WidthExpr]
    is_signed: bool
    array_dim: Optional[tuple[Expr, Expr]]

@dataclass
class HDLInstance:
    inst_name: str
    target: str
    param_map: dict[str, Expression]
    port_map: dict[str, Expression]   # 端口名 → 连接的信号表达式
```

### 7.2 语义分析流程

#### 7.2.1 元编程展开
*   **条件限制**：`#for` 的起止步长、`#if` 条件必须为纯整数常量或直接 `param` 标识符引用。不满足则立即报错。
*   **展开算法**：在 AST 上直接替换节点，生成重复或条件分支语句，再交后续推导。

#### 7.2.2 符号收集与隐式声明
1.  遍历模块，收集所有显式声明的参数、端口、信号、实例名。
2.  收集所有标识符引用。
3.  若端口列表为空，未被收集的引用标识符均成为候选端口；若端口列表显式，则只有列表内是端口，其余未声明的标识符自动生成为隐式 `logic` 信号，位宽由赋值/使用上下文推断，无法推断则报错。

#### 7.2.3 驱动分析（改进算法）
为避免内部自驱动的信号泄漏为端口，**必须先判定每个标识符在模块内部是否有驱动源**。
*   扫描所有赋值左值、非阻塞赋值目标、`assign` 左值，标记“内部驱动”集合。
*   候选端口判定：标识符 **没有** 内部驱动，但被读取 → `input`；**只有** 内部驱动 → `output`；既有内部驱动又有读取且无法区分方向 → 报错。
*   内部信号即便读写同时存在也是正常的组合/时序逻辑，不会变成端口。

#### 7.2.4 时序块赋值纠正
遍历所有 `SeqBlock`，将其中的阻塞赋值 `=` (非 `assign` 语句) 替换为 `<=`，并产生编译警告。

#### 7.2.5 实例化正则映射展开
1.  获取目标模块端口信息（来自同设计中 IR 或通过 `slang` 反射外部文件）。
2.  对每个目标端口，按连接列表顺序匹配：显式连接 > 同名连接 > 正则映射。
3.  未匹配的端口若无默认值则报错；输出端口未连接给出警告。

---

## 8. 代码生成（片段解析 + SyntaxRewriter）

### 8.1 策略
完全通过 API 构建语法树极其繁琐，因此采用以下混合策略：
1.  将每个 IR 模块的头部、内部项、实例化等，**拼装成合法的 SystemVerilog 文本片段**。
2.  调用 `pyslang.SyntaxTree.fromText(snippet)` 解析为对应子树。
3.  使用 `SyntaxRewriter` 或直接操作 Syntax List 将这些子树组合为完整 `CompilationUnit`。
4.  最终通过语法树的标准序列化输出源码。

**优点**：代码量减少 ~80%，子树天然合法，可利用 slang 默认格式化。

### 8.2 主要映射
*   `HDLPort`：生成 `input logic [W-1:0] name` 或 `output logic ...` 片段。
*   `SeqBlock`：生成 `always_ff @(posedge clk or negedge rst_n) begin … end` 片段，内部赋值已为 `<=`。
*   `Instance`：生成 `模块名 #(...) 实例名 ( .port(sig), … );` 片段。
*   隐式信号：生成 `logic [W-1:0] sig;` 。

### 8.3 格式化与验证
生成后可选：
*   让 `slang` 再次解析输出文件并收集诊断信息，确保无语法/基本语义错误。
*   利用 `slang` 的代码风格选项重新格式输出，保持统一。

---

## 9. Slang 集成层

### 9.1 IP 反射
`slang_integration.reflect_module(sv_path, module_name)` 返回包含参数和端口列表的字典，供实例化正则映射使用。

### 9.2 诊断
输出 SystemVerilog 后，通过 `pyslang.Compilation` 加载并调用 `getAllDiagnostics()`，将问题（如宽度不匹配）映射回源文件位置。

---

## 10. 命令行接口

```
slip build [-o <out_dir>] [-ip <ip_dirs>] <file.slip>
slip check [-ip <ip_dirs>] <file.slip>
```

*   `build`：编译生成 SystemVerilog 文件，并对生成结果做 slang 校验。
*   `check`：仅执行语义分析和集成检查，不产生输出文件。

---

## 11. 错误处理

所有编译器异常继承自 `SlipError`：
*   `SlipSyntaxError`：解析期异常，含行列号。
*   `SlipSemanticError`：推导或类型异常。
*   `SlipCodegenError`：代码生成期内部错误。

报错格式：`Error at <file>:<line>:<col>: <message>`，通过 CLI 输出。

---

## 12. 测试策略

*   **单元测试**：词法分析、Pratt 表达式解析、驱动分析算法、片段生成器。
*   **集成测试**：输入 `.slip` 用例，对比生成的 SystemVerilog 关键片段，并通过 `slang` 检查无错误。
*   **回归套件**：覆盖自动推导、`seq`、元编程、实例化正则映射等典型场景。

---

## 13. 开发路线图

### Phase 1 – 最小可行内核
*   词法/语法解析器 (含 Pratt)
*   模块、参数、端口、`assign`、`seq`、`if`、`for` 支持
*   隐式端口与信号推导 (含改进驱动分析)
*   片段解析生成 SystemVerilog + slang 校验
*   CLI `build` 可用

### Phase 2 – 元编程与集成
*   `#for` / `#if` 展开 (严格常量限制)
*   实例化 (显式+同名+正则) 与 slang 反射
*   `seq` 内部赋值纠正
*   完善错误位置映射

### Phase 3 – 稳定与扩展
*   常规系统函数支持 (`$clog2`, `signed'` 等)
*   全面测试与文档
*   可选：Jinja2 模板定制输出风格

---

**附录 A 术语**
*   **Pratt 解析器**：自顶向下运算符优先级解析器
*   **SyntaxRewriter**：slang 提供的语法树重写访问器
*   **IR**：中间表示

**附录 B 参考**
*   pyslang：https://github.com/MikePopoloski/slang
*   MetaHDL 原始项目：https://github.com/himingway/metahdl

---

本文档严格匹配 Slip 语言规范与 SystemVerilog 运算符优先级，所有开发人员须以此为准实现。如有偏离需同步更新文档。
