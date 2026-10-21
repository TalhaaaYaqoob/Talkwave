"use client";

import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, BarChart2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export const SonicWaveformCanvas = () => {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) return;

        let animationFrameId: number;
        let isVisible = true;
        const mouse = { x: 0, y: 0 };
        let mouseSet = false;
        let time = 0;
        let w = 0;
        let h = 0;
        let lastFrame = 0;
        const FRAME_INTERVAL = 1000 / 30; // cap at 30fps

        const resizeCanvas = () => {
            const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
            w = canvas.clientWidth;
            h = canvas.clientHeight;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            if (!mouseSet) {
                mouse.x = w / 2;
                mouse.y = h / 2;
            }
        };

        const draw = (now: number) => {
            animationFrameId = requestAnimationFrame(draw);

            if (!isVisible) return;

            const delta = now - lastFrame;
            if (delta < FRAME_INTERVAL) return;
            lastFrame = now - (delta % FRAME_INTERVAL);

            ctx.fillStyle = '#050a0a';
            ctx.fillRect(0, 0, w, h);

            const lineCount = 20;
            const segmentCount = 40;
            const centerY = h / 2;

            for (let i = 0; i < lineCount; i++) {
                ctx.beginPath();
                const colorIntensity = Math.sin((i / lineCount) * Math.PI);
                ctx.strokeStyle = `rgba(52,245,194,${colorIntensity * 0.45})`;
                ctx.lineWidth = 1.5;

                for (let j = 0; j <= segmentCount; j++) {
                    const x = (j / segmentCount) * w;
                    const distToMouse = Math.hypot(x - mouse.x, centerY - mouse.y);
                    const mouseEffect = Math.max(0, 1 - distToMouse / 400);
                    const noise = Math.sin(j * 0.1 + time + i * 0.2) * 20;
                    const spike = Math.cos(j * 0.2 + time + i * 0.1) * Math.sin(j * 0.05 + time) * 50;
                    const y = centerY + noise + spike * (1 + mouseEffect * 2);

                    if (j === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                }
                ctx.stroke();
            }

            time += 0.02;
        };

        const handleMouseMove = (event: MouseEvent) => {
            mouse.x = event.clientX;
            mouse.y = event.clientY;
            mouseSet = true;
        };

        const observer = new IntersectionObserver(
            ([entry]) => { isVisible = entry.isIntersecting; },
            { threshold: 0.05 },
        );
        observer.observe(canvas);

        window.addEventListener('resize', resizeCanvas, { passive: true });
        window.addEventListener('mousemove', handleMouseMove, { passive: true });

        resizeCanvas();
        animationFrameId = requestAnimationFrame(draw);

        return () => {
            cancelAnimationFrame(animationFrameId);
            observer.disconnect();
            window.removeEventListener('resize', resizeCanvas);
            window.removeEventListener('mousemove', handleMouseMove);
        };
    }, []);

    return <canvas ref={canvasRef} className="absolute inset-0 z-0 w-full h-full bg-[#050a0a]" />;
};


// The main hero component
const SonicWaveformHero = () => {
    const fadeUpVariants = {
        hidden: { opacity: 0, y: 20 },
        visible: (i: number) => ({
            opacity: 1,
            y: 0,
            transition: {
                delay: i * 0.2 + 0.5,
                duration: 0.8,
                ease: "easeInOut" as const,
            },
        }),
    };

    return (
        <div 
            className="relative h-screen w-full flex flex-col items-center justify-center overflow-hidden"
        >
            <SonicWaveformCanvas />
            
            <div className="absolute inset-0 bg-gradient-to-t from-black via-black/30 to-transparent z-10"></div>

            {/* Overlay HTML Content */}
            <div className="relative z-20 text-center p-6">
                <motion.div
                    custom={0} variants={fadeUpVariants} initial="hidden" animate="visible"
                    className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-teal-500/10 border border-teal-500/20 mb-6 backdrop-blur-sm"
                >
                    <BarChart2 className="h-4 w-4 text-teal-300" />
                    <span className="text-sm font-medium text-gray-200">
                        Real-Time Data Sonification
                    </span>
                </motion.div>

                <motion.h1
                    custom={1} variants={fadeUpVariants} initial="hidden" animate="visible"
                    className="text-5xl md:text-7xl font-bold tracking-tighter mb-6 bg-clip-text text-transparent bg-gradient-to-b from-white to-gray-400"
                >
                    Sonic Waveform
                </motion.h1>

                <motion.p
                    custom={2} variants={fadeUpVariants} initial="hidden" animate="visible"
                    className="max-w-2xl mx-auto text-lg text-gray-400 mb-10"
                >
                    Translate complex data streams into intuitive, interactive soundscapes. Hear the patterns, feel the insights.
                </motion.p>

                <motion.div
                    custom={3} variants={fadeUpVariants} initial="hidden" animate="visible"
                >
                    <button className="px-8 py-4 bg-white text-black font-semibold rounded-lg shadow-lg hover:bg-gray-200 transition-colors duration-300 flex items-center gap-2 mx-auto">
                        Analyze the Stream
                        <ArrowRight className="h-5 w-5" />
                    </button>
                </motion.div>
            </div>
        </div>
    );
};

export default SonicWaveformHero;
