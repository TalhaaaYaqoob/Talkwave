'use client';

import {
    Globe, Upload, X, Building2, UtensilsCrossed,
    HeartPulse, ShoppingBag, Landmark, ArrowLeft, Link2, Plus, Trash2, Mic,
    Search, Smile, Pill, Dog, Dumbbell, Flower2, ShieldCheck, Calculator,
    ShoppingCart, Apple, Scale, Briefcase, Users, Megaphone, Home, Wrench,
    Sparkles, GraduationCap, BookOpen, Cloud, Monitor, Phone, MapPin, Clock,
    Car, Settings, Plane, CalendarDays, Scissors, Truck, HardHat, Building,
    HeartHandshake, Ticket, Camera, Coffee, CakeSlice, Bed, CircleDot, Mail,
    FileText, Book,
    type LucideIcon
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState, useCallback, useEffect, useRef, useMemo } from 'react';

import { createWorkflowApiV1WorkflowCreateDefinitionPost } from '@/client/sdk.gen';
import { AILoader } from '@/components/ui/ai-loader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';

const BLANK_WORKFLOW_DEFINITION = {
    nodes: [
        { id: "start-1", type: "startCall", position: { x: 400, y: 100 }, data: { prompt: "Hello! How can I help you today?", name: "Start Call", is_start: true, is_static: false, allow_interrupt: false }, measured: { width: 300, height: 100 } },
        { id: "end-1", type: "endCall", position: { x: 400, y: 400 }, data: { prompt: "Thank you for calling. Goodbye!", name: "End Call", is_end: true, is_static: false, allow_interrupt: false }, measured: { width: 300, height: 100 } },
    ],
    edges: [{ animated: true, type: "custom", source: "start-1", target: "end-1", id: "edge-start-end", data: { condition: "", label: "" } }],
    viewport: { x: 0, y: 0, zoom: 1 },
};

const BLANK_MEETING_WORKFLOW_DEFINITION = {
    nodes: [
        { id: "trigger-1", type: "meetingTrigger", position: { x: 400, y: 100 }, data: { name: "Wake Word Trigger", trigger_config: { mode: "wake_word", wake_words: ["hey agent"], cooldown_seconds: 2 }, response_prompt: "Respond helpfully and concisely to the question based on the meeting context.", max_response_tokens: 300 }, measured: { width: 300, height: 100 } },
        { id: "agent-1", type: "agentNode", position: { x: 400, y: 350 }, data: { name: "Meeting Assistant", prompt: "You are a helpful meeting assistant. Answer questions based on the meeting context and knowledge base. Be concise and direct — do not introduce yourself or use call-style greetings.", is_static: false, allow_interrupt: true, add_global_prompt: true }, measured: { width: 300, height: 100 } },
        { id: "summary-1", type: "meetingSummary", position: { x: 400, y: 600 }, data: { name: "Meeting Summary", summary_config: { mode: "end_of_meeting", include_action_items: true, include_decisions: true, include_key_points: true }, output_format: "markdown" }, measured: { width: 300, height: 100 } },
    ],
    edges: [
        { animated: true, type: "custom", source: "trigger-1", target: "agent-1", id: "edge-trigger-agent", data: { condition: "", label: "" } },
        { animated: true, type: "custom", source: "agent-1", target: "summary-1", id: "edge-agent-summary", data: { condition: "", label: "" } },
    ],
    viewport: { x: 0, y: 0, zoom: 1 },
};

type CreationMode = 'industry' | 'ai-generated' | 'blank';
type AIMode = 'describe' | 'website';

interface AudioFile {
    id: string;
    file: File;
    name: string;
    size: number;
}

type IndustryKey =
    | 'restaurant' | 'hotel' | 'cafe' | 'bakery'
    | 'healthcare' | 'dental' | 'pharmacy' | 'veterinary' | 'fitness' | 'spa'
    | 'banking' | 'insurance' | 'accounting'
    | 'retail' | 'ecommerce' | 'grocery'
    | 'legal' | 'consulting' | 'recruitment' | 'marketing'
    | 'real_estate' | 'property_management' | 'home_services' | 'cleaning'
    | 'education' | 'tutoring'
    | 'saas' | 'it_support' | 'telecom'
    | 'auto_dealership' | 'auto_repair'
    | 'travel' | 'event_planning'
    | 'salon'
    | 'logistics' | 'construction'
    | 'government' | 'nonprofit'
    | 'entertainment' | 'photography'
    | 'pet_services';

type CategoryKey =
    | 'all'
    | 'food-hospitality' | 'healthcare-wellness' | 'financial-services'
    | 'retail-ecommerce' | 'professional-services' | 'home-property'
    | 'education-training' | 'technology' | 'automotive'
    | 'travel-leisure' | 'beauty-personal' | 'logistics-industrial'
    | 'government-nonprofit' | 'media-entertainment' | 'pet-services';

interface IndustryDef {
    key: IndustryKey;
    label: string;
    category: CategoryKey;
    description: string;
    icon: LucideIcon;
    placeholder: string;
    hoursPlaceholder?: string;
    locationPlaceholder?: string;
    servicesPlaceholder?: string;
    policiesPlaceholder?: string;
}

interface BusinessInfo {
    business_hours: string;
    location: string;
    phone: string;
    email: string;
    services: string;
    policies: string;
}

const CATEGORIES: { key: CategoryKey; label: string; icon: LucideIcon }[] = [
    { key: 'all', label: 'All Industries', icon: CircleDot },
    { key: 'food-hospitality', label: 'Food & Hospitality', icon: UtensilsCrossed },
    { key: 'healthcare-wellness', label: 'Healthcare & Wellness', icon: HeartPulse },
    { key: 'financial-services', label: 'Financial Services', icon: Landmark },
    { key: 'retail-ecommerce', label: 'Retail & E-Commerce', icon: ShoppingBag },
    { key: 'professional-services', label: 'Professional Services', icon: Briefcase },
    { key: 'home-property', label: 'Home & Property', icon: Home },
    { key: 'education-training', label: 'Education & Training', icon: GraduationCap },
    { key: 'technology', label: 'Technology', icon: Cloud },
    { key: 'automotive', label: 'Automotive', icon: Car },
    { key: 'travel-leisure', label: 'Travel & Leisure', icon: Plane },
    { key: 'beauty-personal', label: 'Beauty & Personal Care', icon: Scissors },
    { key: 'logistics-industrial', label: 'Logistics & Industrial', icon: Truck },
    { key: 'government-nonprofit', label: 'Government & Nonprofit', icon: Building },
    { key: 'media-entertainment', label: 'Media & Entertainment', icon: Ticket },
    { key: 'pet-services', label: 'Pet Services', icon: Dog },
];

