# PRD: NovaCell AI Support Assistant (v1)

| | |
|---|---|
| **Status** | Draft for review |
| **Date** | 15 Nov 2026 |
| **Product area** | Customer Care / Digital Self-Serve |
| **Stakeholders** | Customer Care Ops, Digital (app + web), Knowledge Management, Legal/Privacy, Security & Fraud, Data/ML Engineering |

---

## 1. Problem & Objective

### Problem
NovaCell (~4M subscribers) spends heavily on customer support and scores low on satisfaction. Most contacts are **Tier-1 questions whose answers already exist** in NovaCell's own content, but that content lives in three disconnected places:

| Source | What it holds | Today's audience |
|---|---|---|
| Public FAQ | Short, customer-ready Q&A (data, billing, SIM, roaming, voice, device, account) | Customers |
| Resolved-ticket database | Real symptom → root cause → resolution pairs | Agents only |
| PDF technical guides | Deep troubleshooting steps, plan mechanics, billing logic, roaming zones | Agents only ("Internal Use Only") |

No single place lets a customer ask a question in plain language and get one consistent, trustworthy answer drawn from all three. As a result:
- **Customers** wait on hold for answers that already exist.
- **Agents** burn out repeating the same answers and can't focus on complex cases.
- **Answers vary** depending on which source or agent a customer reaches.

### Objective
Launch an AI chat assistant that answers Tier-1 questions in plain language, **grounded only in NovaCell's verified knowledge**, with a source for every answer. It must say clearly when it doesn't know, and hand off to a human smoothly when it should.

### Goals (v1)
1. **Deflect** a large share of Tier-1 contacts from live channels (611 calls, live chat).
2. **Accuracy and trust:** no invented prices, policies or facts.
3. **Consistency:** the same question gets the same answer, whichever channel it comes through.
4. **Better handoffs:** when the bot escalates, the agent receives the full conversation, so the customer doesn't have to repeat themselves.

### Non-goals (v1)
- Answering questions about a specific account ("what's my balance", "why is *my* bill $240")
- Taking actions on an account (plan changes, refunds, SIM swaps)
- Replacing human agents for Tier-2/3 issues

---

## 2. Target Users & Key Use Cases

### Personas

| Persona | Description | Need |
|---|---|---|
| **Everyday subscriber** (primary) | Prepaid or postpaid, using the MyTelecom app or web, wants a quick fix | A fast, plain-language answer without calling 611 |
| **Traveler** | Going abroad soon, worried about bill shock | How to set up roaming, which bundles exist, what the rates are |
| **New / switching customer** | Activating a SIM or eSIM, or porting a number in | Step-by-step activation help and realistic timelines |
| **Support agent** (secondary) | Receives escalated chats | Full context: the transcript, what the bot already suggested, the detected issue category |
| **Knowledge / support ops** (internal) | Owns the content | Can update FAQ, tickets and guides without an engineering release, and can see where the bot fails |

### Key use cases (mapped to the top contact themes)

| # | Theme | Example question | What the bot can do in v1 | Main source |
|---|---|---|---|---|
| UC1 | Slow or dropped data | "My 4G is super slow in the city centre" | Explain likely causes (congestion, weak signal, used-up high-speed data → 512 kbps) and walk through troubleshooting: airplane mode, APN, reseating the SIM, outage check | FAQ #2, Guide §2–3, TK-001/008 |
| UC2 | Unexpected charges | "Why is my bill higher than usual?" | List common causes (roaming, premium SMS/carrier billing, add-on packs, mid-cycle plan change) and show where to find the itemised bill. **Cannot see the customer's bill**: explain this and hand off | FAQ #16/18, Guide §7, TK-004/006/016 |
| UC3 | SIM / eSIM activation | "My eSIM QR code won't scan" | Expected timelines, troubleshooting steps, and when a new code is needed (agent action → escalate) | FAQ #12/20, Guide §5, TK-005/009 |
| UC4 | Roaming before travel | "I'm going to Japan next week, what do I need to do?" | Turn roaming on, explain zones (Japan = Zone B), recommend buying a bundle *before* use, check device network-selection settings | FAQ #9/10, Guide §4, TK-004/012 |
| UC5 | Voice-call issues | "Calls keep dropping / go straight to voicemail" | Troubleshoot drops, explain how to enable VoLTE and Wi-Fi calling, flag possible call barring (agent action → escalate) | FAQ #6/7/22, Guide §6, TK-007/011/017 |
| UC6 | Account & app | "I can't log in to the app" | Password reset steps, how to contact support. Possible account takeover → **escalate immediately**, no troubleshooting | FAQ #25, TK-013/020 |
| UC7 | Personal account question | "What's my data balance?" | Explain it can't see accounts, then give self-serve paths: *123#, MyTelecom > My Usage | FAQ #1 |
| UC8 | Out of scope / unknown | "Can I get a refund for last month?" | Say it can't do this and offer handoff to a human | — |

