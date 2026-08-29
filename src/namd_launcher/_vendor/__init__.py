"""Vendored fallbacks used only when ``interfaceforge`` is not importable.

Each module here is a faithful, minimal copy of the corresponding
InterfaceForge implementation so ``namdforge`` behaves identically whether or
not InterfaceForge is installed alongside it. ``namd_launcher._compat``
prefers the real InterfaceForge functions and falls back to these.
"""
