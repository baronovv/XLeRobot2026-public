from lerobot.policies.act.modeling_act import ACTPolicy
import policy_common

def load(policy_path):
    return policy_common.load_policy(ACTPolicy, policy_path)
