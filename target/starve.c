/*
 * starve.c - CPU starvation by an unbounded high-priority burst.
 *
 *   ctrl (prio 20): 20 ms periodic task with 3 ms of work, pf_period markers.
 *   hog  (prio 40): every 400 ms runs a CPU burst of 150 ms (think: image processing, a logging flush, a crypto job).
 *
 * Modes (argv[1]):
 *   bug   hog really runs at priority 40 -> ctrl is kept off the CPU for 150 ms and misses ~7 deadlines per burst
 *   fix   hog runs at priority 10 (below ctrl) -> ctrl always preempts it
 *
 * usage: starve <bug|fix> [seconds]
 * SPDX-License-Identifier: Apache-2.0
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/neutrino.h>
#include "pf_mark.h"

static volatile int running = 1;
static int hogprio = 40;

static long long now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000; }
static void busy(int ms) { long long end = now_ms() + ms; while (now_ms() < end) { } }
static void sleep_until(long long ms) { long long d = ms - now_ms(); if (d > 0) { struct timespec t = { d / 1000, (d % 1000) * 1000000L }; nanosleep(&t, NULL); } }
static void setup(const char *name, int p)
{
    struct sched_param sp = { .sched_priority = p };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pthread_setname_np(pthread_self(), name);
    pf_name("%s", name);
}

static void *hog(void *a)
{
    setup("hog", hogprio);
    long long next = now_ms() + 230;
    while (running) { sleep_until(next); busy(150); next += 400; }
    return NULL;
}

static void *ctrl(void *a)
{
    int n = 0;
    setup("ctrl", 20);
    long long next = now_ms() + 20;
    while (running) {
        sleep_until(next);
        pf_period_begin("ctrl", n);
        busy(3);
        pf_period_end("ctrl", n);
        n++; next += 20;
    }
    return NULL;
}

int main(int argc, char **argv)
{
    pthread_t t[2];
    int secs = argc > 2 ? atoi(argv[2]) : 2;
    if (argc < 2 || (strcmp(argv[1], "bug") && strcmp(argv[1], "fix"))) { fprintf(stderr, "usage: starve <bug|fix> [seconds]\n"); return 2; }
    hogprio = strcmp(argv[1], "fix") ? 40 : 10;
    { struct sched_param sp = { .sched_priority = 50 }; pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp); }
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pf_name("main"); pf_note("starve mode=%s", argv[1]);
    pthread_create(&t[0], NULL, hog, NULL);
    pthread_create(&t[1], NULL, ctrl, NULL);
    struct timespec ts = { secs, 0 }; nanosleep(&ts, NULL);
    running = 0;
    pthread_join(t[0], NULL); pthread_join(t[1], NULL);
    printf("starve mode=%s done\n", argv[1]);
    return 0;
}
