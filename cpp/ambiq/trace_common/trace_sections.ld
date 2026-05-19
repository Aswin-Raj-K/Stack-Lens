/* Linker fragment — adds the .trace_buf section (1.5 MB ring buffer in
 * SHARED_SRAM) only when the trace module is linked in. Included via
 * target_link_options in trace_common.cmake.
 */
SECTIONS
{
    .trace_buf (NOLOAD) :
    {
        . = ALIGN(4);
        _trace_buf_start = .;
        KEEP(*(.trace_buf))
        KEEP(*(.trace_idx))
        . = ALIGN(4);
        _trace_buf_end = .;
    } > SHARED_SRAM
}
