module tb;
    logic clk=0, rst_n=0;
    logic [7:0] din=0, short_out, long_out, bus_out, packet;
    logic [2:0] base=0;
    logic [3:0] hi,lo,selected;
    logic active;
    logic [7:0] history0=0,history1=0;
    logic [7:0] expected_swap, expected_short, expected_long;
    features dut(.*);
    initial begin
        for (int cycle=0; cycle<160; cycle++) begin
            clk=1;
            rst_n=(cycle>=2 && cycle!=39 && cycle!=91);
            din=8'((cycle*73)^8'ha5);
            base=3'(cycle%5);
            if ($test$plusargs("fail_assert") && cycle==7) base=7;
            expected_swap={din[3:0],din[7:4]};
            expected_short=rst_n ? history0 : 0;
            expected_long=rst_n ? history1 : 0;
            #3; clk=0; #3;
            if ({hi,lo} !== expected_swap) $fatal(1,"function, struct or concatenation mismatch %0d",cycle);
            if (selected !== 4'(din >> base)) $fatal(1,"indexed select mismatch %0d",cycle);
            if (packet !== din) $fatal(1,"typed port mismatch %0d",cycle);
            if (bus_out !== din) $fatal(1,"bundle mismatch %0d",cycle);
            if (active !== (rst_n && din[0])) $fatal(1,"enum state mismatch %0d",cycle);
            if (short_out !== expected_short || long_out !== expected_long)
                $fatal(1,"specialized falling-edge pipeline mismatch %0d: %h %h / %h %h",cycle,short_out,expected_short,long_out,expected_long);
            if (!rst_n) begin history0=0; history1=0; end
            else begin history1=history0; history0=expected_swap; end
        end
        $display("PASS: 160 cycles, bundles, typed ports, structs, enums, functions, arrays, indexed selects and specialized falling-edge pipelines");
        $finish;
    end
endmodule
