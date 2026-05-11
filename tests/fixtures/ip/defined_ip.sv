`define DATA_W 32
`define ADDR_W (`DATA_W / 4)

module defined_ip (
    input  logic                  clk,
    input  logic [`ADDR_W-1:0]   addr,
    input  logic [`DATA_W-1:0]   wdata,
    output logic [`DATA_W-1:0]   rdata,
    output logic                  valid
);
    assign rdata = wdata;
    assign valid = 1'b1;
endmodule