const INDUSTRIES: IndustryDef[] = [
    // Food & Hospitality
    { key: 'restaurant', label: 'Restaurant', category: 'food-hospitality', description: 'Reservations, orders, menu info, catering, and more', icon: UtensilsCrossed, placeholder: "Describe your cuisine, dining options (dine-in, takeout, delivery), specialties, and what makes your restaurant unique.", hoursPlaceholder: "e.g., Tue-Sun 11am-10pm, Closed Monday", servicesPlaceholder: "e.g., Dine-in, Takeout, Delivery, Catering, Private Events", policiesPlaceholder: "e.g., Reservations for parties of 6+, No outside food, Corkage fee $25" },
    { key: 'hotel', label: 'Hotel & Hospitality', category: 'food-hospitality', description: 'Room bookings, concierge, check-in/out, amenities, and guest services', icon: Bed, placeholder: "Describe your property type, room types, amenities, and what makes your hotel special.", hoursPlaceholder: "e.g., Front desk 24/7, Pool 7am-10pm, Restaurant 6am-11pm", servicesPlaceholder: "e.g., Room Service, Valet, Airport Shuttle, Spa, Conference Rooms", policiesPlaceholder: "e.g., Check-in 3pm, Check-out 11am, Cancellation 48hrs, Pet-friendly floors 3-5" },
    { key: 'cafe', label: 'Coffee Shop & Cafe', category: 'food-hospitality', description: 'Menu, hours, mobile orders, catering, loyalty, and event space', icon: Coffee, placeholder: "Describe your coffee/tea offerings, food menu, atmosphere, and any special programs like subscriptions.", hoursPlaceholder: "e.g., Daily 6am-6pm", servicesPlaceholder: "e.g., Dine-in, Mobile Order, Catering, Coffee Subscription", policiesPlaceholder: "e.g., Free wifi, Pet-friendly patio, Loyalty rewards" },
    { key: 'bakery', label: 'Bakery & Pastry Shop', category: 'food-hospitality', description: 'Custom cakes, daily specials, pre-orders, catering, and wholesale', icon: CakeSlice, placeholder: "Describe your baked goods, specialties, custom order capabilities, and any classes or events.", hoursPlaceholder: "e.g., Tue-Sun 7am-5pm", servicesPlaceholder: "e.g., Custom Cakes, Breads, Pastries, Wholesale, Catering, Classes", policiesPlaceholder: "e.g., 48-hour notice for custom cakes, 50% deposit required" },

    // Healthcare & Wellness
    { key: 'healthcare', label: 'Healthcare Clinic', category: 'healthcare-wellness', description: 'Appointments, prescriptions, triage, billing, and patient services', icon: HeartPulse, placeholder: "Describe your specialties, providers, patient services, and types of care you offer (in-person, telehealth).", hoursPlaceholder: "e.g., Mon-Fri 8am-6pm, Sat 9am-1pm", servicesPlaceholder: "e.g., Family Medicine, Pediatrics, Dermatology, Telehealth, Lab Services", policiesPlaceholder: "e.g., Accepted insurance plans, New patient forms required, 24hr cancellation" },
    { key: 'dental', label: 'Dental Practice', category: 'healthcare-wellness', description: 'Appointments, cleanings, emergencies, insurance, and cosmetic dentistry', icon: Smile, placeholder: "Describe your dental services, specializations, technology, and patient experience.", hoursPlaceholder: "e.g., Mon-Fri 8am-5pm, Sat 9am-1pm", servicesPlaceholder: "e.g., Cleanings, Fillings, Crowns, Implants, Invisalign, Whitening", policiesPlaceholder: "e.g., Insurance plans accepted, In-house financing for cosmetic work" },
    { key: 'pharmacy', label: 'Pharmacy', category: 'healthcare-wellness', description: 'Prescriptions, refills, drug info, insurance, and health consultations', icon: Pill, placeholder: "Describe your pharmacy type, services offered, delivery options, and any specialty services like compounding.", hoursPlaceholder: "e.g., Mon-Sat 8am-8pm, Sun 10am-4pm", servicesPlaceholder: "e.g., Prescriptions, Delivery, Immunizations, Compounding", policiesPlaceholder: "e.g., Delivery within 10 miles, Auto-refill available" },
    { key: 'veterinary', label: 'Veterinary Clinic', category: 'healthcare-wellness', description: 'Pet appointments, emergencies, vaccinations, surgery, and pet care info', icon: Dog, placeholder: "Describe what animals you treat, your services, surgical capabilities, and any boarding/grooming.", hoursPlaceholder: "e.g., Mon-Fri 7am-7pm, Sat 8am-4pm, Emergency 24/7", servicesPlaceholder: "e.g., Wellness Exams, Vaccinations, Surgery, Dental, Boarding, Grooming", policiesPlaceholder: "e.g., Accept pet insurance, Vaccination records required, Emergency after-hours line" },
    { key: 'fitness', label: 'Fitness & Gym', category: 'healthcare-wellness', description: 'Memberships, class schedules, personal training, and facility info', icon: Dumbbell, placeholder: "Describe your facility, equipment, classes, personal training, and membership options.", hoursPlaceholder: "e.g., 24/7 or Mon-Fri 5am-11pm, Sat-Sun 7am-9pm", servicesPlaceholder: "e.g., Weight Room, Pool, Group Classes, Personal Training, Sauna", policiesPlaceholder: "e.g., 7-day free trial, Monthly/annual plans, Freeze/cancel policy" },
    { key: 'spa', label: 'Spa & Wellness Center', category: 'healthcare-wellness', description: 'Treatment bookings, packages, memberships, gift cards, and wellness info', icon: Flower2, placeholder: "Describe your treatments, facilities, product lines, and any membership or package offerings.", hoursPlaceholder: "e.g., Tue-Sun 9am-8pm", servicesPlaceholder: "e.g., Massage, Facials, Body Treatments, Nail Services, Couples Suites", policiesPlaceholder: "e.g., 24hr cancellation, Arrive 15min early, Health intake form required" },

    // Financial Services
    { key: 'banking', label: 'Banking & Credit Union', category: 'financial-services', description: 'Accounts, transfers, cards, loans, fraud protection, and more', icon: Landmark, placeholder: "Describe your banking products, branch network, digital services, and what sets you apart.", hoursPlaceholder: "e.g., Mon-Fri 9am-5pm, Sat 9am-12pm, ATMs 24/7", servicesPlaceholder: "e.g., Checking, Savings, Loans, Mortgages, Business Banking, Investment", policiesPlaceholder: "e.g., FDIC/NCUA insured, ID required for transactions" },
    { key: 'insurance', label: 'Insurance Agency', category: 'financial-services', description: 'Quotes, claims, policy management, renewals, and coverage questions', icon: ShieldCheck, placeholder: "Describe the types of insurance you offer, carriers you represent, and client segments you serve.", hoursPlaceholder: "e.g., Mon-Fri 8:30am-5:30pm", servicesPlaceholder: "e.g., Auto, Home, Life, Business, Umbrella, Claims Support", policiesPlaceholder: "e.g., Free quotes, Annual policy reviews, Licensed in specific states" },
    { key: 'accounting', label: 'Accounting & Tax', category: 'financial-services', description: 'Tax prep, bookkeeping, consultations, deadlines, and financial planning', icon: Calculator, placeholder: "Describe your accounting services, client types, tax specialties, and software platforms you use.", hoursPlaceholder: "e.g., Mon-Fri 9am-6pm (extended hours during tax season)", servicesPlaceholder: "e.g., Tax Preparation, Bookkeeping, Payroll, Business Formation", policiesPlaceholder: "e.g., Extension filing deadline, Document submission requirements" },

    // Retail & E-Commerce
    { key: 'retail', label: 'Retail Store', category: 'retail-ecommerce', description: 'Products, orders, returns, shipping, loyalty programs, and support', icon: ShoppingBag, placeholder: "Describe your products, brands, shopping experience, and what makes your store unique.", hoursPlaceholder: "e.g., Mon-Sat 10am-9pm, Sun 11am-6pm", servicesPlaceholder: "e.g., In-store, Online, Curbside Pickup, Personal Shopping, Gift Wrap", policiesPlaceholder: "e.g., 30-day returns, Free shipping over $X, Price match guarantee" },
    { key: 'ecommerce', label: 'E-Commerce', category: 'retail-ecommerce', description: 'Online store support, order management, shipping, returns, and product help', icon: ShoppingCart, placeholder: "Describe your online store, product categories, unique value proposition, and customer experience.", servicesPlaceholder: "e.g., Worldwide Shipping, Gift Wrapping, Subscriptions, Custom Orders", policiesPlaceholder: "e.g., Return policy, Shipping rates, International duties disclaimer" },
    { key: 'grocery', label: 'Grocery & Supermarket', category: 'retail-ecommerce', description: 'Store info, delivery, weekly specials, deli orders, and loyalty programs', icon: Apple, placeholder: "Describe your store departments, specialty sections, delivery/pickup options, and loyalty programs.", hoursPlaceholder: "e.g., Daily 7am-10pm", servicesPlaceholder: "e.g., Deli, Bakery, Butcher, Organic, Curbside Pickup, Home Delivery", policiesPlaceholder: "e.g., Minimum for delivery, Rain checks on sale items, Loyalty discounts" },

    // Professional Services
    { key: 'legal', label: 'Law Firm', category: 'professional-services', description: 'Consultations, case inquiries, appointments, document requests, and billing', icon: Scale, placeholder: "Describe your practice areas, attorney team, consultation process, and case types you handle.", hoursPlaceholder: "e.g., Mon-Fri 8:30am-5:30pm", servicesPlaceholder: "e.g., Personal Injury, Family Law, Estate Planning, Business Law", policiesPlaceholder: "e.g., Free initial consultation for certain cases, Retainer structure" },
    { key: 'consulting', label: 'Consulting Firm', category: 'professional-services', description: 'Service inquiries, project scoping, scheduling, proposals, and client support', icon: Briefcase, placeholder: "Describe your consulting specialties, industries served, engagement types, and approach.", hoursPlaceholder: "e.g., Mon-Fri 9am-6pm", servicesPlaceholder: "e.g., Strategy, Digital Transformation, Process Optimization, Change Mgmt", policiesPlaceholder: "e.g., Engagement models (retainer, project), NDA required" },
    { key: 'recruitment', label: 'Recruitment & Staffing', category: 'professional-services', description: 'Job inquiries, candidate screening, interview scheduling, and placement', icon: Users, placeholder: "Describe your staffing specialties, placement types, industries served, and process.", hoursPlaceholder: "e.g., Mon-Fri 8am-6pm", servicesPlaceholder: "e.g., Contract, Contract-to-Hire, Direct Hire, Executive Search", policiesPlaceholder: "e.g., Placement guarantee period, Background check requirements" },
    { key: 'marketing', label: 'Marketing Agency', category: 'professional-services', description: 'Campaign inquiries, client onboarding, project updates, and lead qualification', icon: Megaphone, placeholder: "Describe your marketing services, team size, client types, and typical engagement structure.", hoursPlaceholder: "e.g., Mon-Fri 9am-6pm", servicesPlaceholder: "e.g., SEO, PPC, Social Media, Content, Web Design, Branding", policiesPlaceholder: "e.g., Monthly retainer model, Minimum engagement period, Reporting cadence" },

    // Home & Property
    { key: 'real_estate', label: 'Real Estate', category: 'home-property', description: 'Listings, viewings, buyer/seller inquiries, market info, and closings', icon: Home, placeholder: "Describe your real estate team, service area, property types, and what makes your agency stand out.", hoursPlaceholder: "e.g., Mon-Sat 9am-7pm, Sun by appointment", servicesPlaceholder: "e.g., Buying, Selling, Rentals, Property Management, Commercial", policiesPlaceholder: "e.g., Showings by appointment, Virtual tours available" },
    { key: 'property_management', label: 'Property Management', category: 'home-property', description: 'Tenant services, maintenance requests, leasing, rent payments, and owner support', icon: Building2, placeholder: "Describe your property portfolio, management approach, and services for tenants and owners.", hoursPlaceholder: "e.g., Office Mon-Fri 9am-5pm, Emergency maintenance 24/7", servicesPlaceholder: "e.g., Tenant Relations, Maintenance, Leasing, Rent Collection, Owner Reports", policiesPlaceholder: "e.g., Emergency maintenance protocol, Rent due dates, Late fee policy" },
    { key: 'home_services', label: 'Home Services', category: 'home-property', description: 'Plumbing, HVAC, electrical, repairs, estimates, and emergency service', icon: Wrench, placeholder: "Describe your trade specialties, certifications, service area, and emergency capabilities.", hoursPlaceholder: "e.g., Mon-Fri 7am-6pm, Emergency service 24/7", servicesPlaceholder: "e.g., Plumbing, HVAC, Electrical, Repairs, Installations, Maintenance Plans", policiesPlaceholder: "e.g., Free estimates, Licensed/bonded/insured, Warranty on work" },
    { key: 'cleaning', label: 'Cleaning Services', category: 'home-property', description: 'Residential cleaning, commercial cleaning, scheduling, quotes, and special services', icon: Sparkles, placeholder: "Describe your cleaning services, service area, crew size, and any special capabilities.", hoursPlaceholder: "e.g., Mon-Sat 7am-6pm", servicesPlaceholder: "e.g., Recurring Cleans, Deep Cleaning, Move-in/out, Post-construction, Office", policiesPlaceholder: "e.g., Bonded and insured, Eco-friendly options, Satisfaction guarantee" },

    // Education & Training
    { key: 'education', label: 'School & University', category: 'education-training', description: 'Admissions, enrollment, course info, financial aid, and student services', icon: GraduationCap, placeholder: "Describe your programs, campus, student services, and what makes your institution unique.", hoursPlaceholder: "e.g., Admissions Mon-Fri 8am-5pm", servicesPlaceholder: "e.g., Undergraduate, Graduate, Online, Financial Aid, Career Services", policiesPlaceholder: "e.g., Rolling admissions, Application deadlines, Transfer credit policy" },
    { key: 'tutoring', label: 'Tutoring & Test Prep', category: 'education-training', description: 'Subject tutoring, test prep, scheduling, progress tracking, and pricing', icon: BookOpen, placeholder: "Describe your subjects, grade levels, tutoring formats, and tutor qualifications.", hoursPlaceholder: "e.g., Mon-Sat 9am-8pm", servicesPlaceholder: "e.g., 1-on-1 Tutoring, Group Sessions, SAT/ACT Prep, Online, In-person", policiesPlaceholder: "e.g., Free initial assessment, 24hr cancellation, Session makeup policy" },

    // Technology
    { key: 'saas', label: 'SaaS & Software', category: 'technology', description: 'Product demos, technical support, billing, onboarding, and feature inquiries', icon: Cloud, placeholder: "Describe your software product, target customers, pricing tiers, and key features.", hoursPlaceholder: "e.g., Support Mon-Fri 8am-8pm, Platform 24/7", servicesPlaceholder: "e.g., Free Trial, Onboarding, API Access, Custom Integrations, Training", policiesPlaceholder: "e.g., SLA uptime guarantee, Cancellation terms, Data handling policy" },
    { key: 'it_support', label: 'IT Support & MSP', category: 'technology', description: 'Help desk, troubleshooting, onboarding, network issues, and managed services', icon: Monitor, placeholder: "Describe your managed services, client base, support capabilities, and response times.", hoursPlaceholder: "e.g., Help desk Mon-Fri 7am-7pm, Critical support 24/7", servicesPlaceholder: "e.g., Help Desk, Network Management, Cybersecurity, Cloud Migration", policiesPlaceholder: "e.g., SLA response times, Escalation tiers, After-hours protocol" },
    { key: 'telecom', label: 'Telecommunications', category: 'technology', description: 'Plans, billing, technical support, equipment, and account management', icon: Phone, placeholder: "Describe your telecom services, coverage area, plans, and technology.", hoursPlaceholder: "e.g., Customer service Mon-Sat 8am-9pm, Technical 24/7", servicesPlaceholder: "e.g., Internet, Phone, TV, Bundles, Business Plans", policiesPlaceholder: "e.g., Contract terms, Early termination fees, Equipment return policy" },

    // Automotive
    { key: 'auto_dealership', label: 'Auto Dealership', category: 'automotive', description: 'Vehicle inquiries, test drives, financing, trade-ins, and service scheduling', icon: Car, placeholder: "Describe your brands, inventory types (new/used), financing options, and service capabilities.", hoursPlaceholder: "e.g., Sales Mon-Sat 9am-8pm, Service Mon-Fri 7am-6pm", servicesPlaceholder: "e.g., New Cars, Certified Pre-Owned, Financing, Trade-In, Service, Parts", policiesPlaceholder: "e.g., Test drive requirements, Exchange policy, Warranty terms" },
    { key: 'auto_repair', label: 'Auto Repair Shop', category: 'automotive', description: 'Repair scheduling, diagnostics, estimates, maintenance, and towing', icon: Settings, placeholder: "Describe your repair specialties, certifications, vehicle types serviced, and unique offerings.", hoursPlaceholder: "e.g., Mon-Fri 7:30am-5:30pm, Sat 8am-1pm", servicesPlaceholder: "e.g., Diagnostics, Brakes, Engine, Transmission, Oil Change, Inspections", policiesPlaceholder: "e.g., Free diagnostic with repair, Warranty on parts/labor, Loaner cars" },

    // Travel & Leisure
    { key: 'travel', label: 'Travel Agency', category: 'travel-leisure', description: 'Trip planning, bookings, packages, group travel, and travel advisories', icon: Plane, placeholder: "Describe your travel specialties, preferred partners, destination expertise, and client types.", hoursPlaceholder: "e.g., Mon-Fri 9am-6pm, Sat 10am-3pm", servicesPlaceholder: "e.g., Vacation Packages, Honeymoons, Group Travel, Corporate, Cruises", policiesPlaceholder: "e.g., Booking deposit, Cancellation terms, Travel insurance recommended" },
    { key: 'event_planning', label: 'Event Planning', category: 'travel-leisure', description: 'Event inquiries, venue booking, vendor coordination, and timeline management', icon: CalendarDays, placeholder: "Describe the types of events you plan, your capacity range, and vendor partnerships.", hoursPlaceholder: "e.g., Mon-Fri 9am-6pm, Weekends for events", servicesPlaceholder: "e.g., Corporate Events, Weddings, Galas, Venue Sourcing, Day-of Coordination", policiesPlaceholder: "e.g., Deposit required, Planning timeline, Vendor referral list" },

    // Beauty & Personal Care
    { key: 'salon', label: 'Salon & Barbershop', category: 'beauty-personal', description: 'Appointments, services, pricing, stylist matching, and product sales', icon: Scissors, placeholder: "Describe your salon type, stylist specialties, service menu, and unique offerings.", hoursPlaceholder: "e.g., Tue-Sat 9am-7pm", servicesPlaceholder: "e.g., Cuts, Color, Highlights, Balayage, Keratin, Extensions, Bridal", policiesPlaceholder: "e.g., Cancellation/no-show fee, Patch test for color, Walk-ins welcome" },

    // Logistics & Industrial
    { key: 'logistics', label: 'Logistics & Shipping', category: 'logistics-industrial', description: 'Shipment tracking, quotes, scheduling pickups, claims, and account management', icon: Truck, placeholder: "Describe your logistics services, coverage area, transport modes, and client industries.", hoursPlaceholder: "e.g., Mon-Fri 7am-7pm, Dispatch 24/7", servicesPlaceholder: "e.g., LTL, FTL, Last-Mile, Warehousing, Same-Day Delivery", policiesPlaceholder: "e.g., Claims filing timeframe, Insurance coverage, Credit terms" },
    { key: 'construction', label: 'Construction', category: 'logistics-industrial', description: 'Project inquiries, estimates, scheduling, permits, and subcontractor coordination', icon: HardHat, placeholder: "Describe your construction specialties, project types, licensing, and service area.", hoursPlaceholder: "e.g., Office Mon-Fri 8am-5pm, Sites 7am-5pm", servicesPlaceholder: "e.g., Remodeling, Custom Homes, Commercial, Additions, Design-Build", policiesPlaceholder: "e.g., Licensed/bonded/insured, Free estimates, Change order process" },

    // Government & Nonprofit
    { key: 'government', label: 'Government Agency', category: 'government-nonprofit', description: 'Citizen services, permits, licensing, public information, and department routing', icon: Building, placeholder: "Describe your agency, departments, citizen services, and online capabilities.", hoursPlaceholder: "e.g., Mon-Fri 8am-5pm", servicesPlaceholder: "e.g., Permits, Licensing, Utilities, Parks & Rec, Public Works, Courts", policiesPlaceholder: "e.g., ID requirements, Fee schedules, Online portal available" },
    { key: 'nonprofit', label: 'Nonprofit Organization', category: 'government-nonprofit', description: 'Donations, volunteer coordination, program info, events, and impact reporting', icon: HeartHandshake, placeholder: "Describe your mission, programs, impact, and how people can get involved.", hoursPlaceholder: "e.g., Office Mon-Fri 9am-5pm", servicesPlaceholder: "e.g., Food Distribution, Job Training, Youth Programs, Community Kitchen", policiesPlaceholder: "e.g., Volunteer requirements, Donation tax deductibility, Eligibility criteria" },

    // Media & Entertainment
    { key: 'entertainment', label: 'Entertainment Venue', category: 'media-entertainment', description: 'Tickets, events, group bookings, venue info, and membership', icon: Ticket, placeholder: "Describe your venue type, event genres, capacity, and special offerings.", hoursPlaceholder: "e.g., Box office Tue-Sat 12pm-6pm, Event nights until end", servicesPlaceholder: "e.g., Concerts, Comedy, Private Events, VIP Boxes, Food & Drink", policiesPlaceholder: "e.g., Ticket refund policy, Age restrictions, Prohibited items" },
    { key: 'photography', label: 'Photography & Videography', category: 'media-entertainment', description: 'Session booking, packages, galleries, prints, and event coverage', icon: Camera, placeholder: "Describe your photography style, session types, travel range, and deliverables.", hoursPlaceholder: "e.g., By appointment, Weekends for events", servicesPlaceholder: "e.g., Weddings, Portraits, Headshots, Commercial, Video, Prints/Albums", policiesPlaceholder: "e.g., Deposit to book, Delivery turnaround, Usage rights" },

    // Pet Services
    { key: 'pet_services', label: 'Pet Care & Grooming', category: 'pet-services', description: 'Grooming, daycare, boarding, training, and pet supply', icon: Dog, placeholder: "Describe your pet services, animals accepted, facilities, and any special programs.", hoursPlaceholder: "e.g., Mon-Sat 7am-7pm", servicesPlaceholder: "e.g., Grooming, Daycare, Boarding, Training, Webcam Access", policiesPlaceholder: "e.g., Vaccination records required, Temperament assessment, Breed restrictions" },

];

