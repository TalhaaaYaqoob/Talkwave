"use client";

import { motion } from 'framer-motion';
import {
    Activity, ArrowRight, ArrowUpRight, Clock, CreditCard,
    Phone, Plug,
    Users, Zap
} from 'lucide-react';
import Link from 'next/link';
import {
    Area, AreaChart, CartesianGrid, ResponsiveContainer,
    Tooltip, XAxis, YAxis
} from 'recharts';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/lib/auth';

const data = [
    { name: 'Mon', calls: 400, minutes: 240 },
    { name: 'Tue', calls: 300, minutes: 139 },
    { name: 'Wed', calls: 200, minutes: 980 },
    { name: 'Thu', calls: 278, minutes: 390 },
    { name: 'Fri', calls: 189, minutes: 480 },
    { name: 'Sat', calls: 239, minutes: 380 },
    { name: 'Sun', calls: 349, minutes: 430 },
];

const StatsCard = ({ title, value, change, icon: Icon, color }: { title: string, value: string, change: string, icon: any, color: string }) => (
    <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        whileHover={{ y: -5 }}
        transition={{ duration: 0.3 }}
    >
        <Card className="glass group border border-white/5 relative overflow-hidden">
            <div className={`absolute -right-6 -top-6 p-4 opacity-5 group-hover:opacity-10 transition-opacity ${color} bg-current rounded-full blur-3xl w-32 h-32`} />

            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0 relative z-10">
                <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
                <div className={`p-2 rounded-lg bg-white/5 ${color} border border-white/5`}>
                    <Icon className="w-4 h-4" />
                </div>
            </CardHeader>
            <CardContent className="relative z-10">
                <div className="text-3xl font-bold text-white">{value}</div>
                <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                    <span className="text-emerald-400 flex items-center bg-emerald-400/10 px-1 rounded border border-emerald-400/20">
                        <ArrowUpRight className="w-3 h-3 mr-1" /> {change}
                    </span>
                    from last month
                </p>
            </CardContent>
        </Card>
    </motion.div>
);

