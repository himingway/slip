cmake_minimum_required(VERSION 3.24)
file(MAKE_DIRECTORY "${WORK_DIR}")
execute_process(COMMAND "${SLIP_BIN}" build --project "${SOURCE_DIR}/examples/interop/slip.conf" --profile four -o "${WORK_DIR}/rtl"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 30)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Interop generation failed: ${result}\n${output}${errors}")
endif()
file(WRITE "${WORK_DIR}/tb.sv" [=[
module tb;
    types::packet_t a, y, z;
    top dut(.a(a), .y(y), .z(z));
    initial begin
        for (int i=0; i<256; i++) begin
            a.data = 8'(i);
            a.valid = 1'(i);
            #1;
            if (y !== a || z !== a) $fatal(1, "interface array or type parameter mismatch at %0d", i);
        end
        $finish;
    end
endmodule
]=])
execute_process(COMMAND "${VERILATOR}" --binary --timing --top-module tb -Wno-fatal
    -f "${WORK_DIR}/rtl/sources.f" "${WORK_DIR}/tb.sv" --Mdir "${WORK_DIR}/obj" -o sim
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 120)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Verilator interop build failed: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${WORK_DIR}/obj/sim" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Interop simulation failed: ${result}\n${output}${errors}")
endif()