---

## 3. Scope

### In scope (v1)
- **Channels:** chat widget in the MyTelecom app and on the NovaCell support website. English only.
- **Topics:** the six Tier-1 themes above, plus general plan, device and support-contact questions covered by the sources.
- **Knowledge:** the FAQ, resolved tickets and PDF guides, combined into one searchable index with source citations.
- **Answers:** plain language, step-by-step where useful, with a short link to the source on every answer.
- **"I don't know" behavior:** an explicit refusal when the sources don't support an answer.
- **Personal-data boundary:** detect account-specific questions and point to self-serve tools or a human (see FR-5).
- **Escalation:** handoff to existing live chat, or a callback / ticket outside live-chat hours, with the transcript attached.
- **Content admin:** support ops can upload, edit, retire and re-index content without an engineering release.
- **Feedback & analytics:** thumbs up/down, a resolution check ("Did this solve it?"), and an ops dashboard.
- **Session memory:** follow-up questions within one conversation keep their context.

### Explicitly out of scope (v1)
- Any live billing, CRM, network or OSS/BSS access: no balances, bills, plan details or outage lookups by location
- Transactions: plan changes, add-on purchases, refunds, credits, SIM swaps, porting, unlocking
- Login or identity verification inside the chat
- Voice/IVR channel, SMS, WhatsApp and social channels
- Languages other than English
- Proactive outreach and notifications
- An agent-assist copilot (planned for v2)

---

## 4. Functional Requirements

Priority: **P0** = required for launch, **P1** = strongly desired, **P2** = nice to have.

### FR-1 Knowledge ingestion & management
| ID | Requirement | Priority |
|---|---|---|
| 1.1 | Ingest all three source types: FAQ (CSV or CMS), resolved tickets (database), PDF guides. Split each into chunks with metadata: source type, document/record ID, section/page, category, effective date, owner, audience (customer vs. internal) | P0 |
| 1.2 | Admin console where support ops can add, edit, retire and re-index content **without an engineering release**. Changes go live within **15 minutes** | P0 |
| 1.3 | **Content approval flow:** new or changed content goes live only after a named approver signs off. Keep a version history and allow rollback | P0 |
| 1.4 | **Ticket filtering:** only tickets with `status = resolved` are indexed. Escalated, security or fraud tickets (e.g. TK-020) are excluded by default | P0 |
| 1.5 | **PII scrubbing:** remove names, phone numbers, email addresses, IMSI/IMEI, addresses and card fragments from ticket text before indexing | P0 |
| 1.6 | **Audience tagging:** content marked "internal only" (e.g. agent procedures in the technical guide such as "agents can push the VoLTE profile remotely", fraud-handling rules, identity-verification rules) is either excluded or rewritten into customer-safe wording before it can be used in answers | P0 |
| 1.7 | **Conflict detection:** flag likely contradictions between sources for ops to review (see §7 for examples found in the current data) | P1 |
| 1.8 | **Source priority** when sources disagree: approved FAQ > current guide > resolved tickets. Ticket-specific details such as goodwill credit amounts are never shown as policy | P0 |
| 1.9 | **Freshness:** each item has an effective date and an optional expiry date. Expired content is not used, and ops are warned before content expires | P1 |

