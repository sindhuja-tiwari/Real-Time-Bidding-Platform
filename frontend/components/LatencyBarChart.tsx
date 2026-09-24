"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function LatencyBarChart({
  p50,
  p95,
  p99,
}: {
  p50: number;
  p95: number;
  p99: number;
}) {
  const data = [
    { name: "P50", ms: p50 },
    { name: "P95", ms: p95 },
    { name: "P99", ms: p99 },
  ];
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="name" stroke="#64748b" />
        <YAxis stroke="#64748b" unit="ms" />
        <Tooltip
          contentStyle={{ background: "#111827", border: "1px solid #1e293b", borderRadius: 8 }}
          labelStyle={{ color: "#e2e8f0" }}
        />
        <Bar dataKey="ms" fill="#22d3ee" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
