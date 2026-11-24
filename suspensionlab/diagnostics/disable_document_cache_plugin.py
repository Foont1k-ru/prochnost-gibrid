"""Opt-in pytest diagnostic: bypass document-cache get/put, not a product setting.

This does not revert the UI changes and cannot prove whether the cache caused a
crash. Use only with scenarios not asserting cache behaviour, in isolated pytest
processes, and compare the same test order and environment.
"""


def pytest_configure() -> None:
    from suspensionlab.core.cad_document_cache import DocumentMeshCache

    def miss(self, key):
        return None

    def dont_store(self, key, mesh):
        pass

    DocumentMeshCache.get = miss
    DocumentMeshCache.put = dont_store
