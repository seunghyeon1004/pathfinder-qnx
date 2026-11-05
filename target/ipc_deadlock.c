/*
 * ipc_deadlock.c - a classic QNX message-passing deadlock.
 *
 * Two single-threaded "servers" (think: two resource managers) each own a channel:
 *
 *    ping server  <---- client 1 sends "ping"
 *    pong server  <---- client 2 sends "pong"
 *
 * While handling a request each server calls the OTHER server (MsgSend) before it replies.
 * If both requests arrive together, ping blocks in MsgSend() to pong's channel, pong blocks in
 * MsgSend() to ping's channel, and neither ever returns to MsgReceive(): a cycle of SEND-blocked
 * threads. Every client is REPLY-blocked behind its server.
 *
 * Modes (argv[1]):
 *   bug   server calls the peer synchronously before replying   -> deadlock (watchdog timeouts break it)
 *   fix   server replies first, then notifies the peer with MsgSendPulse (no blocking call in the handler)
 *
 * usage: ipc_deadlock <bug|fix> [rounds]
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/siginfo.h>
#include "pf_mark.h"

#define TMO_NS 1200000000ULL        /* break the deadlock after 1.2 s so the demo terminates */

static int chid_ping, chid_pong;
static int fixed;
static volatile int deadlocks;

struct msg { int type; int hops; };

static void sleep_ms(int ms) { struct timespec t = { ms / 1000, (long)(ms % 1000) * 1000000L }; nanosleep(&t, NULL); }

static void prio(const char *name, int p)
{
    struct sched_param sp = { .sched_priority = p };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    pthread_setname_np(pthread_self(), name);
    pf_name("%s", name);
}

static void *server(void *arg)
{
    int mine = (intptr_t)arg ? chid_pong : chid_ping;
    int peer = (intptr_t)arg ? chid_ping : chid_pong;
    const char *nm = (intptr_t)arg ? "pong_srv" : "ping_srv";
    int coid = ConnectAttach(0, 0, peer, _NTO_SIDE_CHANNEL, 0);
    struct msg m, r;
    prio(nm, 30);
    for (;;) {
        int rcvid = MsgReceive(mine, &m, sizeof m, NULL);
        if (rcvid <= 0) {                    /* pulse or error */
            if (rcvid == 0 && m.type == 99) break;
            continue;
        }
        if (m.type == 99) { MsgReply(rcvid, 0, NULL, 0); break; }
        sleep_ms(5);                          /* some work */
        if (m.type == 2) {                    /* request coming from the peer: just answer */
            MsgReply(rcvid, 0, &m, sizeof m);
        } else if (!fixed) {
            /* BUG: a blocking call to the other server while a client is still waiting for our reply */
            uint64_t tmo = TMO_NS;
            struct msg q = { 2, m.hops + 1 };
            pf_note("%s: calling peer from handler", nm);
            /* TimerTimeout() arms the NEXT blocking kernel call only, so nothing may come between it and MsgSend() */
            TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND | _NTO_TIMEOUT_REPLY, NULL, &tmo, NULL);
            if (MsgSend(coid, &q, sizeof q, &r, sizeof r) == -1 && errno == ETIMEDOUT) {
                deadlocks++;
                pf_note("DEADLOCK: %s timed out waiting for peer", nm);
                printf("DEADLOCK suspected: %s timed out in MsgSend to its peer after 1.2 s\n", nm);
                fflush(stdout);
            }
            MsgReply(rcvid, 0, &m, sizeof m);
        } else {
            /* FIX: reply first, then tell the peer with a pulse (never blocks) */
            MsgReply(rcvid, 0, &m, sizeof m);
            MsgSendPulse(coid, 30, 1, m.hops + 1);
        }
    }
    return NULL;
}

static void *client(void *arg)
{
    int which = (intptr_t)arg;
    int coid = ConnectAttach(0, 0, which ? chid_pong : chid_ping, _NTO_SIDE_CHANNEL, 0);
    struct msg m = { 1, 0 }, r;
    prio(which ? "client2" : "client1", 20);
    sleep_ms(100);
    pf_note("%s: sending request", which ? "client2" : "client1");
    MsgSend(coid, &m, sizeof m, &r, sizeof r);
    pf_note("%s: reply received", which ? "client2" : "client1");
    return NULL;
}

int main(int argc, char **argv)
{
    pthread_t s[2], c[2];
    fixed = argc > 1 && !strcmp(argv[1], "fix");
    if (argc > 1 && strcmp(argv[1], "fix") && strcmp(argv[1], "bug")) {
        fprintf(stderr, "usage: ipc_deadlock <bug|fix>\n");
        return 2;
    }
    chid_ping = ChannelCreate(0);
    chid_pong = ChannelCreate(0);
    pf_name("main");
    pf_note("ipc_deadlock mode=%s", fixed ? "fix" : "bug");
    pthread_create(&s[0], NULL, server, (void *)0);
    pthread_create(&s[1], NULL, server, (void *)1);
    pthread_create(&c[0], NULL, client, (void *)0);
    pthread_create(&c[1], NULL, client, (void *)1);
    pthread_join(c[0], NULL);
    pthread_join(c[1], NULL);
    sleep_ms(200);
    /* stop servers */
    int a = ConnectAttach(0, 0, chid_ping, _NTO_SIDE_CHANNEL, 0), b = ConnectAttach(0, 0, chid_pong, _NTO_SIDE_CHANNEL, 0);
    struct msg q = { 99, 0 }, r;
    MsgSend(a, &q, sizeof q, &r, sizeof r);
    MsgSend(b, &q, sizeof q, &r, sizeof r);
    pthread_join(s[0], NULL);
    pthread_join(s[1], NULL);
    printf("ipc_deadlock mode=%s deadlocks_broken_by_timeout=%d\n", fixed ? "fix" : "bug", deadlocks);
    return deadlocks ? 1 : 0;
}
