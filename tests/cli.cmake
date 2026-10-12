file(MAKE_DIRECTORY "${WORK_DIR}")
file(WRITE "${WORK_DIR}/valid.slip" "module m(a,y) { logic a; logic y; assign y=a; }\n")
execute_process(COMMAND "${SLIP_BIN}" build "${WORK_DIR}/valid.slip" --strict -o "${WORK_DIR}/rtl"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT EXISTS "${WORK_DIR}/rtl/m.sv")
    message(FATAL_ERROR "CLI build failed: ${result}\n${output}${errors}")
endif()

# The installed compiler needs neither a Python interpreter nor tools on PATH.
execute_process(COMMAND "${CMAKE_COMMAND}" -E env "PATH=" "${SLIP_BIN}" build - --stdout
    INPUT_FILE "${WORK_DIR}/valid.slip"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT output MATCHES "assign y = a;")
    message(FATAL_ERROR "stdin/stdout compilation failed: ${result}\n${output}${errors}")
endif()

file(WRITE "${WORK_DIR}/invalid.slip" "module good(a,y) { assign y=a; } module bad { unknown u {}; }\n")
file(READ "${WORK_DIR}/rtl/m.sv" before)
execute_process(COMMAND "${SLIP_BIN}" build "${WORK_DIR}/invalid.slip" -o "${WORK_DIR}/rtl" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
file(READ "${WORK_DIR}/rtl/m.sv" after)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_MODULE" OR NOT before STREQUAL after
        OR EXISTS "${WORK_DIR}/rtl/good.sv")
    message(FATAL_ERROR "Compilation failure published output or returned invalid diagnostics: ${result}\n${errors}")
endif()

execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/valid.slip" --stdout --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 2 OR NOT code STREQUAL "E_USAGE")
    message(FATAL_ERROR "Invalid CLI arguments did not produce E_USAGE / exit 2: ${errors}")
endif()
