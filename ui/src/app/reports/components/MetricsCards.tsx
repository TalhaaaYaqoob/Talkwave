'use client';

import { ArrowUpRight, Phone, PhoneForwarded, TrendingUp } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';

interface MetricsCardsProps {
  metrics: {
    total_runs: number;
    xfer_count: number;
  };
}

export function MetricsCards({ metrics }: MetricsCardsProps) {
  const transferRate = metrics.total_runs > 0
    ? ((metrics.xfer_count / metrics.total_runs) * 100).toFixed(1)
    : '0.0';

  const cards = [
    {
      title: 'Total Calls',
      value: metrics.total_runs.toLocaleString(),
      subtitle: 'Calls processed today',
      icon: Phone,
      gradient: 'from-primary/20 to-teal-500/20',
      iconBg: 'bg-primary/20',
      iconColor: 'text-primary',
      borderColor: 'border-primary/20',
    },
    {
      title: 'Transfers',
      value: metrics.xfer_count.toLocaleString(),
      subtitle: 'Calls transferred (XFER)',
      icon: PhoneForwarded,
      gradient: 'from-emerald-500/20 to-teal-500/20',
      iconBg: 'bg-emerald-500/20',
      iconColor: 'text-emerald-400',
      borderColor: 'border-emerald-500/20',
    },
    {
      title: 'Transfer Rate',
      value: `${transferRate}%`,
      subtitle: 'Of total calls transferred',
      icon: TrendingUp,
      gradient: 'from-violet-500/20 to-purple-500/20',
      iconBg: 'bg-violet-500/20',
      iconColor: 'text-violet-400',
      borderColor: 'border-violet-500/20',
    },
    {
      title: 'Completion Rate',
      value: metrics.total_runs > 0
        ? `${(100 - parseFloat(transferRate)).toFixed(1)}%`
        : '0.0%',
      subtitle: 'Calls handled by AI',
      icon: ArrowUpRight,
      gradient: 'from-amber-500/20 to-orange-500/20',
      iconBg: 'bg-amber-500/20',
      iconColor: 'text-amber-400',
      borderColor: 'border-amber-500/20',
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => (
        <Card
          key={card.title}
          className={`relative overflow-hidden border ${card.borderColor} bg-gradient-to-br ${card.gradient} backdrop-blur-sm`}
        >
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-medium text-muted-foreground">{card.title}</p>
              <div className={`p-2 rounded-lg ${card.iconBg}`}>
                <card.icon className={`h-4 w-4 ${card.iconColor}`} />
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-3xl font-bold tracking-tight">{card.value}</p>
              <p className="text-xs text-muted-foreground">{card.subtitle}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
