# ⚡ Real-Time Bidding Platform

A production-style **Real-Time Bidding (RTB) platform** that simulates a programmatic advertising auction system with concurrent DSP bidding, strict auction deadlines, Redis caching, Kafka-based event streaming, PostgreSQL persistence, fault tolerance, and real-time observability.

The system is designed around a latency-sensitive auction path where multiple Demand-Side Platforms (DSPs) compete to serve an advertisement for a publisher's ad slot.

> **Core engineering focus:** concurrency, low-latency systems, distributed event processing, caching, fault tolerance, idempotency, and performance optimization.

---

## 🚀 Overview

In a real-time bidding system, an ad opportunity can trigger multiple advertisers or DSPs to compete for the same impression.

The platform receives an ad request, identifies eligible campaigns, concurrently requests bids from multiple DSPs, validates the responses, selects a winner, and returns the winning advertisement within a strict latency budget.

A simplified flow is:

```text
                         Ad Request
                              │
                              ▼
                     ┌─────────────────┐
                     │  Auction API    │
                     └────────┬────────┘
                              │
                    Retrieve campaign
                       / targeting data
                              │
                              ▼
                         ┌────────┐
                         │ Redis  │
                         └───┬────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Auction Engine │
                    └────────┬────────┘
                             │
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
          DSP A            DSP B            DSP C
        20ms response    45ms response    120ms timeout
             │               │
             └───────────────┼───────────────┘
                             ▼
                     Bid Validation
                             │
                             ▼
                     Winner Selection
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              Auction Result       Kafka
                                      │
                         ┌────────────┼────────────┐
                         ▼            ▼            ▼
                     Analytics      Audit      Monitoring
