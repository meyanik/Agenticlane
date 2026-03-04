create_clock -name clk -period 24.0 [get_ports {clk}]
set_input_delay -clock clk 4.0 [all_inputs]
set_output_delay -clock clk 4.0 [all_outputs]
