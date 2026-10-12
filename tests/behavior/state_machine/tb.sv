module tb;
    logic clk=0,rst_n=0,start=0,ack=0,busy,done;
    logic [1:0] phase;
    int model_phase=0,deadline=0;
    int idle_samples=0,active_samples=0,done_samples=0;
    controller dut(.*);
    initial begin
        for(int cycle=0;cycle<256;cycle++) begin
            clk=0;
            rst_n=(cycle>=2 && cycle!=27 && cycle!=73 && cycle!=155);
            start=(cycle%9==0);
            ack=(cycle%7==0);
            #2;
            if(!rst_n && phase !== 0) $fatal(1,"asynchronous reset mismatch %0d",cycle);
            clk=1; #2;
            // A timestamp model is independent of the DUT's countdown register.
            if(!rst_n) model_phase=0;
            else if(model_phase==0 && start) begin model_phase=1; deadline=cycle+4; end
            else if(model_phase==1 && cycle>=deadline) model_phase=2;
            else if(model_phase==2 && ack) model_phase=0;
            if(phase !== 2'(model_phase) || busy !== (model_phase==1) || done !== (model_phase==2))
                $fatal(1,"state machine mismatch %0d: got phase=%0d expected=%0d",cycle,phase,model_phase);
            if(model_phase==0) idle_samples++;
            if(model_phase==1) active_samples++;
            if(model_phase==2) done_samples++;
        end
        if(idle_samples==0 || active_samples==0 || done_samples==0) $fatal(1,"missing state coverage");
        $display("PASS: 256 state machine cycles, all phases, start/ack and asynchronous resets");
        $finish;
    end
endmodule
