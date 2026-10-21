'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface DurationData {
  bucket: string;
  range_start: number;
  range_end: number | null;
  count: number;
  percentage: number;
}

interface DurationChartProps {
  data: DurationData[];
}

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: DurationData & { label: string } }> }) => {
  if (active && payload && payload[0]) {
    const data = payload[0].payload;
    return (
      <div className="bg-background/95 backdrop-blur-sm border border-white/10 rounded-xl shadow-2xl p-4 min-w-[160px]">
        <p className="font-semibold text-sm mb-2">{data.label}</p>
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">
            Calls: <span className="text-foreground font-medium">{data.count}</span>
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

export function DurationChart({ data }: DurationChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    label: item.bucket === '>180' ? '3m+' : `${item.bucket}s`,
    shortLabel: item.bucket === '>180' ? '3m+' : item.bucket === '120-180' ? '2-3m' : item.bucket === '60-120' ? '1-2m' : `${item.bucket}s`,
  }));

  // Find the bucket with the most calls for highlight
  const maxCount = Math.max(...data.map(d => d.count), 0);

  return (
    <Card className="border-white/5 bg-gradient-to-br from-white/[0.03] to-transparent backdrop-blur-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">Duration Distribution</CardTitle>
        <CardDescription className="text-muted-foreground/70">
          How long calls typically last
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="h-[320px] flex flex-col items-center justify-center gap-2">
            <div className="w-16 h-16 rounded-full bg-muted/20 flex items-center justify-center">
              <svg className="w-8 h-8 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground/60">No duration data available</p>
          </div>
        ) : (
          <div className="flex flex-col">
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart
                data={chartData}
                margin={{ top: 10, right: 10, left: -10, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="durationGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#34f5c2" stopOpacity={0.4} />
                    <stop offset="50%" stopColor="#2dd4bf" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#2dd4bf" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="durationStroke" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#34f5c2" />
                    <stop offset="100%" stopColor="#2dd4bf" />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.05)"
                  vertical={false}
                />
                <XAxis
                  dataKey="shortLabel"
                  stroke="rgba(255,255,255,0.2)"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="rgba(255,255,255,0.2)"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="url(#durationStroke)"
                  strokeWidth={2.5}
                  fill="url(#durationGradient)"
                  dot={{
                    r: 4,
                    fill: '#34f5c2',
                    stroke: '#0e3d31',
                    strokeWidth: 2,
                  }}
                  activeDot={{
                    r: 6,
                    fill: '#34f5c2',
                    stroke: 'white',
                    strokeWidth: 2,
                  }}
                />
              </AreaChart>
            </ResponsiveContainer>

            {/* Duration buckets as badges */}
            <div className="mt-4 grid grid-cols-3 sm:grid-cols-6 gap-2 px-1">
              {chartData.map((item, idx) => (
                <div
                  key={idx}
                  className={`text-center py-2 px-2 rounded-lg border transition-colors ${
                    item.count === maxCount && maxCount > 0
                      ? 'border-primary/30 bg-primary/10'
                      : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.04]'
                  }`}
                >
                  <p className={`text-lg font-bold tabular-nums ${
                    item.count === maxCount && maxCount > 0 ? 'text-primary' : ''
                  }`}>
                    {item.count}
                  </p>
                  <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mt-0.5">{item.label}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
