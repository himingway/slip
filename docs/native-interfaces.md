# 原生 SystemVerilog interface

Slip 可以直接连接外部 SV 定义的 interface。定义通过 `-ip`、`-f` 或项目配置加载；
输出保留真实的 interface 实例和端口，交给 slang 做完整的 SV 类型、参数和位宽校验。
现有 `bundle` 仍用于展开成普通信号端口，两者不做隐式转换。

## 定义与实例

例如外部 `stream.sv`：

```systemverilog
interface Stream #(parameter int W = 8) (input logic clk, rst_n);
    logic [W-1:0] data;
    logic valid, ready;
    modport master(input clk, rst_n, ready, output data, valid);
    modport slave(input clk, rst_n, data, valid, output ready);
endinterface
```

Slip 内部声明及其生成结果：

```slip
interface Stream #(.W(16)) link { .clk(clk), .rst_n(rst_n) };
```

```systemverilog
Stream #(.W(16)) link (.clk(clk), .rst_n(rst_n));
```

无构造端口时可直接写 `interface Stream link;`；构造连接支持 `.clk` 同名简写。
参数覆盖使用命名参数；未知参数、重复覆盖及覆盖 localparam 均报错。
构造端口采用普通实例连接的检查规则，完整输出会再经过 SV 展开校验。

## 模块端口和字段

```slip
module producer(tx, data, enable) {
    interface Stream.master tx;
    logic [7:0] data;
    logic enable;
    seq (tx.clk, neg: tx.rst_n) {
        if (!tx.rst_n) {
            tx.data = '0;
            tx.valid = 1'b0;
        } else if (tx.ready) {
            tx.data = data;
            tx.valid = enable;
        }
    }
}
```

Slip 的 interface 端口必须出现在模块头的端口列表中，并指定 modport。
端口的 interface 参数及构造连接由调用方的实际实例决定，不能在端口声明上重新指定。
内部实例的声明不带 modport；在连接处可选择视图。

字段可用于连续赋值、组合和时序过程、取片、数组下标及结构体成员访问。
时钟和复位也可写为 interface 字段。未知字段及 modport 未公开的字段报 `E_INTERFACE`，
给 input 字段赋值或用实例输出驱动它报 `E_DIRECTION`。
不同字段分别跟踪驱动；重叠驱动报 `E_MULTIPLE_DRIVERS`。
位宽以实际连接的 SV 类型为准，`--strict` 将位宽不匹配升级为错误。

## 整组连接

```slip
producer source { .tx(link), .data, .enable };
stream_sink sink { .bus(link.slave), .observed };
```

支持连接 Slip 模块及外部 SV 模块的 interface 端口；也支持 `.tx` 同名简写。
实际连接必须是已声明的 interface 实例或 interface 端口，类型必须匹配。
未连接的 interface 端口（包括显式 `_`）报错。
显式选择的 modport 必须与目标端口要求一致。
转接已有 modport 端口时保留同一视图，防止绕过输入方向或扩大字段访问权限。
外部 SV 的未指定 modport 端口可连接内部实例；不指定视图时按双向连接处理。

interface 端口没有独立的固定数据位宽；例如连接到 `Stream #(.W(16))` 后，
端口内的 `tx.data` 就是 16 位。需要与模块参数一致时，可用
`static_assert($bits(tx.data) == W);` 显式约束。

## inspect

文本输出列出 interface 类型、modport、实例/端口身份及可访问字段。
JSON 增加模块级 `interfaces` 数组，包含 `name`、`type`、`modport`、`port`、
`parameters`、`fields` 和 `location`。字段同时作为带点号的信号出现在 `signals` 中，
用于显示驱动方向；这些检查用的信号不会重复生成声明。
字段类型使用 `type(实例.字段)` 保留对实际 SV 类型的引用；`width` 使用
`$bits(实例.字段)` 表示实际字段的总位数，包含数组全部元素。
整组连接的来源标为 `interface`。

## 范围

当前支持顶层声明的数据字段，以及由 input/output/inout 数据字段组成的 modport。
支持 interface 实例/端口数组（包括多维数组）、值参数和类型参数。
暂不支持嵌套 interface、clocking、
modport 表达式/重命名字段、ref 字段及 import/export task/function。
未使用的复杂 modport 不阻断其他受支持视图；实际使用时会给出明确诊断。

完整的参数化示例位于 [examples/native-interface](../examples/native-interface/design.slip)：

```bash
build/release/slip check --project examples/native-interface/slip.conf
build/release/slip build --project examples/native-interface/slip.conf
build/release/slip inspect --project examples/native-interface/slip.conf --format=json
```

下游工具需要同时读取生成的模块和外部 interface/IP 源码。

## 数组、package 类型和类型参数

```slip
interface Stream #(.T(types::packet_t)) links[0:N-1];
producer #(.N(N)) source { .links };
consumer sink { .link(links[0]) };
```

接口端口声明可写 `interface Stream.source links[0:N-1];`。
整组连接检查每一维大小，元素连接和字段读写仍检查 modport 方向与多驱动。
数组下标必须是编译时常量；生成循环可以展开下标。数组维度参与生成参数冻结，
按实例的不同尺寸创建特化；元素和字段展开受 `max_expanded_statements` 约束。

外部 package 类型直接使用 `types::packet_t`，常量和函数也可使用限定名称。
Slip 模块类型参数写作 `param type T = logic [7:0]`，实例覆盖使用
`.T(types::packet_t)` 或 `.T(logic [15:0])`。普通 RTL 类型参数保留为 SV 参数；
参与生成控制的类型参数按绑定特化，并保留 `$typename` 冻结检查。
推断连接类型时保留具名类型与类型参数绑定，而非只继承默认位宽。

端口类型在模块头可见时生成 ANSI 声明；依赖模块内 typedef 的端口采用非 ANSI 声明。
支持 `(* keep = "true" *)` 等 SV 属性，应用于模块、信号、实例和过程块。
完整的 package、类型参数、数组与属性示例见 [examples/interop](../examples/interop/slip.conf)。
