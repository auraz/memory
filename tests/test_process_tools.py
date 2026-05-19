import asyncio

import pytest

from app.tools import processes


def test_run_pkill_rejects_unknown_target():
    with pytest.raises(ValueError, match="Unknown pkill target"):
        asyncio.run(processes.run_pkill("python"))
