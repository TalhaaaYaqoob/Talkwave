"use client";

import { cn } from "@/lib/utils";
import React from "react";
import { motion } from "framer-motion";
import { SpotlightCard } from "@/components/ui/spotlight";

interface FeatureItem {
  title: string;
  description: string;
  icon: React.ReactNode;
}

export function FeaturesSectionWithHoverEffects({
  features,
}: {
  features: FeatureItem[];
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 relative z-10 py-10 max-w-7xl mx-auto">
      {features.map((feature, index) => (
        <Feature key={feature.title} {...feature} index={index} total={features.length} />
      ))}
    </div>
  );
}

const Feature = ({
  title,
  description,
  icon,
  index,
  total,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  index: number;
  total: number;
}) => {
  const isFeatured = index < 2 && total > 6;

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.5, delay: index * 0.04 }}
      className={cn(isFeatured && "md:col-span-2")}
    >
      <SpotlightCard
        className={cn(
          "h-full rounded-2xl border border-white/[0.06] bg-[#111] group/feature",
          "hover:border-white/[0.15] transition-all duration-300"
        )}
        spotlightColor="rgba(52, 245, 194, 0.06)"
      >
        <div className={cn("flex flex-col p-6", isFeatured ? "sm:p-8" : "sm:p-6")}>
          <div
            className={cn(
              "mb-5 flex items-center justify-center rounded-xl",
              "w-11 h-11 bg-[#34F5C2]/[0.08] border border-[#34F5C2]/[0.14]",
              "group-hover/feature:animate-pulse-glow transition-all duration-300"
            )}
          >
            <div className="text-[#34F5C2]">{icon}</div>
          </div>

          <h3
            className={cn(
              "font-semibold text-white mb-2 tracking-tight",
              isFeatured ? "text-xl" : "text-lg"
            )}
          >
            {title}
          </h3>

          <p
            className={cn(
              "text-sm text-[#9CA3AF] leading-relaxed",
              isFeatured ? "max-w-md" : "max-w-xs"
            )}
          >
            {description}
          </p>

          <div className="mt-auto pt-5">
            <div className="h-px w-full bg-gradient-to-r from-[#34F5C2]/30 via-[#34F5C2]/10 to-transparent" />
          </div>
        </div>
      </SpotlightCard>
    </motion.div>
  );
};
