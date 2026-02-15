from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class PatchTarget:
    target_object: Any
    method_name: str
    original_method: Callable = None
    patched_method: Callable = None

    def apply_patch(self) -> None:
        self.original_method = getattr(
            self.target_object, self.method_name
        )
        setattr(
            self.target_object,
            self.method_name,
            self.patched_method,
        )

    def remove_patch(self) -> None:
        if self.original_method is not None:
            setattr(
                self.target_object,
                self.method_name,
                self.original_method,
            )


class MethodPatcher:
    def __init__(self):
        self.patch_targets: list[PatchTarget] = []

    def register_patch(
        self,
        target_object: Any,
        method_name: str,
        patched_method: Callable,
    ) -> None:
        patch_target = PatchTarget(
            target_object=target_object,
            method_name=method_name,
            patched_method=patched_method,
        )
        self.patch_targets.append(patch_target)

    def apply_all_patches(self) -> None:
        for patch_target in self.patch_targets:
            patch_target.apply_patch()

    def remove_all_patches(self) -> None:
        for patch_target in self.patch_targets:
            patch_target.remove_patch()
        self.patch_targets.clear()

    def get_original_method(
        self, method_name: str
    ) -> Callable:
        for patch_target in self.patch_targets:
            if patch_target.method_name == method_name:
                return patch_target.original_method
        return None
