"""Print a summary of the demo analysis: ``python -m backend.network``."""

from backend.network import DEMO_CASE_ID, get_network_clusters, get_network_module_result


def main() -> None:
    for cluster in get_network_clusters(DEMO_CASE_ID):
        state = "flagged" if cluster["flagged"] else "not flagged"
        print(
            f"{cluster['id']}: {cluster['size']} accounts, score {cluster['coordination_risk_score']:.2f}, "
            f"risk {cluster['risk_level']}, {state}"
        )
    for line in get_network_module_result(DEMO_CASE_ID)["evidence"]:
        print(f"- {line}")


if __name__ == "__main__":
    main()
