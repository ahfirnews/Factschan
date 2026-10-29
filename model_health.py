#!/usr/bin/env python3
"""Non-billable catalog check used by the scheduled health workflow."""

import json

from ai_generator import catalog_health
from prompt_reserve import seed, stats


if __name__ == "__main__":
    seed()
    print(json.dumps({"providers": catalog_health(), "reserve": stats()}, indent=2, sort_keys=True))
