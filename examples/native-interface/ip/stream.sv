interface Stream #(parameter int W = 8) (input logic clk, rst_n);
    logic [W-1:0] data;
    logic valid, ready;
    modport master(input clk, rst_n, ready, output data, valid);
    modport slave(input clk, rst_n, data, valid, output ready);
endinterface

module stream_sink #(parameter int W = 8) (
    Stream.slave bus,
    output logic [W-1:0] observed
);
    assign bus.ready = 1'b1;
    assign observed = bus.valid ? bus.data : '0;
    if ($bits(bus.data) != W) begin : width_check
        $error("stream_sink W must match its interface data width");
    end
endmodule
