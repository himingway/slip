// External IP: parameterized output buffer with tri-state
module prim_obuf #(
    parameter int Width = 1
) (
    input  logic             oe,
    input  logic [Width-1:0] din,
    output logic [Width-1:0] dout
);
    assign dout = oe ? din : 'z;
endmodule
