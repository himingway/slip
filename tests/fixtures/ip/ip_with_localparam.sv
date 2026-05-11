module ip_with_localparam #(
    parameter int WIDTH = 8,
    localparam int HALF_W = WIDTH / 2
)(
    input  logic              clk,
    input  logic [WIDTH-1:0]  din,
    output logic [HALF_W-1:0] dout,
    output logic              valid
);
    assign dout = din[HALF_W-1:0];
    assign valid = 1'b1;
endmodule
