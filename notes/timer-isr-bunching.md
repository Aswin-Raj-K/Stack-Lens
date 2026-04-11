# Timer ISR bunching at end of Trace_Test run

**Status:** open, deferred
**First observed:** 2026-04-10 (trace captured at 21:03 on daqboard_v2)
**Trace file:** `C:\Users\ixana\Downloads\test_trace.json`

## TL;DR

Running `app/Trace_Test` with a 500 µs periodic timer ISR, the first
7 timer ticks fire cleanly at 500 µs intervals as expected. But after the
last `run_pipeline()` call (and entry into `assert(0)`), **three additional
timer interrupts fire in rapid succession** — ~11 µs apart — which is far
faster than the configured 500 µs period and physically impossible if
the timer were operating normally.

The first of those three ticks also fires **190 µs earlier than scheduled**
(at 612901 µs vs. expected 613091 µs). The remaining two are serviced via
NVIC tail-chaining, indicating they were already pending when the first
one ran.

## The code

[app/Trace_Test/main.cpp](../../QS127S_2/FW-APP-QS127S-audio/app/Trace_Test/main.cpp):

```cpp
int main() {
    trace_init();
    board::init();

    run_pipeline();           // #1 — before pause
    trace_pause();
    paused();                 // 100 µs delay + timer setup, then resume
    board::spare_timer.config(BOARD_TIMER_FREQ_FOR_US, false);
    const uint32_t tick_per_us = board::spare_timer.tick_freq() / 1000000;
    board::spare_timer.period_set(tick_per_us * 0.5 * 1000.0f);  // 500 µs
    board::spare_timer.irq_callback(cb_timer_tick, nullptr);
    board::spare_timer.irq_enable();
    board::spare_timer.start();
    trace_resume();

    for (int i = 0; i < 10; i++) {   // #2–#11 — instrumented workload
        run_pipeline();
    }

    assert(0);                       // <-- ticks 8, 9, 10 bunch here
    return 0;
}
```

The ISR callback (instrumented because it's in main.cpp):

```cpp
static void cb_timer_tick(void *) {
    TRACE_MARK("timer_tick");
    tick_count++;
    isr_inner_work(tick_count);
}
```

Timer clock is HFRC/16 = 6 MHz, period = 3000 ticks = 500 µs.
Timer mode: `AM_HAL_TIMER_FN_UPCOUNT` (the `false` in `config(..., false)`
maps to `single_shot=false` → upcount, periodic).

## Observation — tick timing table

```
 #   start (µs)   gap from prev exit   duration
 ─   ──────────   ──────────────────   ────────
 1   609591.61    —                    8.24
 2   610091.61    491.76               8.23    \
 3   610591.61    491.77               8.23     \
 4   611091.61    491.77               8.24      |  clean 500 µs period
 5   611591.68    491.82               8.23      |  (ticks 1-7)
 6   612091.61    491.71               8.23     /
 7   612591.61    491.77               8.24    /
 8   612901.07    301.22               8.23    ← 190 µs EARLY vs. expected 613091
 9   612912.62      3.32               8.24    ← NVIC tail-chain (pending)
10   612924.19      3.32               8.24    ← NVIC tail-chain (pending)
```

The 3.32 µs gap between ticks 8→9 and 9→10 is the textbook ARM Cortex-M4
tail-chaining latency (register save/restore between back-to-back ISRs).
This spacing is only physically possible if the ISRs were **already
pending** at the moment the previous one started running. It is NOT
consistent with a timer periodically firing every 500 µs.

## Thread activity at the anomaly

Last instrumented thread activity, from the same trace:

```
612515.84  enter run_pipeline (#11 — last loop iteration)
612519.58    enter calibrate
612521.88      enter delay_long
612591.61      ISR: cb_timer_tick #7     ← preempts delay_long
612599.85      ISR exit
612640.55      exit  delay_long
...
612787.79    enter delay_long (second in pipeline #11)
612894.27    exit  delay_long
612897.92  exit  run_pipeline               ← main() falls through to assert(0)

612901.07  ISR: cb_timer_tick #8  ← 3.15 µs after exit from main thread
612909.30  ISR exit
612912.62  ISR: cb_timer_tick #9  ← 3.32 µs tail-chain
612920.86  ISR exit
612924.19  ISR: cb_timer_tick #10 ← 3.32 µs tail-chain
612932.43  ISR exit                        (trace ends here)
```

`assert(0)` is not instrumented (vendor SDK code is not built with
`-finstrument-functions`) so the profiler sees the main thread "disappear"
after pipeline #11 exits.

## What doesn't fit a simple model

Cortex-M4 NVIC has **one pending bit per interrupt source**. You cannot
legitimately accumulate 3 pending interrupts from a single timer on ARM.
So one of the following must be true:

1. The timer hardware is **re-asserting the interrupt line immediately
   after the ISR clears it** — which would happen if the counter isn't
   being reset at compare0 match, or if some other condition is latched.

2. A **second interrupt source** on the same timer is also firing.
   `qs_timer_t::period_set()` sets *both* `compare0` (period, 3000 ticks
   = 500 µs) and `compare1` (period × 50% duty = 1500 ticks = 250 µs).
   If compare1 is also routed to NVIC, you'd see extra interrupts.
   The current ISR (`qs_timer_irq` in
   [FW-toolchain/Ambiq_AMA4BP/peripheral/qs_timer.cpp](../../QS127S_2/FW-APP-QS127S-audio/FW-toolchain/Ambiq_AMA4BP/peripheral/qs_timer.cpp))
   only clears the `COMPARE0` flag, not `COMPARE1` — so if compare1 IS
   firing it would stay pending and trigger immediate re-entry.

3. The **pipeline's trace_log critical sections** (each ~30 cycles of
   IRQ-disabled state) accumulated enough total disabled-IRQ time to
   let the hardware latch multiple events in some way we're not
   modelling correctly.

