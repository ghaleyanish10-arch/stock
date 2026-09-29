"""NEPSE integration package.

Layering (outer depends on inner, never the reverse):

    routes -> service -> client (adapter) -> `nepse` package
"""
