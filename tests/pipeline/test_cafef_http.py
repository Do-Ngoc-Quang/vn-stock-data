from datetime import date
from unittest import mock

import pytest

from pipeline.providers import cafef_provider
from pipeline.errors import TransientProviderError


def test_connection_reset_is_transient():
    with mock.patch.object(cafef_provider.urllib.request, "urlopen", side_effect=ConnectionResetError(104, "reset")):
        with pytest.raises(TransientProviderError):
            cafef_provider._http_page("FPT", date(2026, 1, 1), date(2026, 2, 1), 1, "HOSE")
