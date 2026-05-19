#include "am_mcu_apollo.h"
#include "core_cm4.h"    // CMSIS, adjust to your Cortex-M variant
#include <stdint.h>

// Must be a power of 2 so `% TRACE_BUFFER_SIZE` compiles to a bitwise AND.
// 131072 events x 12 B = 1.5 MB in SHARED_SRAM (requires SRAM_ALL power mode).
#define TRACE_BUFFER_SIZE 131072

// TRACE_BUFFER_SIZE events are preserved instead of being overwritten.
// Useful for capturing startup behavior that would otherwise be wrapped away.
// Enable via `add_compile_definitions(TRACE_STOP_ON_OVERFLOW=1)` in app cmake.
#ifndef TRACE_STOP_ON_OVERFLOW
#define TRACE_STOP_ON_OVERFLOW 1
#endif

struct TraceEvent {
    uint8_t  type;       // 0 = enter, 1 = exit, 2 = mark
    uint8_t  ipsr;       // 0 = thread mode; nonzero = ISR exception number
    uint8_t  _pad[2];
    uint32_t cyccnt;
    uint32_t context;    // func_addr for type 0/1; string literal pointer for type 2
};

__attribute__((section(".trace_buf"), used))
volatile TraceEvent trace_buf[TRACE_BUFFER_SIZE];

__attribute__((section(".trace_idx"), used))
volatile uint32_t trace_idx = 0;

// BSS-zeroed → false before any constructor runs
static volatile bool trace_ready = false;

// ── Must mark all internal helpers as no_instrument ──────────────────
__attribute__((no_instrument_function))
void trace_init() {
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;
    trace_idx = 0;
    trace_ready = true;
}

__attribute__((no_instrument_function))
static inline void trace_log(void *func, uint8_t type) {
    if (!trace_ready) return;

    uint32_t primask = __get_PRIMASK();
    __disable_irq();

#if TRACE_STOP_ON_OVERFLOW
    if (trace_idx >= TRACE_BUFFER_SIZE) {
        trace_ready = false;
        __set_PRIMASK(primask);
        return;
    }
#endif

    uint32_t idx = trace_idx & (TRACE_BUFFER_SIZE - 1);
    volatile TraceEvent *evt = &trace_buf[idx];
    evt->type    = type;
    evt->ipsr    = (uint8_t)(__get_IPSR() & 0xFF);
    evt->cyccnt  = DWT->CYCCNT;
    evt->context = (uint32_t)func;
    trace_idx++;

    __set_PRIMASK(primask);
}

// Public: log a named timeline marker (string literal in .rodata)
__attribute__((no_instrument_function))
void trace_mark(const char *label) {
    if (!trace_ready) return;

    uint32_t primask = __get_PRIMASK();
    __disable_irq();

#if TRACE_STOP_ON_OVERFLOW
    if (trace_idx >= TRACE_BUFFER_SIZE) {
        trace_ready = false;
        __set_PRIMASK(primask);
        return;
    }
#endif

    uint32_t idx = trace_idx & (TRACE_BUFFER_SIZE - 1);
    volatile TraceEvent *evt = &trace_buf[idx];
    evt->type    = 2;
    evt->ipsr    = (uint8_t)(__get_IPSR() & 0xFF);
    evt->cyccnt  = DWT->CYCCNT;
    evt->context = (uint32_t)label;
    trace_idx++;

    __set_PRIMASK(primask);
}

// Public: temporarily stop logging instrumented events. Useful for excluding
// noisy boot/idle code so the ring buffer captures only the interesting region.
//
// IMPORTANT: pause()/resume() are nestable in the sense that the *same*
// trace_ready flag is shared. Don't bracket recursively.
__attribute__((no_instrument_function))
void trace_pause() {
    if (!trace_ready) return;
    // Log the pause mark BEFORE flipping the flag so the timestamp is captured
    trace_mark("__trace_pause__");
    trace_ready = false;
}

__attribute__((no_instrument_function))
void trace_resume() {
    // Re-enable BEFORE logging so the resume mark is captured.
    // Note: if TRACE_STOP_ON_OVERFLOW is 1 and the buffer already overflowed,
    // resuming will re-enable logging but trace_idx keeps wrapping — oldest
    // events will be overwritten from here on.
    trace_ready = true;
    trace_mark("__trace_resume__");
}

// ── These are the hooks the compiler is already calling ──────────────
extern "C" {

__attribute__((no_instrument_function))
void __cyg_profile_func_enter(void *func, void *caller) {
    trace_log(func, 0);
}

__attribute__((no_instrument_function))
void __cyg_profile_func_exit(void *func, void *caller) {
    trace_log(func, 1);
}

} // extern "C"