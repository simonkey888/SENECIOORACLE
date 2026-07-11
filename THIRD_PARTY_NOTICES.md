# Third-party design references

## virattt/ai-hedge-fund v2

- Source: https://github.com/virattt/ai-hedge-fund/tree/main/v2
- License: MIT
- Use in SENECIO: architectural inspiration for separating alpha views from
  portfolio/execution decisions and for point-in-time signal contracts.
- SENECIO's `engine_contracts.py` is an original prediction-market adaptation;
  no stock strategy, LLM persona, or backtesting implementation is imported.