Explanation (2) is the leading suspect because it would directly
explain both the "fires early" and "fires back-to-back" symptoms.

## Things to try next

1. **Dump `TMR15_CMP1` at runtime.** Break in `cb_timer_tick` and read
   the compare1 register. If it's non-zero and matches a sub-period value,
   that confirms a dual-source firing hazard.

2. **Check `am_hal_timer_interrupt_status_get()` inside the ISR** —
   print which flags are set. Expectation is only `COMPARE0`; if
   `COMPARE1` is also set, we've found the bug.

3. **Call `am_hal_timer_interrupt_clear()` for BOTH `COMPARE0` AND
   `COMPARE1` inside `qs_timer_irq`** and re-run. If bunching disappears,
   it was a compare1-related issue in the HAL wrapper.

4. **Add a counter in `cb_timer_tick`**, read it after halting at
   `assert(0)`, and compare to `elapsed_time / 500`. If counts match,
   the timer really is firing at 500 µs and we're just seeing a
   different artifact. If counts are higher, the timer is firing faster
   than configured.

5. **Replace `assert(0)` with `while(1){}`** to rule out any assert-
   handler side effects. If the bunching moves or disappears, the assert
   handler is involved.

6. **Try `single_shot=true`** in the `config()` call. Even though `true`
   nominally means one-shot, it uses `AM_HAL_TIMER_FN_EDGE` which may
   have cleaner periodic behaviour in this HAL wrapper.

7. **Flip the test to a non-instrumented ISR** (move `cb_timer_tick` into
   a separate `.cpp` without `-finstrument-functions`) and see if the
   bunching still happens. If it goes away, the instrumentation overhead
   is interacting with the ISR timing somehow. If it persists, it's a
   pure timer-hardware / HAL issue.

## Relevant files

- [app/Trace_Test/main.cpp](../../QS127S_2/FW-APP-QS127S-audio/app/Trace_Test/main.cpp) — the test program
- [app/Trace_Test/trace.cpp](../../QS127S_2/FW-APP-QS127S-audio/app/Trace_Test/trace.cpp) — `trace_mark()`, `trace_pause/resume`
- [FW-toolchain/Ambiq_AMA4BP/peripheral/qs_timer.cpp](../../QS127S_2/FW-APP-QS127S-audio/FW-toolchain/Ambiq_AMA4BP/peripheral/qs_timer.cpp) — timer ISR shim; only clears COMPARE0
- [FW-toolchain/Ambiq_AMA4BP/peripheral/qs_private_ambiq_timer.hpp](../../QS127S_2/FW-APP-QS127S-audio/FW-toolchain/Ambiq_AMA4BP/peripheral/qs_private_ambiq_timer.hpp) — `period_set` sets both `compare0` and `compare1`
- `C:\Users\ixana\Downloads\test_trace.json` — the trace showing the bunching

## Notes for future analysis

- Trace is NOT wrapped (`wrapped: false` in metadata, 251 spans / 131072
  buffer capacity — well under limit). Buffer overflow is NOT an
  explanation.
- DWT->CYCCNT wrap is 44.7 s at 96 MHz; trace runs ~4.4 s, well within
  one cycle. Timestamp wraparound is NOT an explanation.
- The pipeline completes in ~380 µs with ~400 instrumented function
  calls; trace_log overhead per call is ~30 cycles IRQ-disabled
  (~0.3 µs), so max contiguous IRQ-disabled time is ~0.3 µs — far too
  short to cause multiple pending interrupts to accumulate.
- All 10 ticks have the same `ipsr` value (98), which on Apollo4 maps to
  IRQ 82 = `am_timer15_isr`. So they're all coming from the same timer
  peripheral, same HAL ISR shim.
