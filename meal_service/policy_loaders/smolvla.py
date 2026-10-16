from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
import policy_common

def load(policy_path):
    return policy_common.load_policy(SmolVLAPolicy, policy_path)
