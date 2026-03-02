"""
Synthetic event generator for demo / testing without external APIs.

Provides deterministic, reproducible event streams for both
ENERGY_GEO and AI_RELEASES domains.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from .base import BaseFeed, EventDomain, NewsEvent

# ---------------------------------------------------------------------------
# Template event pools
# ---------------------------------------------------------------------------

_ENERGY_GEO_TEMPLATES = [
    # (headline, summary, sentiment, importance)
    ("Iran Closes Strait of Hormuz to Tanker Traffic",
     "Tehran announces temporary closure following escalation with US naval forces.",
     -0.9, 0.95),
    ("Houthi Missile Strike Hits Saudi Aramco Facility",
     "Explosion at Ras Tanura refinery disrupts 5% of global crude supply.",
     -0.85, 0.90),
    ("OPEC+ Emergency Meeting Called After Bab el-Mandeb Incident",
     "Unexpected attack on container vessel forces emergency producer summit.",
     -0.7, 0.80),
    ("Egypt Announces Reduced Suez Canal Capacity Due to Drought",
     "Low Nile water levels force draft restrictions on tanker passage.",
     -0.6, 0.75),
    ("Libya Oil Field Returns to Production After Militia Standoff",
     "El Sharara field resumes output following ceasefire agreement.",
     0.5, 0.65),
    ("West Africa Offshore Pipeline Rupture Cuts Output",
     "Sabotage of trans-Niger Delta pipeline takes 80k bpd offline.",
     -0.75, 0.82),
    ("Iran Sanctions Tightened — EU Joins US Measures",
     "Coordinated measures target petroleum exports and shipping insurance.",
     -0.65, 0.78),
    ("Saudi Arabia Raises Official Selling Prices for Asia",
     "Aramco increases OSP for Arab Light by $1.50/bbl signalling demand confidence.",
     0.4, 0.55),
    ("Turkey Threatens to Block Bosphorus for Russian Tankers",
     "Ankara responds to Black Sea incident with transit restriction warning.",
     -0.7, 0.80),
    ("Nigeria Petrol Subsidy Removal Triggers Refinery Investment",
     "Federal government signals $10bn in downstream investment following reform.",
     0.45, 0.60),
    ("Drone Strike Damages Iraq Kirkuk-Ceyhan Pipeline",
     "PKK-linked attack disrupts 300k bpd of Kurdish crude exports.",
     -0.80, 0.88),
    ("Red Sea Shipping Insurance Premiums Triple After New Attack",
     "Lloyd's war risk committee upgrades Bab el-Mandeb corridor to zone 1.",
     -0.65, 0.72),
    ("UAE Confirms New Deep-Water Oil Discovery Off Abu Dhabi",
     "ADNOC reports 5 billion barrel estimated reserve in offshore block 6.",
     0.6, 0.70),
    ("Morocco-Spain Gas Pipeline Reopens After Two-Year Closure",
     "Diplomatic normalisation leads to restart of Maghreb–Europe pipeline.",
     0.55, 0.62),
    ("Algeria Cuts Gas Supply to Spain Amid Political Dispute",
     "Sonatrach citing treaty violations halts LNG deliveries to Enagas.",
     -0.72, 0.78),
]

_AI_RELEASES_TEMPLATES = [
    ("OpenAI Releases GPT-5 — Benchmark Dominance Across All Tasks",
     "New model surpasses human-level performance on MMLU, HumanEval, and MATH benchmarks.",
     0.85, 0.95),
    ("Anthropic Launches Claude 4 with Autonomous Agent Capabilities",
     "Model can execute multi-step code tasks, manage files, and run terminal commands.",
     0.80, 0.90),
    ("Google DeepMind Gemini Ultra 2 Released with Multimodal Reasoning",
     "Achieves state-of-the-art on video understanding and scientific problem-solving.",
     0.75, 0.85),
    ("Meta Open-Sources LLaMA-4 400B Parameter Model",
     "Full model weights, training code, and data released under permissive licence.",
     0.70, 0.80),
    ("OpenAI Launches Operator Agent — Autonomous Web Browsing at Scale",
     "New service allows enterprises to automate complex multi-step web workflows.",
     0.78, 0.88),
    ("Anthropic Security Research: Jailbreak Vector Found in Production Systems",
     "Critical prompt injection vulnerability enables system prompt extraction.",
     -0.65, 0.82),
    ("Microsoft Copilot Deep Integration with Azure DevOps Announced",
     "Full CI/CD pipeline automation via AI agent now generally available.",
     0.60, 0.70),
    ("OpenAI Faces EU Regulatory Action Over Data Processing Practices",
     "European Data Protection Board opens investigation into ChatGPT training data.",
     -0.55, 0.72),
    ("Anthropic Raises $4B Series F at $60B Valuation",
     "Round led by strategic investors; capital earmarked for compute and safety research.",
     0.65, 0.75),
    ("Coding Agent Framework Devin 2.0 Solves Real GitHub Issues Autonomously",
     "Benchmarks show 43% resolution rate on SWE-bench full repository tasks.",
     0.72, 0.80),
    ("OpenAI Infrastructure Outage Affects Millions of API Users",
     "3-hour GPT-4 API disruption triggers SLA credits and customer complaints.",
     -0.50, 0.65),
    ("New AI Chip Architecture from Cerebras Achieves 10x Inference Speedup",
     "CS-3 wafer-scale chip demonstrates industry-leading tokens-per-second at inference.",
     0.65, 0.72),
    ("Mistral AI Releases New Enterprise LLM Optimised for Edge Deployment",
     "7B parameter model fits within 4GB RAM, targets IoT and embedded applications.",
     0.55, 0.65),
    ("China Bans Export of AI Training Datasets Exceeding 100GB",
     "Ministry of Science implements new data sovereignty regulations for AI firms.",
     -0.60, 0.78),
    ("Anthropic Constitutional AI Paper Wins NeurIPS Best Paper Award",
     "Research demonstrates alignment technique generalises across unseen task distributions.",
     0.50, 0.60),
]


class SyntheticFeed(BaseFeed):
    """
    Generates synthetic news events from template pools.

    Parameters
    ----------
    domain: EventDomain
        Which event pool to draw from.
    events_per_poll: int
        How many events to emit per poll call (0–N, with randomness).
    seed: int | None
        Random seed for reproducibility (None = non-deterministic).
    start_time: datetime | None
        Backfill start timestamp; if set, events get sequential timestamps
        spaced by ``time_step`` minutes.
    time_step_minutes: int
        Gap between synthetic events when backfilling.
    """

    def __init__(
        self,
        domain: EventDomain,
        events_per_poll: int = 1,
        seed: Optional[int] = None,
        start_time: Optional[datetime] = None,
        time_step_minutes: int = 30,
        credibility_weight: float = 1.0,
    ):
        name = f"synthetic_{domain.value.lower()}"
        super().__init__(name=name, domain=domain, credibility_weight=credibility_weight)
        self._rng = random.Random(seed)
        self._events_per_poll = events_per_poll
        self._time_step = timedelta(minutes=time_step_minutes)
        self._cursor = start_time or datetime.now(timezone.utc)
        templates = (
            _ENERGY_GEO_TEMPLATES if domain == EventDomain.ENERGY_GEO
            else _AI_RELEASES_TEMPLATES
        )
        self._templates = templates

    async def poll(self) -> list[NewsEvent]:
        n = self._rng.randint(0, self._events_per_poll)
        events: list[NewsEvent] = []
        for _ in range(n):
            tmpl = self._rng.choice(self._templates)
            ev = self._make_event(tmpl)
            if self._is_new(ev.event_id):
                events.append(ev)
            self._cursor += self._time_step
        return events

    def generate_batch(self, count: int) -> list[NewsEvent]:
        """Generate exactly *count* events (no dedup check). For backtest seeding."""
        events: list[NewsEvent] = []
        for i in range(count):
            tmpl = self._templates[i % len(self._templates)]
            ev = self._make_event(tmpl, suffix=str(i))
            events.append(ev)
            self._cursor += self._time_step
        return events

    def _make_event(self, tmpl: tuple, suffix: str = "") -> NewsEvent:
        headline, summary, sentiment, importance = tmpl
        if suffix:
            headline = f"{headline} [{suffix}]"
        url = f"https://synthetic.ndbot/{self.domain.value.lower()}/{abs(hash(headline))}"
        event_id = NewsEvent.make_id(self.name, url, headline)
        return NewsEvent(
            event_id=event_id,
            domain=self.domain,
            headline=headline,
            summary=summary,
            source=self.name,
            url=url,
            published_at=self._cursor,
            credibility_weight=self.credibility_weight,
            sentiment_score=sentiment + self._rng.uniform(-0.05, 0.05),
            importance_score=min(1.0, max(0.0, importance + self._rng.uniform(-0.05, 0.05))),
        )
