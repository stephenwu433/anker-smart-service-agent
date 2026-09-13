"""最小 sandbox 实验：调用 application 的 health handler。"""

from smart_service_agent.main import health_check


def main() -> None:
    print(health_check())


if __name__ == "__main__":
    main()
