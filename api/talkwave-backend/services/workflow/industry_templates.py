"""
Industry-specific knowledge base and workflow assembly for specialized agent creation.

Each industry defines:
- Possible use cases the CrewAI crew can draw from
- Compliance rules that must be preserved
- KB-eligible node patterns
- Industry Expert backstory for the CrewAI agent
- Fixed structural patterns (e.g., banking requires verification before routing)
"""

import re
import uuid
from typing import Any, Optional


def _sanitize_var_name(name: str) -> str:
    """Coerce an AI-generated variable name into an identifier-safe key.

    The runtime template renderers only substitute names matching ``\\w+`` (no
    spaces, hyphens, or punctuation), so a name like "Party Size" or
    "reservation-date" would silently never fill in. We lower-case, swap
    separators for underscores, drop anything else, and ensure it doesn't start
    with a digit. Returns "" if nothing usable remains.
    """
    cleaned = re.sub(r"[\s\-]+", "_", (name or "").strip().lower())
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = f"var_{cleaned}"
    return cleaned


INDUSTRY_CATEGORIES: dict[str, dict[str, str]] = {
    "food-hospitality": {"label": "Food & Hospitality", "icon": "utensils"},
    "healthcare-wellness": {"label": "Healthcare & Wellness", "icon": "heart-pulse"},
    "financial-services": {"label": "Financial Services", "icon": "landmark"},
    "retail-ecommerce": {"label": "Retail & E-Commerce", "icon": "shopping-bag"},
    "professional-services": {"label": "Professional Services", "icon": "briefcase"},
    "home-property": {"label": "Home & Property", "icon": "home"},
    "education-training": {"label": "Education & Training", "icon": "graduation-cap"},
    "technology": {"label": "Technology", "icon": "cpu"},
    "automotive": {"label": "Automotive", "icon": "car"},
    "travel-leisure": {"label": "Travel & Leisure", "icon": "plane"},
    "beauty-personal": {"label": "Beauty & Personal Care", "icon": "scissors"},
    "logistics-industrial": {"label": "Logistics & Industrial", "icon": "truck"},
    "government-nonprofit": {"label": "Government & Nonprofit", "icon": "building"},
    "media-entertainment": {"label": "Media & Entertainment", "icon": "film"},
    "pet-services": {"label": "Pet Services", "icon": "heart"},
}

