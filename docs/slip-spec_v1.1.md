## Slip 开发者文档 v1.1（更新）

*在 v1.1 中补充了组合逻辑块 `comb` 以及实例化与正则端口映射的完整设计，并对相关章节进行了同步修订。*

---

**全称**：Streamlined Integration Platform  
**状态**：草案  
**面向读者**：项目核心开发人员  
**最后更新**：2026-05-11

---

### 更新说明
1. **新增 `comb` 块**：用于组合逻辑，对应 `always_comb`，块内阻塞赋值不会被转换为非阻塞赋值。
2. **补全实例化与正则端口映射的详细描述**：包含语法、语义分析中的展开算法、对未连接端口的处理规则。
3. 相应调整了 EBNF 语法、AST/IR 节点和代码生成说明。

---

以下为完整文档，已整合全部修改。

---

# Slip 开发者文档 v1.1

**全称**：Streamlined Integration Platform  
**状态**：草案  
**面向读者**：项目核心开发人员  
**最后更新**：2026-05-11

---

## 1. 引言

Slip 是一个极简硬件描述语言 (DSL) 编译器。它定义了一组高度精简的直觉化语法糖，可将硬件设计意图自动编译为高质量、可综合的 SystemVerilog 代码，并利用 `slang` 引擎提供语义验证与 IP 集成。

### 1.1 设计目标
*   **极简源语言**：通过上下文自动推导端口方向、信号类型、实例化连线，只保留硬件本质描述。
*   **严谨代码生成**：采用“片段解析 + SyntaxRewriter”模式，通过 `pyslang` 构建语法树，确保输出代码语法与语义正确。
*   **可靠的元编程**：提供编译期 `#for` / `#if` 展开，严格限制条件为常量或 `param` 标识符，避免前端的复杂求值。
*   **IP 自动集成**：利用 `slang` 反射外部模块端口，支持正则批量端口映射。
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
  ├─ 时序块赋值强制纠正 (seq 块)
  ├─ 实例化连接展开 (含正则批量映射)
  └─ 组合逻辑块识别 (comb 块保持阻塞赋值)
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
*   **关键字**：`module`, `param`, `logic`, `signed`, `assign`, `seq`, `comb`, `pos`, `neg`, `if`, `else`, `for`, `#for`, `#if`, `#else`
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
            | CombBlock
            | IfStmt
            | ForStmt
            | GenForStmt
            | GenIfStmt
            | InstanceStmt
            | BlockStmt

SignalDecl ::= ["logic"] ["signed"] [ "[" Expr "]" ]
               IDENT [ "[" Expr ":" Expr "]" ] ";"

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
*   **`comb` 块**：`comb { … }` 生成 `always_comb begin … end`，块内保留阻塞赋值 `=`，**不进行**非阻塞转换。工具不为其推断敏感列表，完全交给 SystemVerilog 语义。
*   **元编程**：`#for` / `#if` 条件 **仅支持纯整数常量或直接 `param` 引用**。任何运算符、函数调用均禁止，保持常量求值零成本。
*   **实例化与正则端口映射**：详见第 7.2.6 节。

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

class CombBlock(ASTNode):
    body: BlockStmt

class InstanceStmt(ASTNode):
    module_name: str
    params: list[NamedParam]
    inst_name: str
    connections: list[Connection]

class Connection(ASTNode):
    port: Optional[str]          # 显式连接时有效
    signal: Optional[Expr]       # 显式连接时有效
    port_regex: Optional[str]    # 正则映射时有效
    signal_regex: Optional[str]  # 正则映射时有效
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

#### 7.2.4 赋值纠正
*   遍历所有 `SeqBlock`，将其中的阻塞赋值 `=` (非 `assign` 语句) 替换为 `<=`，并产生编译警告。
*   `CombBlock` 内的赋值不做转换，保持为阻塞赋值。

#### 7.2.5 组合逻辑块处理
*   `CombBlock` 直接转为 `LogicBlock` 类型 `always_comb`，内部语句保持不变。

#### 7.2.6 实例化与正则端口映射（详细设计）

实例化语句允许三种端口连接形式，共同构成一个完整的端口映射方案：

1. **显式点名连接**：`.port(signal)`，将实例端口 `port` 连接到当前模块的 `signal` 表达式。
2. **同名自动连接**：`.port`，等价于 `.port(port)`，要求当前模块存在与端口同名的信号。
3. **正则批量映射**：`"regex" => "replacement"`，使用类似 Python `re.sub` 的替换规则，对目标模块的每个端口名应用正则匹配，生成连接的信号名。

**展开算法**（在 AST→IR 过程中执行）：

