module delay_check #(parameter W=8,D=3)(output logic finished=0);
    logic clk=0,rst_n=0,enable=0;
    logic [W-1:0] din=0,dout,expected=0;
    logic [W-1:0] history[0:D-1];
    int cursor=0;
    delay #(.WIDTH(W),.DEPTH(D)) dut(.*);
    initial begin
        for(int cycle=0;cycle<256;cycle++) begin
            clk=0;
            rst_n=(cycle>=2 && cycle!=37 && cycle!=113);
            enable=(cycle%5!=0);
            din=W'((cycle*7919)^32'hcafe1234);
            #2;
            if(!rst_n && dout !== 0) $fatal(1,"array asynchronous reset W=%0d D=%0d",W,D);
            clk=1; #2;
            // Circular history differs from the generated shift-register structure.
            if(!rst_n) begin
                foreach(history[i]) history[i]=0;
                cursor=0; expected=0;
            end else if(enable) begin
                history[cursor]=din;
                cursor=(cursor+1)%D;
                expected=history[cursor];
            end
            if(dout !== expected) $fatal(1,"array mismatch W=%0d D=%0d cycle=%0d",W,D,cycle);
        end
        finished=1;
    end
endmodule
module tb;
    logic a,b,c;
    delay_check #(.W(3),.D(1)) narrow_case(.finished(a));
    delay_check #(.W(8),.D(3)) default_case(.finished(b));
    delay_check #(.W(16),.D(5)) wide_case(.finished(c));
    initial begin
        wait(a && b && c);
        $display("PASS: 256 cycles each, arrays W=3/8/16 D=1/3/5, stalls and resets");
        $finish;
    end
endmodule
