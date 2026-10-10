"""Stable selection with coverage inside each priority tier."""
from collections import Counter

PLANNING_VERSION='daily-v1'


def select_candidates(candidates, limit):
    selected=[]; counts=Counter()
    for due in (True,False):
        tier=sorted((c for c in candidates if (c.due_at is not None)==due),
            key=lambda c:(c.due_at if due else c.created_at,c.mistake_id))
        remaining=[]
        for item in tier:
            if len(selected)>=limit:
                return selected
            if counts[item.group_id]<2:
                selected.append(item); counts[item.group_id]+=1
            else:
                remaining.append(item)
        for item in remaining:
            if len(selected)>=limit:
                return selected
            selected.append(item); counts[item.group_id]+=1
    return selected
