"""Shared, harness-neutral EKG contracts."""

from .models import (
    BuildSpec,
    Capability,
    DeploymentDescriptor,
    Event,
    Ontology,
    OntologyMode,
    Operation,
    Plan,
    ProvisioningSpec,
    Target,
)



def package_version() -> str:
    """The installed distribution's version, or "checkout" when run from source."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("ekg-skills-local")
    except PackageNotFoundError:
        return "checkout"


__all__ = [
    "BuildSpec", "Capability", "DeploymentDescriptor", "Event", "Ontology",
    "OntologyMode", "Operation", "Plan",
    "ProvisioningSpec", "Target", "package_version",
]
