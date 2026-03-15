"""
ndbot — News-Driven Intraday Trading Research Framework
========================================================
A production-grade, event-driven systematic trading framework
designed for research on geopolitical and AI-release events.

Execution modes:
  simulate  — fictional capital, no real orders
  backtest  — replay historical events + candles
  paper     — CCXT sandbox / testnet (DRY_RUN default)

Domains:
  ENERGY_GEO  — Africa/Middle East chokepoints, sanctions, pipeline events
  AI_RELEASES — OpenAI, Anthropic, major AI lab announcements
"""

__version__ = "0.2.0"
__author__ = "ndbot contributors"
