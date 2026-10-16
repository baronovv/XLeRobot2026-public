# policy_loaders/pi0.py
from lerobot.policies.pi0.modeling_pi0 import PI0Policy
import policy_common

def load(policy_path):
    return policy_common.load_policy(PI0Policy, policy_path)