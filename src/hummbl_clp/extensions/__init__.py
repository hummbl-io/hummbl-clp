"""CLP extensions -- modules with pluggable backends for host-specific integration.

Extensions may depend on external services (Ollama, Open Brain server, AgentHub)
or host-specific infrastructure (coordination bus, MEMORY.md paths). They import
from hummbl_clp.core but never the reverse.
"""
