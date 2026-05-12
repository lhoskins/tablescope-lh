"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Props = {
  data: Array<Record<string, number | string>>;
  xKey: string;
  yKey: string;
};

export function SimpleLineChart({ data, xKey, yKey }: Props) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey={xKey} stroke="#475569" />
        <YAxis stroke="#475569" />
        <Tooltip />
        <Line
          type="monotone"
          dataKey={yKey}
          stroke="var(--brand-color)"
          strokeWidth={2}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
