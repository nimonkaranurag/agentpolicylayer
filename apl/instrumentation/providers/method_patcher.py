"""
Idempotent, transactional monkeypatching of SDK methods.

Patching third-party SDK methods is the most fragile thing instrumentation does, so the
mechanics are kept honest here (ENGINEERING_REVIEW §3.8):

- **Idempotent** — a method is patched at most once. A second :meth:`apply_patch` (e.g. a
  second ``auto_instrument``) sees the ``__apl_patched__`` marker and refuses to capture
  the *wrapper* as if it were the original, which used to permanently lose the real method.
- **Closure-captured original** — the wrapper is built from a ``wrapper_factory`` that
  receives the captured original, so a wrapper never resolves its original by index into a
  shared list (which coupled correctness to registration order).
- **Transactional** — :meth:`MethodPatcher.apply_all_patches` rolls back everything it
  installed if any single patch fails, so a partial apply never leaks half-patched SDKs.
- **Authoritative removal** — a target only restores the original it actually installed, so
  ``uninstrument`` is correct even when several instrumentations coexist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

# Marks a callable as an APL wrapper. ``functools.wraps`` also sets ``__wrapped__`` to the
# original, so the genuine method is always recoverable from a wrapper.
APL_PATCH_MARKER = "__apl_patched__"

WrapperFactory = Callable[[Callable], Callable]


@dataclass
class PatchTarget:
    """
    One ``target_object.method_name`` to patch, and how to build its wrapper.
    """

    target_object: Any
    method_name: str
    wrapper_factory: WrapperFactory
    original_method: Optional[Callable] = None
    applied: bool = False

    def apply_patch(self) -> None:
        """
        Install the wrapper, capturing the real original by closure.

        Idempotent: if the attribute is already an APL wrapper, record the underlying
        original (so removal still works) but install nothing and mark this target as not
        having applied a patch — there is nothing of ours to roll back or remove.
        """
        current: Callable = getattr(self.target_object, self.method_name)

        if getattr(current, APL_PATCH_MARKER, False):
            self.original_method = getattr(current, "__wrapped__", current)
            self.applied = False
            return

        self.original_method = current
        patched: Callable = self.wrapper_factory(current)
        setattr(patched, APL_PATCH_MARKER, True)
        setattr(self.target_object, self.method_name, patched)
        self.applied = True

    def remove_patch(self) -> None:
        """
        Restore the original, but only if this target actually installed a patch.
        """
        if self.applied and self.original_method is not None:
            setattr(self.target_object, self.method_name, self.original_method)
            self.applied = False


class MethodPatcher:
    def __init__(self) -> None:
        self.patch_targets: List[PatchTarget] = []

    def register_patch(
        self,
        target_object: Any,
        method_name: str,
        wrapper_factory: WrapperFactory,
    ) -> None:
        """
        Register a method to patch.

        ``wrapper_factory`` is called with the captured original at apply time and must
        return the replacement callable — the original is reached by closure, never by
        index.
        """
        self.patch_targets.append(
            PatchTarget(
                target_object=target_object,
                method_name=method_name,
                wrapper_factory=wrapper_factory,
            )
        )

    def apply_all_patches(self) -> None:
        """
        Apply every registered patch transactionally.

        If any patch raises, roll back the ones already installed (LIFO) and re-raise,
        so the SDKs are never left half-patched.
        """
        installed: List[PatchTarget] = []
        try:
            for target in self.patch_targets:
                target.apply_patch()
                if target.applied:
                    installed.append(target)
        except Exception:
            for target in reversed(installed):
                target.remove_patch()
            raise

    def remove_all_patches(self) -> None:
        """
        Restore all originals (LIFO) and forget the registrations.
        """
        for target in reversed(self.patch_targets):
            target.remove_patch()
        self.patch_targets.clear()
