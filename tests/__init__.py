"""SupportDesk test package.

Makes ``tests`` a regular package so ``from tests.conftest import ...``
resolves regardless of how pytest is invoked (``python -m pytest`` puts the
cwd on sys.path; the bare ``pytest`` console script used by CI does not).
"""
