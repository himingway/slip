file(MAKE_DIRECTORY "${WORK_DIR}")
set(project "${WORK_DIR}/project with spaces")
set(outside "${WORK_DIR}/outside")
file(MAKE_DIRECTORY "${project}/rtl" "${project}/ip" "${project}/more ip" "${outside}")
file(WRITE "${project}/ip/leaf.sv" "module leaf(input logic [7:0] a, output logic [7:0] y); assign y=a; endmodule\n")
file(WRITE "${project}/more ip/spare.sv" "module spare(input logic [7:0] a, output logic [7:0] y); assign y=a; endmodule\n")
file(WRITE "${project}/sources.f" "ip/leaf.sv\n")
file(WRITE "${project}/rtl/top.slip" "module top(a,y) { logic [7:0] link; leaf u {.a,.y(link)}; spare v {.a(link),.y}; }\n")
file(WRITE "${project}/slip.conf" "# Project paths are configuration-relative.\nentry = rtl/top.slip\nfilelist = sources.f\nip_dir = \"more ip\"\nout_dir = \"generated rtl\" # inline comment\nstrict = true\n")

execute_process(COMMAND "${SLIP_BIN}" build --diagnostics=json WORKING_DIRECTORY "${project}"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT errors STREQUAL "" OR NOT EXISTS "${project}/generated rtl/top.sv")
    message(FATAL_ERROR "Automatic project build did not use configuration paths: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" inspect --project "${project}/slip.conf" --format=json --diagnostics=json
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(JSON name GET "${output}" modules 0 name)
string(JSON width GET "${output}" modules 0 ports 0 width)
if(NOT result EQUAL 0 OR NOT errors STREQUAL "" OR NOT name STREQUAL "top" OR NOT width STREQUAL "[7:0]"
        OR EXISTS "${outside}/build")
    message(FATAL_ERROR "Project inspection lost configured IP or wrote output: ${result}\n${output}${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" build --project "${project}/slip.conf" -o custom-rtl
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT EXISTS "${outside}/custom-rtl/top.sv")
    message(FATAL_ERROR "CLI output override should be relative to the working directory: ${result}\n${output}${errors}")
endif()

# An explicit input without --project remains independent of nearby settings.
file(WRITE "${outside}/slip.conf" "unknown_option = true\n")
file(WRITE "${outside}/standalone.slip" "module standalone(a,y) { assign y=a; }\n")
execute_process(COMMAND "${SLIP_BIN}" check standalone.slip WORKING_DIRECTORY "${outside}"
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Explicit source unexpectedly loaded slip.conf: ${result}\n${errors}")
endif()

# CLI source and IP arguments override or extend the configured project.
file(MAKE_DIRECTORY "${outside}/extra-ip")
file(WRITE "${outside}/extra-ip/extra.sv" "module extra(input logic [7:0] a, output logic [7:0] y); assign y=a; endmodule\n")
file(WRITE "${outside}/listed.sv" "module listed(input logic [7:0] a, output logic [7:0] y); assign y=a; endmodule\n")
file(WRITE "${outside}/extra.f" "listed.sv\n")
file(WRITE "${outside}/override.slip" "module override(a,y) { logic [7:0] x; logic [7:0] z; leaf u {.a,.y(x)}; extra v {.a(x),.y(z)}; listed w {.a(z),.y}; }\n")
execute_process(COMMAND "${SLIP_BIN}" build override.slip --project "${project}/slip.conf" -ip extra-ip -f extra.f --stdout
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT output MATCHES "module override" OR output MATCHES "module top")
    message(FATAL_ERROR "CLI entry and additional IP failed to merge with project: ${result}\n${output}${errors}")
endif()

# Strict settings are overridable individually and in command-line order.
file(WRITE "${outside}/width.slip" "module m(a,y) { logic [15:0] a; logic [7:0] y; assign y=a; }\n")
execute_process(COMMAND "${SLIP_BIN}" check width.slip --project "${project}/slip.conf" --widths-as-warnings --diagnostics=json
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 0 OR NOT code STREQUAL "W_WIDTH")
    message(FATAL_ERROR "CLI should disable configured width errors independently: ${result}\n${errors}")
endif()
file(WRITE "${outside}/implicit.slip" "module m(y) { logic y; assign y=missing; }\n")
execute_process(COMMAND "${SLIP_BIN}" check implicit.slip --project "${project}/slip.conf" --allow-implicit --diagnostics=json
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT errors MATCHES "W_IMPLICIT" OR NOT errors MATCHES "W_UNDRIVEN")
    message(FATAL_ERROR "CLI should allow implicit declarations from a strict project: ${result}\n${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" check implicit.slip --project "${project}/slip.conf" --no-strict --no-implicit --diagnostics=json
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_IMPLICIT")
    message(FATAL_ERROR "The last CLI check should override earlier flags: ${result}\n${errors}")
endif()
foreach(settings "strict = true\nno_implicit = false\nwidths_as_errors = false" "widths_as_errors = false\nno_implicit = false\nstrict = true")
    file(WRITE "${project}/overrides.conf" "entry = rtl/top.slip\n${settings}\n")
    execute_process(COMMAND "${SLIP_BIN}" check "${outside}/implicit.slip" --project "${project}/overrides.conf" --diagnostics=json
        RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
    if(NOT result EQUAL 0 OR NOT errors MATCHES "W_IMPLICIT")
        message(FATAL_ERROR "Independent project settings should override strict in any key order: ${result}\n${errors}")
    endif()
endforeach()

# Quoted paths preserve spaces and # characters instead of treating them as comments.
file(WRITE "${project}/rtl/design #1.slip" "module quoted(a,y) { assign y=a; }\n")
file(WRITE "${project}/quoted.conf" "entry = 'rtl/design #1.slip' # comment\nout_dir = \"generated #1\"\n")
execute_process(COMMAND "${SLIP_BIN}" build --project "${project}/quoted.conf"
    WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
if(NOT result EQUAL 0 OR NOT EXISTS "${project}/generated #1/quoted.sv")
    message(FATAL_ERROR "Quoted project paths were parsed as comments: ${result}\n${output}${errors}")
endif()

function(expect_config_error name contents expected_line)
    file(WRITE "${project}/${name}.conf" "${contents}")
    execute_process(COMMAND "${SLIP_BIN}" build --project "${project}/${name}.conf" --diagnostics=json
        WORKING_DIRECTORY "${outside}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
    string(STRIP "${errors}" errors)
    string(JSON code GET "${errors}" code)
    string(JSON line GET "${errors}" line)
    string(JSON source_file GET "${errors}" file)
    if(NOT result EQUAL 2 OR NOT code STREQUAL "E_CONFIG" OR NOT line EQUAL expected_line
            OR NOT source_file STREQUAL "${project}/${name}.conf" OR NOT output STREQUAL "")
        message(FATAL_ERROR "Malformed config should fail before compiling at its source line: ${name}\n${result}\n${errors}")
    endif()
endfunction()
expect_config_error(unknown "entry = rtl/top.slip\nstrcit = true\n" 2)
expect_config_error(duplicate "entry = rtl/top.slip\nentry = other.slip\n" 2)
expect_config_error(boolean "entry = rtl/top.slip\nstrict = yes\n" 2)
expect_config_error(empty "entry = \"\"\n" 1)
expect_config_error(unclosed "entry = \"rtl/top.slip\n" 1)
expect_config_error(trailing "entry = \"rtl/top.slip\" unexpected\n" 1)
expect_config_error(syntax "entry rtl/top.slip\n" 1)
expect_config_error(stdin "entry = -\n" 1)
expect_config_error(missing_entry "strict = true\n" 1)

execute_process(COMMAND "${SLIP_BIN}" check --project "${project}/missing.conf" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 1 OR NOT code STREQUAL "E_IO")
    message(FATAL_ERROR "Missing project configuration should report E_IO: ${result}\n${errors}")
endif()
execute_process(COMMAND "${SLIP_BIN}" check --project "${project}/slip.conf" --project "${project}/quoted.conf" --diagnostics=json
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 15)
string(STRIP "${errors}" errors)
string(JSON code GET "${errors}" code)
if(NOT result EQUAL 2 OR NOT code STREQUAL "E_USAGE")
    message(FATAL_ERROR "Multiple project configurations should report E_USAGE: ${result}\n${errors}")
endif()
