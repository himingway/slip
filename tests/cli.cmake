cmake_minimum_required(VERSION 3.24)

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

# Inspection is structured independently of diagnostics and publishes no RTL.
file(WRITE "${WORK_DIR}/inspect.slip"
    "module top(bus_a,bus_y) { leaf #(.W(16)) u { \"data_(.*)\" => \"bus_\\1\" }; }\nmodule leaf #(param W=8)(data_a,data_y) { logic [W-1:0] data_a; logic [W-1:0] data_y; assign data_y=data_a; }\n")
file(MAKE_DIRECTORY "${WORK_DIR}/inspection-only")
execute_process(COMMAND "${SLIP_BIN}" inspect "${WORK_DIR}/inspect.slip" --format=json --diagnostics=json
    WORKING_DIRECTORY "${WORK_DIR}/inspection-only"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(JSON count LENGTH "${output}" modules)
string(JSON name GET "${output}" modules 1 name)
string(JSON width GET "${output}" modules 1 ports 0 width)
string(JSON direction GET "${output}" modules 1 ports 1 direction)
string(JSON origin GET "${output}" modules 1 instances 0 connections 0 origin)
string(JSON signal GET "${output}" modules 1 instances 0 connections 0 signal)
if(NOT result EQUAL 0 OR NOT count EQUAL 2 OR NOT name STREQUAL "top" OR NOT width STREQUAL "[15:0]"
        OR NOT direction STREQUAL "output" OR NOT origin STREQUAL "regex: data_(.*)" OR NOT signal STREQUAL "bus_a"
        OR NOT errors STREQUAL "" OR EXISTS "${WORK_DIR}/inspection-only/build")
    message(FATAL_ERROR "Inspection returned incorrect connections or published RTL: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" inspect "${WORK_DIR}/inspect.slip"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT output MATCHES "output logic \\[15:0\\] bus_y" OR NOT output MATCHES "regex: data_"
        OR NOT output MATCHES "width from leaf.data_y")
    message(FATAL_ERROR "Text inspection lost inferred interface information: ${result}\n${output}${errors}")
endif()

# Human diagnostics retain the original stdin line and show a caret.
file(WRITE "${WORK_DIR}/backend-error.slip" "module m(a,y) {\n    logic a; logic y;\n    assign y = missing(a);\n}\n")
execute_process(COMMAND "${SLIP_BIN}" check -
    INPUT_FILE "${WORK_DIR}/backend-error.slip"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 1 OR NOT errors MATCHES "<stdin>:3:5: error \\[E_SV\\]"
        OR NOT errors MATCHES "assign y = missing\\(a\\);" OR NOT errors MATCHES "\\^")
    message(FATAL_ERROR "Stdin backend errors lost source excerpt or location: ${result}\n${errors}")
endif()

file(WRITE "${WORK_DIR}/typo.slip" "module m(y) {\n    logic data; logic y;\n    assign y = dtaa;\n}\n")
execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/typo.slip" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON line GET "${errors}" line)
string(JSON message GET "${errors}" message)
if(NOT result EQUAL 0 OR NOT code STREQUAL "W_IMPLICIT" OR NOT line EQUAL 3 OR NOT message MATCHES "did you mean 'data'")
    message(FATAL_ERROR "Implicit warning omitted source or spelling suggestion: ${result}\n${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/typo.slip" --no-implicit --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON line GET "${errors}" line)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_IMPLICIT" OR NOT line EQUAL 3)
    message(FATAL_ERROR "--no-implicit did not report original identifier: ${result}\n${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/warning.slip" --widths-as-errors --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
string(JSON source_file GET "${errors}" file)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_SV" OR NOT source_file STREQUAL "${WORK_DIR}/warning.slip")
    message(FATAL_ERROR "--widths-as-errors lost original source location: ${result}\n${errors}")
endif()

file(WRITE "${WORK_DIR}/expanded-error.slip" "module m(y) {\n    logic [1:0] y;\n    `for (`i=0; `i<2; `i=`i+1) {\n        assign y[`i] = 300;\n    }\n}\n")
execute_process(COMMAND "${SLIP_BIN}" check "${WORK_DIR}/expanded-error.slip" --strict --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON line GET "${errors}" line)
string(JSON expansion GET "${errors}" expansion)
if(NOT result EQUAL 1 OR NOT line EQUAL 4 OR NOT expansion STREQUAL "i=0")
    message(FATAL_ERROR "Expanded diagnostics lost the loop binding: ${result}\n${errors}")
endif()

foreach(arguments "inspect;--stdout" "inspect;--format=" "inspect;--format=xml" "check;--format=json" "inspect;-o;unused")
    execute_process(COMMAND "${SLIP_BIN}" ${arguments} "${WORK_DIR}/valid.slip" --diagnostics=json
        RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
    string(STRIP "${errors}" errors)
    string(JSON code GET "${errors}" code)
    if(NOT result EQUAL 2 OR NOT code STREQUAL "E_USAGE")
        message(FATAL_ERROR "Invalid inspection arguments were accepted: ${arguments}\n${errors}")
    endif()
endforeach()

file(WRITE "${WORK_DIR}/trace.slip" "module traced(clk,a,y) { logic clk,a,y; seq(clk) { y=a; } }\n")
execute_process(COMMAND "${SLIP_BIN}" inspect "${WORK_DIR}/trace.slip" --signal traced.a --format=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(JSON selected GET "${output}" modules 0 ports 0 name)
string(JSON consumer GET "${output}" modules 0 ports 0 uses 0 kind)
if(NOT result EQUAL 0 OR NOT selected STREQUAL "a" OR NOT consumer STREQUAL "seq assignment")
    message(FATAL_ERROR "Signal query did not retain references: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" inspect "${WORK_DIR}/trace.slip" --signal traced.missing --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 2 OR NOT errors MATCHES "unknown signal")
    message(FATAL_ERROR "Unknown signal query should fail: ${result}\n${errors}")
endif()

# External reflection works while a project's entry is syntactically incomplete.
file(MAKE_DIRECTORY "${WORK_DIR}/reflection")
file(WRITE "${WORK_DIR}/reflection/ext.sv" "module ext #(parameter type T=logic [7:0]) (input T a, output T y); assign y=a; endmodule\n")
file(WRITE "${WORK_DIR}/reflection/broken.slip" "module top { ext u { .\n")
file(WRITE "${WORK_DIR}/reflection/slip.conf" "entry=broken.slip\nip_dir=.\ntop=top\n")
execute_process(COMMAND "${SLIP_BIN}" inspect --interface ext --project "${WORK_DIR}/reflection/slip.conf" --format=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(JSON type_parameter GET "${output}" modules 0 parameters 0 is_type)
string(JSON port GET "${output}" modules 0 ports 0 name)
if(NOT result EQUAL 0 OR NOT type_parameter OR NOT port STREQUAL "a")
    message(FATAL_ERROR "Independent external reflection failed: ${result}\n${output}${errors}")
endif()