*输入*：目标模块的端口列表（可通过同设计内已解析的 `HDLModule` 获得，或通过 `slang_integration.reflect_module()` 从外部 SystemVerilog 文件获取）。

*映射优先级*（高到低）：
1. 显式 `.port(signal)`
2. 同名 `.port`
3. 正则映射 `"regex" => "replacement"`（按书写顺序，首个匹配生效）

*具体步骤*：
1. 初始化一个空的端口连接字典 `port_map`。
2. 遍历实例化语句中的 `Connection` 列表：
   - 若是 `.port(signal)`，则 `port_map[port] = signal`。
   - 若是 `.port`，则在当前模块作用域内查找同名信号，若存在则 `port_map[port] = that_signal`；若不存在则报错。
   - 若是正则映射，则暂时存储该规则 (`regex`, `replacement`)。
3. 获取目标模块的完整端口列表（`target_ports`）。
4. 对于每个目标端口 `p`：
   - 如果 `p` 已在 `port_map` 中（通过显式或同名连接），则跳过。
   - 否则，按顺序尝试正则映射规则：用 `re.match(regex, p)` 或 `re.sub(regex, replacement, p)` 生成候选信号名 `cand`。
     - 在作用域内查找 `cand`，如果找到，则将 `port_map[p] = cand` 并停止尝试后续正则规则。
     - 若无匹配的正则或生成的信号不存在，则继续下一条规则。
5. 所有正则尝试完毕后，若端口 `p` 仍未连接：
   - 检查该端口在目标模块中是否有默认值（仅参数？端口无默认值，除非是输入端口且可省略连接）。实际 RTL 中未连接的输入端口将导致综合问题，因此 **对于 `input` / `inout` 端口，必须报错**；对于 `output` 端口，未连接则给出警告（允许悬空输出）。
6. 所有连接确定后，构建 `HDLInstance` 的 `port_map`。

**作用域与隐式信号**：
- 正则映射生成的信号名如果在当前模块中既非显式信号、也非端口，则隐式声明一个新的 `logic` 信号，位宽根据目标端口宽度推断（需要从反射信息中获取端口宽度）。如果无法推断宽度（如外部端口宽度为复杂表达式且不可静态求值），则报错要求用户显式声明该信号。

**示例**：
```
// 外部模块 fifo 端口：wr_en, rd_en, data_in[7:0], data_out[7:0], full, empty
fifo #(.DEPTH(16)) buf1 {
    .wr_en,
    .rd_en,
    "data_(.*)" => "fifo_\1",
    .full, .empty
}
```
反射得到 fifo 端口列表，按规则：
- `wr_en` 已在连接列表中通过 `.wr_en` 建立同名连接。
- `rd_en` 同上。
- `data_in` 未显式连接，尝试正则：`re.sub("data_(.*)", "fifo_\1", "data_in")` → `fifo_in`，查找作用域是否存在 `fifo_in`，若不存在且无法推断位宽则报错；若能从反射中知 `data_in` 宽度为 `[7:0]`，则隐式创建 `logic [7:0] fifo_in`，并连接。
- `data_out` 同理映射到 `fifo_out`。
- `full`、`empty` 显式同名连接。

**错误情况**：
- 目标模块端口未连接且为输入 → `SlipSemanticError: unconnected input port 'port_name'`.
- 正则映射产生了信号名但与已有信号宽度不匹配 → 报错。
- 正则匹配失败且无同名/显式连接 → 同上。

---

## 8. 代码生成（片段解析 + SyntaxRewriter）

策略同前，在片段生成时另行处理：

*   `SeqBlock` → 生成 `always_ff @(...) begin ... end`，内部赋值已转为 `<=`。
*   `CombBlock` → 生成 `always_comb begin ... end`，内部保留 `=`。
*   `Instance` → 根据 `port_map` 生成 `.port(signal)` 列表。

---

## 9. Slang 集成层

### 9.1 IP 反射
`slang_integration.reflect_module(sv_path, module_name)` 返回外部模块的端口列表（名称、方向、宽度、是否 signed）。用于实例化正则映射时的端口枚举和宽度推断。

---

## 10. 命令行接口

```
slip build [-o <out_dir>] [-ip <ip_dirs>] <file.slip>
slip check [-ip <ip_dirs>] <file.slip>
```

---

## 11. 错误处理

同前，所有异常继承自 `SlipError`。

---

## 12. 测试策略

新增针对实例化正则映射、`comb` 块的单元测试与集成测试。

---

## 13. 开发路线图

已包含上述功能到对应 Phase。

---

**附录**：示例与术语保持不变。

---

文档已全面更新，填补了实例化与正则端口映射的设计空白，并加入了组合逻辑块 `comb`。开发者可据此进入具体实现阶段。
