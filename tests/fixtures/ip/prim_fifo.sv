// External IP: simple FIFO with standard bus interface
// This is a SystemVerilog file that Slip needs to reflect
module prim_fifo #(
    parameter int unsigned Depth = 4,
    parameter int unsigned Width = 8
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             wren,
    input  logic [Width-1:0] wdata,
    output logic [Width-1:0] rdata,
    output logic             full,
    output logic             empty
);
    logic [Width-1:0] mem [0:Depth-1];
    logic [$clog2(Depth):0] wr_ptr, rd_ptr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wren && !full) begin
                mem[wr_ptr[$clog2(Depth)-1:0]] <= wdata;
                wr_ptr <= wr_ptr + 1;
            end
        end
    end

    assign rdata = mem[rd_ptr[$clog2(Depth)-1:0]];
    assign full  = (wr_ptr - rd_ptr) == Depth;
    assign empty = (wr_ptr == rd_ptr);
endmodule
