# Golden SDC file for testing
create_clock -name core_clk -period 10.0 [get_ports clk]
set_false_path -from [get_ports reset]
set_false_path -from [get_ports test_mode]
set_multicycle_path -setup 2 -from [get_ports data_in]
set_max_delay 5.0 -from [get_ports data_in] -to [get_ports data_out]
set_clock_uncertainty 0.1 [get_clocks core_clk]
