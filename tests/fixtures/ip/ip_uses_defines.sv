// Module that uses defines from ip_def_base.sv
// Requires defines to be processed first
module ip_uses_defines (
    input  logic [`DATA_WIDTH-1:0] data_in,
    output logic [`DATA_WIDTH-1:0] data_out,
    input  logic [`ADDR_WIDTH-1:0] addr
);
    assign data_out = data_in;
endmodule