### FR-2 Question understanding & retrieval
| ID | Requirement | Priority |
|---|---|---|
| 2.1 | Hybrid retrieval (keyword + semantic) across all three sources, with re-ranking | P0 |
| 2.2 | Classify each question into a theme (data, billing, SIM, roaming, voice, account, device, other) and an intent type: general, account-specific, transactional, complaint, or safety/fraud | P0 |
| 2.3 | Rewrite follow-up questions using conversation context (e.g. "what about Japan?" after a roaming question) | P0 |
| 2.4 | Ask **one** clarifying question when the question is too vague to answer well (e.g. "Is this on Wi-Fi or mobile data?") | P1 |

### FR-3 Grounded answer generation
| ID | Requirement | Priority |
|---|---|---|
| 3.1 | Answers may only use retrieved NovaCell content. **Every factual claim must be backed by a cited source**; claims that can't be backed are removed | P0 |
| 3.2 | **Prices, fees, timelines, speeds and policy rules** (e.g. "$15/day EU bundle", "512 kbps", "$5 SIM replacement") must appear word-for-word in a source. A post-generation check blocks any number that doesn't | P0 |
| 3.3 | Each answer shows clickable citations (e.g. "FAQ: International roaming" or "Guide §4, p.5") | P0 |
| 3.4 | Tone: plain language, about an 8th-grade reading level, short. Numbered steps for troubleshooting. No technical jargon unless explained | P0 |
| 3.5 | **Translate agent actions into customer steps:** when a ticket's resolution needs an agent action (re-provisioning a SIM, lifting call barring, issuing a new eSIM code), the bot says "a support specialist can do this for you" and offers handoff. It never tells the customer to do something they can't do | P0 |
| 3.6 | The bot never promises credits, refunds, compensation or exceptions | P0 |
| 3.7 | Answers about something that may vary by plan (hotspot limits, throttle speed, rollover) say "this depends on your plan" and point to where the customer can check | P0 |

### FR-4 Confidence & "I don't know"
| ID | Requirement | Priority |
|---|---|---|
| 4.1 | Compute an answer-confidence score from retrieval relevance and a grounding/faithfulness check | P0 |
| 4.2 | Below the threshold, the bot doesn't guess. It says it isn't sure, shows the closest related help articles if any, and offers a human | P0 |
| 4.3 | Thresholds are configurable by ops per theme (e.g. a stricter threshold for billing) | P1 |
| 4.4 | Every unanswered or low-confidence question is logged to a **content-gap queue** for ops | P0 |

### FR-5 Personal-account boundary (no live billing/CRM in v1)
**Decision:** the bot recognizes account-specific questions and handles them in three steps: **(1) say clearly what it can't see, (2) answer the general version of the question, (3) point to the self-serve tool or a human.**

