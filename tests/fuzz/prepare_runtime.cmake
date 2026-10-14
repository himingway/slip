cmake_minimum_required(VERSION 3.24)

# Optional ELF runtime workaround: keep libFuzzer's allocator definitions local
# to its own object, leaving ASan's global new/delete interceptors intact.
if(NOT DEFINED ENGINE OR NOT EXISTS "${ENGINE}" OR NOT DEFINED OUTPUT)
    message(FATAL_ERROR "Specify -DENGINE=/path/to/libclang_rt.fuzzer.a and -DOUTPUT=/path/to/private-copy.a")
endif()
get_filename_component(engine "${ENGINE}" REALPATH)
get_filename_component(output "${OUTPUT}" REALPATH)
if(engine STREQUAL output)
    message(FATAL_ERROR "OUTPUT must be a private copy, not the installed engine")
endif()
find_program(objcopy NAMES llvm-objcopy objcopy REQUIRED)
get_filename_component(directory "${output}" DIRECTORY)
file(MAKE_DIRECTORY "${directory}")
set(symbols "${directory}/fuzzer-allocator-symbols.txt")
file(WRITE "${symbols}" "_ZdaPv\n_ZdaPvSt11align_val_t\n_ZdaPvm\n_ZdaPvmSt11align_val_t\n_ZdlPv\n_ZdlPvSt11align_val_t\n_ZdlPvm\n_ZdlPvmSt11align_val_t\n_Znam\n_ZnamSt11align_val_t\n_Znwm\n_ZnwmSt11align_val_t\n")
execute_process(COMMAND "${objcopy}" "--localize-symbols=${symbols}" "${engine}" "${output}"
    RESULT_VARIABLE result ERROR_VARIABLE errors)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Cannot prepare private libFuzzer runtime: ${errors}")
endif()
message(STATUS "Private engine: ${output}; configure with -DSLIP_LIBFUZZER_RUNTIME=${output}")
