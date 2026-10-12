module reference(input logic clk, rst_n, input logic [15:0] din,
                 output logic [15:0] dout);
    logic [15:0] s0, s1, s2;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin s0<=0; s1<=0; s2<=0; end
        else begin s0<=din; s1<=s0; s2<=s1; end
    end
    assign dout=s2;
endmodule
module tb;
    logic clk=0, rst_n=0;
    logic [15:0] din=0, got, expected;
    logic [7:0] y, narrow;
    logic [15:0] wide;
    top dut(.clk, .rst_n, .din, .dout(got));
    reference ref_dut(.clk, .rst_n, .din, .dout(expected));
    arithmetic arithmetic_dut(.y, .narrow, .wide);
    initial begin
        for (int cycle=0; cycle<128; cycle++) begin
            clk=0;
            rst_n=(cycle>=2 && cycle!=41 && cycle!=79);
            din=16'((cycle*7919) ^ 16'hf0a5);
            #5; clk=1; #5;
            if (got !== expected) $fatal(1,"pipeline mismatch at cycle %0d",cycle);
            if (y !== 8'd1 || narrow !== 8'd0 || wide !== 16'd128)
                $fatal(1,"context-sensitive arithmetic mismatch");
        end
        $display("PASS: 128 cycles, resets, 16-bit data, arithmetic contexts");
        $finish;
    end
endmodule
