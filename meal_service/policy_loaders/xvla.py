# policy_loaders/xvla.py
from lerobot.policies.xvla.modeling_xvla import XVLAPolicy
import policy_common

def load(policy_path):
    return policy_common.load_policy(XVLAPolicy, policy_path)