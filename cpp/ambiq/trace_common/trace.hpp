#pragma once

// Profiler tracing API.
//
// trace_init() must be called once during startup before any instrumented
// function runs. On Ambiq parts whose SHARED_SRAM is not powered until
// board::init(), call trace_init() AFTER board::init() — see the existing
// pattern in Trace_Test/main.cpp.
//
// Both functions have C++ linkage, matching the existing
// `extern void trace_init();` forward declarations in the codebase.
void trace_init();

// Log a named timeline marker at the current cycle count.
//
// The `label` pointer is stored directly in the trace ring buffer and
// resolved later by the Python profiler by reading the ELF. This means
// `label` MUST point to memory that is stable across the whole run — use
// a string literal. Runtime-built strings (stack/heap) will not work.
void trace_mark(const char *label);

// Compile-time enforcement: the `"" label ""` concatenation only works if
// `label` is a string literal. Passing `const char *` at runtime fails with
// a clear compiler error.
#define TRACE_MARK(label) trace_mark(("" label ""))

// Pause / resume tracing for a region of code. Calls between pause() and
// resume() are silently dropped from the ring buffer. The profiler shows
// the paused interval as a gray translucent band on the flame chart.
//
// Usage:
//   trace_pause();
//   noisy_setup_code_we_dont_care_about();
//   trace_resume();
//   the_actual_thing_were_profiling();
//
// Implementation reuses the existing TRACE_MARK mechanism with sentinel
// labels "__trace_pause__" / "__trace_resume__" so no new event format
// is needed.
void trace_pause();
void trace_resume();
