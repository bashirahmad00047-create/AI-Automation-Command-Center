"""Modular Business Templates & Catalog for OpsFlow Multi-Tenant Business OS.

Provides reusable, configurable templates for:
- Category A: Online Businesses (E-Commerce, Digital Agency, SaaS, Bookings, Lead Gen)
- Category B: Offline Businesses (Retail/Wholesale, Clinics, Restaurants, Warehouses, Physical Services)

Zero hardcoded logic: Each template defines configurable default services,
operating hours, business policies, communication channels, role structures,
and grounded AI Call Center instructions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


BUSINESS_TEMPLATES: List[Dict[str, Any]] = [
    # =========================================================================
    # CATEGORY A: ONLINE BUSINESSES
    # =========================================================================
    {
        "id": "tpl-online-ecommerce",
        "category": "online",
        "industry": "ecommerce",
        "name": "E-Commerce & Online Store",
        "description": "Direct-to-consumer and B2B online storefronts requiring order tracking, cart recovery, and customer support.",
        "icon": "🛒",
        "badge_color": "#0ea5e9",
        "default_services": [
            {"name": "Standard Delivery", "price": 250, "currency": "PKR", "turnaround": "2-3 business days"},
            {"name": "Express Same-Day Dispatch", "price": 500, "currency": "PKR", "turnaround": "Within 24 hours"},
            {"name": "Cash on Delivery (COD)", "price": 0, "currency": "PKR", "turnaround": "Upon arrival"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "09:00", "close": "21:00", "closed": False},
                "tue": {"open": "09:00", "close": "21:00", "closed": False},
                "wed": {"open": "09:00", "close": "21:00", "closed": False},
                "thu": {"open": "09:00", "close": "21:00", "closed": False},
                "fri": {"open": "09:00", "close": "21:00", "closed": False},
                "sat": {"open": "10:00", "close": "20:00", "closed": False},
                "sun": {"open": "12:00", "close": "18:00", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "return_policy": "7-day no-questions-asked return policy on unopened items in original packaging.",
            "refund_policy": "Full refunds processed to original payment method or JazzCash within 3-5 business days upon item receipt.",
            "cancellation_policy": "Orders may be cancelled free of charge prior to warehouse dispatch notification.",
            "shipping_policy": "Orders placed before 4:00 PM are dispatched same-day. Free shipping on orders over PKR 3,000.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Store Manager", "level": "admin", "department": "Operations"},
            {"title": "Fulfillment Specialist", "level": "operator", "department": "Warehouse"},
            {"title": "Customer Support Rep", "level": "operator", "department": "Support"},
        ],
        "ai_instructions": (
            "You are the intelligent customer service and shopping assistant for this store. "
            "Help customers find products, verify stock, explain delivery times, and assist with order tracking. "
            "Always maintain a welcoming, helpful, and professional tone. "
            "If a customer requests a return or refund, collect their order number and reason, but explain that "
            "refund authorizations require supervisor review."
        ),
        "ai_guardrails": (
            "Never promise discounts exceeding 10% without supervisor approval. "
            "Never confirm a financial refund directly; always flag for human operator review."
        ),
        "recommended_workflows": [
            "template-ai-lead-qualification",
            "template-customer-support-router",
            "template-ecommerce-order-sync",
        ],
    },
    {
        "id": "tpl-online-agency",
        "category": "online",
        "industry": "agency",
        "name": "Digital Agency & Marketing",
        "description": "Creative, marketing, design, and development service providers handling client inquiries, project milestones, and SLAs.",
        "icon": "🚀",
        "badge_color": "#8b5cf6",
        "default_services": [
            {"name": "Performance Marketing Audit", "price": 15000, "currency": "PKR", "turnaround": "3 business days"},
            {"name": "Monthly SEO & Content Retainer", "price": 45000, "currency": "PKR", "turnaround": "Monthly"},
            {"name": "Full-Stack Web Application Development", "price": 150000, "currency": "PKR", "turnaround": "2-4 weeks"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "09:00", "close": "18:00", "closed": False},
                "tue": {"open": "09:00", "close": "18:00", "closed": False},
                "wed": {"open": "09:00", "close": "18:00", "closed": False},
                "thu": {"open": "09:00", "close": "18:00", "closed": False},
                "fri": {"open": "09:00", "close": "18:00", "closed": False},
                "sat": {"open": "00:00", "close": "00:00", "closed": True},
                "sun": {"open": "00:00", "close": "00:00", "closed": True},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "payment_terms": "50% upfront milestone deposit, 50% upon final client sign-off and deployment.",
            "revision_policy": "Up to 3 revision rounds included per deliverable phase. Additional scope estimated separately.",
            "sla_policy": "Standard support requests answered within 4 hours during business days.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Account Director", "level": "admin", "department": "Management"},
            {"title": "Project Manager", "level": "operator", "department": "Delivery"},
            {"title": "Technical Lead", "level": "operator", "department": "Engineering"},
        ],
        "ai_instructions": (
            "You are the senior discovery coordinator for our digital agency. "
            "Engage prospective clients warmly, understand their business goals, budget scope, and timeline. "
            "Offer to schedule a discovery call with our account director. "
            "For active clients, confirm receipt of inquiries and route to the assigned project manager."
        ),
        "ai_guardrails": (
            "Do not quote definitive project prices without scoping; provide estimate ranges only."
        ),
        "recommended_workflows": [
            "template-ai-lead-qualification",
            "template-sales-followup",
        ],
    },
    {
        "id": "tpl-online-saas",
        "category": "online",
        "industry": "saas",
        "name": "SaaS & Software Company",
        "description": "Cloud applications, API platforms, and subscription software businesses.",
        "icon": "⚡",
        "badge_color": "#06b6d4",
        "default_services": [
            {"name": "Starter Cloud Workspace", "price": 2500, "currency": "PKR", "turnaround": "Instant Access"},
            {"name": "Professional Team Tier", "price": 7500, "currency": "PKR", "turnaround": "Instant Access"},
            {"name": "Enterprise Dedicated Cluster", "price": 25000, "currency": "PKR", "turnaround": "1-2 business days"},
        ],
        "default_operating_hours": {
            "timezone": "UTC",
            "schedule": {
                "mon": {"open": "00:00", "close": "23:59", "closed": False},
                "tue": {"open": "00:00", "close": "23:59", "closed": False},
                "wed": {"open": "00:00", "close": "23:59", "closed": False},
                "thu": {"open": "00:00", "close": "23:59", "closed": False},
                "fri": {"open": "00:00", "close": "23:59", "closed": False},
                "sat": {"open": "00:00", "close": "23:59", "closed": False},
                "sun": {"open": "00:00", "close": "23:59", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "sla_policy": "99.9% platform availability guarantee with public status page reporting.",
            "billing_policy": "Monthly or annual recurring subscription with automatic invoice dispatch.",
            "cancellation_policy": "Cancel at any time with zero penalty. Access remains active through period end.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "DevOps Engineer", "level": "admin", "department": "Infrastructure"},
            {"title": "Support Engineer", "level": "operator", "department": "Customer Success"},
            {"title": "Billing Specialist", "level": "operator", "department": "Finance"},
        ],
        "ai_instructions": (
            "You are the technical support and product onboarding assistant for our SaaS platform. "
            "Help developers with API usage, explain subscription tiers, resolve billing inquiries, and triage error reports. "
            "If an incident or outage is reported, collect error traces and escalate immediately to the on-call SRE."
        ),
        "ai_guardrails": "Never modify user subscriptions directly without human confirmation.",
        "recommended_workflows": [
            "template-api-failure-alert",
            "template-security-threat-quarantine",
        ],
    },
    {
        "id": "tpl-online-booking",
        "category": "online",
        "industry": "booking",
        "name": "Online Bookings & Consultations",
        "description": "Appointment scheduling, virtual coaching, legal/consulting sessions, and customer reservations.",
        "icon": "📅",
        "badge_color": "#10b981",
        "default_services": [
            {"name": "Initial 30-Min Strategy Consultation", "price": 3000, "currency": "PKR", "turnaround": "30 mins"},
            {"name": "Comprehensive 60-Min Deep Dive", "price": 6000, "currency": "PKR", "turnaround": "60 mins"},
            {"name": "Monthly Consultation Package (4 Sessions)", "price": 20000, "currency": "PKR", "turnaround": "4 weeks"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "10:00", "close": "19:00", "closed": False},
                "tue": {"open": "10:00", "close": "19:00", "closed": False},
                "wed": {"open": "10:00", "close": "19:00", "closed": False},
                "thu": {"open": "10:00", "close": "19:00", "closed": False},
                "fri": {"open": "10:00", "close": "19:00", "closed": False},
                "sat": {"open": "10:00", "close": "15:00", "closed": False},
                "sun": {"open": "00:00", "close": "00:00", "closed": True},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "rescheduling_policy": "Free rescheduling up to 4 hours prior to appointment time.",
            "cancellation_policy": "Full refund if cancelled 24 hours in advance; 50% credit thereafter.",
            "no_show_policy": "Missed appointments without notice require booking fee forfeit.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Principal Consultant", "level": "admin", "department": "Consulting"},
            {"title": "Appointment Coordinator", "level": "operator", "department": "Scheduling"},
        ],
        "ai_instructions": (
            "You are our appointment and scheduling concierge. "
            "Help clients pick available appointment slots, explain session requirements, and send calendar confirmations. "
            "Always confirm the client's timezone and preferred contact channel."
        ),
        "ai_guardrails": "Never double-book an already confirmed calendar slot.",
        "recommended_workflows": [
            "template-website-contact-form",
            "template-sales-followup",
        ],
    },
    {
        "id": "tpl-online-leadgen",
        "category": "online",
        "industry": "leadgen",
        "name": "Online Lead Gen & Inbound Sales",
        "description": "High-velocity sales pipelines, real estate lead capture, loan inquiries, and B2B inbound qualification.",
        "icon": "🎯",
        "badge_color": "#f59e0b",
        "default_services": [
            {"name": "Standard Inbound Consultation", "price": 0, "currency": "PKR", "turnaround": "Instant"},
            {"name": "VIP Priority Qualification", "price": 0, "currency": "PKR", "turnaround": "< 5 minutes"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "08:00", "close": "22:00", "closed": False},
                "tue": {"open": "08:00", "close": "22:00", "closed": False},
                "wed": {"open": "08:00", "close": "22:00", "closed": False},
                "thu": {"open": "08:00", "close": "22:00", "closed": False},
                "fri": {"open": "08:00", "close": "22:00", "closed": False},
                "sat": {"open": "09:00", "close": "20:00", "closed": False},
                "sun": {"open": "10:00", "close": "18:00", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "privacy_policy": "Lead contact details are encrypted and never shared with third parties without consent.",
            "response_sla": "High-urgency leads contacted within 5 minutes of form completion.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Sales VP", "level": "admin", "department": "Sales"},
            {"title": "Inbound SDR", "level": "operator", "department": "Sales"},
        ],
        "ai_instructions": (
            "You are a top-tier consultative sales qualification agent. "
            "Engage prospects who fill out forms or message on WhatsApp immediately. "
            "Ask qualifying questions regarding their need, timeline, and budget. "
            "Score lead readiness and immediately notify the sales team when a hot lead is detected."
        ),
        "ai_guardrails": "Do not sign or finalize contracts on behalf of the company.",
        "recommended_workflows": [
            "template-ai-lead-qualification",
            "template-sales-followup",
        ],
    },

    # =========================================================================
    # CATEGORY B: OFFLINE BUSINESSES
    # =========================================================================
    {
        "id": "tpl-offline-retail",
        "category": "offline",
        "industry": "retail",
        "name": "Retail Shop & Wholesale Depot",
        "description": "Physical stores, clothing shops, electronics retailers, wholesale merchants, and grocery distributors.",
        "icon": "🏬",
        "badge_color": "#3b82f6",
        "default_services": [
            {"name": "In-Store Pickup (Click & Collect)", "price": 0, "currency": "PKR", "turnaround": "Ready in 1 hour"},
            {"name": "Local City Van Delivery", "price": 300, "currency": "PKR", "turnaround": "Same day if ordered by 1 PM"},
            {"name": "Wholesale Bulk Tier 1 (100+ units)", "price": 0, "currency": "PKR", "turnaround": "1-2 days"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "10:00", "close": "22:00", "closed": False},
                "tue": {"open": "10:00", "close": "22:00", "closed": False},
                "wed": {"open": "10:00", "close": "22:00", "closed": False},
                "thu": {"open": "10:00", "close": "22:00", "closed": False},
                "fri": {"open": "14:00", "close": "22:00", "closed": False},
                "sat": {"open": "10:00", "close": "23:00", "closed": False},
                "sun": {"open": "12:00", "close": "21:00", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "exchange_policy": "In-store exchange within 7 days with original printed sales receipt.",
            "wholesale_policy": "Minimum order quantity for wholesale pricing is 50 pieces per SKU.",
            "damage_policy": "Claims for damaged goods must be logged upon delivery sign-off.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Shop Owner / Branch Manager", "level": "admin", "department": "Management"},
            {"title": "Cashier & Counter Staff", "level": "operator", "department": "Sales Counter"},
            {"title": "Stock Clerk", "level": "operator", "department": "Inventory"},
        ],
        "ai_instructions": (
            "You are the store catalog and customer assistant. "
            "Help customers check item availability, store location, opening hours, and current promotions. "
            "For wholesale buyers, collect their product requirements and business details for a custom quote."
        ),
        "ai_guardrails": "Never modify prices or issue store credit without cashier supervisor confirmation.",
        "recommended_workflows": [
            "template-customer-support-router",
            "template-website-contact-form",
        ],
    },
    {
        "id": "tpl-offline-clinic",
        "category": "offline",
        "industry": "clinic",
        "name": "Clinic, Hospital & Medical Practice",
        "description": "Healthcare centers, dental clinics, specialty doctors, diagnostic labs, and medical billing practices.",
        "icon": "🏥",
        "badge_color": "#ef4444",
        "default_services": [
            {"name": "General Physician Consultation", "price": 1500, "currency": "PKR", "turnaround": "15-20 mins"},
            {"name": "Specialist Consultant Visit", "price": 3000, "currency": "PKR", "turnaround": "30 mins"},
            {"name": "Diagnostic Blood Panel & Reports", "price": 4500, "currency": "PKR", "turnaround": "Same evening"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "09:00", "close": "21:00", "closed": False},
                "tue": {"open": "09:00", "close": "21:00", "closed": False},
                "wed": {"open": "09:00", "close": "21:00", "closed": False},
                "thu": {"open": "09:00", "close": "21:00", "closed": False},
                "fri": {"open": "09:00", "close": "21:00", "closed": False},
                "sat": {"open": "10:00", "close": "18:00", "closed": False},
                "sun": {"open": "11:00", "close": "16:00", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "emergency_disclaimer": "OpsFlow AI is not an emergency medical service. In life-threatening emergencies, call 1122 or visit the nearest ER immediately.",
            "appointment_policy": "Arrive 15 minutes before scheduled slot for vitals and registration.",
            "confidentiality_policy": "Strict patient data privacy maintained in accordance with healthcare compliance guidelines.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Medical Director / Chief Doctor", "level": "admin", "department": "Clinical"},
            {"title": "Head Nurse / Triage Specialist", "level": "operator", "department": "Nursing"},
            {"title": "Receptionist / Billing Desk", "level": "operator", "department": "Front Desk"},
        ],
        "ai_instructions": (
            "You are the medical appointment coordinator for our healthcare clinic. "
            "Assist patients with scheduling doctor visits, explaining clinic hours, and providing registration instructions. "
            "Always include the medical disclaimer that this assistant cannot provide medical diagnoses or prescriptions. "
            "For urgent pain or emergency symptoms, instruct the patient to proceed to the emergency department immediately."
        ),
        "ai_guardrails": (
            "Strictly NEVER diagnose illnesses, prescribe medications, or advise stopping prescribed drugs. "
            "Always advise consulting a qualified physician."
        ),
        "recommended_workflows": [
            "template-customer-support-router",
            "template-website-contact-form",
        ],
    },
    {
        "id": "tpl-offline-restaurant",
        "category": "offline",
        "industry": "restaurant",
        "name": "Restaurant, Cafe & Catering",
        "description": "Dining establishments, cafes, bakeries, cloud kitchens, and event caterers.",
        "icon": "🍽️",
        "badge_color": "#f97316",
        "default_services": [
            {"name": "Table Reservation (Up to 6 guests)", "price": 0, "currency": "PKR", "turnaround": "Instant booking"},
            {"name": "Private Dining Room Booking", "price": 5000, "currency": "PKR", "turnaround": "2 hours advance"},
            {"name": "Event Catering Package (Per Head)", "price": 1800, "currency": "PKR", "turnaround": "48 hours advance"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "12:00", "close": "01:00", "closed": False},
                "tue": {"open": "12:00", "close": "01:00", "closed": False},
                "wed": {"open": "12:00", "close": "01:00", "closed": False},
                "thu": {"open": "12:00", "close": "01:00", "closed": False},
                "fri": {"open": "13:00", "close": "02:00", "closed": False},
                "sat": {"open": "12:00", "close": "02:00", "closed": False},
                "sun": {"open": "12:00", "close": "01:00", "closed": False},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "reservation_grace_period": "Reserved tables held for up to 15 minutes past booking time.",
            "cancellation_policy": "Reservations may be cancelled anytime with courtesy WhatsApp notice.",
            "dietary_policy": "Please inform our staff of any food allergies or halal/vegetarian dietary preferences.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Restaurant Manager", "level": "admin", "department": "Floor"},
            {"title": "Head Chef / Kitchen Lead", "level": "operator", "department": "Kitchen"},
            {"title": "Host / Reservation Concierge", "level": "operator", "department": "Front Desk"},
        ],
        "ai_instructions": (
            "You are the front-of-house concierge and reservation host for our restaurant. "
            "Help guests reserve tables, browse our menu highlights, learn about daily specials, and get directions. "
            "Maintain an enthusiastic, warm hospitality tone. "
            "Always ask about party size, requested time, and any special dietary requirements."
        ),
        "ai_guardrails": "Never confirm table reservations for parties larger than 12 without manager approval.",
        "recommended_workflows": [
            "template-customer-support-router",
            "template-website-contact-form",
        ],
    },
    {
        "id": "tpl-offline-warehouse",
        "category": "offline",
        "industry": "warehouse",
        "name": "Warehouse, Distributor & Logistics",
        "description": "Supply chain depots, freight dispatchers, 3PL providers, and inventory warehouses.",
        "icon": "📦",
        "badge_color": "#6366f1",
        "default_services": [
            {"name": "Standard Pallet Inbound Receiving", "price": 1200, "currency": "PKR", "turnaround": "Per pallet / month"},
            {"name": "Pick, Pack & Dispatch Handling", "price": 150, "currency": "PKR", "turnaround": "Per parcel"},
            {"name": "Inter-City Truckload Dispatch", "price": 45000, "currency": "PKR", "turnaround": "Scheduled daily"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "07:00", "close": "20:00", "closed": False},
                "tue": {"open": "07:00", "close": "20:00", "closed": False},
                "wed": {"open": "07:00", "close": "20:00", "closed": False},
                "thu": {"open": "07:00", "close": "20:00", "closed": False},
                "fri": {"open": "07:00", "close": "20:00", "closed": False},
                "sat": {"open": "08:00", "close": "18:00", "closed": False},
                "sun": {"open": "00:00", "close": "00:00", "closed": True},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "receiving_policy": "Truck deliveries require 24 hours advance ASN (Advanced Shipping Notice).",
            "inspection_policy": "Inbound damaged goods photographed and reported to client within 2 hours.",
            "liability_policy": "Standard carrier liability coverage included up to declared manifest valuation.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Logistics Operations Director", "level": "admin", "department": "Operations"},
            {"title": "Warehouse Floor Supervisor", "level": "operator", "department": "Floor"},
            {"title": "Fleet Dispatcher", "level": "operator", "department": "Dispatch"},
        ],
        "ai_instructions": (
            "You are the operations dispatcher for our logistics warehouse. "
            "Assist drivers, suppliers, and retail clients with shipment tracking, dock receiving times, "
            "and delivery statuses. Maintain concise, direct, and factual communication."
        ),
        "ai_guardrails": "Never authorize release of cargo without formal verified gate pass credentials.",
        "recommended_workflows": [
            "template-customer-support-router",
            "template-security-threat-quarantine",
        ],
    },
    {
        "id": "tpl-offline-services",
        "category": "offline",
        "industry": "services",
        "name": "Physical Services & Repairs",
        "description": "Auto repair workshops, home HVAC/electrical services, salons, cleaning companies, and equipment maintenance.",
        "icon": "🔧",
        "badge_color": "#14b8a6",
        "default_services": [
            {"name": "Diagnostic Inspection & Estimate", "price": 1000, "currency": "PKR", "turnaround": "30 mins"},
            {"name": "Standard Service / Routine Tune-Up", "price": 4500, "currency": "PKR", "turnaround": "2 hours"},
            {"name": "Emergency On-Site Callout", "price": 2500, "currency": "PKR", "turnaround": "Within 60 mins"},
        ],
        "default_operating_hours": {
            "timezone": "Asia/Karachi",
            "schedule": {
                "mon": {"open": "08:30", "close": "19:00", "closed": False},
                "tue": {"open": "08:30", "close": "19:00", "closed": False},
                "wed": {"open": "08:30", "close": "19:00", "closed": False},
                "thu": {"open": "08:30", "close": "19:00", "closed": False},
                "fri": {"open": "08:30", "close": "19:00", "closed": False},
                "sat": {"open": "09:00", "close": "17:00", "closed": False},
                "sun": {"open": "00:00", "close": "00:00", "closed": True},
            },
            "support_24_7_ai": True,
        },
        "default_policies": {
            "warranty_policy": "30-day labor guarantee on all completed repair jobs and genuine replacement parts.",
            "estimate_policy": "Written estimates provided before any billable repair work begins.",
            "cancellation_policy": "Please cancel or reschedule service calls at least 2 hours in advance.",
        },
        "default_channels": {
            "whatsapp": True,
            "web_chat": True,
            "phone_call_center": False,
            "email_notifications": True,
        },
        "default_roles": [
            {"title": "Workshop General Manager", "level": "admin", "department": "Management"},
            {"title": "Lead Service Technician", "level": "operator", "department": "Technicians"},
            {"title": "Service Desk Advisor", "level": "operator", "department": "Customer Service"},
        ],
        "ai_instructions": (
            "You are the service advisor and booking coordinator for our repair and maintenance center. "
            "Help customers describe their issue, schedule diagnostic appointments, and check job status. "
            "Give realistic time estimates and explain our warranty policies clearly."
        ),
        "ai_guardrails": "Never guarantee fixed repair completion times without on-site diagnostic inspection.",
        "recommended_workflows": [
            "template-customer-support-router",
            "template-website-contact-form",
        ],
    },
]


def get_all_templates() -> List[Dict[str, Any]]:
    """Returns the full catalog of online and offline business templates."""
    return BUSINESS_TEMPLATES


def get_templates_by_category(category: str) -> List[Dict[str, Any]]:
    """Filter templates by 'online' or 'offline'."""
    cat = (category or "").strip().lower()
    return [t for t in BUSINESS_TEMPLATES if t["category"] == cat]


def get_template_by_id(template_id: str) -> Optional[Dict[str, Any]]:
    """Look up a template by its unique ID or industry slug."""
    clean_id = (template_id or "").strip().lower()
    for t in BUSINESS_TEMPLATES:
        if t["id"] == clean_id or t["industry"] == clean_id:
            return t
    return None
