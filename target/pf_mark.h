/*
 * pf_mark.h - tiny helper to put human-meaningful markers into the QNX kernel event stream.
 *
 * Markers are ordinary user trace events (TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, ...)).
 * They show up in `traceprinter` output as USREVENT lines and let Pathfinder name threads,
 * mark periods/deadlines and (for semaphores, which have no kernel-visible owner) lock ownership.
 * Cost when tracing is off: one kernel call that returns immediately.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef PF_MARK_H
#define PF_MARK_H

#include <stdio.h>
#include <stdarg.h>
#include <sys/neutrino.h>
#include <sys/trace.h>

/* user event codes (0..1023 are available to applications) */
#define PF_EV_NAME   1   /* "name <text>"            : name the calling thread */
#define PF_EV_PERIOD 2   /* "begin|end <task> <n>"   : one period / job of a periodic task */
#define PF_EV_LOCK   3   /* "acq|rel|want <lock>"    : lock bookkeeping (needed for semaphores) */
#define PF_EV_NOTE   4   /* free text                : shown on the timeline */

static inline void pf_mark(int code, const char *fmt, ...)
{
    char buf[96];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, code, buf);
}

#define pf_name(...)        pf_mark(PF_EV_NAME, __VA_ARGS__)
#define pf_period_begin(t, n) pf_mark(PF_EV_PERIOD, "begin %s %d", (t), (n))
#define pf_period_end(t, n)   pf_mark(PF_EV_PERIOD, "end %s %d", (t), (n))
#define pf_lock_want(l)     pf_mark(PF_EV_LOCK, "want %s", (l))
#define pf_lock_acq(l)      pf_mark(PF_EV_LOCK, "acq %s", (l))
#define pf_lock_rel(l)      pf_mark(PF_EV_LOCK, "rel %s", (l))
#define pf_note(...)        pf_mark(PF_EV_NOTE, __VA_ARGS__)

#endif
