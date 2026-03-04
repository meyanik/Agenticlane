// 8-bit synchronous counter with async reset
// Synthesizable Verilog for AgenticLane example design

module counter (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    output reg  [7:0] count
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 8'b0;
        end else if (en) begin
            count <= count + 8'b1;
        end
    end

endmodule
