"""
Shared loading helper -- every lerobot policy type (ACT, SmolVLA, XVLA,
pi0, ...) follows the same load pattern: PolicyClass.from_pretrained(path)
then make_pre_post_processors(policy.config, path). Each policy_loaders/*.py
file just supplies the right PolicyClass to this helper.
"""
import torch
from lerobot.policies.factory import make_pre_post_processors


def load_policy(policy_cls, policy_path, device=None):
    device = device or torch.device(
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    policy = policy_cls.from_pretrained(policy_path).to(device).eval()
    preprocess, postprocess = make_pre_post_processors(
        policy.config,
        policy_path,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )
    return policy, preprocess, postprocess, device