export default function OverviewPage() {
    const { user, provider } = useAuth();
    const isOSSMode = provider !== 'stack';

    // Animation variants
    const container = {
        hidden: { opacity: 0 },
        show: {
            opacity: 1,
            transition: {
                staggerChildren: 0.1
            }
        }
    };

    return (
        <div className="p-8 max-w-[1600px] mx-auto space-y-8">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-white">
                        {isOSSMode ? (
                            "Dashboard"
                        ) : (
                            <span className="bg-clip-text text-transparent bg-gradient-to-r from-white to-white/60">
                                Good afternoon, {(user as any)?.displayName?.split(' ')[0] || (user as any)?.name?.split(' ')[0] || 'Creator'}
                            </span>
                        )}
                    </h1>
                    <p className="text-muted-foreground mt-1">
                        Here's what's happening with your agents today.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" className="glass hover:bg-white/10 text-white border-white/10">
                        <Clock className="mr-2 h-4 w-4" /> Last 7 Days
                    </Button>
                    <Link href="/workflow/create">
                        <Button className="bg-white text-black hover:bg-gray-200 shadow-lg shadow-white/5 font-semibold">
                            <Zap className="mr-2 h-4 w-4" /> New Agent
                        </Button>
                    </Link>
                </div>
            </div>

            {/* Stats Grid */}
            <motion.div
                variants={container}
                initial="hidden"
                animate="show"
                className="grid gap-4 md:grid-cols-2 lg:grid-cols-4"
            >
                <StatsCard title="Total Calls" value="2,845" change="+12.5%" icon={Phone} color="text-primary" />
                <StatsCard title="Active Agents" value="14" change="+4" icon={Users} color="text-purple-400" />
                <StatsCard title="Minutes Used" value="14,230" change="+8.2%" icon={Activity} color="text-pink-400" />
                <StatsCard title="Cost" value="$420.50" change="+2.1%" icon={CreditCard} color="text-orange-400" />
            </motion.div>

            {/* Main Content Grid */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
                {/* Chart Section */}
                <Card className="col-span-4 glass border-white/5">
                    <CardHeader>
                        <CardTitle className="text-white">Call Volume</CardTitle>
                        <CardDescription className="text-muted-foreground">
                            Use the chart below to analyze call traffic over the last week.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="pl-2">
                        <div className="h-[350px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={data}>
                                    <defs>
                                        <linearGradient id="colorCalls" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.3} />
                                            <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" className="stroke-white/5" vertical={false} />
                                    <XAxis
                                        dataKey="name"
                                        stroke="#525252"
                                        fontSize={12}
                                        tickLine={false}
                                        axisLine={false}
                                    />
                                    <YAxis
                                        stroke="#525252"
                                        fontSize={12}
                                        tickLine={false}
                                        axisLine={false}
                                        tickFormatter={(value) => `${value}`}
                                    />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0A0A0A', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', color: '#fff' }}
                                        cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }}
                                    />
                                    <Area
                                        type="monotone"
                                        dataKey="calls"
                                        stroke="var(--primary)"
                                        strokeWidth={2}
                                        fillOpacity={1}
                                        fill="url(#colorCalls)"
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </CardContent>
                </Card>

                {/* Recent Activity */}
                <Card className="col-span-3 glass border-white/5 flex flex-col">
                    <CardHeader>
                        <CardTitle className="text-white">Recent Activity</CardTitle>
                        <CardDescription className="text-muted-foreground">
                            Real-time logs from your active agents.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex-1 overflow-auto pr-2">
                        <div className="space-y-6">
                            {[
                                { agent: "Sales Bot Alpha", action: "Completed call", time: "2m ago", status: "success" },
                                { agent: "Support Helper", action: "Transferred to human", time: "15m ago", status: "warning" },
                                { agent: "Appointment Setter", action: "Booked slot", time: "1h ago", status: "success" },
                                { agent: "Survey Bot", action: "Failed to connect", time: "3h ago", status: "error" },
                                { agent: "Sales Bot Alpha", action: "Completed call", time: "4h ago", status: "success" },
                            ].map((item, i) => (
                                <div key={i} className="flex items-center justify-between group cursor-pointer hover:bg-white/5 p-2 rounded-lg transition-colors">
                                    <div className="flex items-center space-x-4">
                                        <div className={`w-2 h-2 rounded-full ${item.status === 'success' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' :
                                            item.status === 'warning' ? 'bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.5)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'
                                            }`} />
                                        <div className="space-y-1">
                                            <p className="text-sm font-medium leading-none text-white">{item.agent}</p>
                                            <p className="text-xs text-muted-foreground">{item.action}</p>
                                        </div>
                                    </div>
                                    <div className="flex items-center text-xs text-muted-foreground">
                                        {item.time}
                                        <ArrowRight className="ml-2 w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-white" />
                                    </div>
                                </div>
                            ))}
                        </div>
                        <Button variant="ghost" className="w-full mt-6 text-xs text-muted-foreground hover:text-white hover:bg-white/5">
                            View All Activity
                        </Button>
                    </CardContent>
                </Card>
            </div>

            {/* Config Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Link href="/workflow" className="group">
                    <Card className="glass border-white/5 hover:border-primary/50 transition-all duration-300 h-full group-hover:bg-white/5">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors text-white">
                                <Users className="w-5 h-5" /> Manage Agents
                            </CardTitle>
                            <CardDescription className="text-muted-foreground">
                                Create, edit, and deploy your voice AI workforce.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                                <div className="h-full w-3/4 bg-primary shadow-[0_0_10px_var(--primary)]" />
                            </div>
                            <p className="text-xs text-muted-foreground mt-2">14/20 Agents Active</p>
                        </CardContent>
                    </Card>
                </Link>

                <Link href="/integrations" className="group">
                    <Card className="glass border-white/5 hover:border-primary/50 transition-all duration-300 h-full group-hover:bg-white/5">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors text-white">
                                <Plug className="w-5 h-5" /> Integrations
                            </CardTitle>
                            <CardDescription className="text-muted-foreground">
                                Connect Gmail, Twilio, and other services to your agents.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="flex gap-2">
                            <Badge variant="secondary" className="bg-white/5 text-white hover:bg-white/10 border-white/10">Gmail</Badge>
                            <Badge variant="secondary" className="bg-white/5 text-white hover:bg-white/10 border-white/10">Twilio</Badge>
                            <Badge variant="secondary" className="bg-white/5 text-white hover:bg-white/10 border-white/10">WhatsApp</Badge>
                        </CardContent>
                    </Card>
                </Link>
            </div>
        </div>
    );
}
