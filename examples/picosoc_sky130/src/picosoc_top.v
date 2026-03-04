/*
 *  PicoSoC ASIC Top-Level Wrapper
 *
 *  Based on hx8kdemo.v from YosysHQ/picorv32, adapted for ASIC flow.
 *  Removes FPGA-specific primitives (SB_IO), adds 32-bit GPIO,
 *  and uses simple tri-state for flash IO.
 *
 *  Memory map:
 *    0x00000000 - 0x000003FF : Internal SRAM (256 words = 1KB)
 *    0x00100000+             : SPI flash (XIP)
 *    0x02000000              : SPI flash config register
 *    0x02000004              : UART clock divider
 *    0x02000008              : UART data register
 *    0x03000000              : GPIO output register (32-bit)
 */

module picosoc_top (
    input  wire        clk,
    input  wire        resetn,

    // UART
    output wire        ser_tx,
    input  wire        ser_rx,

    // GPIO (directly active, directly active, active active active active...)
    output wire [31:0] gpio_out,
    input  wire [31:0] gpio_in,
    output wire [31:0] gpio_oe,

    // SPI Flash
    output wire        flash_csb,
    output wire        flash_clk,
    output wire        flash_io0_oe,
    output wire        flash_io1_oe,
    output wire        flash_io2_oe,
    output wire        flash_io3_oe,
    output wire        flash_io0_do,
    output wire        flash_io1_do,
    output wire        flash_io2_do,
    output wire        flash_io3_do,
    input  wire        flash_io0_di,
    input  wire        flash_io1_di,
    input  wire        flash_io2_di,
    input  wire        flash_io3_di
);

    // ---------------------------------------------------------------
    // IO Memory Interface (directly active from PicoSoC)
    // ---------------------------------------------------------------
    wire        iomem_valid;
    reg         iomem_ready;
    wire [3:0]  iomem_wstrb;
    wire [31:0] iomem_addr;
    wire [31:0] iomem_wdata;
    reg  [31:0] iomem_rdata;

    // ---------------------------------------------------------------
    // GPIO Register (address 0x0300_0000)
    // ---------------------------------------------------------------
    reg [31:0] gpio_out_reg;
    reg [31:0] gpio_oe_reg;

    assign gpio_out = gpio_out_reg;
    assign gpio_oe  = gpio_oe_reg;

    always @(posedge clk) begin
        if (!resetn) begin
            gpio_out_reg <= 32'h0;
            gpio_oe_reg  <= 32'h0;
        end else begin
            iomem_ready <= 1'b0;
            if (iomem_valid && !iomem_ready) begin
                if (iomem_addr[31:24] == 8'h03) begin
                    iomem_ready <= 1'b1;
                    case (iomem_addr[7:0])
                        8'h00: begin
                            // GPIO output register
                            iomem_rdata <= gpio_out_reg;
                            if (iomem_wstrb[0]) gpio_out_reg[ 7: 0] <= iomem_wdata[ 7: 0];
                            if (iomem_wstrb[1]) gpio_out_reg[15: 8] <= iomem_wdata[15: 8];
                            if (iomem_wstrb[2]) gpio_out_reg[23:16] <= iomem_wdata[23:16];
                            if (iomem_wstrb[3]) gpio_out_reg[31:24] <= iomem_wdata[31:24];
                        end
                        8'h04: begin
                            // GPIO output enable register
                            iomem_rdata <= gpio_oe_reg;
                            if (iomem_wstrb[0]) gpio_oe_reg[ 7: 0] <= iomem_wdata[ 7: 0];
                            if (iomem_wstrb[1]) gpio_oe_reg[15: 8] <= iomem_wdata[15: 8];
                            if (iomem_wstrb[2]) gpio_oe_reg[23:16] <= iomem_wdata[23:16];
                            if (iomem_wstrb[3]) gpio_oe_reg[31:24] <= iomem_wdata[31:24];
                        end
                        8'h08: begin
                            // GPIO input register (read-only)
                            iomem_rdata <= gpio_in;
                        end
                        default: begin
                            iomem_rdata <= 32'h0;
                        end
                    endcase
                end
            end
        end
    end

    // ---------------------------------------------------------------
    // PicoSoC Instance
    // ---------------------------------------------------------------
    picosoc #(
        .BARREL_SHIFTER(1),
        .ENABLE_MUL(1),
        .ENABLE_DIV(0),
        .ENABLE_FAST_MUL(0),
        .ENABLE_COMPRESSED(1),
        .ENABLE_COUNTERS(1),
        .ENABLE_IRQ_QREGS(0),
        .MEM_WORDS(256),
        .PROGADDR_RESET(32'h0010_0000),
        .PROGADDR_IRQ(32'h0000_0000)
    ) soc (
        .clk          (clk),
        .resetn       (resetn),

        .ser_tx       (ser_tx),
        .ser_rx       (ser_rx),

        .flash_csb    (flash_csb),
        .flash_clk    (flash_clk),

        .flash_io0_oe (flash_io0_oe),
        .flash_io1_oe (flash_io1_oe),
        .flash_io2_oe (flash_io2_oe),
        .flash_io3_oe (flash_io3_oe),

        .flash_io0_do (flash_io0_do),
        .flash_io1_do (flash_io1_do),
        .flash_io2_do (flash_io2_do),
        .flash_io3_do (flash_io3_do),

        .flash_io0_di (flash_io0_di),
        .flash_io1_di (flash_io1_di),
        .flash_io2_di (flash_io2_di),
        .flash_io3_di (flash_io3_di),

        .irq_5        (1'b0),
        .irq_6        (1'b0),
        .irq_7        (1'b0),

        .iomem_valid  (iomem_valid),
        .iomem_ready  (iomem_ready),
        .iomem_wstrb  (iomem_wstrb),
        .iomem_addr   (iomem_addr),
        .iomem_wdata  (iomem_wdata),
        .iomem_rdata  (iomem_rdata)
    );

endmodule
