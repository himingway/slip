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

file(WRITE "${WORK_DIR}/not-a-directory" "occupied\n")
execute_process(COMMAND "${SLIP_BIN}" build "${WORK_DIR}/valid.slip" -o "${WORK_DIR}/not-a-directory" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON file GET "${errors}" file)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_IO" OR NOT file STREQUAL "${WORK_DIR}/not-a-directory")
    message(FATAL_ERROR "Invalid output directory should report E_IO at its path: ${result}\n${errors}")
endif()

file(MAKE_DIRECTORY "${WORK_DIR}/partial-output/z.sv")
file(WRITE "${WORK_DIR}/two-modules.slip" "module a {} module z {}\n")
execute_process(COMMAND "${SLIP_BIN}" build "${WORK_DIR}/two-modules.slip" -o "${WORK_DIR}/partial-output" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON file GET "${errors}" file)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_IO" OR NOT file STREQUAL "${WORK_DIR}/partial-output/z.sv"
        OR EXISTS "${WORK_DIR}/partial-output/a.sv")
    message(FATAL_ERROR "Output target conflicts should fail before publishing any module: ${result}\n${errors}")
endif()

set(quoted_input "${WORK_DIR}/quote\"name.slip")
file(WRITE "${quoted_input}" "module m {\n    assign y=;\n}\n")
execute_process(COMMAND "${SLIP_BIN}" check "${quoted_input}" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON file GET "${errors}" file)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_PARSE" OR NOT file STREQUAL "${quoted_input}")
    message(FATAL_ERROR "JSON diagnostics should escape quotes in source paths: ${result}\n${errors}")
endif()

file(WRITE "${WORK_DIR}/warning.slip" "module m(a,y) { logic [15:0] a; logic [7:0] y; assign y=a; }\n")
execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/warning.slip" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON severity GET "${errors}" severity)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 0 OR NOT severity STREQUAL "warning" OR NOT code STREQUAL "W_WIDTH")
    message(FATAL_ERROR "Width warnings should use valid JSON diagnostics: ${result}\n${errors}")
endif()

execute_process(COMMAND "${SLIP_BIN}" build --diagnostics=json --out-dir
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 2 OR NOT code STREQUAL "E_USAGE")
    message(FATAL_ERROR "Missing option values should report E_USAGE / exit 2: ${result}\n${errors}")
endif()

execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/valid.slip" --stdout --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 2 OR NOT code STREQUAL "E_USAGE")
    message(FATAL_ERROR "check --stdout should report E_USAGE / exit 2: ${result}\n${errors}")
endif()