INDUSTRY_REGISTRY: dict[str, dict[str, Any]] = {
    # ──────────────────────────────────────────────
    # FOOD & HOSPITALITY
    # ──────────────────────────────────────────────
    "restaurant": {
        "display_name": "Restaurant",
        "category": "food-hospitality",
        "description": "Reservations, orders, menu info, catering, and more",
        "icon": "utensils",
        "placeholder_text": (
            "Describe your cuisine type, dining style (family-owned, fine-dining, casual), "
            "what you're known for, and any special offerings like catering, wine club, or private dining."
        ),
        "expert_backstory": (
            "You are a senior hospitality operations consultant with 20 years of experience "
            "advising restaurants of all sizes — from single-location family restaurants to "
            "multi-unit chains. You deeply understand reservation management, front-of-house "
            "operations, takeout/delivery logistics, catering workflows, menu engineering, "
            "allergen liability, food safety regulations, liquor license limitations, "
            "kitchen workflow timing, and customer complaint resolution in food service. "
            "You know the difference between a fine-dining caller experience and a casual "
            "pizzeria caller experience."
        ),
        "compliance_rules": [
            "Always include an allergen disclaimer: 'Please inform us of any allergies — we take food safety seriously.'",
            "Never guarantee specific ingredient sourcing without the business confirming it.",
            "Mention that menu items and prices may vary; recommend confirming with the restaurant.",
            "For liquor-related inquiries, never promise availability without checking.",
        ],
        "possible_use_cases": [
            {"name": "Reservations", "description": "Table bookings — date, time, party size, special occasions, waitlist, modifications, cancellations"},
            {"name": "Menu Information", "description": "Menu items, prices, daily specials, dietary options, allergens, chef recommendations", "kb_eligible": True},
            {"name": "Takeout/Delivery Orders", "description": "Food ordering, customizations, upselling, delivery address, estimated time, payment"},
            {"name": "Catering & Events", "description": "Corporate events, weddings, custom menus, guest count, budget, tasting appointments"},
            {"name": "Complaints & Feedback", "description": "Handling complaints with empathy, resolution offers, manager escalation, positive feedback"},
            {"name": "General Inquiries", "description": "Hours, location, parking, accessibility, gift cards, loyalty program"},
            {"name": "Private Dining", "description": "Private room availability, minimum spend, A/V setup, custom menus"},
            {"name": "Wine Club / Bar", "description": "Wine club membership, cocktail menu, tasting events, pairing recommendations", "kb_eligible": True},
            {"name": "Dietary Specialist", "description": "Detailed allergen cross-contamination info, custom dietary accommodations", "kb_eligible": True},
            {"name": "Waitlist Management", "description": "Join waitlist, check position, estimated wait time, callback"},
        ],
        "fixed_patterns": None,
    },

    "hotel": {
        "display_name": "Hotel & Hospitality",
        "category": "food-hospitality",
        "description": "Room bookings, concierge, check-in/out, amenities, and guest services",
        "icon": "bed",
        "placeholder_text": (
            "Describe your hotel style (boutique, resort, business), key amenities like pool, spa, "
            "or restaurants, and any unique features such as loyalty programs, pet-friendly policies, or event spaces."
        ),
        "expert_backstory": (
            "You are a hotel operations expert with 18 years in hospitality management, "
            "from boutique inns to large resort chains. You understand revenue management, "
            "front desk operations, housekeeping coordination, concierge services, group "
            "booking logistics, loyalty programs, OTA channel management, guest complaint "
            "resolution, and the nuances of different guest segments (business, leisure, "
            "wedding blocks, corporate retreats)."
        ),
        "compliance_rules": [
            "Never share guest information or confirm whether someone is staying at the hotel.",
            "Clearly state cancellation policy windows and any fees.",
            "For payment, never ask for full card numbers over the phone — use secure booking links.",
            "Mention any resort fees or additional charges upfront.",
        ],
        "possible_use_cases": [
            {"name": "Room Reservations", "description": "Availability, room types, rates, packages, group bookings, modifications, cancellations"},
            {"name": "Concierge Services", "description": "Local recommendations, restaurant reservations, tours, transportation, special requests"},
            {"name": "Check-in/Check-out", "description": "Early check-in, late check-out, express options, key issues, room assignments"},
            {"name": "Amenities & Facilities", "description": "Pool, spa, gym, restaurant hours, meeting rooms, business center", "kb_eligible": True},
            {"name": "Guest Complaints", "description": "Room issues, noise complaints, service recovery, compensation, manager escalation"},
            {"name": "Loyalty Program", "description": "Points balance, tier status, rewards redemption, membership benefits"},
            {"name": "Events & Conferences", "description": "Meeting space, A/V setup, catering, room blocks, event coordination"},
            {"name": "General Inquiries", "description": "Directions, parking, pet policy, accessibility, local attractions"},
        ],
        "fixed_patterns": None,
    },

    "cafe": {
        "display_name": "Coffee Shop & Cafe",
        "category": "food-hospitality",
        "description": "Menu, hours, mobile orders, catering, loyalty, and event space",
        "icon": "coffee",
        "placeholder_text": (
            "Describe your cafe concept (artisan roastery, neighborhood spot, chain), "
            "what makes your menu unique, and any special offerings like bean subscriptions, cupping events, or catering."
        ),
        "expert_backstory": (
            "You are a specialty coffee and cafe operations consultant who understands "
            "barista workflows, menu engineering for cafes, subscription commerce, "
            "third-wave coffee sourcing, mobile ordering integration, and the unique "
            "community-building aspects of cafe culture."
        ),
        "compliance_rules": [
            "Include allergen info for food items — especially nuts, dairy, and gluten.",
            "Clearly state that menu items and prices may vary by location.",
            "For subscription orders, mention cancellation and modification policies.",
        ],
        "possible_use_cases": [
            {"name": "Menu & Ordering", "description": "Drinks, food, seasonal specials, customizations, dietary options", "kb_eligible": True},
            {"name": "Mobile Orders", "description": "Place orders, pickup time, order status, favorites"},
            {"name": "Catering", "description": "Office catering, event coffee service, bulk orders, custom menus"},
            {"name": "Subscriptions", "description": "Coffee subscription, bean selection, delivery frequency, billing"},
            {"name": "Loyalty Program", "description": "Points, rewards, free drink tracking, membership perks"},
            {"name": "General Inquiries", "description": "Hours, locations, wifi, events, private bookings"},
        ],
        "fixed_patterns": None,
    },

    "bakery": {
        "display_name": "Bakery & Pastry Shop",
        "category": "food-hospitality",
        "description": "Custom cakes, daily specials, pre-orders, catering, and wholesale",
        "icon": "cake-slice",
        "placeholder_text": (
            "Describe your bakery specialty (artisan breads, custom cakes, pastries), "
            "any signature styles or inspirations, and additional offerings like wholesale, catering, or baking classes."
        ),
        "expert_backstory": (
            "You are a bakery operations specialist who understands production scheduling, "
            "custom cake order management, wholesale bread delivery logistics, seasonal "
            "menu planning, allergen cross-contamination in a bakery setting, and the "
            "balance between retail and wholesale operations."
        ),
        "compliance_rules": [
            "Always ask about allergies — bakeries have high cross-contamination risk for nuts, gluten, dairy, eggs.",
            "Custom cake orders require clear lead time communication.",
            "Mention that designs shown in photos are approximate — final product may vary slightly.",
        ],
        "possible_use_cases": [
            {"name": "Custom Cake Orders", "description": "Design, size, flavors, dietary needs, pickup date, deposit, modifications"},
            {"name": "Daily Menu", "description": "Today's fresh items, bread schedule, seasonal specials", "kb_eligible": True},
            {"name": "Pre-Orders", "description": "Reserve popular items, holiday specials, bulk orders, pickup scheduling"},
            {"name": "Catering", "description": "Event platters, corporate orders, wedding dessert tables, pricing"},
            {"name": "Wholesale", "description": "Restaurant supply, bulk pricing, delivery schedules, new accounts"},
            {"name": "Classes & Events", "description": "Cake decorating, bread making, kids classes, private parties"},
            {"name": "General Inquiries", "description": "Hours, location, allergens, ingredients, gift cards"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # HEALTHCARE & WELLNESS
    # ──────────────────────────────────────────────
    "healthcare": {
        "display_name": "Healthcare Clinic",
        "category": "healthcare-wellness",
        "description": "Appointments, prescriptions, triage, billing, and patient services",
        "icon": "heart-pulse",
        "placeholder_text": (
            "Describe your practice type (multi-specialty, family medicine, urgent care), "
            "the specialties you cover, and key services like telehealth, in-house labs, or mental health counseling."
        ),
        "expert_backstory": (
            "You are a healthcare operations consultant with deep expertise in clinical "
            "practice management. You understand HIPAA compliance inside and out — what can "
            "and cannot be discussed on the phone, how to handle patient information safely, "
            "and the critical importance of medical disclaimers. You know clinical scheduling "
            "workflows, insurance verification processes, prescription refill procedures, "
            "triage protocols (including when to redirect to 911), patient communication best "
            "practices, and medical terminology (and importantly, when NOT to use it with "
            "patients). You understand the difference between a small family practice and "
            "a large multi-specialty clinic."
        ),
        "compliance_rules": [
            "HIPAA: Never diagnose, never interpret test results, never recommend medications.",
            "Always include: 'I can help with scheduling and general information. For specific medical advice, please consult with your provider.'",
            "For urgent symptoms (chest pain, difficulty breathing, severe bleeding, stroke signs), IMMEDIATELY redirect to 911.",
            "Never confirm or deny whether someone is a patient at the practice.",
            "Always mention after-hours emergency contact number.",
        ],
        "possible_use_cases": [
            {"name": "Urgent Triage", "description": "Life-threatening symptom check (911 redirect), severity assessment, nurse callback scheduling"},
            {"name": "New Patient Registration", "description": "Demographics, insurance info, PCP preference, first visit preparation"},
            {"name": "Appointment Scheduling", "description": "Patient verification, provider preference, rescheduling, cancellation, telehealth option"},
            {"name": "Prescription Refill", "description": "Identity verification, medication/dosage, pharmacy info, authorization status"},
            {"name": "Medical Information", "description": "Services, provider bios, accepted insurance, preparation instructions", "kb_eligible": True},
            {"name": "Insurance & Billing", "description": "Accepted plans, copay info, payment plans, billing disputes, referral process"},
            {"name": "Lab & Test Results", "description": "Direct to patient portal, schedule follow-up (cannot give results over phone)"},
            {"name": "Telehealth Enrollment", "description": "Eligibility, platform setup, technical requirements, scheduling"},
            {"name": "Vaccination & Wellness", "description": "Vaccine schedules, wellness checkup booking, preventive care info", "kb_eligible": True},
            {"name": "Specialist Referral", "description": "Referral process, specialist availability, insurance pre-authorization"},
            {"name": "Mental Health Services", "description": "Therapy options, crisis resources (988 hotline), confidentiality assurance"},
            {"name": "Patient Portal Support", "description": "Login help, password reset, accessing records, messaging providers"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Start call router MUST check for urgent medical concerns FIRST before any other intent.",
        },
    },

    "dental": {
        "display_name": "Dental Practice",
        "category": "healthcare-wellness",
        "description": "Appointments, cleanings, emergencies, insurance, and cosmetic dentistry",
        "icon": "smile",
        "placeholder_text": (
            "Describe your practice type (family, cosmetic, pediatric), the services you offer "
            "such as cleanings, implants, Invisalign, or whitening, and whether you provide financing options."
        ),
        "expert_backstory": (
            "You are a dental practice management expert who understands dental scheduling "
            "complexities (operatory time, hygiene vs. doctor appointments), insurance "
            "verification for dental plans (PPO, HMO, discount plans), treatment plan "
            "presentation, dental emergency triage, cosmetic dentistry consultations, "
            "and patient anxiety management for dental-phobic callers."
        ),
        "compliance_rules": [
            "HIPAA applies — never share patient information without verification.",
            "Never diagnose dental conditions over the phone.",
            "For dental emergencies (severe pain, knocked-out tooth, uncontrolled bleeding), prioritize immediate scheduling.",
            "Clearly explain that treatment plans and costs are estimates until in-person examination.",
        ],
        "possible_use_cases": [
            {"name": "Appointment Scheduling", "description": "Cleanings, exams, procedures, emergency slots, provider preference"},
            {"name": "Dental Emergency", "description": "Pain assessment, knocked-out tooth guidance, same-day scheduling, after-hours protocol"},
            {"name": "Insurance & Billing", "description": "Accepted plans, coverage verification, payment plans, financing options"},
            {"name": "Treatment Information", "description": "Procedure descriptions, prep instructions, recovery expectations", "kb_eligible": True},
            {"name": "Cosmetic Dentistry", "description": "Whitening, veneers, Invisalign, consultations, pricing"},
            {"name": "New Patient Intake", "description": "Registration, insurance info, medical history forms, first visit prep"},
            {"name": "General Inquiries", "description": "Hours, location, providers, accepted plans, parking"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Dental emergency detection must happen early in the call flow.",
        },
    },

    "pharmacy": {
        "display_name": "Pharmacy",
        "category": "healthcare-wellness",
        "description": "Prescriptions, refills, drug info, insurance, and health consultations",
        "icon": "pill",
        "placeholder_text": (
            "Describe your pharmacy type (independent, specialty, compounding), key services like "
            "prescription delivery, immunizations, or custom compounding, and what sets you apart in your community."
        ),
        "expert_backstory": (
            "You are a pharmacy operations consultant who understands prescription workflows, "
            "insurance adjudication, prior authorization processes, drug interaction concerns, "
            "compounding operations, immunization scheduling, and the regulatory requirements "
            "around controlled substances. You know how to handle callers asking about "
            "medication side effects while staying within safe boundaries."
        ),
        "compliance_rules": [
            "HIPAA: Verify patient identity before sharing any prescription information.",
            "Never provide medical advice or recommend medications — direct to pharmacist or physician.",
            "For controlled substances, follow strict verification protocols.",
            "Never confirm or deny prescription existence without patient verification.",
        ],
        "possible_use_cases": [
            {"name": "Prescription Refills", "description": "Refill requests, Rx number lookup, auto-refill enrollment, transfer requests"},
            {"name": "Order Status", "description": "Ready for pickup, processing time, insurance issues, backorder status"},
            {"name": "Drug Information", "description": "General drug info, common side effects (direct to pharmacist for specifics)", "kb_eligible": True},
            {"name": "Insurance & Pricing", "description": "Coverage check, copay info, generic alternatives, discount programs"},
            {"name": "Immunizations", "description": "Available vaccines, scheduling, insurance coverage, walk-in availability"},
            {"name": "Delivery", "description": "Delivery area, scheduling, tracking, same-day options"},
            {"name": "General Inquiries", "description": "Hours, location, drive-through, compounding services"},
        ],
        "fixed_patterns": None,
    },

    "veterinary": {
        "display_name": "Veterinary Clinic",
        "category": "healthcare-wellness",
        "description": "Pet appointments, emergencies, vaccinations, surgery, and pet care info",
        "icon": "paw-print",
        "placeholder_text": (
            "Describe the types of animals you care for, your key services such as surgery, dental care, "
            "boarding, or grooming, and any special offerings like emergency care or wellness plans."
        ),
        "expert_backstory": (
            "You are a veterinary practice management expert who understands small animal "
            "medicine workflows, emergency triage for pets, vaccination schedules, surgical "
            "pre/post-op protocols, pet insurance processes, boarding and grooming operations, "
            "and the emotional sensitivity required when dealing with pet owners, especially "
            "during emergencies or end-of-life discussions."
        ),
        "compliance_rules": [
            "Never diagnose conditions over the phone — always recommend bringing the pet in.",
            "For emergencies (poisoning, trauma, difficulty breathing, seizures), direct to immediate care.",
            "Be sensitive when discussing serious conditions or end-of-life options.",
            "Clearly communicate pre-surgery fasting and medication instructions.",
        ],
        "possible_use_cases": [
            {"name": "Appointment Scheduling", "description": "Wellness exams, sick visits, follow-ups, multiple pet scheduling"},
            {"name": "Pet Emergency", "description": "Symptom assessment, poisoning guidance, after-hours emergency protocol"},
            {"name": "Vaccinations", "description": "Vaccine schedules by species/age, reminders, titers, boarding requirements"},
            {"name": "Surgery & Procedures", "description": "Pre-op instructions, scheduling, cost estimates, recovery expectations"},
            {"name": "Boarding & Grooming", "description": "Availability, pricing, requirements (vaccines), special needs, drop-off/pickup"},
            {"name": "Pet Insurance", "description": "Accepted plans, claims process, wellness plan enrollment"},
            {"name": "General Inquiries", "description": "Hours, location, accepted species, emergency contact, new client registration"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Pet emergency detection must happen first in the call flow.",
        },
    },

    "fitness": {
        "display_name": "Fitness & Gym",
        "category": "healthcare-wellness",
        "description": "Memberships, class schedules, personal training, and facility info",
        "icon": "dumbbell",
        "placeholder_text": (
            "Describe your facility type (full gym, boutique studio, CrossFit), key amenities and class offerings, "
            "and membership options like personal training, family plans, or corporate programs."
        ),
        "expert_backstory": (
            "You are a fitness facility operations expert who understands membership sales "
            "and retention, class scheduling logistics, personal training program design, "
            "facility management, corporate wellness partnerships, and the importance of "
            "creating a welcoming experience for beginners while serving advanced athletes."
        ),
        "compliance_rules": [
            "Never provide specific medical or nutritional advice — recommend consulting a physician.",
            "Clearly state membership terms, cancellation policies, and any commitment periods.",
            "Mention liability waivers are required before first visit.",
        ],
        "possible_use_cases": [
            {"name": "Membership Inquiries", "description": "Plans, pricing, family/corporate rates, free trial, discounts"},
            {"name": "Class Schedule", "description": "Group fitness classes, booking, waitlist, instructor info", "kb_eligible": True},
            {"name": "Personal Training", "description": "Trainer availability, package pricing, assessment booking, specialties"},
            {"name": "Facility Info", "description": "Equipment, hours, pool schedule, locker rooms, parking", "kb_eligible": True},
            {"name": "Account Management", "description": "Freeze, cancel, upgrade, billing questions, guest passes"},
            {"name": "Corporate Wellness", "description": "Company partnerships, group rates, on-site classes, wellness programs"},
        ],
        "fixed_patterns": None,
    },

    "spa": {
        "display_name": "Spa & Wellness Center",
        "category": "healthcare-wellness",
        "description": "Treatment bookings, packages, memberships, gift cards, and wellness info",
        "icon": "flower",
        "placeholder_text": (
            "We're a luxury day spa offering massages, facials, body treatments, "
            "nail services, and wellness packages. We have 8 treatment rooms, a "
            "relaxation lounge, and a couple's suite. We sell skincare products "
            "and offer monthly membership packages."
        ),
        "expert_backstory": (
            "You are a spa and wellness operations consultant who understands treatment "
            "menu design, therapist scheduling, intake form requirements, contraindication "
            "screening, retail product sales, membership and package management, and the "
            "calm, luxurious tone required for spa guest communication."
        ),
        "compliance_rules": [
            "Ask about health contraindications (pregnancy, allergies, skin conditions) before booking treatments.",
            "Clearly state cancellation policy and late arrival policy.",
            "Never provide medical advice about skin conditions — recommend seeing a dermatologist.",
        ],
        "possible_use_cases": [
            {"name": "Treatment Bookings", "description": "Massages, facials, body treatments, therapist preference, couples options"},
            {"name": "Packages & Memberships", "description": "Spa packages, monthly memberships, benefits, pricing"},
            {"name": "Gift Cards", "description": "Purchase, balance check, redemption, custom amounts, e-gift cards"},
            {"name": "Treatment Information", "description": "Service descriptions, duration, what to expect, contraindications", "kb_eligible": True},
            {"name": "Product Sales", "description": "Skincare lines, recommendations, reorder, online shop"},
            {"name": "General Inquiries", "description": "Hours, location, parking, what to bring, group bookings"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # FINANCIAL SERVICES
    # ──────────────────────────────────────────────
    "banking": {
        "display_name": "Banking & Credit Union",
        "category": "financial-services",
        "description": "Accounts, transfers, cards, loans, fraud protection, and more",
        "icon": "landmark",
        "placeholder_text": (
            "We're a community credit union serving Portland metro. 3 branches, "
            "24/7 ATM network. We offer checking, savings, auto loans, home mortgages, "
            "business accounts, investment advisory, and insurance products. NCUA insured."
        ),
        "expert_backstory": (
            "You are a banking operations and compliance consultant with deep expertise in "
            "retail banking, credit unions, and financial services. You understand PCI-DSS "
            "requirements (never read back full account/card numbers), KYC/AML regulations, "
            "banking product structures (checking, savings, CDs, money market, loans, mortgages), "
            "fraud detection and resolution workflows, identity verification best practices, "
            "regulatory disclosure requirements, and financial terminology appropriate for "
            "everyday customers. You know the difference between a large commercial bank "
            "and a community credit union."
        ),
        "compliance_rules": [
            "PCI-DSS: NEVER read back full account numbers (only last 4), NEVER share SSN, NEVER ask for full card number or PIN.",
            "Always include: 'This call may be recorded for quality and training purposes.'",
            "Always remind: '[Bank] will never ask for your PIN, password, or full Social Security number by phone or email.'",
            "Identity verification is MANDATORY before any account-specific information is shared.",
            "Mention FDIC/NCUA insured status where appropriate.",
            "For fraud/lost card, treat as URGENT — skip regular queue and act immediately.",
        ],
        "possible_use_cases": [
            {"name": "Account Inquiries", "description": "Balance, recent transactions, statements, account summary, interest rates"},
            {"name": "Transfers & Payments", "description": "Internal/external transfers, bill pay, wire transfers, recurring payments"},
            {"name": "Card Services", "description": "Lost/stolen card (URGENT block), activation, PIN reset, disputes, travel notices"},
            {"name": "Loan & Mortgage Info", "description": "Products, rates, eligibility, application process, pre-qualification, refinancing", "kb_eligible": True},
            {"name": "Fraud & Security", "description": "Suspicious activity, account freeze, identity theft protocol, security measures"},
            {"name": "New Accounts", "description": "Account types, features, fees, minimum balances, promotional rates, opening process"},
            {"name": "Tech Support", "description": "Online banking, mobile app, 2FA, Zelle/P2P, ATM issues"},
            {"name": "Investment & Wealth", "description": "Portfolio overview, advisor scheduling, IRA/401k info", "kb_eligible": True},
            {"name": "Business Banking", "description": "Business accounts, merchant services, payroll, business loans"},
            {"name": "Insurance Products", "description": "Life, auto, home insurance through the bank, bundling discounts", "kb_eligible": True},
            {"name": "Foreign Exchange", "description": "Currency exchange rates, international wire fees, travel currency"},
        ],
        "fixed_patterns": {
            "verify_before_route": True,
            "description": (
                "Banking workflows MUST have: Start Call → Identity Verification Agent → "
                "Intent Router → [service agents]. Verification is mandatory before any "
                "account access. The only exception is lost/stolen card which should be "
                "detected at the start call level and fast-tracked."
            ),
        },
    },

    "insurance": {
        "display_name": "Insurance Agency",
        "category": "financial-services",
        "description": "Quotes, claims, policy management, renewals, and coverage questions",
        "icon": "shield-check",
        "placeholder_text": (
            "We're an independent insurance agency offering auto, home, life, "
            "business, and umbrella policies from 15+ carriers. We serve families "
            "and small businesses. Licensed in 5 states. We do annual policy reviews "
            "and help with claims advocacy."
        ),
        "expert_backstory": (
            "You are an insurance agency operations consultant who understands "
            "multi-carrier quoting, policy lifecycle management, claims processes "
            "across different insurance types, underwriting basics that affect "
            "customer-facing conversations, and regulatory requirements for insurance "
            "communications. You know how to explain complex coverage concepts in "
            "plain language."
        ),
        "compliance_rules": [
            "Never guarantee coverage or make binding decisions — only licensed agents can bind policies.",
            "Always note that quotes are estimates subject to underwriting approval.",
            "Verify policyholder identity before discussing account details.",
            "Include state-required disclaimers where applicable.",
        ],
        "possible_use_cases": [
            {"name": "Quote Requests", "description": "Auto, home, life, business quotes, information gathering, follow-up scheduling"},
            {"name": "Claims Filing", "description": "First notice of loss, documentation needs, adjuster scheduling, status updates"},
            {"name": "Policy Management", "description": "Changes, additions, deletions, coverage adjustments, address updates"},
            {"name": "Billing & Payments", "description": "Premium due dates, payment options, autopay, late payment, reinstatement"},
            {"name": "Coverage Questions", "description": "What's covered, deductibles, limits, exclusions, recommendations", "kb_eligible": True},
            {"name": "Renewals", "description": "Upcoming renewals, rate changes, review scheduling, shopping alternatives"},
            {"name": "Certificates & ID Cards", "description": "Certificate of insurance requests, ID card replacement, proof of coverage"},
        ],
        "fixed_patterns": None,
    },

    "accounting": {
        "display_name": "Accounting & Tax",
        "category": "financial-services",
        "description": "Tax prep, bookkeeping, consultations, deadlines, and financial planning",
        "icon": "calculator",
        "placeholder_text": (
            "We're a CPA firm with 6 accountants serving individuals and small businesses. "
            "We offer tax preparation, bookkeeping, payroll services, QuickBooks setup, "
            "business formation, and financial planning. Tax season hours extended to evenings and Saturdays."
        ),
        "expert_backstory": (
            "You are an accounting practice management expert who understands tax season "
            "workflow management, client document collection processes, bookkeeping service "
            "structures, payroll processing, and the importance of deadline management. "
            "You know how to communicate about financial matters without giving specific "
            "tax advice over the phone."
        ),
        "compliance_rules": [
            "Never provide specific tax advice over the phone — schedule a consultation.",
            "Client confidentiality is paramount — verify identity before discussing any account details.",
            "Clearly communicate document deadlines and extension requirements.",
            "Mention that tax situations are unique and require professional review.",
        ],
        "possible_use_cases": [
            {"name": "Tax Preparation", "description": "Scheduling, document checklist, status updates, extension filing"},
            {"name": "Bookkeeping", "description": "Service inquiries, monthly packages, software setup, reporting"},
            {"name": "Consultations", "description": "Business formation, tax planning, financial review, scheduling"},
            {"name": "Payroll Services", "description": "Setup, processing schedules, tax deposits, year-end forms"},
            {"name": "Document Requests", "description": "Prior year returns, financial statements, audit support"},
            {"name": "General Inquiries", "description": "Services, pricing, deadlines, new client onboarding"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # RETAIL & E-COMMERCE
    # ──────────────────────────────────────────────
    "retail": {
        "display_name": "Retail Store",
        "category": "retail-ecommerce",
        "description": "Products, orders, returns, shipping, loyalty programs, and support",
        "icon": "shopping-bag",
        "placeholder_text": (
            "We sell premium outdoor gear online and in our Seattle flagship store. "
            "30-day return policy, free shipping over $75. We carry Patagonia, "
            "Arc'teryx, and our own house brand. Loyalty program, gift cards, "
            "size consultations, and we do wholesale for businesses."
        ),
        "expert_backstory": (
            "You are a retail operations and e-commerce consultant with extensive experience "
            "in omnichannel retail. You understand inventory management, return/exchange "
            "logistics, shipping carrier workflows, customer loyalty program psychology, "
            "chargeback and dispute processes, wholesale/B2B operations, size and fit "
            "guidance, gift services, subscription commerce, and price matching policies. "
            "You know the difference between a luxury boutique caller experience and a "
            "high-volume online retailer's support line."
        ),
        "compliance_rules": [
            "Always clearly state the return policy window and conditions.",
            "Never make promises about stock availability without checking.",
            "For pricing, mention that prices may vary and promotions have terms.",
            "Handle payment information carefully — never ask for full card numbers over the phone.",
        ],
        "possible_use_cases": [
            {"name": "Product Inquiry", "description": "Availability, specs, pricing, comparisons, recommendations, stock alerts", "kb_eligible": True},
            {"name": "Order Status", "description": "Order lookup, tracking, delivery updates, delay handling"},
            {"name": "Returns & Exchanges", "description": "Eligibility check, RMA initiation, return label, refund timeline, exchange process"},
            {"name": "Shipping & Delivery", "description": "Shipping options/costs, international, address changes, lost/damaged claims"},
            {"name": "Complaints & Escalation", "description": "Active listening, resolution cascade, supervisor escalation"},
            {"name": "Loyalty & Promotions", "description": "Points balance, rewards, tier status, current promotions, referral program"},
            {"name": "Size & Fit Guidance", "description": "Size charts, fit recommendations, measurement instructions", "kb_eligible": True},
            {"name": "Gift Services", "description": "Gift cards (purchase/balance/redeem), gift wrapping, gift registry, corporate gifting"},
            {"name": "Wholesale / B2B", "description": "Bulk pricing, minimum orders, business accounts, net terms"},
            {"name": "Subscription Management", "description": "Subscription management, frequency changes, skip/pause, product swaps"},
            {"name": "Store Locator", "description": "Nearest store, hours, in-stock at location, curbside pickup"},
            {"name": "Price Match", "description": "Price match policy, competitor verification, adjustment process"},
        ],
        "fixed_patterns": None,
    },

    "ecommerce": {
        "display_name": "E-Commerce",
        "category": "retail-ecommerce",
        "description": "Online store support, order management, shipping, returns, and product help",
        "icon": "shopping-cart",
        "placeholder_text": (
            "We're an online marketplace selling handmade home decor from independent artisans. "
            "We ship worldwide, offer gift wrapping, have a 30-day return policy, and feature "
            "a monthly subscription box. Over 5,000 unique products from 200+ makers."
        ),
        "expert_backstory": (
            "You are an e-commerce operations expert specializing in online-only businesses. "
            "You understand cart abandonment recovery, shipping logistics across carriers, "
            "international shipping and customs, digital product delivery, marketplace "
            "seller management, and high-volume customer service operations."
        ),
        "compliance_rules": [
            "Never process payment information over the phone — direct to secure checkout.",
            "Clearly state shipping timelines, return windows, and any restocking fees.",
            "For international orders, mention potential customs duties and import taxes.",
        ],
        "possible_use_cases": [
            {"name": "Order Support", "description": "Order status, modifications, cancellations, tracking, delivery issues"},
            {"name": "Product Information", "description": "Specifications, availability, recommendations, custom requests", "kb_eligible": True},
            {"name": "Returns & Refunds", "description": "Return process, refund timeline, exchange options, defective items"},
            {"name": "Shipping", "description": "Rates, international shipping, tracking, lost packages, expedited options"},
            {"name": "Account Help", "description": "Login issues, wishlist, order history, preferences, account deletion"},
            {"name": "Promotions", "description": "Current deals, discount codes, loyalty rewards, referral program"},
        ],
        "fixed_patterns": None,
    },

    "grocery": {
        "display_name": "Grocery & Supermarket",
        "category": "retail-ecommerce",
        "description": "Store info, delivery, weekly specials, deli orders, and loyalty programs",
        "icon": "apple",
        "placeholder_text": (
            "We're a family-owned grocery store with 2 locations. We have a full deli, "
            "bakery, organic produce section, and butcher counter. We offer curbside pickup, "
            "home delivery within 15 miles, and a weekly flyer with deals. Open daily 7am-10pm."
        ),
        "expert_backstory": (
            "You are a grocery retail operations expert who understands perishable inventory "
            "management, deli and bakery department operations, delivery/pickup logistics, "
            "weekly promotional cycles, loyalty program management, and the unique needs "
            "of grocery shoppers including dietary restrictions and product sourcing questions."
        ),
        "compliance_rules": [
            "Allergen awareness is critical — especially for deli, bakery, and prepared foods.",
            "Prices and availability change frequently — always recommend confirming in-store.",
            "For delivery, clearly communicate minimum orders, fees, and delivery windows.",
        ],
        "possible_use_cases": [
            {"name": "Store Information", "description": "Hours, locations, departments, services, holiday hours", "kb_eligible": True},
            {"name": "Delivery & Pickup", "description": "Ordering, delivery windows, curbside pickup, minimum orders, fees"},
            {"name": "Deli & Bakery Orders", "description": "Custom cakes, party platters, catering trays, advance orders"},
            {"name": "Weekly Specials", "description": "Current deals, flyer items, loyalty discounts, rain checks"},
            {"name": "Product Inquiries", "description": "Availability, brands, organic options, special orders, dietary needs"},
            {"name": "Loyalty Program", "description": "Points, rewards, digital coupons, fuel discounts, enrollment"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # PROFESSIONAL SERVICES
    # ──────────────────────────────────────────────
    "legal": {
        "display_name": "Law Firm",
        "category": "professional-services",
        "description": "Consultations, case inquiries, appointments, document requests, and billing",
        "icon": "scale",
        "placeholder_text": (
            "We're a mid-size law firm with 12 attorneys specializing in personal injury, "
            "family law, estate planning, and business law. We offer free initial consultations "
            "for personal injury cases. Offices in two locations, virtual consultations available."
        ),
        "expert_backstory": (
            "You are a legal practice management consultant who understands intake processes "
            "for different practice areas, attorney-client privilege limitations on phone "
            "conversations, conflict checking procedures, fee structure communication, "
            "court deadline awareness, and the sensitivity required for family law and "
            "personal injury callers who may be in distress."
        ),
        "compliance_rules": [
            "Never provide legal advice — only attorneys can give legal advice. Schedule a consultation.",
            "Attorney-client privilege: be careful about what is discussed before engagement is established.",
            "Clearly state that initial consultations may or may not be free depending on practice area.",
            "For urgent matters (restraining orders, arrests, custody emergencies), flag for immediate attorney attention.",
        ],
        "possible_use_cases": [
            {"name": "New Client Intake", "description": "Case type, basic facts, scheduling consultation, conflict check"},
            {"name": "Case Status", "description": "Updates on existing cases, next steps, upcoming dates, document needs"},
            {"name": "Consultations", "description": "Scheduling, preparation, what to bring, virtual vs in-person"},
            {"name": "Billing & Payments", "description": "Invoice questions, payment plans, retainer balance, trust account"},
            {"name": "Practice Areas", "description": "Services offered, attorney bios, experience, case types handled", "kb_eligible": True},
            {"name": "Document Requests", "description": "Copies of filings, contracts, closing documents, estate plans"},
            {"name": "Urgent Matters", "description": "Arrests, emergency custody, restraining orders — priority routing"},
        ],
        "fixed_patterns": None,
    },

    "consulting": {
        "display_name": "Consulting Firm",
        "category": "professional-services",
        "description": "Service inquiries, project scoping, scheduling, proposals, and client support",
        "icon": "briefcase",
        "placeholder_text": (
            "We're a management consulting firm with 20 consultants specializing in "
            "digital transformation, process optimization, and change management. "
            "We serve mid-market companies across manufacturing, healthcare, and financial services. "
            "Engagements range from 2-week assessments to 12-month transformations."
        ),
        "expert_backstory": (
            "You are a professional services operations expert who understands consulting "
            "sales cycles, proposal and SOW development, resource allocation, engagement "
            "management, and the importance of qualifying leads effectively during initial "
            "contact. You know how to communicate value propositions without giving away "
            "methodology details."
        ),
        "compliance_rules": [
            "Client information is confidential — never reference other client engagements by name.",
            "Do not provide specific advice during intake — schedule a proper discovery call.",
            "Clearly communicate engagement structures and typical timelines.",
        ],
        "possible_use_cases": [
            {"name": "Service Inquiries", "description": "Capabilities, methodologies, industry expertise, case studies"},
            {"name": "Lead Qualification", "description": "Company size, challenge, timeline, budget, decision-maker identification"},
            {"name": "Consultation Scheduling", "description": "Discovery calls, availability, preparation, attendee coordination"},
            {"name": "Client Support", "description": "Project status, deliverable updates, escalation, feedback"},
            {"name": "Proposals & Pricing", "description": "Engagement types, pricing models, timeline expectations, SOW process"},
        ],
        "fixed_patterns": None,
    },

    "recruitment": {
        "display_name": "Recruitment & Staffing",
        "category": "professional-services",
        "description": "Job inquiries, candidate screening, interview scheduling, and placement",
        "icon": "users",
        "placeholder_text": (
            "We're a staffing agency specializing in tech and healthcare placements. "
            "We handle contract, contract-to-hire, and direct-hire positions. "
            "We serve candidates and employers across 8 states. Average placement "
            "time is 3 weeks. We also offer executive search services."
        ),
        "expert_backstory": (
            "You are a recruitment operations expert who understands candidate screening "
            "workflows, ATS management, job order fulfillment, interview scheduling across "
            "time zones, offer negotiation communication, and compliance requirements "
            "for staffing (especially in healthcare with credentialing). You can handle "
            "both candidate-side and employer-side conversations effectively."
        ),
        "compliance_rules": [
            "Never share candidate information with unauthorized parties.",
            "EEO compliance — never ask about protected characteristics (age, race, religion, etc.).",
            "Clearly communicate whether positions are contract, contract-to-hire, or direct-hire.",
            "For healthcare placements, mention credentialing and background check requirements.",
        ],
        "possible_use_cases": [
            {"name": "Job Inquiries", "description": "Open positions, requirements, location, compensation range, application process"},
            {"name": "Candidate Screening", "description": "Experience, skills, availability, salary expectations, work authorization"},
            {"name": "Interview Scheduling", "description": "Coordination, preparation tips, format, rescheduling, follow-up"},
            {"name": "Employer Services", "description": "Staffing needs, job order intake, pricing, SLA, engagement models"},
            {"name": "Placement Support", "description": "Onboarding, first-day info, payroll setup, benefits enrollment"},
            {"name": "General Inquiries", "description": "Services, industries served, process, timeframes, office locations"},
        ],
        "fixed_patterns": None,
    },

    "marketing": {
        "display_name": "Marketing Agency",
        "category": "professional-services",
        "description": "Campaign inquiries, client onboarding, project updates, and lead qualification",
        "icon": "megaphone",
        "placeholder_text": (
            "We're a full-service digital marketing agency with 15 team members. "
            "We specialize in SEO, PPC, social media, content marketing, web design, "
            "and branding. We serve small to mid-size businesses with monthly retainer "
            "packages starting at $2,000/month."
        ),
        "expert_backstory": (
            "You are a marketing agency operations expert who understands client "
            "onboarding workflows, project management across multiple services, "
            "creative brief development, campaign reporting, and the sales process "
            "for agency services. You know how to qualify leads and communicate "
            "ROI without overpromising results."
        ),
        "compliance_rules": [
            "Never guarantee specific results (rankings, leads, conversions) — marketing outcomes vary.",
            "Client campaign data is confidential — never reference other client metrics.",
            "Clearly communicate contract terms, notice periods, and pricing structures.",
        ],
        "possible_use_cases": [
            {"name": "Service Inquiries", "description": "Capabilities, packages, pricing, case studies, portfolio"},
            {"name": "Lead Qualification", "description": "Business type, goals, budget, timeline, current marketing efforts"},
            {"name": "Client Onboarding", "description": "Kickoff scheduling, asset collection, access setup, strategy timeline"},
            {"name": "Project Updates", "description": "Campaign status, deliverable timelines, revision requests, approvals"},
            {"name": "Reporting & Results", "description": "Monthly reports, KPI reviews, strategy adjustments, meeting scheduling"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # HOME & PROPERTY
    # ──────────────────────────────────────────────
    "real_estate": {
        "display_name": "Real Estate",
        "category": "home-property",
        "description": "Listings, viewings, buyer/seller inquiries, market info, and closings",
        "icon": "home",
        "placeholder_text": (
            "We're a real estate team of 8 agents covering the greater Denver metro area. "
            "We help buyers and sellers with residential properties — single-family, condos, "
            "and townhomes. We also handle rentals and property management for 50+ units. "
            "Average sale price in our market is $550K."
        ),
        "expert_backstory": (
            "You are a real estate operations expert who understands lead qualification, "
            "showing scheduling, listing presentation workflows, offer management, "
            "transaction coordination, and the emotional aspects of home buying/selling. "
            "You know fair housing laws and can communicate market information without "
            "making promises about values or returns."
        ),
        "compliance_rules": [
            "Fair Housing Act: Never steer based on race, religion, national origin, familial status, disability, or sex.",
            "Never guarantee property values or investment returns.",
            "Clearly state that agent availability may vary and showings are by appointment.",
            "For pricing, mention that list prices and estimates are not guarantees.",
        ],
        "possible_use_cases": [
            {"name": "Buyer Inquiries", "description": "Property details, scheduling showings, pre-qualification, neighborhood info"},
            {"name": "Seller Inquiries", "description": "Market analysis, listing process, pricing strategy, agent consultation"},
            {"name": "Showing Scheduling", "description": "Property tours, open houses, virtual tours, agent coordination"},
            {"name": "Market Information", "description": "Area stats, school ratings, commute times, recent sales", "kb_eligible": True},
            {"name": "Transaction Support", "description": "Closing timeline, document needs, inspection scheduling, title questions"},
            {"name": "Rental Inquiries", "description": "Available rentals, application process, lease terms, move-in costs"},
            {"name": "General Inquiries", "description": "Agent bios, office locations, service areas, testimonials"},
        ],
        "fixed_patterns": None,
    },

    "property_management": {
        "display_name": "Property Management",
        "category": "home-property",
        "description": "Tenant services, maintenance requests, leasing, rent payments, and owner support",
        "icon": "building-2",
        "placeholder_text": (
            "We manage 300+ residential units across 15 properties. We handle tenant "
            "relations, maintenance, rent collection, leasing, and owner reporting. "
            "24/7 emergency maintenance line. We manage single-family homes, apartments, "
            "and small commercial properties."
        ),
        "expert_backstory": (
            "You are a property management operations expert who understands tenant "
            "communication, maintenance request triage (emergency vs. routine), lease "
            "administration, rent collection workflows, owner reporting, and fair housing "
            "compliance. You handle both tenant-side and owner-side conversations."
        ),
        "compliance_rules": [
            "Fair Housing Act compliance is mandatory in all tenant interactions.",
            "Never disclose tenant information to unauthorized parties.",
            "Maintenance emergencies (flood, fire, gas leak, no heat) must be escalated immediately.",
            "Clearly communicate lease terms, fees, and security deposit policies.",
        ],
        "possible_use_cases": [
            {"name": "Maintenance Requests", "description": "Issue reporting, priority assessment, scheduling, emergency dispatch"},
            {"name": "Rent & Payments", "description": "Payment options, due dates, late fees, payment plans, ledger questions"},
            {"name": "Leasing Inquiries", "description": "Available units, pricing, application process, move-in requirements"},
            {"name": "Tenant Services", "description": "Lease questions, renewals, move-out process, roommate changes"},
            {"name": "Owner Services", "description": "Property performance, statements, maintenance approvals, vacancy updates"},
            {"name": "Emergency Line", "description": "After-hours emergencies — flood, fire, gas leak, lockout, no heat/AC"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Emergency maintenance must be detected and escalated immediately at call start.",
        },
    },

    "home_services": {
        "display_name": "Home Services",
        "category": "home-property",
        "description": "Plumbing, HVAC, electrical, repairs, estimates, and emergency service",
        "icon": "wrench",
        "placeholder_text": (
            "We're a licensed plumbing and HVAC company serving the Dallas-Fort Worth area. "
            "We handle repairs, installations, maintenance plans, and emergency service 24/7. "
            "Free estimates on installations. 10+ technicians on staff. Licensed, bonded, and insured."
        ),
        "expert_backstory": (
            "You are a home services operations expert who understands dispatching, "
            "emergency triage for home systems (burst pipes, no heat/AC, gas leaks), "
            "estimate scheduling, maintenance plan sales, and the logistics of managing "
            "a fleet of technicians across a service area."
        ),
        "compliance_rules": [
            "For gas leaks or carbon monoxide concerns, advise evacuating and calling 911 first.",
            "Clearly state that estimates are free/paid and any dispatch fees.",
            "Mention licensing, bonding, and insurance when relevant.",
            "Never guarantee specific pricing over the phone — diagnoses require on-site inspection.",
        ],
        "possible_use_cases": [
            {"name": "Emergency Service", "description": "Burst pipes, no heat/AC, gas smell, electrical hazards — immediate dispatch"},
            {"name": "Repair Scheduling", "description": "Issue description, availability, technician assignment, time windows"},
            {"name": "Estimates", "description": "New installations, renovations, system replacements, on-site assessment booking"},
            {"name": "Maintenance Plans", "description": "Annual plans, seasonal tune-ups, priority scheduling, member discounts"},
            {"name": "General Inquiries", "description": "Services, service area, hours, licensing, payment options"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Emergency situations (gas leak, flooding, no heat) must be detected immediately.",
        },
    },

    "cleaning": {
        "display_name": "Cleaning Services",
        "category": "home-property",
        "description": "Residential cleaning, commercial cleaning, scheduling, quotes, and special services",
        "icon": "sparkles",
        "placeholder_text": (
            "We provide residential and commercial cleaning services across Miami-Dade. "
            "We offer recurring weekly/biweekly/monthly cleans, deep cleaning, move-in/out "
            "cleaning, post-construction cleanup, and office cleaning. 50+ trained cleaners. "
            "Eco-friendly product options available."
        ),
        "expert_backstory": (
            "You are a cleaning services operations expert who understands job estimation, "
            "crew scheduling, supply management, quality control, and the differences between "
            "residential and commercial cleaning operations. You know how to qualify leads, "
            "handle recurring booking management, and address service quality concerns."
        ),
        "compliance_rules": [
            "Clearly communicate pricing structure (flat rate vs hourly vs square footage).",
            "Mention insurance and bonding status for client confidence.",
            "Set clear expectations about what is and isn't included in standard cleans.",
        ],
        "possible_use_cases": [
            {"name": "Quote Requests", "description": "Home size, cleaning type, frequency, special needs, scheduling"},
            {"name": "Booking & Scheduling", "description": "New bookings, recurring schedules, one-time deep cleans, availability"},
            {"name": "Service Management", "description": "Reschedule, cancel, add services, change frequency, special requests"},
            {"name": "Commercial Cleaning", "description": "Office cleaning, retail, medical facilities, custom proposals"},
            {"name": "Quality & Complaints", "description": "Service feedback, re-clean requests, damage claims, team changes"},
            {"name": "General Inquiries", "description": "Services, pricing, service area, eco-friendly options, supplies"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # EDUCATION & TRAINING
    # ──────────────────────────────────────────────
    "education": {
        "display_name": "School & University",
        "category": "education-training",
        "description": "Admissions, enrollment, course info, financial aid, and student services",
        "icon": "graduation-cap",
        "placeholder_text": (
            "We're a private university with 5,000 students offering undergraduate "
            "and graduate programs in business, engineering, healthcare, and liberal arts. "
            "We have on-campus and online programs, financial aid, career services, "
            "and athletic programs. Rolling admissions for most programs."
        ),
        "expert_backstory": (
            "You are a higher education operations expert who understands admissions "
            "funnels, enrollment management, financial aid processes (FAFSA, scholarships, "
            "payment plans), academic advising, student services, and the complex decision "
            "journey of prospective students and their families."
        ),
        "compliance_rules": [
            "FERPA: Never share student records or enrollment status without proper authorization.",
            "Financial aid information is specific to each student — provide general info only.",
            "Never guarantee admission or specific scholarship amounts.",
        ],
        "possible_use_cases": [
            {"name": "Admissions", "description": "Application process, requirements, deadlines, campus tours, decision timeline"},
            {"name": "Program Information", "description": "Degrees, courses, faculty, accreditation, career outcomes", "kb_eligible": True},
            {"name": "Financial Aid", "description": "FAFSA, scholarships, grants, payment plans, tuition costs"},
            {"name": "Enrollment", "description": "Registration, class schedules, prerequisites, add/drop, transcripts"},
            {"name": "Student Services", "description": "Housing, dining, health services, counseling, career center"},
            {"name": "General Inquiries", "description": "Campus info, events, parking, contact departments"},
        ],
        "fixed_patterns": None,
    },

    "tutoring": {
        "display_name": "Tutoring & Test Prep",
        "category": "education-training",
        "description": "Subject tutoring, test prep, scheduling, progress tracking, and pricing",
        "icon": "book-open",
        "placeholder_text": (
            "We offer 1-on-1 and small group tutoring for K-12 and college students. "
            "Subjects include math, science, English, and SAT/ACT prep. In-person at "
            "our learning center and online via Zoom. 50+ certified tutors. "
            "Free initial assessment for new students."
        ),
        "expert_backstory": (
            "You are a tutoring center operations expert who understands student assessment, "
            "tutor matching, session scheduling across subjects and levels, progress "
            "tracking communication with parents, test prep program structures, and "
            "the enrollment journey from inquiry to ongoing engagement."
        ),
        "compliance_rules": [
            "For minors, all communication should go through parents/guardians.",
            "Never guarantee specific grade improvements or test score increases.",
            "Clearly communicate session policies (cancellation, makeup, no-show).",
        ],
        "possible_use_cases": [
            {"name": "Program Inquiries", "description": "Subjects, levels, formats, pricing, tutor qualifications"},
            {"name": "Assessment & Enrollment", "description": "Initial assessment scheduling, tutor matching, package selection"},
            {"name": "Session Scheduling", "description": "Booking, rescheduling, cancellation, recurring sessions, availability"},
            {"name": "Test Prep", "description": "SAT, ACT, GRE programs, practice tests, timelines, packages", "kb_eligible": True},
            {"name": "Progress Updates", "description": "Student progress, tutor feedback, parent conferences, goal adjustments"},
            {"name": "General Inquiries", "description": "Hours, locations, online options, free trial, group rates"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # TECHNOLOGY
    # ──────────────────────────────────────────────
    "saas": {
        "display_name": "SaaS & Software",
        "category": "technology",
        "description": "Product demos, technical support, billing, onboarding, and feature inquiries",
        "icon": "cloud",
        "placeholder_text": (
            "We're a B2B SaaS company offering project management software for construction "
            "companies. 3 pricing tiers (Starter, Pro, Enterprise). 5,000+ customers. "
            "We offer a 14-day free trial, API access on Pro+, and dedicated account managers "
            "for Enterprise. 99.9% uptime SLA."
        ),
        "expert_backstory": (
            "You are a SaaS operations expert who understands product-led growth, "
            "trial-to-paid conversion, tier-based pricing communication, technical "
            "support triage, onboarding workflows, feature request management, and "
            "enterprise sales qualification. You know how to handle both self-serve "
            "users and enterprise buyers."
        ),
        "compliance_rules": [
            "Never share other customer data or usage patterns.",
            "For security-related issues, escalate to the security team immediately.",
            "Clearly communicate pricing, contract terms, and data handling policies.",
            "SOC 2 / compliance certifications should be mentioned when asked about security.",
        ],
        "possible_use_cases": [
            {"name": "Product Demos", "description": "Scheduling demos, feature overview, use case matching, trial setup"},
            {"name": "Technical Support", "description": "Bug reports, troubleshooting, integration help, API questions"},
            {"name": "Billing & Plans", "description": "Pricing, upgrades, downgrades, invoices, payment methods, cancellation"},
            {"name": "Onboarding", "description": "Setup guidance, data migration, training scheduling, best practices"},
            {"name": "Feature Requests", "description": "Feature inquiries, roadmap questions, beta access, feedback"},
            {"name": "Enterprise Sales", "description": "Custom pricing, security review, SLA, POC, procurement process"},
        ],
        "fixed_patterns": None,
    },

    "it_support": {
        "display_name": "IT Support & MSP",
        "category": "technology",
        "description": "Help desk, troubleshooting, onboarding, network issues, and managed services",
        "icon": "monitor",
        "placeholder_text": (
            "We're a managed IT services provider supporting 80+ small and mid-size businesses. "
            "We handle help desk support, network management, cybersecurity, cloud migration, "
            "hardware procurement, and 24/7 monitoring. Average response time under 15 minutes."
        ),
        "expert_backstory": (
            "You are an MSP operations expert who understands tiered support models, "
            "ticket triage and prioritization, SLA management, remote monitoring and "
            "management (RMM), cybersecurity incident response, and the balance between "
            "proactive and reactive support. You can communicate technical concepts to "
            "non-technical business owners."
        ),
        "compliance_rules": [
            "Never share credentials or sensitive system information over the phone.",
            "For suspected security breaches, escalate immediately to the security team.",
            "Clearly communicate SLA response times and escalation procedures.",
            "Verify caller identity before providing system access or making changes.",
        ],
        "possible_use_cases": [
            {"name": "Help Desk", "description": "Password resets, software issues, email problems, printer issues, connectivity"},
            {"name": "Emergency Support", "description": "System down, security breach, ransomware, critical outage — priority escalation"},
            {"name": "Service Inquiries", "description": "Managed service plans, pricing, capabilities, onboarding process"},
            {"name": "Project Requests", "description": "Office setup, migration, hardware procurement, network upgrades"},
            {"name": "Account Management", "description": "Contract questions, billing, service reviews, adding users/devices"},
        ],
        "fixed_patterns": {
            "urgency_first": True,
            "description": "Security incidents and system outages must be detected and escalated immediately.",
        },
    },

    "telecom": {
        "display_name": "Telecommunications",
        "category": "technology",
        "description": "Plans, billing, technical support, equipment, and account management",
        "icon": "phone",
        "placeholder_text": (
            "We're a regional internet and phone service provider covering rural communities. "
            "We offer fiber internet (up to 1 Gbps), VoIP phone service, and TV streaming "
            "bundles. 30,000+ residential and business customers. 24/7 technical support."
        ),
        "expert_backstory": (
            "You are a telecommunications operations expert who understands service plan "
            "structures, bandwidth and connectivity troubleshooting, equipment provisioning, "
            "service activation workflows, outage management communication, and the regulatory "
            "landscape for telecom providers."
        ),
        "compliance_rules": [
            "Verify account holder identity before making any account changes.",
            "Clearly communicate contract terms, early termination fees, and promotional pricing end dates.",
            "For outages, provide honest estimated restoration times.",
            "Never share account information with unauthorized parties.",
        ],
        "possible_use_cases": [
            {"name": "Plan Inquiries", "description": "Available plans, pricing, speeds, bundles, promotional offers"},
            {"name": "Technical Support", "description": "Connectivity issues, speed problems, equipment troubleshooting, outage info"},
            {"name": "Billing", "description": "Bill explanation, payment options, autopay, disputes, promotional credits"},
            {"name": "Account Management", "description": "Plan changes, upgrades, moves, cancellation, account holder changes"},
            {"name": "New Service", "description": "Availability check, installation scheduling, equipment options, activation"},
            {"name": "Outage Information", "description": "Current outages, estimated restoration, alternative options, credits"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # AUTOMOTIVE
    # ──────────────────────────────────────────────
    "auto_dealership": {
        "display_name": "Auto Dealership",
        "category": "automotive",
        "description": "Vehicle inquiries, test drives, financing, trade-ins, and service scheduling",
        "icon": "car",
        "placeholder_text": (
            "We're a Toyota dealership with new and certified pre-owned inventory. "
            "We have an on-site service center, parts department, and body shop. "
            "We offer financing through multiple lenders, accept trade-ins, and "
            "have a 7-day exchange policy on certified pre-owned vehicles."
        ),
        "expert_backstory": (
            "You are an automotive dealership operations expert who understands vehicle "
            "sales processes, test drive scheduling, financing and leasing structures, "
            "trade-in valuation communication, service department operations, parts "
            "ordering, and the customer journey from initial inquiry to post-sale service."
        ),
        "compliance_rules": [
            "Never quote exact financing rates without running credit — rates vary by creditworthiness.",
            "Clearly state that vehicle prices may not include taxes, fees, and dealer add-ons.",
            "Trade-in values are estimates until in-person inspection.",
            "Advertised prices and inventory are subject to change.",
        ],
        "possible_use_cases": [
            {"name": "Vehicle Inquiries", "description": "Inventory search, specs, pricing, availability, comparisons", "kb_eligible": True},
            {"name": "Test Drives", "description": "Scheduling, availability, required documents, trade-in during visit"},
            {"name": "Financing", "description": "Pre-qualification, lease vs buy, payment estimates, required documents"},
            {"name": "Trade-In", "description": "Initial valuation, required info, scheduling appraisal, payoff process"},
            {"name": "Service Department", "description": "Maintenance scheduling, recalls, warranty work, repair estimates"},
            {"name": "Parts & Accessories", "description": "Parts ordering, availability, pricing, installation scheduling"},
            {"name": "General Inquiries", "description": "Hours, location, current promotions, special events"},
        ],
        "fixed_patterns": None,
    },

    "auto_repair": {
        "display_name": "Auto Repair Shop",
        "category": "automotive",
        "description": "Repair scheduling, diagnostics, estimates, maintenance, and towing",
        "icon": "settings",
        "placeholder_text": (
            "We're an independent auto repair shop specializing in European vehicles "
            "(BMW, Mercedes, Audi, VW). ASE-certified mechanics, 20+ years experience. "
            "We do diagnostics, brakes, engine work, transmission, electrical, and "
            "state inspections. Loaner cars available for major repairs."
        ),
        "expert_backstory": (
            "You are an auto repair shop operations expert who understands appointment "
            "scheduling with bay/lift availability, diagnostic workflow communication, "
            "estimate approval processes, parts sourcing timelines, and customer "
            "communication about complex repairs in understandable terms."
        ),
        "compliance_rules": [
            "Never authorize repairs without customer approval — always communicate estimates first.",
            "Clearly explain diagnostic fees and whether they apply toward repair costs.",
            "Warranties on parts and labor should be clearly stated.",
        ],
        "possible_use_cases": [
            {"name": "Appointment Scheduling", "description": "Repair type, vehicle info, drop-off/pickup times, loaner car"},
            {"name": "Diagnostics", "description": "Symptom description, check engine light, noise/vibration, scheduling"},
            {"name": "Estimates", "description": "Repair cost estimates, parts availability, timeline, approval process"},
            {"name": "Maintenance", "description": "Oil changes, tire rotation, brake inspection, fluid flushes, tune-ups"},
            {"name": "Status Updates", "description": "Repair progress, additional findings, completion estimate, pickup ready"},
            {"name": "General Inquiries", "description": "Services, specialties, hours, location, warranty, towing"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # TRAVEL & LEISURE
    # ──────────────────────────────────────────────
    "travel": {
        "display_name": "Travel Agency",
        "category": "travel-leisure",
        "description": "Trip planning, bookings, packages, group travel, and travel advisories",
        "icon": "plane",
        "placeholder_text": (
            "We're a full-service travel agency specializing in luxury vacations, "
            "honeymoons, group travel, and corporate retreats. We book flights, hotels, "
            "cruises, tours, and travel insurance. Preferred partners with Marriott, "
            "Sandals, Viking, and Disney. 15 years in business."
        ),
        "expert_backstory": (
            "You are a travel industry expert who understands destination knowledge, "
            "booking system workflows, group travel logistics, travel insurance "
            "recommendations, visa/passport requirements, and the consultative "
            "approach to luxury travel planning."
        ),
        "compliance_rules": [
            "Clearly communicate cancellation policies, change fees, and travel insurance options.",
            "Mention that prices are subject to change until booked and paid.",
            "Recommend travel insurance for all international bookings.",
            "Advise checking passport validity and visa requirements well in advance.",
        ],
        "possible_use_cases": [
            {"name": "Trip Planning", "description": "Destination recommendations, itinerary design, budget planning, best times to visit"},
            {"name": "Bookings", "description": "Flights, hotels, cruises, tours, transfers, activity reservations"},
            {"name": "Group Travel", "description": "Weddings, corporate retreats, family reunions, custom group packages"},
            {"name": "Travel Modifications", "description": "Changes, cancellations, rebooking, credit usage, upgrades"},
            {"name": "Travel Information", "description": "Visa requirements, health advisories, packing tips, destination guides", "kb_eligible": True},
            {"name": "General Inquiries", "description": "Services, pricing, payment plans, loyalty programs, gift certificates"},
        ],
        "fixed_patterns": None,
    },

    "event_planning": {
        "display_name": "Event Planning",
        "category": "travel-leisure",
        "description": "Event inquiries, venue booking, vendor coordination, and timeline management",
        "icon": "calendar",
        "placeholder_text": (
            "We're an event planning company specializing in corporate events, weddings, "
            "and galas. We handle venues, catering, entertainment, decor, AV, and "
            "day-of coordination. We've planned 500+ events from intimate dinners (20 guests) "
            "to large conferences (2,000+ attendees)."
        ),
        "expert_backstory": (
            "You are an event planning operations expert who understands venue sourcing, "
            "vendor management, budget allocation, timeline creation, guest management, "
            "and the high-touch communication style required for event clients, especially "
            "during high-stress wedding planning."
        ),
        "compliance_rules": [
            "Clearly communicate deposits, payment schedules, and cancellation terms.",
            "Event details and guest lists are confidential.",
            "Mention that final pricing depends on guest count, venue, and selections.",
        ],
        "possible_use_cases": [
            {"name": "Event Inquiries", "description": "Event types, capabilities, portfolio, pricing models, availability"},
            {"name": "Consultation Booking", "description": "Initial meeting, venue tours, tasting appointments, design sessions"},
            {"name": "Planning Updates", "description": "Timeline status, vendor confirmations, budget tracking, decisions needed"},
            {"name": "Vendor Coordination", "description": "Catering, photography, entertainment, florals, rentals, AV"},
            {"name": "Day-of Support", "description": "Timeline, contact numbers, emergency protocols, final details"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # BEAUTY & PERSONAL CARE
    # ──────────────────────────────────────────────
    "salon": {
        "display_name": "Salon & Barbershop",
        "category": "beauty-personal",
        "description": "Appointments, services, pricing, stylist matching, and product sales",
        "icon": "scissors",
        "placeholder_text": (
            "We're an upscale hair salon with 12 stylists offering cuts, color, "
            "highlights, balayage, keratin treatments, extensions, and bridal styling. "
            "We also sell professional haircare products. Open Tue-Sat, "
            "walk-ins welcome but appointments preferred."
        ),
        "expert_backstory": (
            "You are a salon operations expert who understands appointment booking with "
            "service duration planning, stylist specialization matching, retail product "
            "sales, bridal/event styling coordination, and the personalized experience "
            "expected in premium salon settings."
        ),
        "compliance_rules": [
            "Ask about allergies before booking chemical services (color, relaxers, keratin).",
            "Clearly communicate cancellation/no-show policies and any fees.",
            "Pricing is approximate — final cost depends on hair length, thickness, and condition.",
        ],
        "possible_use_cases": [
            {"name": "Appointment Booking", "description": "Service selection, stylist preference, duration, walk-in availability"},
            {"name": "Services & Pricing", "description": "Service menu, pricing, add-ons, package deals, new client specials", "kb_eligible": True},
            {"name": "Stylist Matching", "description": "Specialties, experience, portfolio, availability, consultation booking"},
            {"name": "Bridal & Events", "description": "Wedding hair, group appointments, trial sessions, on-location services"},
            {"name": "Product Sales", "description": "Haircare products, recommendations, reorder, online shop"},
            {"name": "General Inquiries", "description": "Hours, location, parking, gift cards, loyalty program"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # LOGISTICS & INDUSTRIAL
    # ──────────────────────────────────────────────
    "logistics": {
        "display_name": "Logistics & Shipping",
        "category": "logistics-industrial",
        "description": "Shipment tracking, quotes, scheduling pickups, claims, and account management",
        "icon": "truck",
        "placeholder_text": (
            "We're a regional freight and logistics company handling LTL, FTL, "
            "last-mile delivery, and warehousing. We serve e-commerce businesses, "
            "manufacturers, and retailers across the southeastern US. "
            "Same-day and next-day delivery available in metro areas."
        ),
        "expert_backstory": (
            "You are a logistics operations expert who understands freight classification, "
            "shipping rate structures, tracking systems, claims processes, warehouse "
            "operations, and the communication needs of shippers who need reliable "
            "delivery updates and problem resolution."
        ),
        "compliance_rules": [
            "Shipping quotes are estimates — final rates depend on actual weight, dimensions, and classification.",
            "Claims must be filed within specified timeframes with proper documentation.",
            "Never guarantee delivery times for weather or carrier delays.",
        ],
        "possible_use_cases": [
            {"name": "Shipment Tracking", "description": "Real-time status, delivery updates, delay notifications, POD requests"},
            {"name": "Rate Quotes", "description": "LTL/FTL quotes, dimensional pricing, accessorial charges, volume discounts"},
            {"name": "Pickup Scheduling", "description": "Pickup requests, dock scheduling, recurring pickups, special handling"},
            {"name": "Claims", "description": "Damage claims, lost shipment, filing process, documentation requirements"},
            {"name": "Account Management", "description": "New accounts, credit terms, billing questions, service agreements"},
            {"name": "Warehousing", "description": "Storage, fulfillment, inventory management, receiving, distribution"},
        ],
        "fixed_patterns": None,
    },

    "construction": {
        "display_name": "Construction",
        "category": "logistics-industrial",
        "description": "Project inquiries, estimates, scheduling, permits, and subcontractor coordination",
        "icon": "hard-hat",
        "placeholder_text": (
            "We're a general contractor specializing in residential remodeling "
            "and custom home building. Kitchen and bathroom renovations, additions, "
            "whole-home remodels, and new construction. Licensed in 3 counties. "
            "Average project range $50K-$500K."
        ),
        "expert_backstory": (
            "You are a construction operations expert who understands project scoping, "
            "estimation processes, permitting workflows, subcontractor coordination, "
            "construction timelines, change order management, and the communication "
            "needs of homeowners during stressful renovation projects."
        ),
        "compliance_rules": [
            "Estimates are preliminary until detailed scope and site inspection are complete.",
            "Mention licensing, bonding, and insurance status when relevant.",
            "Clearly communicate that timelines are estimates and subject to change.",
            "Change orders must be documented and approved before work proceeds.",
        ],
        "possible_use_cases": [
            {"name": "Project Inquiries", "description": "Scope, capabilities, portfolio, process, rough budget ranges"},
            {"name": "Estimate Scheduling", "description": "Site visit booking, scope discussion, timeline for proposal"},
            {"name": "Project Updates", "description": "Construction progress, timeline status, decision points, change orders"},
            {"name": "Warranty & Service", "description": "Post-completion warranty, punch list items, service requests"},
            {"name": "General Inquiries", "description": "Services, areas served, licensing, references, financing options"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # GOVERNMENT & NONPROFIT
    # ──────────────────────────────────────────────
    "government": {
        "display_name": "Government Agency",
        "category": "government-nonprofit",
        "description": "Citizen services, permits, licensing, public information, and department routing",
        "icon": "building",
        "placeholder_text": (
            "We're a city government serving 150,000 residents. We handle permits, "
            "licensing, utilities, parks and recreation, code enforcement, public works, "
            "and animal control. City hall open Mon-Fri 8am-5pm. Online portal available "
            "for most services."
        ),
        "expert_backstory": (
            "You are a government operations expert who understands citizen service "
            "workflows, permit and licensing processes, department routing, public "
            "information requests, and the importance of accessible, non-discriminatory "
            "service delivery. You know how to handle frustrated citizens while "
            "maintaining professionalism."
        ),
        "compliance_rules": [
            "ADA compliance — offer alternative formats and accessibility accommodations.",
            "Public records requests have specific legal timelines and processes.",
            "Never share personal information about residents or employees.",
            "Maintain political neutrality in all communications.",
        ],
        "possible_use_cases": [
            {"name": "Citizen Services", "description": "General inquiries, service requests, complaint filing, status checks"},
            {"name": "Permits & Licensing", "description": "Application process, requirements, fees, status, renewals"},
            {"name": "Utilities", "description": "Water/sewer service, billing, outages, new connections, disconnections"},
            {"name": "Parks & Recreation", "description": "Program registration, facility reservations, event info, hours", "kb_eligible": True},
            {"name": "Department Routing", "description": "Connect to the right department, hours, locations, online resources"},
            {"name": "Public Works", "description": "Road issues, trash collection, snow removal, street lights, reporting"},
        ],
        "fixed_patterns": None,
    },

    "nonprofit": {
        "display_name": "Nonprofit Organization",
        "category": "government-nonprofit",
        "description": "Donations, volunteer coordination, program info, events, and impact reporting",
        "icon": "heart-handshake",
        "placeholder_text": (
            "We're a nonprofit food bank serving 50,000 families annually across 3 counties. "
            "We operate 2 warehouses, 15 mobile pantry sites, and a community kitchen. "
            "We rely on 2,000+ volunteers and corporate partnerships. We also run nutrition "
            "education and job training programs."
        ),
        "expert_backstory": (
            "You are a nonprofit operations expert who understands donor relations, "
            "volunteer management, program delivery, grant compliance communication, "
            "event fundraising, and the mission-driven communication style that inspires "
            "engagement while maintaining transparency about impact."
        ),
        "compliance_rules": [
            "Donor information is confidential — never share without authorization.",
            "Clearly state tax-deductibility of donations where applicable.",
            "Be transparent about how funds are used and impact metrics.",
        ],
        "possible_use_cases": [
            {"name": "Donations", "description": "How to give, recurring donations, matching gifts, planned giving, tax receipts"},
            {"name": "Volunteer", "description": "Opportunities, scheduling, requirements, group volunteering, corporate days"},
            {"name": "Program Information", "description": "Services offered, eligibility, locations, hours, enrollment", "kb_eligible": True},
            {"name": "Events", "description": "Fundraising galas, runs/walks, community events, tickets, sponsorships"},
            {"name": "General Inquiries", "description": "Mission, impact, leadership, financials, partnerships, media"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # MEDIA & ENTERTAINMENT
    # ──────────────────────────────────────────────
    "entertainment": {
        "display_name": "Entertainment Venue",
        "category": "media-entertainment",
        "description": "Tickets, events, group bookings, venue info, and membership",
        "icon": "ticket",
        "placeholder_text": (
            "We're a 1,500-seat concert venue and event space hosting live music, "
            "comedy shows, corporate events, and private parties. Full bar and food service. "
            "VIP boxes available. We host 200+ events per year across all genres."
        ),
        "expert_backstory": (
            "You are an entertainment venue operations expert who understands ticket "
            "sales, event scheduling, VIP and group sales, food and beverage operations, "
            "venue rental, and the excitement-driven communication style appropriate "
            "for entertainment businesses."
        ),
        "compliance_rules": [
            "Clearly state ticket policies — refunds, exchanges, age restrictions.",
            "Mention parking, accessibility, and prohibited items for events.",
            "For sold-out events, offer waitlist or alternative dates.",
        ],
        "possible_use_cases": [
            {"name": "Ticket Sales", "description": "Event info, pricing, seating, availability, purchase, group discounts"},
            {"name": "Event Information", "description": "Upcoming events, genres, schedules, performers, age restrictions", "kb_eligible": True},
            {"name": "Group & VIP", "description": "Group bookings, VIP boxes, corporate events, birthday packages"},
            {"name": "Venue Rental", "description": "Private events, pricing, capacity, catering, A/V, booking process"},
            {"name": "General Inquiries", "description": "Location, parking, accessibility, food/drink, policies"},
        ],
        "fixed_patterns": None,
    },

    "photography": {
        "display_name": "Photography & Videography",
        "category": "media-entertainment",
        "description": "Session booking, packages, galleries, prints, and event coverage",
        "icon": "camera",
        "placeholder_text": (
            "We're a photography and videography studio specializing in weddings, "
            "portraits, corporate headshots, and commercial product photography. "
            "We serve the Bay Area, with travel available for destination weddings. "
            "Full editing and album design included in packages."
        ),
        "expert_backstory": (
            "You are a photography business operations expert who understands booking "
            "workflows, package pricing structures, session preparation, gallery delivery "
            "timelines, print fulfillment, and the personal connection required when "
            "working with clients during milestone moments like weddings."
        ),
        "compliance_rules": [
            "Clearly communicate usage rights and licensing for commercial work.",
            "Deposits and cancellation policies must be stated clearly.",
            "Delivery timelines are estimates — mention turnaround time ranges.",
        ],
        "possible_use_cases": [
            {"name": "Session Booking", "description": "Availability, session types, location, duration, preparation tips"},
            {"name": "Packages & Pricing", "description": "Package options, custom quotes, add-ons, payment plans", "kb_eligible": True},
            {"name": "Gallery & Delivery", "description": "Gallery access, download instructions, delivery timeline, selections"},
            {"name": "Prints & Products", "description": "Print ordering, albums, canvases, wall art, gift items"},
            {"name": "Wedding Inquiries", "description": "Wedding packages, engagement sessions, timeline planning, second shooter"},
            {"name": "General Inquiries", "description": "Style, portfolio, availability, travel, gift certificates"},
        ],
        "fixed_patterns": None,
    },

    # ──────────────────────────────────────────────
    # PET SERVICES
    # ──────────────────────────────────────────────
    "pet_services": {
        "display_name": "Pet Care & Grooming",
        "category": "pet-services",
        "description": "Grooming, daycare, boarding, training, and pet supply",
        "icon": "paw-print",
        "placeholder_text": (
            "We offer professional dog grooming, doggy daycare, overnight boarding, "
            "and basic obedience training. We accept dogs and cats. All pets must be "
            "up to date on vaccinations. Open Mon-Sat 7am-7pm. "
            "Webcam access for daycare and boarding."
        ),
        "expert_backstory": (
            "You are a pet services operations expert who understands grooming scheduling "
            "by breed and coat type, daycare capacity management, boarding safety protocols, "
            "vaccination requirements, and the emotional connection pet owners have — "
            "they want reassurance their pets are in good hands."
        ),
        "compliance_rules": [
            "Require proof of vaccinations (rabies, distemper, bordetella) before any service.",
            "Clearly communicate behavioral requirements for daycare and group settings.",
            "Mention any breed restrictions or additional fees for large/difficult breeds.",
        ],
        "possible_use_cases": [
            {"name": "Grooming Appointments", "description": "Scheduling, breed-specific services, pricing, add-ons, special needs"},
            {"name": "Daycare", "description": "Enrollment, rates, hours, temperament assessment, webcam access"},
            {"name": "Boarding", "description": "Availability, pricing, suite options, feeding instructions, medication handling"},
            {"name": "Training", "description": "Classes, private sessions, puppy programs, behavioral issues, pricing"},
            {"name": "General Inquiries", "description": "Hours, location, vaccination requirements, new client registration"},
        ],
        "fixed_patterns": None,
    },

}


def get_industry_list() -> list[dict[str, str]]:
    """Return a lightweight list of industries for the frontend."""
    return [
        {
            "key": key,
            "display_name": info["display_name"],
            "description": info["description"],
            "icon": info["icon"],
            "category": info.get("category", ""),
            "placeholder_text": info["placeholder_text"],
        }
        for key, info in INDUSTRY_REGISTRY.items()
    ]


def get_category_list() -> list[dict[str, str]]:
    """Return the list of industry categories for the frontend."""
    return [
        {"key": key, "label": cat["label"], "icon": cat["icon"]}
        for key, cat in INDUSTRY_CATEGORIES.items()
    ]


def assemble_workflow_definition(
    blueprint: dict,
    prompts: dict[str, str],
) -> dict:
    """
    Convert a CrewAI-generated blueprint + prompts into a valid workflow_definition
    matching the app's ReactFlow schema.

    The blueprint has:
      - nodes: [{id, type, name, exit_conditions, kb_enabled, ...}]
      - edges: [{source, target, condition, label}]

    Returns a full workflow_definition dict ready for DB storage.
    """
    raw_nodes = blueprint.get("nodes", [])
    raw_edges = blueprint.get("edges", [])

    positions = _calculate_layout(raw_nodes, raw_edges)

    # Index node types so we can resolve `sourceHandle` on outgoing edges.
    # ifElse / categorize nodes use React Flow's handle system to indicate
    # which branch an edge leaves from, and the architect's JSON only carries
    # a free-form `condition` string. We translate that here.
    node_type_by_id: dict[str, str] = {n["id"]: n.get("type", "agentNode") for n in raw_nodes}

    # Union of every variable extracted anywhere in the flow, keyed by name so
    # the same concept (e.g. caller_name) isn't duplicated. We replay this onto
    # the End node(s) below so there is ONE place that holds the complete data
    # set after the call — the natural hook point for post-call integrations.
    all_extraction_vars: dict[str, dict[str, Any]] = {}

    nodes = []
    for n in raw_nodes:
        nid = n["id"]
        ntype = n.get("type", "agentNode")
        node_data: dict[str, Any] = {
            "name": n.get("name", "Agent"),
            "prompt": prompts.get(nid, n.get("prompt", "")),
            "is_static": False,
            "allow_interrupt": ntype != "endCall",
        }

        if ntype == "startCall":
            node_data["is_start"] = True
            node_data["add_global_prompt"] = True
        elif ntype == "endCall":
            node_data["is_end"] = True
            node_data["allow_interrupt"] = False
        elif ntype == "globalNode":
            pass
        elif ntype == "ifElse":
            # ifElse is a deterministic LLM-evaluated branch. It doesn't
            # converse with the caller, so no global prompt and no
            # interruptions. The condition text is what the LLM evaluates.
            node_data["condition_text"] = n.get("condition_text", "") or n.get("prompt", "")
            node_data["is_static"] = True
            node_data["allow_interrupt"] = False
            node_data.pop("prompt", None)
        elif ntype == "categorize":
            # categorize takes the conversation context and picks one of the
            # named categories. Each category becomes an output handle that
            # the architect can route to a different downstream node.
            cats = n.get("categories")
            if not isinstance(cats, list) or len(cats) < 2:
                # Defensive fallback so a malformed blueprint never crashes
                # rendering. Two categories is the minimum the UI accepts.
                cats = ["Option A", "Option B"]
            node_data["categories"] = cats
            node_data["is_static"] = True
            node_data["allow_interrupt"] = False
        elif ntype == "transfer":
            # transfer hands off the live audio to a phone number / SIP URI.
            # `is_literal=True` makes the agent speak the message verbatim
            # before transferring, which is what the architect's example
            # uses; we leave `transfer_target` empty if the architect didn't
            # have a real number to provide (the user wires it in the UI).
            node_data["transfer_target"] = n.get("transfer_target", "") or ""
            node_data["is_literal"] = bool(n.get("is_literal", True))
            node_data["allow_interrupt"] = False
            node_data["add_global_prompt"] = True
        else:
            node_data["add_global_prompt"] = True

        exit_conditions = n.get("exit_conditions")
        if exit_conditions:
            for ec in exit_conditions:
                if "id" not in ec:
                    ec["id"] = f"exit-{uuid.uuid4().hex[:8]}"
            node_data["exit_conditions"] = exit_conditions

        # AI-generated data capture → reusable {{variables}} for integrations.
        # Only agent/end nodes extract; we sanitize the architect's output so it
        # always matches the app's ExtractionVariableDTO (name + string/number/
        # boolean type + optional prompt). This is what makes generated agents
        # plug-and-play with calendar/CRM/email/webhook actions out of the box.
        if ntype in ("agentNode", "endCall") and n.get("extraction_enabled"):
            raw_vars = n.get("extraction_variables")
            cleaned_vars: list[dict[str, Any]] = []
            if isinstance(raw_vars, list):
                for v in raw_vars:
                    if not isinstance(v, dict):
                        continue
                    var_name = _sanitize_var_name(v.get("name") or "")
                    if not var_name:
                        continue
                    var_type = (v.get("type") or "string").strip().lower()
                    if var_type not in ("string", "number", "boolean"):
                        var_type = "string"
                    cleaned_vars.append({
                        "name": var_name,
                        "type": var_type,
                        "prompt": (v.get("prompt") or "").strip(),
                        # Default to critical (required) unless the architect
                        # explicitly marks it optional.
                        "required": v.get("required") is not False,
                    })
            if cleaned_vars:
                node_data["extraction_enabled"] = True
                node_data["extraction_variables"] = cleaned_vars
                extraction_prompt = (n.get("extraction_prompt") or "").strip()
                if extraction_prompt:
                    node_data["extraction_prompt"] = extraction_prompt
                # Accumulate for the end-of-call consolidation (first definition
                # of a given name wins so the earliest, most specific prompt is
                # kept).
                for cv in cleaned_vars:
                    all_extraction_vars.setdefault(cv["name"], cv)

        if n.get("kb_enabled"):
            # chunk_limit=8 because we now persist the full deep-crawled site
            # as the KB doc. For multi-chunk docs (large sites) we want
            # retrieval to surface enough chunks per query that the agent
            # rarely misses a specific fact. For single-chunk docs (typical
            # small-business sites ≤50K chars) the limit is irrelevant —
            # the one chunk is always returned in full.
            node_data["knowledge_base"] = {
                "enabled": True,
                "llm_description": (
                    f"Search the knowledge base when the caller asks about "
                    f"{n.get('name', 'this topic').lower()} details — services, "
                    f"prices, hours, policies, FAQs, contact info, or any "
                    f"specific fact about the business."
                ),
                "query_override": "",
                "chunk_limit": 8,
            }

        if n.get("web_search_enabled"):
            node_data["web_search_enabled"] = True

        pos = positions.get(nid, {"x": 400, "y": 100})
        nodes.append({
            "id": nid,
            "type": ntype,
            "position": pos,
            "measured": {"width": 320, "height": 180},
            "data": node_data,
        })

    # Cap the number of REQUIRED extraction variables across the whole workflow.
    # Too many required fields turn the agent into an interrogator and stall the
    # call (it keeps demanding info the caller may not want to give). We keep a
    # minimal essential set (the first few the architect marked required) and
    # demote the rest to optional. Optional variables are STILL captured when
    # mentioned and STILL surface as suggestions in the Call Variables hub, so
    # the user can promote any of them back to required from the UI if they want.
    MAX_REQUIRED_VARS = 3
    _required_names: set[str] = set()
    for _node in nodes:
        _nd = _node.get("data") or {}
        _ev = _nd.get("extraction_variables")
        if not isinstance(_ev, list):
            continue
        for _var in _ev:
            if not isinstance(_var, dict) or not _var.get("required"):
                continue
            _name = _var.get("name")
            # Keep every occurrence of an already-selected required name required.
            if _name in _required_names:
                continue
            if len(_required_names) < MAX_REQUIRED_VARS:
                _required_names.add(_name)
            else:
                _var["required"] = False

    # Create ONE post-call "Call Variables" hub that surfaces every variable the
    # call collected, and wire each End node into it. This replaces the old
    # practice of dumping all variables onto the End node. The hub is a
    # read-only data hub: users attach Action nodes to it for post-call
    # integrations (calendar, CRM, email, webhooks), dropping in {{caller_name}},
    # {{reservation_date}}, etc. without configuring extraction by hand.
    if all_extraction_vars:
        # Only wire End nodes that don't already route somewhere (the End node
        # allows at most one outgoing edge). In practice the architect never
        # wires post-end actions, but this keeps us safe if it ever does.
        sources_with_out = {e["source"] for e in raw_edges}
        end_nodes = [
            n for n in nodes
            if n["type"] == "endCall" and n["id"] not in sources_with_out
        ]
        if end_nodes:
            hub_id = f"node-callvars-{uuid.uuid4().hex[:8]}"
            hub_vars = list(all_extraction_vars.values())
            first_end_pos = end_nodes[0].get("position") or {"x": 400, "y": 100}
            hub_pos = {
                "x": first_end_pos.get("x", 400),
                "y": first_end_pos.get("y", 100) + 430,
            }
            nodes.append({
                "id": hub_id,
                "type": "callVariables",
                "position": hub_pos,
                "measured": {"width": 320, "height": 180},
                "data": {
                    "name": "Call Variables",
                    "description": (
                        "Every variable collected during the call. Attach Action "
                        "nodes here to run post-call integrations."
                    ),
                    "is_static": False,
                    "allow_interrupt": False,
                    # Stored as a snapshot for display; the UI node also
                    # aggregates live across the workflow. The hub is never
                    # dispatched as a conversational node, so this never triggers
                    # extraction at runtime.
                    "extraction_variables": hub_vars,
                },
            })
            for en in end_nodes:
                raw_edges.append({
                    "id": f"edge-{uuid.uuid4().hex[:8]}",
                    "source": en["id"],
                    "target": hub_id,
                    "label": "",
                    "condition": "",
                })

    edges = []
    for e in raw_edges:
        source_id = e["source"]
        source_type = node_type_by_id.get(source_id)
        condition = e.get("condition", "") or ""

        # React Flow uses `sourceHandle` to pick which output handle an edge
        # leaves from on a multi-output node. ifElse exposes "true" / "false"
        # handles; categorize exposes "category-<name>" handles. Everything
        # else uses the single default handle (sourceHandle stays None).
        source_handle: Optional[str] = None
        if source_type == "ifElse":
            cond_lower = condition.lower()
            if cond_lower in ("true", "yes", "y", "1"):
                source_handle = "true"
            elif cond_lower in ("false", "no", "n", "0"):
                source_handle = "false"
        elif source_type == "categorize":
            if condition:
                source_handle = f"category-{condition}"

        edge_payload = {
            "id": e.get("id", f"edge-{uuid.uuid4().hex[:8]}"),
            "source": source_id,
            "target": e["target"],
            "type": "custom",
            "animated": True,
            "data": {
                "condition": condition,
                "label": e.get("label", condition),
            },
        }
        if source_handle is not None:
            edge_payload["sourceHandle"] = source_handle
        edges.append(edge_payload)

    return {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _calculate_layout(
    nodes: list[dict],
    edges: list[dict],
) -> dict[str, dict[str, int]]:
    """
    Layered top-down auto-layout that handles branching workflows cleanly.

    Algorithm:
      1. Assign every node a "rank" (depth from startCall) via BFS over edges.
         globalNode is parked on the left rail (no rank). endCall and
         transfer nodes get pushed to the maximum rank so terminals sit at
         the bottom regardless of where they appear in the BFS order.
      2. Within each rank, spread nodes horizontally with enough padding
         that adjacent nodes never visually touch.
      3. Centre each rank on x = 0 (a wider canvas than the old fixed
         x=400 anchor; React Flow viewports centre on the bounding box).

    Spacing is sized for the 320×180 px node card, with a 160 px horizontal
    gutter and 250 px vertical gap so labels and edges have room to breathe.
    """

    NODE_W = 320
    NODE_H = 180
    H_GAP = 160       # horizontal gap between sibling nodes in a rank
    V_GAP = 250       # vertical gap between ranks
    COL_W = NODE_W + H_GAP
    ROW_H = NODE_H + V_GAP

    node_map = {n["id"]: n for n in nodes}
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for e in edges:
        s, t = e["source"], e["target"]
        outgoing.setdefault(s, []).append(t)
        incoming.setdefault(t, []).append(s)

    global_id: Optional[str] = None
    start_id: Optional[str] = None
    end_ids: list[str] = []
    transfer_ids: list[str] = []

    for n in nodes:
        ntype = n.get("type")
        if ntype == "globalNode":
            global_id = n["id"]
        elif ntype == "startCall":
            start_id = n["id"]
        elif ntype == "endCall":
            end_ids.append(n["id"])
        elif ntype == "transfer":
            transfer_ids.append(n["id"])

    # ── Rank assignment (BFS from startCall) ────────────────────────────
    # Nodes that are unreachable from startCall (orphans) get placed at a
    # synthetic trailing rank so they're still rendered, just at the bottom.
    rank: dict[str, int] = {}
    if start_id:
        rank[start_id] = 0
        queue: list[str] = [start_id]
        while queue:
            current = queue.pop(0)
            for nxt in outgoing.get(current, []):
                if nxt == global_id:
                    continue
                # Each node lands at max(parent rank) + 1; this keeps merge
                # points (multiple parents) at the deepest level so edges
                # always point downward and never cross back up.
                proposed = rank[current] + 1
                if nxt not in rank or proposed > rank[nxt]:
                    rank[nxt] = proposed
                    queue.append(nxt)

    # Push every terminal (endCall, transfer) to the bottom row so they
    # never sit mid-graph next to active agents. We compute the max rank
    # over non-terminal nodes first, then bump terminals beyond it.
    non_terminal_ranks = [
        r for nid, r in rank.items()
        if nid not in end_ids and nid not in transfer_ids
    ]
    floor_rank = max(non_terminal_ranks, default=0) + 1
    for tid in end_ids + transfer_ids:
        # Only bump them if they're reachable — keep relative order if a
        # transfer node has incoming edges from a deeper agent.
        if tid in rank:
            rank[tid] = max(rank[tid], floor_rank)
        else:
            rank[tid] = floor_rank

    # Orphans (no rank assigned) go below everything else, one per slot.
    orphan_rank = max(rank.values(), default=0) + 1
    for n in nodes:
        nid = n["id"]
        if nid == global_id:
            continue
        if nid not in rank:
            rank[nid] = orphan_rank

    # ── Group nodes by rank, preserving a stable left-to-right order ────
    # Within a rank we sort by the average rank of incoming neighbours,
    # then by node name, so siblings stay near their parents and graphs
    # render the same way every time.
    by_rank: dict[int, list[str]] = {}
    for nid, r in rank.items():
        by_rank.setdefault(r, []).append(nid)

    def _stable_key(nid: str) -> tuple:
        parents = incoming.get(nid, [])
        parent_idx = 0.0
        if parents:
            # Use the parent's current order index if known (best-effort).
            parent_idx = sum(
                by_rank.get(rank.get(p, 0), []).index(p)
                if p in by_rank.get(rank.get(p, 0), []) else 0
                for p in parents
            ) / len(parents)
        return (parent_idx, node_map.get(nid, {}).get("name", "") or nid)

    for r in sorted(by_rank.keys()):
        by_rank[r].sort(key=_stable_key)

    # ── Assign x/y coordinates ──────────────────────────────────────────
    positions: dict[str, dict[str, int]] = {}

    for r, ids in by_rank.items():
        count = len(ids)
        # Centre the rank around x=0. With COL_W stride, the leftmost node
        # sits at -(count-1)*COL_W/2.
        offset = -(count - 1) * COL_W // 2
        for i, nid in enumerate(ids):
            positions[nid] = {
                "x": offset + i * COL_W,
                "y": r * ROW_H,
            }

    # Global prompt: parked on the left rail, vertically centred on the graph.
    if global_id:
        rank_count = len(by_rank)
        mid_y = (rank_count - 1) * ROW_H // 2 if rank_count > 1 else 0
        # Far enough left that even the widest rank doesn't run into it.
        widest_rank = max((len(v) for v in by_rank.values()), default=1)
        left_edge = -(widest_rank - 1) * COL_W // 2
        positions[global_id] = {"x": left_edge - COL_W - 80, "y": mid_y}

    return positions
