/* inversion.c - the smallest priority-inversion demo for QNX 8.0 (codelab step 2).
 * L (prio 10) holds a lock for 60 ms, M (prio 20) burns CPU for 150 ms, H (prio 30) wants the lock.
 * All threads are pinned to CPU 0 so the result is deterministic.
 * usage: inversion none|inherit        build: qcc -Vgcc_ntox86_64 -o inversion inversion.c
 * SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <sys/neutrino.h>

static pthread_mutex_t m;

static long long now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000LL + t.tv_nsec / 1000000; }
static void busy(int ms) { long long e = now_ms() + ms; while (now_ms() < e) { } }
static void nap(int ms) { struct timespec t = { 0, ms * 1000000L }; nanosleep(&t, NULL); }
static void me(const char *name, int prio)
{
    struct sched_param sp = { .sched_priority = prio };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)1);
    pthread_setname_np(pthread_self(), name);
}

static void *low(void *a)  { me("L", 10); pthread_mutex_lock(&m); busy(60); pthread_mutex_unlock(&m); return NULL; }
static void *med(void *a)  { me("M", 20); nap(20); busy(150); return NULL; }
static void *high(void *a)
{
    me("H", 30);
    nap(40);
    long long t = now_ms();
    pthread_mutex_lock(&m);
    printf("H waited %lld ms for the lock\n", now_ms() - t);
    pthread_mutex_unlock(&m);
    return NULL;
}

int main(int argc, char **argv)
{
    pthread_mutexattr_t at;
    pthread_t t[3];
    pthread_mutexattr_init(&at);
    pthread_mutexattr_setprotocol(&at, argc > 1 && !strcmp(argv[1], "inherit") ? PTHREAD_PRIO_INHERIT : PTHREAD_PRIO_NONE);
    pthread_mutex_init(&m, &at);
    me("main", 40);
    pthread_create(&t[0], NULL, low, NULL);
    nap(5);
    pthread_create(&t[1], NULL, med, NULL);
    pthread_create(&t[2], NULL, high, NULL);
    for (int i = 0; i < 3; i++) pthread_join(t[i], NULL);
    return 0;
}
