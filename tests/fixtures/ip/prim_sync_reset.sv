// External IP: synchronous reset converter
// Converts async reset to synchronized reset output
module prim_sync_reset (
    input  logic clk,
    input  logic rst_n_async,
    output logic rst_n_sync
);
    logic rst_n_d0, rst_n_d1;

    always_ff @(posedge clk or negedge rst_n_async) begin
        if (!rst_n_async) begin
            rst_n_d0  <= 1'b0;
            rst_n_d1  <= 1'b0;
            rst_n_sync <= 1'b0;
        end else begin
            rst_n_d0   <= 1'b1;
            rst_n_d1   <= rst_n_d0;
            rst_n_sync <= rst_n_d1;
        end
    end
endmodule
