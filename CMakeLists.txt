cmake_minimum_required(VERSION 3.24)
project(slip VERSION 0.2.0 LANGUAGES CXX)

if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build configuration" FORCE)
endif()

include(CTest)
include(FetchContent)
include(GNUInstallDirs)

option(SLIP_FETCH_SLANG "Fetch pinned slang when no installed package is found" ON)
option(SLIP_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)
option(SLIP_THREAD_SANITIZER "Enable the thread sanitizer" OFF)
option(SLIP_COVERAGE "Instrument Slip sources for GCC line and branch coverage" OFF)
option(SLIP_FUZZING "Build deterministic mutation fuzz tests" OFF)
option(SLIP_LIBFUZZER "Build a Clang libFuzzer target (also requires SLIP_FUZZING)" OFF)
set(SLIP_LIBFUZZER_RUNTIME "" CACHE FILEPATH "Optional compatible libFuzzer engine archive")
if(SLIP_COVERAGE AND (NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR CMAKE_CONFIGURATION_TYPES))
    message(FATAL_ERROR "Coverage requires GCC with a single-configuration generator")
endif()
if(SLIP_LIBFUZZER AND (NOT SLIP_FUZZING OR NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang" OR NOT SLIP_SANITIZERS))
    message(FATAL_ERROR "libFuzzer requires Clang, SLIP_FUZZING=ON and SLIP_SANITIZERS=ON")
endif()
if(SLIP_THREAD_SANITIZER AND (SLIP_SANITIZERS OR NOT CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang"))
    message(FATAL_ERROR "ThreadSanitizer requires GCC or Clang and cannot be combined with SLIP_SANITIZERS")
endif()

find_package(slang 10 CONFIG QUIET)
if(NOT TARGET slang::slang)
    if(NOT SLIP_FETCH_SLANG)
        message(FATAL_ERROR "slang 10 is required; set slang_DIR or enable SLIP_FETCH_SLANG")
    endif()
    set(SLANG_INCLUDE_TESTS OFF CACHE BOOL "" FORCE)
    set(SLANG_INCLUDE_TOOLS OFF CACHE BOOL "" FORCE)
    set(SLANG_INCLUDE_INSTALL OFF CACHE BOOL "" FORCE)
    set(SLANG_USE_MIMALLOC OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(slang
        GIT_REPOSITORY https://github.com/MikePopoloski/slang.git
        GIT_TAG ace09c5d7c9f4e28eed654d2f353c6dc792ebf67)
    FetchContent_MakeAvailable(slang)
endif()

# slang's debug allocator layout differs from release; reject mixed imported
# configurations instead of producing an executable with an ABI mismatch.
get_target_property(_slip_slang_imported slang::slang IMPORTED)
if(_slip_slang_imported AND NOT CMAKE_CONFIGURATION_TYPES)
    get_target_property(_slip_slang_configs slang::slang IMPORTED_CONFIGURATIONS)
    if(CMAKE_BUILD_TYPE STREQUAL "Debug" AND NOT "DEBUG" IN_LIST _slip_slang_configs)
        message(FATAL_ERROR "A Debug Slip build requires a Debug slang installation; use Release/RelWithDebInfo or build slang in Debug")
    elseif(NOT CMAKE_BUILD_TYPE STREQUAL "Debug" AND _slip_slang_configs STREQUAL "DEBUG")
        message(FATAL_ERROR "Release Slip requires a Release slang installation")
    endif()
endif()

add_library(slip_core
    src/frontend.cpp
    src/functions.cpp
    src/pattern.cpp
    src/slang_backend.cpp
    src/compiler.cpp)
add_library(slip::core ALIAS slip_core)
target_include_directories(slip_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_compile_features(slip_core PUBLIC cxx_std_20)
set_target_properties(slip_core PROPERTIES CXX_EXTENSIONS OFF)
target_link_libraries(slip_core PRIVATE slang::slang)
find_path(SLIP_PCRE2_INCLUDE_DIR pcre2.h REQUIRED)
find_library(SLIP_PCRE2_LIBRARY NAMES pcre2-8 REQUIRED)
target_include_directories(slip_core PRIVATE ${SLIP_PCRE2_INCLUDE_DIR})
target_link_libraries(slip_core PRIVATE ${SLIP_PCRE2_LIBRARY})
if(MSVC)
    target_compile_options(slip_core PRIVATE /W4 /permissive-)
else()
    target_compile_options(slip_core PRIVATE -Wall -Wextra -Wpedantic)
endif()
if(SLIP_SANITIZERS AND NOT MSVC)
    target_compile_options(slip_core PUBLIC -O1 -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(slip_core PUBLIC -fsanitize=address,undefined)
endif()
if(SLIP_THREAD_SANITIZER)
    target_compile_options(slip_core PUBLIC -O1 -fsanitize=thread -fno-omit-frame-pointer)
    target_link_options(slip_core PUBLIC -fsanitize=thread)
endif()
if(SLIP_COVERAGE)
    target_compile_options(slip_core PUBLIC --coverage -O0 -g)
    target_link_options(slip_core PUBLIC --coverage)
    find_program(SLIP_GCOV gcov REQUIRED)
    find_program(SLIP_GZIP gzip REQUIRED)
    add_custom_target(coverage_report
        COMMAND ${CMAKE_COMMAND}
            "-DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}"
            "-DBUILD_DIR=${CMAKE_CURRENT_BINARY_DIR}"
            "-DGCOV=${SLIP_GCOV}"
            "-DGZIP=${SLIP_GZIP}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/coverage.cmake"
        DEPENDS slip VERBATIM)
endif()
if(SLIP_LIBFUZZER)
    target_compile_options(slip_core PRIVATE -fsanitize=fuzzer-no-link)
endif()

add_executable(slip src/main.cpp)
target_link_libraries(slip PRIVATE slip_core)
install(TARGETS slip RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

if(SLIP_FUZZING)
    add_executable(slip_mutation_fuzz tests/fuzz/target.cpp tests/fuzz/mutation.cpp)
    target_link_libraries(slip_mutation_fuzz PRIVATE slip::core)
    if(BUILD_TESTING)
        file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/tests/fuzz")
        add_test(NAME compiler.fuzz.mutations COMMAND slip_mutation_fuzz
            --corpus "${CMAKE_CURRENT_SOURCE_DIR}/tests/fuzz/corpus" --runs 3000 --seed 42)
        set_tests_properties(compiler.fuzz.mutations PROPERTIES TIMEOUT 180
            WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/tests/fuzz" LABELS fuzz)
    endif()
    if(SLIP_LIBFUZZER)
        add_executable(slip_fuzzer tests/fuzz/target.cpp)
        target_link_libraries(slip_fuzzer PRIVATE slip::core)
        if(SLIP_LIBFUZZER_RUNTIME)
            if(NOT EXISTS "${SLIP_LIBFUZZER_RUNTIME}")
                message(FATAL_ERROR "libFuzzer engine archive does not exist: ${SLIP_LIBFUZZER_RUNTIME}")
            endif()
            # Instrument the target without implicitly linking a second engine.
            target_compile_options(slip_fuzzer PRIVATE -fsanitize=fuzzer-no-link)
            target_link_options(slip_fuzzer PRIVATE -fsanitize=fuzzer-no-link)
            target_link_libraries(slip_fuzzer PRIVATE
                "$<LINK_LIBRARY:WHOLE_ARCHIVE,${SLIP_LIBFUZZER_RUNTIME}>")
        else()
            target_compile_options(slip_fuzzer PRIVATE -fsanitize=fuzzer)
            target_link_options(slip_fuzzer PRIVATE -fsanitize=fuzzer)
        endif()
    endif()
endif()

if(BUILD_TESTING)
    find_package(Threads REQUIRED)
    add_executable(slip_tests tests/compiler_tests.cpp)
    target_link_libraries(slip_tests PRIVATE slip::core Threads::Threads)
    add_test(NAME compiler.unit COMMAND slip_tests)

    set(_slip_regressions
        tests/regression/frontend.cpp
        tests/regression/semantic.cpp
        tests/regression/diagnostics.cpp
        tests/regression/runtime.cpp)
    add_executable(slip_regressions tests/regression_main.cpp ${_slip_regressions})
    target_link_libraries(slip_regressions PRIVATE slip::core Threads::Threads)
    foreach(_slip_source IN LISTS _slip_regressions)
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_slip_source}")
        file(STRINGS "${_slip_source}" _slip_cases REGEX "^TEST_CASE\\([a-zA-Z0-9_]+\\)")
        foreach(_slip_case IN LISTS _slip_cases)
            string(REGEX REPLACE "^TEST_CASE\\(([a-zA-Z0-9_]+)\\).*" "\\1" _slip_name "${_slip_case}")
            add_test(NAME compiler.regression.${_slip_name} COMMAND slip_regressions "${_slip_name}")
        endforeach()
    endforeach()

    file(GLOB _slip_fixtures CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/*.slip")
    foreach(_slip_fixture IN LISTS _slip_fixtures)
        get_filename_component(_slip_name "${_slip_fixture}" NAME_WE)
        add_test(NAME compiler.fixture.${_slip_name}
            COMMAND slip check "${_slip_fixture}" -ip "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/ip")
    endforeach()
    add_test(NAME compiler.cli COMMAND ${CMAKE_COMMAND}
        "-DSLIP_BIN=$<TARGET_FILE:slip>"
        "-DWORK_DIR=${CMAKE_CURRENT_BINARY_DIR}/tests/cli"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/cli.cmake")

    find_program(SLIP_VERILATOR verilator)
    if(SLIP_VERILATOR)
        foreach(_slip_behavior pipeline combinational state_machine array_parameters)
            set(_slip_behavior_source "${CMAKE_CURRENT_SOURCE_DIR}/tests/behavior")
            if(NOT _slip_behavior STREQUAL "pipeline")
                string(APPEND _slip_behavior_source "/${_slip_behavior}")
            endif()
            add_test(NAME compiler.behavior.${_slip_behavior} COMMAND ${CMAKE_COMMAND}
            "-DSLIP_BIN=$<TARGET_FILE:slip>"
            "-DVERILATOR=${SLIP_VERILATOR}"
            "-DSOURCE_DIR=${_slip_behavior_source}"
            "-DWORK_DIR=${CMAKE_CURRENT_BINARY_DIR}/tests/behavior/${_slip_behavior}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/behavior.cmake")
            set_tests_properties(compiler.behavior.${_slip_behavior} PROPERTIES TIMEOUT 180 LABELS behavior)
        endforeach()
    else()
        message(STATUS "Verilator not found; compiler.behavior is unavailable")
    endif()
endif()
