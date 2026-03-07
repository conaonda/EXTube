from src.reconstruction.reconstruction import (
    ColmapRetryConfig,
    ReconstructionResult,
    exhaustive_matcher,
    export_to_ply,
    feature_extractor,
    image_undistorter,
    is_colmap_retryable_error,
    patch_match_stereo,
    reconstruct,
    sparse_reconstructor,
    stereo_fusion,
)

__all__ = [
    "ColmapRetryConfig",
    "ReconstructionResult",
    "exhaustive_matcher",
    "export_to_ply",
    "feature_extractor",
    "image_undistorter",
    "is_colmap_retryable_error",
    "patch_match_stereo",
    "reconstruct",
    "sparse_reconstructor",
    "stereo_fusion",
]


def __getattr__(name: str):
    """Lazy import for gaussian_splatting symbols (requires nerfstudio)."""
    _gs_names = {
        "GaussianSplattingResult",
        "convert_colmap_to_nerfstudio",
        "detect_vram_gb",
        "run_gaussian_splatting",
        "select_vram_preset",
        "train_gaussian_splatting",
    }
    if name in _gs_names:
        from src.reconstruction import gaussian_splatting as _gs

        return getattr(_gs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