| ID | Requirement | Priority |
|---|---|---|
| 5.1 | Detect account-specific intent ("my balance", "my bill", "why was I charged", "is my roaming on") | P0 |
| 5.2 | Reply using the pattern above. Example: *"I can't see your account details from this chat. Bills usually go up because of roaming, premium SMS, add-on packs or a mid-cycle plan change. You can see every charge in MyTelecom > Billing > Itemised Bill. Want me to connect you to an agent to review it?"* | P0 |
| 5.3 | Deep links to the right self-serve screen (My Usage, Itemised Bill, Roaming toggle, Request Unlock) and USSD codes (*123#) | P1 |
| 5.4 | The bot **never asks for** and discourages sharing passwords, full card numbers, date of birth, PINs/PUKs or SIM serial numbers in chat. If the customer shares them anyway, they are masked in logs and transcripts | P0 |

### FR-6 Escalation & handoff
**Escalation triggers** (any one is enough):

| Trigger | Example |
|---|---|
| Customer asks for a human | "agent", "talk to a person" |
| Low confidence (FR-4) or two "I don't know" replies in a row | — |
| Account-specific or transactional need the customer wants to pursue | refund, plan change, bill dispute |
| **Safety, fraud or security signals: escalate immediately, no troubleshooting** | unauthorized plan change, suspected SIM swap, account takeover, lost or stolen phone, harassment |
| The resolution needs an agent or network action | re-provisioning, call barring, a new eSIM code, network investigation after all self-help steps fail |
| Frustration detected, or the conversation goes in circles | negative sentiment, same question 3+ times, 2 thumbs-downs |
| Complaint or regulatory language | "complaint", "ombudsman", "cancel my contract" |
| Emergency | Tell the customer to call emergency services right away. The bot does not troubleshoot |

| ID | Requirement | Priority |
|---|---|---|
| 6.1 | Hand off to the existing live-chat queue when it's open (8am–10pm per the FAQ). Otherwise offer a callback or create a ticket, and give a realistic expected response time | P0 |
| 6.2 | Handoff package: full transcript, detected theme and intent, steps the bot already suggested, citations used, confidence scores, and the reason for escalation | P0 |
| 6.3 | Route by theme and reason. Fraud/security → the fraud team queue | P1 |
| 6.4 | Before handing off for troubleshooting issues, offer the relevant self-help steps once (e.g. the network troubleshooting flow). Never block a customer who asks for a human | P0 |
| 6.5 | Always visible "Talk to a person" button | P0 |

### FR-7 Conversation experience
| ID | Requirement | Priority |
|---|---|---|
| 7.1 | Opening message explains what the bot can do, shows **an AI disclosure**, notes it can't see account details, and offers suggested topic chips | P0 |
| 7.2 | Answers stream token by token. Show a typing indicator | P1 |
| 7.3 | Thumbs up/down on each answer, plus a "Did this solve your issue?" question at the end of the conversation | P0 |
| 7.4 | Customers can download or email their transcript | P2 |
| 7.5 | Accessibility: WCAG 2.1 AA (screen reader, keyboard navigation, contrast) | P0 |

### FR-8 Analytics & ops dashboard
| ID | Requirement | Priority |
|---|---|---|
| 8.1 | Dashboard: conversations, containment, escalation reasons, CSAT, top intents, content-gap queue, most-cited and never-cited sources | P0 |
| 8.2 | Sampled conversation review with a QA labeling tool (correct / incorrect / ungrounded / unsafe) | P0 |
| 8.3 | Offline evaluation harness: a "golden set" of 300+ real questions with expected answers and sources, run on every content or model change | P0 |

### FR-9 Guardrails
| ID | Requirement | Priority |
|---|---|---|
| 9.1 | Prompt-injection and jailbreak defense: ignore instructions inside user input or retrieved content, and never reveal system prompts or internal content | P0 |
| 9.2 | Topic guardrail: politely decline unrelated requests (general chit-chat, competitor comparisons, legal or medical advice) | P0 |
| 9.3 | Toxicity and abuse filtering on both input and output | P0 |

---

## 5. Non-Functional Requirements

| Area | Requirement |
|---|---|
| **Accuracy** | ≥ **95%** of answered questions judged correct and fully grounded on the golden set and on weekly human-reviewed samples. **0** invented prices, fees or policy statements in the launch-gate sample (any one found blocks launch). Faithfulness score ≥ 0.9 from automated eval |
| **Answer-or-abstain** | On out-of-scope or unanswerable test questions, the bot correctly declines or escalates ≥ **95%** of the time |
| **Latency** | First token ≤ **1.5 s** (p50), ≤ **3 s** (p95). Full answer ≤ **6 s** (p95) |
| **Availability** | **99.9%** monthly. If the model or retrieval fails, show a message and offer the human or FAQ path. Never fail silently |
| **Scalability** | Handle peak load at roughly 10% of subscribers per month using chat (~400K conversations/month), with ≥ 3× headroom for outage spikes |
| **Content freshness** | Published content is live in the bot within **15 minutes**. Retired content stops being used within 15 minutes |
| **Privacy** | No account data in v1. PII redaction on ingest (tickets) and in conversation logs. Transcripts kept ≤ 90 days (Legal to confirm). The LLM provider has zero data retention and does not train on NovaCell data. Data stays in approved regions. Complies with applicable data protection law (e.g. GDPR-equivalent) |
| **Security** | Encryption in transit and at rest. Role-based access for the admin console. Audit log of all content changes. Pen test and a prompt-injection red-team exercise before launch |
| **Cost** | Target **≤ $0.05 per conversation** in model and infrastructure cost (vs. an assumed **$4–8** per assisted contact). Use a smaller model for classification and routing, cache common question/answer pairs, and set a monthly budget alert |
| **Explainability** | Every answer can be traced to the exact source chunks, model version, prompt version and content version, for audit and disputes |
| **Accessibility** | WCAG 2.1 AA |

---

## 6. Success Metrics

### North-star
**Tier-1 contained resolution rate:** the share of bot conversations that end resolved (customer confirms, or doesn't contact NovaCell again on the same topic within 7 days) with no human handoff.

### Primary KPIs (measured at 90 days post-launch)
| Metric | Definition | Target |
|---|---|---|
| Contained resolution | See north-star | ≥ **40%** at launch, ≥ **55%** by day 90 |
| Tier-1 contact deflection | Drop in 611 calls and live-chat volume for the six themes vs. a matched control group | ≥ **20%** |
| Answer accuracy | Human-reviewed share of answers that are correct and grounded | ≥ **95%** |
| Hallucination rate | Share of answers with any unsupported claim | ≤ **1%**, and **0** for prices or policies |
| Bot CSAT | Post-chat survey | ≥ **4.0 / 5** |

### Secondary & guardrail metrics
| Metric | Why it matters | Target / guardrail |
|---|---|---|
| Escalation rate (and breakdown by reason) | Shows where content or capability is missing | Watch trend; no hard target |
| Appropriate escalation | Safety/fraud cases routed to a human | **100%** |
| Repeat contact within 7 days | Catches "false containment" | No higher than the live-channel baseline |
| Agent handle time on escalated chats | Shows whether the handoff context helps | **−15%** vs. non-bot chats |
| Overall support CSAT / NPS | Make sure the bot doesn't hurt the overall experience | No drop |
| Content-gap closure time | Shows ops can keep up | Median ≤ 5 business days |
| Cost per resolved conversation | Business case | ≤ $0.10 |

### Launch gates (must pass before going to 100% of users)
1. Golden-set accuracy ≥ 95% and zero invented prices or policies
2. Red-team pass for prompt injection, PII leakage and leakage of internal-only content
3. Escalation works end to end in every live-chat schedule scenario
4. Legal/Privacy sign-off

### Rollout plan
Internal dogfood (agents) → 5% of app users (A/B against the current help center) → 25% → 100% app → web. Each step needs 2 weeks of stable guardrail metrics.

---

## 7. Risks, Assumptions & Open Questions

### Risks
| Risk | Impact | Mitigation |
|---|---|---|
| **Hallucinated prices, policies or promises** | Bill disputes, regulatory exposure, loss of trust | Grounding-only generation, exact-match number check (FR-3.2), confidence threshold, never promise credits |
| **Conflicting sources.** Already present in the current data: (a) FAQ says plan upgrades "take effect at the start of your next billing cycle", but Guide §7 says mid-cycle upgrades are charged pro-rata from the change date. (b) FAQ says turn roaming on "at least 24 hours before travel", but Guide §4 says network activation takes up to 15 minutes. (c) FAQ gives one throttle speed (512 kbps), but the guide says 512 kbps standard / 1 Mbps premium | Inconsistent or wrong answers | Content clean-up sprint before launch, source priority rules (FR-1.8), conflict detection (FR-1.7), a named content owner per topic |
| **Exposing internal-only content.** The PDF guide is marked "Internal Use Only" and includes fraud procedures and identity-verification rules | Security and fraud exposure (e.g. helps social engineering) | Audience tagging, a customer-safe rewrite pass, exclude the fraud and verification sections, red-team testing |
| **PII in tickets** | Privacy breach | Redaction before indexing, only reviewed resolution patterns indexed, access controls |
| **Tickets describe agent-only fixes** (re-provisioning, HLR changes, goodwill credits) | Bot tells customers to do things they can't, or implies entitlement to credits | FR-3.5 / 3.6; consider turning tickets into curated "symptom → self-help → escalate" patterns rather than indexing raw tickets |
| **Brand and data inconsistencies.** Sources say "MyTelecom", "telecom.example.com" and "@TelecomSupport", not NovaCell | Confusing or broken links | Clean up and standardize branding before ingest; check links automatically |
| **False containment** (customer gives up rather than getting help) | Inflated metrics, frustrated customers | Measure repeat contact within 7 days, always-visible human option |
| **Thin knowledge base** (25 FAQs, 20 tickets, 1 guide in the sample) | Low coverage and high escalation | Content-gap queue, seed from the top 200 contact reasons, plan ops capacity for content |
| **Fraud and social engineering through the bot** | Account takeover | No account actions in v1, escalate any security signal, rate limiting |
| **Model or provider outage or cost spike** | Poor availability or overspending | Fallback model, cached answers, budget alerts, degrade gracefully to search results |

### Assumptions
- Most Tier-1 contacts can be answered from general (not account-specific) knowledge. **Validate** by sampling 1,000 recent contacts and checking what share needed account data.
- Support ops has, or will get, a named knowledge-management owner with capacity to maintain content (estimate 1–2 FTE).
- The live-chat platform supports API handoff with a transcript attached.
- The MyTelecom app and web can embed the chat widget and support deep links.
- An approved LLM provider is available with zero data retention and acceptable data residency.
- Baseline cost per assisted contact and Tier-1 volume by theme are available from current reporting.

### Open questions
| # | Question | Owner |
|---|---|---|
| 1 | What share of today's contacts are Tier-1, and how are they split by theme? (needed to size the deflection target) | Care Ops / Analytics |
| 2 | Should raw tickets be indexed at all, or only curated patterns derived from them? | Product + Knowledge Mgmt |
| 3 | Which version wins on the upgrade-timing and roaming-lead-time conflicts? Who is the policy owner? | Product Marketing / Billing |
| 4 | Can a customer-facing version of the technical guide be produced, or must we filter the internal one? | Knowledge Mgmt / Security |
| 5 | What should the bot do outside live-chat hours: callback, ticket, or both? What SLA? | Care Ops |
| 6 | Must the bot be offered to logged-out web visitors, or only logged-in app users? | Digital |
| 7 | Transcript retention period and consent wording? Any regulator requirements for AI disclosure? | Legal / Privacy |
| 8 | Does the target cover prepaid and postpaid equally, given their different billing models? | Product |
| 9 | Which second language comes first in v2, and how much demand is there? | Care Ops |

---

## 8. Future Iterations (v2+)

| Phase | Capability | Value |
|---|---|---|
| **v2: Personalized answers** | Authenticated chat with read-only CRM/billing access: balance, current bill breakdown, plan details, roaming status, outage status by location | Answers "my bill / my balance" questions directly, which is likely the biggest remaining deflection opportunity |
| **v2: Agent assist** | The same grounded engine in the agent console: suggested replies, cited answers, summaries of escalated chats | Faster handle time, consistent agent answers, safer use of internal-only content |
| **v2: Multilingual** | Top 1–2 additional languages | Reach and inclusion |
| **v2: Guided diagnostics** | Interactive troubleshooting flows (signal check, APN guide, eSIM wizard) | Higher resolution for data and SIM issues |
| **v3: Safe actions** | Low-risk transactions with step-up authentication: buy a roaming bundle or data pack, turn on Wi-Fi calling, re-send eSIM QR code, request unlock | End-to-end resolution, not just answers |
| **v3: Proactive support** | Before-travel roaming nudges, outage notifications, bill-shock explanations | Prevents contacts before they happen |
| **v3: More channels** | WhatsApp, SMS, IVR/voice bot | Meet customers where they already are |
| **Ongoing: Learning loop** | Automatically draft new FAQ entries from resolved escalations and content gaps, for human approval | Coverage grows with less ops effort |
