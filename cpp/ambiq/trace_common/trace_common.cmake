target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/trace.cpp
)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE
    -include ${CMAKE_CURRENT_LIST_DIR}/trace.hpp
)

# Adds the .trace_buf section to the final link without editing the main
# toolchain linker script. Uses INSERT BEFORE .sram_end so _esram still
# points to end-of-used-SRAM regardless of this fragment.
target_link_options(${CMAKE_PROJECT_NAME} PRIVATE
    -T${CMAKE_CURRENT_LIST_DIR}/trace_sections.ld
)
