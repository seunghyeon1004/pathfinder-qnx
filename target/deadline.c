/*
 * deadline.c - a 10 ms control loop that occasionally misses its deadline because of a LONG critical section
 * (not an inversion: the lock owner keeps running). Shows Pathfinder separating "bounded blocking" from priority inversion.
 *
 *   control (prio 30): every 10 ms: 2 ms of work; every 5th cycle it also reads shared config under `cfg_lock`
 *   logger  (prio 10): periodically takes `cfg_lock` and formats/writes a log snapshot
 *
 * Modes (argv[1]):
 *   bug   logger holds the lock for the whole 25 ms formatting+write       -> control blocks 25 ms, misses its 10 ms deadline
 *   fix   logger copies the data under the lock (0.3 ms) and writes outside -> no misses
 *
 * usage: deadline <bug|fix> [seconds]
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

static pthread_mutex_t cfg_lock = PTHREAD_MUTEX_INITIALIZER;   /* QNX default protocol: PTHREAD_PRIO_INHERIT */
static int fixed;
static volatile int running = 1;

static long long now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000; }
static void busy(double ms) { long long end = now_ms() + (long long)(ms + 0.999); while (now_ms() < end) { } }
static void sleep_until(long long ms) { long long d = ms - now_ms(); if (d > 0) { struct timespec t = { d / 1000, (d % 1000) * 1000000L }; nanosleep(&t, NULL); } }

static void setup(const char *name, int p)
{
    struct sched_param sp = { .sched_priority = p };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pthread_setname_np(pthread_self(), name);
    pf_name("%s", name);
}

static void *logger(void *a)
{
    setup("logger", 10);
    sleep_until(now_ms() + 37);
    while (running) {
        pf_lock_want("cfg"); pthread_mutex_lock(&cfg_lock); pf_lock_acq("cfg");
        busy(fixed ? 0.3 : 25);
        pf_lock_rel("cfg"); pthread_mutex_unlock(&cfg_lock);
        if (fixed) busy(25);                    /* the slow part now happens outside the lock */
        sleep_until(now_ms() + 90);
    }
    return NULL;
}

static void *control(void *a)
{
    int n = 0;
    setup("control", 30);
    long long next = now_ms() + 20;
    while (running) {
        sleep_until(next);
        pf_period_begin("control", n);
        busy(2);
        if (n % 5 == 0) {
            pf_lock_want("cfg"); pthread_mutex_lock(&cfg_lock); pf_lock_acq("cfg");
            busy(0.2);
            pf_lock_rel("cfg"); pthread_mutex_unlock(&cfg_lock);
        }
        pf_period_end("control", n);
        n++;
        next += 10;
    }
    return NULL;
}

int main(int argc, char **argv)
{
    pthread_t t[2];
    int secs = argc > 2 ? atoi(argv[2]) : 2;
    if (argc < 2 || (strcmp(argv[1], "bug") && strcmp(argv[1], "fix"))) { fprintf(stderr, "usage: deadline <bug|fix> [seconds]\n"); return 2; }
    fixed = !strcmp(argv[1], "fix");
    { struct sched_param sp = { .sched_priority = 50 }; pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp); }
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pf_name("main"); pf_note("deadline mode=%s", argv[1]);
    pthread_create(&t[0], NULL, logger, NULL);
    pthread_create(&t[1], NULL, control, NULL);
    struct timespec ts = { secs, 0 }; nanosleep(&ts, NULL);
    running = 0;
    pthread_join(t[0], NULL); pthread_join(t[1], NULL);
    printf("deadline mode=%s done\n", argv[1]);
    return 0;
}
