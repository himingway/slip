# RTL 功能扩展

完整示例位于 [examples/features](../examples/features/slip.conf)：

```bash
build/release/slip check --project examples/features/slip.conf
build/release/slip inspect --project examples/features/slip.conf
```

## 数据拆分、取片、数组与时钟

```slip
assign {hi, lo} = data;        // 拼接左值，各部分分别参与驱动检查
assign byte = word[offset +: 8];
assign word[15 -: 8] = byte;
logic [7:0] memory [0:3][0:15];

seq (neg: clk, neg: rst_n) {
    if (!rst_n) { q = 0; }
    else { q = d; }
}
```

取片宽度遵循 SV 常量规则，起点可以是运行时表达式；越界和宽度错误交给 slang 校验。
数组可以有多个非压缩维度。左值支持标识符、结构体字段、下标、切片及其拼接。
重叠的连续赋值和实例驱动仍会报错，动态下标按保守规则检查。
`seq(clk)` 使用上升沿，也可显式写 `seq(pos:clk)`；复位边沿独立指定。
同步复位继续使用 `seq(clk)` 内的条件赋值。

## 枚举、类型别名和结构体

```slip
typedef enum logic [1:0] { IDLE, RUN = 2, DONE } state_t;
typedef logic [7:0] byte_t;
typedef struct packed {
    byte_t data;
    logic valid;
} packet_t;

module decode(clk, input_packet, output_packet) {
    logic clk;
    input packet_t input_packet;
    output packet_t output_packet;
    state_t state;
    assign output_packet.data = input_packet.data;
    assign output_packet.valid = input_packet.valid;
}
```

`typedef` 可位于顶层或模块体；跨模块共享的类型放在顶层或被 include 的文件中。
顶层类型在各模块内定义。使用自定义端口类型时生成非 ANSI 端口声明，以保持类型作用域。
结构体支持 packed 数据字段和嵌套的已声明类型；不同字段会参与独立的驱动和反馈检查。
也可写 `enum [1:0] { IDLE, RUN } state;` 创建匿名类型变量。
省略枚举基类型时采用 SV 的 `int`，未指定的枚举值从前一个值递增。

可选的 `input` / `output` / `inout` 放在信号声明上；端口名称仍列在模块头中。
未指定方向时继续推断，显式输入被内部逻辑或实例输出驱动时报 `E_DIRECTION`。
显式单比特声明保留单比特类型，连接较宽端口时报告位宽不匹配。

## 按实例生成不同的结构

```slip
module top(a, b) {
    logic [1:0] a;
    logic [3:0] b;
    generated #(.N(2)) small_instance { .y(a) };
    generated #(.N(4)) large_instance { .y(b) };
}
```

当 `N` 参与 Slip 生成循环或条件时，每组不同的生成参数创建独立模块。
相同参数组合复用模块，名字由模块名和参数绑定确定；实例的生成参数连接被消除。
参数依赖和嵌套封装同样传播，包括函数内部的生成控制。父参数用于配置子模块结构时，
父参数也固定为本次生成值，生成的 SV 保留防止后续不一致覆盖的检查。
只影响普通 RTL 的参数继续保留 SV 参数覆盖。

生成控制及其覆盖值必须可在调用方常量环境中求值，并符合原有有符号 64 位范围。
模板默认配置也会编译和校验。单次编译最多创建 1,024 个参数特化，依赖深度上限为 128。

## 总线分组

```slip
bundle Stream #(param W = 8) {
    output logic [W-1:0] data;
    output logic valid;
    input logic ready;
}

module passthrough(rx, tx) {
    slave Stream #(.W(16)) rx;
    master Stream #(.W(16)) tx;
    assign tx.data = rx.data;
    assign tx.valid = rx.valid;
    assign rx.ready = tx.ready;
}
```

Schema 中的方向以 master 为视角，slave 反转方向。
作为模块端口的分组必须出现在端口列表中，并声明 master 或 slave。
内部中性连线使用 `bus Stream link;`。字段展开为 `link_data`、`link_valid` 等普通 SV 信号，
不引入原生 SV interface；生成文件可直接接入现有的普通模块工具链。

连接实例时，`.rx(link)` 展开整组连接；同名简写 `.rx` 也可连接同名分组。
连接要求分组已声明、schema 相同且字段一致，位宽仍经过完整 SV 校验。
显式字段连接与正则连接可继续使用。重复字段、未知参数、未知字段和方向冲突会报错。
重复驱动及未驱动字段沿用已有检查；`--strict` 将位宽不匹配升级为错误。

## 可综合函数

```slip
function [7:0] invert(logic [7:0] x) {
    logic [7:0] tmp;
    tmp = ~x;
    if (x == 0) { return 8'hff; }
    else { return tmp; }
}
module example(a, y) {
    logic [7:0] a;
    logic [7:0] y;
    assign y = invert(a);
}
```

函数可在顶层或模块内定义，生成 `function automatic`。
返回类型支持 logic、bit、int、自定义类型和位宽；省略返回类型时为单比特 logic。
参数为输入值，函数支持局部变量、类型、常量、if/case/for、生成循环、断言和 return。
函数只可引用参数、局部名称和模块常量，要求阻塞赋值及所有控制路径返回值，不允许时钟过程和实例。
局部名称不会变成模块端口。外部信号依赖或状态性语句报 `E_FUNCTION`。
原有 `defun` 的生成阶段行为保持独立。

## 断言

```slip
module control #(param DEPTH = 8) (clk, valid) {
    logic clk; logic valid;
    static_assert(DEPTH > 0, "DEPTH must be positive");
    seq(clk) { assert(valid, "valid required"); }
}
```

`static_assert` 位于模块层，在编译时检查，并保留生成 SV 的展开期检查，
因此普通参数在实例覆盖后也必须满足约束。条件支持常量算术、模块常量及可求值的 RTL 函数。
违反直接求值约束报告 `E_ASSERT`，由 SV 展开发现的约束错误报告 `E_SV`。
`assert` 位于过程或函数内，生成立即断言及失败时的 `$error`。
消息可省略，运行时检查需在下游仿真工具中启用断言，例如 Verilator 的 `--assert`。

## 外部 IP 与检查结果

外部源码先做语法解析和定义索引；仅对 Slip 实际实例化的模块反射参数与端口。
未使用的模块含有类型参数或原生 interface 端口，不再仅因反射边界阻断整个 IP 目录。
真正连接到 Slip 的模块若使用类型参数，会给出明确的 `E_IP`。
原生 interface 支持参数化实例、modport、整组直连和字段访问，详见
[原生 interface 说明](native-interfaces.md)。外部文件的语法错误、实际设计的语义错误仍会报告。

`inspect` 显示分组及字段，JSON 增加 `bundles` 数组与信号的 `type` 字段。
`width` 表示声明或推断出的 packed 范围；自定义类型或 int 的空范围不表示单比特，
实际类型大小由 SV 类型决定。连接来源 `bundle` 表示由分组连接展开。

测试包括独立 RTL/算术模型的 160 周期组合功能仿真、故意输入非法值时的运行时断言失败检查，以及上述功能的正、反例回归。
