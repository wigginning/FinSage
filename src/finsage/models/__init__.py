"""核心域模型（§3/§4 —— FROZEN）。

按模块承载：sources（§4.1-4.3）、claims（§4.4/4.8）、entities、planning。
FinancialMetric/Quote 见 providers.finance.domain（§4.6/4.7）；
Calculation 见 financial.models（§4.5）。
"""
from __future__ import annotations

from .sources import Evidence, SourceRef

__all__ = ["Evidence", "SourceRef"]