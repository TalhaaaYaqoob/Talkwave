'use client';

import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface DispositionData {
  disposition: string;
  count: number;
  percentage: number;
}

interface DispositionChartProps {
  data: DispositionData[];
}

const COLORS = [
  '#34f5c2', // sonic mint
  '#10b981', // emerald-500
  '#f59e0b', // amber-500
  '#8b5cf6', // violet-500
  '#ef4444', // red-500
  '#06b6d4', // cyan-500
  '#f97316', // orange-500
  '#ec4899', // pink-500
  '#14b8a6', // teal-500
  '#6b7280', // gray-500
];

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: DispositionData & { fill: string } }> }) => {
  if (active && payload && payload[0]) {
    const data = payload[0].payload;
    return (
      <div className="bg-background/95 backdrop-blur-sm border border-white/10 rounded-xl shadow-2xl p-4 min-w-[160px]">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: data.fill }} />
          <p className="font-semibold text-sm">{data.disposition}</p>
        </div>
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">
            Count: <span className="text-foreground font-medium">{data.count}</span>
          </p>
          <p className="text-sm text-muted-foreground">
            Share: <span className="text-foreground font-medium">{data.percentage}%</span>
          </p>
        </div>
      </div>
    );
  }
  return null;
};

const renderCustomLabel = ({
  cx, cy, midAngle, innerRadius, outerRadius, percentage,
}: {
  cx: number; cy: number; midAngle: number; innerRadius: number; outerRadius: number; percentage: number;
}) => {
  if (percentage < 5) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);

  return (
    <text
      x={x}
      y={y}
      fill="white"
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={12}
      fontWeight={600}
    >
      {`${percentage}%`}
    </text>
  );
};

export function DispositionChart({ data }: DispositionChartProps) {
  const chartData = data.map((item, index) => ({
    ...item,
    fill: COLORS[index % COLORS.length],
  }));

  return (
    <Card className="border-white/5 bg-gradient-to-br from-white/[0.03] to-transparent backdrop-blur-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">Disposition Breakdown</CardTitle>
        <CardDescription className="text-muted-foreground/70">
          Call outcomes distribution
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="h-[320px] flex flex-col items-center justify-center gap-2">
            <div className="w-16 h-16 rounded-full bg-muted/20 flex items-center justify-center">
              <svg className="w-8 h-8 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground/60">No disposition data available</p>
          </div>
        ) : (
          <div className="flex flex-col">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={110}
                  paddingAngle={3}
                  dataKey="count"
                  label={renderCustomLabel}
                  labelLine={false}
                  strokeWidth={0}
                >
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.fill}
                      className="transition-opacity hover:opacity-80"
                    />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
                <Legend
                  verticalAlign="bottom"
                  height={36}
                  iconType="circle"
                  iconSize={8}
                  formatter={(value: string) => (
                    <span className="text-xs text-muted-foreground">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>

            {/* Stats list below the chart */}
            <div className="mt-4 space-y-2 px-2">
              {chartData.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between py-1.5 px-3 rounded-lg hover:bg-white/[0.03] transition-colors">
                  <div className="flex items-center gap-2.5">
                    <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item.fill }} />
                    <span className="text-sm text-muted-foreground truncate max-w-[140px]">{item.disposition}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium tabular-nums">{item.count}</span>
                    <span className="text-xs text-muted-foreground/60 tabular-nums w-12 text-right">{item.percentage}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
