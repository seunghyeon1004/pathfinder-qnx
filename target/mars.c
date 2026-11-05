/*
 * mars.c - the 1997 Mars Pathfinder priority-inversion bug, rebuilt on QNX 8.0.
 *
 * Four SCHED_FIFO threads, all pinned to CPU 0 so the inversion is deterministic:
 *
 *   watchdog  prio 40  every 150 ms: did the bus manager report in? if not -> "WATCHDOG RESET"
 *   bus_mgr   prio 30  every 100 ms: take the shared "bus" lock, do 5 ms of work, heartbeat
 *   comms     prio 20  medium priority: long CPU bursts that do not touch the lock
 *   meteo     prio 10  low priority: holds the "bus" lock for 60 ms per cycle (the data collector)
 *
 * Lock modes (argv[1]):
 *   none     pthread mutex with PTHREAD_PRIO_NONE      -> priority inversion (the bug)
 *   sem      binary POSIX semaphore used as a lock      -> priority inversion (no inheritance)
 *   inherit  pthread mutex with PTHREAD_PRIO_INHERIT    -> fixed (this is also the QNX default)
 *   protect  pthread mutex with PTHREAD_PRIO_PROTECT    -> fixed (ceiling = 30)
 *
 * usage: mars <none|sem|inherit|protect> [seconds]
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include "pf_mark.h"

enum mode { M_NONE, M_SEM, M_INHERIT, M_PROTECT };
static enum mode mode;
static pthread_mutex_t bus_mx;
static sem_t bus_sem;
static volatile int heartbeat;
static volatile int running = 1;
static volatile int resets;

static void lock_bus(void)
{
    if (mode == M_SEM) sem_wait(&bus_sem); else pthread_mutex_lock(&bus_mx);
}
static void unlock_bus(void)
{
    if (mode == M_SEM) sem_post(&bus_sem); else pthread_mutex_unlock(&bus_mx);
}

static long long now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static void busy(int ms)
{
    long long end = now_ms() + ms;
    while (now_ms() < end) { }
}

static void sleep_ms(int ms)
{
    struct timespec t = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&t, NULL);
}

static void setup_thread(const char *name, int prio)
{
    struct sched_param sp = { .sched_priority = prio };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);   /* CPU 0 only */
    pthread_setname_np(pthread_self(), name);
    pf_name("%s", name);
}

static void *meteo(void *a)       /* low: collects data under the lock */
{
    setup_thread("meteo", 10);
    while (running) {
        pf_lock_want("bus"); lock_bus(); pf_lock_acq("bus");
        busy(60);
        pf_lock_rel("bus"); unlock_bus();
        sleep_ms(20);
    }
    return NULL;
}

static void *comms(void *a)       /* medium: unrelated CPU burst */
{
    setup_thread("comms", 20);
    sleep_ms(30);
    while (running) {
        busy(150);
        sleep_ms(150);
    }
    return NULL;
}

static void *bus_mgr(void *a)     /* high: periodic, needs the lock */
{
    int n = 0;
    setup_thread("bus_mgr", 30);
    long long next = now_ms() + 50;
    while (running) {
        long long d = next - now_ms();
        if (d > 0) sleep_ms((int)d);
        pf_period_begin("bus_mgr", n);
        pf_lock_want("bus"); lock_bus(); pf_lock_acq("bus");
        busy(5);
        pf_lock_rel("bus"); unlock_bus();
        heartbeat++;
        pf_period_end("bus_mgr", n);
        n++;
        next += 100;
    }
    return NULL;
}

static void *watchdog(void *a)
{
    int last = 0;
    setup_thread("watchdog", 40);
    sleep_ms(300);
    while (running) {
        sleep_ms(150);
        if (heartbeat == last) {
            resets++;
            pf_note("WATCHDOG RESET #%d", resets);
            printf("WATCHDOG RESET #%d at t=%lld ms (bus_mgr missed its heartbeat)\n", resets, now_ms() % 100000);
            fflush(stdout);
        }
        last = heartbeat;
    }
    return NULL;
}

int main(int argc, char **argv)
{
    const char *m = argc > 1 ? argv[1] : "none";
    int secs = argc > 2 ? atoi(argv[2]) : 2;
    pthread_mutexattr_t at;
    pthread_t t[4];

    if (!strcmp(m, "none")) mode = M_NONE;
    else if (!strcmp(m, "sem")) mode = M_SEM;
    else if (!strcmp(m, "inherit")) mode = M_INHERIT;
    else if (!strcmp(m, "protect")) mode = M_PROTECT;
    else { fprintf(stderr, "usage: mars <none|sem|inherit|protect> [seconds]\n"); return 2; }

    pthread_mutexattr_init(&at);
    switch (mode) {
    case M_NONE:    pthread_mutexattr_setprotocol(&at, PTHREAD_PRIO_NONE); break;
    case M_INHERIT: pthread_mutexattr_setprotocol(&at, PTHREAD_PRIO_INHERIT); break;
    case M_PROTECT: pthread_mutexattr_setprotocol(&at, PTHREAD_PRIO_PROTECT);
                    pthread_mutexattr_setprioceiling(&at, 30); break;
    default: break;
    }
    pthread_mutex_init(&bus_mx, &at);
    sem_init(&bus_sem, 0, 1);

    {   struct sched_param sp = { .sched_priority = 50 };
        pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp); }
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pf_name("main");
    pf_note("mars mode=%s", m);

    pthread_create(&t[0], NULL, meteo, NULL);
    pthread_create(&t[1], NULL, comms, NULL);
    pthread_create(&t[2], NULL, bus_mgr, NULL);
    pthread_create(&t[3], NULL, watchdog, NULL);

    sleep_ms(secs * 1000);
    running = 0;
    for (int i = 0; i < 4; i++) pthread_join(t[i], NULL);
    printf("mars mode=%s heartbeats=%d watchdog_resets=%d\n", m, heartbeat, resets);
    return resets ? 1 : 0;
}
