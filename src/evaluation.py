def evaluate_evidence(evidence):
    if not evidence:
        return {
            "recommendation": "Unverified",
            "signals": [],
            "conflict": False,
        }

    statuses = {item[5] for item in evidence}

    if "Verified" in statuses and "Failed" in statuses:
        return {
            "recommendation": "At risk",
            "signals": sorted(statuses),
            "conflict": True,
        }

    if "Failed" in statuses:
        recommendation = "Failed"
    elif "Verified" in statuses:
        recommendation = "Verified"
    elif "At risk" in statuses:
        recommendation = "At risk"
    else:
        recommendation = "Unverified"

    return {
        "recommendation": recommendation,
        "signals": sorted(statuses),
        "conflict": False,
    }
