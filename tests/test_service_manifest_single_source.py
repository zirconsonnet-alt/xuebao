from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import SERVICE_CLASS_IMPORTS, iter_internal_service_modules
from src.services import registry
from src.services.vendor_registry import iter_vendor_owner_modules


def test_registry_and_loader_share_single_service_manifest() -> None:
    assert registry._SERVICE_CLASS_IMPORTS is SERVICE_CLASS_IMPORTS
    service_modules = {module_path for module_path, _ in SERVICE_CLASS_IMPORTS.values()}
    owner_modules = set(iter_vendor_owner_modules())
    assert set(iter_internal_service_modules()) == service_modules | owner_modules
