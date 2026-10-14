file(MAKE_DIRECTORY "${WORK_DIR}")
execute_process(COMMAND "${SLIP_BIN}" build "${SOURCE_DIR}/design.slip" -o "${WORK_DIR}/rtl"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Behavioral fixture failed to compile: ${result}\n${output}${errors}")
endif()
file(GLOB sources "${WORK_DIR}/rtl/*.sv")
execute_process(COMMAND "${VERILATOR}" --binary --timing --assert -Wno-fatal --top-module tb
    --Mdir "${WORK_DIR}/obj" ${sources} "${SOURCE_DIR}/tb.sv"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 150)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Verilator build failed: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${WORK_DIR}/obj/Vtb"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT output MATCHES "PASS:")
    message(FATAL_ERROR "Independent RTL comparison failed: ${result}\n${output}${errors}")
endif()
if(CASE_NAME STREQUAL "features")
    execute_process(COMMAND "${WORK_DIR}/obj/Vtb" +fail_assert
        RESULT_VARIABLE assertion_result OUTPUT_VARIABLE assertion_output ERROR_VARIABLE assertion_errors TIMEOUT 15)
    if(assertion_result EQUAL 0 OR NOT "${assertion_output}${assertion_errors}" MATCHES "slice exceeds data width")
        message(FATAL_ERROR "Runtime assertion did not reject invalid input: ${assertion_result}\n${assertion_output}${assertion_errors}")
    endif()
endif()

message(STATUS "${output}")
