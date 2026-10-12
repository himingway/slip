module tb;
    logic signed [7:0] a,b,shifted;
    logic [1:0] sel;
    logic [8:0] sum;
    logic less,parity;
    logic [7:0] muxed,expected_mux;
    int signed_a,signed_b,unsigned_a,unsigned_b;
    bit expected_parity;
    combo dut(.*);
    initial begin
        for(int sample=0;sample<1024;sample++) begin
            a=8'(sample*73+129);
            b=8'(sample*29+sample/7);
            sel=2'(sample/5);
            #1;
            signed_a=$signed(a); signed_b=$signed(b);
            unsigned_a=$unsigned(a); unsigned_b=$unsigned(b);
            if(sum !== 9'(unsigned_a+unsigned_b)) $fatal(1,"carry mismatch %0d",sample);
            if(shifted !== 8'(signed_a >>> sel)) $fatal(1,"signed shift mismatch %0d",sample);
            if(less !== (signed_a<signed_b)) $fatal(1,"signed comparison mismatch %0d",sample);
            expected_parity=0;
            for(int bit_index=0;bit_index<8;bit_index++)
                if(a[bit_index]) expected_parity=!expected_parity;
            if(parity !== expected_parity) $fatal(1,"parity mismatch %0d",sample);
            if(sel==3) expected_mux=8'(255-unsigned_a);
            else if(sel==2) expected_mux=a^b;
            else if(sel==1) expected_mux=b;
            else expected_mux=a;
            if(muxed !== expected_mux) $fatal(1,"case mux mismatch %0d",sample);
        end
        $display("PASS: 1024 combinational samples, carry, signed shifts, comparisons, parity and case");
        $finish;
    end
endmodule