export default function CreateWorkflowPage() {
    const router = useRouter();
    const { user, getAccessToken } = useAuth();
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const limitCheckDone = useRef(false);
    useEffect(() => {
        if (limitCheckDone.current) return;
        limitCheckDone.current = true;
        (async () => {
            try {
                const token = await getAccessToken();
                if (!token) return;
                const baseUrl = getBackendUrl();
                const res = await fetch(`${baseUrl}/api/v1/subscription/status`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (res.ok) {
                    const sub = await res.json();
                    const wfRes = await fetch(`${baseUrl}/api/v1/workflow/fetch?status=active`, {
                        headers: { Authorization: `Bearer ${token}` },
                    });
                    if (wfRes.ok) {
                        const workflows = await wfRes.json();
                        if (Array.isArray(workflows) && workflows.length >= sub.max_workflows) {
                            setError(
                                `You've reached your limit of ${sub.max_workflows} workflow(s) on the ${sub.plan_display_name} plan. Please upgrade to create more.`
                            );
                            setTimeout(() => router.push('/usage'), 3000);
                            return;
                        }
                    }
                }
            } catch {
                // Non-blocking
            }
        })();
    }, [getAccessToken, router]);

    // Mode
    const [creationMode, setCreationMode] = useState<CreationMode>('industry');

    // AI-generated / Blank state
    const [aiMode, setAiMode] = useState<AIMode>('describe');
    const [useCase, setUseCase] = useState('');
    const [activityDescription, setActivityDescription] = useState('');
    const [workflowName, setWorkflowName] = useState('');
    const [websiteUrl, setWebsiteUrl] = useState('');
    const [websitePrompt, setWebsitePrompt] = useState('');
    const [callType, setCallType] = useState<'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING'>('INBOUND');
    const [kbFiles, setKbFiles] = useState<File[]>([]);

    // Industry selection
    const [selectedIndustry, setSelectedIndustry] = useState<IndustryKey | null>(null);
    const [activeCategory, setActiveCategory] = useState<CategoryKey>('all');
    const [searchQuery, setSearchQuery] = useState('');

    // Form state
    const [industryBusinessName, setIndustryBusinessName] = useState('');
    const [industryDescription, setIndustryDescription] = useState('');
    const [industryCallType, setIndustryCallType] = useState<'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING'>('INBOUND');
    const [referenceLinks, setReferenceLinks] = useState<string[]>([]);
    const [newLinkInput, setNewLinkInput] = useState('');
    const MAX_REFERENCE_LINKS = 5;

    // Structured business info (dynamic, easily updateable)
    const [businessInfo, setBusinessInfo] = useState<BusinessInfo>({
        business_hours: '',
        location: '',
        phone: '',
        email: '',
        services: '',
        policies: '',
    });
    const updateBusinessInfo = useCallback((field: keyof BusinessInfo, value: string) => {
        setBusinessInfo(prev => ({ ...prev, [field]: value }));
    }, []);

    // Audio
    const [audioFiles, setAudioFiles] = useState<AudioFile[]>([]);
    const MAX_AUDIO_FILES = 5;
    const ALLOWED_AUDIO_EXTS = ['.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac'];

    const filteredIndustries = useMemo(() => {
        let result = INDUSTRIES;
        if (activeCategory !== 'all') {
            result = result.filter(i => i.category === activeCategory);
        }
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase();
            result = result.filter(
                i => i.label.toLowerCase().includes(q) || i.description.toLowerCase().includes(q)
            );
        }
        return result;
    }, [activeCategory, searchQuery]);

    const selectedIndustryDef = useMemo(
        () => INDUSTRIES.find(i => i.key === selectedIndustry),
        [selectedIndustry]
    );

    const addReferenceLink = useCallback(() => {
        const url = newLinkInput.trim();
        if (!url) return;
        try {
            new URL(url.startsWith('http') ? url : `https://${url}`);
        } catch {
            setError('Please enter a valid URL');
            return;
        }
        if (referenceLinks.length >= MAX_REFERENCE_LINKS) {
            setError(`You can add up to ${MAX_REFERENCE_LINKS} reference links`);
            return;
        }
        const normalized = url.startsWith('http') ? url : `https://${url}`;
        setReferenceLinks(prev => [...prev, normalized]);
        setNewLinkInput('');
        setError(null);
    }, [newLinkInput, referenceLinks.length]);

    const removeReferenceLink = useCallback((index: number) => {
        setReferenceLinks(prev => prev.filter((_, i) => i !== index));
    }, []);

    const handleAudioFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const selected = Array.from(e.target.files || []);
        const remaining = MAX_AUDIO_FILES - audioFiles.length;
        if (selected.length > remaining) {
            setError(`You can upload up to ${MAX_AUDIO_FILES} recordings. ${remaining} slot(s) remaining.`);
            return;
        }
        for (const f of selected) {
            if (f.size > 25 * 1024 * 1024) {
                setError(`File "${f.name}" exceeds 25 MB limit.`);
                return;
            }
        }
        const newFiles: AudioFile[] = selected.slice(0, remaining).map(f => ({
            id: `${Date.now()}-${Math.random().toString(36).substring(7)}`,
            file: f, name: f.name, size: f.size,
        }));
        setAudioFiles(prev => [...prev, ...newFiles]);
        setError(null);
        if (e.target) e.target.value = '';
    }, [audioFiles.length]);

    const removeAudioFile = useCallback((id: string) => {
        setAudioFiles(prev => prev.filter(f => f.id !== id));
    }, []);

    const formatFileSize = (bytes: number) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const submitMultipart = async (
        endpoint: string,
        payload: Record<string, unknown>,
        recordings: AudioFile[],
    ): Promise<{ ok: boolean; id?: number; errorMsg?: string; subscriptionLimit?: boolean }> => {
        const accessToken = await getAccessToken();
        const baseUrl = getBackendUrl();
        const form = new FormData();
        form.append('data', JSON.stringify(payload));
        for (const r of recordings) form.append('style_recordings', r.file, r.name);
        const res = await fetch(`${baseUrl}${endpoint}`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${accessToken}` },
            body: form,
        });
        if (res.ok) { const data = await res.json().catch(() => null); return { ok: true, id: data?.id }; }
        if (res.status === 403) {
            const errData = await res.json().catch(() => null);
            if (errData?.detail?.error === 'subscription_limit') return { ok: false, subscriptionLimit: true, errorMsg: errData.detail.message || 'Subscription limit reached.' };
            return { ok: false, errorMsg: 'Subscription limit reached. Please upgrade your plan.' };
        }
        const errText = await res.text().catch(() => '');
        return { ok: false, errorMsg: errText || `Request failed with status ${res.status}` };
    };

    const uploadKbFiles = async (workflowId: number) => {
        const accessToken = await getAccessToken();
        const baseUrl = getBackendUrl();
        for (const file of kbFiles) {
            try {
                const form = new FormData();
                form.append('file', file);
                form.append('name', file.name);
                form.append('workflow_id', String(workflowId));
                await fetch(`${baseUrl}/api/v1/knowledge-base/documents/upload`, {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${accessToken}` },
                    body: form,
                });
            } catch {
                logger.error(`Failed to upload KB file: ${file.name}`);
            }
        }
    };

    const handleCreateWorkflow = async () => {
        if (creationMode === 'industry') {
            if (!selectedIndustry) { setError('Please select an industry'); return; }
            if (!industryBusinessName.trim()) { setError('Please enter your business name'); return; }
            if (!industryDescription.trim()) { setError('Please describe your business'); return; }
        } else if (creationMode === 'ai-generated') {
            if (aiMode === 'describe') {
                if (!useCase.trim()) { setError('Please enter a name for your agent'); return; }
                if (!activityDescription.trim()) { setError('Please describe what your agent should do'); return; }
            } else {
                if (!websiteUrl.trim()) { setError('Please enter your website URL'); return; }
                try { new URL(websiteUrl.startsWith('http') ? websiteUrl : `https://${websiteUrl}`); } catch { setError('Please enter a valid URL'); return; }
            }
        } else {
            if (!workflowName.trim()) { setError('Please enter a workflow name'); return; }
        }
        if (!user) { setError('You must be logged in'); return; }

        setIsLoading(true);
        setError(null);

        try {
            const accessToken = await getAccessToken();

            if (creationMode === 'blank') {
                const definition = callType === 'MEETING' ? BLANK_MEETING_WORKFLOW_DEFINITION : BLANK_WORKFLOW_DEFINITION;
                const response = await createWorkflowApiV1WorkflowCreateDefinitionPost({
                    body: {
                        name: workflowName.trim(),
                        workflow_definition: definition,
                        ...({ workflow_configurations: { call_type: callType } } as Record<string, unknown>),
                    },
                    headers: { 'Authorization': `Bearer ${accessToken}` },
                });
                if (response.data?.id) {
                    if (kbFiles.length > 0) {
                        await uploadKbFiles(response.data.id);
                    }
                    router.push(`/workflow/${response.data.public_id ?? response.data.id}`);
                    return;
                }
                const status = response.response?.status;
                const detail = (response.error as { detail?: unknown } | undefined)?.detail;
                logger.error(`Error creating blank workflow (status ${status}): ${JSON.stringify(response.error)}`);
                if (detail && typeof detail === 'object' && (detail as { error?: string }).error === 'subscription_limit') {
                    setError((detail as { message?: string }).message || 'Subscription limit reached.');
                    setTimeout(() => router.push('/usage'), 2000);
                } else if (status === 429) {
                    setError('Too many requests. Please wait and try again.');
                } else if (typeof detail === 'string') {
                    setError(detail);
                } else {
                    setError(`Failed to create workspace${status ? ` (status ${status})` : ''}. Please try again.`);
                }
                return;
            }

            if (creationMode === 'industry') {
                const cleanInfo: Record<string, string> = {};
                for (const [k, v] of Object.entries(businessInfo)) {
                    if (v.trim()) cleanInfo[k] = v.trim();
                }

                // If the user typed a URL in the reference-link input but
                // forgot to click "+", include it anyway. Otherwise the URL
                // is silently dropped and the crew gets zero website context.
                const pendingUrl = newLinkInput.trim();
                let finalLinks = referenceLinks;
                if (pendingUrl && referenceLinks.length < MAX_REFERENCE_LINKS) {
                    try {
                        const normalized = pendingUrl.startsWith('http')
                            ? pendingUrl
                            : `https://${pendingUrl}`;
                        new URL(normalized);
                        finalLinks = [...referenceLinks, normalized];
                    } catch {
                        // Invalid URL — ignore silently; the user will see
                        // empty context but the crew still runs.
                    }
                }

                const result = await submitMultipart(
                    '/api/v1/workflow/create/industry-template',
                    {
                        industry: selectedIndustry,
                        business_name: industryBusinessName.trim(),
                        call_type: industryCallType,
                        business_description: industryDescription.trim(),
                        reference_links: finalLinks.length > 0 ? finalLinks : undefined,
                        business_info: Object.keys(cleanInfo).length > 0 ? cleanInfo : undefined,
                    },
                    audioFiles,
                );
                if (result.ok) {
                    if (kbFiles.length > 0 && result.id) {
                        await uploadKbFiles(result.id);
                    }
                    router.push('/workflow');
                }
                else { setError(result.errorMsg || 'Failed to create agent.'); if (result.subscriptionLimit) setTimeout(() => router.push('/usage'), 2000); }
                return;
            }

            // AI-Generated
            let requestBody: Record<string, unknown>;
            if (aiMode === 'website') {
                const normalizedUrl = websiteUrl.startsWith('http') ? websiteUrl : `https://${websiteUrl}`;
                const baseDesc = `Create a voice AI agent for the business at ${normalizedUrl}. Analyze the website to understand the business type, services, products, and create an appropriate voice agent.`;
                requestBody = {
                    call_type: callType,
                    use_case: 'Business Assistant',
                    activity_description: websitePrompt.trim() ? `${baseDesc}\n\nUser instructions: ${websitePrompt.trim()}` : baseDesc,
                    website_url: normalizedUrl,
                };
            } else {
                requestBody = { call_type: callType, use_case: useCase, activity_description: activityDescription };
            }
            const result = await submitMultipart('/api/v1/workflow/create/template', requestBody, audioFiles);
            if (result.ok) {
                if (kbFiles.length > 0 && result.id) {
                    await uploadKbFiles(result.id);
                }
                router.push('/workflow');
            }
            else { setError(result.errorMsg || 'Failed to create workflow.'); if (result.subscriptionLimit) setTimeout(() => router.push('/usage'), 2000); }
        } catch (err: unknown) {
            const error = err as { response?: { status?: number }; message?: string };
            if (error?.response?.status === 429) setError('Too many requests. Please wait and try again.');
            else setError('Failed to create agent. Please try again.');
            logger.error(`Error creating workflow: ${err}`);
        } finally {
            setIsLoading(false);
        }
    };

    const isSubmitDisabled = () => {
        if (isLoading) return true;
        if (creationMode === 'industry') return !selectedIndustry || !industryBusinessName.trim() || !industryDescription.trim();
        if (creationMode === 'blank') return !workflowName.trim();
        if (aiMode === 'describe') return !useCase.trim() || !activityDescription.trim();
        return !websiteUrl.trim();
    };

    const StyleRecordingsSection = () => (
        <div className="space-y-3 border-t pt-4 mt-4">
            <div className="flex items-center justify-between">
                <div>
                    <Label className="text-base flex items-center gap-2">
                        <Mic className="w-4 h-4 text-amber-500" />
                        Mimic a Real Agent&apos;s Style
                        <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                    </Label>
                    <p className="text-sm text-muted-foreground mt-1">
                        Upload real call recordings and we&apos;ll extract tone, pacing, empathy moves,
                        and signature phrases — your agent will mirror how they actually work.
                    </p>
                </div>
                {audioFiles.length < MAX_AUDIO_FILES && (
                    <label>
                        <Button type="button" variant="outline" size="sm" className="cursor-pointer" asChild>
                            <span><Upload className="w-4 h-4 mr-2" />Add Recording</span>
                        </Button>
                        <input type="file" className="hidden" accept={ALLOWED_AUDIO_EXTS.join(',')} onChange={handleAudioFileSelect} multiple />
                    </label>
                )}
            </div>
            {audioFiles.length > 0 ? (
                <div className="space-y-2">
                    {audioFiles.map((file) => (
                        <div key={file.id} className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                            <div className="flex items-center gap-3 min-w-0">
                                <Mic className="w-4 h-4 text-amber-500 flex-shrink-0" />
                                <div className="min-w-0">
                                    <p className="text-sm font-medium truncate">{file.name}</p>
                                    <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                                </div>
                            </div>
                            <Button type="button" variant="ghost" size="icon" className="flex-shrink-0 text-muted-foreground hover:text-destructive" onClick={() => removeAudioFile(file.id)}>
                                <X className="w-4 h-4" />
                            </Button>
                        </div>
                    ))}
                    <p className="text-xs text-muted-foreground">{audioFiles.length}/{MAX_AUDIO_FILES} recording(s) attached</p>
                </div>
            ) : (
                <label className="block cursor-pointer">
                    <div className="border border-dashed rounded-lg p-4 text-center hover:border-primary/50 hover:bg-muted/30 transition-colors">
                        <Mic className="w-6 h-6 text-muted-foreground/40 mx-auto mb-2" />
                        <p className="text-sm text-muted-foreground">
                            No recordings attached. Drop MP3/WAV/M4A files (up to 25 MB each)
                        </p>
                    </div>
                    <input type="file" className="hidden" accept={ALLOWED_AUDIO_EXTS.join(',')} onChange={handleAudioFileSelect} multiple />
                </label>
            )}
        </div>
    );

    const KnowledgeBaseSection = () => (
        <div className="space-y-3 border-t pt-4 mt-4">
            <div className="flex items-center justify-between">
                <div>
                    <Label className="text-base flex items-center gap-2">
                        <Book className="w-4 h-4 text-primary" />
                        Knowledge Base
                        <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                    </Label>
                    <p className="text-sm text-muted-foreground mt-1">
                        Upload documents your agent can reference during conversations (PDF, TXT, DOCX, XLSX).
                    </p>
                </div>
                <label>
                    <Button type="button" variant="outline" size="sm" className="cursor-pointer" asChild>
                        <span><Upload className="w-4 h-4 mr-2" />Add Files</span>
                    </Button>
                    <input type="file" className="hidden" accept=".txt,.md,.pdf,.docx,.xlsx,.xls,.csv" onChange={(e) => {
                        const files = Array.from(e.target.files || []);
                        setKbFiles(prev => [...prev, ...files]);
                        e.target.value = '';
                    }} multiple />
                </label>
            </div>
            {kbFiles.length > 0 ? (
                <div className="space-y-2">
                    {kbFiles.map((file, idx) => (
                        <div key={`${file.name}-${idx}`} className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                            <div className="flex items-center gap-3 min-w-0">
                                <FileText className="w-4 h-4 text-primary flex-shrink-0" />
                                <div className="min-w-0">
                                    <p className="text-sm font-medium truncate">{file.name}</p>
                                    <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                                </div>
                            </div>
                            <Button type="button" variant="ghost" size="icon" className="flex-shrink-0 text-muted-foreground hover:text-destructive" onClick={() => setKbFiles(prev => prev.filter((_, i) => i !== idx))}>
                                <X className="w-4 h-4" />
                            </Button>
                        </div>
                    ))}
                    <p className="text-xs text-muted-foreground">{kbFiles.length} document(s) will be uploaded after creation</p>
                </div>
            ) : (
                <label className="block cursor-pointer">
                    <div className="border border-dashed rounded-lg p-4 text-center hover:border-primary/50 hover:bg-muted/30 transition-colors">
                        <FileText className="w-6 h-6 text-muted-foreground/40 mx-auto mb-2" />
                        <p className="text-sm text-muted-foreground">
                            No documents attached. Drop files here to add to the knowledge base.
                        </p>
                    </div>
                    <input type="file" className="hidden" accept=".txt,.md,.pdf,.docx,.xlsx,.xls,.csv" onChange={(e) => {
                        const files = Array.from(e.target.files || []);
                        setKbFiles(prev => [...prev, ...files]);
                        e.target.value = '';
                    }} multiple />
                </label>
            )}
        </div>
    );

    // ─── RENDER: AI-Generated or Blank form ───
    if (creationMode !== 'industry') {
        return (
            <div className="min-h-screen bg-background">
                <div className="container mx-auto px-4 py-8 max-w-2xl">
                    <button onClick={() => setCreationMode('industry')} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6">
                        <ArrowLeft className="w-4 h-4" /> Back to industries
                    </button>

                    <Card>
                        <CardHeader>
                            <CardTitle>{creationMode === 'blank' ? 'Blank Workspace' : 'AI-Generated Agent'}</CardTitle>
                            <CardDescription>
                                {creationMode === 'blank' ? 'Start with a blank canvas and build your workflow manually.' : 'Describe what you need or provide a website URL.'}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            {creationMode === 'blank' ? (
                                <>
                                    <div className="space-y-2">
                                        <Label htmlFor="workflow-name">Workflow Name</Label>
                                        <Input id="workflow-name" placeholder="e.g., My Custom Agent" value={workflowName} onChange={(e) => setWorkflowName(e.target.value)} />
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="blank-call-type">Call Type</Label>
                                        <Select value={callType} onValueChange={(v) => setCallType(v as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING')}>
                                            <SelectTrigger id="blank-call-type"><SelectValue /></SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="INBOUND">Inbound (Users call AI)</SelectItem>
                                                <SelectItem value="OUTBOUND">Outbound (AI calls users)</SelectItem>
                                                <SelectItem value="WEBSITE">Website (Voice widget)</SelectItem>
                                                <SelectItem value="MEETING">Meeting Agent (Joins meetings)</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </>
                            ) : (
                                <Tabs value={aiMode} onValueChange={(v) => setAiMode(v as AIMode)} className="w-full">
                                    <TabsList className="grid w-full grid-cols-2 mb-6">
                                        <TabsTrigger value="describe" className="gap-2">Describe</TabsTrigger>
                                        <TabsTrigger value="website" className="gap-2"><Globe className="w-4 h-4" />From Website</TabsTrigger>
                                    </TabsList>
                                    <TabsContent value="describe" className="space-y-6 mt-0">
                                        <div className="space-y-2">
                                            <Label htmlFor="use-case">Agent Name</Label>
                                            <Input id="use-case" placeholder="e.g., Customer Support, Booking Agent" value={useCase} onChange={(e) => setUseCase(e.target.value)} />
                                        </div>
                                        <div className="space-y-2">
                                            <Label htmlFor="activity-description">What should your agent do?</Label>
                                            <Textarea id="activity-description" placeholder="Describe what your voice agent will do..." value={activityDescription} onChange={(e) => setActivityDescription(e.target.value)} className="min-h-[120px]" />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Call Type</Label>
                                            <Select value={callType} onValueChange={(v) => setCallType(v as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING')}>
                                                <SelectTrigger><SelectValue /></SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="INBOUND">Inbound</SelectItem>
                                                    <SelectItem value="OUTBOUND">Outbound</SelectItem>
                                                    <SelectItem value="WEBSITE">Website</SelectItem>
                                                    <SelectItem value="MEETING">Meeting Agent</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <StyleRecordingsSection />
                                        <KnowledgeBaseSection />
                                    </TabsContent>
                                    <TabsContent value="website" className="space-y-6 mt-0">
                                        <div className="space-y-2">
                                            <Label htmlFor="website-url">Your Website URL</Label>
                                            <Input id="website-url" type="url" placeholder="https://www.your-business.com" value={websiteUrl} onChange={(e) => setWebsiteUrl(e.target.value)} />
                                            <p className="text-sm text-muted-foreground">We&apos;ll crawl your website and build an agent automatically.</p>
                                        </div>
                                        <div className="space-y-2">
                                            <Label htmlFor="website-prompt">Agent Instructions <span className="text-xs text-muted-foreground font-normal">(Optional)</span></Label>
                                            <Textarea id="website-prompt" placeholder="Guide the AI on what your agent should focus on..." value={websitePrompt} onChange={(e) => setWebsitePrompt(e.target.value)} className="min-h-[100px]" />
                                        </div>
                                        <div className="space-y-2">
                                            <Label>Call Type</Label>
                                            <Select value={callType} onValueChange={(v) => setCallType(v as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING')}>
                                                <SelectTrigger><SelectValue /></SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="INBOUND">Inbound</SelectItem>
                                                    <SelectItem value="OUTBOUND">Outbound</SelectItem>
                                                    <SelectItem value="WEBSITE">Website</SelectItem>
                                                    <SelectItem value="MEETING">Meeting Agent</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <StyleRecordingsSection />
                                        <KnowledgeBaseSection />
                                    </TabsContent>
                                </Tabs>
                            )}

                            {error && <p className="text-sm text-red-500">{error}</p>}

                            <div className="pt-4">
                                <Button onClick={handleCreateWorkflow} disabled={isSubmitDisabled()} className="w-full">
                                    {isLoading ? 'Creating...' : creationMode === 'blank' ? 'Create Blank Workspace' : 'Create Agent'}
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                </div>
                {isLoading && <AILoader />}
            </div>
        );
    }

    // ─── RENDER: Industry selection grid ───
    if (!selectedIndustry) {
        return (
            <div className="min-h-screen bg-background">
                <div className="container mx-auto px-3 sm:px-4 py-6 sm:py-8 max-w-5xl">
                    {/* Header */}
                    <div className="text-center mb-5 sm:mb-6">
                        <h1 className="text-2xl sm:text-3xl font-bold mb-2">Create Your Specialized Agent</h1>
                        <p className="text-sm sm:text-base text-muted-foreground max-w-xl mx-auto">
                            Choose your industry and we&apos;ll build a voice AI agent fine-tuned with expert knowledge,
                            compliance rules, and best practices for your specific business.
                        </p>
                    </div>

                    {/* Quick-access: AI-Generated / Blank */}
                    <div className="flex items-center justify-center gap-2 sm:gap-3 mb-5 sm:mb-6">
                        <span className="text-xs text-muted-foreground">or</span>
                        <button
                            onClick={() => { setCreationMode('ai-generated'); setError(null); }}
                            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-all"
                        >
                            <Sparkles className="w-3 h-3" />
                            AI-Generated
                        </button>
                        <button
                            onClick={() => { setCreationMode('blank'); setError(null); }}
                            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-all"
                        >
                            <Plus className="w-3 h-3" />
                            Blank Workspace
                        </button>
                    </div>

                    {/* Search */}
                    <div className="relative max-w-md mx-auto mb-5 sm:mb-6">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                        <Input
                            placeholder="Search industries..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-10"
                        />
                    </div>

                    {/* Category pills - horizontal scroll on mobile */}
                    <div className="overflow-x-auto -mx-3 px-3 sm:mx-0 sm:px-0 mb-6 sm:mb-8 scrollbar-hide">
                        <div className="flex sm:flex-wrap gap-2 sm:justify-center pb-2 sm:pb-0 min-w-max sm:min-w-0">
                            {CATEGORIES.map((cat) => {
                                const IconComponent = cat.icon;
                                const isActive = activeCategory === cat.key;
                                return (
                                    <button
                                        key={cat.key}
                                        onClick={() => {
                                            setActiveCategory(cat.key);
                                            setSearchQuery('');
                                        }}
                                        className={`
                                            inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs sm:text-sm
                                            transition-all border whitespace-nowrap
                                            ${isActive
                                                ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                                                : 'bg-background text-muted-foreground border-border hover:border-primary/40 hover:text-foreground'
                                            }
                                        `}
                                    >
                                        <IconComponent className="w-3.5 h-3.5" />
                                        {cat.label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Industry grid */}
                    {filteredIndustries.length === 0 ? (
                        <div className="text-center py-12">
                            <Search className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
                            <p className="text-muted-foreground">No industries found matching your search.</p>
                            <Button variant="ghost" size="sm" className="mt-2" onClick={() => { setSearchQuery(''); setActiveCategory('all'); }}>
                                Clear filters
                            </Button>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 sm:gap-3">
                            {filteredIndustries.map((industry) => {
                                const IconComponent = industry.icon;
                                return (
                                    <Card
                                        key={industry.key}
                                        className="cursor-pointer transition-all hover:border-primary/50 hover:shadow-md active:scale-[0.98] group"
                                        onClick={() => setSelectedIndustry(industry.key)}
                                    >
                                        <CardContent className="p-3 sm:p-4">
                                            <div className="flex items-start gap-3">
                                                <div className="p-2 sm:p-2.5 rounded-xl bg-primary/10 text-primary flex-shrink-0 group-hover:bg-primary/20 transition-colors">
                                                    <IconComponent className="w-4 h-4 sm:w-5 sm:h-5" />
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <h3 className="font-semibold text-sm mb-0.5">{industry.label}</h3>
                                                    <p className="text-xs text-muted-foreground line-clamp-2">{industry.description}</p>
                                                </div>
                                            </div>
                                        </CardContent>
                                    </Card>
                                );
                            })}
                        </div>
                    )}

                    {/* Count */}
                    <p className="text-center text-xs text-muted-foreground mt-6">
                        {filteredIndustries.length} specialized {filteredIndustries.length === 1 ? 'agent' : 'agents'} available
                    </p>

                    {error && (
                        <div className="max-w-md mx-auto mt-4">
                            <p className="text-sm text-red-500 text-center">{error}</p>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ─── RENDER: Selected industry form ───
    const SelectedIcon = selectedIndustryDef?.icon || Building2;

    return (
        <div className="min-h-screen bg-background">
            <div className="container mx-auto px-3 sm:px-4 py-6 sm:py-8 max-w-2xl">
                {/* Back + header */}
                <div className="mb-5 sm:mb-6">
                    <button
                        onClick={() => setSelectedIndustry(null)}
                        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        Back to industries
                    </button>
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 sm:p-3 rounded-xl bg-primary/10 text-primary">
                            <SelectedIcon className="w-5 h-5 sm:w-6 sm:h-6" />
                        </div>
                        <div className="min-w-0">
                            <h1 className="text-xl sm:text-2xl font-bold truncate">{selectedIndustryDef?.label} Agent</h1>
                            <p className="text-xs sm:text-sm text-muted-foreground line-clamp-1">{selectedIndustryDef?.description}</p>
                        </div>
                    </div>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle>Tell us about your business</CardTitle>
                        <CardDescription>
                            We&apos;ll build a specialized agent with industry-specific knowledge, compliance rules, and best practices.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <Label htmlFor="industry-business-name">Business Name</Label>
                            <Input
                                id="industry-business-name"
                                placeholder="e.g., Bella Italia, Greenwood Medical, Peak Outdoors"
                                value={industryBusinessName}
                                onChange={(e) => setIndustryBusinessName(e.target.value)}
                            />
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="industry-call-type">Call Type</Label>
                            <Select value={industryCallType} onValueChange={(value) => setIndustryCallType(value as 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING')}>
                                <SelectTrigger id="industry-call-type"><SelectValue placeholder="Select type" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="INBOUND">Inbound (Customers call you)</SelectItem>
                                    <SelectItem value="OUTBOUND">Outbound (You call customers)</SelectItem>
                                    <SelectItem value="WEBSITE">Website (Voice widget on your site)</SelectItem>
                                    <SelectItem value="MEETING">Meeting Agent (Joins meetings)</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Business Info -- all optional */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <Label htmlFor="biz-hours" className="text-sm flex items-center gap-1.5">
                                    <Clock className="w-3.5 h-3.5 text-muted-foreground" />
                                    Business Hours
                                    <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                                </Label>
                                <Input
                                    id="biz-hours"
                                    placeholder={selectedIndustryDef?.hoursPlaceholder || "e.g., Mon-Fri 9am-5pm"}
                                    value={businessInfo.business_hours}
                                    onChange={(e) => updateBusinessInfo('business_hours', e.target.value)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="biz-location" className="text-sm flex items-center gap-1.5">
                                    <MapPin className="w-3.5 h-3.5 text-muted-foreground" />
                                    Location
                                    <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                                </Label>
                                <Input
                                    id="biz-location"
                                    placeholder="e.g., 123 Main St, Austin, TX"
                                    value={businessInfo.location}
                                    onChange={(e) => updateBusinessInfo('location', e.target.value)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="biz-phone" className="text-sm flex items-center gap-1.5">
                                    <Phone className="w-3.5 h-3.5 text-muted-foreground" />
                                    Phone
                                    <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                                </Label>
                                <Input
                                    id="biz-phone"
                                    placeholder="e.g., (512) 555-0100"
                                    value={businessInfo.phone}
                                    onChange={(e) => updateBusinessInfo('phone', e.target.value)}
                                />
                            </div>
                            <div className="space-y-1.5">
                                <Label htmlFor="biz-email" className="text-sm flex items-center gap-1.5">
                                    <Mail className="w-3.5 h-3.5 text-muted-foreground" />
                                    Email
                                    <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                                </Label>
                                <Input
                                    id="biz-email"
                                    placeholder="e.g., info@yourbusiness.com"
                                    value={businessInfo.email}
                                    onChange={(e) => updateBusinessInfo('email', e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="space-y-1.5">
                            <Label htmlFor="biz-services" className="text-sm">
                                Services / Offerings
                                <span className="text-xs text-muted-foreground font-normal ml-1.5">(Optional)</span>
                            </Label>
                            <Input
                                id="biz-services"
                                placeholder={selectedIndustryDef?.servicesPlaceholder || "e.g., Service A, Service B, Service C"}
                                value={businessInfo.services}
                                onChange={(e) => updateBusinessInfo('services', e.target.value)}
                            />
                        </div>

                        <div className="space-y-1.5">
                            <Label htmlFor="biz-policies" className="text-sm">
                                Key Policies
                                <span className="text-xs text-muted-foreground font-normal ml-1.5">(Optional)</span>
                            </Label>
                            <Input
                                id="biz-policies"
                                placeholder={selectedIndustryDef?.policiesPlaceholder || "e.g., Return policy, cancellation terms, special rules"}
                                value={businessInfo.policies}
                                onChange={(e) => updateBusinessInfo('policies', e.target.value)}
                            />
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="industry-description">
                                Business Description
                            </Label>
                            <Textarea
                                id="industry-description"
                                placeholder={selectedIndustryDef?.placeholder}
                                value={industryDescription}
                                onChange={(e) => setIndustryDescription(e.target.value)}
                                className="min-h-[80px]"
                            />
                            <p className="text-sm text-muted-foreground">
                                Anything else — specialties, brand personality, target customers, unique offerings.
                            </p>
                        </div>

                        {/* Reference Links */}
                        <div className="space-y-3 border-t pt-4 mt-4">
                            <div>
                                <Label className="text-base flex items-center gap-2">
                                    <Link2 className="w-4 h-4 text-primary" />
                                    Reference Links
                                    <span className="text-xs text-muted-foreground font-normal">(Optional)</span>
                                </Label>
                                <p className="text-sm text-muted-foreground mt-1">
                                    Add your website, menu pages, service docs, or any URLs with business info — we&apos;ll extract context automatically
                                </p>
                            </div>
                            <div className="flex gap-2">
                                <Input
                                    placeholder="https://www.your-business.com"
                                    value={newLinkInput}
                                    onChange={(e) => setNewLinkInput(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addReferenceLink(); } }}
                                    className="flex-1"
                                />
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="icon"
                                    onClick={addReferenceLink}
                                    disabled={!newLinkInput.trim() || referenceLinks.length >= MAX_REFERENCE_LINKS}
                                >
                                    <Plus className="w-4 h-4" />
                                </Button>
                            </div>
                            {newLinkInput.trim() && (
                                <p className="text-xs text-amber-500 flex items-center gap-1.5">
                                    <span className="font-medium">Pending:</span>
                                    press <kbd className="px-1 py-0.5 rounded bg-muted border text-[10px]">Enter</kbd> or click <kbd className="px-1 py-0.5 rounded bg-muted border text-[10px]">+</kbd> to add — it will be auto-included on submit if you forget.
                                </p>
                            )}
                            {referenceLinks.length > 0 ? (
                                <div className="space-y-2">
                                    {referenceLinks.map((link, i) => (
                                        <div key={i} className="flex items-center justify-between p-2.5 rounded-lg border bg-muted/30 gap-3">
                                            <div className="flex items-center gap-2.5 min-w-0">
                                                <Globe className="w-4 h-4 text-primary flex-shrink-0" />
                                                <span className="text-sm truncate">{link}</span>
                                            </div>
                                            <Button type="button" variant="ghost" size="icon" className="flex-shrink-0 h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => removeReferenceLink(i)}>
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </Button>
                                        </div>
                                    ))}
                                    <p className="text-xs text-muted-foreground">{referenceLinks.length}/{MAX_REFERENCE_LINKS} links added</p>
                                </div>
                            ) : (
                                <div className="border border-dashed rounded-lg p-3 text-center">
                                    <p className="text-sm text-muted-foreground">
                                        No links added yet. Add your website or document URLs for richer context.
                                    </p>
                                </div>
                            )}
                        </div>

                        <StyleRecordingsSection />
                        <KnowledgeBaseSection />

                        {error && <p className="text-sm text-red-500">{error}</p>}

                        <div className="pt-4">
                            <Button onClick={handleCreateWorkflow} disabled={isSubmitDisabled()} className="w-full">
                                {isLoading ? 'Creating...' : 'Create Specialized Agent'}
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            </div>

            {isLoading && <AILoader />}
        </div>
    );
}
